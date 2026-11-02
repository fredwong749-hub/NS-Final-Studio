"""L-116「待你看」队列（UIRSI2，总调度 fredw-2b 11-02 派；项目方 11:5x 原话：
“uiux 需要添加个要我看的阵列，点击去审核。其中，我需要全自动检测，尽量少人的操作。”）

只放三类事，其余全部由系统自动处理：
  ① decide  必须项目方拍板的事（花钱 / 下载许可 / 删除 / 推翻旧审美 / 导入新季）
             来源：data/owner_queue/requests.json（总调度 / 各 loop 投递，kind=decide，category 必须是上面五类之一）
                   + docs/master/MASTER_PICTURE.md §1 账本里状态写“待项目方”的行（按脚本路径去重）
                   + data/sentinel/open.json 里 S13“等人决定”工单中写明等项目方的（等总调度的不进队列，只计数 master_waits）
  ② spot    机签抽检样本：data/vqa/autosign_spot.jsonl 里 human 还是空的（tools/vqa/autosign.py sign 按 10% 抽）
  ③ pick    审美挑选：requests.json 里 kind=pick 的候选组——只保留过了生成契约的候选（auto_current.passes 同一口径）；
             过契约的只剩 1 张 → 系统直接选它（记 by=POLICY），不进队列；0 张 → 不进队列（交回出图方重出）

接口：
  GET  /api/owner/queue   {count, counts, items[], auto_today, master_waits, machine_signed{sid:{image,last}}, autosign_mode}
  POST /api/owner/decide  {id, choice, reason?, by:"owner"}  登录即本人：AuthMiddleware 把登录项目方的 by=owner 放行（其余改成
                          unauthenticated → 403），并自动记审计 data/audit/<日期>.jsonl；这里另记 data/owner_queue/decisions.jsonl
       choice：decide → approve | reject | later（稍后：4 小时内不再出现）；spot → pass | fail（→ autosign.spot，抽检不一致自动退回人工）；
               pick → 候选 key（apply=activate 且候选是某镜版本时，经 pipeline.set_active 设为当前）| later
  “机签通过”：每镜首帧 / 尾帧的当前版本过契约（含 Q9 本地看图）且机签开关 mode=auto、不在待抽检里、抽检没判不过 → machine_signed，
             画布 / 单集页显示“● 机签通过 vN”（灰字），不再提示项目方点“用这张 / 不要”。
规则 K-UI-053；data_parity D-QUEUE 核对“页面待你看数 = 队列数 = 各来源现算数”。
"""
from __future__ import annotations

from ns_api import run_paths as _RP   # K-OPS-F24：渲染根目录按当前剧（V1 已归档，不在网页显示）
import contextvars
import glob
import hashlib
import importlib.util
import json
import re
import sys
import threading
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

REPO = Path(__file__).resolve().parents[3]
router = APIRouter(tags=["owner-queue"])
_lock = threading.Lock()

CATEGORIES = {"spend": "花钱", "license": "下载许可", "delete": "删除", "overturn": "推翻旧审美", "import_season": "导入新季"}
KIND_LABEL = {"decide": "要你拍板", "spot": "机签抽检", "pick": "挑一张"}
SNOOZE_S = 4 * 3600
OWNER_WORDS = ("等项目方", "项目方点选", "项目方定", "项目方拍板", "项目方决定")
STAGES = ("image", "last")
STAGE_WORD = {"image": "首帧", "last": "尾帧", "video": "视频"}


def _paths(root: Path) -> dict:
    q = root / "data" / "owner_queue"
    return {"requests": q / "requests.json", "decisions": q / "decisions.jsonl", "spot": root / "data" / "vqa" / "autosign_spot.jsonl",
            "signed": root / "data" / "vqa" / "autosign_signed.jsonl", "state": root / "data" / "vqa" / "autosign_state.json",
            "sentinel": root / "data" / "sentinel" / "open.json", "master": root / "docs" / "master" / "MASTER_PICTURE.md",
            "renders": _RP.renders_root(root)}


# 本次汇总里读不了的来源（每次 build 调用一份，ContextVar 隔离并发请求）：随结果返回 source_errors / status=error，
# 界面写“队列读取失败：<来源>”，不显示成空队列
_errs_var: contextvars.ContextVar[list[str] | None] = contextvars.ContextVar("owner_queue_errs", default=None)


def _warn(msg: str) -> None:
    errs = _errs_var.get()
    if errs is not None:
        errs.append(msg[:200])
    print(f"[owner_queue] {msg}"[:300], file=sys.stderr)


