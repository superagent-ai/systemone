import math
import re

from nagato_svdquant_recipe import RECIPES

RUN = "nagato-security-mix-export-v1-20260920"
BASE = "nagato-fp8-v2-20260918-export"
IDENTITY = {
    "source": "Qwen/Qwen3.8-27B",
    "revision": "1d4bf0f2ff6012fd82039f2fa52739d0dd7c60c0",
    "adapter_sha256": "a3767ed058009037cc48e28f86a414ad17bffbf8bb8b8180b228e45af835fe6f",
}


def validate_manifest(manifest):
    if (
        any(manifest.get(key) != value for key, value in IDENTITY.items())
        or manifest.get("run_id") != RUN
        or manifest.get("base_export") != BASE
        or manifest.get("format") != "nagato_security_mix_mlp_v1"
        or manifest.get("rank") != 128
        or manifest.get("all_roundtrips_equal") is not True
    ):
        raise ValueError("Unexpected Nagato sidecar identity or format")
    expected = {f"model.language_model.layers.{index}.mlp" for index in range(64)}
    modules = manifest.get("modules", {})
    files = manifest.get("output_files", {})
    expected_files = {f"layer-{index:03d}.safetensors" for index in range(64)}
    if set(modules) != expected or set(files) != expected_files:
        raise ValueError("Incomplete Nagato sidecar")
    for index in range(64):
        filename = f"layer-{index:03d}.safetensors"
        info = files[filename]
        if (
            set(info) != {"sha256", "bytes"}
            or re.fullmatch(r"[0-9a-f]{64}", info["sha256"]) is None
            or type(info["bytes"]) is not int
            or info["bytes"] <= 0
        ):
            raise ValueError("Invalid sidecar integrity record")
        module = modules[f"model.language_model.layers.{index}.mlp"]
        if module["file"] != filename or set(module["projections"]) != {"gate_up", "down"}:
            raise ValueError("Invalid sidecar projection map")
        for kind, shape in (("gate_up", [34816, 5120]), ("down", [5120, 17408])):
            projection = module["projections"][kind]
            errors = (
                projection["calibration_error"],
                projection["probe_error"]["relative_l2_error"],
                projection["probe_error"]["max_absolute_error"],
            )
            if (
                projection["shape"] != shape
                or projection["recipe"] not in RECIPES
                or projection["reload_identical"] is not True
                or any(not math.isfinite(value) or value < 0 for value in errors)
            ):
                raise ValueError("Invalid sidecar projection")
    return manifest
