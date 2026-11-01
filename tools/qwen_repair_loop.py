"""
Qwen 格式返修循环（docs/qwen_writing_contract.md；docs/REQUIREMENTS.md G1–G3）。

内容一律由 Qwen 写；本工具只做“系统”的事：校验 → 把返修请求发给 Qwen → 把 Qwen 的回复原样拼回剧本 → 再校验。
唯一的机械修正：H3 对齐句按 **时长** 重算（ns_schema.h3_lint.alignment_line / frames_for_seconds），逐条记入 state。

    .venv\\Scripts\\python.exe tools\\qwen_repair_loop.py "data/staging_v3/为他而骚 （剧本和镜头）v3.md"
        [--out PATH] [--episodes 1,3-5] [--max-rounds 3] [--dry-run] [--resume] [--fix-warn] [--think]
        [--base-url http://127.0.0.1:PORT]   # 不给则自动开 ssh 隧道 gpu33 → 127.0.0.1:8098

每个失败镜头一次请求一个镜头：system = config/qwen_writer_system_prompt.txt；user = 本集集头（上下文）+ 该镜当前完整
Markdown + validate_qwen_script 的返修请求。回复只接受：恰好一个同镜号的镜头块、对白/🎙 原文逐字保留、时长不变
（除非本镜本来就有 S1-W2）。否则拒收重试；最多 --max-rounds 轮，仍不行保留原文并记录。

进度：<out 目录>/repair/state.json（每个单元：轮数、前后问题、拒收原因、机械修正、耗时），Qwen 原始回复
repair/replies/<单元>_r<轮>.txt，请求 repair/requests/<单元>_r<轮>.txt。每个单元处理完即写出输出文件，可 --resume。
原始输入文件只读。
"""
from __future__ import annotations

import argparse
import atexit
import collections
import importlib.util
import json
import os
import re
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT / "packages" / "schema", ROOT / "services" / "agent"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from ns_agent.importer.script_md import EP_RE, SHOT_RE, import_script  # noqa: E402
from ns_schema import h3_lint as L  # noqa: E402

_spec = importlib.util.spec_from_file_location("validate_qwen_script", ROOT / "tools" / "validate_qwen_script.py")
V = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(V)
if hasattr(V, "WL"):
    V.WL.WRITER_LINT_LEVEL = "block"   # ITERAUDIT 11-01：返修环里 QW-W1–W4 当阻断，写作方自己改

DEFAULT_IN = ROOT / "data" / "staging_v3" / "为他而骚 （剧本和镜头）v3.md"
SYSTEM_PROMPT = ROOT / "config" / "qwen_writer_system_prompt.txt"
REMOTE_PORT = 8098
LOCAL_PORT = 18098
HEAD_RULES = {"QW-E1", "R-C1"}          # 能靠改集头修的集级规则
ALIGN_PREFIX = "How the reference pictures align"


def log(msg: str):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


# ------------------------------------------------------------------ 切分 / 拼接（纯文本，逐行）

def _norm(line: str) -> str:
    return line.rstrip().replace(r"\*", "*").replace(r"\`", "`")


def split_doc(text: str) -> tuple[str, list[str]]:
    """→ (前言, [每集原文])；前言 + ''.join(各集) == 原文"""
    lines = text.splitlines(keepends=True)
    starts = [i for i, ln in enumerate(lines) if EP_RE.match(_norm(ln))]
    if not starts:
        return text, []
    pre = "".join(lines[:starts[0]])
    chunks = ["".join(lines[a:b]) for a, b in zip(starts, starts[1:] + [len(lines)])]
    return pre, chunks


def _is_boundary(line: str) -> bool:
    n = _norm(line)
    return bool(SHOT_RE.match(n) or EP_RE.match(n) or n.strip() == "---" or n.startswith("# ") or n.startswith("## "))


def _trim_end(lines: list[str], a: int, b: int) -> int:
    while b > a and not lines[b - 1].strip():
        b -= 1
    return b


def segment(chunk: str) -> dict:
    """一集原文 → {'lines', 'head': (a,b), 'shots': [(镜号, a, b, b_raw)]}；b 不含末尾空行"""
    lines = chunk.splitlines(keepends=True)
    shot_starts = [i for i, ln in enumerate(lines) if SHOT_RE.match(_norm(ln))]
    head_end = shot_starts[0] if shot_starts else next(
        (i for i, ln in enumerate(lines) if i and _norm(ln).strip() == "---"), len(lines))
    shots = []
    for i in shot_starts:
        j = i + 1
        while j < len(lines) and not _is_boundary(lines[j]):
            j += 1
        shots.append((int(SHOT_RE.match(_norm(lines[i])).group(1)), i, _trim_end(lines, i, j), j))
    return {"lines": lines, "head": (0, _trim_end(lines, 0, head_end)), "shots": shots}


def block_text(chunk: str, which) -> str:
    seg = segment(chunk)
    a, b = seg["head"] if which == "head" else seg["shots"][which][1:3]
    return "".join(seg["lines"][a:b]).rstrip("\n")


