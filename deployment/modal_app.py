"""Production Modal deployment for the verified Nagato checkpoint."""

import atexit
import hashlib
import json
import os
import signal
import subprocess
import threading
from pathlib import Path

import modal

APP_NAME = "nagato-api"
BASE_EXPORT = "nagato-fp8-v2-20260918-export"
SIDECAR_EXPORT = "nagato-security-mix-export-v1-20260920"
SIDECAR_MANIFEST_SHA256 = "af06368cc746efb847d1f545487821bab28274eb4e89e87f4fd7a77066c8a46b"
TUNING_CACHE_SHA256 = "57c020e85fe1deba8815c02e37a86896e5a56258c82471e83557e69abe9d6e9f"
SOURCE_MODEL = "Qwen/Qwen3.8-27B"
SOURCE_REVISION = "1d4bf0f2ff6012fd82039f2fa52739d0dd7c60c0"

app = modal.App(APP_NAME)
artifacts = modal.Volume.from_name("openjev-rlcd-artifacts-v1", create_if_missing=False)
cache = modal.Volume.from_name("rlcd-hf-cache-v1", create_if_missing=False)
production_secret = modal.Secret.from_name("nagato-production")

image = (
    modal.Image.from_registry("lmsysorg/sglang:v0.5.19-cu130")
    .entrypoint([])
    .add_local_dir("src", remote_path="/app/src", copy=True)
    .add_local_dir("deployment/runtime", remote_path="/work", copy=True)
    .run_commands(
        "/opt/sglang/bin/pip install --no-cache-dir "
        "'fastapi>=0.116,<1' 'httpx>=0.28,<1' 'orjson>=3.10,<4' "
        "'pydantic-settings>=2.10,<3' 'uvicorn[standard]>=0.35,<1'",
        "/opt/sglang/bin/python /work/patch_nagato_mlp.py",
        "/opt/sglang/bin/python /work/patch_sglang_logprobs.py",
    )
    .env(
        {
            "PYTHONPATH": "/app/src:/work",
            "HF_HOME": "/cache/huggingface",
            "TRANSFORMERS_OFFLINE": "1",
            "TOKENIZERS_PARALLELISM": "false",
            "SGLANG_RUST_SERVER": "0",
            "SGLANG_JIT_DEEPGEMM_PRECOMPILE": "0",
            "NAGATO_BACKEND_URL": "http://127.0.0.1:30000",
            "NAGATO_SERVED_MODEL": "nagato-27b-2026-09-20",
            "NAGATO_MODEL_ALIASES": "nagato,nagato-latest,openjev,jev-latest",
            "NAGATO_TEMPERATURE": "1.0905077326652577",
            "NAGATO_MAX_INPUT_TOKENS": "32768",
            "NAGATO_MAX_TOTAL_INPUT_TOKENS": "262144",
            "NAGATO_MAX_CONCURRENT_REQUESTS": "32",
            "NAGATO_MAX_CONCURRENT_BRANCHES": "128",
        }
    )
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_artifacts() -> tuple[Path, Path]:
    model_root = Path("/artifacts") / BASE_EXPORT
    sidecar_root = Path("/artifacts") / SIDECAR_EXPORT
    manifest_path = sidecar_root / "export.json"
    if sha256(manifest_path) != SIDECAR_MANIFEST_SHA256:
        raise RuntimeError("Nagato sidecar manifest does not match the verified release")
    if sha256(sidecar_root / "tuning-cache.json") != TUNING_CACHE_SHA256:
        raise RuntimeError("Nagato kernel tactic cache does not match the verified release")
    manifest = json.loads(manifest_path.read_text())
    if sha256(model_root / "export.json") != manifest["base_export_manifest_sha256"]:
        raise RuntimeError("Nagato base model and correction sidecar do not match")
    return model_root / "merged", sidecar_root


def tokenizer_snapshot() -> str:
    owner, model = SOURCE_MODEL.split("/", 1)
    snapshot = (
        Path("/cache/huggingface/hub") / f"models--{owner}--{model}" / "snapshots" / SOURCE_REVISION
    )
    required = {
        "config.json",
        "tokenizer.json",
        "tokenizer_config.json",
        "chat_template.jinja",
    }
    missing = sorted(name for name in required if not (snapshot / name).is_file())
    if missing:
        raise RuntimeError(f"Pinned tokenizer snapshot is incomplete: {missing}")
    return str(snapshot)


def launch_sglang(model_path: Path, tokenizer_path: str) -> subprocess.Popen:
    command = [
        "/opt/sglang/bin/python",
        "-m",
        "sglang.launch_server",
        "--model-path",
        str(model_path),
        "--tokenizer-path",
        tokenizer_path,
        "--host",
        "127.0.0.1",
        "--port",
        "30000",
        "--language-only",
        "--dtype",
        "bfloat16",
        "--context-length",
        "32768",
        "--mem-fraction-static",
        ".85",
        "--max-running-requests",
        "128",
        "--max-total-tokens",
        "131072",
        "--max-mamba-cache-size",
        "128",
        "--mamba-ssm-dtype",
        "bfloat16",
        "--attention-backend",
        "trtllm_mha",
        "--linear-attn-prefill-backend",
        "flashinfer",
        "--chunked-prefill-size",
        "8192",
        "--cuda-graph-backend-prefill",
        "breakable",
        "--cuda-graph-max-bs-decode",
        "64",
        "--fp8-gemm-backend",
        "deep_gemm",
        "--enable-metrics",
    ]
    process = subprocess.Popen(command, start_new_session=True)
    stopping = threading.Event()

    def stop_backend():
        stopping.set()
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)

    def restart_container_if_backend_dies():
        process.wait()
        if not stopping.is_set():
            os._exit(1)

    atexit.register(stop_backend)
    threading.Thread(target=restart_container_if_backend_dies, daemon=True).start()
    return process


@app.function(
    image=image,
    gpu="B200",
    cpu=4,
    memory=32768,
    timeout=86_400,
    min_containers=1,
    max_containers=1,
    scaledown_window=600,
    volumes={"/artifacts": artifacts, "/cache": cache},
    secrets=[production_secret],
)
@modal.concurrent(max_inputs=32)
@modal.asgi_app()
def web():
    artifacts.reload()
    cache.reload()
    from nagato_api.api import create_app
    from nagato_api.config import Settings

    settings = Settings()
    if not settings.accepted_api_keys:
        raise RuntimeError("NAGATO_API_KEYS must contain at least one production API key")
    model_path, sidecar_path = verify_artifacts()
    tokenizer_path = tokenizer_snapshot()
    os.environ.update(
        {
            "NAGATO_MODEL_PATH": tokenizer_path,
            "NAGATO_SVDQUANT_MLP_ROOT": str(sidecar_path),
            "NAGATO_SVDQUANT_MANIFEST_SHA256": SIDECAR_MANIFEST_SHA256,
            "NAGATO_SVDQUANT_TUNING_SHA256": TUNING_CACHE_SHA256,
        }
    )
    launch_sglang(model_path, tokenizer_path)
    return create_app(Settings())
