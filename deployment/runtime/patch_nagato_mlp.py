"""Opt-in Nagato dense-MLP serving hook for the pinned SGLang image."""

import hashlib
import json
from pathlib import Path

OLD_INIT = "        self._enable_silu_fp4_quant_fusion = False"
NEW_INIT = """        self._enable_silu_fp4_quant_fusion = False
        self._nagato_prefix = prefix
        self._nagato_svdquant = bool(__import__("os").environ.get("NAGATO_SVDQUANT_MLP_ROOT"))"""
OLD_FORWARD = """        gate_up, _ = self.gate_up_proj(x)
        if self._enable_silu_fp4_quant_fusion and not isinstance(gate_up, tuple):"""
NEW_FORWARD = """        if self._nagato_svdquant:
            from nagato_security_mix_mlp_v1 import corrected_mlp
            return corrected_mlp(self, x)
        gate_up, _ = self.gate_up_proj(x)
        if self._enable_silu_fp4_quant_fusion and not isinstance(gate_up, tuple):"""


def replace_once(source, old, new):
    if source.count(old) != 1:
        raise ValueError("Pinned SGLang source changed or Nagato patch already applied")
    return source.replace(old, new)


def main():
    path = Path("/sgl-workspace/sglang/python/sglang/srt/models/qwen2_moe.py")
    before = path.read_text()
    after = replace_once(replace_once(before, OLD_INIT, NEW_INIT), OLD_FORWARD, NEW_FORWARD)
    compile(after, str(path), "exec")
    path.write_text(after)
    receipt = {
        "path": str(path),
        "before_sha256": hashlib.sha256(before.encode()).hexdigest(),
        "after_sha256": hashlib.sha256(after.encode()).hexdigest(),
    }
    Path("/opt/nagato-mlp-patch.json").write_text(json.dumps(receipt, indent=2))
    print(json.dumps(receipt))


if __name__ == "__main__":
    main()
