"""V2 实时进度页（项目方 11-02 18:5x：“每5秒自动刷新，然后把内容更新到我的网页来，我可以看到你最新的进展”）。

每 5 秒重写 data/review_pages/v2_live/index.html（页面自带 meta refresh 5 s）：
- 总调度进展日志：docs/master/V2_LIVE.md（总调度和各 agent 追加，最新在上）
- 阶段表：唯一阶段模型 tools/master/sop_gate.stage_view 的九阶段（当前主剧，PRODMERGE-O）
- runs.json 里各剧状态、七项分数（data/rsi/scores.jsonl 最新）、V2 资产包清单条数、assets_v2/inbox 收到的文件
只读，不连服务器，不调模型。用法：python tools/monitor/v2_live.py [--once]
"""
from __future__ import annotations

import html
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data" / "review_pages" / "v2_live" / "index.html"
# PRODMERGE-O 11-03（C-6）：阶段表读唯一阶段模型 tools/master/sop_gate.stage_view（九阶段），stage_status.json 退役（没有写入方）
SOP_STAGES = ["剧本", "导入闸门", "资产就绪", "提示词", "出图", "出图检测", "尾帧", "视频", "整集预览"]
STAGES = [(s, s) for s in SOP_STAGES]


def sop_stage_rows(run: str | None, view=None) -> dict:
    """{阶段: {state: done|doing|todo, text}}：全部已开工集都过 = done；有集停在这里 = doing（写卡点）；否则 todo"""
    if not run:
        return {}
    try:
        if view is None:
            import importlib.util as _u
            sp = _u.spec_from_file_location("sop_gate_for_v2_live", ROOT / "tools" / "master" / "sop_gate.py")
            m = _u.module_from_spec(sp)
            sp.loader.exec_module(m)
            view = m.stage_view(run, ROOT)
    except Exception as e:  # noqa: BLE001  # arch-ok: 进度页只读展示，读不出写原因
        return {SOP_STAGES[0]: {"state": "wait", "text": f"阶段模型读不出：{e!r}"[:120]}}
    eps = view.get("episodes") or []
    out = {}
    for s in SOP_STAGES:
        here = [e for e in eps if e["stage"] == s]
        if eps and all(s in e["passed"] for e in eps):
            out[s] = {"state": "done", "text": f"{len(eps)} 集都过"}
        elif here:
            out[s] = {"state": "doing", "text": "；".join(f"ep{e['episode']:02d}：{e['why']}" for e in here)[:160]}
        else:
            out[s] = {"state": "todo", "text": "未开始"}
    return out


def _rj(p: Path, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):   # arch-ok: 进度页只读展示，读不到显示默认值
        return default


def _scores() -> dict:
    last = {}
    p = ROOT / "data" / "rsi" / "scores.jsonl"
    try:
        lines = p.read_text(encoding="utf-8").splitlines()[-400:]
    except OSError:   # arch-ok: 没有分数文件就不显示分数
        return {}
    for ln in lines:
        try:
            d = json.loads(ln)
        except ValueError:   # arch-ok: 并发追加的半行跳过
            continue
        if d.get("line") and d.get("score") is not None:
            last[d["line"]] = (d.get("score"), d.get("at", ""))
    return last