REQUIRED = ("sentinel", "master")   # 必须在的来源：不在 = 队列读取失败（requests / 抽检表 / 决定记录没有文件 = 当前为空，正常）
ALERTS_REL = Path("data") / "qa" / "alerts.jsonl"


def _alert(root: Path, errs: list[str]) -> None:
    """队列读取失败 → data/qa/alerts.jsonl 报警（同一组错误 1 小时内只记一次）"""
    p = root / ALERTS_REL
    key = hashlib.md5("|".join(errs).encode()).hexdigest()[:12]
    hour = time.strftime("%Y-%m-%dT%H")
    if any(r.get("id") == "OWNERQ-READ" and r.get("key") == key and str(r.get("at", "")).startswith(hour) for r in _rows_quiet(p)):
        return
    p.parent.mkdir(parents=True, exist_ok=True)
    with _lock, p.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "id": "OWNERQ-READ", "key": key, "owner_loop": "UIRSI",
                            "severity": "P1", "title": "待你看队列读取失败（页面显示“队列读取失败”，不显示成空队列）", "errors": errs[:6]},
                           ensure_ascii=False) + chr(10))


def _rows_quiet(p: Path) -> list[dict]:
    if not p.exists():
        return []
    out = []
    for x in p.read_text(encoding="utf-8", errors="replace").splitlines()[-400:]:
        if x.strip().startswith("{"):
            try:
                out.append(json.loads(x))
            except ValueError as e:
                print(f"[owner_queue] alerts 行坏了：{e!r}", file=sys.stderr)
    return out


def _json(p: Path, default):
    """没有这个文件 = 这一来源当前为空（正常）；有文件但读不了 / 坏了 → 记 stderr 再按空处理（不让一个坏来源拖垮整个队列）"""
    if not p.exists():
        return default
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        _warn(f"读不了 {p}：{e!r}")
        return default


def _rows(p: Path) -> list[dict]:
    if not p.exists():
        return []
    try:
        lines = p.read_text(encoding="utf-8").splitlines()
    except OSError as e:
        _warn(f"读不了 {p}：{e!r}")
        return []
    out = []
    for k, x in enumerate(lines, 1):
        if not x.strip():
            continue
        try:
            out.append(json.loads(x))
        except ValueError as e:
            _warn(f"{p} 第 {k} 行坏了，跳过：{e!r}")
    return out


def _file_url(rel: str | None) -> str | None:
    if not rel:
        return None
    rel = str(rel).replace("\\", "/")
    rel = rel[5:] if rel.startswith("data/") else rel
    return f"/files/{rel}"


def _passes(t: dict | None) -> bool:
    """过契约（含 Q9 本地看图）= ns_render.auto_current.passes；测试 / 无渲染包时退回同一口径的本地实现"""
    if not t:
        return False
    try:
        from ns_render import auto_current as AC
        return AC.passes(t)
    except Exception:  # noqa: BLE001
        pf = t.get("postflight") or {}
        q9 = next((i for i in pf.get("items") or [] if i.get("id") == "Q9"), None)
        return pf.get("ok") is True and not t.get("bad") and (q9 is None or q9.get("status") in ("pass", "na"))


def _scores(t: dict | None) -> list[dict]:
    pf = (t or {}).get("postflight") or {}
    return [{"id": i.get("id"), "title": i.get("title") or "", "status": i.get("status"), "detail": str(i.get("detail") or "")[:240]}
            for i in pf.get("items") or [] if i.get("id")]


def _takes(root: Path, sid: str) -> dict:
    ep, s = sid.split("-")
    return _load_takes(_paths(root)["renders"] / ep / s / "takes.json")


def _take(root: Path, sid: str, stage: str, n) -> dict | None:
    try:
        n = int(n)
    except (TypeError, ValueError):
        return None
    return next((t for t in _takes(root, sid).get("takes") or [] if t.get("stage") == stage and int(t.get("n") or 0) == n), None)


# ------------------------------------------------------------------ 决定记录
def decisions(root: Path) -> list[dict]:
    return _rows(_paths(root)["decisions"])


def _closed(root: Path, now: float) -> set[str]:
    """已决定的 id：每个 id 以最后一行为准；稍后 = 4 小时内不出现；undo = 重新打开"""
    last: dict[str, dict] = {}
    for d in decisions(root):
        if d.get("id"):
            last[d["id"]] = d
    out = set()
    for i, d in last.items():
        if d.get("choice") == "undo":
            continue
        if d.get("choice") == "later":
            try:
                if now - time.mktime(time.strptime(d.get("at", "")[:19], "%Y-%m-%dT%H:%M:%S")) >= SNOOZE_S:
                    continue
            except ValueError:
                continue
        out.add(i)
    return out


