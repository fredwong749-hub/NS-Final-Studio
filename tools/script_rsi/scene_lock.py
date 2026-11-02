"""场景定稿行 + 衔接点 + 不重复描述环境（K-WRT-H23 / H24 / H25；总调度 11-02，docs/master/CONSISTENCY_PLAN.md §3 写作层）。

集头（**配乐** 前）每个场景一行：
  **场景定稿｜<场景id>**：陈设=A、B、C｜主光=<方案名或动机光源（方位）>｜站位=<名>：<左/中/右>·<姿态>；…｜屏幕方向=<谁在哪侧、面朝哪边>
判：
  H23 每个用到的场景都有定稿行且四个字段齐；同框 ≥2 人（在画或局部入画）的镜，人物行里的左右顺序和定稿行一致（不越轴；本镜或之前同场某镜 **衔接** 写了
      “承：动作｜<名>移到<侧>” 的，从那镜起按新位置）；【灯光】用同一方案名或含同一动机光源。
  H24 同场换机位 / 接力镜的 **衔接** “承：”只用 视线 / 动作 / 声音，且后面有内容。
  H25 同一场里，img 里不带人名的环境分句（含 光 / 灯 / 窗 / 墙 / 背景 / 虚化 / 霓虹 / 光斑 …）和本场前面某镜的环境分句二字片段重合 ≥ 0.6 = 重复描述环境。
导出：export → <run>/continuity/scene_locks_epNN.json（IMGMASTER continuity 从这里读）。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LOCK_RE = re.compile(r"^\*\*场景定稿｜(sk_[a-z0-9_]+)\*\*[：:]\s*(.+)$")
FIELDS = ("陈设", "主光", "站位", "屏幕方向")
SIDES = {"左": 0, "中": 1, "右": 2}
LINK_OK = ("视线", "动作", "声音", "位置")      # “位置”= 上一镜动作的落点（K-WRT-H20 拆镜：下一镜人已到位），按动作类衔接算
ENV_WORDS = re.compile(r"光|灯|窗|墙|背景|虚化|霓虹|光斑|夜色|天色|地板|地面|走廊|楼道|街")
MOVE_RE = re.compile(r"([^\s；;，,｜]+?)(?:移到|换到|走到|坐到)([左中右])")


def parse_locks(text: str) -> dict:
    """集头文本 → {场景id: {"陈设": [...], "主光": str, "站位": {名: {"side": 左/中/右, "pose": str}}, "屏幕方向": str, "missing": [...]}}"""
    out = {}
    for ln in text.split("\n"):
        m = LOCK_RE.match(ln.strip())
        if not m:
            continue
        sid, body = m.group(1), m.group(2)
        f = {}
        for part in body.split("｜"):
            if "=" in part:
                k, v = part.split("=", 1)
                f[k.strip()] = v.strip()
        stand = {}
        for item in re.split(r"[；;]", f.get("站位", "")):
            if "：" in item or ":" in item:
                name, rest = re.split(r"[：:]", item, maxsplit=1)
                side = next((s for s in SIDES if rest.strip().startswith(s)), None)
                stand[name.strip()] = {"side": side, "pose": rest.strip()[1:].lstrip("·").strip() if side else rest.strip()}
        out[sid] = {"陈设": [x.strip() for x in re.split(r"[、，,]", f.get("陈设", "")) if x.strip()], "主光": f.get("主光", ""),
                    "站位": stand, "屏幕方向": f.get("屏幕方向", ""), "missing": [k for k in FIELDS if not f.get(k)]}
    return out


def _field(block: str, label: str) -> str:
    return next((ln.split("：", 1)[1].strip() for ln in block.split("\n") if ln.startswith(f"**{label}**：")), "")


def _img(block: str) -> str:
    return next((ln.split("：", 1)[1] for ln in block.split("\n") if re.match(r"^\*\*镜\d+｜img\*\*", ln)), "")


def _bigrams(t: str) -> set:
    t = re.sub(r"[\s，。；、：|｜（）()“”\"*]", "", t)
    return {t[i:i + 2] for i in range(len(t) - 1)}


def check_episode(head: str, shots: list, blocks: list, scene_ids: list | None = None, names: list | None = None) -> dict:
    """→ {"H23": (ok, why), "H24": (ok, why), "H25": (ok, why)}；shots 要有 index / scene_id / cast（name, presence, x）"""
    locks = parse_locks(head)
    used = scene_ids or sorted({s.scene_id for s in shots if getattr(s, "scene_id", None)})
    h23 = [f"{sid} 没有场景定稿行" for sid in used if sid not in locks]
    h23 += [f"{sid} 定稿行缺 {'、'.join(v['missing'])}" for sid, v in locks.items() if v["missing"]]
    h24, h25 = [], []
    cur_side, env_seen = {}, {}
    for s, b in zip(shots, blocks):
        sid = getattr(s, "scene_id", None)
        lk = locks.get(sid)
        link = _field(b, "衔接")
        if sid not in cur_side and lk:
            cur_side[sid] = {n: v["side"] for n, v in lk["站位"].items()}
        mv = re.search(r"承[：:]\s*动作｜(.*)", link)
        for m in MOVE_RE.finditer(mv.group(1) if mv else ""):
            nm = next((n for n in (cur_side.get(sid) or {}) if n in m.group(1)), None)
            if nm:
                cur_side[sid][nm] = m.group(2)
        # H23：不越轴 + 主光一致
        if lk:
            # 局部入画（过肩前景的肩 / 背影 / 手）也占画面一侧，同样算越轴（总调度 11-02：ep03 镜10 过肩镜左右对调漏判）
            on = [(c.name, getattr(c, "x", None)) for c in (s.cast or []) if c.presence in ("在画", "局部") and getattr(c, "x", None) in SIDES]
            locked = cur_side.get(sid) or {}
            pairs = [(a, b2) for i, a in enumerate(on) for b2 in on[i + 1:] if a[0] in locked and b2[0] in locked
                     and locked[a[0]] and locked[b2[0]] and locked[a[0]] != locked[b2[0]]]
            for (n1, x1), (n2, x2) in pairs:
                want = SIDES[locked[n1]] < SIDES[locked[n2]]
                got = SIDES[x1] < SIDES[x2] if x1 != x2 else None
                if got is not None and got != want:
                    h23.append(f"镜{s.index}：{n1}（{x1}）和 {n2}（{x2}）左右和定稿行相反（越轴）")
            lt = _field(b, "灯光")
            key = lk["主光"]
            scheme = re.sub(r"（.*", "", key).strip()
            if lt and key and not (scheme and scheme in lt) and not any(len(w) >= 2 and w in lt for w in re.split(r"[，、（）()\s]", key)):
                h23.append(f"镜{s.index}：【灯光】和定稿行主光“{key[:20]}”对不上")
        # H24：衔接点
        if link.startswith(("同场换机位", "接力")):
            m = re.search(r"承[：:]\s*([^｜]*)｜?(.*)", link)
            kind, cue = (m.group(1).strip(), m.group(2).strip()) if m else ("", "")
            if kind not in LINK_OK or not cue:
                h24.append(f"镜{s.index}“{link[:24]}”")
        # H25：重复描述环境
        cast_names = [c.name for c in (s.cast or [])] + list(names or [])
        envs = [c for c in re.split(r"[，。；]", _img(b)) if c.strip() and ENV_WORDS.search(c) and not any(n and n in c for n in cast_names)]
        prev = env_seen.setdefault(sid, [])
        for c in envs:
            bc = _bigrams(c)
            if any(len(bc & p) / max(1, len(bc | p)) >= 0.6 for p in prev):
                h25.append(f"镜{s.index}“{c.strip()[:20]}”")
                break
        prev.extend(_bigrams(c) for c in envs)
    return {"H23": (not h23, f"场景定稿问题：{h23[:8] or '无'}"), "H24": (not h24, f"衔接点不是 视线 / 动作 / 声音 或没写内容：{h24[:8] or '无'}"),
            "H25": (not h25, f"重复描述环境的镜：{h25[:8] or '无'}")}


def export(run_dir: Path, ep: int) -> Path:
    """→ <run>/continuity/scene_locks_epNN.json：{episode, scenes: {sid: {fixtures, key_light, blocking, screen_direction, shots}}, links: [...]}"""
    L3 = _load("line3_score", "tools/script_rsi/line3_score.py")
    pre, chunk = L3.best_chunk(run_dir, ep)
    H, RL = L3.H, L3.RL
    wd = run_dir / f"work_ep{ep:02d}"
    wd.mkdir(exist_ok=True)
    obj = H.episode_obj(pre, chunk, ep, wd)
    shots = sorted(obj.shots, key=lambda q: q.index)
    blocks = [RL.block_text(chunk, k) for k in range(len(shots))]
    locks = parse_locks(RL.block_text(chunk, "head"))
    scenes = {sid: {"fixtures": v["陈设"], "key_light": v["主光"], "blocking": v["站位"], "screen_direction": v["屏幕方向"],
                    "shots": [s.index for s in shots if s.scene_id == sid]} for sid, v in locks.items()}
    links = []
    for s, b in zip(shots, blocks):
        link = _field(b, "衔接")
        m = re.search(r"^([^｜]*)｜?承[：:]\s*([^｜]*)｜?(.*)", link)
        links.append({"shot": s.index, "transition": (m.group(1) if m else link).strip(), "cue_type": (m.group(2).strip() if m else ""),
                      "cue": (m.group(3).strip() if m else "")})
    out = run_dir / "continuity" / f"scene_locks_ep{ep:02d}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"schema": "nsfs.scene_locks/1", "run": run_dir.name, "episode": ep, "scenes": scenes, "links": links},
                              ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(out)
    return out


def _load(name, rel):
    import importlib.util
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("export")
    e.add_argument("--run-dir", required=True)
    e.add_argument("--episodes", default="1-10")
    c = sub.add_parser("check", help="写手自检：对一份稿（整集稿 writer_out/P4_epNN_rK.md 或 final.md）跑 H23–H25 + v3_checks")
    c.add_argument("--file", required=True)
    c.add_argument("--episode", type=int, required=True)
    a = ap.parse_args(argv)
    if a.cmd == "check":
        L3 = _load("line3_score", "tools/script_rsi/line3_score.py")
        f = Path(a.file) if Path(a.file).is_absolute() else ROOT / a.file
        t = f.read_text(encoding="utf-8")
        if f.name.endswith(".final.md"):
            pre, chunks = L3.RL.split_doc(t)
            chunk = chunks[0]
        else:
            from ns_api import script_chat as SC
            pre = SC.script_header(registry={})[0] + "\n---\n\n"
            chunk = (t[t.find("## ep"):] if "## ep" in t else t).rstrip() + "\n\n---\n"
        wd = ROOT / "data" / "rsi" / "_scene_check" / f"ep{a.episode:02d}"
        wd.mkdir(parents=True, exist_ok=True)
        obj = L3.H.episode_obj(pre, chunk, a.episode, wd)
        sh = sorted(obj.shots, key=lambda q: q.index)
        bl = [L3.RL.block_text(chunk, k) for k in range(len(sh))]
        res = {**{k: v for k, v in check_episode(L3.RL.block_text(chunk, "head"), sh, bl).items()},
               **{f"v3#{k}": v for k, v in L3.RC6.v3_checks(sh, bl).items()},
               **{f"k211#{k}": v for k, v in L3.RC6.mirror_hand_checks(sh, bl).items()}}
        for k, (ok, why) in res.items():
            print(("OK  " if ok else "FAIL"), k, why)
        return 0 if all(ok for ok, _w in res.values()) else 1
    run_dir = Path(a.run_dir) if Path(a.run_dir).is_absolute() else ROOT / a.run_dir
    L3 = _load("line3_score", "tools/script_rsi/line3_score.py")
    for ep in sorted(L3.H.RL.parse_episodes(a.episodes)):
        print(str(export(run_dir, ep).relative_to(ROOT)).replace(chr(92), "/"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
