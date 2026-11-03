"""W2 · MERGE-IMG（11-03）：V2 ep01 过“提示词”阶段——三处并回 V1 部件的回归。

1 ISS-1103-031008-8c50 导入器：每镜 构图 / 灯光 / 光线 / 分拍 / 表演节拍 原样进 shot.extras（label 不变）→ shot_language / first_beat_gaze 读得到
2 ISS-1103-032336-3aff 资产包模式造型唯一来源 = 清单（不设 looks_file），部件带 item_id
3 ISS-1103-030746-664a 提示词探针走 build_first + preflight（sop_gate.compile_preflight，多人镜 / 非女主镜不拒）；episode_ready 设定图缺口归 sheet 资产作业
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in ("services/agent", "packages/schema", "services/render_router", "packages/qc", ""):
    if str(ROOT / p) not in sys.path:
        sys.path.insert(0, str(ROOT / p))

from ns_agent import asset_refs as AR  # noqa: E402
from ns_agent import frame_job as FJ  # noqa: E402
from ns_agent import shot_language as SL  # noqa: E402

V2 = "series10_v2"
HAVE_V2 = bool(AR.project_cfg(V2)) and (ROOT / "assets_v2" / "manifest.json").is_file()

MD = """## ep01《t》

**镜1｜img**：近景，祁念站着
**构图**：前景=手｜中景=脸
**光线**：主光=顶光｜补光=白幕反射
**灯光**：动机光源=顶光（上方）
**分拍**：0–2秒｜抬手｜视线=灯架后的方向｜表情=抬眼；2–4秒｜放手｜视线=地面｜表情=平
**表演节拍**：0–2秒｜抬手
2–4秒｜放手
**机位与景别**：近景
**时长**：4秒
"""


# ---------------------------------------------------------------- 1 导入器
def _shot(tmp_path):
    from ns_agent.importer import script_md as M
    md = tmp_path / "p4.md"
    md.write_text(MD, encoding="utf-8")
    ep = M.import_script(md).episodes[0]
    return ep, ep.shots[0]


def test_importer_shot_extras_keep_labels(tmp_path):
    ep, sh = _shot(tmp_path)
    ex = {e.label: e.text for e in sh.extras}
    assert list(ex) == ["构图", "光线", "灯光", "分拍", "表演节拍", "机位与景别"]   # W7：七段全收（A2 F3）
    assert ex["光线"] == "主光=顶光｜补光=白幕反射"
    assert ex["表演节拍"].splitlines() == ["0–2秒｜抬手", "2–4秒｜放手"]          # 续行接在本字段
    assert not ep.extras          # W7：A2 F1 改口——V1 不变由编译冻结守（tests/test_w7_import_followup.py），不再拿“机位与景别落集级”代表


def test_compile_side_reads_imported_extras(tmp_path):
    _, sh = _shot(tmp_path)
    assert SL.script_field(sh, "composition") == "前景=手｜中景=脸"
    assert SL.script_field(sh, "lighting") == "动机光源=顶光（上方）"
    assert FJ.first_beat_gaze(sh) == "灯架后的方向"


# ---------------------------------------------------------------- 2 造型唯一来源
def _projects() -> dict:
    return json.loads((ROOT / "config" / "recipes" / "asset_refs.json").read_text(encoding="utf-8"))["projects"]


def test_asset_package_projects_have_single_looks_source():
    for name, c in _projects().items():
        if c.get("assets_manifest"):
            assert "looks_file" not in c, f"{name}：资产包模式造型只认清单，不许再设 looks_file"
            assert not AR.chain_files(name, "looks_file")


@pytest.mark.skipif(not HAVE_V2, reason="V2 资产包不在本机")
def test_v2_looks_come_from_manifest_with_item_ids():
    looks = AR.load_looks(V2)
    assert looks == AR.manifest_looks(V2)
    o4 = looks["lead_f"]["O4"]
    assert o4.parts and all(p.item_id for p in o4.parts)


# ---------------------------------------------------------------- 3 提示词探针 + episode_ready
def test_sop_gate_probe_is_build_first_not_golden():
    """探针口径（PLAN v4 1-4）：sop_gate.compile_preflight（PRODMERGE-O 实现）= build_first + preflight，不走 golden_v2 的单人镜限制"""
    cfg = json.loads((ROOT / "config" / "pipeline" / "sop_gate.json").read_text(encoding="utf-8"))
    assert "golden_v2" not in json.dumps(cfg.get("prompt_probe"))
    src = (ROOT / "tools" / "master" / "sop_gate.py").read_text(encoding="utf-8")
    body = src[src.index("def compile_preflight"):src.index("def _probe_subprocess")]
    code = body.split('"""')[2]                               # 去掉 docstring，只看代码
    assert "FJ.build_first(" in code and "PF.check(" in code and "golden" not in code and "祁念" not in code


def test_episode_ready_sheet_gap_owned_by_sheet_job(monkeypatch, tmp_path):
    import types
    sys.path.insert(0, str(ROOT / "tools" / "master"))
    import episode_ready as ER
    chars = [{"character": "lead_f", "name": "祁念", "presence": "在画", "look": "O4"}]
    warns = [{"character": "祁念", "kind": "造型参考用清单单品图", "detail": "x"}]
    src = tmp_path / "s.json"
    src.write_text(json.dumps({"episodes": [{"number": 1, "shots": [{"index": 1}, {"index": 8}]}]}), encoding="utf-8")
    from ns_agent import run_paths as RP
    monkeypatch.setattr(RP, "runs_module", lambda root: types.SimpleNamespace(script_path=lambda run, root: src))
    sr = types.SimpleNamespace(characters=chars, scene_id=None, missing=[], subject=None, zones=["face", "upper"], warnings=warns)
    monkeypatch.setattr(AR, "resolve_shot", lambda run, ep, s: sr)
    monkeypatch.setattr(AR, "manifest", lambda run: {"characters": {"lead_f": {"display_name": "祁念"}}})
    monkeypatch.setattr(ER, "character_gaps", lambda *a, **k: [])
    res = ER.check(V2, 1, tmp_path)
    assert not res["ready"] and len(res["gaps"]) == 1
    g = res["gaps"][0]
    assert (g["kind"], g["what"], g["shots"]) == ("look", "祁念 造型O4 没有设定图", [1, 8])
    assert "sheet-lead_f-O4" in g["owner"] and "写手" not in g["owner"]