def _record(root: Path, row: dict) -> dict:
    p = _paths(root)["decisions"]
    p.parent.mkdir(parents=True, exist_ok=True)
    row = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), **row}
    with _lock, p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row


# ------------------------------------------------------------------ ① 要你拍板
def _cat_of(text: str) -> str | None:
    if re.search(r"删除|删掉|永久删", text):
        return "delete"
    if re.search(r"花钱|付费|费用|充值|计费|预算", text):
        return "spend"
    if re.search(r"许可|license|License|下载", text):
        return "license"
    if re.search(r"导入.{0,6}(新季|第二季|第\s*\d+\s*季)", text):
        return "import_season"
    if re.search(r"推翻|改审美|换掉已定", text):
        return "overturn"
    return None


def master_rows(root: Path) -> list[dict]:
    """MASTER_PICTURE §1 账本：状态列写“待项目方”的行 → 要你拍板（同一脚本只出一项）"""
    mp = _paths(root)["master"]
    if not mp.exists():
        return []
    text = mp.read_text(encoding="utf-8")
    out, seen = [], set()
    for line in text.splitlines():
        if not line.startswith("| L-") or "待项目方" not in line:
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 4 or "待项目方" not in cells[-1]:
            continue
        lid, quote, rule = cells[0], cells[2], cells[3]
        cat = _cat_of(" ".join(cells))
        if not cat:
            continue
        m = re.search(r"[\w./\\-]+\.(?:ps1|sh|py)", line)
        key = m.group(0) if m else lid
        if key in seen:
            continue
        seen.add(key)
        out.append({"id": f"mp:{lid}", "kind": "decide", "category": cat, "title": f"{CATEGORIES[cat]}：{rule[:60]}",
                    "detail": (cells[-2][:300] if len(cells) >= 2 else "") + "。点“同意”只记下你的决定、通知总调度，不会立刻删除或花钱。", "quote": quote[:200], "source": f"MASTER_PICTURE {lid}",
                    "script": m.group(0) if m else None})
    return out


def sentinel_waits(root: Path) -> tuple[list[dict], dict]:
    """S13 等人决定工单：写明等项目方的进队列；等总调度的只计数（总调度自己定，不打扰项目方）"""
    d = _json(_paths(root)["sentinel"], {}) or {}
    items, master_n, master_objs = [], 0, []
    for i in d.get("issues") or []:
        if i.get("slo") != "S13" or i.get("status") != "open" or not str(i.get("key", "")).startswith("S13:wait"):
            continue
        ev = i.get("evidence") or {}
        reasons = [str(r) for r in ev.get("reasons") or []]
        if any(w in r for r in reasons for w in OWNER_WORDS):
            items.append({"id": f"sn:{i.get('id')}", "kind": "decide", "category": _cat_of(" ".join(reasons)) or "overturn",
                          "title": i.get("title") or "等你决定", "detail": "；".join(reasons)[:300], "source": f"SENTINEL {i.get('id')}",
                          "objs": list(ev.get("objs") or [])[:12]})
        else:
            master_n += int(ev.get("n") or 0)
            master_objs += list(ev.get("objs") or [])
    return items, {"n": master_n, "objs": sorted(set(master_objs))[:20],
                   "title": f"总调度在定 {master_n} 项（等总调度，不需要你）" if master_n else ""}


def requests(root: Path) -> list[dict]:
    d = _json(_paths(root)["requests"], [])
    if isinstance(d, dict):
        d = d.get("items") or []
    return [x for x in d if isinstance(x, dict) and x.get("id")]


DECIDE_OPTS = [{"key": "approve", "label": "同意"}, {"key": "reject", "label": "不同意"}, {"key": "later", "label": "稍后"}]


def _decide_item(r: dict) -> dict | None:
    cat = r.get("category")
    if cat not in CATEGORIES:
        return None
    rec = r.get("recommend")
    return {"id": str(r["id"]), "kind": "decide", "category": cat, "category_label": CATEGORIES[cat], "title": r.get("title") or CATEGORIES[cat],
            "detail": r.get("detail") or "", "quote": r.get("quote") or "", "source": r.get("source") or r.get("by") or "总调度",
            "at": r.get("at") or "", "media": [m for m in (r.get("media") or []) if isinstance(m, dict)],
            "options": r.get("options") or DECIDE_OPTS, "recommend": {"choice": rec, "why": r.get("why") or ""} if rec else None,
            "scores": [], "link": r.get("link")}


