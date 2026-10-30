"""
剧本创作对话框（T58，REQUIREMENTS G8）。项目方 2026-10-30 先让 abliteration 写，后改回：“还是用qwen写吧，api那个太贵了”。

项目方在画布 #/script-chat 输入剧本大纲 → 写作模型（2026-10-30 夜起默认 abliteration large-flash；
服务商 / 模型在统一配置 config/llm_providers.json 选，千问已撤下）按 config/script_chat_rules.md（rules_v2）+ 按需附录 + 格式契约写剧本与镜头分镜。系统只收发：
  - 系统提示词 = 核心规则 + 按原稿触发词挑选的附录节（config/script_chat_rules_appendix.md，预算内）
    + 格式契约 + 当前剧本全局头（到第一个 `## ep` 为止，只读参考）；超出上下文预算时 fit_messages 先丢历史；
  - 模型回复原样存档；回复里的 `## ep<N>《…》` 整集按集号覆盖进本会话草稿 data/script_chat/<sid>/script.md
    （全局头 + 各集，与剧本库同格式）；
  - 草稿过 tools/validate_qwen_script.py（只查格式），不读不改内容。

模型配置（2026-10-30 夜 fredw-92/W1：改读统一配置 config/llm_providers.json，见 ns_api/llm_config.py；
默认写作模型 = abliteration large-flash，千问撤下；config/script_chat.json 只剩规则 / 附录 / 全局头等写作设置）：
  load_config() -> dict                       读 config/script_chat.json；cfg["llm"] = 本次覆盖 {provider?,model?,params?}，
                                              cfg["purpose"] = 用途（默认 script_write）
  provider(cfg=None) -> {"name"(服务商 id),"label","base_url","model","api_key",...}   密钥只用于请求头
  build_system_prompt(cfg=None) -> (text, parts)
  stream_completion(messages, cfg=None, max_tokens=None) -> 迭代 ("reasoning"|"content"|"usage", 值)
  complete(messages, cfg=None) -> {"content","reasoning","usage"}

接口（前缀 /api/script-chat）：
  GET  /config                       当前模型、是否有 key、系统提示词各部分
  GET  /system                       系统提示词全文
  GET  /sessions                     会话列表
  POST /sessions {title?, outline?, episodes?:[from,to], shots_per_ep?, seconds_per_shot?, rules?, llm?, registry_from?}
                                     新建会话；给了提纲时生成首条请求（提纲原文 + 集数 / 镜数 / 时长目标），存 pending；
                                     registry_from = 继承登记来源（会话 id / 剧本 md），其人物表 / 场景表与生产登记一起
                                     原样并进全局头的全剧人物表 / 全剧场景表（fredw-92 2026-10-31：全剧一份、逐集继承）
  GET  /sessions/{sid}               消息 + 草稿集列表 + 最近一次校验
  POST /sessions/{sid}/chat {content?, llm?}   SSE 流：reasoning / content / done{validation} / error；
                                     content 为空时发送会话的 pending（提纲首条请求）
  POST /sessions/{sid}/to-inbox      把草稿登记为剧本导入候选（不自动导入）→ {path, sha256, validation}
  POST /ab {outline, episodes, llm_a, llm_b, ...}   同一提纲建两个会话 → {a, b}（各自 /chat 写，结果进 A/B 对比页）
  GET  /rules                        可选的写作规则版本
  GET  /sessions/{sid}/repair        由最近一次校验生成的【格式返修】消息（只引用格式规则）
  POST /sessions/{sid}/validate      重新校验草稿
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from . import llm_config as LC

REPO =Path(__file__).resolve().parents[3]
CONFIG = REPO / "config" / "script_chat.json"
STORE = REPO / "data" / "script_chat"
VALIDATOR = REPO / "tools" / "validate_script_strict.py"   # 严格校验：全部 H3 规则 + Image 2.1 Turbo 检查

EP_HEAD_RE = re.compile(r"^## ep(\d+)《", re.M)

router = APIRouter(prefix="/api/script-chat")
_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def _lock(sid: str) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(sid, threading.Lock())


# ------------------------------------------------------------------ 模型配置

def load_config() -> dict:
    return json.loads(CONFIG.read_text(encoding="utf-8"))


def provider(cfg: dict | None = None) -> dict:
    """统一配置（config/llm_providers.json）里本用途的服务商 + 本次覆盖 cfg["llm"]"""
    cfg = cfg or load_config()
    try:
        rv = LC.resolve(cfg.get("purpose") or "script_write", cfg.get("llm"))
    except LC.LLMConfigError as e:
        raise ChatError(str(e)) from e
    return {**rv, "name": rv["id"], "label": rv["name"],
            "max_tokens": rv["params"].get("max_tokens") or cfg.get("max_tokens", 32000), "timeout": rv["timeout_s"]}


def rules_parts(cfg: dict, rules: str | None) -> list[str]:
    """规则版本 → 系统提示词文件（config/script_chat.json rules_versions；不给 = 现行 system_parts）"""
    vers = cfg.get("rules_versions") or {}
    if not rules:
        return cfg.get("system_parts", [])
    if rules not in vers:
        raise HTTPException(400, f"没有这个规则版本：{rules}（可选：{'、'.join(vers) or '无'}）")
    return vers[rules]


def session_cfg(s: dict, llm: dict | None = None) -> dict:
    """会话的有效配置：规则版本 + 模型覆盖（本次 llm > 会话建立时的 llm > 用途默认）"""
    cfg = load_config()
    cfg["system_parts"] = rules_parts(cfg, s.get("rules"))
    cfg["llm"] = llm or s.get("llm") or None
    cfg["registry"] = session_registry(s)
    return cfg


def session_registry(s: dict) -> dict:
    """会话的继承登记来源（fredw-92 2026-10-31 定：人物表 / 场景表全剧一份、逐集继承）：
    from = 会话建立时指定的登记来源草稿；session + before = 本会话草稿里集号 < 本次起始集的那些集（批量按集号顺序写时逐集继承）"""
    rng = s.get("episode_range") or []
    return {"from": s.get("registry_from") or [], "session": s.get("id"), "before": rng[0] if rng else 0}


PRODUCTION_SCRIPT = REPO / "data" / "import" / "script_v2.json"
_CHAR_COLS = ("角色", "角色id", "中文外貌句", "EN外貌短语", "VOICE声线短语")
_CHAR_FIELDS = ("name", "char_id", "zh", "en", "voice")
_SCENE_COLS = ("场景id", "名称", "空间描述", "时段", "光线", "固定陈设")
_SCENE_FIELDS = ("scene_id", "name", "space", "time_of_day", "light", "fixtures")


def resolve_draft(ref: str) -> Path:
    """登记来源：会话 id（data/script_chat/<id>/script.md）或相对项目根 / 绝对的剧本 md 路径"""
    p = STORE / ref / "script.md"
    if re.fullmatch(r"[\w-]+", ref or "") and p.exists():
        return p
    q = Path(ref)
    q = q if q.is_absolute() else REPO / q
    if not q.exists():
        raise ChatError(f"登记来源不存在：{ref}")
    return q


def _import_globals(path: Path):
    from ns_agent.importer.script_md import import_script
    return import_script(path).globals


def registry_tables(registry: dict | None) -> tuple[list[dict], list[dict], list[str]]:
    """继承的已登记人物 / 场景（原文逐字，系统不写）：生产 script_v2.json 的 globals 登记 → 登记来源草稿（按给定顺序）
    → 本会话集号 < before 的集。同一角色名 / 场景 id 先登记的为准（与导入器、合并导入同口径）。→ (人物, 场景, 来源)"""
    chars: dict[str, dict] = {}
    scenes: dict[str, dict] = {}
    used: list[str] = []

    def add(cs, ss, label):
        n0 = len(chars) + len(scenes)
        for c in cs or []:
            c = c if isinstance(c, dict) else c.model_dump()
            if c.get("name"):
                chars.setdefault(c["name"], c)
        for e in ss or []:
            e = e if isinstance(e, dict) else e.model_dump()
            if e.get("scene_id"):
                scenes.setdefault(e["scene_id"], e)
        if len(chars) + len(scenes) > n0:
            used.append(label)

    registry = registry or {}
    if PRODUCTION_SCRIPT.exists():
        try:
            g = json.loads(PRODUCTION_SCRIPT.read_text(encoding="utf-8")).get("globals") or {}
            add(g.get("character_registry"), g.get("scene_library"), "data/import/script_v2.json")
        except (OSError, ValueError):
            pass
    for ref in registry.get("from") or []:
        g = _import_globals(resolve_draft(ref))
        add(g.character_registry, g.scene_library, ref)
    sid, before = registry.get("session"), registry.get("before")
    if sid and before and (STORE / sid / "session.json").exists():
        eps = load_session(sid)["episodes"]
        prev = [eps[k] for k in sorted(eps, key=int) if int(k) < int(before)]
        if prev:
            tmp = STORE / "_tmp" / f"reg-{uuid.uuid4().hex[:8]}.md"
            tmp.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text("\n\n---\n\n".join(prev) + "\n\n---\n", encoding="utf-8", newline="\n")
            try:
                g = _import_globals(tmp)
                add(g.character_registry, g.scene_library, f"{sid}（ep<{before}）")
            finally:
                tmp.unlink(missing_ok=True)
    return list(chars.values()), list(scenes.values()), used


def _table(label: str, cols: tuple, fields: tuple, rows: list[dict]) -> str:
    out = [f"**{label}**：", "| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    out += ["| " + " | ".join(str(r.get(f) or "") for f in fields) + " |" for r in rows]
    return "\n".join(out)


def script_header(cfg: dict | None = None, registry: dict | None = None) -> tuple[str, str | None]:
    """当前剧本全局头（角色锁 / 统一后缀 / 触发词表），到第一个 `## ep` 为止；
    后面原样并入继承的全剧人物表 / 全剧场景表（registry_tables；全局头原文已有的角色 / 场景不重复）"""
    cfg = cfg or load_config()
    registry = registry if registry is not None else cfg.get("registry")
    for rel in cfg.get("header_sources", []):
        p = REPO / rel
        if p.exists():
            text = p.read_text(encoding="utf-8")
            m = EP_HEAD_RE.search(text)
            head = (text[: m.start()] if m else text).rstrip() + "\n"
            return head + registry_block(head, registry), rel
    return "", None


def registry_block(head: str, registry: dict | None) -> str:
    chars, scenes, _ = registry_tables(registry)
    if not chars and not scenes:
        return ""
    from ns_agent.importer.script_md import character_tables, scene_tables
    have_c = {d["cells"]["name"] for d in character_tables(head)[0]}
    have_s = {d["cells"]["scene_id"] for d in scene_tables(head)[0]}
    chars = [c for c in chars if c["name"] not in have_c]
    scenes = [e for e in scenes if e["scene_id"] not in have_s]
    parts = []
    if chars:
        parts.append(_table("全剧人物表", _CHAR_COLS, _CHAR_FIELDS, chars))
    if scenes:
        parts.append(_table("全剧场景表", _SCENE_COLS, _SCENE_FIELDS, scenes))
    return "\n" + "\n\n".join(parts) + "\n" if parts else ""


APPX_HEAD_RE = re.compile(r"^## \[(.+?)\]\s*$", re.M)
APPX_TRIG_RE = re.compile(r"^> 触发[:：]\s*(.+)$", re.M)


def appendix_sections(cfg: dict | None = None) -> list[dict]:
    """附录按节切分：`## [节名]` + `> 触发：词、词`（“全部”= 每次都带）"""
    cfg = cfg or load_config()
    rel = cfg.get("appendix")
    if not rel or not (REPO / rel).exists():
        return []
    text = (REPO / rel).read_text(encoding="utf-8")
    heads = list(APPX_HEAD_RE.finditer(text))
    out = []
    for i, m in enumerate(heads):
        body = text[m.start(): heads[i + 1].start() if i + 1 < len(heads) else len(text)].strip()
        t = APPX_TRIG_RE.search(body)
        trig = [w.strip() for w in re.split(r"[、,，]", t.group(1)) if w.strip()] if t else ["全部"]
        out.append({"name": m.group(1), "triggers": trig, "text": body})
    return out


def count_tokens(text: str, cfg: dict | None = None) -> int:
    """写作模型的 token 数（llama-server /tokenize）；没有计数接口时按字符粗估"""
    pv = provider(cfg)
    if pv.get("tokenize_url"):
        try:
            req = urllib.request.Request(pv["tokenize_url"], data=json.dumps({"content": text}).encode("utf-8"),
                                         headers={"Content-Type": "application/json"})
            return len(json.load(urllib.request.urlopen(req, timeout=60))["tokens"])
        except (OSError, ValueError, KeyError):
            pass
    return int(len(text) * 0.8)


CODE_BLOCK_RE = re.compile(r"^\*\*([^\n]+?)\*\*[^\n]*\n+```[^\n]*\n(.*?)\n```", re.S | re.M)


def compact_header(header: str) -> str:
    """精简全局头（config header_mode = "compact"）：只留代码块里的角色锁、LoRA 触发词表、姿势表，
    每条只留“名字 + 第一个括号前的短描述”。材质 / 声音 / 规格等长段说明已写进 rules_v2 核心与附录。"""
    out = []
    for title, body in CODE_BLOCK_RE.findall(header):
        lines = []
        for ln in body.splitlines():
            s = ln.strip()
            if not s:
                continue
            if s.startswith("【"):           # 角色锁：整行保留
                lines.append(s)
                continue
            s = re.split(r"[（(]", s, 1)[0].rstrip()
            lines.append(re.sub(r"\s{2,}", " ", s))
        out.append(f"{title}\n" + "\n".join(lines))
    scenes = SCENE_TABLE_RE.search(header)   # S1（fredw-92/S-back）：全剧场景表原样保留（写作模型要照用场景 id）
    if out and scenes:
        out.append(scenes.group(0).strip())
    people = CHARACTER_TABLE_RE.search(header)   # R3：全剧人物表原样保留（EN / VOICE 要逐字照抄进 H3）
    if out and people:
        out.append(people.group(0).strip())
    return "\n\n".join(out) + "\n" if out else header


SCENE_TABLE_RE = re.compile(r"^\*\*全剧场景表\*\*[^\n]*\n(?:[ \t]*\n)?(?:[ \t]*\|[^\n]*(?:\n|$))+", re.M)
CHARACTER_TABLE_RE = re.compile(r"^\*\*全剧人物表\*\*[^\n]*\n(?:[ \t]*\n)?(?:[ \t]*\|[^\n]*(?:\n|$))+", re.M)


def build_system_prompt(cfg: dict | None = None, context: str | None = None,
                        appendix_budget: int | None = None) -> tuple[str, list[dict]]:
    """核心规则（每次都带）+ 按 context（原稿 / 用户消息）触发词挑选的附录节 + 格式契约 + 剧本全局头。
    附录总量受预算限制。优先级（总调度 2026-10-30）：本集触发词直接命中的节先带、不能丢；
    标“全部”的通用节后带，空间不够先丢它们。丢掉的节在 parts 里带 dropped = "always" / "hit" 和原因；
    出现 "hit"（命中的节也放不下）时，调用方应把原稿拆成两半分两次写（tools/script_chat_batch.py）。"""
    cfg = cfg or load_config()
    pv = provider(cfg)
    parts, chunks = [], []
    for rel in cfg.get("system_parts", []):
        if not (REPO / rel).exists():
            continue
        text = (REPO / rel).read_text(encoding="utf-8").strip()
        parts.append({"name": Path(rel).name, "path": rel, "chars": len(text)})
        chunks.append(text)
    budget = pv.get("appendix_budget") if appendix_budget is None else appendix_budget
    used = 0
    secs = appendix_sections(cfg)   # 命中触发词的节先占预算，“全部”类后带
    hits = [x for x in secs if "全部" not in x["triggers"] and context and any(w in context for w in x["triggers"])]
    always = [x for x in secs if "全部" in x["triggers"]]
    for sec in hits + always:
        kind = "always" if sec in always else "hit"
        n = count_tokens(sec["text"], cfg) if budget is not None else 0
        if budget is not None and used + n > budget:
            why = ("命中本集触发词但上下文放不下" if kind == "hit" else "通用节，空间不够时优先丢")
            parts.append({"name": f"附录·{sec['name']}（未带：{why}）", "path": cfg.get("appendix"), "chars": 0,
                          "dropped": kind, "reason": why, "tokens": n})
            continue
        used += n
        parts.append({"name": f"附录·{sec['name']}", "path": cfg.get("appendix"), "chars": len(sec["text"])})
        chunks.append(sec["text"])
    header, src = script_header(cfg)
    if header and cfg.get("header_mode") == "compact":
        header = compact_header(header)
    if header:
        parts.append({"name": "剧本全局头" + ("（精简）" if cfg.get("header_mode") == "compact" else ""),
                      "path": src, "chars": len(header)})
        chunks.append("【当前剧本全局头（角色锁、统一后缀、触发词表；只读参考，照此写，不要输出它）】\n" + header)
    return "\n\n========\n\n".join(chunks), parts


def prompt_for(user_text: str, context: str | None = None, cfg: dict | None = None) -> tuple[str, list[dict]]:
    """给一条用户消息配系统提示词：附录预算 = min(配置的 appendix_budget, 上下文剩余)，
    剩余 = ctx − reserve − 输出上限 − 核心/契约/全局头 − 这条消息。空间不够时少带附录，不压输出上限。"""
    cfg = cfg or load_config()
    pv = provider(cfg)
    if not pv.get("ctx"):
        return build_system_prompt(cfg, context)
    limit = pv["ctx"] - (pv.get("reserve") or 0) - (pv.get("max_tokens") or 12000)
    user_n = count_tokens(user_text, cfg)
    base, _ = build_system_prompt(cfg, None, appendix_budget=0)
    room = limit - count_tokens(base, cfg) - user_n - 200
    budget = max(0, min(pv.get("appendix_budget") or room, room))
    for _ in range(4):   # 逐节估算与整体分词有出入：拼好后整体实测，超了就按超出量收紧附录预算再拼
        system, parts = build_system_prompt(cfg, context, appendix_budget=budget)
        over = count_tokens(system, cfg) + user_n - limit
        if over <= 0 or budget == 0:
            return system, parts
        budget = max(0, budget - over - 100)
    return system, parts


def fit_messages(messages: list[dict], cfg: dict | None = None) -> tuple[list[dict], int]:
    """上下文预算（provider.ctx）：prompt + 输出 ≤ ctx。超了先丢最早的对话历史（system 和最后一条保留），
    再把输出上限压到不低于 4000；仍放不下就报错。返回 (messages, max_tokens)"""
    pv = provider(cfg)
    mt = pv.get("max_tokens") or 12000
    if not pv.get("ctx"):
        return messages, mt
    limit = pv["ctx"] - (pv.get("reserve") or 0)   # 留余量：分词误差、模板 token
    msgs = list(messages)

    def size():
        return sum(count_tokens(m["content"], cfg) + 8 for m in msgs)
    n = size()
    while n + mt > limit and len(msgs) > 2:
        del msgs[1]
        n = size()
    if n + mt > limit:
        mt = limit - n
    if mt < 4000:
        raise ChatError(f"上下文超预算：prompt 约 {n} token，{pv['name']} 每请求上限 {pv['ctx']}，留给输出不足 4000；"
                        "请把这条消息拆短，或减少附录")
    return msgs, mt


HTTP_HINT = LC.HTTP_HINT


class ChatError(RuntimeError):
    """给项目方看的错误（界面原样显示）"""


def _request(messages: list[dict], cfg: dict, stream: bool, max_tokens: int | None):
    """统一配置的 /chat/completions（ns_api/llm_config.chat_request；错误中文、密钥遮盖）"""
    pv = provider(cfg)
    return LC.chat_request(pv, messages, stream, max_tokens or pv["max_tokens"], error_cls=ChatError)


def stream_completion(messages: list[dict], cfg: dict | None = None, max_tokens: int | None = None):
    cfg = cfg or load_config()
    messages, fit_mt = fit_messages(messages, cfg)
    with _request(messages, cfg, True, min(max_tokens or fit_mt, fit_mt)) as r:
        try:
            yield from _sse(r)
        except (TimeoutError, OSError) as e:   # 读流途中断线 / 超时
            raise ChatError(f"流式输出中断：{e}；已收到的部分已存档，可以发“继续”或重新发送") from e


def _sse(r):
    for raw in r:
        line = raw.decode("utf-8", "replace").strip()
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if data == "[DONE]":
            break
        try:
            d = json.loads(data)
        except ValueError:
            continue
        if d.get("usage"):
            yield "usage", d["usage"]
        for ch in d.get("choices") or []:
            delta = ch.get("delta") or {}
            rs = delta.get("reasoning") or delta.get("reasoning_content")
            if rs:
                yield "reasoning", rs
            if delta.get("content"):
                yield "content", delta["content"]
            if ch.get("finish_reason"):
                yield "finish", ch["finish_reason"]


def complete(messages: list[dict], cfg: dict | None = None, max_tokens: int | None = None) -> dict:
    out = {"content": "", "reasoning": "", "usage": None, "finish": None}
    for kind, val in stream_completion(messages, cfg, max_tokens):
        if kind in ("content", "reasoning"):
            out[kind] += val
        else:
            out[kind] = val
    return out


# ------------------------------------------------------------------ 会话与草稿

def _sdir(sid: str) -> Path:
    if not re.fullmatch(r"[0-9A-Za-z_-]{6,64}", sid):
        raise HTTPException(400, "会话 id 不合法")
    return STORE / sid


def load_session(sid: str) -> dict:
    p = _sdir(sid) / "session.json"
    if not p.exists():
        raise HTTPException(404, "会话不存在")
    return json.loads(p.read_text(encoding="utf-8"))


class session_file_lock:
    """跨进程锁（data/script_chat/<sid>/.lock，O_EXCL 创建）：批量、返修工具、画布 API 同时改同一会话时，
    “读入 → 修改 → 写回”整段互斥，避免后写的覆盖先写的（封板修复）。超过 120 秒的锁视为残留，直接接管。"""

    def __init__(self, sid: str, wait: float = 60.0):
        self.path, self.wait = _sdir(sid) / ".lock", wait

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        t0 = time.time()
        while True:
            try:
                os.close(os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
                return self
            except FileExistsError:
                try:
                    if time.time() - self.path.stat().st_mtime > 120:
                        self.path.unlink(missing_ok=True)
                        continue
                except OSError:
                    continue
                if time.time() - t0 > self.wait:
                    raise TimeoutError(f"会话锁等待超时：{self.path}")
                time.sleep(0.2)

    def __exit__(self, *exc):
        self.path.unlink(missing_ok=True)


def update_session(sid: str, fn) -> dict:
    """加锁读入会话 → fn(s) 原地修改 → 写回；返回修改后的会话"""
    with session_file_lock(sid):
        s = load_session(sid)
        fn(s)
        save_session(s)
        return s


def save_session(s: dict) -> None:
    d = _sdir(s["id"])
    d.mkdir(parents=True, exist_ok=True)
    tmp = d / "session.json.tmp"
    tmp.write_text(json.dumps(s, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n")
    tmp.replace(d / "session.json")


def outline_message(outline: str, episodes: list[int] | None = None, shots_per_ep: int | None = None,
                    seconds_per_shot: float | None = None) -> str:
    """提纲首条请求：项目方提纲原文 + 集数 / 镜数 / 时长目标（只拼参数，不加内容）"""
    lines = ["【提纲（项目方提供，原文）】", outline.strip(), "", "【本次要写】"]
    if episodes:
        a, b = episodes[0], episodes[-1]
        lines.append(f"- 集数：ep{a:02d}" + (f"–ep{b:02d}（共 {b - a + 1} 集）" if b != a else "（1 集）"))
    if shots_per_ep:
        lines.append(f"- 每集镜头数目标：约 {shots_per_ep} 镜")
    if seconds_per_shot:
        lines.append(f"- 每镜时长目标：约 {seconds_per_shot:g} 秒")
    lines.append("- 按系统提示词里的写作规则与格式契约输出每一集（整集，从 `## ep` 到 `---`）。")
    return "\n".join(lines)


def new_session(title: str | None = None, independent: bool = False, **brief) -> dict:
    """brief：outline / episodes [from,to] / shots_per_ep / seconds_per_shot / rules / llm（规格 8.1）"""
    sid = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
    s = {"id": sid, "title": title or "新剧本", "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
         "independent": independent, "messages": [], "episodes": {}, "validation": None}
    eps = brief.get("episodes")
    if eps:
        if len(eps) not in (1, 2) or min(eps) < 1 or eps[0] > eps[-1]:
            raise HTTPException(400, "episodes 要写成 [起始集, 结束集]，集号从 1 开始")
        eps = [int(eps[0]), int(eps[-1])]
    if brief.get("rules"):
        rules_parts(load_config(), brief["rules"])   # 校验规则版本
    if brief.get("llm"):
        try:
            LC.resolve("script_write", brief["llm"])
        except LC.LLMConfigError as e:
            raise HTTPException(400, str(e)) from e
    for ref in brief.get("registry_from") or []:   # 继承登记来源（会话 id 或剧本 md 路径），建会话时就校验存在
        try:
            resolve_draft(ref)
        except ChatError as e:
            raise HTTPException(400, str(e)) from e
    s.update({k: v for k, v in {"outline": brief.get("outline"), "episode_range": eps,
                                "shots_per_ep": brief.get("shots_per_ep"),
                                "seconds_per_shot": brief.get("seconds_per_shot"),
                                "rules": brief.get("rules"), "llm": brief.get("llm"),
                                "ab": brief.get("ab"), "registry_from": brief.get("registry_from")}.items() if v})
    if (brief.get("outline") or "").strip():
        s["pending"] = outline_message(brief["outline"], eps, brief.get("shots_per_ep"), brief.get("seconds_per_shot"))
        if not title:
            s["title"] = brief["outline"].strip().splitlines()[0][:30]
    save_session(s)
    return s


def unwrap(text: str) -> str:
    """模型偶尔把整篇包进 ```markdown 代码块：只去掉最外层这一对围栏"""
    t = text.strip()
    m = re.match(r"^```(?:markdown|md)\s*\n(.*)\n```\s*$", t, re.S)
    return m.group(1) if m else t


def split_episodes(text: str) -> dict[int, str]:
    """回复里的整集：`## ep<N>《` 到下一个 `## ep` / 文末，去掉结尾的 ---"""
    t = unwrap(text)
    heads = list(EP_HEAD_RE.finditer(t))
    out = {}
    for i, m in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(t)
        body = re.sub(r"\n-{3,}\s*$", "", t[m.start():end].rstrip()).rstrip()
        out[int(m.group(1))] = body
    return out


