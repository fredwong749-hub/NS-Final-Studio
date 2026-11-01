"""R11-3 写作返修链路（K-OPS-W04，WORKFLOW 11-01）：tools/pipeline/repair_chain.py。
- 每集输入取 script_v2.json 登记的现行来源（不是 23:14 底稿），sha256 对不上就不拼；
- 桩写作方原样回镜头时，链路跑通、输出能导入解析、集 / 镜 / 对白 / 时长不变，导入计划不带 body（不导入）。
只读真实剧本来源；产物写临时目录。"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools/pipeline"))
import repair_chain as RC  # noqa: E402

pytestmark = pytest.mark.skipif(not RC.SCRIPT.exists(), reason="没有生产剧本")


def test_sources_follow_script_v2_not_base():
    srcs = RC.episode_sources()
    d = json.loads(RC.SCRIPT.read_text(encoding="utf-8"))
    last = {}
    for s in d["sources"]:
        for e in s.get("episodes") or []:
            last[int(e)] = Path(s["path"].replace("\\", "/")).name
    assert {e: v["path"].name for e, v in srcs.items()} == last


def test_stub_chain_roundtrip(tmp_path):
    srcs = RC.episode_sources()
    ep = next((e for e, v in sorted(srcs.items()) if v["sha_ok"]), None)
    if ep is None:
        pytest.skip("没有 sha 一致的来源")
    code = RC.main(["--episodes", str(ep), "--stub", "--max-rounds", "1", "--out-dir", str(tmp_path)])
    v = json.loads((tmp_path / "verify.json").read_text(encoding="utf-8"))
    assert code == 0 and v["verify"]["ok"], v
    assert (tmp_path / "input.md").read_bytes() == (tmp_path / "output.md").read_bytes()   # 桩不改内容
    plan = json.loads((tmp_path / "import_plan.json").read_text(encoding="utf-8"))
    assert plan["needs_master_approval"] and plan["body"] is None


def test_changed_source_refuses(tmp_path, monkeypatch):
    RL = RC._load_rl()
    bad = {7: {"path": tmp_path / "x.md", "sha256": "0", "sha_ok": False}}
    with pytest.raises(SystemExit):
        RC.assemble(RL, [7], bad)
