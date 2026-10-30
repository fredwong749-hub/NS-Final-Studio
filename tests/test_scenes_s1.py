"""S1（fredw-92/S-back）：场景表 + 每镜 **场景** 行的导入与格式校验。合成占位剧本（格式占位，不是剧情文本）。"""
import importlib.util
from pathlib import Path

from ns_agent.importer.script_md import import_script
from ns_schema.script import ScriptImport

ROOT = Path(__file__).resolve().parent.parent


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


T = _load("_t_vqs", "tests/test_validate_qwen_script.py")   # 复用占位剧本生成器（episode / shot）
V = T.V
STRICT = _load("_t_vss", "tools/validate_script_strict.py")

HEAD = "| 场景id | 名称 | 空间描述 | 时段 | 光线 | 固定陈设 |\n|---|---|---|---|---|---|\n"
GLOBAL = ("# 全局头\n\n**全剧场景表**：\n" + HEAD +
          "| sk_place_a | 占位名称A | 占位空间A | 占位时段A | 占位光线A | 占位陈设A |\n\n---\n\n")


def scene_shot(i, sid="sk_place_a", detail="占位细节"):
    text = T.shot(i)
    line = f"**场景**：{sid}｜{detail}" if detail is not None else f"**场景**：{sid}"
    head, rest = text.split("\n\n", 1)
    return f"{head}\n{line}\n\n{rest}"


def ep_text(n=1, shots=None, table=""):
    shots = shots or [scene_shot(i) for i in range(1, 7)]
    body = T.episode(shots).replace("## ep01《", f"## ep{n:02d}《")
    if table:
        body = body.replace("\n\n**镜1｜img**", f"\n\n**本集场景表**：\n{HEAD}{table}\n\n**镜1｜img**", 1)
    return body


def write(tmp_path, text, name="s.md"):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


def rules(rep, level="block"):
    out = [i["rule_id"] for i in rep.get("global_issues", []) if i["level"] == level]
    for ep in rep["episodes"]:
        out += [i["rule_id"] for i in ep["issues"] if i["level"] == level]
        out += [i["rule_id"] for s in ep["shots"] for i in s["issues"] if i["level"] == level]
    return out


def test_import_scene_library_and_shot_fields(tmp_path):
    table = "| sk_place_b | 占位名称B | 占位空间B | 占位时段B | 占位光线B | 占位陈设B |\n"
    shots = [scene_shot(1), scene_shot(2, "sk_place_b", "占位细节二")] + [scene_shot(i) for i in range(3, 7)]
    imp = import_script(write(tmp_path, GLOBAL + ep_text(1, shots, table)))
    lib = {e.scene_id: e for e in imp.globals.scene_library}
    assert set(lib) == {"sk_place_a", "sk_place_b"}
    a = lib["sk_place_a"]
    assert (a.name, a.space, a.time_of_day, a.light, a.fixtures) == ("占位名称A", "占位空间A", "占位时段A", "占位光线A", "占位陈设A")
    assert a.defined_in == [None] and lib["sk_place_b"].defined_in == [1]
    s1, s2 = imp.episodes[0].shots[:2]
    assert (s1.scene_id, s1.scene_detail) == ("sk_place_a", "占位细节")
    assert (s2.scene_id, s2.scene_detail) == ("sk_place_b", "占位细节二")
    assert s1.img_prompt and s1.motion_prompt               # 场景行不打断其它字段
    assert not any("无法归属" in w or "场景" in w for w in imp.warnings), imp.warnings
    # 往返 JSON（script_v2.json）
    assert ScriptImport.model_validate_json(imp.model_dump_json()).globals.scene_library[1].scene_id == "sk_place_b"


def test_old_script_without_scenes_still_imports_and_passes_gate(tmp_path):
    p = write(tmp_path, T.episode())
    imp = import_script(p)
    assert imp.globals.scene_library == [] and imp.episodes[0].shots[0].scene_id is None
    rep = V.validate(p)
    assert rep["blocking"] == 0, rules(rep)
    assert "QW-SC1" not in rules(rep, "warn")               # 旧剧本：导入关口不报
    assert "QW-SC1" in rules(STRICT.strict_validate(p))     # 剧本创作（严格）必须有场景


