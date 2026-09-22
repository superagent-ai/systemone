"""Validate the public-review surface of the SystemOne v2 result package."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results.json"
EXPECTED_SYSTEMS = {"Base Qwen3.8-27B", "SystemOne v1", "SystemOne v2", "Jev 1.13.0"}
EXPECTED_DATASET = {
    "training": (41_632, "ac40ce0bd84f0f5eef42b0dc6f43c2fb25880260da90a98f5f269d6c46dfb8a5"),
    "development": (2_871, "5143890e5de1c3d85790daad6a43e06175888f64f2c13273c791f84b19055375"),
    "calibration": (2_867, "319b4bdbc542dd8fc3be36061b53f15d6b88aff0bd3e5990d000a70ab44dc25c"),
    "operational_evaluation": (
        800,
        "7eed76d379730a55d7e5122d12a31402ef15a1115e6ea544340eff5298229217",
    ),
}
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
    assert report["run_id"] == "systemone-general-v2-full-20260922a"
    assert report["model"] == {
        "source": "Qwen/Qwen3.8-27B",
        "revision": "1d4bf0f2ff6012fd82039f2fa52739d0dd7c60c0",
    }
    assert set(report["systems"]) == EXPECTED_SYSTEMS
    for name, (rows, digest) in EXPECTED_DATASET.items():
        assert report["dataset"][name] == {"rows": rows, "sha256": digest}
    assert report["jevbench_public"]["rows"] == 231
    assert report["jevbench_public"]["input_sha256"] == (
        "888bc813fce3d26b4c63c5be221525e20ee7e24fb89adf305707a6e89144ef92"
    )
    assert report["checkpoint"]["total_steps"] == 652
    assert 0 <= report["checkpoint"]["selected_step"] <= 652
    assert report["checkpoint"]["temperature"] > 0
    assert report["checkpoint"]["development"]["baseline"]["rows"] == 3_806
    assert report["checkpoint"]["development"]["selected"]["rows"] == 3_806
    assert set(report["source_artifacts"]) == {
        "evaluation_summary_sha256",
        "jevbench_summary_sha256",
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