def splice(chunk: str, which, new_block: str) -> str:
    """把第 which 个镜头块（或 'head'）整体换成 new_block，其它行逐字不动"""
    seg = segment(chunk)
    a, b = seg["head"] if which == "head" else seg["shots"][which][1:3]
    lines = seg["lines"]
    new_lines = [ln + "\n" for ln in new_block.rstrip("\n").split("\n")]
    if b == len(lines) and lines and not lines[-1].endswith("\n"):
        new_lines[-1] = new_lines[-1].rstrip("\n")
    return "".join(lines[:a] + new_lines + lines[b:])


# ------------------------------------------------------------------ Qwen 回复解析

def strip_think(raw: str) -> str:
    s = re.sub(r"<think>.*?</think>", "", raw or "", flags=re.S)
    if "</think>" in s:
        s = s.rsplit("</think>", 1)[1]
    return s.replace("<think>", "").strip()


def _close_fences(lines: list[str]) -> tuple[list[str], str]:
    while lines and not lines[-1].strip():
        lines.pop()
    fences = lambda: sum(1 for ln in lines if ln.strip().startswith("```"))  # noqa: E731
    if fences() % 2:
        # Qwen 把整段包在 ```markdown 里时多出的收尾围栏：从最后一个裸 ``` 起（含其后的说明文字）截掉
        last = max(i for i, ln in enumerate(lines) if ln.strip().startswith("```"))
        if lines[last].strip() == "```":
            del lines[last:]
            while lines and not lines[-1].strip():
                lines.pop()
    return lines, ("" if fences() % 2 == 0 else "代码块围栏 ``` 没有成对闭合")


def parse_shot_reply(raw: str, index: int) -> tuple[str | None, str]:
    """→ (镜头块, 错误)。只接受恰好一个镜头块且镜号不变"""
    lines = strip_think(raw).split("\n")
    starts = [i for i, ln in enumerate(lines) if SHOT_RE.match(_norm(ln))]
    if not starts:
        return None, "回复里没有 `**镜N｜img**` 开头的镜头块"
    if len(starts) > 1:
        return None, f"回复里有 {len(starts)} 个镜头块，只能输出被要求的这一个镜头"
    got = int(SHOT_RE.match(_norm(lines[starts[0]])).group(1))
    if got != index:
        return None, f"镜号被改成了 {got}（应为 {index}）"
    out, i = [], starts[0]
    in_code = False
    while i < len(lines):
        ln = lines[i]
        if ln.strip().startswith("```"):
            in_code = not in_code
        elif not in_code and i > starts[0] and _is_boundary(ln):
            break
        out.append(ln.rstrip())
        i += 1
    out, err = _close_fences(out)
    return ("\n".join(out), "") if not err else (None, err)


def parse_head_reply(raw: str, ep_no: int, title: str) -> tuple[str | None, str]:
    lines = strip_think(raw).split("\n")
    starts = [i for i, ln in enumerate(lines) if EP_RE.match(_norm(ln))]
    if len(starts) != 1:
        return None, "回复里应恰好有一行 `## ep<N>《<标题>》`"
    m = EP_RE.match(_norm(lines[starts[0]]))
    if int(m.group(1)) != ep_no or m.group(2) != title:
        return None, f"集号/集标题被改动（应为 ep{ep_no:02d}《{title}》）"
    out = []
    for ln in lines[starts[0]:]:
        if out and (_is_boundary(ln) or ln.strip().startswith("```")):
            break
        out.append(ln.rstrip())
    while out and not out[-1].strip():
        out.pop()
    return "\n".join(out), ""


# ------------------------------------------------------------------ 校验（只校验一集：前言 + 该集）

class Checker:
    def __init__(self, preamble: str, work_dir: Path, names: list[str]):
        self.pre = preamble
        self.pre_lines = len(preamble.splitlines())
        self.work = work_dir / "_work.md"
        self.names = names

    def run(self, chunk: str, ep_no: int) -> dict:
        self.work.write_text(self.pre + chunk, encoding="utf-8")
        rep = V.validate(self.work, ep_no, self.names)
        imp = import_script(self.work)
        ep_rep = rep["episodes"][0] if rep["episodes"] else {"issues": [], "shots": []}
        ep_obj = next((e for e in imp.episodes if e.number == ep_no), None)
        seg = segment(chunk)
        # QW-F0（无法归属的散行）落在哪个镜头块里，就算那个镜头的问题
        shot_issues = [list(s["issues"]) for s in ep_rep["shots"]]
        head_issues = []
        for i in ep_rep["issues"]:
            m = re.match(r"第 (\d+) 行", i["detail"]) if i["rule_id"] == "QW-F0" else None
            k = None
            if m:
                ln = int(m.group(1)) - 1 - self.pre_lines
                k = next((n for n, (_, a, _b, b_raw) in enumerate(seg["shots"]) if a <= ln < b_raw), None)
            if k is not None and k < len(shot_issues):
                shot_issues[k].append(i)
            else:
                head_issues.append(i)
        # --force-shot（PRODUCER 11-01）：校验没标出、但契约方判定的同类格式冲突，按单镜发返修请求；该镜原文改过即视为已处理
        for k, (idx, a, b, _raw) in enumerate(seg["shots"]):
            key = (ep_no, idx)
            if key in FORCE and k < len(shot_issues):
                blk = "".join(seg["lines"][a:b])
                ORIG.setdefault(key, blk)
                if blk == ORIG[key]:
                    code, detail = FORCE[key]
                    shot_issues[k].append({"rule_id": code, "level": "warn", "detail": detail, "field": "img"})
        return {"ep": ep_rep, "obj": ep_obj, "shot_issues": shot_issues, "head_issues": head_issues,
                "seg": seg}