SHOT_HEAD_RE = re.compile(r"^\*\*镜(\d+)｜img", re.M)
SHOT_END_RE = re.compile(r"^\*\*负面追加\*\*", re.M)


def split_shots(ep_text: str) -> tuple[str, dict[int, str], str]:
    """整集 → (集头, {镜号: 这一镜全文（从 **镜N｜img 到下一镜前）}, 集尾如 **负面追加**)"""
    heads = list(SHOT_HEAD_RE.finditer(ep_text))
    if not heads:
        return ep_text, {}, ""
    tail_m = SHOT_END_RE.search(ep_text, heads[-1].start())
    end = tail_m.start() if tail_m else len(ep_text)
    shots = {}
    for i, m in enumerate(heads):
        stop = heads[i + 1].start() if i + 1 < len(heads) else end
        shots[int(m.group(1))] = ep_text[m.start():stop].rstrip() + "\n"
    return ep_text[: heads[0].start()], shots, ep_text[end:]


def merge_shot(ep_text: str, index: int, shot_text: str) -> str:
    """用模型返修后的这一镜替换原镜（只认回复里第一个 `**镜<index>｜img` 块）"""
    _, got, _ = split_shots(unwrap(shot_text))
    if index not in got:
        raise ValueError(f"返修回复里没有镜{index}")
    head, shots, tail = split_shots(ep_text)
    shots[index] = got[index]
    return head + "\n".join(shots[k].rstrip() + "\n" for k in sorted(shots)) + ("\n" + tail if tail else "")


