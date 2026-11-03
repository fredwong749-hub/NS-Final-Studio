"""HEADER-O 11-03（ISS-1103-011343-a0ff，L-126 完全切割）：写作链全局头 / 写手包按剧取，V2 不出现任何 V1 id；V1 行为不变。
另：写手包的运镜表从 config/director/camera_moves.yaml 自动注入（单一来源），集合 = 本剧 enabled 的那一组。"""
from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in ("services/api", "services/agent", "packages/schema", "tools/pipeline"):
    if str(ROOT / p) not in sys.path:
        sys.path.insert(0, str(ROOT / p))

from ns_api import script_chat as S  # noqa: E402
from ns_agent import camera_norm as CN  # noqa: E402

V2, V1 = "series10_v2", "series10_v1"
pytestmark = pytest.mark.skipif(not (ROOT / "data/pipeline/runs" / V2 / "P1_storyline.json").is_file()
                                or not (ROOT / "data/import/script_v2.json").is_file(), reason="需要真实仓库的 V1 导入稿和 V2 P1")


def v1_ids() -> set[str]:
    """V1 导入稿里全部人物（名 / id）和场景 id + 点名的 V1 触发词"""
    g = json.loads((ROOT / "data/import/script_v2.json").read_text(encoding="utf-8"))["globals"]
    out = {"lin_wan", "gu_chen", "lnwan01", "sk_office_night"}
    for c in g.get("character_registry") or []:
        out |= {c.get("name"), c.get("char_id")}
    for e in g.get("scene_library") or []:
        out.add(e.get("scene_id"))
    return {x for x in out if x}


def hits(text: str, run: str = V2) -> list[str]:
    """V1 导入稿 id（本测试独立算）+ 统一守卫词表（第二季 / 剧名 / 道具词 / V1 风格，按本剧 P1 白名单）"""
    return sorted(set(i for i in v1_ids() if i in text) | set(S.v1_hits(text, run)))


@pytest.fixture
def v2(monkeypatch):
    monkeypatch.setenv("NS_RUN", V2)


@pytest.fixture
def v1(monkeypatch):
    monkeypatch.setenv("NS_RUN", V1)


def test_v2_header_derived_from_own_run_only(v2):
    head, src = S.script_header(registry={})
    assert src == f"data/pipeline/runs/{V2}/P1_storyline.json"
    assert hits(head) == [], hits(head)
    story = json.loads((ROOT / "data/pipeline/runs" / V2 / "P1_storyline.json").read_text(encoding="utf-8"))
    for c in story["characters"]:
        assert f"| {c['name']} | {c['char_id']} |" in head
    for sc in story["scenes"]:
        assert f"| {sc['scene_id']} |" in head
    assert "sk_white_cyc" in head and "assets_v2/manifest.json" in head      # 资产包清单也是来源
    assert hits(S.compact_header(head)) == []
    # 显式给 run 与 NS_RUN 同口径；registry 也按本剧导入稿取
    assert S.script_header(registry={}, run=V2)[0] == head
    chars, scenes, used = S.registry_tables({"run": V2})
    assert hits(json.dumps([chars, scenes, used], ensure_ascii=False)) == []
    assert all("data/import/script_v2.json" != u for u in used)


GENERIC_FILES = ("config/script_chat_rules.md", "config/qwen_writer_system_prompt.txt", "config/script_chat_rules_appendix.md",
                 "config/recipes/writer_knowledge.md", "config/pipeline/examples/P1_storyline.json",
                 "config/pipeline/examples/P4_episode.md", "config/pipeline/prompts/P0-P1.md", "config/pipeline/prompts/P3-P4.md")
V2_NAMES = ("祁念", "黎岸", "江予白", "周序", "卓琳", "唐瑶")


def test_generic_rule_files_have_no_concrete_characters():
    """通用规则 / 示例只用通用写法（女主 A / 男主 B）：不出现 V1 或 V2 的任何具体人物"""
    for f in GENERIC_FILES:
        t = (ROOT / f).read_text(encoding="utf-8")
        assert hits(t) == [], (f, hits(t))
        assert not [n for n in V2_NAMES if n in t], f
    assert "non_legacy_scrub" not in S.load_config()          # 临时改写表已删
    assert not hasattr(S, "scrub_v1") and not hasattr(S, "scrub_for_run")


