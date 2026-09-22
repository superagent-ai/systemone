"""Build the aggregate SystemOne v2 review package from frozen evaluation outputs."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
DATASET = {
    "training": {
        "rows": 41_632,
        "sha256": "ac40ce0bd84f0f5eef42b0dc6f43c2fb25880260da90a98f5f269d6c46dfb8a5",
    },
    "development": {
        "rows": 2_871,
        "sha256": "5143890e5de1c3d85790daad6a43e06175888f64f2c13273c791f84b19055375",
    },
    "calibration": {
        "rows": 2_867,
        "sha256": "319b4bdbc542dd8fc3be36061b53f15d6b88aff0bd3e5990d000a70ab44dc25c",
    },
    "operational_evaluation": {
        "rows": 800,
        "sha256": "7eed76d379730a55d7e5122d12a31402ef15a1115e6ea544340eff5298229217",
    },
}
SYSTEMS = ("Base Qwen3.8-27B", "SystemOne v1", "SystemOne v2", "Jev 1.13.0")


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def maybe_metric(value: dict[str, Any] | None, key: str) -> float | None:
    return None if value is None else value.get(key)


def compact_system(system: dict[str, Any]) -> dict[str, Any]:
    general = system["general"]
    security = system["security"]
    latency = system["latency"]
    return {
        "broad_macro_accuracy": system["general_macro_accuracy"],
        "mmlu_pro": {
            key: general["mmlu-pro"][key] for key in ("n", "accuracy", "nll", "brier")
        },
        "rewardbench_2": {
            key: general["reward-bench-2-best-of-4"][key]
            for key in ("n", "accuracy", "nll", "brier")
        },
        "truthfulqa_2025": {
            key: general["truthfulqa-2025-binary"][key]
            for key in ("n", "accuracy", "nll", "brier")
        },
        "typesafe_102_agreement": system["typesafe102"]["equal_case_modal_agreement"],
        "operations": {
            "rows": None if system["operations"] is None else system["operations"]["n"],
            "accuracy": maybe_metric(system["operations"], "accuracy"),
            "nll": maybe_metric(system["operations"], "nll"),
            "brier": maybe_metric(system["operations"], "brier"),
        },
        "prompt_injection": {
            benchmark: {
                key: security[benchmark].get(key)
                for key in (
                    "rows",
                    "accuracy",
                    "attack_recall",
                    "false_positive_rate",
                    "precision",
                    "balanced_accuracy",
                    "auroc",
                    "binary_brier",
                    "nll",
                )
            }
            for benchmark in ("bipia-detector", "deepset-test", "notinject")
        },
        "jevbench_public": {
            key: system["jevbench_public"].get(key)
            for key in ("rows", "correct", "total", "accuracy", "nll", "brier", "ece_10_bin")
            if key in system["jevbench_public"]
        },
        "latency": {
            "scope": latency.get("scope", "Observed serving path"),
            "request_width": latency.get("request_width"),
            "p50_seconds": latency["request_p50_seconds"],
            "p95_seconds": latency["request_p95_seconds"],
        },
    }


def percent(value: float | None) -> str:
    return "—" if value is None else f"{value * 100:.1f}%"


def latency(value: float | None) -> str:
    return "—" if value is None else f"{value * 1000:.0f} ms"


def markdown(report: dict[str, Any]) -> str:
    systems = report["systems"]
    columns = list(SYSTEMS)
    rows = [
        ("Broad benchmark macro", [systems[name]["broad_macro_accuracy"] for name in columns]),
        ("MMLU-Pro accuracy", [systems[name]["mmlu_pro"]["accuracy"] for name in columns]),
        (
            "RewardBench 2 accuracy",
            [systems[name]["rewardbench_2"]["accuracy"] for name in columns],
        ),
        (
            "TruthfulQA 2025 accuracy",
            [systems[name]["truthfulqa_2025"]["accuracy"] for name in columns],
        ),
        (
            "TypeSafe 102 agreement",
            [systems[name]["typesafe_102_agreement"] for name in columns],
        ),
        (
            "Operations accuracy",
            [systems[name]["operations"]["accuracy"] for name in columns],
        ),
        (
            "BIPIA attack recall",
            [
                systems[name]["prompt_injection"]["bipia-detector"]["attack_recall"]
                for name in columns
            ],
        ),
        (
            "Deepset accuracy",
            [systems[name]["prompt_injection"]["deepset-test"]["accuracy"] for name in columns],
        ),
        (
            "NotInject benign accuracy",
            [systems[name]["prompt_injection"]["notinject"]["accuracy"] for name in columns],
        ),
        (
            "JevBench v1.2 public accuracy",
            [systems[name]["jevbench_public"]["accuracy"] for name in columns],
        ),
    ]
    lines = [
        "# SystemOne v2 results",
        "",
        f"Run `{report['run_id']}` selected checkpoint step "
        f"{report['checkpoint']['selected_step']} of {report['checkpoint']['total_steps']}.",
        "",
        "| Evaluation | " + " | ".join(columns) + " |",
        "| --- | " + " | ".join("---:" for _ in columns) + " |",
    ]
    lines.extend(
        f"| {label} | " + " | ".join(percent(value) for value in values) + " |"
        for label, values in rows
    )
    lines.extend(
        [
            "",
            "## Observed latency",
            "",
            "These are observed paths, not normalized price or serving-stack comparisons.",
            "",
            "| Metric | " + " | ".join(columns) + " |",
            "| --- | " + " | ".join("---:" for _ in columns) + " |",
            "| Median | "
            + " | ".join(latency(systems[name]["latency"]["p50_seconds"]) for name in columns)
            + " |",
            "| P95 | "
            + " | ".join(latency(systems[name]["latency"]["p95_seconds"]) for name in columns)
            + " |",
            "",
            "## Claim boundary",
            "",
            "JevBench reports all 231 publicly released decisions. It is not the official "
            "534-decision composite because the remaining 303 decisions are unavailable.",
            "",
            "## Limitations",
            "",
            *[f"- {item}" for item in report["limitations"]],
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--jevbench", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=ROOT)
    args = parser.parse_args()
    output_json = args.output_dir / "results.json"
    output_markdown = args.output_dir / "RESULTS.md"
    if output_json.exists() or output_markdown.exists():
        parser.error("Refusing to overwrite an existing result package")

    summary = load(args.summary)
    jevbench = load(args.jevbench)
    training = summary["training"]
    if training["run_id"] != "systemone-general-v2-full-20260922a":
        parser.error("Unexpected training run")
    if jevbench["training_run_id"] != training["run_id"]:
        parser.error("JevBench artifact does not belong to the training run")
    expected_jevbench_sha256 = (
        "888bc813fce3d26b4c63c5be221525e20ee7e24fb89adf305707a6e89144ef92"
    )
    if jevbench["input_sha256"] != expected_jevbench_sha256:
        parser.error("Unexpected JevBench public input")

    report = {
        "schema_version": 1,
        "status": "complete",
        "run_id": training["run_id"],
        "model": {
            "source": training["base_model"]["source"],
            "revision": training["base_model"]["revision"],
        },
        "checkpoint": {
            "selected_step": training["selected_step"],
            "total_steps": training["steps"],
            "temperature": training["temperature"],
            "training_elapsed_seconds": training["training_elapsed_seconds"],
        },
        "dataset": DATASET,
        "jevbench_public": {
            "rows": 231,
            "input_sha256": jevbench["input_sha256"],
            "upstream_revision": jevbench["revision"],
            "official_full_rows": 534,
            "unavailable_rows": 303,
        },
        "systems": {
            name: compact_system(summary["systems"][name]) for name in SYSTEMS
        },
        "source_artifacts": {
            "evaluation_summary_sha256": digest(args.summary),
            "jevbench_summary_sha256": digest(args.jevbench),
        },
        "limitations": summary["limitations"],
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    output_markdown.write_text(markdown(report))
    print(json.dumps({"results": str(output_json), "results_sha256": digest(output_json)}))


if __name__ == "__main__":
    main()