def write_draft(s: dict) -> Path:
    # 草稿 = 全局头 + 继承登记（只外部来源：生产登记 + 登记来源草稿；本会话各集本身就在文件里，按集号先登记为准）+ 各集
    header, _ = script_header(registry={"from": s.get("registry_from") or []})
    eps = [s["episodes"][k] for k in sorted(s["episodes"], key=int)]
    p = _sdir(s["id"]) / "script.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(header + "\n---\n\n" + "\n\n---\n\n".join(eps) + ("\n\n---\n" if eps else ""), encoding="utf-8",
                 newline="\n")
    return p


GATE_VALIDATOR = REPO / "tools" / "validate_qwen_script.py"   # 导入关口同款（script_inbox 用它）：决定“可否送导入”


def _run_validator(tool: Path, p: Path, episode: int | None) -> tuple[dict | None, str]:
    cmd = [sys.executable, str(tool), str(p), "--json"] + (["--episode", str(episode)] if episode else [])
    r = subprocess.run(cmd, capture_output=True, cwd=REPO, timeout=900,
                       env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    try:
        return json.loads(r.stdout.decode("utf-8")), ""
    except ValueError:
        return None, (r.stderr or b"").decode("utf-8", "replace")[-800:]


def _ikey(i: dict) -> tuple:
    return i.get("rule_id"), i.get("field"), i.get("detail")


def _hint_new(i: dict, gate: dict) -> bool:
    """严格校验的一条是否另列为提示：关口没有这条，或关口只报 warn 而严格报 block"""
    k = _ikey(i)
    return k not in gate or (i.get("level") == "block" and gate[k] != "block")


def validate_draft(s: dict, episode: int | None = None) -> dict | None:
    """格式校验；episode 给定时只校这一集，结果并入 s['validation']。
    fredw-92 定（2026-10-30 夜）：blocking / warnings / issues / repair / can_send 只来自导入关口同款
    tools/validate_qwen_script.py；tools/validate_script_strict.py 多查出来的条目另列为“附加提示”
    （episodes[].hints / hint_issues、shots[].hints、合计 hints），不算阻断，两个数字不混。"""
    if not s["episodes"]:
        return None
    p = write_draft(s)
    rep, err = _run_validator(GATE_VALIDATOR, p, episode)
    if rep is None:
        return {"error": err}
    strict, _ = _run_validator(VALIDATOR, p, episode)   # 附加提示；出错就不给
    st_eps = {e["number"]: e for e in (strict or {}).get("episodes", [])}
    old = {e["number"]: e for e in ((s.get("validation") or {}).get("episodes") or [])} if episode else {}
    for e in rep["episodes"]:
        se = st_eps.get(e["number"]) or {"issues": [], "shots": []}
        # fredw-92/D2：同一条在关口是 warn、严格校验是 block（如 QW-C3）时也列为提示（带 block 级），否则严格 block 被吞掉；
        # 有 block 级提示的镜 / 集另带 hint_repair（严格校验的返修原文），/repair 在关口没有返修时用它（can_send 仍只看关口）
        gate_ep = {_ikey(i): i["level"] for i in e["issues"]}
        ep_hints = [{**i, "hint": True} for i in se["issues"] if _hint_new(i, gate_ep)]
        st_shots = {sh["id"]: sh for sh in se["shots"]}
        shots = []
        for sh in e["shots"]:
            gk = {_ikey(i): i["level"] for i in sh["issues"]}
            st = st_shots.get(sh["id"]) or {}
            hints = [{**i, "hint": True} for i in st.get("issues", []) if _hint_new(i, gk)]
            shots.append({"id": sh["id"], "index": sh["index"], "duration": sh["duration"], "ok": sh["ok"],
                          "issues": sh["issues"], "repair": sh["repair"], "hints": hints,
                          "hint_repair": st.get("repair") if any(i["level"] == "block" for i in hints) else ""})
        old[e["number"]] = {"number": e["number"], "title": e["title"],
                            "blocking": sum(i["level"] == "block" for i in e["issues"])
                            + sum(i["level"] == "block" for sh in e["shots"] for i in sh["issues"]),
                            "warnings": sum(i["level"] != "block" for i in e["issues"])
                            + sum(i["level"] != "block" for sh in e["shots"] for i in sh["issues"]),
                            "issues": e["issues"], "repair": e["repair"], "shots": shots,
                            "hint_issues": ep_hints, "hints": len(ep_hints) + sum(len(x["hints"]) for x in shots),
                            "hint_repair": se.get("repair") if any(i["level"] == "block" for i in ep_hints) else ""}
    eps = [old[k] for k in sorted(old) if str(k) in s["episodes"] or k in s["episodes"]]
    blocking = sum(e["blocking"] for e in eps)
    v = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "episodes": eps,
         "blocking": blocking, "warnings": sum(e["warnings"] for e in eps),
         "hints": sum(e.get("hints", 0) for e in eps), "can_send": blocking == 0,
         "gate": GATE_VALIDATOR.relative_to(REPO).as_posix(), "hints_from": VALIDATOR.relative_to(REPO).as_posix(),
         "hints_available": strict is not None,
         "draft": p.relative_to(REPO).as_posix() if p.is_relative_to(REPO) else str(p)}
    s["validation"] = v
    return v


