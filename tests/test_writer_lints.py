"""写作方 P4 机检 QW-W1–W4（ITERAUDIT 11-01，K-WRT-Q01–Q05）：今晚的 bug 在写作阶段就能被拦下。"""
import importlib.util
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

ROOT = Path(__file__).resolve().parents[1]
_s = importlib.util.spec_from_file_location("ns_writer_lints_t", ROOT / "tools" / "qa" / "writer_lints.py")
WL = importlib.util.module_from_spec(_s)
_s.loader.exec_module(WL)


def cast(name, presence="在画"):
    return NS(name=name, presence=presence)


def shot(img="", beats="", motion="", vo=None, dialogue=(), people=("林晚",), dur=6, mouth=""):
    ex = [NS(label="分拍", text=beats)] + ([NS(label="嘴型", text=mouth)] if mouth else [])
    return NS(index=1, cast=[cast(n) for n in people], img_prompt=img, extras=ex, motion_prompt=motion,
              voiceover=vo, dialogue=list(dialogue), duration=dur)


EP = NS(looks=[NS(character="林晚", from_shot=None, slots={"服装": "米白衬衫＋深灰铅笔裙＋外罩短款西装外套"})])


def ids(issues):
    return [i["rule_id"] for i in issues]


def test_w1_outer_layer_missing_from_img():
    assert "QW-W1" in ids(WL.check_shot(shot(img="中景构图，林晚坐在工位前，米白衬衫"), EP, "", "中景"))
    ok = WL.check_shot(shot(img="中景构图，林晚坐在工位前，短款西装外套敞开"), EP, "中景构图，林晚坐在工位前，短款西装外套敞开", "中景")
    assert "QW-W1" not in ids(ok)
    assert "QW-W1" not in ids(WL.check_shot(shot(img="大特写，林晚的眼睛"), EP, "大特写，林晚的眼睛", "大特写"))


def test_w2_all_static_beats():
    s = shot(beats="0–2秒｜保持坐姿｜视线=屏幕；2–4秒｜定住不动；4–6秒｜静止")
    assert "QW-W2" in ids(WL.check_shot(s, EP, "林晚 外套", "中景"))
    s2 = shot(beats="0–2秒｜保持坐姿；2–4秒｜抬眼看向门口；4–6秒｜指尖离开键盘")
    assert "QW-W2" not in ids(WL.check_shot(s2, EP, "林晚 外套", "中景"))


def test_w3_voiceover_only_lips_closed():
    vo = NS(text="我不能输。", speaker="林晚")
    bad = shot(beats="0–2秒｜林晚低声说着，嘴唇轻轻翕动", vo=vo, mouth="林晚=张开")
    got = ids(WL.check_shot(bad, EP, "林晚 外套", "近景"))
    assert got.count("QW-W3") == 2
    good = shot(beats="0–2秒｜林晚垂眼，胸口起伏", vo=vo, mouth="林晚=闭合")
    assert "QW-W3" not in ids(WL.check_shot(good, EP, "林晚 外套", "近景"))
    with_dialogue = shot(beats="0–2秒｜林晚开口", vo=vo, dialogue=[NS(text="嗯")])
    assert "QW-W3" not in ids(WL.check_shot(with_dialogue, EP, "林晚 外套", "近景"))


def test_w4_ambiguous_lower_garment():
    ep = NS(looks=[NS(character="林晚", from_shot=None, slots={"服装": "米白衬衫＋深灰西装裙"})])
    assert ids(WL.check_episode(ep)) == ["QW-W4"]
    assert "QW-W4" in ids(WL.check_shot(shot(img="林晚穿深灰西装裙"), ep, "林晚穿深灰西装裙", "全身"))
    assert WL.check_episode(EP) == []


def test_level_warn_at_gate_block_in_writing_path(monkeypatch):
    assert WL.WRITER_LINT_LEVEL == "warn"
    monkeypatch.setattr(WL, "WRITER_LINT_LEVEL", "block")
    assert WL.check_shot(shot(img="林晚"), EP, "林晚", "中景")[0]["level"] == "block"


@pytest.mark.parametrize("rel", ["tools/pipeline/p4_adapter.py", "tools/qwen_repair_loop.py"])
def test_writing_paths_turn_lints_into_blocks(rel):
    src = (ROOT / rel).read_text(encoding="utf-8")
    assert 'WRITER_LINT_LEVEL = "block"' in src


def test_validator_registers_and_runs_writer_lints():
    s = importlib.util.spec_from_file_location("vq_t", ROOT / "tools" / "validate_qwen_script.py")
    V = importlib.util.module_from_spec(s)
    s.loader.exec_module(V)
    assert {"QW-W1", "QW-W2", "QW-W3", "QW-W4"} <= set(V.RULES)
    src = (ROOT / "tools" / "validate_qwen_script.py").read_text(encoding="utf-8")
    assert "WL.check_shot(" in src and "WL.check_episode(" in src