def render() -> str:
    runs = (_rj(ROOT / "config" / "pipeline" / "runs.json", {}) or {})
    st = sop_stage_rows(runs.get("primary"))
    man = _rj(ROOT / "assets_v2" / "manifest.json", {}) or {}
    inbox = sorted(p.name for p in (ROOT / "assets_v2" / "inbox").glob("*") if p.is_file()) if (ROOT / "assets_v2" / "inbox").is_dir() else []
    try:
        log = (ROOT / "docs" / "master" / "V2_LIVE.md").read_text(encoding="utf-8")
    except OSError:   # arch-ok: 还没有日志就显示空
        log = ""
    sc = _scores()
    e = html.escape
    rows = "".join(f"<tr><td>{k}</td><td>{e(n)}</td><td class='{(st.get(k) or {}).get('state', 'todo')}'>"
                   f"{e((st.get(k) or {}).get('text', '未开始'))}</td></tr>" for k, n in STAGES)
    runs_html = "".join(f"<li>{e(k)}：{e(str(v.get('status')))}</li>" for k, v in (runs.get("runs") or {}).items())
    score_html = "".join(f"<li>{e(k)}：{v[0]}（{e(str(v[1])[11:16])}）</li>" for k, v in sorted(sc.items()))
    nchar = len((man.get("characters") or {})) if isinstance(man, dict) else 0
    nscene = len((man.get("scenes") or {})) if isinstance(man, dict) else 0
    return f"""<!doctype html><html lang="zh"><head><meta charset="utf-8"><meta http-equiv="refresh" content="5">
<title>V2 实时进度</title><style>
body{{background:#0b0b0c;color:#e9e6e0;font:14px/1.6 system-ui,'Microsoft YaHei';margin:0;padding:20px 24px}}
h1{{font-size:20px;margin:0 0 4px}} .sub{{color:#8a8780;font-size:12px;margin-bottom:16px}}
.grid{{display:grid;grid-template-columns:1.2fr 1fr;gap:20px}} .card{{background:#141414;border:1px solid #222;border-radius:8px;padding:14px 16px}}
h2{{font-size:14px;color:#c9b27a;margin:0 0 8px}} table{{width:100%;border-collapse:collapse}} td{{padding:5px 6px;border-bottom:1px solid #1f1f1f}}
td.todo{{color:#8a8780}} td.doing{{color:#e0a43c}} td.done{{color:#7fc79a}} td.wait{{color:#e0a43c;font-weight:600}}
pre{{white-space:pre-wrap;font:13px/1.6 system-ui,'Microsoft YaHei';margin:0;max-height:70vh;overflow:auto}} ul{{margin:0;padding-left:18px}}
</style></head><body><h1>V2 实时进度</h1><div class="sub">每 5 秒自动刷新 · 最后更新 {time.strftime('%H:%M:%S')}</div>
<div class="grid"><div class="card"><h2>总调度进展（最新在上）</h2><pre>{e(log)}</pre></div>
<div><div class="card"><h2>V2 九道闸门</h2><table>{rows}</table></div><br>
<div class="card"><h2>资产包</h2>角色 {nchar} · 场景 {nscene}<br>收件箱 assets_v2/inbox：{e('、'.join(inbox) or '空')}</div><br>
<div class="card"><h2>剧集状态</h2><ul>{runs_html}</ul></div><br>
<div class="card"><h2>七项分数</h2><ul>{score_html or '<li>暂无</li>'}</ul></div></div></div></body></html>"""


LOCK = OUT.parent / ".v2_live.pid"


def write_once() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT.with_name(f"index.{os.getpid()}.tmp")
    tmp.write_text(render(), encoding="utf-8")
    for _ in range(10):   # 浏览器刷新正读着文件时 Windows 会拒绝替换：稍等重试，不退出
        try:
            os.replace(tmp, OUT)
            return
        except PermissionError:
            time.sleep(0.3)
    tmp.unlink(missing_ok=True)


def _single_instance() -> bool:
    """只允许一份循环在跑：锁文件里的进程还活着就退出"""
    try:
        old = int(LOCK.read_text(encoding="utf-8").strip())
        if old != os.getpid():
            os.kill(old, 0)
            return False
    except (OSError, ValueError):   # arch-ok: 锁文件不在 / 旧进程已死 → 本进程接管
        pass
    LOCK.write_text(str(os.getpid()), encoding="utf-8")
    return True


if __name__ == "__main__":
    if "--once" in sys.argv:
        write_once()
    else:
        if not _single_instance():
            sys.exit(0)
        while True:
            try:
                write_once()
            except Exception as e:  # noqa: BLE001  进度页只是展示，单次失败不让循环退出
                print("v2_live write failed:", repr(e), file=sys.stderr)
            time.sleep(5)