# ------------------------------------------------------------------ ② 机签抽检
SPOT_EVERY = 10   # policy resources.master_review_autosign.testphase_spot_check_ratio = 0.10


def spot_pool(root: Path, scan: dict | None = None) -> list[dict]:
    """机签抽检样本 = autosign_spot.jsonl 里还没人判的 + 今天机签通过并设为当前的版本按 id 的 md5 定序每 10 张抽 1 张（结果稳定，FILMUI 稿同一口径）"""
    rows = {str(r.get("id")): r for r in _rows(_paths(root)["spot"]) if r.get("id")}
    out = [r for r in rows.values() if r.get("human") is None]
    if autosign_mode(root) == "auto":
        scan = scan or scan_takes(root)
        pool = sorted(scan.get("today_signed") or [], key=lambda i: hashlib.md5(i.encode()).hexdigest())
        for i in pool[::SPOT_EVERY]:
            if i not in rows:
                out.append({"id": i, "auto": "pass", "human": None, "derived": True})
    return out


def spot_items(root: Path, scan: dict | None = None) -> list[dict]:
    out = []
    for r in spot_pool(root, scan):
        try:
            sid, stage, n = str(r["id"]).split(":")
        except ValueError:
            continue
        t = _take(root, sid, stage, n)
        ep = sid.split("-")[0]
        out.append({"id": f"spot:{r['id']}", "spot_id": r["id"], "derived": bool(r.get("derived")), "kind": "spot", "category": "spot",
                    "category_label": "机签抽检", "title": f"第 {int(ep[2:])} 集 {sid.split('-')[1]} · 第 {n} 版{STAGE_WORD.get(stage, stage)}（机签已通过）",
                    "sid": sid, "stage": stage, "n": int(n),
                    "detail": "系统已自动通过并设为当前，按每 10 张抽 1 张抽到这张。同意 = 抽检通过；不同意 = 机签暂停、回到人工复核，系统按你的理由重出。",
                    "source": "VQAGATE 机签抽检", "at": r.get("queued_at") or str((t or {}).get("created_at") or ""),
                    "media": [{"url": _file_url(r.get("file") or (t or {}).get("file")), "kind": "video" if stage == "video" else "image",
                               "label": f"{sid.split('-')[1]} v{n}"}],
                    "scores": _scores(t), "options": [{"key": "pass", "label": "同意"}, {"key": "fail", "label": "不同意"}, {"key": "later", "label": "稍后"}],
                    "recommend": {"choice": "pass", "why": "契约全过 + 本地看图 Q9 过 + 回归集全过"}, "link": f"#{ep}"})
    return out


# ------------------------------------------------------------------ ③ 挑一张
def _cand_ok(root: Path, c: dict) -> tuple[bool, dict | None]:
    if c.get("sid") and c.get("stage") and c.get("n") is not None:
        t = _take(root, c["sid"], c["stage"], c["n"])
        return _passes(t), t
    return c.get("contract_ok") is True, None


def pick_items(root: Path, closed: set[str]) -> tuple[list[dict], list[dict]]:
    """返回（进队列的挑选, 系统自动选掉的挑选）"""
    out, auto = [], []
    for r in requests(root):
        if r.get("kind") != "pick" or str(r["id"]) in closed:
            continue
        cands = []
        for i, c in enumerate(r.get("candidates") or []):
            if not isinstance(c, dict):
                continue
            ok, t = _cand_ok(root, c)
            if not ok:
                continue
            key = str(c.get("key") or i + 1)
            cands.append({"key": key, "label": c.get("label") or key, "url": _file_url(c.get("file") or (t or {}).get("file")),
                          "kind": "video" if str(c.get("stage")) == "video" else "image", "scores": _scores(t),
                          "sid": c.get("sid"), "stage": c.get("stage"), "n": c.get("n"), "score": c.get("score")})
        if len(cands) <= 1:
            auto.append({"id": str(r["id"]), "kind": "pick", "only": cands[0]["key"] if cands else None, "apply": r.get("apply"),
                         "cand": cands[0] if cands else None})
            continue
        rec = str(r.get("recommend")) if str(r.get("recommend")) in {c["key"] for c in cands} else \
            max(cands, key=lambda c: float(c.get("score") or 0))["key"]
        out.append({"id": str(r["id"]), "kind": "pick", "category": "pick", "category_label": "挑一张", "title": r.get("title") or "挑一张",
                    "detail": r.get("detail") or "", "source": r.get("source") or r.get("by") or "", "at": r.get("at") or "",
                    "media": [{"url": c["url"], "kind": c["kind"], "label": c["label"], "key": c["key"]} for c in cands],
                    "candidates": cands, "scores": next((c["scores"] for c in cands if c["key"] == rec), []),
                    "options": [{"key": c["key"], "label": c["label"]} for c in cands] + [{"key": "later", "label": "稍后"}],
                    "recommend": {"choice": rec, "why": r.get("why") or "系统推荐（契约分最高）"}, "apply": r.get("apply"), "link": r.get("link")})
    return out, auto


