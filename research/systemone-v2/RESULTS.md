# SystemOne v2 results

Run `systemone-general-v2-full-20260922a` selected checkpoint step 600 of 652.

## Checkpoint selection

| Development metric | Base | Selected checkpoint |
| --- | ---: | ---: |
| Accuracy | 80.0% | 84.6% |
| General macro accuracy | 78.0% | 80.6% |
| Primary selection score | 79.8% | 83.6% |
| NLL (lower is better) | 0.4810 | 0.3555 |
| Brier score (lower is better) | 0.2738 | 0.2132 |

## Held-out evaluation

| Evaluation | Base Qwen3.8-27B | SystemOne v1 | SystemOne v2 | Jev 1.13.0 |
| --- | ---: | ---: | ---: | ---: |
| Broad benchmark macro | 76.0% | 76.7% | 76.3% | 88.1% |
| MMLU-Pro accuracy | 58.4% | 60.1% | 60.1% | 81.5% |
| RewardBench 2 accuracy | 80.1% | 82.3% | 80.4% | 87.4% |
| TruthfulQA 2025 accuracy | 89.4% | 87.8% | 88.5% | 95.3% |
| TypeSafe 102 agreement | 86.6% | 86.6% | 87.6% | 88.3% |
| Operations accuracy | 72.4% | 96.8% | 82.2% | — |
| BIPIA attack recall | 64.7% | 92.8% | 75.5% | 62.3% |
| Deepset accuracy | 78.4% | 89.7% | 81.9% | 72.4% |
| NotInject benign accuracy | 96.2% | 85.8% | 91.4% | 97.6% |
| JevBench v1.2 public accuracy | 85.7% | 89.6% | 87.4% | 86.6% |

## Observed latency

These are observed paths, not normalized price or serving-stack comparisons.

| Metric | Base Qwen3.8-27B | SystemOne v1 | SystemOne v2 | Jev 1.13.0 |
| --- | ---: | ---: | ---: | ---: |
| Median | 980 ms | 1207 ms | 1162 ms | 703 ms |
| P95 | 995 ms | 1224 ms | 1179 ms | 846 ms |

## Claim boundary

JevBench reports all 231 publicly released decisions. It is not the official 534-decision composite because the remaining 303 decisions are unavailable.

## Limitations

- JevBench covers the 231 public decisions, not its hidden 303 decisions or official 534-decision composite.
- Jev general and security values are frozen evidence on identical datasets; operations has no Jev result.
- SystemOne/base latency is warm local H200 execution; Jev latency includes its hosted network path.
- Direct answer-slot scoring is a classifier protocol, not generative chain-of-thought evaluation.
- This is one fixed training seed; replication across seeds is required before a production quality claim.
