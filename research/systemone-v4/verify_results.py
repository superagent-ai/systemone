"""Validate the aggregate-only SystemOne v4 review package."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results.json"
EXPECTED_SYSTEMS = {"Base Qwen3.8-27B", "SystemOne v2", "SystemOne v4", "Jev 1.13.0"}
FORBIDDEN_KEYS = {
    "prompt",
    "state",
    "questions",
    "options",
    "teacher_probabilities",
    "target_probabilities",
    "predictions",
    "token",
    "api_key",
    "secret",
    "weights",
}


def walk(value, path="root"):
    if isinstance(value, dict):
        for key, child in value.items():
            assert key.lower() not in FORBIDDEN_KEYS, f"forbidden field at {path}.{key}"
            yield from walk(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from walk(child, f"{path}[{index}]")
    elif isinstance(value, float):
        assert math.isfinite(value), f"non-finite number at {path}"
    elif isinstance(value, str):
        lowered = value.lower()
        assert "hf_" not in lowered and "apikey_" not in lowered, f"credential-like value at {path}"


def main() -> None:
    report = json.loads(RESULTS.read_text())
    assert report["schema_version"] == 1
    assert report["status"] == "complete"
    assert report["run_id"] == "systemone-general-v4-full-s1-20260923a"
    assert report["model"] == {
        "source": "Qwen/Qwen3.8-27B",
        "revision": "1d4bf0f2ff6012fd82039f2fa52739d0dd7c60c0",
    }
    assert report["checkpoint"]["selected_step"] == 938
    assert report["checkpoint"]["total_steps"] == 938
    assert len(report["seed_selection"]) == 3
    assert report["seed_selection"][0]["primary_score"] == max(
        seed["primary_score"] for seed in report["seed_selection"]
    )
    assert set(report["systems"]) == EXPECTED_SYSTEMS
    assert report["dataset"]["training"] == {
        "rows": 60_000,
        "sha256": "e9a20528b14612cbe3f5453cbd6e085a5b5ce8a77ef1b3392cf135590e403b75",
    }
    assert sum(report["dataset"]["mixture"].values()) == 60_000
    assert report["jevbench_public"]["rows"] == 231
    assert report["jevbench_public"]["unavailable_rows"] == 303
    assert report["optimized_serving"]["requests"] == 37
    assert report["optimized_serving"]["decisions_per_request"] == 21
    assert report["optimized_serving"]["serving_mode"] == "native_lora"
    assert set(report["source_artifacts"]) == {
        "evaluation_summary_sha256",
        "jevbench_summary_sha256",
        "jevbench_comparison_sha256",
        "sglang_summary_sha256",
        "sglang_manifest_sha256",
        "adapter_model_sha256",
        "adapter_config_sha256",
    }
    assert all(
        len(value) == 64 and all(character in "0123456789abcdef" for character in value)
        for value in report["source_artifacts"].values()
    )
    list(walk(report))
    digest = hashlib.sha256(RESULTS.read_bytes()).hexdigest()
    print(json.dumps({"status": "verified", "results_sha256": digest}))


if __name__ == "__main__":
    main()

