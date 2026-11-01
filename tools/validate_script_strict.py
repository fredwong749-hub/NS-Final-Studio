"""
严格剧本格式校验（T58，总调度 2026-10-30：“validate 必须调用 h3_lint 的全部 H3 规则，再加上 Image 2.1 Turbo
提示词的格式检查”）。剧本创作对话框 / 批量重写（Qwen）和 fredw-92 的返修循环共用。只查格式，不判断内容。

= tools/validate_qwen_script.py 的全部检查（导入器解析 + ns_schema.h3_lint.lint_h3，lint_h3 内含 lint_h3_extra）
  + 下面的 Image 2.1 Turbo 检查；并把画布取字段要用的 QW-C1/C2/C3 从 warn 升为 block；
  + 每镜必须有 **场景**（S1）；v3 字段规则（R3，docs/production_rules_v3.md：QW-G*/P*/E4–E7/CH*/LK*/K*/M1/D1/D2/
    SC7/SC8、H3-X1–X3）总按表中级别查（导入关口只在剧本写了 v3 字段时查）。

    IMG-N1  block  首帧 img 不写否定词（Turbo CFG=1，否定词无效且会被画出来）
    IMG-L1  block  每镜都有尾帧：motion 最后一个“——”之后的结束状态非空、≥8 字
    IMG-L2  block  尾帧结束状态不写否定词、不写剪辑词
    IMG-T1  warn   img 里像触发词的词必须在全局触发词表里（pose_* 除外），且放在 img 开头

可调用：
    from validate_script_strict import strict_validate     # (path, episode=None, names=None) -> 报告（同 validate_qwen_script.validate）
    .venv\\Scripts\\python.exe tools\\validate_script_strict.py <script.md> [--episode N] [--json] [--repair-dir DIR]
退出码：0 无 block；1 有 block；2 解析不出任何集。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import validate_qwen_script as V  # noqa: E402

# 中文否定词；左侧列表里的固定搭配是正向描述，不算否定
NEG_ZH = re.compile(r"[不无没别勿]|未[经曾]|避免|去掉")
# 与 config/script_chat_rules.md「不写否定词」条的“可照写的固定词”逐一对应（rules_v2，默认值待确认 Q6）
NEG_OK = ("不锈钢", "不对称", "不规则", "不透明", "无袖", "无肩带", "无缝", "无痕", "无钢圈", "无名指", "不停", "不断",
          "忍不住", "毫无保留", "特别", "分别", "性别", "级别", "别致", "别针", "没入", "淹没",
          "告别", "离别", "别墅")   # 封板修复：ep02 尾帧“告别氛围”被误判为否定

STRICT_RULES = {
    "IMG-N1": ("block", "首帧 img 只写画面里“有什么”：不写否定词 不/无/没/别（Image 2.1 Turbo CFG=1，否定词无效）"),
    "IMG-L1": ("block", "每镜都要有尾帧：motion 最后一个 `——` 之后写结束状态（一张能画出来的静帧，≥8 字）"),
    "IMG-L2": ("block", "尾帧结束状态只写画面里有什么：不写否定词，不写 切/转场/cut/剪辑"),
    "IMG-T1": ("warn", "img 开头的触发词只用全局触发词表里的词或 pose_<名称>"),
}
# 严格模式下为 block：QW-C1/C2/C3 画布取“运镜 / 景别 / 表情”要用；
# H3-D7 非亲密镜（项目方 2026-10-30：“普通对话镜每镜只让一个人说话”，原为 warn）
ESCALATE = {"QW-C1", "QW-C2", "QW-C3", "H3-D7"}
V.RULES.update(STRICT_RULES)   # 只加新编号（返修请求引用规则原文）；QW-C* 的升级只在 strict_check_shot 里做，不改 V.RULES


def _negations(text: str) -> list[str]:
    masked = text
    for ok in NEG_OK:
        masked = masked.replace(ok, "　" * len(ok))
    return sorted({text[max(0, m.start() - 2): m.end() + 3] for m in NEG_ZH.finditer(masked)})


def image_checks(shot, triggers: set[str]) -> list[dict]:
    out = []
    img = shot.img_prompt or ""
    neg = _negations(img)
    if neg:
        out.append(V._issue("IMG-N1", f"img 里有否定词：{'｜'.join(neg[:6])}", field="img"))
    mo = shot.motion_prompt or ""
    if mo:
        end = mo.rsplit("——", 1)[1].strip(" ，。；、") if "——" in mo else ""
        if len(end) < 8:
            out.append(V._issue("IMG-L1", f"尾帧结束状态{'缺失' if not end else f'太短：{end}'}", field="motion"))
        else:
            neg = _negations(end)
            if neg:
                out.append(V._issue("IMG-L2", f"尾帧结束状态有否定词：{'｜'.join(neg[:6])}", field="motion"))
            if V.CUT_RE.search(end):
                out.append(V._issue("IMG-L2", f"尾帧结束状态有剪辑词：{V.CUT_RE.search(end).group(0)}", field="motion"))
    lead = set()   # img 开头连续的触发词
    for tok in re.split(r"[，,]", img):
        if not V.TRIGGER_LIKE.fullmatch(tok.strip()):
            break
        lead.add(tok.strip())
    for t in sorted(set(V.TRIGGER_LIKE.findall(img))):
        if triggers and t not in triggers and not t.startswith("pose_"):
            out.append(V._issue("IMG-T1", f"img 里有不在触发词表里的触发词：{t}", field="img"))
        elif t not in lead:
            out.append(V._issue("IMG-T1", f"触发词 {t} 没放在 img 开头", field="img"))
    return out


_base_check_shot = V.check_shot


def strict_check_shot(shot, ep, triggers, names):
    out = []
    for i in _base_check_shot(shot, ep, triggers, names):
        if i["rule_id"] in ESCALATE:
            i = {**i, "level": "block"}
        out.append(i)
    return out + image_checks(shot, triggers)


_base_check_episode = V.check_episode


shot_cap = V.shot_cap   # 本集镜数上限 = max(8, 说话轮次 + 独白段数, ⌈总时长 ÷ 6⌉)（K1 + G29，导入器 ns_agent.importer.script_md.shot_cap）


def strict_check_episode(ep) -> list[dict]:
    """K1（fredw-92 2026-10-31，production_rules_v3 §0）：QW-E2 / QW-E3 与导入关口同一判定——
    镜数 6..max(8, 说话轮次+独白段数) block；总时长 50–75 通过、75–90 warn、>90 或 <50 block；镜号不连续 block"""
    return _base_check_episode(ep)


def strict_validate(path, episode: int | None = None, names: list[str] | None = None) -> dict:
    V.check_shot, V.check_episode = strict_check_shot, strict_check_episode
    try:
        # S1：剧本创作每镜必须有 **场景**；R3：v3 字段（人物表 / 出场人物 / 造型 / 人物 / 衔接…）总按表中级别查
        rep = V.validate(Path(path), episode, names, require_scenes=True, require_v3=True)
    finally:
        V.check_shot, V.check_episode = _base_check_shot, _base_check_episode
    rep["strict"] = True
    return rep


def main(argv=None) -> int:
    V.check_shot, V.check_episode = strict_check_shot, strict_check_episode   # V.main 调用的 validate 走严格检查
    V.REQUIRE_SCENES = True                                                    # S1：每镜必须有 **场景**
    V.REQUIRE_V3 = True                                                        # R3：v3 字段总按表中级别查
    return V.main(argv)


if __name__ == "__main__":
    sys.exit(main())
