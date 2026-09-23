# SystemOne v4 multi-objective protocol

This directory is the private review package for the SystemOne v4 multi-objective continuation.
It publishes aggregate metrics, immutable provenance, seed selection evidence, and the exact serving
protocol. It excludes dataset rows, teacher outputs, credentials, and model weights.

## Research question

Can a continuation from SystemOne v2 improve general classification, reasoning, operational
routing, and security detection together without selecting on the final held-out benchmarks?

## Model and training

- Base: `Qwen/Qwen3.8-27B` at revision
  `1d4bf0f2ff6012fd82039f2fa52739d0dd7c60c0`
- Parent: SystemOne v2 checkpoint step 600
- Precision/hardware: BF16 on one NVIDIA H200 per seed
- Adaptation: rank-32 LoRA over attention and MLP projections, alpha 32, no dropout
- Context: 32,768 tokens for training and 65,536 for direct evaluation
- Schedule: one pass, 938 updates, peak learning rate `2e-6`
- Objective: verified labels dominate; agreeing Jev targets receive 0.45 soft CE; the loss also
  includes a 0.10 Brier component
- Seeds: `20260923`, `20260924`, and `20260925`

This is probability distillation with proper-scoring losses. It is not claimed to reproduce a
proprietary RLCD recipe.

## Frozen 60,000-row mixture

| Domain | Rows | Share |
| --- | ---: | ---: |
| Hard reasoning | 33,000 | 55% |
| Factual calibration | 9,000 | 15% |
| Security | 9,000 | 15% |
| Preference | 6,000 | 10% |
| Operations | 3,000 | 5% |

Reasoning used 80% lowest teacher-label confidence plus 20% deterministic coverage. Security used
2,250 unsafe variants and 6,750 independently sourced benign tasks. All inherited rows were
rechecked for normalized exact overlap and at least 80% five-word-shingle containment against the
protected final evaluations; two overlaps were removed.

| Artifact | Rows | SHA-256 |
| --- | ---: | --- |
| Training | 60,000 | `e9a20528b14612cbe3f5453cbd6e085a5b5ce8a77ef1b3392cf135590e403b75` |
| Development | 2,919 | `c1b5edd5c47a418c3d05fa4c502a442efea333c0a145bbdb14e2689745796147` |
| Calibration | 2,919 | `fc7cb63dceef30dd8c691b974bc61a046a3f897322f6adfefc32184d516ff251` |
| Operations evaluation | 800 | `7eed76d379730a55d7e5122d12a31402ef15a1115e6ea544340eff5298229217` |
| GSM8K test | 1,319 | `e9e7618c578caef60fdf33e034904ceac60127340c2ec63c27c367300499e6f7` |

Protected final suites were MMLU-Pro, RewardBench 2, TruthfulQA, TypeSafe 102, operations, BIPIA,
Deepset, NotInject, the 231 public JevBench decisions, and GSM8K test.

## Sealed selection

Checkpoints were eligible only if reasoning, knowledge, preference, operations, security recall,
security false-positive rate, NLL, and Brier remained inside predeclared gates relative to each
seed's step-0 parent. Final held-out benchmarks were report-only. Among eligible seed winners, the
highest sealed-development primary score won, with NLL as the tie-breaker.

| Seed | Selected step | Sealed score | NLL |
| --- | ---: | ---: | ---: |
| 20260923 | 938 | **86.81%** | **0.3219** |
| 20260924 | 300 | 86.05% | 0.3439 |
| 20260925 | 200 | 85.15% | 0.3632 |

Seed `20260923`, step 938, was selected before inspecting its final held-out results.

## Optimized serving protocol

The exact selected adapter was served with SGLang 0.5.19 on one B200, BF16 weights, native LoRA
dispatch, TRT-LLM attention, radix caching, and the pinned OpenJev SGLang client. Each latency
request contains 21 independent decisions. Cold-prefix measurements flush the cache after warm-up;
warm-prefix measurements repeat the same request. Tokenization, concurrent branches, and loopback
HTTP are included; process startup is excluded.

The native path produced zero argmax flips on the 64-row trained smoke gate and a mean probability
difference of 0.00242 from the direct reference.

## Interpretation boundaries

- JevBench covers 231 public decisions, not the hidden 303 or official 534-decision composite.
- SystemOne latency is loopback B200 serving; Jev latency is a prior hosted-WAN observation.
- Direct answer-slot scoring evaluates classification, not generative chain-of-thought reasoning.
- Three seeds reduce seed-selection risk but do not establish production parity with Jev.

