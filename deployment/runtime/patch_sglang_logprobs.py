"""Narrow SGLang 0.5.19 selected-logprob compatibility fix."""

import hashlib
import json
from pathlib import Path


def main():
    path = Path(
        "/sgl-workspace/sglang/python/sglang/srt/managers/scheduler_components/"
        "batch_result_processor.py"
    )
    before = path.read_text()
    old = "v.tolist() for v in logits_output.next_token_token_ids_logprobs_val"
    start = before.index("    def _normalize_decode_outputs(")
    end = before.index("    def _apply_decode_logprobs(", start)
    block = before[start:end]
    if block.count(old) != 1:
        raise ValueError("Pinned SGLang logprob source changed or patch already applied")
    fixed = block.replace(
        old,
        "(v.tolist() if torch.is_tensor(v) else v) for v in "
        "logits_output.next_token_token_ids_logprobs_val",
    )
    after = before[:start] + fixed + before[end:]
    path.write_text(after)
    Path("/opt/systemone-logprob-patch.json").write_text(
        json.dumps(
            {
                "path": str(path),
                "before_sha256": hashlib.sha256(before.encode()).hexdigest(),
                "after_sha256": hashlib.sha256(after.encode()).hexdigest(),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
