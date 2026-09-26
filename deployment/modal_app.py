"""Production Modal deployment for the verified SystemOne AutoJev V2.3 checkpoint."""

import atexit
import hashlib
import json
import os
import signal
import subprocess
import threading
from pathlib import Path

import modal

APP_NAME = "systemone-api"
MODEL_EXPORT = "autojev-security-v2-3-sglang-export-20260925a"
MODEL_EXPORT_MANIFEST_SHA256 = "6d4ae1b91f5431c895cb869f87298feb7306b22a48b706f13acc5e0ad42c23ba"
TRAINING_RUN = "autojev-security-v2-3-full-20260925b"
TRAINING_MODEL = "autojev-security-v2-3"
SOURCE_MODEL = "Qwen/Qwen3.8-27B"
SOURCE_REVISION = "1d4bf0f2ff6012fd82039f2fa52739d0dd7c60c0"

app = modal.App(APP_NAME)
artifacts = modal.Volume.from_name("openjev-rlcd-artifacts-v1", create_if_missing=False)
cache = modal.Volume.from_name("rlcd-hf-cache-v1", create_if_missing=False)
production_secret = modal.Secret.from_name("systemone-production")
testing_secret = modal.Secret.from_name("systemone-testing-key")

image = (
    modal.Image.from_registry("lmsysorg/sglang:v0.5.19-cu130")
    .entrypoint([])
    .add_local_dir("src", remote_path="/app/src", copy=True)
    .add_local_dir("deployment/runtime", remote_path="/work", copy=True)
    .run_commands(
        "/opt/sglang/bin/pip install --no-cache-dir "
        "'fastapi>=0.116,<1' 'httpx>=0.28,<1' 'orjson>=3.10,<4' "
        "'pydantic-settings>=2.10,<3' 'uvicorn[standard]>=0.35,<1'",
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
            "SYSTEMONE_BACKEND_URL": "http://127.0.0.1:30000",
            "SYSTEMONE_SERVED_MODEL": "security-one",
            "SYSTEMONE_MODEL_ALIASES": (
                "security-one-latest,systemone,systemone-latest,openjev,jev-latest"
            ),
            "SYSTEMONE_RELEASE_DATE": "2026-09-25",
            "SYSTEMONE_TEMPERATURE": "0.14527332485151376",
            "SYSTEMONE_MAX_INPUT_TOKENS": "65536",
            "SYSTEMONE_MAX_TOTAL_INPUT_TOKENS": "131072",
            "SYSTEMONE_MAX_CONCURRENT_REQUESTS": "32",
            "SYSTEMONE_MAX_CONCURRENT_BRANCHES": "128",
        }
    )
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_artifacts() -> Path:
    model_root = Path("/artifacts") / MODEL_EXPORT
    manifest_path = model_root / "export.json"
    if sha256(manifest_path) != MODEL_EXPORT_MANIFEST_SHA256:
        raise RuntimeError("SystemOne model manifest does not match the verified release")
    manifest = json.loads(manifest_path.read_text())
    expected = {
        "training_run_id": TRAINING_RUN,
        "training_model_id": TRAINING_MODEL,
        "base_source": SOURCE_MODEL,
        "base_revision": SOURCE_REVISION,
        "dtype": "bfloat16",
    }
    if any(manifest.get(key) != value for key, value in expected.items()):
        raise RuntimeError("SystemOne model lineage does not match the verified release")
    fidelity = manifest.get("fidelity", {})
    if fidelity.get("rows") != 64 or fidelity.get("argmax_flips") != 0:
        raise RuntimeError("SystemOne model failed its recorded export-fidelity gate")
    merged = model_root / "merged"
    missing = sorted(
        name
        for name in {
            "config.json",
            "tokenizer.json",
            "tokenizer_config.json",
            "chat_template.jinja",
        }
        if not (merged / name).is_file()
    )
    if missing:
        raise RuntimeError(f"Pinned SystemOne model export is incomplete: {missing}")
    for name, metadata in manifest.get("output_files", {}).items():
        path = merged / name
        if not path.is_file() or path.stat().st_size != metadata["bytes"]:
            raise RuntimeError(f"Pinned SystemOne weight shard is incomplete: {name}")
    return merged


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
        "65536",
        "--mem-fraction-static",
        ".85",
        "--max-running-requests",
        "128",
        "--max-total-tokens",
        "131072",
        "--max-mamba-cache-size",
        "128",
        "--mamba-ssm-dtype",
        "float32",
        "--mamba-radix-cache-strategy",
        "extra_buffer",
        "--attention-backend",
        "trtllm_mha",
        "--chunked-prefill-size",
        "8192",
        "--cuda-graph-backend-prefill",
        "breakable",
        "--cuda-graph-max-bs-decode",
        "64",
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
    secrets=[production_secret, testing_secret],
)
@modal.concurrent(max_inputs=32)
@modal.asgi_app()
def web():
    artifacts.reload()
    cache.reload()
    from systemone_api.api import create_app
    from systemone_api.config import Settings

    settings = Settings()
    if not settings.accepted_api_keys:
        raise RuntimeError("SYSTEMONE_API_KEYS must contain at least one production API key")
    model_path = verify_artifacts()
    tokenizer_path = str(model_path)
    os.environ["SYSTEMONE_MODEL_PATH"] = tokenizer_path
    launch_sglang(model_path, tokenizer_path)
    return create_app(Settings())