def score(issues: list[dict]) -> tuple[int, int]:
    return (sum(i["level"] == "block" for i in issues), sum(i["level"] != "block" for i in issues))


FORCE: dict = {}           # (集, 镜) → (规则号, 说明)：--force-shot ep03-S1=QW-SZ1:说明
ORIG: dict = {}
ONLY_CODES: set = set()     # --only-codes（PRODUCER 11-01）：只返修这些规则号，别的问题不发给写作方、不算“要返修”


def only(issues: list[dict]) -> list[dict]:
    return [i for i in issues if i.get("rule_id") in ONLY_CODES] if ONLY_CODES else issues


def failing(issues: list[dict], fix_warn: bool) -> bool:
    b, w = score(only(issues))
    return bool(b or (fix_warn and w))


def head_fixable(issues: list[dict]) -> list[dict]:
    return only([i for i in issues if i["level"] == "block" and i["rule_id"] in HEAD_RULES and "写在了镜" not in i["detail"]])


# ------------------------------------------------------------------ 不变量：镜号 / 对白逐字 / 🎙 / 时长

def dialogue_check(old_shot, new_shot, allow_duration: bool) -> str:
    old = [d.text.strip() for d in old_shot.dialogue]
    new = [d.text.strip() for d in new_shot.dialogue]
    if old and all(d.speaker_note for d in old_shot.dialogue):
        if old != new:
            return f"对白原文被改动或增删：原 {old} → 新 {new}；对白必须逐字、逐条、同顺序保留"
    else:   # 原稿本身格式不规范（S1-W4）：每条原文仍须按原顺序原样出现在 **对白** 里
        raw, pos = (new_shot.dialogue_raw or ""), 0
        for t in old:
            k = raw.find(t, pos)
            if k < 0:
                return f"对白原文 {t!r} 没有逐字保留在 **对白** 里"
            pos = k + len(t)
        if len(new) < len(old):
            return f"对白条数从 {len(old)} 变成 {len(new)}"
        if not old and new:
            return f"原镜头没有对白，回复新增了对白 {new}；不要增加台词"
    ov = (old_shot.voiceover.text.strip() if old_shot.voiceover else "")
    nv = (new_shot.voiceover.text.strip() if new_shot.voiceover else "")
    if ov != nv:
        return "🎙 内心独白原文被改动或删除；必须逐字保留"
    if not allow_duration and old_shot.duration != new_shot.duration:
        return f"**时长** 被从 {old_shot.duration} 秒改成 {new_shot.duration} 秒；本镜时长不需要改"
    return ""


def mech_align(block: str, seconds: int) -> tuple[str, str]:
    """机械修正：H3 第一行对齐句按时长重算。→ (新块, 记录；空 = 未改)"""
    lines = block.split("\n")
    try:
        i = next(i for i, ln in enumerate(lines) if ln.strip().startswith(ALIGN_PREFIX))
    except StopIteration:
        return block, ""
    want = L.alignment_line(L.frames_for_seconds(seconds or 10))
    if lines[i].strip() == want:
        return block, ""
    old = lines[i].strip()
    lines[i] = want
    return "\n".join(lines), f"H3 对齐句按时长 {seconds} 秒重算：{old[-60:]!r} → {want[-60:]!r}"


# ------------------------------------------------------------------ Qwen 连接

def _free_port(prefer: int) -> int:
    for port in (prefer, 0):
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", port))
                return s.getsockname()[1]
            except OSError:
                continue
    raise RuntimeError("没有空闲端口")


