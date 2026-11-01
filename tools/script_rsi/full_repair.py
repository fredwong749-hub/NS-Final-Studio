"""SCRIPT-RSI 全量返修（D-SCR-07，2026-11-01）：节奏重切（QW-T1）→ 表演 / 视线 / 轴线返修（QW-A1–A8、QW-AX1）→ 校验 → 合并 → 导入计划。

项目方原话（11-01 18:2x）：“演员表现：所有图片不要看镜头……3. 规则与剧本：……你把演员的演戏规则、导演的规则、镜头的规则都做上去，
把剧本改一下，重新更新一下规则。”

Claude 只写系统：拼输入、算数字、发返修请求、核对不变量。剧本正文全部由写作模型（llm_config.resolve("script_write")）改写，
系统不改写、不评价内容。不变量：每条对白 / 🎙 逐字保留且同顺序；集总时长不变；P4 阻断不增加。

节奏重切只做算术：每镜上限 L = writer_lints QW-T1（无台词 6 秒；有台词 max(6, 字数 ÷ 4.5 + 1.5)），超出部分记为“让出秒数”；
相邻几镜让出的秒数凑成 3–6 秒，交给写作方在这组里插一个无台词的新镜（承接 / 反应 / 局部，内容由写作方定）；
新镜数受 D-SCR-06 上限 max(8, 轮次 + 独白, ⌈秒数 ÷ 6⌉) 约束，装不下的组整组不动（留着 QW-T1，报告里列出）。

    # 单集（可并行开 10 个进程）
    .venv/Scripts/python.exe tools/script_rsi/full_repair.py run --episode 3 --out-dir data/autopilot/script_rsi/<tag>
    # 合并 + 校验 + 暂存 + 导入计划
    .venv/Scripts/python.exe tools/script_rsi/full_repair.py merge --out-dir data/autopilot/script_rsi/<tag> --episodes 1-10
    # 桩写作方（不花钱，只验链路）：run 加 --stub
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "packages" / "schema", ROOT / "services" / "agent", ROOT / "services" / "api"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

CODES = ["QW-A1", "QW-A2", "QW-A3", "QW-A4", "QW-A5", "QW-A6", "QW-A7", "QW-A8", "QW-AX1"]
INSERT_MIN_S, INSERT_MAX_S = 3, 6


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _log(od: Path, msg: str):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(od / "log.txt", "a", encoding="utf-8") as f:
        f.write(line + "\n")


# ------------------------------------------------------------------ 写作方客户端（计调用数和 token）

class Writer:
    """OpenAI 兼容；用途 script_write（K-WRT-108：默认关推理）。usage 累计到 self.usage"""

    def __init__(self, timeout: int = 900, temperature: float = 0.3):
        from ns_api import llm_config
        rv = llm_config.resolve("script_write")
        self.model, self.key, self.base = rv["model"], rv["api_key"], rv["base_url"].rstrip("/")
        self.off = ((rv.get("reasoning_body") or {}).get("off") or {}) if (rv.get("reasoning_ok") or {}).get("off") else {}
        self.timeout, self.temperature = timeout, temperature
        self.usage = {"calls": 0, "failed": 0, "prompt_tokens": 0, "completion_tokens": 0, "model": self.model,
                      "provider": rv["id"], "purpose": "script_write"}
        if not self.key:
            raise SystemExit(f"缺少 {rv['name']} 的 API key")

    def __call__(self, system: str, user: str) -> str:
        body = {"model": self.model, "temperature": self.temperature, "stream": False, "max_tokens": 12000,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}], **self.off}
        last = None
        for attempt in range(5):
            try:
                req = urllib.request.Request(f"{self.base}/chat/completions", json.dumps(body).encode(),
                                             {"Content-Type": "application/json", "Authorization": f"Bearer {self.key}"})
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    data = json.loads(r.read().decode("utf-8"))
                self.usage["calls"] += 1
                u = data.get("usage") or {}
                self.usage["prompt_tokens"] += int(u.get("prompt_tokens") or 0)
                self.usage["completion_tokens"] += int(u.get("completion_tokens") or 0)
                return data["choices"][0]["message"].get("content") or ""
            except (urllib.error.URLError, OSError, TimeoutError, KeyError, json.JSONDecodeError) as e:
                last = e
                self.usage["failed"] += 1
                time.sleep(min(60, 5 * (attempt + 1) ** 2))
        raise RuntimeError(f"{self.model} 连续 5 次请求失败：{last!r}")


def stub_writer(system: str, user: str) -> str:
    """桩：原样回第一个镜头块（重切请求会因时长不符被拒，链路照常走完）"""
    m = re.search(r"当前的完整 Markdown：\n(.*?)\n\n(?:【|它后面)", user, re.S)
    return m.group(1) if m else ""


# ------------------------------------------------------------------ 节奏重切：纯算术

def speech_limit(WL, sh) -> int:
    ch = WL._speech_chars(sh)
    return int(WL.PACE_MAX_S if not ch else max(WL.PACE_MAX_S, -(-int(ch / WL.SPEECH_CPS * 10 + 15) // 10)))


def plan_groups(durs: list[int], lims: list[int], n0: int, cap: int | None) -> tuple[list[dict], list[int]]:
    """→ (组, 留下仍超长的镜号)。镜号 1 起。每组：donors {镜号: 新时长}、insert_after 镜号、dur 新镜秒数"""
    cut = {i + 1: max(0, d - lim) for i, (d, lim) in enumerate(zip(durs, lims))}
    groups, cur = [], []
    for k in range(1, n0 + 1):
        if not cut[k]:
            continue
        if sum(cut[x] for x in cur) + cut[k] > INSERT_MAX_S and sum(cut[x] for x in cur) >= INSERT_MIN_S:
            groups.append(cur)
            cur = []
        cur.append(k)
    if cur:
        groups.append(cur)
    # 单镜让出 > 6 秒（如 13 秒镜）：拆不完的部分留着
    out, left = [], []
    for g in groups:
        s = sum(cut[x] for x in g)
        if s < INSERT_MIN_S and out and sum(out[-1]["donors_cut"].values()) + s <= INSERT_MAX_S:
            out[-1]["donors_cut"].update({x: cut[x] for x in g})
            continue
        out.append({"donors_cut": {x: cut[x] for x in g}})
    room = max(0, (cap or n0) - n0)
    keep = sorted(out, key=lambda g: -sum(g["donors_cut"].values()))[:room]
    res = []
    for g in out:
        s = sum(g["donors_cut"].values())
        if g not in keep or s < INSERT_MIN_S:
            left += list(g["donors_cut"])
            continue
        if s > INSERT_MAX_S:   # 只取到 6 秒：从让出最多的镜少让
            over = s - INSERT_MAX_S
            for x in sorted(g["donors_cut"], key=lambda x: -g["donors_cut"][x]):
                take = min(over, g["donors_cut"][x])
                g["donors_cut"][x] -= take
                over -= take
                if g["donors_cut"][x] and durs[x - 1] - g["donors_cut"][x] > lims[x - 1]:
                    left.append(x)
            g["donors_cut"] = {x: c for x, c in g["donors_cut"].items() if c}
            s = INSERT_MAX_S
        k = max(g["donors_cut"], key=lambda x: (g["donors_cut"][x], -x))
        res.append({"donors": {x: durs[x - 1] - c for x, c in g["donors_cut"].items()}, "insert_after": k, "dur": s})
    return res, sorted(set(left))


# ------------------------------------------------------------------ 请求文本（只讲格式与数字，不写内容）

def retime_request(k: int, old: int, new: int, lim: int) -> str:
    return (f"【节奏返修 QW-T1（D-SCR-06 / D-SCR-07：剧情镜头太慢，单镜不超过上限）】\n"
            f"镜{k} 现在 {old} 秒，单镜上限 {lim} 秒。把 **时长** 改成 {new} 秒：分拍时间轴、motion、H3 的 At 时间码和末句都按 {new} 秒重排，"
            f"每拍 ≤2.5 秒、第一拍从 0 秒起就在动作中；多出来的动作删掉或压缩（相邻会插入一个新镜承接）。"
            f"同时满足：每拍写 视线=（落在画里的人或物上）和 表情=；多人镜每拍 反应= 写其他每个在画的人“名字：视线落点 + 表情”；"
            f"img 里每个在画的人写视线落点；不写朝向镜头 / 看镜头。")


def insert_user_msg(ep_no: int, k: int, head: str, block: str, nxt: str, old: int, new: int, z: int, lim: int, note: str) -> str:
    parts = [f"以下是 ep{ep_no:02d} 的集头（只作上下文，不要输出）：", head, "",
             f"以下是 ep{ep_no:02d} 镜{k} 当前的完整 Markdown：", block, ""]
    if nxt:
        parts += [f"它后面原来的下一镜（只作上下文，不要输出；系统会把它顺延编号）：", nxt, ""]
    parts += [
        f"【节奏返修 QW-T1（D-SCR-06 / D-SCR-07：项目方“剧情镜头太慢”，单镜不超过上限）】",
        f"镜{k} 现在 {old} 秒，单镜上限 {lim} 秒。请输出两个镜头块：",
        f"1）**镜{k}**：原有的 **对白** 与 🎙 逐字保留（含标点、同顺序）；**时长** 改成 {new} 秒，分拍时间轴、motion、H3 的 At 时间码按 {new} 秒重排。",
        f"2）**镜{k + 1}**（新插入的镜）：**时长** {z} 秒；没有台词也没有 🎙（不写 **对白** 行）；接住镜{k} 的动作，或给在画的人一个反应 / 局部特写；"
        f"**场景** 用镜{k} 的同一个场景 id，**人物** 只用镜{k} 人物行里已有的人，造型不变；**衔接** 写 接力 或 同场换机位；"
        f"字段齐全、顺序同上面的镜头（img、场景、人物、衔接、站位、光线、镜头运动、分拍、motion、时长、sound、H3提示词）。",
        "两镜都要：第一拍从 0 秒起就在动作中，每拍 ≤2.5 秒；每拍写 视线=（落在画里的人或物上）和 表情=；多人镜每拍 反应= 写其他每个在画的人"
        "“名字：视线落点 + 表情”；img 里每个在画的人写视线落点；H3 第一个时间码之前写出开场时每个在画的人眼睛落在哪里；不写朝向镜头 / 看镜头。"]
    if note:
        parts += ["", f"上一次的回复没有被采用：{note}"]
    parts += ["", f"只输出 **镜{k}｜img** 和 **镜{k + 1}｜img** 开头的这两个完整镜头块，不要解释，不要输出集头或其它镜头。"]
    return "\n".join(parts)


def parse_blocks(RL, raw: str, want: list[int]) -> tuple[list[str] | None, str]:
    lines = RL.strip_think(raw).split("\n")
    starts = [i for i, ln in enumerate(lines) if RL.SHOT_RE.match(RL._norm(ln))]
    got = [int(RL.SHOT_RE.match(RL._norm(lines[i])).group(1)) for i in starts]
    if got != want:
        return None, f"回复里的镜头块镜号是 {got}，应为 {want}"
    out = []
    for n, s in enumerate(starts):
        e = starts[n + 1] if n + 1 < len(starts) else len(lines)
        blk, in_code = [], False
        for i in range(s, e):
            ln = lines[i]
            if ln.strip().startswith("```"):
                in_code = not in_code
            elif not in_code and i > s and RL._is_boundary(ln):
                break
            blk.append(ln.rstrip())
        blk, err = RL._close_fences(blk)
        if err:
            return None, err
        out.append("\n".join(blk))
    return out, ""


def renumber(chunk: str, after: int) -> str:
    return re.sub(r"镜(\d+)", lambda m: f"镜{int(m.group(1)) + 1}" if int(m.group(1)) > after else m.group(0), chunk)


HARD_SKIP = ("QW-A", "QW-D", "QW-W", "VQ-", "QW-T")


def hard_list(c: dict, skip: tuple = ()) -> list[dict]:
    iss = list(c["head_issues"]) + [i for s in c["shot_issues"] for i in s]
    return [i for i in iss if i.get("level") == "block" and not str(i.get("rule_id", "")).startswith(HARD_SKIP + skip)]


def hard_blocks(c: dict, skip: tuple = ()) -> int:
    return len(hard_list(c, skip))


def hard_note(c: dict, skip: tuple = ()) -> str:
    return "；".join(f"{i['rule_id']} {i['detail'][:160]}" for i in hard_list(c, skip))[:600]


# 让出镜先改时长时集总时长会暂时变短（插入新镜后才补回）：中间步骤不看 QW-E3（总时长 50–75 秒）
MID_SKIP = ("QW-E3",)


# ------------------------------------------------------------------ 单集：重切

def recut_episode(RL, WL, pre: str, chunk: str, ep_no: int, ask, od: Path, rounds: int = 3) -> tuple[str, dict]:
    chk = RL.Checker(pre, od, [])
    c0 = chk.run(chunk, ep_no)
    ep = c0["obj"]
    shots = sorted(ep.shots, key=lambda s: s.index)
    durs = [int(s.duration or 0) for s in shots]
    lims = [speech_limit(WL, s) for s in shots]
    from ns_agent.importer.script_md import shot_cap
    cap = shot_cap(ep)
    groups, left = plan_groups(durs, lims, len(shots), cap)
    rep = {"ep": ep_no, "n0": len(shots), "cap": cap, "total": sum(durs), "durs_before": durs, "limits": lims,
           "plan": groups, "left_planned": left, "groups": []}
    _log(od, f"ep{ep_no:02d} 重切计划：{len(shots)} 镜 / {sum(durs)} 秒 / 上限 {cap} 镜；组 {groups}；装不下 {left}")
    base_hard = hard_blocks(c0)
    base_mid = hard_blocks(c0, MID_SKIP)
    req_dir = od / "recut"
    req_dir.mkdir(exist_ok=True)

    def call(uid, user):
        (req_dir / f"{uid}.req.txt").write_text(user, encoding="utf-8")
        raw = ask(SYSTEM["text"], user)
        (req_dir / f"{uid}.reply.txt").write_text(raw, encoding="utf-8")
        return raw

    for g in sorted(groups, key=lambda g: -g["insert_after"]):
        snap = chunk
        k = g["insert_after"]
        grec = {"insert_after": k, "planned": g, "done": [], "status": ""}
        z = g["dur"]
        # ① 其它让出镜先改时长（不插入，编号不变）
        for x in sorted(g["donors"]):
            if x == k:
                continue
            new = g["donors"][x]
            ok, note = False, ""
            for r in range(1, rounds + 1):
                blk = RL.block_text(chunk, x - 1)
                orig = RL.Checker(pre, od, []).run(chunk, ep_no)["obj"].shots[x - 1]
                head = RL.block_text(chunk, "head")
                raw = call(f"ep{ep_no:02d}-S{x}-retime-r{r}",
                           RL.shot_user_msg(ep_no, x, head, blk, retime_request(x, durs[x - 1], new, lims[x - 1]), note))
                cand, err = RL.parse_shot_reply(raw, x)
                if not err:
                    cand, _ = RL.mech_align(cand, new)
                    ch2 = RL.splice(chunk, x - 1, cand)
                    c2 = chk.run(ch2, ep_no)
                    ns = c2["obj"].shots[x - 1] if c2["obj"] and len(c2["obj"].shots) >= x else None
                    err = ("拼回后解析不到这个镜头" if ns is None else RL.dialogue_check(orig, ns, True)
                           or (f"**时长** 应为 {new} 秒（现在 {ns.duration}）" if int(ns.duration or 0) != new else "")
                           or (f"引入了新的格式阻断：{hard_note(c2, MID_SKIP)}" if hard_blocks(c2, MID_SKIP) > base_mid else ""))
                if not err:
                    chunk, ok = ch2, True
                    break
                note = err
                _log(od, f"  ep{ep_no:02d}-S{x} 改时长 r{r} 拒收：{err[:120]}")
            if ok:
                grec["done"].append({"shot": x, "dur": new})
            else:
                z -= durs[x - 1] - new
                grec["done"].append({"shot": x, "failed": note[:200]})
        if z < INSERT_MIN_S:
            chunk = snap
            grec["status"] = f"整组撤回：新镜只剩 {z} 秒（<{INSERT_MIN_S}）"
            rep["groups"].append(grec)
            _log(od, f"  ep{ep_no:02d} 组@S{k} {grec['status']}")
            continue
        # ② 让出最多的镜 + 插入新镜（一次请求两个块）
        new_k = g["donors"][k]
        ok, note = False, ""
        for r in range(1, rounds + 1):
            c_now = chk.run(chunk, ep_no)
            orig = c_now["obj"].shots[k - 1]
            n_now = len(c_now["obj"].shots)
            blk = RL.block_text(chunk, k - 1)
            nxt = RL.block_text(chunk, k) if k < n_now else ""
            raw = call(f"ep{ep_no:02d}-S{k}-insert-r{r}",
                       insert_user_msg(ep_no, k, RL.block_text(chunk, "head"), blk, nxt, durs[k - 1], new_k, z, lims[k - 1], note))
            blocks, err = parse_blocks(RL, raw, [k, k + 1])
            if not err:
                b1, _ = RL.mech_align(blocks[0], new_k)
                b2, _ = RL.mech_align(blocks[1], z)
                ch2 = RL.splice(renumber(chunk, k), k - 1, b1 + "\n" + b2)
                c2 = chk.run(ch2, ep_no)
                sh2 = c2["obj"].shots if c2["obj"] else []
                if len(sh2) != n_now + 1:
                    err = f"拼回后镜数 {len(sh2)}，应为 {n_now + 1}"
                else:
                    a, b = sh2[k - 1], sh2[k]
                    err = (RL.dialogue_check(orig, a, True)
                           or (f"镜{k} **时长** 应为 {new_k} 秒（现在 {a.duration}）" if int(a.duration or 0) != new_k else "")
                           or (f"新镜{k + 1} **时长** 应为 {z} 秒（现在 {b.duration}）" if int(b.duration or 0) != z else "")
                           or (f"新镜{k + 1} 不能有台词或 🎙" if (b.dialogue or (b.voiceover and b.voiceover.text)) else "")
                           or (f"新镜{k + 1} 的场景 id 应与镜{k} 相同（{a.scene_id}）" if b.scene_id != a.scene_id else "")
                           or (f"引入了新的格式阻断（{hard_blocks(c2)} > {base_hard}）："
                               + "；".join(f"{i['rule_id']} {i['detail'][:200]}" for i in
                                          (list(c2['head_issues']) + [j for s in c2['shot_issues'] for j in s])
                                          if i.get('level') == 'block' and not str(i.get('rule_id', '')).startswith(HARD_SKIP))[:300]
                               if hard_blocks(c2) > base_hard else ""))
            if not err:
                chunk, ok = ch2, True
                break
            note = err
            _log(od, f"  ep{ep_no:02d}-S{k} 插入 r{r} 拒收：{err[:160]}")
        if ok:
            grec["done"].append({"shot": k, "dur": new_k, "inserted": k + 1, "insert_dur": z})
            grec["status"] = "ok"
        else:
            chunk = snap
            grec["status"] = f"整组撤回：插入失败（{note[:160]}）"
        rep["groups"].append(grec)
        _log(od, f"  ep{ep_no:02d} 组@S{k}：{grec['status']}")
    c_end = chk.run(chunk, ep_no)
    rep["durs_after"] = [int(s.duration or 0) for s in sorted(c_end["obj"].shots, key=lambda s: s.index)]
    rep["total_after"] = sum(rep["durs_after"])
    return chunk, rep


SYSTEM = {"text": ""}


def _system_text() -> str:
    s = (ROOT / "config" / "qwen_writer_system_prompt.txt").read_text(encoding="utf-8")
    wk = ROOT / "config" / "recipes" / "writer_knowledge.md"
    if wk.exists():
        s += "\n\n========\n\n" + wk.read_text(encoding="utf-8")
    return s


# ------------------------------------------------------------------ 不变量（原稿 → 终稿，按集）

def dialogue_seq(ep) -> list[str]:
    out = []
    for s in sorted(ep.shots, key=lambda s: s.index):
        out += [f"{d.speaker}|{d.text.strip()}" for d in s.dialogue]
        if s.voiceover and s.voiceover.text:
            out.append(f"🎙{s.voiceover.speaker}|{s.voiceover.text.strip()}")
    return out


def invariants(a_path: Path, b_path: Path) -> dict:
    from ns_agent.importer.script_md import import_script
    A = {e.number: e for e in import_script(a_path).episodes}
    B = {e.number: e for e in import_script(b_path).episodes}
    res = {"ok": True, "eps": {}}
    for n, ea in A.items():
        eb = B.get(n)
        r = {"present": eb is not None}
        if eb:
            r["dialogue_verbatim"] = dialogue_seq(ea) == dialogue_seq(eb)
            r["total_s"] = [sum(int(s.duration or 0) for s in ea.shots), sum(int(s.duration or 0) for s in eb.shots)]
            r["shots"] = [len(ea.shots), len(eb.shots)]
            r["ok"] = r["dialogue_verbatim"] and r["total_s"][0] == r["total_s"][1]
        else:
            r["ok"] = False
        res["eps"][n] = r
        res["ok"] &= r["ok"]
    return res


def counts(V_json: dict) -> dict:
    """validate --json → {集: {规则: 数}}"""
    out = {}
    for e in V_json.get("episodes") or []:
        n = e.get("number") or e.get("episode")
        c = {}
        for i in list(e.get("issues") or []) + [j for s in e.get("shots") or [] for j in s.get("issues") or []]:
            c[i["rule_id"]] = c.get(i["rule_id"], 0) + 1
            if i.get("level") == "block":
                c["_block"] = c.get("_block", 0) + 1
        out[int(n)] = c
    return out


def validate_json(path: Path) -> dict:
    import os
    import subprocess
    r = subprocess.run([sys.executable, str(ROOT / "tools/validate_qwen_script.py"), str(path), "--json"], capture_output=True,
                       cwd=ROOT, timeout=1800, env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"})
    return json.loads(r.stdout.decode("utf-8"))


# ------------------------------------------------------------------ 命令

def cmd_run(a) -> int:
    RC = _load("repair_chain", "tools/pipeline/repair_chain.py")
    RL = RC._load_rl()
    WL = RL.V.WL
    od = Path(a.out_dir) / f"ep{a.episode:02d}"
    od.mkdir(parents=True, exist_ok=True)
    SYSTEM["text"] = _system_text()
    ask = stub_writer if a.stub else Writer()
    text, rec = RC.assemble(RL, [a.episode], RC.episode_sources())
    (od / "input.md").write_text(text, encoding="utf-8")
    (od / "sources.json").write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
    pre, chunks = RL.split_doc(text)
    rep = {"episode": a.episode, "started": time.strftime("%F %T")}
    if a.skip_recut:
        new = chunks[0]
    else:
        new, rep["recut"] = recut_episode(RL, WL, pre, chunks[0], a.episode, ask, od, rounds=a.rounds)
    (od / "recut.md").write_text(pre + new, encoding="utf-8")
    # 表演 / 视线 / 轴线返修：qwen_repair_loop（同一校验器、同一写作方客户端）
    args = [str(od / "recut.md"), "--out", str(od / "output.md"), "--repair-dir", str(od / "repair"), "--fix-warn",
            "--only-codes", ",".join(CODES), "--no-export", "--max-rounds", str(a.rounds)]
    RL.main(args, ask=ask)
    rep["verify_a_pass"] = RC.verify(RL, od / "recut.md", od / "output.md", [a.episode])
    rep["invariants"] = invariants(od / "input.md", od / "output.md")
    rep["usage"] = getattr(ask, "usage", {"calls": 0, "stub": True})
    rep["finished"] = time.strftime("%F %T")
    (od / "report.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    _log(od, f"ep{a.episode:02d} 完成：不变量 {rep['invariants']['ok']}；A 环校验 {rep['verify_a_pass']['ok']}；调用 {rep['usage']}")
    return 0 if rep["invariants"]["ok"] else 1


def cmd_polish(a) -> int:
    """第二遍：对单集终稿再跑一次返修环（A 码 + 本集出现的 P4 阻断码），终稿前一版留作 output_pass<N>.md；不变量对 input.md 重算"""
    RC = _load("repair_chain", "tools/pipeline/repair_chain.py")
    RL = RC._load_rl()
    od = Path(a.out_dir) / f"ep{a.episode:02d}"
    SYSTEM["text"] = _system_text()
    ask = Writer()
    n = 1
    while (od / f"output_pass{n}.md").exists():
        n += 1
    prev = od / f"output_pass{n}.md"
    prev.write_bytes((od / "output.md").read_bytes())
    codes = CODES + [c.strip() for c in (a.extra_codes or "").split(",") if c.strip()]
    RL.main([str(prev), "--out", str(od / "output.md"), "--repair-dir", str(od / f"repair_polish{n}"), "--fix-warn",
             "--only-codes", ",".join(codes), "--no-export", "--max-rounds", str(a.rounds),
             *[x for f in (a.force_shot or []) for x in ("--force-shot", f)]], ask=ask)
    rp = json.loads((od / "report.json").read_text(encoding="utf-8"))
    rp.setdefault("polish", []).append({"pass": n, "codes": codes, "usage": ask.usage,
                                        "verify": RC.verify(RL, prev, od / "output.md", [a.episode])})
    rp["invariants"] = invariants(od / "input.md", od / "output.md")
    for k in ("calls", "prompt_tokens", "completion_tokens", "failed"):
        rp.setdefault("usage", {})[k] = int(rp["usage"].get(k) or 0) + int(ask.usage.get(k) or 0)
    (od / "report.json").write_text(json.dumps(rp, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    _log(od, f"ep{a.episode:02d} polish{n} 完成：不变量 {rp['invariants']['ok']}；调用 {ask.usage}")
    return 0 if rp["invariants"]["ok"] else 1


def cmd_merge(a) -> int:
    RC = _load("repair_chain", "tools/pipeline/repair_chain.py")
    RL = RC._load_rl()
    od = Path(a.out_dir)
    eps = sorted(RL.parse_episodes(a.episodes))
    pre, parts, inp_parts, rec, usage = None, [], [], [], {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "failed": 0}
    for e in eps:
        d = od / f"ep{e:02d}"
        rp = json.loads((d / "report.json").read_text(encoding="utf-8"))
        if not rp["invariants"]["ok"]:
            raise SystemExit(f"ep{e:02d} 不变量没过，不合并：{rp['invariants']}")
        p0, ch = RL.split_doc((d / "output.md").read_text(encoding="utf-8"))
        _, ich = RL.split_doc((d / "input.md").read_text(encoding="utf-8"))
        pre = pre if pre is not None else p0
        parts.append(ch[0] if ch[0].endswith("\n") else ch[0] + "\n")
        inp_parts.append(ich[0] if ich[0].endswith("\n") else ich[0] + "\n")
        rec += json.loads((d / "sources.json").read_text(encoding="utf-8"))
        for k in usage:
            usage[k] += int((rp.get("usage") or {}).get(k) or 0)
    out, inp = od / "output.md", od / "input.md"
    out.write_text(pre + "".join(parts), encoding="utf-8")
    inp.write_text(pre + "".join(inp_parts), encoding="utf-8")
    inv = invariants(inp, out)
    vb, va = validate_json(inp), validate_json(out)
    cb, ca = counts(vb), counts(va)
    summary = {"schema": "nsfs.script_rsi_full_repair/1", "at": time.strftime("%F %T"), "episodes": eps, "sources": rec,
               "invariants": inv, "blocking": {"before": vb.get("blocking"), "after": va.get("blocking")},
               "warnings": {"before": vb.get("warnings"), "after": va.get("warnings")},
               "counts_before": cb, "counts_after": ca, "usage": usage}
    ok = inv["ok"] and not va.get("blocking")
    if ok and not a.no_stage:
        prefix = RC.srcs_name_prefix(rec)
        staged = ROOT / "data/staging_v3/merged" / f"{prefix}_rsiD07_{'_'.join(f'ep{e:02d}' for e in eps)}_v3.md"
        if staged.exists():
            staged = staged.with_name(staged.stem + time.strftime("_%H%M%S") + ".md")
        staged.write_bytes(out.read_bytes())
        summary["staged"] = RC._rel(staged)
        plan = {"why": "D-SCR-07：项目方 11-01 18:2x“把剧本改一下”（总调度 fredw-2b 派 SCRIPT-RSI 返修 + 导入）",
                "endpoint": "POST http://127.0.0.1:8800/api/script-inbox/import",
                "body": {"path": RC._rel(staged), "sha256": hashlib.sha256(staged.read_bytes()).hexdigest(),
                         "by": "SCRIPT-RSI（总调度 fredw-2b 授权，D-SCR-07）", "confirm": True, "mode": "merge",
                         "note": f"D-SCR-07 表演 / 视线 / 节奏返修 ep{a.episodes}"},
                "invariants_ok": inv["ok"], "blocking_after": va.get("blocking")}
        (od / "import_plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=1), encoding="utf-8")
    (od / "merge.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k not in ("sources", "counts_before", "counts_after")},
                     ensure_ascii=False, default=str)[:3000])
    return 0 if ok else 1


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--episode", type=int, required=True)
    r.add_argument("--out-dir", required=True)
    r.add_argument("--rounds", type=int, default=3)
    r.add_argument("--stub", action="store_true")
    r.add_argument("--skip-recut", action="store_true")
    m = sub.add_parser("merge")
    m.add_argument("--out-dir", required=True)
    m.add_argument("--episodes", required=True)
    m.add_argument("--no-stage", action="store_true")
    pz = sub.add_parser("polish")
    pz.add_argument("--episode", type=int, required=True)
    pz.add_argument("--out-dir", required=True)
    pz.add_argument("--rounds", type=int, default=3)
    pz.add_argument("--extra-codes", default="")
    pz.add_argument("--force-shot", action="append", default=[], help="透传 qwen_repair_loop --force-shot：epNN-SK=规则号:更具体的说明（只讲格式）")
    a = ap.parse_args(argv)
    return {"run": cmd_run, "merge": cmd_merge, "polish": cmd_polish}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