def validate_episode_text(body: str, tag: str = "x", registry: dict | None = None) -> dict | None:
    """单集格式校验（全局头 + 继承登记 + 这一集写到临时文件），返回该集报告；批量工具逐集自动返修用。
    registry：同 session_registry（批量按集号顺序写时 = 登记来源 + 本会话 ep < N）"""
    header, _ = script_header(registry=registry)
    p = STORE / "_tmp" / f"{tag}-{uuid.uuid4().hex[:6]}.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(header + "\n---\n\n" + body + "\n\n---\n", encoding="utf-8", newline="\n")
    try:
        r = subprocess.run([sys.executable, str(VALIDATOR), str(p), "--json"], capture_output=True, cwd=REPO,
                           timeout=900, env={**os.environ, "PYTHONIOENCODING": "utf-8"})
        rep = json.loads(r.stdout.decode("utf-8"))
        return rep["episodes"][0] if rep.get("episodes") else None
    except (ValueError, subprocess.SubprocessError):
        return None
    finally:
        p.unlink(missing_ok=True)


QUOTE_RE = re.compile(r"“([^”]+)”")


def spoken_lines(ep_text: str) -> list[str]:
    """一集里的台词（`**对白**` 行引号内）与独白（`**🎙…**` 行冒号后），按出现顺序"""
    out = []
    for ln in ep_text.splitlines():
        if ln.startswith("**对白"):
            out += QUOTE_RE.findall(ln)
        elif ln.startswith("**🎙"):
            out.append(re.split(r"\*\*[:：]", ln, 1)[-1].strip().strip("`*"))
    return [x for x in out if x]