def test_v2_writer_pack_has_no_v1_ids_without_scrub(v2):
    """写手包 = 通用规则 + 全部附录节（触发词全命中）+ 运镜表 + 全局头；autoflow 链各段 system 原样（不经任何改写）检查"""
    ctx = "顾沉 陈宇 阿岚 两人 三人 多人 3p 林晚 亲密 配乐 首帧 场景 镜头 漆皮 高跟 乳环 对白 画外 夜 远景 转身"
    system, parts = S.build_system_prompt(S.load_config(), context=ctx, appendix_budget=None)
    assert hits(system) == [], hits(system)
    assert not any(p["name"].startswith("本剧专属") for p in parts)
    assert any(p["name"].startswith("剧本全局头") and p["path"].endswith(f"{V2}/P1_storyline.json") for p in parts)
    sp = importlib.util.spec_from_file_location("autoflow_for_header_o", ROOT / "tools/script_rsi/autoflow.py")
    af = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(af)
    import writer_prompt as WP
    extra = af.extra_system() + af.rubric_code_brief() + af.camera_brief()
    for link in ("P0-P1", "P1-P2", "P2-P3", "P3-P4"):
        t = WP.system_for(link) + extra
        assert hits(t) == [], (link, hits(t))


def test_v2_fails_closed(monkeypatch):
    monkeypatch.setenv("NS_RUN", "no_such_run_header_o")
    with pytest.raises(S.HeaderMissing):
        S.script_header(registry={})
    monkeypatch.setenv("NS_RUN", V2)
    with pytest.raises(S.HeaderMissing):              # 出口检查：出现 V1 id → 失败，不交给写手
        S.assert_no_v1("镜头里的林晚和 sk_office_night", run=V2)


def test_v2_rejects_v1_registry_source(v2):
    with pytest.raises(S.HeaderMissing):
        S.registry_tables({"run": V2, "from": ["data/import/script_v2.json"]})


def test_v1_behaviour_unchanged(v1):
    from ns_api import import_sources as IS
    head, src = S.script_header(registry={})
    cfg = S.load_config()
    want = IS.header_source(S.PRODUCTION_SCRIPT, S.REPO) or cfg["header_sources"][0]
    assert src == want                                   # 来源仍是 V1 导入记录推导的那份
    text = (S.REPO / src).read_text(encoding="utf-8")
    m = S.EP_HEAD_RE.search(text)
    raw = (text[: m.start()] if m else text).rstrip() + "\n"
    assert head.startswith(raw) and "lin_wan" in head and "lnwan01" in head
    S.assert_no_v1("林晚 lin_wan", run=V1)               # V1 不查


def test_v1_writer_pack_keeps_its_own_clauses(v1):
    """V1 专属条款从通用规则移到 config/script_chat_runs/series10_v1*.md，按剧注入：V1 写手包里仍然都在"""
    cfg = S.load_config()
    system, parts = S.build_system_prompt(cfg, context="顾沉 乳环 高跟 漆皮 **对白**", appendix_budget=None)
    for key in ("林晚入镜以 `lnwan01，` 开头", "雾霾天蓝色及腰直发", "lin_wan / gu_chen / chen_yu / ch_a_lan",
                "有系统角色锁的角色（林晚、顾沉、陈宇）", "ep01–08、49、51–58 素颜通勤", "林晚 22 岁",
                "**乳环**", "**阴环**", "手指甲为5厘米超长透明水晶甲", "**林晚日常与通勤**", "hh12clear", "林晚声线 = 22 岁成年女性",
                "顾沉角色锁“34岁”"):
        assert key in system, key
    assert any(p["name"] == "本剧专属·series10_v1.md" for p in parts)
    names = [x["name"] for x in S.appendix_sections(cfg)]
    assert names.count("A2 多人镜") == 1 and "A3c 饰品与装饰状态" in names
    a2 = next(x for x in S.appendix_sections(cfg) if x["name"] == "A2 多人镜")
    assert "顾沉" in a2["triggers"] and "两人" in a2["triggers"]      # V1 原触发词仍生效


def test_run_for_dir():
    assert S.run_for_dir(ROOT / "data/pipeline/runs" / V2) == V2
    assert S.run_for_dir(ROOT / "data/pipeline/runs" / V2 / "P4_ep01.md") == V2
    assert S.run_for_dir(ROOT / "tmp_somewhere") is None


# ---- 运镜：写手包只给本剧 enabled 的运镜（camera_moves.yaml 单一来源）
DISABLED_PHRASES = ("pan left", "pan right", "truck left", "truck right", "tilt up", "tilt down", "pedestal up",
                    "pedestal down", "arc shot", "tracking shot", "zoom in", "zoom out")


