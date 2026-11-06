"""PS-MASTER 11-07（W-S234）：P1 版本 sha 去掉 L-203 背景视向子场景（parent 非空）与 _by——
项目方对 P1 的放行管故事 / 人物 / 母场景；总调度登记子场景不让放行失效，改母场景或人物仍然失效。"""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_sp = importlib.util.spec_from_file_location("owner_gate_p1sha", ROOT / "tools/script_rsi/owner_gate.py")
OG = importlib.util.module_from_spec(_sp)
_sp.loader.exec_module(OG)

BASE = {"schema": "nsfs.storyline/1", "title": "T", "premise": "P", "world": {"setting": "S"},
        "characters": [{"name": "祁念", "role": "lead"}],
        "scenes": [{"scene_id": "sk_bar", "name": "天台酒吧", "space": "露天", "time_of_day": "夜", "light": "霓虹", "fixtures": "吧台"}],
        "episodes": [{"episode": 1, "title": "E1", "logline": "L", "characters": ["祁念"], "scenes": ["sk_bar"]}]}


def _txt(d) -> str:
    return json.dumps(d, ensure_ascii=False, indent=1)


def _with_sub(d):
    d = copy.deepcopy(d)
    d["scenes"].append({"scene_id": "sk_bar_rev", "name": "天台酒吧（反打）", "space": "露天", "time_of_day": "夜", "light": "霓虹",
                        "fixtures": "吧台", "parent": "sk_bar", "_by": "PS-MASTER L-203"})
    return d


def test_plain_p1_sha_equals_raw_text_sha():
    t = _txt(BASE)
    assert OG.p1_sha(t) == hashlib.sha256(t.encode("utf-8")).hexdigest()[:16]     # 旧放行记录逐字有效


def test_adding_parent_subscene_keeps_sha():
    assert OG.p1_sha(_txt(_with_sub(BASE))) == OG.p1_sha(_txt(BASE))
    d = _with_sub(BASE)
    d["scenes"][0]["_by"] = "PS-MASTER"                                           # 母场景只多登记人也不算改稿
    assert OG.p1_sha(_txt(d)) == OG.p1_sha(_txt(BASE))


def test_changing_parent_scene_or_character_changes_sha():
    d = _with_sub(BASE)
    d["scenes"][0]["light"] = "烛灯暖金"
    assert OG.p1_sha(_txt(d)) != OG.p1_sha(_txt(BASE))
    d = _with_sub(BASE)
    d["characters"][0]["role"] = "villain"
    assert OG.p1_sha(_txt(d)) != OG.p1_sha(_txt(BASE))


def test_owner_direction_survives_subscene_registration(tmp_path):
    rd = tmp_path / "run"
    (rd / "judge_p1").mkdir(parents=True)
    canon = rd / "P1_storyline.json"
    canon.write_text(_txt(BASE), encoding="utf-8")
    (rd / "judge_p1/STATE.json").write_text(json.dumps({"rounds": [{"n": 1, "sha": OG.p1_sha(_txt(BASE))}],
                                                        "owner_direction": {"sha": OG.p1_sha(_txt(BASE)), "by": "总调度"}}), encoding="utf-8")
    assert OG.owner_direction(rd)
    canon.write_text(_txt(_with_sub(BASE)), encoding="utf-8")
    assert OG.owner_direction(rd)                                                 # 登记子场景后放行仍有效
    d = _with_sub(BASE)
    d["scenes"][0]["light"] = "烛灯暖金"
    canon.write_text(_txt(d), encoding="utf-8")
    assert OG.owner_direction(rd) is None                                         # 改母场景 = 换稿，放行失效