SPEAKER_LINE_RE = re.compile(r"（([^）]*)）\s*“([^”]+)”")


def spoken_entries(ep_text: str) -> list[dict]:
    """一集的台词 / 独白清单（按出场顺序）：{shot, speaker, text, kind}；kind = 对白 / 独白"""
    out = []
    for k, body in split_shots(ep_text)[1].items():
        for ln in body.splitlines():
            if ln.startswith("**对白"):
                out += [{"shot": k, "speaker": sp.strip(), "text": t, "kind": "对白"}
                        for sp, t in SPEAKER_LINE_RE.findall(ln)]
            elif ln.startswith("**🎙"):
                t = re.split(r"\*\*[:：]", ln, 1)[-1].strip().strip("`*")
                if t:
                    out.append({"shot": k, "speaker": "林晚内心", "text": t, "kind": "独白"})
    return out


def episode_shot_cap(src_ep: str) -> int:
    """本集镜数上限 = max(8, 说话轮次 + 独白段数)（与 tools/validate_script_strict.py shot_cap 同一口径）"""
    turns, last, mono = 0, None, 0
    for e in spoken_entries(src_ep):
        if e["kind"] == "独白":
            mono += 1
        elif e["speaker"] != last:
            turns, last = turns + 1, e["speaker"]
    return max(8, turns + mono)


def dialogue_checklist(src_ep: str) -> str:
    """首次写作请求里附的“必须逐字出现的台词 / 独白清单”（总调度 2026-10-30：预防为一人一镜删台词）"""
    items = spoken_entries(src_ep)
    if not items:
        return ""
    lines = [f"{i}. 原稿镜{e['shot']}（{e['speaker']}，{e['kind']}）：{e['text']}" for i, e in enumerate(items, 1)]
    return ("【本集必须逐字出现的台词 / 独白清单（共 {n} 句，按出场顺序；每一句都要原文出现，一句都不能少）】\n"
            "合格做法：一镜只能一人说话，所以原稿一镜里两人对话时，拆成连续的一人一镜（镜号顺延；本集镜数最多 "
            f"{episode_shot_cap(src_ep)} 镜、总时长 ≤ 90 秒），每句都保留在说话人那一镜的 `**对白**` 和 H3 `<d>` 里；独白放 `**🎙**`。\n"
            .format(n=len(items)) + "\n".join(lines))


def splice_reply_ok(reply: str, a: int) -> bool:
    """定向返修的回复可用：至少一镜，且从约定的镜 a 开始（封板修复：之前从后面的镜开始也接受，会把镜 a 连同台词丢掉）"""
    got = split_shots(unwrap(reply))[1]
    return bool(got) and min(got) == a


