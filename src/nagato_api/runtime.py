import asyncio
import os
from typing import Any


def load_tokenizer(model_path: str) -> Any:
    if not model_path:
        raise RuntimeError("NAGATO_MODEL_PATH is required when the API loads its own tokenizer")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    from transformers import AutoTokenizer

    return AutoTokenizer.from_pretrained(
        model_path,
        local_files_only=True,
        trust_remote_code=False,
    )


async def wait_until_ready(backend, timeout_seconds: float) -> None:
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    while asyncio.get_running_loop().time() < deadline:
        if await backend.healthy():
            return
        await asyncio.sleep(1)
    raise RuntimeError("SGLang did not become healthy before the startup deadline")
