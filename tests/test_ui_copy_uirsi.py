"""UIRSI r35（K-UI-037）：画布正文不出现流水线内部记录——候选标签里的 agent 名 / 登记过程 / 文件名、加载失败提示里的接口路径和端口。

1. candidates.ts 的 plainLabel：用 node（≥22 自带去类型）直接跑源码里的函数，逐例核对；
2. candLabel / CandidateBox 缩略条都走 plainLabel（不直接显示后端 label）；
3. UIRSI 自己的页面里 LoadError 的 hint 不写接口路径、端口、data/ 目录；
4. 画布审片行的 ↻ 再生成用 compact（窄格只露“↻”，不压人物脸），按钮文字仍是“↻ 再生成”。
"""
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "apps" / "web" / "src"
CAND = WEB / "v3" / "candidates.ts"


def _extract_plain_label() -> str:
    src = CAND.read_text(encoding="utf-8")
    m = re.search(r"const INTERNAL_SEG = .*?;\n", src)
    n = re.search(r"export const plainLabel = .*?\.join\(\" · \"\);\n", src, re.S)
    assert m and n, "candidates.ts 里找不到 INTERNAL_SEG / plainLabel"
    return m.group(0) + n.group(0).replace("export ", "")


@pytest.mark.skipif(not shutil.which("node"), reason="没有 node")
def test_plain_label_drops_internal_segments(tmp_path):
    cases = {
        "ASSETMASTER 已出（PRODUCER 接手登记）": "",
        "新配方": "新配方",
        "旧配方": "旧配方",
        "新配方·IMGGEN 重出": "新配方",
        "新配方 · 侧脸版": "新配方 · 侧脸版",
        "looks/face_overrides.json": "",
        "FLUX 版": "FLUX 版",
        None: "",
    }
    js = _extract_plain_label() + "\nconst cases = " + repr(list(cases.items())).replace("None", "null").replace("(", "[").replace(")", "]") + ";\n"
    js += "for (const [i, want] of cases) { const got = plainLabel(i); if (got !== want) { console.log(JSON.stringify({i, got, want})); process.exit(1); } }\nconsole.log('ok');\n"
    f = tmp_path / "pl.ts"
    f.write_text(js, encoding="utf-8")
    r = subprocess.run(["node", str(f)], capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0 and "ok" in r.stdout, r.stdout + r.stderr


def test_labels_go_through_plain_label():
    cand = CAND.read_text(encoding="utf-8")
    assert re.search(r"candLabel = .*plainLabel\(t\.label\)", cand)
    box = (WEB / "v3" / "CandidateBox.tsx").read_text(encoding="utf-8")
    assert "${x.label}" not in box and "plainLabel(x.label)" in box


# r36（总调度派：ASSETUX 不在岗，同一套做法推到全站）：扫整个 apps/web/src，不再只扫 UIRSI 自己的页面
ALL_TSX = sorted(WEB.rglob("*.tsx"))
INTERNAL = re.compile(r":8800|/api/|data/[a-z]|\.json\b")


def test_load_error_hints_have_no_internal_paths():
    """全站 LoadError 的 hint=、按钮的 why= 字面量不写接口路径 / 端口 / 目录 / 文件名"""
    bad = []
    for f in ALL_TSX:
        for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            for h in re.findall(r'(?:hint|why)="([^"]*)"', line) + re.findall(r'why=\{[^}]*?"([^"]*)"', line):
                if INTERNAL.search(h):
                    bad.append(f"{f.relative_to(ROOT)}:{i} {h}")
    assert not bad, "提示里有接口路径 / 端口 / 目录：\n" + "\n".join(bad)


def test_regen_icon_sits_in_tile_top_right_corner():
    """r36（总调度定：只露 ↻、放帧格右上角、不压脸；帧格 78px 不动）：不另起 absolute 容器，TileTop 改一行、↻ margin-left:auto，下移让开放大镜"""
    css = (WEB / "v3" / "regen.css").read_text(encoding="utf-8")
    assert re.search(r"\.v3-frame > \.ds-tiletop:has\(> \.regen-btn\) \{[^}]*flex-direction: row", css)
    m = re.search(r"\.v3-frame > \.ds-tiletop > \.regen-btn \{([^}]*)\}", css)
    assert m and "margin-left: auto" in m.group(1) and "position" not in m.group(1)
    rr = (WEB / "v3" / "ReviewRow.tsx").read_text(encoding="utf-8")
    assert "{cand ? `${label}候选` : label}" not in rr  # 窄格标签只写“首帧 #n”，“候选”在候选条和悬停提示里


def test_canvas_regen_is_compact_but_keeps_text():
    rr = (WEB / "v3" / "ReviewRow.tsx").read_text(encoding="utf-8")
    seg = rr[rr.index("<RegenButton"): rr.index("/>", rr.index("<RegenButton"))]
    assert re.search(r"\bcompact\b", seg)
    rb = (WEB / "v3" / "RegenButton.tsx").read_text(encoding="utf-8")
    assert "↻<span style={VH}> 再生成</span>" in rb and '"↻ 再生成"' in rb


# ---------------------------------------------------------------- r37（总调度 11-01 派）
def test_frame_owns_click_but_zoom_still_works():
    """P1-1：帧格自己处理点击（data-zoom-own），ZoomLayer 只在点击归属上让路；悬停放大镜 / Alt+点 / Tab+Enter 不变（G11）"""
    z = (WEB / "ds" / "ZoomLayer.tsx").read_text(encoding="utf-8")
    assert 'const OWN_CLICK = "[data-zoom-own]"' in z and "img.closest(OWN_CLICK)" in z
    assert "e.altKey || !interactive" in z  # Alt+点 仍然放大
    tag = z[z.index("const tag = () =>"): z.index("let pend")]
    assert "OWN_CLICK" not in tag  # 帧格里的图仍会被给 tabindex（键盘 Enter / Z 放大）
    rr = (WEB / "v3" / "ReviewRow.tsx").read_text(encoding="utf-8")
    assert "onClick={open} data-zoom-own" in rr


def test_loading_is_not_shown_as_missing():
    """P1-2 / K-UI-D01：候选还没读回来写“读取中…”；底图请求失败写“读不到”，不写“无底图”"""
    rr = (WEB / "v3" / "ReviewRow.tsx").read_text(encoding="utf-8")
    assert "const candLoading = cands === null && !url;" in rr and '{candLoading ? "读取中…" : `${label}未出`}' in rr
    assert "return false as const;" in rr and "plateCache.delete(shot);" in rr
    assert '{sc.plate === null && sc.name && <small className="v3-look-np">无底图</small>}' in rr
    assert "!sc.plate && sc.name" not in rr


def test_narrow_frame_tiletop_hover_reveal():
    """P1-3（总调度选 A）：画布窄帧格标签和 ↻ 悬停 / 聚焦才显示，隐藏时点不到；剧本页宽格不受影响"""
    css = (WEB / "v3" / "regen.css").read_text(encoding="utf-8")
    assert ".v3-rows:not(.sf-fullrows) .v3-frames > .v3-frame > .ds-tiletop { opacity: 0; pointer-events: none;" in css
    assert ".v3-frame:is(:hover, :focus-within) > .ds-tiletop { opacity: 1; }" in css
    assert ".ds-tiletop > * { pointer-events: none; }" in css
    assert "@media (hover: hover)" in css


def test_video_pending_and_season_wording():
    rr = (WEB / "v3" / "ReviewRow.tsx").read_text(encoding="utf-8")
    assert "const vPending = !s.video && (s.takes_count?.video ?? 0) > 0;" in rr and "版待选" in rr
    sea = (WEB / "v3" / "pages" / "SeasonPage.tsx").read_text(encoding="utf-8")
    assert "张候选</span>" in sea and ">候选 {x.cand_n}<" not in sea


def test_identity_face_requires_face_crop_in_ui():
    """项目方 11-01 17:2x（L-086）：非脸部裁切的身份脸候选点了只给说明、不调接口；按钮不删"""
    ph = (WEB / "v3" / "assets" / "PeopleHub.tsx").read_text(encoding="utf-8")
    i = ph.index("const setFace = (file: string) => {")
    body = ph[i: ph.index("};", i)]
    assert body.index("cropWhy(file)") < body.index("hubApi.face(") and "return;" in body
    assert "onUse={() => setFace(f.file)}" in ph  # Verdict 的“用这张”也走同一个关口
    assert "r < 0.6 || r > 1.6" in ph  # 与后端 FACE_CROP_ASPECT 同口径