def splice_shots(ep_text: str, a: int, b: int, reply: str) -> str:
    """用回复里的若干镜替换当前稿的镜 a..b（可以多出镜，用于拆镜），之后全部镜号从 1 顺延重编"""
    head, shots, tail = split_shots(ep_text)
    new = [v for _, v in sorted(split_shots(unwrap(reply))[1].items())]
    if not new:
        raise ValueError("回复里没有镜头")
    seq = [shots[k] for k in sorted(shots) if k < a] + new + [shots[k] for k in sorted(shots) if k > b]
    seq = [SHOT_HEAD_RE.sub(f"**镜{i}｜img", v, count=1) for i, v in enumerate(seq, 1)]
    return head + "\n".join(v.rstrip() + "\n" for v in seq) + ("\n" + tail if tail else "")


def missing_lines_repair(src_ep: str, new_ep: str) -> tuple[str, int, int] | None:
    """只针对缺的台词：找出缺句在当前稿里该落的镜范围（前后最近一句已保留台词所在镜），
    返回 (返修消息, a, b)；回复用 splice_shots 换回镜 a..b。没缺句返回 None"""
    have = "\n".join(spoken_lines(new_ep))
    src_items = spoken_entries(src_ep)
    lost = [i for i, e in enumerate(src_items) if e["text"] not in have]
    if not lost:
        return None
    cur = spoken_entries(new_ep)
    cur_shots = sorted(split_shots(new_ep)[1])

    def shot_of(text):
        return next((e["shot"] for e in cur if e["text"] == text), None)
    prev = [shot_of(src_items[j]["text"]) for j in range(lost[0] - 1, -1, -1)]
    nxt = [shot_of(src_items[j]["text"]) for j in range(lost[-1] + 1, len(src_items))]
    a = next((x for x in prev if x), cur_shots[0])
    b = next((x for x in nxt if x), cur_shots[-1])
    a, b = min(a, b), max(a, b)
    src_shots = split_shots(src_ep)[1]
    ctx_ids = sorted({src_items[i]["shot"] for i in lost})
    cur_map = split_shots(new_ep)[1]
    cur_part = "".join(cur_map[k] for k in cur_shots if a <= k <= b)
    # 封板修复：给这一段定预算（镜数 / 时长），并列出这一段必须出现的全部台词——之前只列缺句，
    # ep02 实测模型把镜 2–6 扩成 9 镜 84 秒、又丢了别的句子
    outside = [k for k in cur_shots if not a <= k <= b]

    def dur(k):
        m = re.search(r"\*\*时长\*\*：(\d+)", cur_map[k])
        return int(m.group(1)) if m else 10
    cap = episode_shot_cap(src_ep)   # 封板：镜数按集放宽为 max(8, 说话轮次 + 独白段数)，总时长 ≤ 90
    max_shots = max(1, cap - len(outside))
    max_secs = 90 - sum(dur(k) for k in outside)
    min_secs = max(5, 50 - sum(dur(k) for k in outside))
    first = next((j for j in range(lost[0], -1, -1) if shot_of(src_items[j]["text"]) == a), lost[0])
    last = next((j for j in range(lost[-1], len(src_items)) if shot_of(src_items[j]["text"]) == b), lost[-1])
    need = src_items[min(first, lost[0]): max(last, lost[-1]) + 1]
    said = [x["speaker"] for x in need if x["kind"] == "对白"]
    turns = sum(1 for i, sp in enumerate(said) if i == 0 or sp != said[i - 1])
    if turns > max_shots:   # 一镜一人时这一段放不下，局部修不可能合格 → 返回 None，调用方改走整集返修
        return None
    msg = (f"【缺台词返修】当前稿镜{a}–镜{b} 漏掉了原稿这些句子（逐字）：\n"
           + "\n".join(f"- 原稿镜{src_items[i]['shot']}（{src_items[i]['speaker']}，{src_items[i]['kind']}）："
                       f"{src_items[i]['text']}" for i in lost)
           + f"\n\n替换后的镜{a} 起这一段，必须按顺序逐字包含下面全部 {len(need)} 句（缺的 + 原本已有的）：\n"
           + "\n".join(f"{i}. （{e['speaker']}，{e['kind']}）{e['text']}" for i, e in enumerate(need, 1))
           + f"\n\n这一段的预算：最多 {max_shots} 镜，时长合计 {min_secs}–{max_secs} 秒（全集最多 {cap} 镜、50–90 秒；"
             f"这一段之外已有 {len(outside)} 镜）。每镜时长 5–15 秒的整数。"
           + "\n合格做法：一镜只能一人说话（同一人连续几句可以在同一镜）；把缺的句子放回说话人那一镜，"
             "需要时拆成连续的一人一镜。台词原文保持不变。\n\n【这些句子在原稿里的前后文】\n"
           + "".join(src_shots[k] for k in ctx_ids if k in src_shots)
           + f"\n【当前稿 镜{a}–镜{b}】\n{cur_part}\n"
           + f"只输出替换镜{a}–镜{b} 的那几镜，从 `**镜{a}｜img**` 开始，镜号从 {a} 连续往后编，"
             "每镜都到 `**H3提示词**` 代码块结束；其它镜不要输出。")
    return msg, a, b


def source_check(rep: dict | None, src_ep: str, new_ep: str) -> dict | None:
    """和原稿比：原稿每句台词 / 独白都要逐字出现在新稿里（项目方：剧情、对白与独白原文保持不变）。
    缺了就往校验报告加一条集级 block（SRC-D1），返修消息原样列出缺的句子。只比文字有无，不判断内容。"""
    if rep is None:
        return rep
    have = "\n".join(spoken_lines(new_ep))
    lost = [x for x in spoken_lines(src_ep) if x not in have]
    if lost:
        detail = "原稿这些台词 / 独白在新稿里找不到（要逐字保留）：" + "｜".join(lost)
        rep["issues"] = rep["issues"] + [{"rule_id": "SRC-D1", "level": "block", "field": "对白", "detail": detail}]
        rep["repair"] = ((rep.get("repair") or "") + f"\n- [SRC-D1|block] {detail}。合格写法：每句都放回 `**对白**`"
                         "（或 🎙），一镜只能一人说话时，把台词挪到相邻镜或拆成一人一镜，原文逐字不变。").strip()
    return rep


# 这些规则的返修要整集重写（拆镜 / 把台词挪到相邻镜会改镜号），不走单镜返修
EPISODE_RULES = {"H3-D7"}

# 返修时附在校验器原文后的“怎样才算合格”（只讲格式上的合格写法，不给内容）
REPAIR_HINTS = {
    "H3-D7": ("合格写法：每镜 H3 里只有一个说话人 (S1)。亲密镜（有【亲密声】）只有林晚说话和发声；原稿亲密镜里有男方台词时，"
              "二选一都合格、由你判断：①保留亲密镜，把男方台词移到相邻的非亲密镜；②这一镜改成普通对话镜（去掉【亲密声】整段）。"
              "普通对话镜里有两人说话时，由你决定拆成一人一镜（镜号顺延；镜数可放宽到 max(8, 说话轮次 + 独白段数)、总时长 ≤ 90 秒）或把台词移到相邻镜。"
              "台词原文逐字不变。"),
}


def repair_hints(issues: list[dict]) -> str:
    ids = dict.fromkeys(i["rule_id"] for i in issues if i["level"] == "block")
    return "\n".join(f"- [{r}] {REPAIR_HINTS[r]}" for r in ids if r in REPAIR_HINTS)


def shot_repair_text(sh: dict) -> str:
    hint = repair_hints(sh["issues"])
    return sh["repair"] + (f"\n{hint}" if hint else "")


