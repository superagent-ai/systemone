"""Fail-closed, TP1 SM100 serving of the calibrated Nagato MLP sidecar."""

import hashlib
import importlib.metadata
import json
import os
import re
from pathlib import Path

from nagato_security_manifest import RUN, validate_manifest
from nagato_svdquant_recipe import PARAMETERS, apply

_manifest = None


def digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def validate_layer(record):
    match = re.fullmatch(r"model\.language_model\.layers\.(\d+)\.mlp", record["prefix"])
    if match is None or not 0 <= int(match[1]) < 64:
        raise ValueError("Unexpected dense MLP prefix")
    expected = {
        "input_dtype": "torch.bfloat16",
        "input_width": 5120,
        "gate_up_shape": [34816, 5120],
        "down_shape": [5120, 17408],
        "gate_up_dtype": "torch.float8_e4m3fn",
        "down_dtype": "torch.float8_e4m3fn",
        "tp_size": 1,
        "tp_rank": 0,
        "gate_up_tp_size": 1,
        "gate_up_tp_rank": 0,
        "bias": False,
        "fp4_fusion": False,
        "activation": "SiluAndMul",
        "input_is_parallel": True,
        "dp_reduce": False,
        "decode_tp": False,
        "sidecar_run": RUN,
    }
    for key, value in expected.items():
        if record.get(key) != value:
            raise ValueError("Unsupported Nagato MLP setting: " + key)


def load_manifest():
    global _manifest
    if _manifest is not None:
        return _manifest
    root = Path(os.environ["NAGATO_SVDQUANT_MLP_ROOT"])
    if root != Path("/artifacts") / RUN:
        raise ValueError("Unregistered sidecar root")
    manifest_path = root / "export.json"
    manifest = validate_manifest(json.loads(manifest_path.read_text()))
    if digest(manifest_path) != os.environ["NAGATO_SVDQUANT_MANIFEST_SHA256"]:
        raise ValueError("Sidecar manifest changed")
    api = importlib.metadata.distribution("flashinfer-python").locate_file(
        "flashinfer/gemm/gemm_svdquant.py"
    )
    if digest(api) != manifest["svdquant_api_sha256"]:
        raise ValueError("Serving SVDQuant API differs from the calibrated export")
    if digest("/work/nagato_svdquant_recipe.py") != manifest["recipe_source_sha256"]:
        raise ValueError("Serving SVDQuant recipe differs from the calibrated export")
    cache = root / "tuning-cache.json"
    if digest(cache) != os.environ["NAGATO_SVDQUANT_TUNING_SHA256"]:
        raise ValueError("Kernel tactic cache changed")
    from flashinfer import autotune

    with autotune(False, cache=str(cache)):
        pass
    _manifest = manifest
    return manifest


def corrected_mlp(mlp, x):
    import torch
    from safetensors.torch import load_file

    if x.dtype != torch.bfloat16 or x.shape[-1] != 5120 or not x.is_cuda:
        raise ValueError("Expected CUDA BF16 hidden states")
    if not hasattr(mlp, "_nagato_svdquant_params"):
        if torch.cuda.is_current_stream_capturing():
            raise ValueError("Nagato sidecar must load before CUDA graph capture")
        if torch.cuda.device_count() != 1 or torch.cuda.get_device_capability() != (10, 0):
            raise ValueError("Nagato production serving requires one SM100 GPU")
        down, gate = mlp.down_proj, mlp.gate_up_proj
        record = {
            "prefix": mlp._nagato_prefix,
            "sidecar_run": RUN,
            "input_dtype": str(x.dtype),
            "input_width": x.shape[-1],
            "down_shape": list(down.weight.shape),
            "gate_up_shape": list(gate.weight.shape),
            "down_dtype": str(down.weight.dtype),
            "gate_up_dtype": str(gate.weight.dtype),
            "tp_size": down.tp_size,
            "tp_rank": down.tp_rank,
            "gate_up_tp_size": gate.tp_size,
            "gate_up_tp_rank": gate.tp_rank,
            "bias": down.bias is not None or gate.bias is not None,
            "fp4_fusion": mlp._enable_silu_fp4_quant_fusion,
            "activation": type(mlp.act_fn).__name__,
            "input_is_parallel": down.input_is_parallel,
            "dp_reduce": down.use_dp_attention_reduce,
            "decode_tp": down.use_decode_attn_tp,
        }
        validate_layer(record)
        manifest = load_manifest()
        module = manifest["modules"][record["prefix"]]
        path = Path(os.environ["NAGATO_SVDQUANT_MLP_ROOT"]) / module["file"]
        integrity = manifest["output_files"][module["file"]]
        if path.stat().st_size != integrity["bytes"] or digest(path) != integrity["sha256"]:
            raise ValueError("Nagato sidecar tensor changed")
        tensors = load_file(str(path), device=str(x.device))
        names = {f"{kind}.{key}" for kind in ("gate_up", "down") for key in PARAMETERS}
        if set(tensors) != names:
            raise ValueError("Wrong Nagato sidecar parameter set")
        mlp._nagato_svdquant_params = {
            kind: {key: tensors[f"{kind}.{key}"] for key in PARAMETERS}
            for kind in ("gate_up", "down")
        }
    shape = x.shape[:-1]
    params = mlp._nagato_svdquant_params
    gate_up = apply(x.reshape(-1, 5120).contiguous(), params["gate_up"])
    activated = mlp.act_fn(gate_up)
    return apply(activated, params["down"]).view(*shape, 5120)
