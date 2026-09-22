# SystemOne v2 evaluation protocol

This directory contains the review package for the SystemOne v2 general-classifier experiment. The package publishes aggregate metrics, immutable provenance, and the exact comparison protocol. It intentionally excludes training rows, cached teacher outputs, credentials, and model weights.

## Research question

Can a fresh Qwen3.8-27B classifier fine-tune improve broad finite-choice classification while preserving operational routing, prompt-injection recall, benign-input specificity, and calibration?

SystemOne v2 is compared with:

- the pinned Qwen3.8-27B base model;
- the previous SystemOne v1 checkpoint;
- Jev 1.13.0 evidence collected on the same public evaluation rows where available.

## Frozen model and training recipe

- Base: `Qwen/Qwen3.8-27B`
- Revision: `1d4bf0f2ff6012fd82039f2fa52739d0dd7c60c0`
- Precision and hardware: BF16 on one NVIDIA H200
- Adaptation: rank-32 LoRA over attention and MLP projections, alpha 32, no dropout
- Context: 32,768 tokens for training; 65,536 tokens for evaluation
- Schedule: one natural-frequency epoch, AdamW, peak learning rate `5e-6`, 5% warmup, cosine decay, gradient accumulation 16
- Objective: verified-label cross-entropy plus soft Jev probability targets when teacher/human checks agree, with a 0.10 Brier component
- Benign security replay: 1.5x example weight
- Seed: `20260922`

This is probability distillation with proper-scoring losses. It is not claimed to reproduce a proprietary RLCD implementation.

## Dataset composition

| Component | Rows |
| --- | ---: |
| Broad knowledge, reasoning, and preference-distillation source | 32,234 |
| Preference replay | 4,400 |
| Operational routing | 3,000 |
| Prompt-injection attacks | 498 |
| Benign security negatives | 1,500 |
| **Total training rows** | **41,632** |

The data is used in its natural frequency distribution. Families are not upsampled to equal size.

| Artifact | Rows | SHA-256 |
| --- | ---: | --- |
| Training | 41,632 | `ac40ce0bd84f0f5eef42b0dc6f43c2fb25880260da90a98f5f269d6c46dfb8a5` |
| Development | 2,871 | `5143890e5de1c3d85790daad6a43e06175888f64f2c13273c791f84b19055375` |
| Calibration | 2,867 | `319b4bdbc542dd8fc3be36061b53f15d6b88aff0bd3e5990d000a70ab44dc25c` |
| Operational evaluation | 800 | `7eed76d379730a55d7e5122d12a31402ef15a1115e6ea544340eff5298229217` |

Training examples were checked against normalized exact matches and at least 80% five-word-shingle matches over every protected public evaluation. Evaluation labels were not used for training or checkpoint selection.

## Checkpoint selection

The untouched base model is step 0 and remains the fallback. A trained checkpoint is eligible only if all of these development gates pass:

- every broad group loses no more than 1 percentage point;
- broad macro accuracy loses no more than 0.2 percentage points;
- operational accuracy loses no more than 2 percentage points;
- benign security false-positive rate is at most 5%;
- attack recall loses no more than 3 percentage points;
- NLL and Brier score are each no more than 1.02 times the baseline value.

Among eligible checkpoints, the primary score is 70% broad macro, 15% operations, and 15% balanced security accuracy. A checkpoint must improve that score by more than 0.2 percentage points, or remain within 0.1 points while improving NLL by more than 0.01.

## Held-out evaluations

- MMLU-Pro
- RewardBench 2 best-of-four
- TruthfulQA 2025 binary
- TypeSafe public 102
- An 800-row operational-routing evaluation
- BIPIA detector adaptation
- Deepset prompt-injection test
- NotInject benign-input evaluation
- JevBench v1.2 public decisions

The JevBench comparison covers exactly 231 public decisions from upstream revision `a1799db9673bf59010bc698753e729b04132431f`, materialized as SHA-256 `888bc813fce3d26b4c63c5be221525e20ee7e24fb89adf305707a6e89144ef92`. It is not the official 534-decision composite: the remaining 303 imported or held-out decisions are not redistributed.

## Interpretation boundaries

- Accuracy comparisons use the same frozen public rows and answer-slot scoring protocol.
- SystemOne/base latency is warm local H200 execution. Jev latency includes its hosted network path, so the numbers describe observed paths rather than identical serving stacks.
- Direct answer-slot scoring evaluates classification, not generative chain-of-thought ability.
- A single fixed seed is evidence for this run, not proof of broad production parity. Replication should precede a release decision.
