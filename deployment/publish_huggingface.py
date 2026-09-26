"""Publish the pinned Security-One BF16 export to Hugging Face from Modal storage."""

from __future__ import annotations

import os
from pathlib import Path

import modal

APP_NAME = "security-one-huggingface-release"
REPO_ID = "superagent-ai/security-one-27b"
EXPORT = "autojev-security-v2-3-sglang-export-20260925a"

app = modal.App(APP_NAME)
artifacts = modal.Volume.from_name("openjev-rlcd-artifacts-v1", create_if_missing=False)
hf_secret = modal.Secret.from_name("huggingface-upload")

image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install("huggingface_hub[hf_xet]>=0.35,<2")
    .add_local_dir(
        "huggingface/security-one-27b",
        remote_path="/release",
        copy=True,
    )
)


@app.function(
    image=image,
    cpu=4,
    memory=8192,
    timeout=86_400,
    volumes={"/artifacts": artifacts},
    secrets=[hf_secret],
)
def publish() -> dict[str, object]:
    from huggingface_hub import HfApi, hf_hub_download

    token = os.environ["HF_TOKEN"]
    api = HfApi(token=token)
    model_path = Path("/artifacts") / EXPORT / "merged"
    manifest_path = Path("/artifacts") / EXPORT / "export.json"
    if not model_path.is_dir() or not manifest_path.is_file():
        raise RuntimeError("Pinned Security-One export is missing")

    api.create_repo(REPO_ID, repo_type="model", private=False, exist_ok=True)
    api.upload_folder(
        repo_id=REPO_ID,
        repo_type="model",
        folder_path=model_path,
        commit_message="Upload verified BF16 SafeTensors checkpoint",
    )
    api.upload_file(
        repo_id=REPO_ID,
        repo_type="model",
        path_or_fileobj=manifest_path,
        path_in_repo="export.json",
        commit_message="Add immutable export manifest",
    )

    license_path = hf_hub_download(
        repo_id="Qwen/Qwen3.8-27B",
        filename="LICENSE",
        revision="1d4bf0f2ff6012fd82039f2fa52739d0dd7c60c0",
        token=token,
    )
    api.upload_file(
        repo_id=REPO_ID,
        repo_type="model",
        path_or_fileobj=license_path,
        path_in_repo="LICENSE",
        commit_message="Add Apache 2.0 license",
    )
    api.upload_folder(
        repo_id=REPO_ID,
        repo_type="model",
        folder_path="/release",
        commit_message="Add model card, attribution, and SGLang recipe",
    )

    info = api.model_info(REPO_ID, files_metadata=True)
    siblings = info.siblings or []
    total_bytes = sum(item.size or 0 for item in siblings)
    return {
        "repo_id": REPO_ID,
        "revision": info.sha,
        "files": len(siblings),
        "total_bytes": total_bytes,
    }
