# SystemOne v3 results

Run `systemone-reasoning-v3-full-20260922a` selected checkpoint step 800 of 954.

## Checkpoint selection

| Development metric | Parent (SystemOne v2) | Selected v3 |
| --- | ---: | ---: |
| Accuracy | 83.4% | 89.9% |
| Reasoning-family macro | 82.5% | 89.6% |
| NLL (lower is better) | 0.4161 | 0.2901 |
| Brier score (lower is better) | 0.2294 | 0.1560 |

## Held-out evaluation

| Evaluation | Base Qwen3.8-27B | SystemOne v2 | SystemOne v3 | Jev 1.13.0 |
| --- | ---: | ---: | ---: | ---: |
| Broad benchmark macro | 76.0% | 76.3% | **76.9%** | **88.1%** |
| MMLU-Pro accuracy | 58.4% | 60.1% | **63.3%** | **81.5%** |
| RewardBench 2 accuracy | 80.1% | 80.4% | **82.3%** | **87.4%** |
| TruthfulQA 2025 accuracy | 89.4% | **88.5%** | 85.2% | **95.3%** |
| GSM8K held-out accuracy | 63.5% | — | **83.9%** | — |
| TypeSafe 102 agreement | 86.6% | 87.6% | **88.0%** | **88.3%** |
| Operations accuracy | 72.4% | 82.2% | **83.9%** | — |
| BIPIA attack recall | 64.7% | 75.5% | **87.5%** | 62.3% |
| Deepset accuracy | 78.4% | 81.9% | **86.2%** | 72.4% |
| NotInject benign accuracy | **96.2%** | 91.4% | 87.6% | **97.6%** |
| JevBench v1.2 public accuracy | 85.7% | **87.4%** | **87.4%** | 86.6% |

The reasoning continuation made real progress on MMLU-Pro, RewardBench 2, GSM8K, operations, and
attack recall. It did not reach Jev on the broad general suite: the remaining broad-macro gap is
11.2 percentage points. TruthfulQA and benign NotInject accuracy regressed, so v3 is not a
drop-in production replacement for v2 without routing or further multi-objective training.

## Optimized B200 latency

All rows are 37-request measurements with 21 decisions per request.

| System / prefix state | Median | P95 | Decisions/s |
| --- | ---: | ---: | ---: |
| Base / cold | 559 ms | 601 ms | 37.5 |
| Base / warm | 436 ms | 484 ms | 47.5 |
| SystemOne v3 / cold | **658 ms** | **745 ms** | **31.2** |
| SystemOne v3 / warm | **479 ms** | **514 ms** | **43.6** |
| Jev 1.13 hosted path | 703 ms | 846 ms | 29.2 |

The earlier low latency is reproducible. Native LoRA adds roughly 44 ms to the base warm median but
keeps the observed 21-decision path below the prior Jev hosted measurement. This is directional,
not a matched-infrastructure claim: SystemOne uses loopback HTTP on a B200, while Jev includes WAN.

## Claim boundary

The public JevBench result covers 231 released decisions only. The official 534-decision composite
cannot be reproduced because 303 decisions are unavailable. The general evaluations use direct
answer-slot scoring and are not generative reasoning leaderboard results.
