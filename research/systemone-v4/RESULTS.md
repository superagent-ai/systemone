# SystemOne v4 results

Run `systemone-general-v4-full-s1-20260923a` selected checkpoint step 938 of 938 using only the
sealed development protocol.

## Sealed development result

| Metric | Parent | Selected v4 |
| --- | ---: | ---: |
| Multi-objective score | 84.24% | **86.81%** |
| Reasoning macro | 82.37% | **87.03%** |
| Knowledge accuracy | 94.04% | **94.44%** |
| Preference accuracy | **66.67%** | 66.17% |
| Operations accuracy | **84.00%** | 83.00% |
| Attack recall | 95.61% | **97.37%** |
| False-positive rate | 0.30% | 0.30% |
| NLL (lower is better) | 0.3729 | **0.3219** |
| Brier (lower is better) | 0.2152 | **0.1837** |

## Held-out evaluation

| Evaluation | Base Qwen3.8-27B | SystemOne v2 | SystemOne v4 | Jev 1.13.0 |
| --- | ---: | ---: | ---: | ---: |
| Broad benchmark macro | 76.0% | 76.3% | **77.3%** | **88.1%** |
| MMLU-Pro accuracy | 58.4% | 60.1% | **62.3%** | **81.5%** |
| RewardBench 2 accuracy | 80.1% | 80.4% | **82.4%** | **87.4%** |
| TruthfulQA 2025 accuracy | **89.4%** | 88.5% | 87.3% | **95.3%** |
| TypeSafe 102 agreement | 86.6% | **87.6%** | 87.0% | **88.3%** |
| Operations accuracy | 72.4% | 82.2% | **84.8%** | — |
| BIPIA attack recall | 64.7% | 75.5% | **91.3%** | 62.3% |
| BIPIA false-positive rate | **0.0%** | **0.0%** | 1.0% | **0.0%** |
| Deepset accuracy | 78.4% | 81.9% | **89.7%** | 72.4% |
| NotInject benign accuracy | **96.2%** | 91.4% | 85.3% | **97.6%** |
| JevBench v1.2 public accuracy | 85.7% | **87.4%** | 86.6% | **86.6%** |

V4 is a real improvement over its v2 parent on the broad macro, MMLU-Pro, RewardBench,
operations, and attack-oriented security evaluations. It ties Jev on the public-only JevBench slice
and beats the frozen Jev observations on BIPIA recall and Deepset accuracy. It is not at Jev's
general level: the broad-macro gap remains 10.7 percentage points, and TruthfulQA plus benign
NotInject accuracy remain clear weaknesses. This checkpoint should therefore remain a research
candidate rather than replace the production model globally.

## Exact B200 serving result

All rows use 37 requests with 21 decisions per request.

| System / prefix state | Median | P95 | Decisions/s |
| --- | ---: | ---: | ---: |
| Base / cold | 397 ms | 432 ms | 52.4 |
| Base / warm | 255 ms | 280 ms | 81.8 |
| SystemOne v4 / cold | **523 ms** | **573 ms** | **39.7** |
| SystemOne v4 / warm | **353 ms** | **391 ms** | **59.3** |
| Jev 1.13 hosted observation | 703 ms | 846 ms | 29.2 |

The exact native-LoRA adapter is faster than the prior Jev hosted observation, but this is not a
matched-infrastructure comparison: SystemOne uses loopback HTTP on a B200 while Jev includes WAN.
The SGLang trained pass retained 95.14% authored accuracy and reproduced direct scoring with 0/144
argmax flips on the authored suite.

## Claim boundary

The public JevBench result covers only 231 released decisions. The official 534-decision composite
cannot be reproduced because 303 decisions are unavailable. General evaluations use direct
answer-slot probabilities and are not generative reasoning leaderboard results.

