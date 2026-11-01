"""服务器常驻重启队列（WORKFLOW 11-02，总调度批准 DJ-20；规则 K-OPS-W16）。

今晚 30 分钟内多次重启服务器常驻（每次作废租约、不等在途）。改为：任何 loop / system_version deploy 要重启，都只往
data/autopilot/restart_requests.jsonl 追加一条请求；resident_sync 每拍调 process(host) 合并执行：
  · 同一台 30 分钟内最多执行一次（RESTART_MIN_GAP_S，与 resident_sync.restart_guarded 同一个时间戳）；
  · 执行前先排空：producer pause → 等心跳 inflight = 0（最多 15 分钟）→ 重启 → resume；
  · 紧急请求（urgent=true）可以插队（不受 30 分钟限制），但审计里写明“紧急插队”与原因；
  · 合并：同一台所有待办请求一次执行，结果写 data/autopilot/restart_done.jsonl（请求 id 列表、谁请求的、原因、是否插队、耗时）。
请求文件只追加，不改不删。

    from restart_queue import request
    request("gpu36", "system_version deploy sv-20261102-0215", by="FACTORY", urgent=False)
    命令行：.venv/Scripts/python.exe tools/autopilot/restart_queue.py request gpu36 --by FACTORY --reason "..." [--urgent]
            .venv/Scripts/python.exe tools/autopilot/restart_queue.py status
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REQ = ROOT / "data/autopilot/restart_requests.jsonl"
DONE = ROOT / "data/autopilot/restart_done.jsonl"


def _lines(p: Path) -> list[dict]:
    out = []
    try:
        for ln in p.read_text(encoding="utf-8").splitlines():
            try:
                out.append(json.loads(ln))
            except ValueError:
                pass
    except OSError:
        pass
    return out


def _append(p: Path, rec: dict) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def request(host: str, reason: str, by: str, urgent: bool = False) -> dict:
    rec = {"id": uuid.uuid4().hex[:12], "at": time.strftime("%Y-%m-%dT%H:%M:%S"), "t": time.time(), "host": host,
           "reason": reason, "by": by, "urgent": bool(urgent)}
    _append(REQ, rec)
    return rec


def pending(host: str | None = None) -> list[dict]:
    done_ids = {i for d in _lines(DONE) for i in d.get("request_ids") or []}
    return [r for r in _lines(REQ) if r.get("id") not in done_ids and (host is None or r.get("host") == host)]


def process(host: str, rs=None, now: float | None = None) -> dict | None:
    """resident_sync 每拍调用：有待办就按规则合并执行一次；返回执行记录或 None（没执行）"""
    if rs is None:
        sys.path.insert(0, str(Path(__file__).parent))
        import resident_sync as rs  # noqa: PLW0127
    now = time.time() if now is None else now
    todo = pending(host)
    if not todo:
        return None
    st = rs.jl(rs.STATE, {}) or {}
    hs = st.setdefault(host, {})
    last = float(hs.get("last_restart") or 0)
    gap_ok = now - last >= rs.RESTART_MIN_GAP_S
    urgent = [r for r in todo if r.get("urgent")]
    if not gap_ok and not urgent:
        return None                                    # 30 分钟内已重启过：请求留着，到点合并执行
    t0 = time.time()
    rec = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "host": host, "request_ids": [r["id"] for r in todo],
           "by": sorted({r.get("by") or "?" for r in todo}), "reasons": [r.get("reason") for r in todo][:20],
           "urgent_jump": bool(urgent and not gap_ok), "since_last_restart_min": round((now - last) / 60, 1) if last else None}
    try:
        rs.ssh(host, f"cd {rs.R} && {rs.OFF}/venv/bin/python tools/autopilot/producer.py pause --by RESTART_QUEUE --note '重启前排空'",
               timeout=120, tries=3)
        drained = False
        while time.time() - t0 < 900:
            try:
                hb = json.loads(rs.ssh(host, f"cat {rs.R}/data/producer/heartbeat.json", timeout=60, tries=2) or b"{}")
            except Exception:  # noqa: BLE001
                hb = {}
            if int(hb.get("inflight") or 0) == 0:
                drained = True
                break
            time.sleep(20)
        rec["drained"] = drained
        rec["restart_out"] = str(rs.restart(host)).strip()[-300:]
        rs.ssh(host, f"cd {rs.R} && {rs.OFF}/venv/bin/python tools/autopilot/producer.py resume --by RESTART_QUEUE --note '重启完成'",
               timeout=120, tries=3)
        rec["ok"] = True
    except Exception as e:  # noqa: BLE001
        rec["ok"] = False
        rec["error"] = repr(e)[:300]
    rec["secs"] = round(time.time() - t0, 1)
    if rec["ok"]:
        st = rs.jl(rs.STATE, {}) or {}
        st.setdefault(host, {})["last_restart"] = time.time()
        rs.js(rs.STATE, st)
        _append(DONE, rec)                              # 失败的不记 done：请求留着，下一拍再试
    rs.log("restart_queue", host, json.dumps({k: rec.get(k) for k in ("request_ids", "by", "urgent_jump", "drained", "ok", "secs")},
                                              ensure_ascii=False))
    return rec


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("cmd", choices=["request", "status"])
    ap.add_argument("host", nargs="?")
    ap.add_argument("--by", default="")
    ap.add_argument("--reason", nargs="*", default=[])
    ap.add_argument("--urgent", action="store_true")
    a = ap.parse_args(argv)
    if a.cmd == "request":
        if not a.host or not a.by:
            print("用法：request <host> --by <谁> --reason <原因> [--urgent]")
            return 2
        print(json.dumps(request(a.host, " ".join(a.reason), a.by, a.urgent), ensure_ascii=False))
    else:
        print(json.dumps({"pending": pending(), "done_last": _lines(DONE)[-5:]}, ensure_ascii=False, indent=1)[:4000])
    return 0


if __name__ == "__main__":
    sys.exit(main())
