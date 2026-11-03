"""W30 · PLAN_OWNER_CHAT 分期 2：项目方 chat 助手（只读）。

项目方 11-03 16:0x：“一旦需要我做什么就直接谈信息出来……改成带 chat 的 llm 模型……llm 模型用我 flash 那个 api，
现在为了省钱，你用 fable 来接管，等项目开发完成后再切换到 flash api”。点选：Q1=现在做、Q2=B（只 C-11 四类确认）、Q3=Fable、Q4=推手机复用现有通道。

原则（docs/master/PLAN_OWNER_CHAT.md §0）：
  - 只有一条登记链：list_todo() 就是 GET /api/owner/queue 的同一个函数 owner_queue.build()，不另起状态；
  - 模型只做“翻译与整理”：一句“现在要你做什么” + 可点动作建议；本期动作一律不执行，只回 proposed_actions 给前端画灰按钮（标“下一期”）；
  - 送模型的只有文字：图 / 视频 / 音频地址、文件路径一律剥掉（成人相关候选只在自有机器看图，K-REV-V01）。

模型（config/llm_providers.json purposes.owner_chat，只改配置不改代码）：
  provider = "claude_cli" → 无头 `claude -p`（命令取 config/pipeline/agent_dispatcher.json claude_cmd，同派单器的 claude 通道），
                            --tools "" 关掉全部工具、不连 MCP、不留会话，只当纯文字模型用；
  provider = 其它（如 abliteration）→ ns_api.llm_config 的统一 OpenAI 兼容客户端（resolve + chat_request）。

协议：模型每轮只回一个 JSON 对象
  {"say": "给项目方的话", "need": "一句现在要你做什么", "tool_calls": [{"tool": "explain", "args": {"item_id": "..."}}],
   "proposed_actions": [{"tool": "pick", "args": {...}, "label": "用推荐的 2 号"}]}
  tool_calls 只执行只读白名单（list_todo / explain），最多 MAX_ROUNDS 轮；白名单外的、任何“执行”类输出 → 拦下、记 blocked，不执行。

接口：
  POST /api/owner/chat         {message, history[{role,content}]} → {reply, need, proposed_actions[], blocked[], tools_used[], model, error?}
                               只有登录的项目方能用（花模型钱）；请求 / 回复落 data/owner_chat/log.jsonl
  GET  /api/owner/chat/digest  → {sentence, count, counts, at}  一句话汇总当前要项目方做的事（不调模型、$0，供常驻 / 推送复用）
"""
from __future__ import annotations

import json
import re
import subprocess
import threading
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ns_api import owner_queue as OQ

REPO = Path(__file__).resolve().parents[3]
router = APIRouter(tags=["owner-chat"])
_lock = threading.Lock()

PURPOSE = "owner_chat"
READ_TOOLS = ("list_todo", "explain")                               # 本期服务端真执行的只有这两个（只读）
ACTION_TOOLS = ("pick", "decide", "gate", "undo", "upload_ref")      # 下一期才执行；本期只回显成灰按钮
MAX_ROUNDS = 3
HISTORY_KEEP = 12
LOG_REL = "data/owner_chat/log.jsonl"
DEFAULT_PURPOSE = {"provider": "claude_cli", "model": "fable", "timeout_s": 180}
EXEC_KEYS = ("execute", "exec", "run", "do", "apply", "actions", "commands", "shell", "bash", "call")   # 模型自造的“执行”字段 → 拦
STATUS_WORD = {"pass": "过了", "ok": "过了", "fail": "没过", "warn": "有提醒", "na": "不适用", "skip": "没查", None: "没结果"}
KIND_WORD = {"decide": "要你拍板", "spot": "机签抽检（看一眼）", "pick": "挑一张"}
_MEDIA_RE = re.compile(r"(https?://\S+|/api/\S+|data:[\w/+.-]+;base64,\S+|[\w./\\:-]+\.(?:png|jpe?g|webp|gif|bmp|tiff?|mp4|mov|webm|mkv|wav|mp3|flac|safetensors))",
                       re.I)
MEDIA_KEYS = {"media", "url", "thumb", "full", "file", "audio", "thumb_url", "image", "images", "video", "path", "pick_api"}


class ChatBody(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)
    history: list[dict] = Field(default_factory=list)