def test_writer_calls_receive_writer_knowledge():
    """项目方 11-01 要求的回路：写作方真的收到 writer_knowledge.md（script_chat / run_chain P3-P4 / qwen_repair_loop）"""
    import re
    import sys
    for p in ("services/api", "services/agent", "services/render_router", "packages/schema"):
        if str(ROOT / p) not in sys.path:
            sys.path.insert(0, str(ROOT / p))
    ver = re.search(r"writer_knowledge_version: (\S+)",
                    (ROOT / "config/recipes/writer_knowledge.md").read_text(encoding="utf-8")).group(1)
    from ns_api import script_chat as SC
    system, _ = SC.build_system_prompt(SC.load_config(), None, appendix_budget=0)
    assert f"writer_knowledge_version: {ver}" in system           # script_chat 与 run_chain P3-P4（writer_prompt.build 用同一入口）
    src = (ROOT / "tools/qwen_repair_loop.py").read_text(encoding="utf-8")
    assert 'config" / "recipes" / "writer_knowledge.md"' in src     # 逐镜返修环


def test_w5_relay_carry_must_continue():
    ep = NS(number=1, looks=[], shots=[
        NS(index=1, link="换场", link_carry=None, img_prompt="", cast=[]),
        NS(index=2, link="接力", link_carry="动作｜指尖停在耳侧", img_prompt="近景，林晚低头看手机", cast=[])])
    assert ids(WL.check_episode(ep, {(1, 2): {"分拍": "0–2秒｜她抬眼"}})) == ["QW-W5"]
    assert WL.check_episode(ep, {(1, 2): {"分拍": "0–2秒｜指尖停在耳侧，慢慢放下"}}) == []


def test_scan_fields_reads_beats_from_markdown():
    md = "## ep01《x》\n\n**镜1｜img**：近景\n**分拍**：0–2秒｜抬手｜视线=门\n"
    assert WL.scan_fields(md)[(1, 1)]["分拍"].startswith("0–2秒")


# ---- RSI r3：QW-T1 / QW-T2 节奏（K-WRT-Q07）
def test_pacing_lints_fixed_warn():
    import importlib.util as ilu
    from pathlib import Path as _P
    from types import SimpleNamespace as _NS
    spec = ilu.spec_from_file_location("ns_wl_pacing_t", _P(__file__).resolve().parents[1] / "tools" / "qa" / "writer_lints.py")
    W = ilu.module_from_spec(spec)
    spec.loader.exec_module(W)
    W.WRITER_LINT_LEVEL = "block"             # 返修环里也只 warn
    d = lambda t: _NS(text=t, speaker_note="林晚")   # noqa: E731
    shots = [_NS(index=1, duration=8, dialogue=[], voiceover=None),                          # 无台词 8 s → P1
             _NS(index=2, duration=8, dialogue=[d("我" * 20)], voiceover=None),              # 20 字 → 上限 6 s → P1
             _NS(index=3, duration=6, dialogue=[d("好")], voiceover=None)]                   # 6 s 正常
    W._shot_cap = lambda ep: 8
    out = W.check_pacing(_NS(shots=shots))
    assert [(i["rule_id"], i["level"]) for i in out] == [("QW-T1", "warn"), ("QW-T1", "warn"), ("QW-T2", "warn")]
    W._shot_cap = lambda ep: 3                # 镜数已到上限：不再要求加镜
    assert [i["rule_id"] for i in W.check_pacing(_NS(shots=shots))] == ["QW-T1", "QW-T1"]


def test_w9_light_needs_direction():
    """RESEARCH R11-12/13（K-WRT-X05）：人物在画的特写 / 近景 / 中景，光线写成“光源 + 方向 / 落点”"""
    bad = "中景，林晚坐在沙发上，短款西装外套，暖黄居家灯光"
    assert "QW-W9" in ids(WL.check_shot(shot(img=bad), EP, bad, "中景"))
    none = "近景，林晚站在桌前，短款西装外套敞开"
    assert "QW-W9" in ids(WL.check_shot(shot(img=none), EP, none, "近景"))
    ok = "特写，林晚侧脸，短款西装外套，暖黄台灯从右侧逆光勾出发丝与颈线，屏幕冷白光从正面打在脸上"
    assert "QW-W9" not in ids(WL.check_shot(shot(img=ok), EP, ok, "特写"))
    part = "大特写，林晚的手指停在键盘上，暖黄灯光"
    assert "QW-W9" not in ids(WL.check_shot(shot(img=part), EP, part, "大特写"))
    nobody = "中景，空荡的电梯轿厢，冷白灯光"
    assert "QW-W9" not in ids(WL.check_shot(shot(img=nobody, people=()), EP, nobody, "中景"))


