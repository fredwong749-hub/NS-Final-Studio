"""W5 UIUX 11-03（项目方 L-155“uiux 很难用，难理解，把它修了吧”；L-146 步骤条 + 进度矩阵；C-09 / C-10 / C-17 / C-20）。

1) 只读聚合 GET /api/sop/stepbar（ns_api/sop.py）：六步只是 sop_gate.STAGES 的分组（不另定义阶段）；计数 = 完成 / 进行中 / 卡住；
   卡点来自 report_issue 未关项：正在这一步 + 阻断 = 卡住；还没到这一步 = 只提醒不标红；sop_gate 原文 why 不进接口；卡点原文去掉文件名 / 作业 id。
2) 导航收敛不删功能：20 个旧路由都在 v3/pageMap.ts 登记了入口，且入口真的存在（步骤条 / 待办 / 设置 ▾ / 设置页“全部页面” / 总览）。
3) 每页顶部一句话 + 404 页；首页 / = 全剧总览；#/inbox → #/queue。
4) #/queue 每条只有“批准 / 用这张”+“修改”，没有“不同意 / 稍后”；点了原地显示“已收到，系统处理中”。
"""
import importlib.util
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "apps" / "web" / "src"
sys.path.insert(0, str(ROOT / "services" / "api"))

from ns_api import sop as SOP  # noqa: E402


def read(p: str) -> str:
    return (WEB / p).read_text(encoding="utf-8")


def code_only(src: str) -> str:
    return "\n".join(ln for ln in src.splitlines() if not ln.strip().startswith(("//", "/*", "*", "{/*")))