class Qwen:
    def __init__(self, base_url: str | None, think: bool, temperature: float, timeout: int):
        self.base_url, self.think, self.temperature, self.timeout = base_url, think, temperature, timeout
        self.tunnel: subprocess.Popen | None = None
        if not base_url:
            self.open_tunnel()
        atexit.register(self.close)

    def open_tunnel(self, tries: int = 12):
        """断网时（gpu3 中继偶尔 reset）按 10 s、20 s … 60 s 退避重试，约 10 分钟内恢复就接着跑"""
        for k in range(tries):
            try:
                return self._open_tunnel_once()
            except RuntimeError as e:
                if k == tries - 1:
                    raise
                wait = min(60, 10 * (k + 1))
                log(f"{e}；{wait} s 后重试隧道（{k + 1}/{tries}）")
                time.sleep(wait)

    def _open_tunnel_once(self):
        self.close()
        port = _free_port(LOCAL_PORT)
        self.tunnel = subprocess.Popen(
            ["ssh", "-N", "-o", "BatchMode=yes", "-o", "ExitOnForwardFailure=yes", "-o", "ServerAliveInterval=30",
             "-L", f"{port}:127.0.0.1:{REMOTE_PORT}", "gpu33"],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.base_url = f"http://127.0.0.1:{port}"
        for _ in range(40):
            try:
                with urllib.request.urlopen(f"{self.base_url}/health", timeout=3) as r:
                    if r.status == 200:
                        log(f"ssh 隧道已建立：{self.base_url} → gpu3 :{REMOTE_PORT}")
                        return
            except OSError:
                pass
            if self.tunnel.poll() is not None:
                raise RuntimeError("ssh 隧道没建起来（ssh gpu33 能否 BatchMode 登录？）")
            time.sleep(1)
        raise RuntimeError(f"gpu3 :{REMOTE_PORT} 没有响应 /health")

    def close(self):
        if self.tunnel and self.tunnel.poll() is None:
            self.tunnel.terminate()
            try:
                self.tunnel.wait(5)
            except subprocess.TimeoutExpired:
                self.tunnel.kill()
        self.tunnel = None

    def __call__(self, system: str, user: str) -> str:
        body = {"messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                "temperature": self.temperature, "stream": False,
                "max_tokens": 16000 if self.think else 8000,
                "chat_template_kwargs": {"enable_thinking": self.think}}
        last = None
        # Qwen 服务迁卡 / 重载模型时会有几分钟不可用：最多 8 次，间隔 5 s → 60 s
        tries = 8
        for attempt in range(tries):
            try:
                req = urllib.request.Request(f"{self.base_url}/v1/chat/completions",
                                             json.dumps(body).encode(), {"Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    data = json.loads(r.read().decode("utf-8"))
                msg = data["choices"][0]["message"]
                content = msg.get("content") or ""
                if msg.get("reasoning_content"):
                    content = f"<think>{msg['reasoning_content']}</think>\n{content}"
                return content
            except (urllib.error.URLError, OSError, TimeoutError, KeyError, json.JSONDecodeError) as e:
                last = e
                log(f"Qwen 请求失败（第 {attempt + 1} 次）：{e!r}")
                if self.tunnel is not None and (self.tunnel.poll() is not None or isinstance(e, urllib.error.URLError)):
                    self.open_tunnel()
                time.sleep(min(60, 5 * (attempt + 1) ** 2))
        raise RuntimeError(f"Qwen 连续 {tries} 次请求失败：{last!r}")


ABLITERATION_CFG = ROOT / "config" / "abliteration.local.json"


def _llm_config():
    """ns_api/llm_config.py（统一模型配置 config/llm_providers.json）"""
    p = ROOT / "services" / "api"
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
    from ns_api import llm_config
    return llm_config


class Abliteration(Qwen):
    """外部写作模型（OpenAI 兼容，非流式；思考内容在 message.reasoning）。2026-10-30 夜 fredw-92/W1：默认后端，
    服务商 / 模型 / 密钥读统一配置 config/llm_providers.json 的用途 script_repair（默认 abliteration large-flash，
    千问撤下）；llm = {provider?, model?} 覆盖。cfg_path 给定时读旧格式文件 {base_url, model, api_key}（兼容）。"""

    def __init__(self, think: bool, temperature: float, timeout: int, cfg_path: Path | None = None,
                 llm: dict | None = None):
        if cfg_path is not None:
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
            self.model, self.key, base = cfg["model"], cfg.get("api_key"), cfg["base_url"]
        else:
            rv = _llm_config().resolve("script_repair", llm)
            self.model, self.key, base = rv["model"], rv["api_key"], rv["base_url"]
            if not self.key and rv.get("key_env"):
                raise RuntimeError(f"缺少 {rv['name']} 的 API key（「模型与 API」页或环境变量 {rv['key_env']}）")
        self.base_url, self.think, self.temperature, self.timeout = base.rstrip("/"), think, temperature, timeout
        self.tunnel = None

    def open_tunnel(self, tries: int = 12):     # 外部服务，不需要隧道
        return None

    def __call__(self, system: str, user: str) -> str:
        body = {"model": self.model, "temperature": self.temperature, "stream": False, "max_tokens": 8000,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
        last = None
        for attempt in range(6):
            try:
                hdr = {"Content-Type": "application/json"}
                if self.key:
                    hdr["Authorization"] = f"Bearer {self.key}"
                req = urllib.request.Request(f"{self.base_url}/chat/completions", json.dumps(body).encode(), hdr)
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    data = json.loads(r.read().decode("utf-8"))
                msg = data["choices"][0]["message"]
                content = msg.get("content") or ""
                think = msg.get("reasoning") or msg.get("reasoning_content")
                return f"<think>{think}</think>\n{content}" if think else content
            except (urllib.error.URLError, OSError, TimeoutError, KeyError, json.JSONDecodeError) as e:
                last = e
                log(f"{self.model} 请求失败（第 {attempt + 1} 次）：{e!r}")
                time.sleep(min(60, 5 * (attempt + 1) ** 2))
        raise RuntimeError(f"{self.model} 连续 6 次请求失败：{last!r}")


# ------------------------------------------------------------------ 请求文本

def shot_user_msg(ep_no: int, index: int, head: str, block: str, request: str, note: str) -> str:
    parts = [f"以下是 ep{ep_no:02d} 的集头（只作上下文，不要输出）：", head, "",
             f"以下是 ep{ep_no:02d} 镜{index} 当前的完整 Markdown：", block, "", request]
    if note:
        parts += ["", f"上一次的回复没有被采用：{note}"]
    parts += ["", "**对白** 与 🎙 的原文逐字保留（含标点），镜号不变。只输出修正后的这一个镜头的完整 Markdown，"
                  "不要解释，不要输出集头或其它镜头。"]
    return "\n".join(parts)


def head_user_msg(ep_no: int, head: str, request: str, note: str, shots_brief: str) -> str:
    parts = [f"以下是 ep{ep_no:02d} 当前的集头：", head, "", "本集镜头的 sound 行（只作上下文，不要输出）：", shots_brief,
             "", request]
    if note:
        parts += ["", f"上一次的回复没有被采用：{note}"]
    parts += ["", "集号、集标题、**剧情** 原文保持不变。只输出修正后的集头（`## ep…《…》`、`**剧情**`、`**配乐**`），"
                  "不要解释，不要输出镜头。"]
    return "\n".join(parts)


# ------------------------------------------------------------------ 主循环

class Repairer:
    def __init__(self, a, ask=None):
        self.a = a
        self.inp = Path(a.script)
        self.out = Path(a.out)
        self.rdir = Path(a.repair_dir) if a.repair_dir else self.out.parent / "repair"
        (self.rdir / "replies").mkdir(parents=True, exist_ok=True)
        (self.rdir / "requests").mkdir(parents=True, exist_ok=True)
        self.state_path = self.rdir / "state.json"
        self.system = SYSTEM_PROMPT.read_text(encoding="utf-8")
        # ITERAUDIT 11-01：返修也带系统知识包（config/recipes/writer_knowledge.md，compile.py 生成，含 QW-W* 对应写法），
        # 和 script_chat / run_chain P3-P4 的 system_parts 一致；返修消息里的规则号在这里能查到怎么写
        wk = ROOT / "config" / "recipes" / "writer_knowledge.md"
        if wk.exists():
            self.system += "\n\n========\n\n" + wk.read_text(encoding="utf-8")
        self.ask = ask
        self.names = [n.strip() for n in (a.names or "").split(",") if n.strip()]

        if a.resume and self.out.exists() and self.state_path.exists():
            text = self.out.read_text(encoding="utf-8")
            self.state = json.loads(self.state_path.read_text(encoding="utf-8"))
            log(f"续跑：从 {self.out.name} 和 state.json 继续（已完成集 {self.state.get('episodes_done', [])}）")
        else:
            if self.state_path.exists() and not a.dry_run:
                self.state_path.replace(self.state_path.with_suffix(".json.bak"))
            text = self.inp.read_text(encoding="utf-8")
            self.state = {"input": str(self.inp), "output": str(self.out), "started": time.strftime("%F %T"),
                          "units": {}, "episodes_done": [], "mechanical": []}
        self.pre, self.chunks = split_doc(text)
        self.checker = Checker(self.pre, self.rdir, self.names)

    # --- 持久化
    def save(self):
        if self.a.dry_run:
            return
        tmp = self.out.with_suffix(".md.tmp")
        tmp.write_text(self.pre + "".join(self.chunks), encoding="utf-8")
        os.replace(tmp, self.out)
        st = self.state_path.with_suffix(".json.tmp")
        st.write_text(json.dumps(self.state, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(st, self.state_path)

    def _qwen(self, uid: str, rnd: int, user: str) -> tuple[str, float]:
        (self.rdir / "requests" / f"{uid}_r{rnd}.txt").write_text(user, encoding="utf-8")
        if self.ask is None:
            backend = getattr(self.a, "backend", "llm")
            if backend == "local":   # 旧本地 Qwen（已撤下，仅兼容）
                self.ask = Qwen(self.a.base_url, self.a.think, self.a.temperature, self.a.timeout)
            else:
                llm = {k: v for k, v in {"provider": getattr(self.a, "provider", None)
                                         or ("abliteration" if backend == "abliteration" else None),
                                         "model": getattr(self.a, "model", None)}.items() if v}
                self.ask = Abliteration(self.a.think, self.a.temperature, self.a.timeout, llm=llm or None)
        t0 = time.time()
        raw = self.ask(self.system, user)
        dt = time.time() - t0
        (self.rdir / "replies" / f"{uid}_r{rnd}.txt").write_text(raw, encoding="utf-8")
        return raw, dt

    # --- 选集
    def selected(self, ep_no: int) -> bool:
        return not self.a.episode_set or ep_no in self.a.episode_set

    def run(self) -> dict:
        for ci, chunk in enumerate(self.chunks):
            ep_no = int(EP_RE.match(_norm(chunk.split("\n", 1)[0])).group(1))
            if not self.selected(ep_no) or ep_no in self.state["episodes_done"]:
                continue
            self.repair_episode(ci, ep_no)
            if not self.a.dry_run:
                self.state["episodes_done"].append(ep_no)
                self.save()
                log(f"ep{ep_no:02d} 完成，已写出 {self.out}")
                self.export(ep_no)
        return self.state

    def export(self, ep_no: int):
        """项目方：“qwen写完文章给我这里下载”——每完成一集复制到 为他而骚短剧/Qwen剧本/（单集 + 全本，原文逐字）"""
        if getattr(self.a, "no_export", False):
            return
        try:
            import importlib.util
            spec = importlib.util.spec_from_file_location("export_qwen_script", ROOT / "tools" / "export_qwen_script.py")
            ex = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(ex)
            for p in ex.export(Path(self.out), [ep_no], getattr(self.a, "rules_tag", "rules_v1")):
                log(f"  已复制到下载目录：{p}")
        except Exception as e:      # 导出失败不影响返修
            log(f"  导出到下载目录失败：{e!r}")

    def repair_episode(self, ci: int, ep_no: int):
        chk = self.checker.run(self.chunks[ci], ep_no)
        n_shots = len(chk["seg"]["shots"])
        todo = [k for k in range(n_shots) if k < len(chk["shot_issues"])
                and failing(chk["shot_issues"][k], self.a.fix_warn)]
        log(f"ep{ep_no:02d}：{n_shots} 镜，需返修 {len(todo)} 镜；集级问题 "
            f"{[i['rule_id'] for i in chk['head_issues']]}")
        if self.a.dry_run:
            for k in todo:
                idx = chk["seg"]["shots"][k][0]
                log(f"  [dry-run] ep{ep_no:02d}-S{idx}: {[i['rule_id'] for i in chk['shot_issues'][k]]}")
            return
        for k in todo:
            uid = chk["ep"]["shots"][k]["id"]
            if self.state["units"].get(uid, {}).get("status") in ("fixed", "improved", "unchanged"):
                continue
            self.repair_shot(ci, ep_no, k, uid)
            self.save()
        chk = self.checker.run(self.chunks[ci], ep_no)
        uid = f"ep{ep_no:02d}-head"
        other = [i for i in chk["head_issues"] if i not in head_fixable(chk["head_issues"]) and i["level"] == "block"]
        if other:
            self.state["units"].setdefault(f"ep{ep_no:02d}-episode", {}).update(
                status="not_auto_repaired", issues=other,
                note="集级问题（总时长/镜数/配乐位置/散行）需要整集返修，本工具不处理")
        if head_fixable(chk["head_issues"]) and self.state["units"].get(uid, {}).get("status") not in (
                "fixed", "improved", "unchanged"):
            self.repair_head(ci, ep_no, uid)
            self.save()

    # --- 单镜
    def repair_shot(self, ci: int, ep_no: int, k: int, uid: str):
        a = self.a
        chk = self.checker.run(self.chunks[ci], ep_no)
        idx = chk["seg"]["shots"][k][0]
        orig_obj = chk["obj"].shots[k]
        orig_block = block_text(self.chunks[ci], k)
        before = chk["shot_issues"][k]
        allow_dur = any(i["rule_id"] == "S1-W2" for i in before)
        head = block_text(self.chunks[ci], "head")
        unit = {"status": "", "rounds": 0, "before": [i["rule_id"] for i in before], "after": [], "rejects": [],
                "mechanical": [], "qwen_seconds": []}
        self.state["units"][uid] = unit
        cur_block, cur_issues = orig_block, before

        def evaluate(block: str):
            chunk = splice(self.chunks[ci], k, block)
            c = self.checker.run(chunk, ep_no)
            return chunk, c

        # 机械修正：对齐句
        if any(i["rule_id"] in ("H3-A1",) for i in cur_issues):
            fixed, note = mech_align(cur_block, orig_obj.duration)
            if note:
                chunk, c = evaluate(fixed)
                if score(c["shot_issues"][k]) < score(cur_issues):
                    self.chunks[ci], cur_block, cur_issues = chunk, fixed, c["shot_issues"][k]
                    unit["mechanical"].append(note)
                    self.state["mechanical"].append(f"{uid}: {note}")
                    log(f"  {uid} 机械修正：{note}")

        note = ""
        for rnd in range(1, a.max_rounds + 1):
            if not failing(cur_issues, a.fix_warn):
                break
            unit["rounds"] = rnd
            req = V.repair_request(ep_no, idx, only(cur_issues))
            raw, dt = self._qwen(uid, rnd, shot_user_msg(ep_no, idx, head, cur_block, req, note))
            unit["qwen_seconds"].append(round(dt, 1))
            cand, err = parse_shot_reply(raw, idx)
            if not err:
                chunk, c = evaluate(cand)
                new_obj = c["obj"].shots[k] if c["obj"] and k < len(c["obj"].shots) else None
                err = "拼回后解析不到这个镜头" if new_obj is None else dialogue_check(orig_obj, new_obj, allow_dur)
            if not err and any(i["rule_id"] == "H3-A1" for i in c["shot_issues"][k]):
                fixed, mnote = mech_align(cand, new_obj.duration)
                if mnote:
                    chunk2, c2 = evaluate(fixed)
                    if score(c2["shot_issues"][k]) < score(c["shot_issues"][k]):
                        cand, chunk, c = fixed, chunk2, c2
                        unit["mechanical"].append(f"r{rnd}: {mnote}")
                        self.state["mechanical"].append(f"{uid} r{rnd}: {mnote}")
            if err:
                unit["rejects"].append(f"r{rnd}: {err}")
                log(f"  {uid} r{rnd} 拒收（{dt:.0f}s）：{err[:120]}")
                note = err
                continue
            new_issues = c["shot_issues"][k]
            log(f"  {uid} r{rnd}（{dt:.0f}s）：{score(cur_issues)} → {score(new_issues)} "
                f"{[i['rule_id'] for i in new_issues if i['level'] == 'block']}")
            if score(new_issues) <= score(cur_issues):
                self.chunks[ci], cur_block, cur_issues = chunk, cand, new_issues
                note = ""
            else:
                note = "上一版回复引入了更多格式问题：" + "；".join(
                    f"{i['rule_id']} {i['detail'][:60]}" for i in new_issues if i["level"] == "block")
                unit["rejects"].append(f"r{rnd}: 问题变多，未采用")
        unit["after"] = [i["rule_id"] for i in cur_issues]
        unit["after_detail"] = [f"{i['rule_id']}|{i['level']} {i['detail'][:200]}" for i in cur_issues
                                if i["level"] == "block" or a.fix_warn]
        if not failing(cur_issues, a.fix_warn):
            unit["status"] = "fixed"
        elif cur_block != orig_block:
            unit["status"] = "improved"
        else:
            unit["status"] = "unchanged"
        log(f"  {uid} → {unit['status']}  {unit['before']} → {unit['after']}")

    # --- 集头
    def repair_head(self, ci: int, ep_no: int, uid: str):
        a = self.a
        chk = self.checker.run(self.chunks[ci], ep_no)
        title = chk["obj"].title
        orig_head = block_text(self.chunks[ci], "head")
        orig_syn = chk["obj"].synopsis.strip()
        cur_head, cur_issues = orig_head, head_fixable(chk["head_issues"])
        unit = {"status": "", "rounds": 0, "before": [i["rule_id"] for i in cur_issues], "after": [],
                "rejects": [], "qwen_seconds": []}
        self.state["units"][uid] = unit
        brief = "\n".join(f"镜{s.index} sound：{s.sound[:200]}" for s in chk["obj"].shots)
        note = ""
        for rnd in range(1, a.max_rounds + 1):
            if not cur_issues:
                break
            unit["rounds"] = rnd
            req = V.repair_request(ep_no, None, cur_issues)
            raw, dt = self._qwen(uid, rnd, head_user_msg(ep_no, cur_head, req, note, brief))
            unit["qwen_seconds"].append(round(dt, 1))
            cand, err = parse_head_reply(raw, ep_no, title)
            if not err:
                chunk = splice(self.chunks[ci], "head", cand)
                c = self.checker.run(chunk, ep_no)
                if c["obj"] is None or c["obj"].synopsis.strip() != orig_syn:
                    err = "**剧情** 原文被改动；必须逐字保留"
                elif len(c["seg"]["shots"]) != len(chk["seg"]["shots"]):
                    err = "镜头数变了；只输出集头"
            if err:
                unit["rejects"].append(f"r{rnd}: {err}")
                log(f"  {uid} r{rnd} 拒收（{dt:.0f}s）：{err}")
                note = err
                continue
            new_issues = head_fixable(c["head_issues"])
            log(f"  {uid} r{rnd}（{dt:.0f}s）：{len(cur_issues)} → {len(new_issues)}")
            if len(new_issues) <= len(cur_issues):
                self.chunks[ci], cur_head, cur_issues = chunk, cand, new_issues
                note = ""
        unit["after"] = [i["rule_id"] for i in cur_issues]
        unit["status"] = "fixed" if not cur_issues else ("improved" if cur_head != orig_head else "unchanged")
        log(f"  {uid} → {unit['status']}")


# ------------------------------------------------------------------ 报告

def rule_counts(path: Path, eps: set[int] | None, names: list[str]) -> collections.Counter:
    c: collections.Counter = collections.Counter()
    rep = V.validate(path, None, names)
    for ep in rep["episodes"]:
        if eps and ep["number"] not in eps:
            continue
        for i in ep["issues"]:
            c[f"{i['rule_id']}|{i['level']}"] += 1
        for s in ep["shots"]:
            for i in s["issues"]:
                c[f"{i['rule_id']}|{i['level']}"] += 1
    return c


def report(r: Repairer) -> str:
    a = r.a
    eps = a.episode_set or None
    before = rule_counts(r.inp, eps, r.names)
    after = rule_counts(r.out, eps, r.names) if r.out.exists() else collections.Counter()
    keys = sorted(set(before) | set(after), key=lambda k: (k.split("|")[1] != "block", -before.get(k, 0)))
    lines = [f"范围：{'全部集' if not eps else sorted(eps)}",
             f"block：{sum(v for k, v in before.items() if k.endswith('|block'))} → "
             f"{sum(v for k, v in after.items() if k.endswith('|block'))}    "
             f"warn：{sum(v for k, v in before.items() if not k.endswith('|block'))} → "
             f"{sum(v for k, v in after.items() if not k.endswith('|block'))}",
             f"{'规则|级别':<18}{'前':>6}{'后':>6}"]
    lines += [f"{k:<18}{before.get(k, 0):>6}{after.get(k, 0):>6}" for k in keys]
    units = r.state["units"]
    st = collections.Counter(u.get("status") for u in units.values())
    secs = [x for u in units.values() for x in u.get("qwen_seconds", [])]
    lines.append(f"\n单元状态：{dict(st)}；Qwen 请求 {len(secs)} 次，平均 {sum(secs) / len(secs):.0f} 秒/次"
                 if secs else f"\n单元状态：{dict(st)}")
    lines.append(f"机械修正 {len(r.state.get('mechanical', []))} 条（见 state.json → mechanical）")
    lines.append("\n仍未通过：")
    for uid, u in units.items():
        if u.get("status") in ("improved", "unchanged", "not_auto_repaired"):
            why = u.get("after_detail") or [f"{i['rule_id']} {i['detail']}" for i in u.get("issues", [])] or u.get(
                "after")
            rej = u.get("rejects", [])[-1:] if u.get("rejects") else []
            lines.append(f"  {uid} [{u['status']}] {'; '.join(map(str, why))[:300]}"
                         + (f"  ｜最后一次拒收：{rej[0][:150]}" if rej else ""))
    text = "\n".join(lines)
    (r.rdir / "report.txt").write_text(text, encoding="utf-8")
    (r.rdir / "report.json").write_text(json.dumps({"before": before, "after": after, "units": units},
                                                   ensure_ascii=False, indent=1), encoding="utf-8")
    return text


def parse_episodes(spec: str | None) -> set[int]:
    out: set[int] = set()
    for part in (spec or "").split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            lo, hi = part.split("-", 1)
            out |= set(range(int(lo), int(hi) + 1))
        else:
            out.add(int(part))
    return out


def build_args(argv=None):
    ap = argparse.ArgumentParser(description="Qwen 格式返修循环")
    ap.add_argument("script", nargs="?", default=str(DEFAULT_IN))
    ap.add_argument("--out", help="输出路径（默认 输入名去掉 v3 → v3.1）")
    ap.add_argument("--episodes", help="只处理这些集，如 1 或 1-5,8")
    ap.add_argument("--max-rounds", type=int, default=3)
    ap.add_argument("--dry-run", action="store_true", help="只校验并列出要返修的单元，不调 Qwen、不写文件")
    ap.add_argument("--resume", action="store_true", help="从输出文件和 state.json 续跑")
    ap.add_argument("--fix-warn", action="store_true", help="warn 级问题也返修")
    ap.add_argument("--only-codes", default="", help="只返修这些规则号（逗号分隔，如 QW-CH6）；其余问题不动")
    ap.add_argument("--force-shot", action="append", default=[], help="单镜返修：epNN-SK=规则号:说明（校验没标出、契约方判定的同类格式冲突）")
    ap.add_argument("--think", action="store_true", help="让 Qwen 先思考（更慢）；默认关闭")
    ap.add_argument("--temperature", type=float, default=0.3)
    ap.add_argument("--timeout", type=int, default=600)
    ap.add_argument("--rules-tag", default="rules_v1", help="导出到下载目录时写进文件名的规则版本（如 rules_v2）")
    ap.add_argument("--no-export", action="store_true", help="不复制到 为他而骚短剧/Qwen剧本/")
    ap.add_argument("--backend", choices=("llm", "abliteration", "local"), default="llm",
                    help="写作模型：llm = 统一配置 config/llm_providers.json 的用途 script_repair（默认 abliteration "
                         "large-flash）；abliteration = 同上但指定服务商 abliteration；local = 旧 gpu3 :8098 Qwen（已撤下，仅兼容）")
    ap.add_argument("--provider", help="llm 后端：覆盖服务商 id（config/llm_providers.json）")
    ap.add_argument("--model", help="llm 后端：覆盖模型名")
    ap.add_argument("--base-url", help="local 后端：已有的 Qwen 地址；不给则自动开 ssh 隧道")
    ap.add_argument("--repair-dir", help="state/回复目录（默认 <输出目录>/repair）")
    ap.add_argument("--names", default="", help="H3 里禁止出现的人名，逗号分隔（传给校验器）")
    a = ap.parse_args(argv)
    ONLY_CODES.update(x.strip() for x in (a.only_codes or "").split(",") if x.strip())
    for fs in a.force_shot:
        sid, _, rest = fs.partition("=")
        code, _, detail = rest.partition(":")
        e_, s_ = sid.lower().replace("ep", "").split("-s")
        FORCE[(int(e_), int(s_))] = (code.strip(), detail.strip())
    src = Path(a.script)
    if not a.out:
        stem = src.stem
        a.out = str(src.with_name((stem[:-2] + "v3.1" if stem.endswith("v3") else stem + "_repaired") + src.suffix))
    if Path(a.out).resolve() == src.resolve():
        ap.error("输出路径不能等于输入（原文只读）")
    a.episode_set = parse_episodes(a.episodes)
    return a


def main(argv=None, ask=None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    a = build_args(argv)
    r = Repairer(a, ask=ask)
    try:
        r.run()
    finally:
        if isinstance(r.ask, Qwen):
            r.ask.close()
    if a.dry_run:
        return 0
    print("\n" + report(r), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