# ------------------------------------------------------------------ 配置
def purpose_cfg(root: Path = REPO) -> dict:
    try:
        cfg = json.loads((root / "config/llm_providers.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cfg = {}
    return {**DEFAULT_PURPOSE, **((cfg.get("purposes") or {}).get(PURPOSE) or {})}


def _claude_cmd(root: Path) -> list[str]:
    try:
        d = json.loads((root / "config/pipeline/agent_dispatcher.json").read_text(encoding="utf-8"))
        return list(d.get("claude_cmd") or []) or ["claude"]
    except (OSError, ValueError):
        return ["claude"]


# ------------------------------------------------------------------ 只送文字（剥媒体）
def scrub(v):
    """递归去掉媒体字段和任何像图 / 视频 / 音频地址、文件路径的字符串。送模型前每一份载荷都过这里。"""
    if isinstance(v, dict):
        return {k: scrub(x) for k, x in v.items() if k not in MEDIA_KEYS}
    if isinstance(v, list):
        return [scrub(x) for x in v]
    if isinstance(v, str):
        return _MEDIA_RE.sub("[图略]", v)
    return v


def _text_item(it: dict) -> dict:
    rec = it.get("recommend") or {}
    out = {"id": it.get("id"), "kind": it.get("kind"), "kind_label": KIND_WORD.get(it.get("kind"), it.get("kind_label") or it.get("kind")),
           "category": it.get("category_label") or it.get("category"), "title": it.get("title") or "", "detail": it.get("detail") or "",
           "recommend": {"choice": rec.get("choice"), "why": rec.get("why") or ""} if rec else None,
           "options": [{"key": o.get("key"), "label": o.get("label")} for o in it.get("options") or [] if isinstance(o, dict)]}
    if it.get("candidates"):
        out["candidates"] = [{"key": c.get("key"), "label": c.get("label"), "score": c.get("score")} for c in it["candidates"]]
    if it.get("people"):
        out["people"] = [{k: p.get(k) for k in ("name", "look", "label") if p.get(k)} for p in it["people"] if isinstance(p, dict)]
    return scrub(out)


# ------------------------------------------------------------------ 只读工具
def queue(root: Path = REPO) -> dict:
    """与 GET /api/owner/queue 同一个函数（owner_queue.build），不另起状态"""
    return OQ.build(root)


def list_todo(root: Path = REPO, q: dict | None = None) -> dict:
    q = q if q is not None else queue(root)
    mw = q.get("master_waits") or {}
    return {"count": q.get("count", len(q.get("items") or [])), "counts": q.get("counts") or {},
            "items": [_text_item(x) for x in q.get("items") or []],
            "not_for_you": mw.get("title") or "", "queue_ok": q.get("status", "ok") == "ok", "queue_note": q.get("status_label") or ""}


def _score_line(s: dict) -> str:
    word = STATUS_WORD.get(s.get("status"), str(s.get("status")))
    t = s.get("title") or s.get("id") or "检查项"
    d = (s.get("detail") or "").strip()
    return f"{t}：{word}" + (f"（{d}）" if d and s.get("status") not in ("pass", "ok") else "")


def explain(item_id: str, root: Path = REPO, q: dict | None = None) -> dict:
    """把一条待办的系统理由（契约检查项 / 评审理由 / 推荐理由）翻成人话。只读，只回文字。"""
    q = q if q is not None else queue(root)
    it = next((x for x in q.get("items") or [] if str(x.get("id")) == str(item_id)), None)
    if not it:
        return scrub({"item_id": item_id, "found": False, "text": "这件事已经不在你的待办里了（可能已经处理，或系统已按规则代选）。"})
    parts = [f"这是一条「{KIND_WORD.get(it.get('kind'), it.get('kind'))}」：{it.get('title') or ''}。"]
    if it.get("detail"):
        parts.append(str(it["detail"]))
    rec = it.get("recommend") or {}
    if rec.get("choice"):
        lab = next((o.get("label") for o in it.get("options") or [] if isinstance(o, dict) and str(o.get("key")) == str(rec["choice"])), rec["choice"])
        parts.append(f"系统建议：{lab}" + (f"，因为{rec['why']}" if rec.get("why") else "") + "。")
    sc = it.get("scores") or []
    bad = [s for s in sc if s.get("status") not in ("pass", "ok", "na")]
    if sc:
        parts.append(f"自动检查 {len(sc)} 项，" + ("全部过了。" if not bad else f"{len(bad)} 项要注意：" + "；".join(_score_line(s) for s in bad[:6]) + "。"))
    if it.get("kind") == "decide" and it.get("category_label"):
        parts.append(f"为什么找你：这属于「{it['category_label']}」，按规矩只有你能拍板（C-11）。")
    return scrub({"item_id": item_id, "found": True, "kind": it.get("kind"), "text": "".join(parts),
                  "checks": [_score_line(s) for s in sc[:12]]})


# ------------------------------------------------------------------ 一句话汇总（$0，不调模型）
def digest_sentence(q: dict) -> str:
    items = q.get("items") or []
    if q.get("status") == "error":
        return f"待办读取不全（{q.get('status_label') or '有来源读不到'}），系统已报卡点；先别依赖这个数字。"
    if not items:
        mw = (q.get("master_waits") or {}).get("n") or 0
        auto = (q.get("auto_today") or {}).get("total") or 0
        tail = []
        if auto:
            tail.append(f"今天系统已自动处理 {auto} 项")
        if mw:
            tail.append(f"另有 {mw} 项由总调度在处理")
        return "现在没有要你做的事" + ("；" + "，".join(tail) if tail else "") + "。"
    c = {}
    for x in items:
        c[x.get("kind")] = c.get(x.get("kind"), 0) + 1
    seg = "、".join(f"{KIND_WORD.get(k, k).split('（')[0]} {n} 件" for k, n in sorted(c.items(), key=lambda kv: ("decide", "pick", "spot").index(kv[0]) if kv[0] in ("decide", "pick", "spot") else 9))
    first = sorted(items, key=lambda x: ("decide", "pick", "spot").index(x.get("kind")) if x.get("kind") in ("decide", "pick", "spot") else 9)[0]
    return scrub(f"现在要你做 {len(items)} 件事（{seg}），先看：{first.get('title') or first.get('id')}。")


def digest(root: Path = REPO) -> dict:
    q = queue(root)
    return {"schema": "nsfs.owner_chat_digest/1", "at": time.strftime("%Y-%m-%dT%H:%M:%S"), "sentence": digest_sentence(q),
            "count": q.get("count", len(q.get("items") or [])), "counts": q.get("counts") or {}}


# ------------------------------------------------------------------ 模型
SYSTEM = """你是短剧生产线里项目方的助手。你只做“翻译与整理”：把系统待办翻成一句人话，告诉项目方现在要他做什么、为什么、点哪里。
规矩：
- 只根据工具给你的数据说话，不编造；不出现系统内部 id（镜号、集数用人话说）；每次回复 ≤3 句、动词开头。
- 你本期只能用只读工具：list_todo（看待办）、explain（{"item_id": "..."}，把一条待办的理由翻成人话）。
- 你不能执行任何动作。需要项目方点的，放进 proposed_actions 当建议按钮（tool 只能是 pick / decide / gate / undo / upload_ref），系统本期不会执行。
- 你看不到任何图片；不要要求看图。
只输出一个 JSON 对象，不要别的文字：
{"say": "给项目方的话", "need": "一句：现在要你做什么（没有就说现在没有要你做的事）", "tool_calls": [], "proposed_actions": [{"tool": "pick", "args": {"item_id": "...", "choice": "2"}, "label": "用推荐的 2 号"}]}
要查更多时，在 tool_calls 里写 [{"tool": "explain", "args": {"item_id": "..."}}]，此时 say/need 可以留空，系统会把结果发回给你。"""


def _flatten(messages: list[dict]) -> str:
    return "\n\n".join(f"[{m['role']}]\n{m['content']}" for m in messages)


def _call_claude_cli(pc: dict, system: str, messages: list[dict], root: Path) -> str:
    cmd = [*_claude_cmd(root), "-p", "--model", str(pc.get("model") or "fable"), "--tools", "",
           "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}', "--permission-mode", "dontAsk",
           "--no-session-persistence", "--output-format", "json", "--system-prompt", system]
    r = subprocess.run(cmd, input=_flatten(messages), capture_output=True, text=True, encoding="utf-8",
                       timeout=float(pc.get("timeout_s") or 180), cwd=str(root))
    if r.returncode != 0:
        raise RuntimeError(f"claude -p 退出码 {r.returncode}：{(r.stderr or r.stdout or '')[:300]}")
    try:
        d = json.loads(r.stdout)
        return str(d.get("result") or "")
    except ValueError:
        return r.stdout


def _call_openai_compat(pc: dict, system: str, messages: list[dict]) -> str:
    from ns_api import llm_config as LC
    rv = LC.resolve(PURPOSE, {"provider": pc.get("provider"), "model": pc.get("model")})
    with LC.chat_request(rv, [{"role": "system", "content": system}, *messages], False, pc.get("max_tokens") or 2000) as r:
        data = json.loads(r.read().decode("utf-8"))
    return str(((data.get("choices") or [{}])[0].get("message") or {}).get("content") or "")


def call_model(system: str, messages: list[dict], root: Path = REPO) -> str:
    """测试里换成桩。messages 已经过 scrub（只有文字）。"""
    pc = purpose_cfg(root)
    if pc.get("provider") == "claude_cli":
        return _call_claude_cli(pc, system, messages, root)
    return _call_openai_compat(pc, system, messages)


def _parse(text: str) -> dict:
    t = (text or "").strip()
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", t, re.S)
    cand = m.group(1) if m else t[t.find("{"): t.rfind("}") + 1] if "{" in t and "}" in t else ""
    try:
        d = json.loads(cand) if cand else None
    except ValueError:
        d = None
    return d if isinstance(d, dict) else {"say": t[:600], "need": "", "tool_calls": [], "proposed_actions": []}


def _norm_history(history: list[dict]) -> list[dict]:
    out = []
    for h in history[-HISTORY_KEEP:]:
        if isinstance(h, dict) and h.get("role") in ("user", "assistant") and isinstance(h.get("content"), str):
            out.append({"role": h["role"], "content": scrub(h["content"][:2000])})
    return out


def _actions(raw, blocked: list[dict]) -> list[dict]:
    out = []
    for a in raw if isinstance(raw, list) else []:
        if not isinstance(a, dict):
            continue
        tool = str(a.get("tool") or "")
        if tool not in ACTION_TOOLS:
            blocked.append({"tool": tool, "why": "不在动作白名单（pick / decide / gate / undo / upload_ref）"})
            continue
        out.append({"tool": tool, "args": scrub(a.get("args") if isinstance(a.get("args"), dict) else {}),
                    "label": scrub(str(a.get("label") or tool))[:40], "executable": False, "phase": "下一期"})
    return out[:4]


def chat(message: str, history: list[dict] | None = None, root: Path = REPO, user: str = "", model_fn=None) -> dict:
    model_fn = model_fn or call_model
    q = queue(root)
    todo = list_todo(root, q)
    msgs = _norm_history(history or [])
    msgs.append({"role": "user", "content": scrub(f"{message}\n\n[系统附：当前待办 list_todo()]\n{json.dumps(todo, ensure_ascii=False)}")})
    blocked: list[dict] = []
    used: list[str] = ["list_todo"]
    d: dict = {}
    err = None
    t0 = time.time()
    try:
        for _ in range(MAX_ROUNDS):
            d = _parse(model_fn(SYSTEM, msgs))
            for k in d:
                if k.lower() in EXEC_KEYS:
                    blocked.append({"tool": k, "why": "模型给出执行类输出，本期一律不执行"})
            calls = [c for c in (d.get("tool_calls") or []) if isinstance(c, dict)] if isinstance(d.get("tool_calls"), list) else []
            results = []
            for c in calls[:4]:
                tool, args = str(c.get("tool") or ""), c.get("args") if isinstance(c.get("args"), dict) else {}
                if tool == "list_todo":
                    results.append({"tool": tool, "result": todo})
                elif tool == "explain":
                    results.append({"tool": tool, "result": explain(str(args.get("item_id") or ""), root, q)})
                else:
                    blocked.append({"tool": tool, "why": "本期只读：只执行 list_todo / explain" if tool in ACTION_TOOLS else "不在工具白名单"})
                    results.append({"tool": tool, "result": {"refused": "本期不执行，只能作为 proposed_actions 建议按钮"}})
                used.append(tool)
            if not calls:
                break
            msgs.append({"role": "assistant", "content": json.dumps(d, ensure_ascii=False)[:4000]})
            msgs.append({"role": "user", "content": scrub("[工具结果]\n" + json.dumps(results, ensure_ascii=False))})
    except Exception as e:  # noqa: BLE001  模型挂了也要给项目方一句准话：退回 $0 的汇总
        err = f"{type(e).__name__}: {e}"[:300]
    sentence = digest_sentence(q)
    need = str(d.get("need") or "").strip() or sentence
    say = str(d.get("say") or "").strip() or (sentence if err or not d else "")
    out = {"schema": "nsfs.owner_chat/1", "reply": scrub(say)[:1200], "need": scrub(need)[:300],
           "proposed_actions": _actions(d.get("proposed_actions"), blocked), "blocked": blocked, "tools_used": used,
           "model": {k: purpose_cfg(root).get(k) for k in ("provider", "model")}, "ms": int((time.time() - t0) * 1000), "todo_count": todo["count"]}
    if err:
        out["error"] = f"模型没回上来，先给你系统汇总：{err}"
    _log(root, {"user": user, "message": message[:2000], "history_n": len(msgs), **{k: out[k] for k in ("reply", "need", "proposed_actions", "blocked", "tools_used", "model")},
                "error": out.get("error")})
    return out


def _log(root: Path, row: dict) -> None:
    p = root / LOG_REL
    try:
        with _lock:
            p.parent.mkdir(parents=True, exist_ok=True)
            with open(p, "a", encoding="utf-8") as f:
                f.write(json.dumps({"at": time.strftime("%Y-%m-%dT%H:%M:%S"), **row}, ensure_ascii=False) + "\n")
    except OSError:   # arch-ok: 留痕失败不影响回复
        pass


# ------------------------------------------------------------------ 接口
@router.post("/api/owner/chat")
def post_chat(body: ChatBody, request: Request):
    from ns_api import auth
    u = auth.user_of(request)
    if not u or u.get("role") != "owner":
        raise HTTPException(403, "只有登录的项目方本人能和助手对话")
    return chat(body.message, body.history, REPO, u["name"])


@router.get("/api/owner/chat/digest")
def get_digest():
    return digest(REPO)
