# Nagato vs Jev: live prompt-injection benchmark

Run date: 2026-09-20

Both production APIs received the same 1,255 frozen public examples as one binary
`choice` question per request. Four requests were in flight for each provider. Three
warm-up requests per provider were discarded. The final rule was identical:
`unsafe` only when `P(unsafe) > 0.70`; otherwise `safe`. There was no `unsure` class.

## Quality

| Public evaluation | Examples | Nagato | Jev 1.13.0 | Winner |
|---|---:|---:|---:|---|
| BIPIA detector adaptation (attack-heavy) | 800 | **68.38%** | 54.50% | Nagato |
| Deepset prompt-injection test | 116 | **72.41%** | 71.55% | Nagato |
| NotInject benign-only test | 339 | 97.35% | **99.12%** | Jev |

The weighted accuracy over all 1,255 examples was 76.57% for Nagato and 68.13%
for Jev. This aggregate is descriptive only because the three datasets have very
different class mixes.

## Security behavior

| Metric across all applicable examples | Nagato | Jev 1.13.0 | Better |
|---|---:|---:|---|
| Attacks detected (660 attacks) | **56.82%** | 39.85% | Nagato |
| Benign inputs incorrectly blocked (595 benign) | 1.51% | **0.50%** | Jev |

Nagato detected 375 attacks and incorrectly blocked 9 benign inputs. Jev detected
263 attacks and incorrectly blocked 3 benign inputs. The practical tradeoff is
therefore higher attack recall from Nagato versus fewer false alarms from Jev.

## Live API latency

| Metric | Nagato | Jev 1.13.0 | Winner |
|---|---:|---:|---|
| Warm request p50 | **701 ms** | 813 ms | Nagato |
| Warm request p95 | **923 ms** | 1,116 ms | Nagato |
| Sustained throughput at concurrency 4 | **5.54 req/s** | 4.18 req/s | Nagato |

Latency includes public internet transit from the same client. It excludes model
cold start and the three discarded warm-ups. Each request contained exactly one
decision, so requests per second equals decisions per second in this run.

## API price

| Price | Nagato | Jev |
|---|---:|---:|
| Input per million provider-counted tokens | $0.050 proposed launch price | $0.042 published price |
| Output per million tokens | Free | Free |
| This 1,255-example run at those rates | $0.0614 | $0.0375 |

The full-suite cost differs by more than the list-price gap because each provider
reported a different input-token count for the identical payloads: 1,228,624 for
Nagato and 892,204 for Jev. Token counts across different tokenizers are not directly
comparable units of text.

## Scope and evidence

- The BIPIA score is for a frozen binary detector adaptation over email, table, and
  code contexts. It is not the original generative BIPIA leaderboard task.
- NotInject contains only benign examples, so its accuracy measures benign pass-through
  and cannot measure attack recall.
- API model responses identified Jev as `jev-1.13.0` and Nagato as `nagato`.
- `summary.json` contains the input SHA-256 fingerprints, totals, latency statistics,
  usage, and metric summaries. The six JSONL files contain all row-level probabilities
  and decisions without copying the benchmark text.
