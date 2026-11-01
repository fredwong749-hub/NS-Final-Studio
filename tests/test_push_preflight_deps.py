"""K-OPS-W13（总调度 01:2x）：推送清单 = producer preflight 的文件依赖。对现行导入稿每一镜调 frame_job.build_first（与 producer 同一入口），
作业里出现的每个文件都必须在 resident_sync.required_data() 里；场景底图（I5）必须在内。只读真实数据。"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in ("tools/autopilot", "tools/pipeline", "services/agent", "services/render_router", "packages/schema", "services/api"):
    sys.path.insert(0, str(ROOT / p))

pytestmark = pytest.mark.skipif(not (ROOT / "data/import/script_v2.json").exists(), reason="没有导入稿")


def test_required_data_covers_every_preflight_dependency():
    import preflight_deps as PD
    import resident_sync as RS
    deps = PD.preflight_deps(include_sources=False)
    assert not deps["errors"], deps["errors"]
    need = RS.required_data()
    missing = sorted({f for fs in deps["per_shot"].values() for f in fs if not f.startswith("data/cache/")} - need)
    assert missing == [], missing[:10]
    assert any(f.startswith("assets/scenes/") for f in need)          # I5 场景底图（01:14 漏列的那一类）
