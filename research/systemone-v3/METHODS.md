# SystemOne v3 general-reasoning protocol

This directory is the private review package for the SystemOne v3 reasoning-only continuation run.
It publishes aggregate metrics, immutable provenance, and the serving protocol. It intentionally
excludes dataset rows, teacher outputs, credentials, and model weights.

## Research question

Can a reasoning-only continuation of SystemOne v2 improve broad finite-choice reasoning without
changing prompts or evaluation labels, and can the resulting adapter retain the earlier low-latency
SGLang serving path?

## Model and training

- Base: `Qwen/Qwen3.8-27B` at revision
  `1d4bf0f2ff6012fd82039f2fa52739d0dd7c60c0`
- Parent: SystemOne v2 checkpoint step 600
- Precision/hardware: BF16 on one NVIDIA H200
- Adaptation: rank-32 LoRA over attention and MLP projections, alpha 32, no dropout
- Context: 32,768 tokens for training and 65,536 for direct evaluation
- Schedule: one natural-frequency pass, 954 updates, peak learning rate `3e-6`
- Objective: verified-label cross-entropy plus 0.45 soft CE for correct, order-stable Jev targets,
  with a 0.10 Brier component
- Seed: `20260922`

This is probability distillation with proper-scoring losses. It is not claimed to reproduce a
proprietary RLCD recipe.

## Public training sources

| Source | Training rows | Frozen revision | License |
| --- | ---: | --- | --- |
| WinoGrande | 19,999 | `01e74176c63542e6b0bcb004dcdea22d94fb67b5` | Apache-2.0 |
| HellaSwag | 17,190 | `218ec52e09a7e7462a5400043bb9a69a41d06b76` | MIT |
| CommonsenseQA | 9,615 | `94630fe30dad47192a8546eb75f094926d47e155` | MIT |
| QASC | 7,377 | `a34ba204eb9a33b919c10cc08f4f1c8dae5ec070` | CC-BY-4.0 |
| GSM8K | 6,872 | `740312add88f781978c0658806c59bc2815b9866` | MIT |
| **Total** | **61,053** | | |

| Artifact | Rows | SHA-256 |
| --- | ---: | --- |
| Training | 61,053 | `a85ae15cfab1a990b09cc17ff4691e1336c97b73e5a37d543c0e170b10012e59` |
| Development | 2,250 | `ff161fdfa56c0f2db573e8c8f8d84243f478ad40d4bf8c4be61b661a9fae5a25` |
| Calibration | 2,250 | `2e7686c176b319ffdb5f0fe02c4fa7ccb8d9e5110710d7e4d89c69b6b279d007` |
| GSM8K test | 1,319 | `e9e7618c578caef60fdf33e034904ceac60127340c2ec63c27c367300499e6f7` |
| Teacher targets | 61,053 | `c49fae796c41e150af4dbb969af93a1a2a3890b8fe5f76804c564a4f61f66b1d` |

Training rows were removed for normalized exact overlap or at least 80% five-word-shingle
containment against every final evaluation, plus all development and calibration inputs. A further
382 duplicate states were removed. Protected final suites were MMLU-Pro, RewardBench 2,
TruthfulQA, TypeSafe 102, operations, BIPIA, Deepset, NotInject, public JevBench, and GSM8K test.

## Checkpoint selection

The parent adapter is step 0. Each reasoning family may lose at most 1.5 percentage points,
reasoning macro may lose at most 0.2 points, and both NLL and Brier must remain within 1.02 times
the baseline. Step 800 was selected from 954 updates and calibrated to temperature
`0.805245165974627`.

## Optimized serving protocol

The exact selected adapter was served with SGLang 0.5.19 on one B200, BF16 weights, native LoRA
dispatch, TRT-LLM attention, radix caching, and the pinned OpenJev SGLang client. Each latency
request contains 21 independent decisions. Cold-prefix measurements flush the cache after warm-up;
warm-prefix measurements repeat the same request. Tokenization, prefix warm-up, concurrent
branches, and loopback HTTP are included; process startup is excluded.

Native adapter serving was chosen because a merged BF16 export exceeded the probability-drift
gate. The accepted native path produced zero argmax flips on the 64-row trained smoke gate and a
mean probability difference of 0.0026 from the direct reference.

## Interpretation boundaries

- JevBench covers its 231 public decisions, not the hidden 303 or official 534-decision composite.
- SystemOne latency is loopback B200 serving; Jev latency is a previously observed hosted WAN path.
- Direct answer-slot scoring evaluates classification, not generative chain-of-thought reasoning.
- This is one fixed training seed; replication is required before a production promotion.