@pytest.mark.parametrize("run", [V2, V1])
def test_writer_pack_camera_set_equals_yaml_enabled(monkeypatch, run):
    monkeypatch.setenv("NS_RUN", run)
    system, parts = S.build_system_prompt(S.load_config(), context=None, appendix_budget=0)
    i = system.index(S.CAMERA_BLOCK_HEAD)
    block = system[i: system.find("\n\n========", i)]
    assert S.CAMERA_ROW_RE.findall(block) == CN.enabled_ids(run)
    assert any(p.get("path") == "config/director/camera_moves.yaml" for p in parts)
    low = system.lower()
    for ph in DISABLED_PHRASES:                     # 规则正文不再手写停用的运镜
        assert not re.search(r"\b" + re.escape(ph) + r"\b", low), ph
    for f in ("config/script_chat_rules.md", "config/qwen_writer_system_prompt.txt"):
        t = (ROOT / f).read_text(encoding="utf-8").lower()
        assert not any(re.search(r"\b" + re.escape(ph) + r"\b", t) for ph in DISABLED_PHRASES), f


def test_camera_block_follows_yaml(monkeypatch):
    """yaml 改了（启用 / 停用），写手包跟着变，不用改规则文件"""
    d = CN.vocab()
    fake = {**d, "moves": [{**m, "enabled": m["id"] == "static"} for m in d["moves"]]}
    monkeypatch.setattr(CN, "vocab", lambda: fake)
    monkeypatch.setattr(CN, "move", lambda mid: next((m for m in fake["moves"] if m["id"] == mid), None))
    txt, ids = S.camera_moves_block(V2)
    assert ids == ["static"] and S.CAMERA_ROW_RE.findall(txt) == ["static"]


def test_agent_packet_checks_without_rewriting(tmp_path, monkeypatch):
    """总调度 11-03：autoflow_agent 作业包不再用 v1_leak.redact 改写；完全切割的剧出现 V1 id → HeaderMissing，干净的包原样写出"""
    sp = importlib.util.spec_from_file_location("autoflow_agent_header_o", ROOT / "tools/script_rsi/autoflow_agent.py")
    ag = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(ag)
    run_dir = tmp_path / "clean_run_header_o"
    run_dir.mkdir()
    (run_dir / "CLEAN_CUT.json").write_text("{}", encoding="utf-8")

    class St:
        def set(self, **kw):
            pass
    sysm, user = "写手规则：女主 A 看向男主 B。", "本集提纲：女主 A 走进影棚。"
    pk = ag.packet(run_dir, St(), "P1", "writer", 1, "P0-P1", sysm, user, "json", [], 1)
    assert pk["user"] == user and pk["system"].startswith(sysm)          # 原样，不改写
    with pytest.raises(S.HeaderMissing):
        ag.packet(run_dir, St(), "P1", "writer", 1, "P0-P1", sysm, "提纲里混进了林晚和 sk_office_night", "json", [], 2)
    assert "VL.redact(" not in (ROOT / "tools/script_rsi/autoflow_agent.py").read_text(encoding="utf-8").split("def packet(")[1].split("\ndef ")[0]


def test_guard_covers_v1_leak_scope_and_whitelists_own_p1():
    """总调度 11-03：assert_no_v1 覆盖 v1_leak 原有范围（第二季人物 / 剧名 / 道具词 / V1 风格），词表在 config/v1_guard.json，只检查不改写"""
    g = json.loads((ROOT / "config/v1_guard.json").read_text(encoding="utf-8"))
    assert "门卡" in g["props"] and "lnwan01" in g["extra_ids"]
    s2_title = json.loads((ROOT / "data/pipeline/runs/series10_s2/P1_storyline.json").read_text(encoding="utf-8"))["title"]
    rej = sorted((ROOT / "data/pipeline/runs" / V2).glob("_rejected_*/writer_out_P1_a1.json"))
    rej_name = [c["name"] for c in json.loads(rej[0].read_text(encoding="utf-8"))["characters"]
                if c["name"] not in S.own_text(V2)][0] if rej else "林晚"                  # 本剧被退回稿里的人物
    for bad in (s2_title, rej_name, "漆皮之下", "门卡", "徕卡 S★", "选 R0 保持不变", "lin_wan"):
        with pytest.raises(S.HeaderMissing):
            S.assert_no_v1(f"写手包：{bad}。", run=V2)
    own = S.own_text(V2)
    assert "钢珠" in own and S.v1_hits("她把钢珠放进口袋", V2) == []              # 本剧 P1 自己用到的词放行
    assert S.v1_hits("[K-WRT-R01] 不写 Leica、Summilux", V2) == []               # 英文整词匹配 + 禁写清单放行
    text = "女主 A 走进影棚"
    assert S.assert_no_v1(text, run=V2) is None and text == "女主 A 走进影棚"
    import importlib.util as iu
    sp = iu.spec_from_file_location("v1_leak_t", ROOT / "tools/script_rsi/v1_leak.py")
    vl = iu.module_from_spec(sp)
    sp.loader.exec_module(vl)
    assert not hasattr(vl, "redact") and list(vl.PROP_LINE) == g["props"]           # 词表单一来源、没有改写函数