# ------------------------------------------------------------------ 机签通过 + 今天自动处理
def autosign_mode(root: Path) -> str:
    return str((_json(_paths(root)["state"], {}) or {}).get("mode") or "manual")


_cache: dict = {"key": None, "val": None}


_fcache: dict[tuple, dict] = {}
_tcache: dict[str, tuple[int, dict]] = {}


def _file_summary(p: Path, today: str) -> dict:
    key = (str(p), p.stat().st_mtime_ns, today)
    hit = _fcache.get(key)
    if hit is not None:
        return hit
    sid = f"{p.parent.parent.name}-{p.parent.name}"
    d = _load_takes(p)
    act = d.get("active") or {}
    sm = {"sid": sid, "passed": {}, "pass": 0, "fail": 0, "redo": 0, "by_stage": {"image": 0, "last": 0, "video": 0}, "today_signed": []}
    for t in d.get("takes") or []:
        if str(t.get("created_at") or "").startswith(today) and t.get("stage") in sm["by_stage"]:
            sm["by_stage"][t["stage"]] += 1
            rung = str((t.get("producer") or {}).get("rung") or "")
            if "重出" in rung or "换 seed" in rung:
                sm["redo"] += 1
        if t.get("stage") in STAGES and str(t.get("created_at") or "").startswith(today) and (t.get("postflight") or {}).get("ok") is not None:
            sm["pass" if _passes(t) else "fail"] += 1
    for stg in STAGES:
        n = act.get(stg)
        if n is None:
            continue
        t = next((x for x in d.get("takes") or [] if x.get("stage") == stg and x.get("n") == n), None)
        if _passes(t) and not t.get("master_reject"):
            sm["passed"][stg] = n
            if str(t.get("created_at") or "").startswith(today):
                sm["today_signed"].append(f"{sid}:{stg}:{n}")
    for k in [k for k in _fcache if k[0] == str(p)]:
        _fcache.pop(k, None)
    _fcache[key] = sm
    return sm


def _load_takes(p: Path) -> dict:
    """takes.json 按 mtime 缓存（只读；调用方不要改返回的对象）"""
    if not p.exists():
        return {}
    m = p.stat().st_mtime_ns
    hit = _tcache.get(str(p))
    if hit and hit[0] == m:
        return hit[1]
    d = _json(p, {}) or {}
    _tcache[str(p)] = (m, d)
    return d


def scan_takes(root: Path) -> dict:
    """每镜首帧 / 尾帧当前版本是否机签通过 + 今天自动判了多少版（按 takes.json mtime 缓存）"""
    files = sorted(glob.glob(str(_paths(root)["renders"] / "ep*" / "S*" / "takes.json")))
    key = (str(root), tuple((f, Path(f).stat().st_mtime_ns) for f in files), time.strftime("%Y-%m-%d"))
    if _cache["key"] == key:
        return _cache["val"]
    today = time.strftime("%Y-%m-%d")
    passed: dict[str, dict] = {}
    auto_pass = auto_fail = redo = 0
    by_stage = {"image": 0, "last": 0, "video": 0}
    today_signed: list[str] = []
    for f in files:
        sm = _file_summary(Path(f), today)    # 每个 takes.json 按 mtime 只算一次（:8800 多线程，整份重扫要 10 秒，会拖慢别的接口）
        if sm["passed"]:
            passed[sm["sid"]] = dict(sm["passed"])
        auto_pass += sm["pass"]
        auto_fail += sm["fail"]
        redo += sm["redo"]
        for k, v in sm["by_stage"].items():
            by_stage[k] += v
        today_signed += sm["today_signed"]
    val = {"passed": passed, "auto_pass": auto_pass, "auto_fail": auto_fail, "redo": redo, "by_stage": by_stage, "today_signed": today_signed}
    _cache.update(key=key, val=val)
    return val