def _gate():
    spec = importlib.util.spec_from_file_location("t_sop_gate", ROOT / "tools" / "master" / "sop_gate.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _cell(state, plain="", why="原文 tools/x.py"):
    return {"state": state, "plain": plain or state, "why": why}


def _pipe():
    steps = [{"id": s, "label": lbl} for s, lbl in zip(SOP.STEP_IDS, ["剧本", "资产", "分镜", "出图", "视频", "成片"])]
    ep1 = {"episode": 1, "stage": "资产就绪", "plain": "停在“资产就绪”", "retro": None,
           "cells": {"script": _cell("done"), "assets": _cell("doing", "还差 3 项资产"), "board": _cell("todo"),
                     "frames": _cell("todo"), "video": _cell("todo"), "cut": _cell("todo")}}
    ep2 = {"episode": 2, "stage": "导入闸门", "plain": "停在“导入闸门”", "retro": None,
           "cells": {"script": _cell("doing", "剧本还有 2 处要改"), **{s: _cell("todo") for s in SOP.STEP_IDS[1:]}}}
    ep3 = {"episode": 3, "stage": "剧本", "plain": "", "retro": None, "cells": {s: _cell("todo") for s in SOP.STEP_IDS}}
    return {"run": "r", "title": "测试剧", "episodes_total": 3, "steps": steps, "episodes": [ep1, ep2, ep3]}


ISSUES = [
    {"id": "ISS-1", "run": "r", "episode": 2, "step": "6 补丁环", "who": "MASTER-WSL", "blocking": True, "status": "open",
     "what": "资产作业 sheet-ch_jiang_yubai-A（江予白）连续失败：seed 1200：q9=fail", "time": "2026-11-03 02:00:00"},
    {"id": "ISS-2", "run": "r", "episode": 1, "step": "9", "who": "SYSAUDIT-F", "blocking": True, "status": "open",
     "what": "V2 视频链没有进程：data/x.json 坏", "time": "2026-11-03 03:00:00"},
    {"id": "ISS-3", "run": "r", "episode": 1, "step": "8 资产就绪", "who": "ASSET-WORKER", "blocking": False, "status": "open",
     "what": "提醒一下", "time": "2026-11-03 03:00:00"},
]


# ---------------------------------------------------------------- 1) 只读聚合
def test_six_steps_are_only_a_grouping_of_sop_gate_stages():
    G = _gate()
    flat = [st for sid in SOP.STEP_IDS for st in SOP.STEP_STAGES[sid]]
    assert flat == list(G.STAGES), "步骤条的阶段必须正好是 sop_gate.STAGES（不许另定义一套）"
    assert SOP.STEP_IDS == ("script", "assets", "board", "frames", "video", "cut")


def test_stepbar_counts_blocked_and_ahead():
    v = SOP.stepbar_view(_pipe(), ISSUES)
    cnt = {s["id"]: s for s in v["steps"]}
    assert (cnt["script"]["done"], cnt["script"]["doing"], cnt["script"]["blocked"], cnt["script"]["todo"]) == (1, 0, 1, 1)
    assert (cnt["assets"]["done"], cnt["assets"]["doing"], cnt["assets"]["blocked"]) == (0, 1, 0)   # 非阻断卡点不改状态
    assert cnt["frames"]["blocked"] == 0                                                          # 还没到“出图”：不标红
    e1, e2 = v["episodes"][0]["cells"], v["episodes"][1]["cells"]
    assert e2["script"]["state"] == "blocked" and e2["script"]["owner"] == "总调度"
    assert e2["script"]["plain"] == "剧本还有 2 处要改" and "江予白" in e2["script"]["block"]
    assert e1["frames"]["state"] == "todo" and e1["frames"]["ahead"] and e1["frames"]["block"].startswith("已知要先解决")
    assert e1["assets"]["owner"] == "系统 · 资产作业" and e1["assets"]["issues"][0]["blocking"] is False
    assert v["now"]["focus"]["episode"] == 1 and v["now"]["focus"]["step"] == "assets"
    assert [b["episode"] for b in v["now"]["blocked"]] == [2]
    assert v["issues_open"] == 3 and v["unplaced"] == 0


def test_no_raw_text_leaks_to_the_page():
    v = SOP.stepbar_view(_pipe(), ISSUES)
    blob = repr(v)
    assert "why" not in {k for e in v["episodes"] for c in e["cells"].values() for k in c}       # sop_gate 原文不进接口
    for bad in ("tools/x.py", "sheet-ch_jiang_yubai-A", "q9=fail", "data/x.json", "seed 1200"):
        assert bad not in blob, bad


def test_issue_step_and_owner_mapping():
    assert SOP.issue_step("8 资产就绪") == "assets" and SOP.issue_step("6 补丁环") == "script"
    assert SOP.issue_step("9") == "frames" and SOP.issue_step("10") == "video" and SOP.issue_step("delegate") == "script"
    assert SOP.issue_step("整集预览") == "cut" and SOP.issue_step("") is None
    assert SOP.owner_label("MASTER-WSL") == "总调度" and SOP.owner_label("项目方") == "你"
    assert SOP.owner_label("ASSET-WORKER").startswith("系统")
    assert len(SOP.issue_plain("一" * 200)) <= 40


def test_route_registered_without_touching_app():
    from ns_api import app as A
    assert "/api/sop/stepbar" in A.app.openapi()["paths"]
    src = (ROOT / "services" / "api" / "ns_api" / "sop.py").read_text(encoding="utf-8")
    assert "_report_issue().load()" in src and "_PSTAT.pipeline_status(run)" in src            # 只调这两个来源，不另算


# ---------------------------------------------------------------- 2) 导航收敛不删功能
OLD_ROUTES = ["#/script-create", "#/assets", "#/frames", "#/videos", "#/sound", "#/script-chat", "#/overview", "#/cut",
              "#/queue", "#/models", "#/image-edit", "#/script-ab", "#/audit", "#/v1-library", "#/trash", "#/settings",
              "#/projects", "#/inbox", "#/assets-v1", "#epNN"]


def _page_map() -> dict[str, str]:
    src = read("v3/pageMap.ts")
    return dict(re.findall(r'\{ hash: "([^"]+)", name: "[^"]+", where: "([^"]+)"', src))


def test_all_twenty_old_routes_have_an_entry():
    pm = _page_map()
    assert len(OLD_ROUTES) == 20
    for r in OLD_ROUTES:
        assert r in pm, f"{r} 没登记入口（L-146：旧功能不删只移位）"
    v3 = re.findall(r'"(#/[a-z0-9-]+)"', read("v3/TopBarV3.helpers.ts"))
    for r in v3:
        assert r in pm, f"路由 {r} 没写进 pageMap"
        assert f'"{r}": lazy(' in read("App.tsx"), f"{r} 的页面组件被删了"


def test_entries_really_exist_in_the_ui():
    top = read("v3/TopBarV3.tsx")
    pm = _page_map()
    steps = re.findall(r'to: "(#/[a-z-]+|canvas)"', top)
    assert steps == ["#/script-create", "#/assets", "canvas", "#/frames", "#/videos", "#/cut"]          # ①–⑥
    tools = set(re.findall(r'\["(#/[a-z0-9-]+)[^"]*", "', top))
    for r, where in pm.items():
        if where == "步骤条":
            assert r in steps or r == "#epNN"
        elif where in ("设置", "设置 › 高级"):
            assert r in tools, f"{r} 应在“设置 ▾”菜单里"
    assert 'group: "高级"' in top and "设置 ▾" in top and "工具 ▾" not in code_only(top)
    for r in ("#/models", "#/script-ab", "#/audit", "#/trash"):                                     # 工程页归“高级”
        assert pm[r] == "设置 › 高级"
    assert 'href="#/overview"' in top and 'location.hash = "#/queue"' in top                        # 总览 / 待办
    assert "<AllPages />" in read("v3/pages/ProjectSettingsPage.tsx")                               # 设置页底：全部页面
    root = read("projects/Root.tsx")
    assert '"#/queue"' in root and "#/overview" in root                                            # #/inbox → 待办；/ → 总览


def test_cut_editor_preview_and_image_editor_still_mounted():
    app = read("App.tsx")
    assert '"#/cut": lazy(() => import("./v3/pages/CutPage"))' in app and '"#/image-edit": lazy(' in app
    cut = read("v3/pages/CutPage.tsx")
    assert '<CutEditor ep={ep}' in cut and 'useState<"edit" | "one" | "cmp">("edit")' in cut       # 进 #/cut 默认就是剪辑器（含整集预览）


def test_stepbar_shows_done_doing_blocked_and_deep_links():
    top = read("v3/TopBarV3.tsx")
    # UIUX-LOOP r5：W5 之后字和数分成两个节点（<i className="w">完成 </i>{sb.done}，窄屏只留数字）；口径不变
    assert "完成 </i>{sb.done}" in top and "进行 </i>{sb.doing}" in top and "卡住 </i>{sb.blocked}" in top
    assert "stepHref(s.pipe, ep, stepbar.v?.run" in top and "focusEp(stepbar.v, s.pipe, epNum)" in top
    sb = read("v3/stepbar.ts")
    assert '"/api/sop/stepbar"' in sb and '"/api/pipeline/status"' in sb and "run=${encodeURIComponent(run)}" in sb


# ---------------------------------------------------------------- 3) 每页一句话 + 404 + 不露命令行
def test_every_page_has_an_intro_and_404_exists():
    pm = read("v3/pageMap.ts")
    intros = re.findall(r'intro: "([^"]+)"', pm)
    assert len(intros) >= 20
    for t in intros:
        assert not re.search(r"uv run|python|tools/|data/|\.py\b|\.json\b|/api/", t), t
        assert len(t) <= 80, f"一句话太长：{t}"
    app = read("App.tsx")
    assert "<PageIntro page={page} />" in app and "<NotFound hash={hash} />" in app
    assert "uv run" not in code_only(app)
    pi = read("v3/PageIntro.tsx")
    assert "这个地址没有页面" in pi and "#/overview" in pi and "#/queue" in pi


def test_overview_answers_the_four_questions():
    pm = read("v3/PipelineMatrix.tsx")
    for h in ("现在在哪", "系统在做什么", "卡在哪 · 谁负责", "需要你做什么"):
        assert f"<h3>{h}</h3>" in pm
    assert "useStepbar()" in pm and "pm-own" in pm and "pm-detail" in pm                          # 每格：状态 + 一句话 + 负责方；可点开详情
    sea = read("v3/pages/SeasonPage.tsx")
    assert sea.count("<NowPanel />") >= 3                                                          # 每镜数据没读到时也先显示


# ---------------------------------------------------------------- 4) 待办：两个动作 + 202
def test_queue_cards_two_actions_only():
    q = read("v3/pages/OwnerQueuePage.tsx")
    c = code_only(q)
    assert "item.options.map(" not in c and "<Acts " not in c and "function Acts(" not in c
    assert c.count("<TwoActs ") >= 3                                                               # 闸门卡 / 普通卡 / 详情
    for w in ("不同意", "稍后", "不要", "打回", "RejectDialog"):
        assert w not in c, w
    assert "已收到，系统处理中" in q and "setAck(" in q
    qa = read("v3/queueActs.ts")
    assert 'label: "批准"' in qa or '"批准"' in qa
    assert 'label: "修改"' in qa and 'label: "用这张"' in qa and "LATER" in qa


def test_queue_acts_mapping_semantics():
    qa = read("v3/queueActs.ts")
    assert re.search(r'const POS = \[[^\]]*"approve"[^\]]*"pass"', qa)
    assert re.search(r'const NEG = \[[^\]]*"reject"[^\]]*"fail"', qa)
    assert re.search(r'const LATER = \[[^\]]*"later"', qa)
    assert "filter((o) => !LATER.includes(o.key))" in qa                                          # “稍后”不做按钮


# ---------------------------------------------------------------- W5b UIUX-FIX（A5 审计 P0 条件 + P1/P2）
LATEST = [
    {"id": "OLD", "run": "r", "episode": 1, "step": "8 资产就绪", "who": "WATCHDOG", "blocking": True, "status": "open",
     "what": "旧原因：资产作业（江予白）连续失败", "time": "2026-11-03 02:24:00"},
    {"id": "NEW", "run": "r", "episode": 1, "step": "8 资产就绪", "who": "ASSET-WORKER", "blocking": True, "status": "open",
     "what": "新原因：卓琳 outfit1 资产作业失败", "time": "2026-11-03 04:38:00"},
    {"id": "OLD", "run": "r", "episode": 1, "step": "8 资产就绪", "who": "WATCHDOG", "blocking": True, "status": "open",
     "what": "旧原因：资产作业（江予白）连续失败", "time": "2026-11-03 02:30:00"},                     # 同 id 重复登记
    {"id": "DUP2", "run": "r", "episode": 1, "step": "8 资产就绪", "who": "WATCHDOG", "blocking": True, "status": "open",
     "what": "旧原因：资产作业（江予白）连续失败", "time": "2026-11-03 01:00:00"},                     # 不同 id、同一句话
    {"id": "STALE", "run": "r", "episode": 1, "step": "6 补丁环", "who": "MASTER-WSL", "blocking": True, "status": "open",
     "what": "补丁环 10 轮白做", "time": "2026-11-03 03:24:00"},                                       # ①剧本已完成
]


def test_blocking_cell_uses_the_latest_issue_first():
    v = SOP.stepbar_view(_pipe(), LATEST)
    a = v["episodes"][0]["cells"]["assets"]
    assert a["state"] == "blocked" and "卓琳" in a["block"], a["block"]                          # 最新那条，不是 02:24 的旧条
    assert [x["id"] for x in a["issues"]] == ["NEW", "OLD"]                                       # 降序 + 同 id / 同一句话去重
    assert a["issues"][1]["at"] == "2026-11-03 02:30:00"                                          # 同 id 留最新一次登记
    b = next(x for x in v["now"]["blocked"] if x["step"] == "assets")
    assert "卓琳" in b["block"] and b["n_issues"] == 2


def test_done_cell_no_longer_shows_stale_blockers():
    v = SOP.stepbar_view(_pipe(), LATEST)
    s = v["episodes"][0]["cells"]["script"]
    assert s["state"] == "done" and s["issues"] == [] and s["block"] == "" and s["stale"] == 1


def test_latest_first_is_pure_and_sorted_desc():
    rows = SOP.latest_first(LATEST[:3])
    assert [r["time"] for r in rows] == sorted((r["time"] for r in rows), reverse=True)
    assert SOP.latest_first([]) == []


def test_fallback_never_says_not_blocked_and_shows_banner():
    sb = read("v3/stepbar.ts")
    pm = read("v3/PipelineMatrix.tsx")
    top = read("v3/TopBarV3.tsx")
    assert 'FALLBACK_TEXT = "后台接口未更新，卡点读不到（旧接口口径）"' in sb
    for src in (pm, code_only(sb)):
        assert "没有卡住" not in src
    assert "StepbarBanner" in pm and pm.count("<StepbarBanner ") >= 2 and "issues_error" in pm      # 首页“现在” + 进度表
    assert "FALLBACK_TEXT" in top and "issues_error" in top and "sb-banner" in top                  # 步骤条下方
    assert 'owner: ""' in sb                                                                        # 旧接口不拿默认负责方冒充事实


def test_plain_words_single_dictionary():
    pw = read("v3/plainWords.ts")
    for en, zh in (("lint", "规则检查"), ("P4", "分镜稿"), ("preflight", "出图前检查"), ("sha", "校验码"), ("seed", "种子号"),
                   ("OCR", "文字识别"), ("producer", "出图程序启动失败")):
        assert en in pw and zh in pw, en
    assert "系统（工程线）" in pw
    assert "plainText(" in read("v3/stepbar.ts") and "plainOwner(" in read("v3/stepbar.ts")
    assert "plainText(" in read("v3/queueActs.ts") and "plainText(" in read("v3/pages/OwnerQueuePage.tsx")
    for f in ("v3/PipelineMatrix.tsx", "v3/pages/OwnerQueuePage.tsx", "v3/stepbar.ts"):          # 别处不另写一套
        assert "PLAIN_WORDS" not in read(f) and "种子号" not in read(f)


def test_topbar_check_follows_scope_bar():
    tc = (ROOT / "apps/web/e2e/uirsi/topbar_check.mjs").read_text(encoding="utf-8")
    assert '.v3-scope button' in tc and 'querySelectorAll(".v3-top button")].some' not in tc
    sh = (ROOT / "apps/web/e2e/w5ui/shoot_w5.py").read_text(encoding="utf-8")
    assert "sys.exit(2)" in sh and "def _rel(" in sh and "f.relative_to(ROOT)" not in sh
