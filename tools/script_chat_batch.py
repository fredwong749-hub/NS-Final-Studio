"""
用剧本创作对话框的后端（T58）批量重写一份剧本：每集单独请求写作模型（不带历史），
回复按集号并入一个对话会话的草稿 data/script_chat/<sid>/script.md，最后整份格式校验。
画布 #/script-chat 里能看到这个会话、每集的请求与回复、校验结果，可以继续对话修改。

系统只收发：给模型的是「原稿这一集 + 固定的任务说明 + 这一集的格式校验问题」，规则全在系统提示词里
（config/script_chat_rules.md + 格式契约 + 全局头），不改模型输出。

    .venv\\Scripts\\python.exe tools\\script_chat_batch.py                      # 默认 v3.1 全部集
    .venv\\Scripts\\python.exe tools\\script_chat_batch.py --episodes 1-3 --workers 2
    .venv\\Scripts\\python.exe tools\\script_chat_batch.py --session <sid>      # 续跑：已有的集跳过
    tools/script_chat_batch.py --episodes 6-60 --registry-from <ep03 会话id>
        人物表 / 场景表全剧一份、逐集继承（fredw-92 2026-10-31）：默认按集号顺序一集一集写（workers=1），
        写 epN 时全局头带 生产登记 + --registry-from + 本会话 ep<N 已登记的全剧人物表 / 全剧场景表；--no-inherit 关掉
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "services" / "api")]
from ns_api import script_chat as S  # noqa: E402

DEFAULT_SOURCE = REPO / "data" / "staging_v3" / "为他而骚 （剧本和镜头）v3.1.md"

TASK = """以下是《为他而骚》ep{n:02d} 的最新稿（{src}）。请按系统规则重写这一集的完整剧本与镜头分镜，只输出这一集（从 `## ep{n:02d}《` 开始，到 `---` 结束）。
- 剧情、人物、对白与独白原文保持不变（对白逐字照抄进 `**对白**` 和 H3 的 `<d>`）。
- 画面、尾帧结束状态、欲望感、声音、配乐、H3 提示词按系统规则写足、写对。
{issues}
{checklist}
【原稿 ep{n:02d}】
{body}"""

# 上下文放不下本集命中的附录时，原稿拆成两半分两次写（总调度 2026-10-30：“不要丢规则”）
TASK_A = """以下是《为他而骚》ep{n:02d} 最新稿（{src}）的前半：集头和镜{a}–镜{b}。请按系统规则重写，只输出集头（`## ep{n:02d}《…》`、`**剧情**`、`**配乐**`）和镜{a}–镜{b}，镜号保持原编号；这一半末尾不写 `---`。后半（镜{c}–镜{d}）另行请求。
- 剧情、人物、对白与独白原文保持不变（对白逐字照抄进 `**对白**` 和 H3 的 `<d>`）。
- 画面、尾帧结束状态、欲望感、声音、配乐、H3 提示词按系统规则写足、写对。
{issues}
{checklist}
【原稿 ep{n:02d} 前半】
{body}"""

TASK_B = """以下是《为他而骚》ep{n:02d} 最新稿（{src}）的后半：镜{c}–镜{d}。前半已经写好，集头如下（只读参考，不要再输出）：
{head}
请按系统规则重写镜{c}–镜{d}，只输出这几镜（从 `**镜{c}｜img**` 开始），镜号保持原编号。
- 剧情、人物、对白与独白原文保持不变（对白逐字照抄进 `**对白**` 和 H3 的 `<d>`）。
- 画面、尾帧结束状态、欲望感、声音、配乐、H3 提示词按系统规则写足、写对。
{issues}
{checklist}
【原稿 ep{n:02d} 后半】
{body}"""


def parse_range(s: str, have: list[int]) -> list[int]:
    if not s:
        return have
    out = []
    for part in s.split(","):
        a, _, b = part.partition("-")
        out += list(range(int(a), int(b or a) + 1))
    return [n for n in out if n in have]


def source_issues(episodes: dict[int, str], todo: list[int]) -> dict[int, str]:
    """原稿这几集的格式校验问题（只列 block 项的规则与现状），帮模型一次写对；逐集校验，不跑整份大文件"""
    out = {}
    for n in todo:
        e = S.validate_episode_text(episodes[n], f"src{n:02d}")
        if not e:
            continue
        lines = [f"- [{i['rule_id']}] {i['detail'][:200]}" for i in e["issues"] if i["level"] == "block"]
        for sh in e["shots"]:
            lines += [f"- 镜{sh['index']} [{i['rule_id']}] {i['detail'][:200]}" for i in sh["issues"]
                      if i["level"] == "block"]
        if lines:
            out[n] = "- 原稿有这些格式问题，重写时必须全部改正：\n" + "\n".join(dict.fromkeys(lines))
    return out


def model_price() -> dict:
    """当前模型每 token 单价（GET /models 的 pricing）；本地模型（gpu3 Qwen）不计费；
    abliteration 取不到时用 2026-10-30 实测的 v2 价格"""
    pv = S.provider()
    if pv["name"] != "abliteration":
        return {"prompt": 0.0, "completion": 0.0, "input_cache_read": 0.0}
    try:
        req = S.urllib.request.Request(pv["base_url"] + "/models",
                                       headers={"Authorization": f"Bearer {pv['api_key']}"} if pv["api_key"] else {})
        for m in json.load(S.urllib.request.urlopen(req, timeout=30))["data"]:
            if m["id"] == pv["model"] and m.get("pricing"):
                p = m["pricing"]
                return {k: float(p.get(k, 0) or 0) for k in ("prompt", "completion", "input_cache_read")}
    except Exception:  # noqa: BLE001
        pass
    return {"prompt": 3e-6, "completion": 5e-6, "input_cache_read": 3e-7}


def usage_cost(u: dict | None, price: dict) -> float:
    if not u:
        return 0.0
    cached = ((u.get("prompt_tokens_details") or {}).get("cached_tokens") or 0)
    return ((u.get("prompt_tokens", 0) - cached) * price["prompt"] + cached * price["input_cache_read"]
            + u.get("completion_tokens", 0) * price["completion"])


def session_cost(s: dict, price: dict) -> float:
    return sum(usage_cost(m.get("usage"), price) for m in s["messages"] if m["role"] == "assistant")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default=str(DEFAULT_SOURCE))
    ap.add_argument("--episodes", default="")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--session")
    ap.add_argument("--title")
    ap.add_argument("--retries", type=int, default=2)
    ap.add_argument("--repair-rounds", type=int, default=3, help="单集格式不过时自动返修的轮数")
    ap.add_argument("--budget-usd", type=float, default=45.0,
                    help="本会话累计花费上限（按实测 usage 计，含之前续跑的部分）；到了就不再接新的集")
    ap.add_argument("--report-every", type=int, default=10)
    ap.add_argument("--export-tag", help="结束后调用 tools/export_qwen_script.py --rules-tag <tag>")
    ap.add_argument("--registry-from", nargs="*", default=None,
                    help="继承登记来源（会话 id / 剧本 md，按顺序，先登记为准）；存进会话 registry_from")
    ap.add_argument("--no-inherit", action="store_true",
                    help="不逐集继承（允许并行）；默认按集号顺序写，epN 继承本会话 ep<N 的登记")
    a = ap.parse_args(argv)
    src = Path(a.source)
    episodes = S.split_episodes(src.read_text(encoding="utf-8"))
    todo = parse_range(a.episodes, sorted(episodes))
    s = S.load_session(a.session) if a.session else S.new_session(a.title or f"{src.stem} 按规则重写", independent=True)
    sid = s["id"]
    if a.registry_from is not None:
        for ref in a.registry_from:
            S.resolve_draft(ref)
        S.update_session(sid, lambda cur: cur.__setitem__("registry_from", a.registry_from))
        s["registry_from"] = a.registry_from
    reg_from = s.get("registry_from") or []

    def reg_for(n: int) -> dict:
        """epN 的继承登记：生产登记 + 登记来源 + 本会话 ep<N（逐集继承）"""
        return {"from": reg_from, "session": sid, "before": 0 if a.no_inherit else n}

    def vet(text: str, n: int, tag: str | None = None):
        return S.validate_episode_text(text, tag or f"ep{n:02d}", registry=reg_for(n))
    resume = {}   # 续跑：已写过但格式 / 台词对照还没过的集，从已有稿接着返修，不重写
    for n in [n for n in todo if str(n) in s["episodes"]]:
        rep0 = S.source_check(vet(s["episodes"][str(n)], n, f"r{n:02d}"), episodes[n],
                              s["episodes"][str(n)])
        if rep0 is None or any(i["level"] == "block" for i in rep0["issues"]) or any(
                i["level"] == "block" for sh in rep0["shots"] for i in sh["issues"]):
            resume[n] = s["episodes"][str(n)]
    todo = [n for n in todo if str(n) not in s["episodes"] or n in resume]
    print(f"会话 {sid}  待写 {len(todo)} 集  模型 {S.provider()['model']}", flush=True)
    print("原稿格式校验中…", flush=True)
    issues = source_issues(episodes, todo)
    lock = threading.Lock()
    price = model_price()
    spent = {"usd": session_cost(s, price), "done": 0, "passed": 0, "stopped": False, "split": 0, "trunc": 0}
    print(f"单价 {price}  本会话已花 ${spent['usd']:.2f}  预算 ${a.budget_usd:.2f}", flush=True)

    def charge(usage):
        """按实测 usage 累计花费；超过预算后不再接新的集 / 新的返修轮"""
        with lock:
            spent["usd"] += usage_cost(usage, price)
            if spent["usd"] >= a.budget_usd and not spent["stopped"]:
                spent["stopped"] = True
                print(f"[预算] 已花 ${spent['usd']:.2f} ≥ ${a.budget_usd:.2f}：不再接新的集，"
                      f"续跑：--session {sid}", flush=True)

    def over_budget() -> bool:
        with lock:
            return spent["stopped"]

    local = threading.local()   # 当前线程在写的集号（逐集继承：系统提示词全局头带 ep<N 的登记）

    def ask(user_msg: str, context: str, accept):
        """一次请求（不带历史：系统提示词按 context 挑附录 + 这一条消息）；网络错误 / 回复不合要求时重试"""
        cfg = S.load_config()
        cfg["registry"] = reg_for(getattr(local, "n", 0))
        system, parts = S.prompt_for(user_msg, context=context, cfg=cfg)
        skipped = [p["name"] for p in parts if "未带" in p["name"]]
        last = None
        for attempt in range(a.retries + 1):
            t0 = time.time()
            try:
                r = S.complete([{"role": "system", "content": system}, {"role": "user", "content": user_msg}])
            except Exception as e:  # noqa: BLE001
                last = str(e)
                print(f"  [请求失败] {last[:200]}", flush=True)
                time.sleep(10 * (attempt + 1))
                continue
            charge(r["usage"])
            if r["finish"] == "length":
                with lock:
                    spent["trunc"] += 1
            u = r["usage"] or {}
            print(f"  [用量] {user_msg[:14]!r}… prompt {u.get('prompt_tokens')} + 输出 {u.get('completion_tokens')} "
                  f"= {u.get('total_tokens')} token · finish={r['finish']}"
                  + (" · ⚠ 输出被截断" if r["finish"] == "length" else "")
                  + (f" · 预算不足未带：{'、'.join(skipped)}" if skipped else "") + f" · {time.time() - t0:.0f}s",
                  flush=True)
            if accept(r["content"]):
                return r, t0, None
            last = f"回复不合要求（finish={r['finish']}）"
        return None, None, last

    def record(n: int, user_msg: str, r: dict, t0: float, episode_text: str):
        """存档这一轮请求与回复；草稿里这一集换成 episode_text（整集回复或合并后的单镜返修）"""
        def apply(cur):
            cur["messages"].append({"role": "user", "content": user_msg, "episode": n,
                                    "at": time.strftime("%Y-%m-%dT%H:%M:%S")})
            S.record_reply(cur, r["content"], r["reasoning"], r["usage"], r["finish"], t0)
            cur["episodes"][str(n)] = episode_text
        with lock:
            S.update_session(sid, apply)   # 跨进程锁：返修工具 / 画布可能同时改这个会话

    def blocks_of(rep) -> int | None:
        if rep is None:
            return None
        return sum(i["level"] == "block" for i in rep["issues"]) + sum(
            i["level"] == "block" for sh in rep["shots"] for i in sh["issues"])

    def needs_split(user_msg: str, context: str) -> bool:
        _, parts = S.prompt_for(user_msg, context=context)
        lost = [p["name"] for p in parts if p.get("dropped")]   # 任何一节放不下都拆半：规则一条不丢
        if lost:
            with lock:
                spent["split"] += 1
            print(f"  [拆半] 有附录放不下：{'、'.join(lost)} → 原稿拆成两半分两次写", flush=True)
        return bool(lost)

    def write_split(n: int):
        head, shots, tail = S.split_shots(episodes[n])
        keys = sorted(shots)
        k = keys[(len(keys) + 1) // 2 - 1]
        first, second = [x for x in keys if x <= k], [x for x in keys if x > k]
        src_a = head + "".join(shots[x] for x in first)
        src_b = "".join(shots[x] for x in second) + tail
        msg_a = TASK_A.format(n=n, src=src.name, a=first[0], b=first[-1], c=second[0], d=second[-1],
                              issues=issues.get(n, ""), body=src_a, checklist=S.dialogue_checklist(src_a))
        r, t0, err = ask(msg_a, src_a, lambda c: n in S.split_episodes(c)
                         and all(x in S.split_shots(S.split_episodes(c)[n])[1] for x in first))
        if r is None:
            return None, f"前半：{err}"
        part_a = S.split_episodes(r["content"])[n]
        record(n, msg_a, r, t0, part_a)
        head_a = S.split_shots(part_a)[0].strip()
        msg_b = TASK_B.format(n=n, src=src.name, c=second[0], d=second[-1], head=head_a,
                              issues=issues.get(n, ""), body=src_b,
                              checklist=S.dialogue_checklist(head + src_b))
        r, t0, err = ask(msg_b, src_b, lambda c: all(x in S.split_shots(S.unwrap(c))[1] for x in second))
        if r is None:
            return None, f"后半：{err}"
        got = S.split_shots(S.unwrap(r["content"]))[1]
        text = part_a.rstrip() + "\n\n" + "\n".join(got[x].rstrip() + "\n" for x in second)
        record(n, msg_b, r, t0, text)
        return text, None

    def one(n: int):
        local.n = n
        if over_budget():
            return n, "跳过（预算已到）"
        msg = TASK.format(n=n, src=src.name, body=episodes[n], issues=issues.get(n, ""),
                          checklist=S.dialogue_checklist(episodes[n]))
        t_start, rounds = time.time(), 0
        if n in resume:
            text = resume[n]
            print(f"  [续跑] ep{n:02d} 从已有稿接着返修", flush=True)
        elif needs_split(msg, episodes[n]):
            text, err = write_split(n)
            if text is None:
                return n, f"失败（分两半）：{err}"
        else:
            r, t0, err = ask(msg, episodes[n], lambda c: n in S.split_episodes(c))
            if r is None:
                return n, f"失败：{err}"
            text = S.split_episodes(r["content"])[n]
            record(n, msg, r, t0, text)
        rep = S.source_check(vet(text, n), episodes[n], text)
        while blocks_of(rep) and rounds < a.repair_rounds and not over_budget():
            rounds += 1
            mr = S.missing_lines_repair(episodes[n], text) if any(
                i["rule_id"] == "SRC-D1" for i in rep["issues"]) else None
            if mr:   # 缺台词：只发缺的句子 + 原稿前后文 + 当前稿相关几镜，换回那几镜（总调度 2026-10-30）
                rmsg, sa, sb = mr
                r, t0, err = ask(rmsg, rmsg, lambda c, sa=sa: S.splice_reply_ok(c, sa))
                if r is not None:
                    text = S.splice_shots(text, sa, sb, r["content"])
                    record(n, rmsg, r, t0, text)
                rep = S.source_check(vet(text, n), episodes[n], text)
                # 封板修复：补完台词后同一轮接着修格式（之前直接进入下一轮，ep03 三轮都只在补台词，H3-A4 / H3-D7 一次没修）
                # 还有问题（包括台词仍没逐字对上，如 ep03 把“这个”写成“的”）就接着走整集 / 单镜返修，
                # 整集返修消息同时列出缺句与全部格式问题
                if not blocks_of(rep):
                    continue
            ep_level = [i for i in rep["issues"] if i["level"] == "block"] + [   # 拆镜 / 挪台词要整集重写
                i for sh in rep["shots"] for i in sh["issues"] if i["level"] == "block" and i["rule_id"] in S.EPISODE_RULES]
            bad_shots = [sh for sh in rep["shots"] if not sh["ok"]]
            if ep_level or not bad_shots:   # 集级问题（集头、镜数、总时长）：整集返修，只带当前稿 + 报告
                rmsg = (f"【当前稿 ep{n:02d}】\n{text}\n\n" + S.episode_repair_text(rep)
                        + "\n\n" + S.dialogue_checklist(episodes[n]))   # 封板修复：整集返修也附台词清单
                r, t0, err = ask(rmsg, text, lambda c: n in S.split_episodes(c))
                if r is None:
                    return n, f"返修失败：{err}"
                text = S.split_episodes(r["content"])[n]
                record(n, rmsg, r, t0, text)
            else:                           # 单镜返修：只带这一镜 + 它的校验报告
                _, shots, _ = S.split_shots(text)
                for sh in bad_shots:
                    k = sh["index"]
                    if k not in shots:
                        continue
                    rmsg = (f"【当前稿 ep{n:02d} 镜{k}】\n{shots[k]}\n{S.shot_repair_text(sh)}\n"
                            f"只输出修正后的镜{k}：从 `**镜{k}｜img**` 到 `**H3提示词**` 代码块结束。")
                    r, t0, err = ask(rmsg, shots[k], lambda c, k=k: k in S.split_shots(S.unwrap(c))[1])
                    if r is None:
                        continue
                    try:
                        text = S.merge_shot(text, k, r["content"])
                    except ValueError:
                        continue
                    record(n, rmsg, r, t0, text)
            rep = S.source_check(vet(text, n), episodes[n], text)
        return n, f"ok {time.time() - t_start:.0f}s 返修{rounds}轮 block={blocks_of(rep)}"

    workers = a.workers if a.no_inherit else 1   # 逐集继承：按集号顺序一集一集写，写完的集登记并进下一集
    if not a.no_inherit:
        todo = sorted(todo)
        print(f"逐集继承：按集号顺序写（workers=1），登记来源 {reg_from or '无'} + 生产登记 + 本会话前面各集", flush=True)
    with ThreadPoolExecutor(workers) as ex:
        for f in as_completed([ex.submit(one, n) for n in todo]):
            n, msg = f.result()
            print(f"ep{n:02d} {msg}", flush=True)
            if msg.startswith("ok"):
                spent["done"] += 1
                spent["passed"] += msg.endswith("block=0")
                if spent["done"] % a.report_every == 0:
                    print(f"[进度] 完成 {spent['done']} 集 · 格式全过 {spent['passed']} 集 · 拆半 {spent['split']} 集 · "
                          f"截断 {spent['trunc']} 次 · 累计花费 "
                          f"${spent['usd']:.2f}", flush=True)
    print(f"[结束] 完成 {spent['done']} 集 · 格式全过 {spent['passed']} 集 · 拆半 {spent['split']} 集 · "
          f"截断 {spent['trunc']} 次 · 累计花费 ${spent['usd']:.2f}"
          + ("（预算停止，可续跑）" if spent["stopped"] else ""), flush=True)

    s = S.load_session(sid)
    v = S.validate_draft(s)
    # 封板修复：只把校验结果写回（加锁、重新读入），不用整份旧会话覆盖——别的进程可能刚写入了新的集
    S.update_session(sid, lambda cur: cur.__setitem__("validation", s.get("validation")))
    if v and "error" not in v:
        print(f"草稿 {v['draft']}  集数 {len(v['episodes'])}  block {v['blocking']}  warn {v['warnings']}")
        for e in v["episodes"]:
            if e["blocking"]:
                print(f"  ep{e['number']:02d} block {e['blocking']}")
    else:
        print("校验失败：", v)
    print(f"画布：#/script-chat/{sid}")
    if a.export_tag and v and "error" not in v:   # fredw-92 的导出：每集 + 全本复制到 为他而骚短剧/Qwen剧本/
        import subprocess
        r = subprocess.run([sys.executable, str(REPO / "tools" / "export_qwen_script.py"), str(REPO / v["draft"]),
                            "--rules-tag", a.export_tag], capture_output=True, cwd=REPO,
                           env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8"})
        print("[导出]", (r.stdout or b"").decode("utf-8", "replace")[-800:],
              (r.stderr or b"").decode("utf-8", "replace")[-400:], flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