def test_v2_ep01_real_writer_pack_passes(v2):
    """V2 第 1 集真实 P3-P4 写手包（system + user，按本剧 P1 / P2 / P3 拼）不经任何改写通过统一守卫"""
    import writer_prompt as WP
    from ns_schema.storyline import check_storyline
    from ns_schema.episode_outline import check_outline
    from ns_schema.screenplay import check_screenplay
    d = ROOT / "data/pipeline/runs" / V2
    rd = lambda n: json.loads((d / n).read_text(encoding="utf-8"))   # noqa: E731
    sl = check_storyline(rd("P1_storyline.json")).obj
    ol = check_outline(rd("P2_ep01_outline.json")).obj
    sp = check_screenplay(rd("P3_ep01_screenplay.json")).obj
    assert sl is not None and ol is not None and sp is not None
    with S.run_scope(V2):
        pr = WP.build("P3-P4", {"storyline": sl, "outline": ol, "screenplay": sp, "episode": 1, "looks": rd("P1_looks.json")})
    assert hits(pr["system"]) == [] and hits(pr["user"]) == [], (hits(pr["system"]), hits(pr["user"]))
    S.assert_no_v1(pr["system"] + pr["user"], run=V2)


def test_writer_facing_rule_texts_have_no_v1_content():
    """ISS-1103-040621-005d：P4_ep02 包里的“顾沉”来自 QW-A5 例句。写手会看到的规则文案（校验器 RULES / LINT_RULE_TEXT、
    knowledge 的 writer_text / title / when / then）一律通用写法，不经改写就过统一守卫"""
    sys.path.insert(0, str(ROOT / "tools"))
    sp = importlib.util.spec_from_file_location("vqs_header_o", ROOT / "tools/validate_qwen_script.py")
    vq = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(vq)
    texts = [m for _lvl, m in vq.RULES.values()] + [str(v) for v in getattr(vq, "LINT_RULE_TEXT", {}).values()]
    assert hits("\n".join(texts)) == [], hits("\n".join(texts))
    import yaml
    for f in sorted((ROOT / "knowledge/rules").glob("*.yaml")):
        d = yaml.safe_load(f.read_text(encoding="utf-8"))
        for r in (d if isinstance(d, list) else (d or {}).get("rules") or []):
            keys = ("writer_text", "title", "when", "then") if str(r.get("domain", "")).startswith("writer") else ("writer_text",)
            t = "\n".join(str(r.get(k) or "") for k in keys)          # 证据（evidence 原文引用）不改，也不进写手包
            assert hits(t) == [], (f.name, r.get("id"), hits(t))
    from ns_schema import h3_lint  # noqa: F401  （亲密镜说话人文案已改“女主”）
    assert "亲密镜只让林晚发声" not in (ROOT / "packages/schema/ns_schema/h3_lint.py").read_text(encoding="utf-8")


def test_knowledge_compile_rejects_concrete_ids():
    """ISS-1103-042507-5b09：K-WRT-213 例子写死 sk_white_cyc 误拦其它剧。compile 检查：通用写作规则里出现任何剧的人物 / 场景 id 即失败"""
    sp = importlib.util.spec_from_file_location("kb_compile_header_o", ROOT / "tools/knowledge/compile.py")
    kc = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(kc)
    ids = kc.concrete_ids(ROOT)
    assert {"sk_white_cyc", "lead_f", "lin_wan", "sk_office_night", "lnwan01"} <= ids
    rules = kc.load_rules(kc.KB / "rules")
    assert kc.concrete_id_check(kc.active(rules), ROOT) == []                         # 现行知识库干净
    bad = [{"id": "K-WRT-999", "writer_text": "例：**场景**：sk_white_cyc｜【幻想段】"}, {"id": "K-WRT-998", "writer_text": "例：sk_xxx"}]
    errs = kc.concrete_id_check(bad, ROOT)
    assert len(errs) == 1 and "K-WRT-999" in errs[0]
    wk = (ROOT / "config/recipes/writer_knowledge.md").read_text(encoding="utf-8")
    assert "sk_white_cyc" not in wk and "sk_xxx" in wk