def episode_repair_text(ep: dict) -> str:
    """单集校验报告 → 【格式返修】消息（校验器原文，只引用格式规则；附 REPAIR_HINTS 的合格写法）"""
    parts = [ep["repair"]] if ep.get("repair") else []
    parts += [shot_repair_text(sh) for sh in ep["shots"] if sh.get("repair")]
    if not parts:
        return ""
    return "\n\n".join(parts) + f"\n→ 请重新输出完整的 ep{ep['number']:02d}（整集，从 `## ep` 到 `---`）。"


def repair_message(s: dict) -> str:
    v = s.get("validation") or {}
    blocks = []
    for e in v.get("episodes", []):
        # fredw-92/D2：关口没有返修文字时，用严格校验的 block 级提示的返修原文（hint_repair）
        parts = [x for x in [e.get("repair") or e.get("hint_repair")] if x]
        parts += [sh.get("repair") or sh.get("hint_repair") for sh in e["shots"]
                  if sh.get("repair") or sh.get("hint_repair")]
        if parts:
            blocks.append("\n\n".join(parts) + f"\n→ 请重新输出完整的 ep{e['number']:02d}（整集，从 `## ep` 到 `---`）。")
    return "\n\n".join(blocks)


def api_messages(s: dict, upto: int | None = None, cfg: dict | None = None) -> list[dict]:
    """系统提示词（附录按最近的用户消息 + 被点名的草稿集挑选）+ 对话；超出上下文预算时 fit_messages 丢最早的历史"""
    msgs = s["messages"][:upto] if upto is not None else s["messages"]
    last = next((m["content"] for m in reversed(msgs) if m["role"] == "user"), "")
    named = [s["episodes"][k] for k in s["episodes"] if re.search(rf"ep0*{k}(?!\d)", last)]
    system, _ = prompt_for(last, context=last + "\n".join(named), cfg=cfg)
    if s.get("independent"):   # 批量会话：每集单独请求，不带历史
        msgs = msgs[-1:]
    return [{"role": "system", "content": system}] + [{"role": m["role"], "content": m["content"]}
                                                     for m in msgs if m["role"] in ("user", "assistant")]


def merge_shot_reply(s: dict, content: str) -> dict[int, str]:
    """fredw-92/D2：【格式返修】消息里每镜的校验器原文写着“只输出这一镜、其它镜头不要输出”，模型照做时回复里
    没有 `## ep`，旧逻辑什么都不并入、返修静默丢失。回复只有 `**镜N｜img` 块时：并入最近一条用户消息点名的那一集
    （只点名一集、且回复里的镜号都在该集草稿里才并，不新增镜）。返回 {集号: 新集全文}；不满足条件返回 {}。"""
    _, got, _ = split_shots(unwrap(content))
    if not got:
        return {}
    last = next((m["content"] for m in reversed(s["messages"]) if m["role"] == "user"), "")
    named = {int(m) for m in re.findall(r"ep0*(\d+)(?!\d)", last)} & {int(k) for k in s["episodes"]}
    if len(named) != 1:
        return {}
    n = named.pop()
    text = s["episodes"][str(n)]
    if not set(got) <= set(split_shots(text)[1]):
        return {}
    for k in sorted(got):
        text = merge_shot(text, k, got[k])
    s["episodes"][str(n)] = text
    return {n: text}


def record_reply(s: dict, content: str, reasoning: str, usage, finish, started: float, partial=False,
                 cfg: dict | None = None) -> list[int]:
    eps = split_episodes(content)
    for n, body in eps.items():
        s["episodes"][str(n)] = body
    if not eps and not partial:
        eps = merge_shot_reply(s, content)
    pv = provider(cfg)
    s["messages"].append({"role": "assistant", "content": content, "reasoning": reasoning, "usage": usage,
                          "finish": finish, "partial": partial, "episodes": sorted(eps),
                          "provider": pv["name"], "model": pv["model"], "seconds": round(time.time() - started, 1),
                          "at": time.strftime("%Y-%m-%dT%H:%M:%S")})
    return sorted(eps)


# ------------------------------------------------------------------ 接口

@router.get("/config")
def get_config():
    cfg = load_config()
    try:
        pv = provider(cfg)
    except ChatError as e:
        raise HTTPException(400, str(e)) from e
    _, parts = build_system_prompt(cfg)
    return {"provider": pv["name"], "provider_label": pv["label"], "model": pv["model"], "base_url": pv["base_url"],
            "has_key": bool(pv["api_key"]), "temperature": pv["params"].get("temperature"),
            "max_tokens": pv["max_tokens"], "ctx": pv.get("ctx"), "parts": parts,
            "rules_versions": list((cfg.get("rules_versions") or {})), "default_rules": cfg.get("default_rules")}


@router.get("/rules")
def get_rules():
    cfg = load_config()
    return {"default": cfg.get("default_rules"),
            "versions": [{"id": k, "parts": v} for k, v in (cfg.get("rules_versions") or {}).items()]}


@router.get("/system")
def get_system():
    text, parts = build_system_prompt()
    return {"text": text, "parts": parts}


@router.get("/sessions")
def list_sessions():
    out = []
    if STORE.exists():
        for d in STORE.iterdir():
            p = d / "session.json"
            if p.exists():
                try:   # 封板修复：一个坏 session.json 不能让整个列表 500，跳过
                    s = json.loads(p.read_text(encoding="utf-8"))
                    v = s.get("validation") or {}
                    out.append({"id": s["id"], "title": s["title"], "created_at": s["created_at"],
                                "messages": len(s["messages"]), "episodes": sorted(int(k) for k in s["episodes"]),
                                "blocking": v.get("blocking") if isinstance(v, dict) else None,
                                "llm": s.get("llm"), "ab": s.get("ab"), "inbox": s.get("inbox"),
                                "episode_range": s.get("episode_range"), "pending": bool(s.get("pending")),
                                "updated_at": time.strftime(
                                    "%Y-%m-%dT%H:%M:%S", time.localtime(p.stat().st_mtime))})
                except (OSError, ValueError, TypeError, KeyError, AttributeError):
                    continue
    return sorted(out, key=lambda x: x["updated_at"], reverse=True)


class LLMOverride(BaseModel):
    provider: str | None = None
    model: str | None = None
    params: dict | None = None


class NewBody(BaseModel):
    title: str | None = None
    outline: str | None = None
    episodes: list[int] | None = None
    shots_per_ep: int | None = None
    seconds_per_shot: float | None = None
    rules: str | None = None
    llm: LLMOverride | None = None
    registry_from: list[str] | None = None   # 继承登记来源：会话 id / 剧本 md 路径（按顺序，先登记为准）


def _llm(o: LLMOverride | None) -> dict | None:
    d = o.model_dump(exclude_none=True) if o else None
    return d or None


@router.post("/sessions")
def post_session(body: NewBody):
    return new_session(body.title, outline=body.outline, episodes=body.episodes, shots_per_ep=body.shots_per_ep,
                       seconds_per_shot=body.seconds_per_shot, rules=body.rules, llm=_llm(body.llm),
                       registry_from=body.registry_from)


class ABBody(BaseModel):
    outline: str
    episodes: list[int] | None = None
    llm_a: LLMOverride
    llm_b: LLMOverride
    shots_per_ep: int | None = None
    seconds_per_shot: float | None = None
    rules: str | None = None
    title: str | None = None
    registry_from: list[str] | None = None


