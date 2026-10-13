# Vehicle Voice Authorization Benchmark (SmartSP 2026)

This repository contains the 202-scenario benchmark, the structured authorization policy, two ablation instructions, model runners, recorded model responses, and scoring code for the SmartSP 2026 vehicle voice authorization study.

## Contents

- `benchmark/vehicle_safety_benchmark_v2_clean.jsonl`: finalized scenarios and reference decisions.
- `benchmark/vehicle_safety_benchmark_v2_clean_original.jsonl`: pre-correction version for the revision audit.
- `prompts/`: exact instructions for the structured, generic safety, and minimal interface conditions.
- `scripts/run_*`: Ollama, OpenAI, and Gemini runners; each sends scenario fields and requests a seven-label JSON decision.
- `scripts/score_authorization.py`: scoring and paired tests.
- `outputs/`: the seven recorded model runs used for the reported results.
- `scores_main/`, `scores_ablation/`: derived summaries and per-scenario scoring.
- `BENCHMARK_POLICY.md`, `CHANGELOG.md`: policy interpretation and documented benchmark corrections.

## Reproduce the reported scores

Use Python 3.10 or newer. Scoring requires only the Python standard library. From this directory, run:

```bash
python scripts/validate_artifact.py
python scripts/score_authorization.py \
  --benchmark benchmark/vehicle_safety_benchmark_v2_clean.jsonl \
  --outputs outputs/llama32_structured_rerun.jsonl outputs/llama31_structured_rerun.jsonl outputs/gpt4o_structured_rerun.jsonl outputs/gemini_pro_structured_final_newproject.jsonl outputs/gemini_flash_structured_rerun.jsonl \
  --names llama32 llama31 gpt4o gemini_pro gemini_flash \
  --outdir scores_main
python scripts/score_authorization.py \
  --benchmark benchmark/vehicle_safety_benchmark_v2_clean.jsonl \
  --outputs outputs/llama32_minimal_rerun.jsonl outputs/llama32_generic_rerun.jsonl outputs/llama32_structured_rerun.jsonl \
  --names minimal generic structured \
  --outdir scores_ablation
```

The expected main Decision Alignment counts are 81, 124, 168, 180, and 178 out of 202, respectively. The ablation counts are 59, 57, and 81 out of 202. The scorer also reports conditional error rates, 95% Wilson intervals, format compliance, and paired McNemar tests.

## Generate new responses

The runner scripts require their respective clients: `ollama` (Python package and a running local server), `openai` with `OPENAI_API_KEY`, or `google-genai` with `GEMINI_API_KEY`. See each script's `--help` for arguments. The recorded runs used temperature 0, with a maximum output setting of 256 tokens for Llama and GPT-4o and 2048 tokens for Gemini; their JSONL metadata identifies requested models and, where returned, resolved versions. Provider aliases and hosted model behavior can change, so fresh API responses may differ from the recorded outputs.

The benchmark was revised after preliminary runs to correct 23 scenario records, including one reference decision, and the reported seven runs use the finalized benchmark. The original records and changes are included for audit.