def machine_signed(root: Path, scan: dict | None = None) -> dict:
    if autosign_mode(root) != "auto":
        return {}
    scan = scan or scan_takes(root)
    rows = _rows(_paths(root)["spot"])
    hold = {str(r.get("id")) for r in rows if r.get("human") == "fail"}   # 抽检判不过的不显示“机签通过”
    hold |= {str(r["id"]) for r in spot_pool(root, scan)}                # 待抽检的进队列，不显示“机签通过”
    out: dict = {}
    for sid, st in scan["passed"].items():
        for stg, n in st.items():
            if f"{sid}:{stg}:{n}" not in hold:
                out.setdefault(sid, {})[stg] = n
    return out


# ------------------------------------------------------------------ 汇总
def build(root: Path = REPO, now: float | None = None) -> dict:
    now = now or time.time()
    _errors: list[str] = []
    tok = _errs_var.set(_errors)
    try:
        return _build(root, now, _errors)
    finally:
        _errs_var.reset(tok)


def _build(root: Path, now: float, _errors: list[str]) -> dict:
    for k in REQUIRED:
        if not _paths(root)[k].exists():
            _warn(f"缺少必需来源 {_paths(root)[k]}")
    closed = _closed(root, now)
    items: list[dict] = []
    for r in requests(root):
        if r.get("kind", "decide") == "decide" and str(r["id"]) not in closed:
            it = _decide_item(r)
            if it:
                items.append(it)
    for r in master_rows(root):
        if r["id"] not in closed:
            items.append({**r, "category_label": CATEGORIES[r["category"]], "options": DECIDE_OPTS, "media": [], "scores": [],
                          "recommend": None, "at": ""})
    sn_items, master_waits = sentinel_waits(root)
    for r in sn_items:
        if r["id"] not in closed:
            items.append({**r, "category_label": CATEGORIES.get(r["category"], "要你拍板"), "options": DECIDE_OPTS, "media": [],
                          "scores": [], "recommend": None, "at": ""})
    scan = scan_takes(root)
    items += [x for x in spot_items(root, scan) if x["id"] not in closed]
    picks, auto_picks = pick_items(root, closed)
    items += picks
    for a in auto_picks:     # 只剩一张过契约 → 系统直接选（记 by=POLICY，不再出现）
        _auto_pick(root, a)
    for x in items:
        x["kind_label"] = KIND_LABEL.get(x["kind"], x["kind"])
    today = time.strftime("%Y-%m-%d", time.localtime(now))
    policy_today = sum(1 for d in decisions(root) if d.get("by") == "POLICY" and str(d.get("at", "")).startswith(today))
    signed_today = sum(1 for r in _rows(_paths(root)["signed"]) if str(r.get("at", "")).startswith(today))
    counts = {k: sum(1 for x in items if x["kind"] == k) for k in KIND_LABEL}
    errs = list(dict.fromkeys(_errors))
    if errs:
        _alert(root, errs)
    st = _json(_paths(root)["state"], {}) or {}
    return {"schema": "nsfs.owner_queue/1", "at": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(now)), "count": len(items),
            "counts": counts, "items": items,
            "auto_today": {"passed": scan["auto_pass"], "rejected": scan["auto_fail"], "signed": signed_today + len(scan["today_signed"]),
                           "policy": policy_today, "redo": scan["redo"], **{f"n_{k}": v for k, v in scan["by_stage"].items()},
                           "agreement": st.get("agreement"), "agreement_n": st.get("n"),
                           "total": sum(scan["by_stage"].values()) + policy_today},
            "master_waits": master_waits, "machine_signed": machine_signed(root, scan), "autosign_mode": autosign_mode(root),
            "source_errors": errs, "complete": not errs, "status": "error" if errs else "ok",
            "status_label": ("队列读取失败：" + "、".join(dict.fromkeys(_src_name(e) for e in errs))) if errs else ""}


def _src_name(err: str) -> str:
    m = re.search(r"([\w.-]+\.(?:json|jsonl|md))", err)
    return m.group(1) if m else err[:40]


def _auto_pick(root: Path, a: dict) -> None:
    if not a.get("only"):
        return
    row = {"id": a["id"], "kind": "pick", "choice": a["only"], "by": "POLICY", "reason": "只有一张过了生成契约，系统直接选它", "source": "owner_queue"}
    c = a.get("cand") or {}
    if a.get("apply") == "activate" and c.get("sid") and c.get("stage") and c.get("n") is not None:
        row["applied"] = _activate(c["sid"], c["stage"], int(c["n"]), "POLICY（L-116 只剩一张过契约）")
    _record(root, row)


