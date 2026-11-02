"""项目方 17:0x：“它还反驳我”——界面上不出现 GEN_CONTRACT / preflight 这类技术词。
扫“给项目方看的”文件里的中文提示 / 按钮 / 提示框文字（排除注释行）；后端返回给界面的大白话也扫。"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "apps" / "web" / "src" / "v3"
TECH = re.compile(r"GEN_CONTRACT|preflight|postflight|契约|I[1-9]\b|Q[1-9]\b|master_reject|registry|producer|prompt_rewrite|ComfyUI|payload", re.I)
BANNED = re.compile(r"不要|打回|或不要|已标不要|不选")        # L-123：界面只有正向动作，没有“不要 / 打回”
FILES = ["shotWord.ts", "EditBox.tsx", "Verdict.tsx", "QueueDock.tsx", "GenState.tsx", "pages/FramesPage.tsx", "assets/Verdict.tsx"]


def visible_strings(src: str):
    for ln in src.splitlines():
        t = ln.strip()
        if t.startswith(("//", "/*", "*", "{/*", "import ")):
            continue
        ln = re.sub(r"/\*.*?\*/|//.*$", "", ln)         # 行尾注释
        for m in re.finditer(r"[\"'`]([^\"'`]*[一-鿿][^\"'`]*)[\"'`]|>([^<>{}]*[一-鿿][^<>{}]*)<", ln):
            yield (m.group(1) or m.group(2))


def test_no_technical_words_in_frontend_text():
    for f in FILES:
        for s in visible_strings((WEB / f).read_text(encoding="utf-8")):
            assert not TECH.search(s), f"{f} 界面文字里有技术词：{s}"


def test_backend_messages_shown_to_owner_are_plain():
    from ns_api import frame_edit_queue as Q
    for v in Q.PLAIN.values():
        assert not TECH.search(v), v
    src = (ROOT / "services" / "api" / "ns_api" / "frame_edit_queue.py").read_text(encoding="utf-8")
    for m in re.finditer(r"note=f?\"([^\"]+)\"", src):
        assert not TECH.search(m.group(1)), m.group(1)
    for m in re.finditer(r"\"word\": f?\"([^\"]+)\"", src):
        assert not TECH.search(m.group(1)), m.group(1)


def test_edit_error_area_only_for_network_failure():
    v = (WEB / "Verdict.tsx").read_text(encoding="utf-8")
    assert "网络不通，没有记下来" in v and "preflight" not in v.lower()      # 弹框错误区只用于“记不下来”，不显示业务校验结果
    e = (WEB / "EditBox.tsx").read_text(encoding="utf-8")
    assert "setErr((e as Error).message)" in e                                # 只显示上面这两句


def test_no_reject_wording_in_owner_facing_text():
    """L-123 补充（总调度 17:3x）：“不要 / 或不要 / 打回”也不许出现在给项目方看的文字里。
    不含 v3/status.ts：分镜页那几句（“首帧待你看：用这张，或不要”…）归 NAVIA 的全站共享状态词表，它改完后把 status.ts 加进 FILES"""
    for f in FILES:
        for s in visible_strings((WEB / f).read_text(encoding="utf-8")):
            assert not BANNED.search(s), f"{f} 界面文字里有“不要 / 打回”：{s}"


def test_assets_pages_say_model_not_lora():
    """总调度 17:4x：资产页的“身份 LoRA / LoRA（总表）”改成大白话（身份模型 / 模型总表）"""
    for f in ("assets/AssetCenter.tsx", "assets/AssetInspector.tsx", "assets/center.ts", "assets/P1Panels.tsx"):
        for s in visible_strings((WEB / f).read_text(encoding="utf-8")):
            if "search" in s or "${" in s:   # 搜索关键词不是界面文字
                continue
            assert "LoRA" not in s, f"{f} 界面文字里还有 LoRA：{s}"


import pytest  # noqa: E402


def test_status_ts_fully_plain():
    for s in visible_strings((WEB / "status.ts").read_text(encoding="utf-8")):
        assert not TECH.search(s) and not BANNED.search(s), s