@router.post("/ab")
def post_ab(body: ABBody):
    """同一份提纲交两个模型：建两个会话（各自带 llm 覆盖），前端分别 /chat；
    两份草稿都是导入候选，直接在 A/B 剧本对比页选"""
    if not body.outline.strip():
        raise HTTPException(400, "提纲为空")
    tag = uuid.uuid4().hex[:6]
    out = {}
    for side, o in (("a", body.llm_a), ("b", body.llm_b)):
        llm = _llm(o)
        if not llm or not llm.get("provider"):
            raise HTTPException(400, f"llm_{side} 要写明 provider")
        label = f"{llm['provider']}/{llm.get('model') or '默认'}"
        title = f"{(body.title or body.outline.strip().splitlines()[0])[:24]}·{side.upper()}·{label}"
        out[side] = new_session(title, outline=body.outline, episodes=body.episodes, shots_per_ep=body.shots_per_ep,
                                seconds_per_shot=body.seconds_per_shot, rules=body.rules, llm=llm,
                                ab={"group": tag, "side": side}, registry_from=body.registry_from)["id"]
    return {"a": out["a"], "b": out["b"], "group": tag}


@router.get("/sessions/{sid}")
def get_session(sid: str):
    return load_session(sid)


class ChatBody(BaseModel):
    content: str = ""
    llm: LLMOverride | None = None


@router.post("/sessions/{sid}/chat")
def post_chat(sid: str, body: ChatBody):
    s0 = load_session(sid)
    text = body.content if body.content.strip() else (s0.get("pending") or "")
    if not text.strip():
        raise HTTPException(400, "内容为空")
    lk = _lock(sid)
    if not lk.acquire(blocking=False):
        raise HTTPException(409, "这个会话正在生成，请等它结束")
    try:
        cfg = session_cfg(s0, _llm(body.llm))
        pv0 = provider(cfg)

        def add_user(cur):
            if not cur["messages"] and cur["title"] == "新剧本":
                cur["title"] = text.strip().splitlines()[0][:30]
            if text == cur.get("pending"):
                cur.pop("pending", None)
            cur["messages"].append({"role": "user", "content": text, "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                                    "llm": {"provider": pv0["name"], "model": pv0["model"]}})
        s = update_session(sid, add_user)   # 封板修复：加跨进程锁，批量可能同时在写这个会话
        msgs = api_messages(s, cfg=cfg)
    except ChatError as e:
        lk.release()
        raise HTTPException(400, str(e)) from e
    except Exception:
        lk.release()
        raise

    def ev(obj) -> str:
        return "data: " + json.dumps(obj, ensure_ascii=False) + "\n\n"

    def gen():
        started = time.time()
        content, reasoning, usage, finish = "", "", None, None
        done = False
        try:
            yield ev({"t": "start", "provider": pv0["name"], "model": pv0["model"]})
            if pv0.get("reasoning_note"):
                yield ev({"t": "warn", "d": pv0["reasoning_note"]})
            yield ev({"t": "progress", "d": "已发送，等待写作模型响应（思考阶段可能需要 1–3 分钟）"})
            for kind, val in stream_completion(msgs, cfg):
                if kind == "content":
                    content += val
                    yield ev({"t": "content", "d": val})
                elif kind == "reasoning":
                    reasoning += val
                    yield ev({"t": "reasoning", "d": val})
                elif kind == "usage":
                    usage = val
                elif kind == "finish":
                    finish = val
            if finish is None:
                raise ChatError("流式输出中断（没有收到结束标记）；已收到的部分已存档，可以发“继续”或重新发送")
            got = {}
            # 封板修复：流式要几分钟，结束时加锁重新读入再追加，不用开始时那份旧会话整份覆盖
            s2 = update_session(sid, lambda cur: got.setdefault(
                "eps", record_reply(cur, content, reasoning, usage, finish, started, cfg=cfg)))
            eps = got["eps"]
            if finish == "length":
                yield ev({"t": "warn", "d": "回复达到长度上限被截断（「模型与 API」页的最大输出 max_tokens）；可以发“继续”"})
            done = True
            yield ev({"t": "saved", "episodes": eps, "usage": usage, "finish": finish})
            if eps:
                yield ev({"t": "validating"})
                for n in eps:
                    validate_draft(s2, n)
                update_session(sid, lambda cur: cur.__setitem__("validation", s2.get("validation")))
            yield ev({"t": "done", "episodes": eps, "validation": s2.get("validation")})
        except Exception as e:  # noqa: BLE001  上游错误原样告诉前端
            yield ev({"t": "error", "d": str(e)})
        finally:
            try:
                if not done and (content or reasoning):   # 中途停止 / 出错：已收到的部分也存档
                    update_session(sid, lambda cur: record_reply(cur, content, reasoning, usage, finish or "stopped",
                                                                 started, partial=True, cfg=cfg))
            finally:
                lk.release()   # 封板修复：存档抛错（跨进程锁超时等）也必须放锁，否则会话一直 409

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/sessions/{sid}/repair")
def get_repair(sid: str):
    return {"text": repair_message(load_session(sid))}


class EstimateBody(BaseModel):
    sid: str | None = None
    content: str | None = None
    outline: str | None = None
    episodes: list[int] | None = None
    shots_per_ep: int | None = None
    seconds_per_shot: float | None = None
    rules: str | None = None
    llm: LLMOverride | None = None


@router.post("/estimate")
def post_estimate(body: EstimateBody):
    """预计费用档（模型设置块用）：按这次要发的系统提示词 + 消息估计提示 token，加该模型 max_tokens 算上限；
    单价读服务商 /models（abliteration 有），拿不到 = 未知。不发写作请求、不花钱。
    返回 {provider, model, prompt_tokens, max_tokens, upper_usd, tier, label, pricing, reasoning, reasoning_note}"""
    s = load_session(body.sid) if body.sid else {"messages": [], "episodes": {}, "rules": body.rules}
    if body.rules:
        s = {**s, "rules": body.rules}
    cfg = session_cfg(s, _llm(body.llm))
    try:
        pv = provider(cfg)
    except ChatError as e:
        raise HTTPException(400, str(e)) from e
    text = (body.content or "").strip() or (
        outline_message(body.outline, body.episodes, body.shots_per_ep, body.seconds_per_shot)
        if (body.outline or "").strip() else (s.get("pending") or ""))
    msgs = api_messages({**s, "messages": s["messages"] + [{"role": "user", "content": text}]}, cfg=cfg)
    n = sum(count_tokens(m["content"], cfg) + 8 for m in msgs)
    est = LC.estimate_cost(pv["name"], pv["model"], n, int(pv["max_tokens"]))
    return {"provider": pv["name"], "model": pv["model"], **est,
            "reasoning": pv.get("reasoning_ok"), "reasoning_note": pv.get("reasoning_note")}


@router.post("/sessions/{sid}/to-inbox")
def post_to_inbox(sid: str):
    """把会话草稿 data/script_chat/<sid>/script.md 登记为剧本导入候选（只写出草稿 + 格式校验摘要；
    不自动导入，项目方在导入页确认）"""
    from . import script_inbox as SI
    s = load_session(sid)
    if not s["episodes"]:
        raise HTTPException(400, "草稿里还没有整集（模型回复里没有 `## ep<N>《…》`），没有可送导入的内容")
    p = write_draft(s)
    if p.resolve() not in [c.resolve() for c in SI.candidates()]:
        raise HTTPException(500, f"草稿 {p} 不在导入候选目录里（data/script_chat/*/script.md）")
    summary = SI.validate(p)
    rel = SI._rel(p)
    info = {"path": rel, "sha256": summary.get("sha256"), "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "episodes": sorted(int(k) for k in s["episodes"]), "blocking": summary.get("blocking")}
    update_session(sid, lambda cur: cur.__setitem__("inbox", info))
    return {**info, "candidate": True, "validation": summary}


@router.post("/sessions/{sid}/validate")
def post_validate(sid: str):
    s = load_session(sid)
    v = validate_draft(s)
    update_session(sid, lambda cur: cur.__setitem__("validation", s.get("validation")))
    return v
