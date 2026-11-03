"""K211-F 11-03（总调度裁定）：事实类缺口的补丁包必须附“画面化写法”指引（要补什么 / 禁止屏幕文字与画外人名 / 2–3 个画面化示例 / I6 不变量）；
事实偏差 id 按内容哈希稳定，不再按位置编号（a15 的 F1 与 a16 的 F1 是两条不同偏差，尝试次数被合计成 2 → 误判试满）。"""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load(name, rel):
    sp = importlib.util.spec_from_file_location(name, ROOT / rel)
    m = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(m)
    return m


AF = _load("autoflow_fact_t", "tools/script_rsi/autoflow.py")

D1 = {"kind": "event", "ref": "事实表 events 8：江予白从相机里抽出存储卡握进掌心", "found": "镜11 只有江予白一人在画"}
D2 = {"kind": "reveal", "ref": "事实表 reveals 4：江予白第一次不给祁念看存储卡", "found": "没有祁念在场"}
D3 = {"kind": "event", "ref": "事实表 events 7 / relations 末条：唐瑶把卓琳的手机号存进自己的手机", "found": "镜10 没交代号码是卓琳的"}


def test_fact_ids_are_stable_by_content_not_position():
    r1 = AF.fact_items([D1, D2])
    r2 = AF.fact_items([D3])                       # 下一轮事实核对只剩第三条：它不能再叫 F1 顶掉上一轮的尝试次数
    ids1 = [u["id"] for _, u in r1]
    assert len(set(ids1)) == 2 and all(i.startswith("F") and len(i) == 7 for i in ids1)
    assert r2[0][1]["id"] not in ids1
    assert AF.fact_items([D2, D1])[0][1]["id"] == ids1[1]                 # 换位置 id 不变
    assert AF.fact_items([{**D3, "found": "别的描述"}])[0][1]["id"] == r2[0][1]["id"]   # found 变了（措辞）id 不变，只看事实表引用
    assert r1[0][1]["why"].startswith("event｜事实表：事实表 events 8")


def test_i6_detail_carries_lint_text_of_the_code_that_grew():
    """a17 实测：补丁只因 H3 末拍写了 'settle'（RL-T6）让 TL-10 0→1，写手包里只有“TL-10 0→1”——现在把那条 lint 原文带上"""
    H = _load("hollywood_fact_t", "tools/script_rsi/hollywood.py")
    L = {"shot_block": ["ep01-S10.timeline：[TL-10] 镜10 时间轴不全（1 项）：RL-T6 最后一拍写了定住类词 'settle'"], "zero_detail": ["ep01-S3：[QW-W11] 外套消失"]}
    d = H.worse_detail({"TL-10": (0, 1), "QW-W11": (0, 1), "QW-CH4": (0, 1)}, L)
    assert d.startswith("变多：TL-10 0→1（ep01-S10.timeline：[TL-10] 镜10 时间轴不全（1 项）：RL-T6 最后一拍写了定住类词 'settle'）")
    assert "QW-W11 0→1（ep01-S3：[QW-W11] 外套消失）" in d and d.endswith("QW-CH4 0→1")      # 找不到原文就只写计数
    assert H.worse_detail({}, L) == "无变多"
    src = (ROOT / "tools/script_rsi/hollywood.py").read_text(encoding="utf-8")
    assert 'add("I6", "lint 每个码不比原稿多", not worse, worse_detail(worse, L))' in src


def test_fact_patch_guide_content_and_wiring():
    g = AF.FACT_PATCH_GUIDE
    for key in ("要补的信息", "不加屏幕文字", "HW-F1", "QW-CH4", "方位 + 物", "SS-A3", "A. ", "B. ", "C. ", "头像照片", "没有文字", "I6 不变量", "从 0 变 1"):
        assert key in g, key
    src = (ROOT / "tools/script_rsi/autoflow.py").read_text(encoding="utf-8")
    fact_branch = src.split('elif d == "fact":')[1].split("elif ")[0]
    assert "tg.append(FACT_PATCH_GUIDE)" in fact_branch