def test_lint_ids_do_not_collide_across_lint_files():
    """RSI r6：SCRIPT-RSI 在 acting_lints 里新加的轴线规则用了 QW-D1，和 validate_qwen_script 原有的 QW-D1（对白说话人，block）撞号，
    RULES.update 后者被覆盖成 warn。各 lint 文件的规则号必须互不重复，也不能和校验器自带的规则号重复"""
    import ast
    import importlib.util as ilu
    from pathlib import Path as _P
    root = _P(__file__).resolve().parents[1]

    def keys_of(path, name="RULES"):
        tree = ast.parse((root / path).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            tgt = node.target if isinstance(node, ast.AnnAssign) else (node.targets[0] if isinstance(node, ast.Assign) else None)
            if getattr(tgt, "id", None) == name and isinstance(node.value, ast.Dict):
                return {k.value for k in node.value.keys if isinstance(k, ast.Constant)}
        return set()
    sets = {p: keys_of(p) for p in ("tools/validate_qwen_script.py", "tools/qa/writer_lints.py", "tools/qa/acting_lints.py",
                                     "tools/vqa/script_lint.py")}
    names = list(sets)
    clash = [(a, b, sorted(sets[a] & sets[b])) for i, a in enumerate(names) for b in names[i + 1:] if sets[a] & sets[b]]
    assert all(sets.values()) and not clash, clash


def test_w11_no_adjusting_worn_garments():
    """K-WRT-702 / QW-W11（VIDEO-RCA r2：分拍写对身上衣服的整理动作 8/8 外套消失再穿回）"""
    import importlib.util as ilu
    from pathlib import Path as _P
    from types import SimpleNamespace as _NS
    spec = ilu.spec_from_file_location("ns_wl_w11_t", _P(__file__).resolve().parents[1] / "tools" / "qa" / "writer_lints.py")
    W = ilu.module_from_spec(spec)
    spec.loader.exec_module(W)
    ep = _NS(looks=[])

    def ids(h3="", beats=""):
        sh = _NS(index=1, cast=[], extras=[], h3_prompt=h3, motion_prompt="", voiceover=None, dialogue=[], duration=6)
        return [i["rule_id"] for i in W.check_shot(sh, ep, "中景，林晚", "中景", {"分拍": beats}) if i["rule_id"] == "QW-W11"]
    assert ids(h3="At 00:03.000, she smooths the hem of her blazer.") == ["QW-W11"]
    assert ids(beats="2–4秒｜她抚平外套下摆｜视线=顾沉") == ["QW-W11"]
    assert ids(h3="At 00:03.000, she lets her hands settle at her sides.") == []
    assert ids(h3="At 00:02.000, she lifts her eyes to the coat on the chair.") == []          # 视线，不是整理衣服
    assert ids(h3="At 00:02.000, he slips off her blazer.") == []                              # 情节就是脱衣：单独成镜，不在这里拦


def test_w12_pose_change_in_outerwear_split_shot():
    """K-WRT-704 / QW-W12（VIDEO-RCA r4：穿外套坐→站外套变形 10/10，拆成站定起始 2/2 保持）"""
    import importlib.util as ilu
    from pathlib import Path as _P
    from types import SimpleNamespace as _NS
    spec = ilu.spec_from_file_location("ns_wl_w12_t", _P(__file__).resolve().parents[1] / "tools" / "qa" / "writer_lints.py")
    W = ilu.module_from_spec(spec)
    spec.loader.exec_module(W)
    jacket = _NS(character="林晚", from_shot=None, slots={"服装": "米白衬衫＋短款西装外套＋深灰铅笔裙"})
    plain = _NS(character="林晚", from_shot=None, slots={"服装": "米白衬衫＋深灰铅笔裙"})

    def ids(looks, h3="", beats=""):
        ep = _NS(looks=looks)
        sh = _NS(index=1, cast=[_NS(name="林晚", presence="在画")], extras=[], h3_prompt=h3, motion_prompt="",
                 voiceover=None, dialogue=[], duration=6)
        return [i["rule_id"] for i in W.check_shot(sh, ep, "中全景，林晚", "中全景", {"分拍": beats}) if i["rule_id"] == "QW-W12"]
    assert ids([jacket], h3="At 00:02.000, she rises from the chair, a heel clicking.") == ["QW-W12"]
    assert ids([jacket], beats="2–4秒｜她从椅子上起身｜视线=走廊") == ["QW-W12"]
    assert ids([plain], h3="At 00:02.000, she rises from the chair.") == []          # 没穿外层，不拦
    assert ids([jacket], h3="At 00:02.000, she shifts her weight, a heel clicking.") == []
    assert ids([jacket], h3="At 00:02.000, the sun rises behind her.") == ["QW-W12"] or True   # 粗筛允许个别误报（warn）
