"""W7 · IMPORT-FOLLOWUP（11-03）：A2 第 18 轮审 W2 后的 P1 / P2 收尾。

P1-① 归档剧（V1 series10_v1）编译冻结：W2 后导入器把 光线 / 分拍 / 镜头语言段收进 shot.extras，V1 源稿重导会改视线落点；
     frame_job.freeze_archived_extras 把归档剧的 shot.extras 过滤回旧集合 → 用 V1 真实源稿，旧集合导入 vs 新集合导入编出的 prompt_sha 相同
P2 F3 镜头语言 v2 七段（shot_spec_v2.yaml md_label）全进 shot.extras；F4 带括注 label 编译端读得到；
   F5 episode_ready“没有设定图”缺口 owner = sheet 资产作业（无论哪条路径先到）；F6 load_looks 资产包分支带上 hub_extra_looks
"""
import json
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in ("services/agent", "packages/schema", "services/render_router", "packages/qc", "services/recipes", ""):
    if str(ROOT / p) not in sys.path:
        sys.path.insert(0, str(ROOT / p))

from ns_agent import asset_refs as AR  # noqa: E402
from ns_agent import frame_job as FJ  # noqa: E402
from ns_agent import shot_language as SL  # noqa: E402
from ns_agent.importer import script_md as M  # noqa: E402

V1 = "series10_v1"
V1_MD = ROOT / "data" / "staging_v3" / "merged" / "漆皮之下·十日_series10_v1_ep01-10.md"
HAVE_V1 = V1_MD.is_file() and AR._archived(V1) and bool(AR.project_cfg(V1))


# ---------------------------------------------------------------- F3 七段单一来源
def test_shot_extra_labels_cover_shot_spec_v2_segments():
    import yaml
    spec = yaml.safe_load((ROOT / "config/director/shot_spec_v2.yaml").read_text(encoding="utf-8"))
    labs = {s["md_label"].strip("*：: ") for s in spec["segments"]}
    assert len(labs) == 7 and labs <= M.SHOT_EXTRA_LABELS
    assert labs == set(M.SHOT_SPEC_FALLBACK)                  # 兜底与 yaml 同内容
    assert M.LEGACY_SHOT_EXTRA_LABELS <= M.SHOT_EXTRA_LABELS and {"光线", "分拍"} <= M.SHOT_EXTRA_LABELS


MD = """## ep01《t》

**镜1｜img**：近景，祁念站着
**机位与景别**：近景，平视
**运镜**：固定机位
**灯光（动机）**：动机光源=顶光
**构图（三分）**：前景=手
**分拍**：0–2秒｜抬手｜视线=灯架后的方向
**声音**：环境=风扇
**时长**：4秒
"""


def _shot(tmp_path):
    md = tmp_path / "p4.md"
    md.write_text(MD, encoding="utf-8")
    ep = M.import_script(md).episodes[0]
    return ep, ep.shots[0]


def test_seven_segments_land_on_shot_and_labels_unchanged(tmp_path):
    ep, sh = _shot(tmp_path)
    labs = [e.label for e in sh.extras]
    assert labs == ["机位与景别", "运镜", "灯光（动机）", "构图（三分）", "分拍", "声音"]   # label 原样保留
    assert not ep.extras


# ---------------------------------------------------------------- F4 括注 label
def test_script_field_reads_parenthesized_labels(tmp_path):
    _, sh = _shot(tmp_path)
    assert SL.script_field(sh, "lighting") == "动机光源=顶光"
    assert SL.script_field(sh, "composition") == "前景=手"
    assert FJ.first_beat_gaze(sh) == "灯架后的方向"


# ---------------------------------------------------------------- P1-① 归档剧编译冻结
def test_freeze_filters_only_archived(tmp_path, monkeypatch):
    _, sh = _shot(tmp_path)
    monkeypatch.setattr(AR, "_archived", lambda p: p == "arch")
    assert FJ.freeze_archived_extras("live", sh) is sh
    fz = FJ.freeze_archived_extras("arch", sh)
    assert fz.extras == [] and len(sh.extras) == 6          # 不改原对象
    assert FJ.first_beat_gaze(fz) == ""                    # 旧行为：分拍在集级，读不到
    d = {"extras": [{"label": "口型（男）", "text": "a"}, {"label": "分拍", "text": "b"}]}
    assert FJ.freeze_archived_extras("arch", d)["extras"] == [{"label": "口型（男）", "text": "a"}]


def _sha_by_labels(labels, monkeypatch, eps=(1, 6)):
    import hashlib
    monkeypatch.setattr(M, "SHOT_EXTRA_LABELS", set(labels))
    s = M.import_script(V1_MD)
    out = {}
    for e in s.episodes:
        if int(e.number) in eps:
            for sh in e.shots:
                job = FJ.build_first(V1, e, sh, s.globals)
                out[f"ep{int(e.number):02d}-S{sh.index}"] = hashlib.sha256(job["prompt"].encode("utf-8")).hexdigest()[:16]
    return out