def test_validator_scene_rules(tmp_path):
    ok = write(tmp_path, GLOBAL + ep_text(), "ok.md")
    rep = V.validate(ok)
    assert not [r for r in rules(rep) if r.startswith("QW-SC")], rules(rep)
    assert not [r for r in rules(STRICT.strict_validate(ok)) if r.startswith("QW-SC")]
    shots = [scene_shot(1, "sk_nope"), scene_shot(2, "Bad-ID"), scene_shot(3, detail=None)] + \
        [T.shot(4)] + [scene_shot(i) for i in (5, 6)]
    rep = V.validate(write(tmp_path, GLOBAL + ep_text(1, shots), "bad.md"))
    by = {s["index"]: [i["rule_id"] for i in s["issues"]] for s in rep["episodes"][0]["shots"]}
    assert "QW-SC3" in by[1] and "QW-SC2" in by[2] and "QW-SC6" in by[3] and "QW-SC1" in by[4]
    lvl = {(s["index"], i["rule_id"]): i["level"] for s in rep["episodes"][0]["shots"] for i in s["issues"]}
    assert lvl[(4, "QW-SC1")] == "block" and lvl[(3, "QW-SC6")] == "warn"   # 有场景表 → 缺场景是 block
    assert "QW-SC1" in rep["episodes"][0]["shots"][3]["repair"]


def test_cross_episode_conflict_and_table_format(tmp_path):
    same = "| sk_place_a | 占位名称A |  | 占位时段A | 占位光线A | 占位陈设A |\n"          # 空格 = 沿用，不算冲突
    diff = "| sk_place_a | 占位名称A | 另一个空间 | 占位时段A | 占位光线A | 占位陈设A |\n"
    text = GLOBAL + ep_text(1, table=same) + "\n" + ep_text(2, table=diff)
    p = write(tmp_path, text)
    imp = import_script(p)
    e = imp.globals.scene_library[0]
    assert e.space == "占位空间A" and e.defined_in == [None, 1, 2]
    assert [(c.field, c.episode) for c in e.conflicts] == [("空间描述", 2)]
    assert any("sk_place_a" in w and "空间描述" in w for w in imp.warnings)
    rep = V.validate(p)
    eps = {e["number"]: [i["rule_id"] for i in e["issues"] if i["level"] == "block"] for e in rep["episodes"]}
    # fredw-92/D2：全剧场景表（继承）登记被改写 = QW-SC9（附原文）；集间改写仍是 QW-SC5（见下）
    assert "QW-SC9" not in eps[1] and "QW-SC9" in eps[2] and "QW-SC5" not in eps[2]
    tb1, tb2 = "| sk_place_b | 名B | 空B | 时B | 光B | 陈B |\n", "| sk_place_b | 名B | 空B2 | 时B | 光B | 陈B |\n"
    loc = ep_text(1, table=tb1) + "\n" + ep_text(2, table=tb2)
    rep = V.validate(write(tmp_path, GLOBAL + loc, "loc.md"))
    eps = {e["number"]: [i["rule_id"] for i in e["issues"] if i["level"] == "block"] for e in rep["episodes"]}
    assert "QW-SC5" in eps[2]
    # 表格格式：缺格 / 表头不对
    bad = GLOBAL.replace("| 占位陈设A |", "|") + ep_text(1)
    rep = V.validate(write(tmp_path, bad, "fmt.md"))
    assert "QW-SC4" in [i["rule_id"] for i in rep["global_issues"]] and rep["blocking"] > 0
    bad2 = GLOBAL.replace("| 光线 |", "| 灯光 |") + ep_text(1)
    rep = V.validate(write(tmp_path, bad2, "fmt2.md"))
    assert any(i["rule_id"] == "QW-SC4" and "表头" in i["detail"] for i in rep["global_issues"])


def test_merge_globals_merges_scene_library():
    from ns_schema.script import SceneEntry, ScriptGlobals
    import sys
    sys.path.insert(0, str(ROOT / "tools"))
    from import_script import merge_globals
    base = ScriptGlobals(scene_library=[SceneEntry(scene_id="sk_a", name="A"), SceneEntry(scene_id="sk_b", name="B")])
    new = ScriptGlobals(scene_library=[SceneEntry(scene_id="sk_b", name="B2")])
    g = merge_globals(base, new)
    # fredw-92 2026-10-31 定：登记表先登记为准（冲突不覆盖），新场景追加（fredw-92/D2 改期望）
    assert [(e.scene_id, e.name) for e in g.scene_library] == [("sk_a", "A"), ("sk_b", "B")]


def test_compact_header_keeps_scene_table():
    from ns_api.script_chat import compact_header
    header = ("**每条prompt统一前缀**：\n```\n【林晚】占位锁\n```\n\n" + GLOBAL.split("\n\n---")[0])
    out = compact_header(header)
    assert "**全剧场景表**" in out and "| sk_place_a |" in out and "【林晚】占位锁" in out
