"""
对剧本创作会话里已写好的某一集再做一次格式返修（只返修校验不过的镜 / 集头），结果并回同一会话草稿。
用于批量返修轮数用完后仍有 block 的集，或返修提示（REPAIR_HINTS）更新后补跑。只查格式，不改内容判断。

    .venv\\Scripts\\python.exe tools\\script_chat_repair.py <会话id> <集号> [--rounds 2]
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "services" / "api")]
from ns_api import script_chat as S  # noqa: E402


def blocks(rep) -> int:
    return sum(i["level"] == "block" for i in rep["issues"]) + sum(
        i["level"] == "block" for sh in rep["shots"] for i in sh["issues"])


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("session")
    ap.add_argument("episode", type=int)
    ap.add_argument("--rounds", type=int, default=2)
    ap.add_argument("--source", default=str(REPO / "data" / "staging_v3" / "为他而骚 （剧本和镜头）v3.1.md"),
                    help="原稿（核对台词 / 独白逐字保留，SRC-D1）")
    a = ap.parse_args(argv)
    n = a.episode
    src_ep = S.split_episodes(Path(a.source).read_text(encoding="utf-8")).get(n, "")
    s = S.load_session(a.session)
    text = s["episodes"][str(n)]
    rep = S.source_check(S.validate_episode_text(text, f"ep{n:02d}"), src_ep, text)
    print(f"ep{n:02d} 返修前 block={blocks(rep)}", flush=True)
    for _ in range(a.rounds):
        if not blocks(rep):
            break
        mr = S.missing_lines_repair(src_ep, text) if any(i["rule_id"] == "SRC-D1" for i in rep["issues"]) else None
        if mr:   # 缺台词：只发缺句 + 原稿前后文 + 当前稿相关几镜，换回那几镜
            targets = [(mr[0], mr[0], lambda c, sa=mr[1]: S.splice_reply_ok(c, sa), ("splice", mr[1], mr[2]))]
        elif any(i["level"] == "block" for i in rep["issues"]) or any(
                i["level"] == "block" and i["rule_id"] in S.EPISODE_RULES for sh in rep["shots"] for i in sh["issues"]):
            msg = (f"【当前稿 ep{n:02d}】\n{text}\n\n" + S.episode_repair_text(rep)
                   + "\n\n" + S.dialogue_checklist(src_ep))   # 封板修复：整集返修也附台词清单
            targets = [(msg, text, lambda c: n in S.split_episodes(c), None)]
        else:
            _, shots, _ = S.split_shots(text)
            targets = [(f"【当前稿 ep{n:02d} 镜{sh['index']}】\n{shots[sh['index']]}\n{S.shot_repair_text(sh)}\n"
                        f"只输出修正后的镜{sh['index']}：从 `**镜{sh['index']}｜img**` 到 `**H3提示词**` 代码块结束。",
                        shots[sh['index']], lambda c, k=sh["index"]: k in S.split_shots(S.unwrap(c))[1], sh["index"])
                       for sh in rep["shots"] if not sh["ok"] and sh["index"] in shots]
        for msg, ctx, ok, k in targets:
            system, _ = S.prompt_for(msg, context=ctx)
            t0 = time.time()
            r = None
            for attempt in range(4):   # Qwen 服务重启 / 连接被重置时重试
                try:
                    r = S.complete([{"role": "system", "content": system}, {"role": "user", "content": msg}])
                    break
                except S.ChatError as e:
                    print(f"  [请求失败，{30 * (attempt + 1)} 秒后重试] {e}", flush=True)
                    time.sleep(30 * (attempt + 1))
            if r is None:
                continue
            u = r["usage"] or {}
            print(f"  [用量] prompt {u.get('prompt_tokens')} + 输出 {u.get('completion_tokens')} · finish={r['finish']} "
                  f"· {time.time() - t0:.0f}s", flush=True)
            if not ok(r["content"]):
                continue
            if isinstance(k, tuple):
                text = S.splice_shots(text, k[1], k[2], r["content"])
            else:
                text = S.split_episodes(r["content"])[n] if k is None else S.merge_shot(text, k, r["content"])
            def apply(s, msg=msg, r=r, t0=t0, text=text):
                s["messages"].append({"role": "user", "content": msg, "episode": n,
                                      "at": time.strftime("%Y-%m-%dT%H:%M:%S")})
                S.record_reply(s, r["content"], r["reasoning"], r["usage"], r["finish"], t0)
                s["episodes"][str(n)] = text
            S.update_session(a.session, apply)   # 跨进程锁：批量可能同时在写同一会话
        rep = S.source_check(S.validate_episode_text(text, f"ep{n:02d}"), src_ep, text)
        print(f"ep{n:02d} 本轮后 block={blocks(rep)}", flush=True)
    s = S.load_session(a.session)
    v = S.validate_draft(s)
    # 封板修复：只写回校验结果（加锁重读），不用旧会话整份覆盖
    S.update_session(a.session, lambda cur: cur.__setitem__("validation", s.get("validation")))
    print(f"草稿 {v['draft']}  block {v['blocking']}  warn {v['warnings']}")
    return 0 if not v["blocking"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
