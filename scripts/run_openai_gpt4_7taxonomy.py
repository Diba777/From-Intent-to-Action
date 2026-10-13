import argparse
import datetime
import json
import os
import re
import sys
import time
from openai import OpenAI


VALID_ACTIONS = {
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
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def read_text(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def normalize_action(action):
    if not action:
        return None
    action = str(action).strip().upper().replace(" ", "_").replace("-", "_")
    return action if action in VALID_ACTIONS else None


def extract_json(text):
    if not text:
        return None

    text = text.strip()

    try:
        return json.loads(text)
    except Exception:
        pass

    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fenced:
        try:
            return json.loads(fenced.group(1))
        except Exception:
            pass

    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except Exception:
            pass

    return None


def extract_action_field(raw):
    if not raw:
        return None
    match = ACTION_FIELD.search(raw)
    return normalize_action(match.group(1)) if match else None


def build_user_prompt(scenario):
    scenario_for_model = {
        "id": scenario.get("id"),
        "command": scenario.get("command"),
        "speaker_role": scenario.get("speaker_role"),
        "auth_status": scenario.get("auth_status"),
        "vehicle_state": scenario.get("vehicle_state"),
        "available_tools": scenario.get("available_tools"),
    }

    return (
        "Evaluate the following vehicle voice-command scenario.\n"
        "Apply the supplied authorization policy and return only its required "
        "JSON object.\n\n"
        + json.dumps(scenario_for_model, indent=2)
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--benchmark",
        default="benchmark/vehicle_safety_benchmark_v2_clean.jsonl",
    )
    parser.add_argument(
        "--prompt",
        default="prompts/structured_authorization_policy.txt",
    )
    parser.add_argument("--model", default="gpt-4o")
    parser.add_argument("--output", default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--sleep", type=float, default=0.0)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--max_tokens", type=int, default=256)
    args = parser.parse_args()

    if not os.getenv("OPENAI_API_KEY"):
        print("OPENAI_API_KEY is not set.", file=sys.stderr)
        sys.exit(1)

    benchmark = load_jsonl(args.benchmark)
    system_prompt = read_text(args.prompt)

    if args.limit:
        benchmark = benchmark[:args.limit]

    safe_model_name = args.model.replace(":", "_").replace("/", "_")
    prompt_name = os.path.splitext(os.path.basename(args.prompt))[0]

    if args.output is None:
        args.output = f"outputs_{safe_model_name}_{prompt_name}.jsonl"
    output_path = os.path.abspath(args.output)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    client = OpenAI()

    print(f"Model: {args.model}")
    print(f"Prompt: {args.prompt}")
    print(f"Scenarios: {len(benchmark)}")
    print(f"Output: {args.output}")

    with open(args.output, "w", encoding="utf-8") as out:
        for i, scenario in enumerate(benchmark, start=1):
            raw = ""
            parsed = None
            action = None

            try:
                response = client.chat.completions.create(
                    model=args.model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": build_user_prompt(scenario)},
                    ],
                    temperature=args.temperature,
                    max_tokens=args.max_tokens,
                )

                raw = response.choices[0].message.content
                parsed = extract_json(raw)

                if isinstance(parsed, dict):
                    action = normalize_action(parsed.get("action"))

                if action is None:
                    action = extract_action_field(raw)

            except Exception as e:
                raw = str(e)
                print(f"[{i}/{len(benchmark)}] ERROR {scenario.get('id')}: {e}")

            print(f"[{i}/{len(benchmark)}] {scenario.get('id')} -> {action}")

            row = {
                "id": scenario.get("id"),
                "model": args.model,
                "prompt_file": args.prompt,
                "benchmark_file": args.benchmark,
                "generated_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "temperature": args.temperature,
                "max_tokens": args.max_tokens,
                "predicted_action": action,
                "raw_response": raw,
                "model_output": parsed,
            }

            out.write(json.dumps(row, ensure_ascii=False) + "\n")
            out.flush()

            if args.sleep > 0:
                time.sleep(args.sleep)

    print(f"Saved: {args.output}")


if __name__ == "__main__":
    main()