def _activate(sid: str, stage: str, n: int, who: str) -> str:
    try:
        from ns_render import pipeline as P
        P.set_active(sid, stage, n, reason="待你看队列：挑一张", actor=who)
        return "设为当前"
    except Exception as e:  # noqa: BLE001
        return f"没设成当前：{e}"[:200]


def _find(root: Path, item_id: str) -> dict | None:
    q = build(root)
    return next((x for x in q["items"] if x["id"] == item_id), None)


def _autosign():
    f = REPO / "tools" / "vqa" / "autosign.py"
    spec = importlib.util.spec_from_file_location("ns_tools_autosign", f)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)   # type: ignore[union-attr]
    return mod


# ------------------------------------------------------------------ 抽检不同意 → 自动作废、按原因重出、记入回归样本（总调度 11-02 14:0x，K-UI-055）
SPOT_PLANS = [   # 原因词 → producer 驳回计划（plan_item 口径）；按顺序取第一个命中的
    (("身份", "不像", "脸"), ["frame_v9:double_face", "frame_v9:double_face"]),
    (("造型", "衣服", "服装", "鞋", "饰品"), ["frame_v9:faces_look", "frame_v9:faces_look"]),
    (("假", "塑料", "质感", "油光"), ["frame_v9_heavy", "frame_v9_heavy"]),
]
SPOT_PLAN_DEFAULT = ["frame_v9", "frame_v9"]   # 手 / 肢体、场景、多人、没写理由：换 seed 重出两次
REGRESSION_REL = Path("data") / "vqa" / "regression" / "owner_spot_fail.jsonl"
NL = chr(10)


def spot_plan(reason: str) -> list[str]:
    for words, plan in SPOT_PLANS:
        if any(w in (reason or "") for w in words):
            return plan
    return SPOT_PLAN_DEFAULT


def _producer_reject(oid: str, n: int, reason: str, plan: list[str], by: str) -> dict:
    """按现行分工（出图由笔记本 producer 统一负责，tools/autopilot/full_redo.py executor=laptop）调 producer.py reject：
    版本记 master_reject（原因）、是当前就撤下、按计划重出、替换版过契约 + 看图闸门后换上"""
    import subprocess
    r = subprocess.run([sys.executable, str(REPO / "tools/autopilot/producer.py"), "reject", "--obj", oid, "--n", str(n), "--reason", reason,
                        "--plan", ",".join(plan), "--by", by], capture_output=True, text=True, encoding="utf-8", errors="replace",
                       timeout=120, cwd=str(REPO), env={**__import__("os").environ, "PYTHONUTF8": "1"})
    return {"ok": r.returncode == 0, "rc": r.returncode, "err": (r.stderr or "")[-300:] if r.returncode else ""}


def spot_fail_redo(root: Path, it: dict, reason: str, user: str, redo_fn=None) -> dict:
    """项目方抽检“不同意”：① 交 producer 作废这一版并按原因重出（原因写进 master_reject，autosign history 自动把它当“人判不过”样本）；
    ② 记一条回归样本 data/vqa/regression/owner_spot_fail.jsonl（auto=pass、human=fail，给 VQAGATE 补回归集）；失败开工单 OWNERQ-REDO"""
    stage, sid, n = it["stage"], it["sid"], int(it["n"])
    oid = f"{'first' if stage == 'image' else 'last'}:{sid}"
    why = f"项目方抽检不同意：{reason.strip() or '没写理由'}"
    plan = spot_plan(reason)
    try:
        res = (redo_fn or _producer_reject)(oid, n, why, plan, f"owner_queue（项目方 {user} 抽检）")
    except Exception as e:  # noqa: BLE001 — 重出没派成：不吞掉，开工单让人跟
        res = {"ok": False, "err": repr(e)[:300]}
    t = _take(root, sid, stage, n) or {}
    reg = root / REGRESSION_REL
    reg.parent.mkdir(parents=True, exist_ok=True)
    with _lock, reg.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "sid": sid, "stage": stage, "n": n, "file": t.get("file"),
                            "auto": "pass", "human": "fail", "reason": reason, "by": user, "src": "owner_queue spot",
                            "scores": _scores(t)}, ensure_ascii=False) + NL)
    if not res.get("ok"):
        p = root / ALERTS_REL
        p.parent.mkdir(parents=True, exist_ok=True)
        with _lock, p.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "id": "OWNERQ-REDO", "owner_loop": "UIRSI", "severity": "P1",
                                "title": f"抽检不同意后自动重出没派成：{oid} v{n}", "err": res.get("err")}, ensure_ascii=False) + NL)
    return {"obj": oid, "n": n, "plan": plan, "reason": why, **res}