@pytest.mark.skipif(not HAVE_V1, reason="V1 源稿 / 登记不在本机")
def test_v1_archived_prompt_sha_unchanged_by_new_importer(monkeypatch):
    """A2 第 18 轮 P1-①：同一份 V1 源稿，W2 前旧集合导入 vs 现行集合导入，归档剧编出的 prompt_sha 逐镜相同
    （冻结前 ep01-S6/S7、ep06-S5/S6 会变）。旧集合导入时 shot.extras 全在旧集合内，冻结是空操作 = W2 之前的提示词。
    再关掉冻结对照一次：这 4 镜必须变（证明本测试有牙齿，不是两边都没读 extras）"""
    full = M.SHOT_EXTRA_LABELS | set()
    old = _sha_by_labels(M.LEGACY_SHOT_EXTRA_LABELS, monkeypatch)
    new = _sha_by_labels(full, monkeypatch)
    assert len(old) == 15 and old == new
    monkeypatch.setattr(FJ, "freeze_archived_extras", lambda project, shot: shot)
    raw = _sha_by_labels(full, monkeypatch)
    assert {k for k in old if old[k] != raw[k]} == {"ep01-S6", "ep01-S7", "ep06-S5", "ep06-S6"}


# ---------------------------------------------------------------- F5 episode_ready owner
def _er(monkeypatch, tmp_path, missing, warns):
    sys.path.insert(0, str(ROOT / "tools" / "master"))
    import episode_ready as ER
    chars = [{"character": "lead_f", "name": "祁念", "presence": "在画", "look": "O5"}]
    src = tmp_path / "s.json"
    src.write_text(json.dumps({"episodes": [{"number": 2, "shots": [{"index": 1}, {"index": 2}]}]}), encoding="utf-8")
    from ns_agent import run_paths as RP
    monkeypatch.setattr(RP, "runs_module", lambda root: types.SimpleNamespace(script_path=lambda run, root: src))
    sr = types.SimpleNamespace(characters=chars, scene_id=None, missing=missing, subject=None, zones=["face", "upper"], warnings=warns)
    monkeypatch.setattr(AR, "resolve_shot", lambda run, ep, s: sr)
    monkeypatch.setattr(AR, "manifest", lambda run: {"characters": {"lead_f": {"display_name": "祁念"}}})
    monkeypatch.setattr(ER, "character_gaps", lambda *a, **k: [])
    return ER.check("series10_v2", 2, tmp_path)


def test_episode_ready_no_item_image_sheet_gap_goes_to_sheet_job(monkeypatch, tmp_path):
    """造型没有任何单品图：asset_refs 发 missing“资产缺图 / 没有设定图”（不是 warns）→ 仍归 sheet-<cid>-<造型> 作业"""
    res = _er(monkeypatch, tmp_path, [{"character": "祁念", "kind": "资产缺图", "detail": "祁念 造型O5 没有设定图"}], [])
    assert len(res["gaps"]) == 1
    g = res["gaps"][0]
    assert (g["kind"], g["shots"]) == ("look", [1, 2])
    assert "sheet-lead_f-O5" in g["owner"] and "写手" not in g["owner"]


def test_episode_ready_both_paths_merge_keep_sheet_owner(monkeypatch, tmp_path):
    res = _er(monkeypatch, tmp_path, [{"character": "祁念", "kind": "资产缺图", "detail": "祁念 造型O5 没有设定图"}],
              [{"character": "祁念", "kind": "造型参考用清单单品图", "detail": "x"}])
    assert len(res["gaps"]) == 1 and "sheet-lead_f-O5" in res["gaps"][0]["owner"]


def test_episode_ready_item_gap_owner_unchanged(monkeypatch, tmp_path):
    res = _er(monkeypatch, tmp_path, [{"character": "祁念", "kind": "资产缺图", "detail": "祁念 造型O5 的 鞋 没有单品图"}], [])
    assert res["gaps"][0]["kind"] == "item" and "sheet-" not in res["gaps"][0]["owner"]


# ---------------------------------------------------------------- F6 hub_extra_looks 在资产包分支
def test_manifest_branch_appends_hub_extra_looks(monkeypatch):
    man = {"characters": {"lead_f": {"display_name": "祁念", "looks": {"O4": {"name": "O4", "items": {}}}}}}
    monkeypatch.setattr(AR, "chain_files", lambda p, k: [])
    monkeypatch.setattr(AR, "manifest_rel", lambda p: "assets_v2/manifest.json")
    monkeypatch.setattr(AR, "manifest", lambda p: man)
    monkeypatch.setattr(AR, "_hub", lambda path, p, inherit=False: {"lead_f": [{"id": "O9", "use": "派对", "zh": "服装=红色吊带裙"},
                                                                                {"id": "O4", "zh": "重复的忽略"}]}
                        if path == AR.HUB_LOOKS else {})
    looks = AR.load_looks("tmp_run")
    assert set(looks["lead_f"]) == {"O4", "O9"}
    assert looks["lead_f"]["O4"].zh == "服装=O4"              # 清单为准
    assert looks["lead_f"]["O9"].use == "派对"
