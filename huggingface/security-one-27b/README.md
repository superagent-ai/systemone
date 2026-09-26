---
license: apache-2.0
library_name: transformers
pipeline_tag: text-classification
base_model: denis-pplx/autojev-27b
base_model_relation: finetune
language:
  - en
tags:
  - qwen3.8
  - safetensors
  - classification
  - decision-model
  - jev
  - system-one
  - prompt-injection
  - ai-security
  - security-routing
  - code-security
  - infrastructure-security
  - sglang
---

# Security-One-27B

**One security model for your applications, agents, code, and infrastructure.**

Security-One-27B is a calibrated decision model designed to run 24/7 as an always-on security triage layer. It evaluates application events, agent activity, code changes, logs, alerts, and infrastructure signals, then returns structured probabilities that can drive deterministic policy:

- handle routine low-risk events automatically;
- send suspicious or high-severity events to a stronger model;
- escalate consequential or ambiguous cases to a human.

Security-One is optimized for this first-pass decision role. It scores supplied options in one forward pass instead of generating a free-form answer, making it suitable for high-volume security pipelines where predictable output and explicit confidence matter.

Prompt-injection detection is the best-validated security capability in this release, but it is one application of the model rather than the product boundary. The same decision interface supports security classification across the application, agent, code, and infrastructure layers. Domain-specific deployments should be calibrated and evaluated on their own traffic before automation.