def decide(root: Path, item_id: str, choice: str, reason: str, user: str, spot_fn=None, redo_fn=None) -> dict:
    it = _find(root, item_id)
    if not it:
        raise HTTPException(404, f"队列里没有 {item_id}（可能已经处理过）")
    keys = {o["key"] for o in it.get("options") or []}
    if choice not in keys:
        raise HTTPException(400, f"{item_id} 只能选：{'、'.join(sorted(keys))}")
    row = {"id": item_id, "kind": it["kind"], "choice": choice, "label": next((o["label"] for o in it["options"] if o["key"] == choice), choice),
           "reason": (reason or "")[:300], "by": user, "source": it.get("source"), "title": it.get("title")}
    if it["kind"] == "spot" and choice in ("pass", "fail"):
        mod = None if spot_fn else _autosign()
        fn = spot_fn or mod.spot
        try:
            if it.get("derived") and mod is not None:   # 队列抽出的样本先按 autosign 自己的写法登记进抽检表，再交 autosign.spot 判
                t = _take(root, it["sid"], it["stage"], it["n"]) or {}
                mod._append(mod.SPOT, {"id": it["spot_id"], "file": t.get("file"), "auto": "pass", "human": None,
                                       "queued_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "by": "owner_queue（L-116 每 10 张抽 1 张）"})
            row["autosign"] = fn(it["spot_id"], choice)
        except SystemExit as e:
            raise HTTPException(409, str(e.code)) from e
        if choice == "fail":
            row["redo"] = spot_fail_redo(root, it, reason or "", user, redo_fn)
    if it["kind"] == "pick" and choice != "later" and it.get("apply") == "activate":
        c = next((c for c in it.get("candidates") or [] if c["key"] == choice), {})
        if c.get("sid") and c.get("stage") and c.get("n") is not None:
            row["applied"] = _activate(c["sid"], c["stage"], int(c["n"]), f"owner:{user}")
    _record(root, row)
    return {"ok": True, "decision": row, "count": build(root)["count"]}


UNDO_S = 600


def undo(root: Path, item_id: str, user: str) -> dict:
    """撤销 10 分钟内的决定（Z）：记一行 undo，项目重新进队列。抽检结论已交给机签（autosign），撤不回"""
    last = next((d for d in reversed(decisions(root)) if d.get("id") == item_id), None)
    if not last or last.get("choice") == "undo":
        raise HTTPException(404, f"{item_id} 没有可撤销的决定")
    if last.get("kind") == "spot" and last.get("choice") in ("pass", "fail"):
        raise HTTPException(409, "抽检结论已经交给机签统计，撤不回；需要改判请告诉总调度")
    try:
        age = time.time() - time.mktime(time.strptime(last.get("at", "")[:19], "%Y-%m-%dT%H:%M:%S"))
    except ValueError:
        age = UNDO_S + 1
    if age > UNDO_S:
        raise HTTPException(409, "超过 10 分钟，不能撤销")
    _record(root, {"id": item_id, "kind": last.get("kind"), "choice": "undo", "by": user, "undo_of": last.get("choice")})
    return {"ok": True, "count": build(root)["count"]}


# ------------------------------------------------------------------ HTTP
class Decide(BaseModel):
    id: str
    choice: str
    reason: str = ""
    by: str = ""


@router.get("/api/owner/queue")
def get_queue():
    return build(REPO)


@router.post("/api/owner/decide")
def post_decide(body: Decide, request: Request):
    from ns_api import auth
    u = auth.user_of(request)
    if body.by != "owner" or not u or u.get("role") != "owner":
        raise HTTPException(403, "只有登录的项目方本人能在这里决定（登录即本人，不用打字）")
    return decide(REPO, body.id, body.choice, body.reason, u["name"])


class Undo(BaseModel):
    id: str
    by: str = ""


@router.post("/api/owner/undo")
def post_undo(body: Undo, request: Request):
    from ns_api import auth
    u = auth.user_of(request)
    if body.by != "owner" or not u or u.get("role") != "owner":
        raise HTTPException(403, "只有登录的项目方本人能撤销")
    return undo(REPO, body.id, u["name"])
