import argparse
import datetime
import json
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

OLLAMA_URL = "http://localhost:11434/api/generate"
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
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def read_text(path):
    with open(path, encoding="utf-8") as f:
        return f.read().strip()


def call_ollama(
    model,
    prompt,
    temperature=0.0,
    max_tokens=256,
    timeout=180,
):
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": temperature,
            "num_predict": max_tokens,
        }
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        OLLAMA_URL,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        out = json.loads(resp.read().decode("utf-8"))
    return out


def parse_json_object(text):
    text = text.strip()
    try:
        return json.loads(text)
    except Exception:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start:end+1])
        except Exception:
            return None
    return None


def normalize_action(value):
    value = str(value or "").strip().upper().replace("-", "_").replace(" ", "_")
    return value if value in VALID_ACTIONS else None


def extract_action_field(text):
    match = ACTION_FIELD.search(text or "")
    return normalize_action(match.group(1)) if match else None


def build_prompt(system_prompt, scenario):
    scenario_for_model = {
        "id": scenario.get("id"),
        "command": scenario.get("command"),
        "speaker_role": scenario.get("speaker_role"),
        "auth_status": scenario.get("auth_status"),
        "vehicle_state": scenario.get("vehicle_state"),
        "available_tools": scenario.get("available_tools"),
    }
    return (
        system_prompt
        + "\n\nScenario:\n"
        + json.dumps(scenario_for_model, ensure_ascii=False, indent=2)
        + "\n\nReturn only the JSON object."
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--benchmark",
        default="benchmark/vehicle_safety_benchmark_v2_clean.jsonl",
    )
    ap.add_argument(
        "--prompt",
        default="prompts/structured_authorization_policy.txt",
    )
    ap.add_argument("--model", default="llama3.2:3b")
    ap.add_argument("--output", default=None)
    ap.add_argument("--limit", type=int, default=None, help="Use for smoke tests, e.g., --limit 10")
    ap.add_argument("--temperature", type=float, default=0.0)
    ap.add_argument("--max_tokens", type=int, default=256)
    ap.add_argument("--timeout", type=int, default=180)
    ap.add_argument("--sleep", type=float, default=0.0)
    args = ap.parse_args()

    bench = load_jsonl(args.benchmark)
    if args.limit:
        bench = bench[:args.limit]
    system_prompt = read_text(args.prompt)

    prompt_name = Path(args.prompt).stem
    safe_model = args.model.replace(":", "_").replace("/", "_")
    output = args.output or f"outputs_{safe_model}_{prompt_name}.jsonl"
    Path(output).parent.mkdir(parents=True, exist_ok=True)

    print(f"Running {len(bench)} scenarios")
    print(f"Model: {args.model}")
    print(f"Prompt: {args.prompt}")
    print(f"Output: {output}")

    done = 0
    with open(output, "w", encoding="utf-8") as f:
        for scenario in bench:
            prompt = build_prompt(system_prompt, scenario)
            try:
                response = call_ollama(
                    args.model,
                    prompt,
                    temperature=args.temperature,
                    max_tokens=args.max_tokens,
                    timeout=args.timeout,
                )
                raw = response.get("response", "")
                parsed = parse_json_object(raw)
                action = normalize_action(parsed.get("action")) if isinstance(parsed, dict) else None
                if action is None:
                    action = extract_action_field(raw)
                record = {
                    "id": scenario["id"],
                    "model": args.model,
                    "prompt_file": args.prompt,
                    "benchmark_file": args.benchmark,
                    "generated_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    "temperature": args.temperature,
                    "max_tokens": args.max_tokens,
                    "resolved_model_version": response.get("model"),
                    "model_output": parsed,
                    "raw_response": raw,
                    "predicted_action": action,
                }
            except Exception as e:
                record = {
                    "id": scenario.get("id"),
                    "model": args.model,
                    "prompt_file": args.prompt,
                    "benchmark_file": args.benchmark,
                    "generated_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    "temperature": args.temperature,
                    "max_tokens": args.max_tokens,
                    "model_output": None,
                    "raw_response": "",
                    "predicted_action": None,
                    "error": repr(e),
                }
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
            f.flush()
            done += 1
            if done % 10 == 0 or done == len(bench):
                print(f"Completed {done}/{len(bench)}")
            if args.sleep:
                time.sleep(args.sleep)

    print("Done.")
    print(f"Saved: {output}")


if __name__ == "__main__":
    main()