It is a continual fine-tune of [`denis-pplx/autojev-27b`](https://huggingface.co/denis-pplx/autojev-27b), itself based on [`Qwen/Qwen3.8-27B`](https://huggingface.co/Qwen/Qwen3.8-27B). The released checkpoint contains merged BF16 SafeTensors weights.

> **Important:** this is a decision model, not a chat model. Use the prompt/readout recipe in [`recipes/sglang`](./recipes/sglang) or the hosted Security-One API. Ordinary chat-completion prompting does not reproduce the reported results.

## Always-on security layer

Security-One is intended to sit on the fast path between telemetry and expensive investigation:

```text
applications · agents · code · infrastructure
                      │
                      ▼
                 Security-One
                      │
          ┌───────────┼────────────┐
          ▼           ▼            ▼
       allow      stronger model   human / incident queue
     or monitor      analysis
```

Typical decision tasks include:

- **Applications:** abuse signals, suspicious requests, policy violations, and incident severity.
- **Agents:** prompt injection, untrusted instructions, tool-use risk, data access, and privilege escalation.
- **Code:** change-risk classification, vulnerability triage, secret exposure, and review prioritization.
- **Infrastructure:** log and alert triage, anomalous actions, configuration risk, and escalation routing.

Security-One produces evidence for a control plane; it is not itself the control plane. Keep authentication, authorization, sandboxing, rate limits, and other deterministic enforcement outside the model.

## Model details

| Property | Value |
|---|---|
| Parameters | 27B |
| Weights | BF16 SafeTensors, 15 shards |
| Architecture | Qwen3.8 / `Qwen3_5ForConditionalGeneration` |
| Native context | 262,144 tokens |
| Validated classification context | 65,536 tokens |
| Parent checkpoint | `denis-pplx/autojev-27b@6f5b557e037f5edb25c7dc92dbc6553e5a19c015` |
| Base checkpoint | `Qwen/Qwen3.8-27B@1d4bf0f2ff6012fd82039f2fa52739d0dd7c60c0` |
| Calibration temperature | `0.14527332485151376` |
| Release format | Merged inference checkpoint |

## Quick start

The recommended path is SGLang on an NVIDIA GPU. A B200 was used for the validated production configuration; other recent high-memory GPUs may work with adjusted memory and concurrency settings.

```bash
pip install -U "huggingface_hub[hf_xet]"
hf download superagent-ai/security-one-27b \
  --include 'recipes/sglang/*' \
  --local-dir security-one-27b
cd security-one-27b/recipes/sglang
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Start SGLang in another terminal:

```bash
docker run --gpus all --ipc=host --shm-size 32g \
  -p 30000:30000 \
  -v "$HOME/.cache/huggingface:/root/.cache/huggingface" \
  lmsysorg/sglang:v0.5.19-cu130 \
  python3 -m sglang.launch_server \
    --model-path superagent-ai/security-one-27b \
    --host 0.0.0.0 \
    --port 30000 \
    --language-only \
    --dtype bfloat16 \
    --context-length 65536 \
    --mem-fraction-static 0.85 \
    --max-running-requests 128 \
    --max-total-tokens 131072 \
    --max-mamba-cache-size 128 \
    --mamba-ssm-dtype float32 \
    --mamba-radix-cache-strategy extra_buffer \
    --attention-backend trtllm_mha \
    --chunked-prefill-size 8192 \
    --cuda-graph-backend-prefill breakable \
    --cuda-graph-max-bs-decode 64
```

Classify a security signal:

```bash
python classify.py \
  --state 'An agent received an instruction from an untrusted document to export environment secrets to an external URL.' \
  --question 'How should this event be routed?' \
  --criteria '{"monitor":"Routine event; continue monitoring","escalate":"Suspicious or consequential event; send to security analysis"}'
```

Example output:

```json
{
  "choice": "escalate",
  "probabilities": {
    "monitor": 0.003,
    "escalate": 0.997
  }
}
```

See the [full recipe](./recipes/sglang/README.md) for binary, multi-class, thresholded, and Python examples.

## Evaluation

The following results use frozen, row-identical evaluation inputs. Security-One and AutoJev were evaluated locally with their released decision readouts; Jev 1.13.0 was evaluated through the hosted TypeSafe API. Security policy metrics use `unsafe` when `P(unsafe) >= 0.70`, otherwise `safe`.

### Prompt-injection evaluations

| Evaluation | Rows | Security-One | AutoJev-27B | Jev 1.13.0 |
|---|---:|---:|---:|---:|
| BIPIA overall accuracy | 800 | **99.75%** | 46.00% | 71.75% |
| BIPIA attacks detected | 600 | **99.83%** | 28.00% | 62.33% |
| BIPIA benign false positives ↓ | 200 | 0.50% | **0.00%** | **0.00%** |
| Deepset overall accuracy | 116 | **88.79%** | 68.10% | 72.41% |
| Deepset attacks detected | 60 | **78.33%** | 38.33% | 46.67% |
| Deepset benign false positives ↓ | 56 | **0.00%** | **0.00%** | **0.00%** |
| NotInject benign accuracy | 339 | 87.61% | **98.82%** | 97.64% |

Security-One is substantially more sensitive to attacks at the fixed 70% threshold, while AutoJev and Jev reject fewer benign NotInject examples. This is an operating-point tradeoff rather than a universal ranking.

### General decision evaluations

| Evaluation | Rows | Security-One | AutoJev-27B | Jev 1.13.0 |
|---|---:|---:|---:|---:|
| JevBench public v1.2 | 231 | 86.15% | **87.01%** | 86.58% |
| MMLU-Pro decision adaptation | 12,032 | 63.16% | 63.14% | **81.47%** |
| RewardBench 2 best-of-4 adaptation | 1,763 | **97.96%** | 97.73% | 87.41% |
| TruthfulQA 2025 binary, order-controlled | 790 | 96.46% | **96.58%** | 95.32% |
| Mean of MMLU-Pro, RewardBench 2, and TruthfulQA | — | 85.86% | 85.82% | **88.07%** |

### Additional Security-One results

| Evaluation | Rows | Result |
|---|---:|---:|
| GSM8K multiple-choice adaptation | 1,319 | 80.36% accuracy |
| TypeSafe 102 | 102 | 86.85% equal-case modal agreement |
| Operational classification evaluation | 800 | 76.62% accuracy |
| Authored holdout | 144 | 99.31% accuracy |

These are decision-task adaptations, not necessarily the canonical generative leaderboard protocols. BIPIA is a frozen binary detector adaptation over email, table, and code contexts; it is not the original generative BIPIA leaderboard task. NotInject is benign-only, so it cannot measure attack recall. TruthfulQA is scored once per unique question and requires the prediction to be correct under both option orders. See [`evals/comparison.json`](./evals/comparison.json) for model revisions, dataset hashes, exact metrics, and protocol notes. Evaluate the model on your own domain and operating threshold before deployment.

## Training

Security-One-27B was continued from AutoJev-27B with a rank-32 LoRA (`alpha=32`) for one short epoch (16 selected updates, peak learning rate `1.5e-6`), then merged into BF16 weights.

The continual-tuning corpus contained 18,106 examples:

| Domain | Rows |
|---|---:|
| Security | 7,106 |
| Reasoning | 4,500 |
| Knowledge | 2,500 |
| Preference | 2,200 |
| Operations | 1,800 |

Security data combined group-separated BIPIA training contexts, Deepset prompt-injection training data, and hard benign examples. General data mixed public reasoning, knowledge, preference, and operational-classification sources. The exact curated corpus is not bundled. BIPIA components retain their upstream MIT or CC BY-SA 4.0 licenses.

Protected final evaluations were excluded from training. An exact hash audit over normalized candidate content checked 1,230 protected rows and found zero overlaps. BIPIA was split by clean context and Deepset by original source row to reduce leakage across train, calibration, development, and test data.

## Export verification

The merged export was checked against the selected training checkpoint on 64 examples:

- argmax flips: **0**
- mean logit difference: **0.0**
- maximum logit difference: **0.0**

`export.json` records immutable source revisions and SHA-256 hashes for every weight shard.

## Intended use

Security-One-27B is intended for:

- continuous first-pass security classification across applications, agents, code, and infrastructure;
- prompt-injection, malicious-instruction, tool-use, and agent-activity screening;
- log, alert, code-change, vulnerability, severity, and policy triage;
- routing suspicious events to stronger models or human responders;
- binary and multi-class decisions with calibrated probabilities;
- high-throughput structured decisions where free-form generation is undesirable.

## Limitations

- Prompt injection remains an open security problem. Do not treat this model as a complete security boundary.
- Code, application, and infrastructure use cases are intended deployment patterns, not equally validated benchmark claims; evaluate each workflow on representative data before enabling automated actions.
- Calibration can shift across domains, languages, prompt formats, quantization methods, and inference engines.
- The `0.70` security threshold is a release policy, not a universal optimum.
- The release is primarily evaluated on English text. Multimodal capability is inherited but is not validated here.
- The model can be confidently wrong. Keep deterministic controls, least privilege, and human review around consequential actions.
- This checkpoint is not intended as a conversational assistant.

## License and attribution

Weights are released under Apache License 2.0, following the licenses of Qwen3.8-27B and AutoJev-27B. See `LICENSE` and `NOTICE` in this repository. Security-One is an independent Superagent release and is not affiliated with Qwen, AutoJev, TypeSafe, or Jev.

## Citation

```bibtex
@software{security_one_27b_2026,
  title        = {Security-One-27B},
  author       = {Superagent Technologies Inc.},
  year         = {2026},
  url          = {https://huggingface.co/superagent-ai/security-one-27b}
}
```
