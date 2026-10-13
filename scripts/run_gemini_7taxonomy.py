import argparse
import datetime
import json
import os
import re
import time
from pathlib import Path
from google import genai
from google.genai import types

LABELS = {
    "EXECUTE",
    "REFUSE",
    "CLARIFY",
    "REQUIRE_CONFIRMATION",
    "REQUIRE_MANUAL_CONTROL",
    "EMERGENCY_RESPONSE",
    "NO_TOOL_CALL",
}
ACTION_FIELD = re.compile(
    r"""["']action["']\s*:\s*["']([A-Za-z_ -]+)["']""",
    re.IGNORECASE,
)

def load_jsonl(path):
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return rows

def build_prompt(policy_text, scenario):
    scenario_view = {
        "id": scenario["id"],
        "command": scenario["command"],
        "speaker_role": scenario["speaker_role"],
        "auth_status": scenario["auth_status"],
        "vehicle_state": scenario["vehicle_state"],
        "available_tools": scenario["available_tools"],
    }

    return f"""{policy_text}

SCENARIO:
{json.dumps(scenario_view, indent=2)}

Return only one JSON object.
Apply the supplied authorization policy and use its required JSON interface.
"""

def normalize_action(action):
    action = str(action or "INVALID").strip().upper()
    action = action.replace(" ", "_").replace("-", "_")
    return action if action in LABELS else "INVALID"

def extract_json(text):
    text = (text or "").strip()

    # Remove markdown fences if the model uses them anyway.
    if text.startswith("```"):
        text = (
            text.replace("```json", "")
                .replace("```JSON", "")
                .replace("```", "")
                .strip()
        )

    # Try direct JSON parse.
    try:
        return json.loads(text)
    except Exception:
        pass

    # Try extracting the first JSON-looking object.
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except Exception:
            pass

    return None

def extract_action_field(text):
    match = ACTION_FIELD.search(text or "")
    return normalize_action(match.group(1)) if match else "INVALID"


def call_gemini_with_retries(
    client,
    model,
    prompt,
    temperature=0.0,
    max_output_tokens=256,
    max_retries=5,
):
    last_error = None

    for attempt in range(max_retries):
        try:
            response = client.models.generate_content(
                model=model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=temperature,
                    max_output_tokens=max_output_tokens,
                ),
            )
            return response
        except Exception as e:
            last_error = e
            wait = 5 * (attempt + 1)
            print(f"API error on attempt {attempt + 1}/{max_retries}: {e}")
            print(f"Waiting {wait} seconds before retrying...")
            time.sleep(wait)

    raise last_error

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="gemini-flash-latest")
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--benchmark", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--sleep", type=float, default=2.0)
    parser.add_argument("--max_retries", type=int, default=5)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--max_tokens", type=int, default=256)
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume an interrupted file. Without this flag, output is overwritten.",
    )
    args = parser.parse_args()

    if not os.environ.get("GEMINI_API_KEY"):
        raise RuntimeError("GEMINI_API_KEY is not set.")

    with open(args.prompt, "r", encoding="utf-8") as f:
        policy_text = f.read()

    scenarios = load_jsonl(args.benchmark)
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    done_ids = set()
    if args.resume and output_path.exists():
        with open(args.output, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    try:
                        scenario_id = json.loads(line)["id"]
                        if scenario_id in done_ids:
                            raise ValueError(
                                f"duplicate scenario ID in resume file: {scenario_id}"
                            )
                        done_ids.add(scenario_id)
                    except Exception:
                        raise ValueError(
                            "resume file contains malformed or duplicate records"
                        )

    mode = "a" if args.resume else "w"
    with open(args.output, mode, encoding="utf-8") as out:
        for i, scenario in enumerate(scenarios, start=1):
            sid = scenario["id"]

            if sid in done_ids:
                continue

            prompt = build_prompt(policy_text, scenario)

            try:
                response = call_gemini_with_retries(
                    client=client,
                    model=args.model,
                    prompt=prompt,
                    temperature=args.temperature,
                    max_output_tokens=args.max_tokens,
                    max_retries=args.max_retries,
                )

                raw = response.text or ""
                parsed = extract_json(raw)

                if isinstance(parsed, dict):
                    action = normalize_action(parsed.get("action", "INVALID"))
                    model_output = {
                        "action": action,
                        "tool_call": parsed.get("tool_call", None),
                        "rationale": parsed.get("rationale", ""),
                    }
                else:
                    action = extract_action_field(raw)
                    model_output = {
                        "action": action,
                        "tool_call": None,
                        "rationale": "action field recovered from malformed response"
                        if action != "INVALID"
                        else "parse failure",
                    }

                row = {
                    "id": sid,
                    "model": args.model,
                    "prompt_file": args.prompt,
                    "benchmark_file": args.benchmark,
                    "generated_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    "temperature": args.temperature,
                    "max_tokens": args.max_tokens,
                    "resolved_model_version": getattr(response, "model_version", None),
                    "model_output": model_output,
                    "raw_response": raw,
                    "predicted_action": action,
                }

            except Exception as e:
                row = {
                    "id": sid,
                    "model": args.model,
                    "prompt_file": args.prompt,
                    "benchmark_file": args.benchmark,
                    "generated_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    "temperature": args.temperature,
                    "max_tokens": args.max_tokens,
                    "resolved_model_version": None,
                    "model_output": {
                        "action": "INVALID",
                        "tool_call": None,
                        "rationale": str(e),
                    },
                    "raw_response": "",
                    "predicted_action": "INVALID",
                }

            out.write(json.dumps(row) + "\n")
            out.flush()

            print(f"[{i}/{len(scenarios)}] {sid} -> {row['predicted_action']}")
            time.sleep(args.sleep)

if __name__ == "__main__":
    main()
