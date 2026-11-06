"""开项目确认单（L-215 / L-216，W-KICKOFF 11-07，PLAN_5H 块 J）。

L-215：项目方一个人管所有项目——他的参与全部前置到“开项目”（素材 / 角色 / 造型 / 场景 / 画风 / 声音 / 成人镜授权 / 代选规则 / 兜底规则一次确认完）；
开工后流水线不再有任何“等项目方”的环节，出问题按开工前定好的规则自动兜底，事后汇报。
L-216：已授权的类别不回头确认；成人镜项目级常设授权——本剧与以后新剧开工即授权（确认单默认“全部授权”），新出现的成人镜由系统自动写入触发清单。

本模块：
  · policy(run)            → 本剧开工规则（config/pipeline/kickoff.json defaults ⊕ runs[run].policy；缺省 = 零等待）
  · sync_adult(run)        → adult_authorization=all 时把导入稿里还没进触发清单的成人镜对象（只按 id / 标记）经 adult_trigger.apply 写入
                             （by="项目方（开项目常设授权 L-216）"，via="kickoff"，先审计后原子写；只加不减）。不看、不描述、不出任何成人内容
  · checklist(run)         → 开项目确认单（markdown，总调度在对话里带项目方逐项过）：来源 P1 + 资产包清单
  · record(run, answers)   → 把项目方的答复记进 kickoff.json（policy 项改规则，其余原话留档）
CLI：
  kickoff.py checklist   --run series10_v2 [--out docs/...md]
  kickoff.py record      --run series10_v2 --set look_confirm=auto --set characters=确认 --by 项目方 --quote "原话"
  kickoff.py sync-adult  [--run series10_v2] [--dry] [--no-push]
  kickoff.py policy      --run series10_v2
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CFG_REL = Path("config") / "pipeline" / "kickoff.json"
ADULT_BY = "项目方（开项目常设授权 L-216）"
ADULT_NOTE = "开项目常设授权（L-215/L-216）：导入稿新出现的成人镜自动入触发清单（只记对象 id）"
DEFAULTS = {"adult_authorization": "all", "look_confirm": "auto", "picks": "delegate_always", "asset_failure": "best_effort",
            "review_needed": "never_blocks", "asset_revise": "notice"}
CHOICES = {"adult_authorization": ("all", "none"), "look_confirm": ("auto", "ask"), "picks": ("delegate_always", "expire"),
           "asset_failure": ("best_effort", "ask"), "review_needed": ("never_blocks",), "asset_revise": ("notice", "card")}
LIVE_STATUSES = ("producing", "preparing")


# ------------------------------------------------------------------ 读写
def cfg_path(root: Path | None = None) -> Path:
    return Path(root or ROOT) / CFG_REL


def load(root: Path | None = None) -> dict:
    try:
        d = json.loads(cfg_path(root).read_text(encoding="utf-8"))
    except FileNotFoundError:   # arch-ok: 没有确认单 = 旧行为（configured() 为 False，各模块不改规则）
        return {}
    except ValueError as e:     # 坏文件不静默：按默认（零等待）走，同时把原因带出去
        return {"_error": f"kickoff.json 读不出：{e}"[:200]}
    return d if isinstance(d, dict) else {}


def _atomic_json(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=p.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(obj, ensure_ascii=False, indent=1) + "\n")
        for i in range(8):
            try:
                os.replace(tmp, p)
                return
            except PermissionError:     # Windows：读者占着文件时重试
                time.sleep(0.1 * (i + 1))
        os.replace(tmp, p)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _runs():
    """tools/autopilot/runs.py（只在第一次把目录放进 sys.path；常驻 API 进程每拍都调，不能让 sys.path 无限变长）"""
    ap = str(ROOT / "tools" / "autopilot")
    if ap not in sys.path:
        sys.path.insert(0, ap)
    import runs as RN  # noqa: PLC0415
    return RN


def _current_run(root: Path | None = None) -> str:
    RN = _runs()
    return RN.primary_run(Path(root or ROOT))


def policy(run: str | None = None, root: Path | None = None) -> dict:
    """本剧开工规则：代码默认 ⊕ kickoff.json defaults ⊕ runs[run].policy（不认识的值回落默认）"""
    d = load(root)
    run = run or _current_run(root)
    out = dict(DEFAULTS)
    for src in (d.get("defaults") or {}, ((d.get("runs") or {}).get(run) or {}).get("policy") or {}):
        for k, v in src.items():
            if k in CHOICES and v in CHOICES[k]:
                out[k] = v
    return out


def configured(root: Path | None = None) -> bool:
    """这个仓库有开项目确认单（config/pipeline/kickoff.json）。没有 = 旧行为（各模块的老测试 / 临时根目录不受影响）"""
    return cfg_path(root).is_file()


def is_on(key: str, run: str | None = None, root: Path | None = None) -> bool:
    """这条零等待规则对本剧开着没（有确认单且值 = 默认零等待那一档）"""
    if not configured(root):
        return False
    try:
        return policy(run, root).get(key) == DEFAULTS[key]
    except Exception:  # noqa: BLE001  # arch-ok: 读不到剧目表 = 按默认零等待（L-215）
        return True


# ------------------------------------------------------------------ 成人镜常设授权（L-216）
def _adult_mod():
    sp = str(ROOT / "services" / "api")
    if sp not in sys.path:
        sys.path.insert(0, sp)
    from ns_api import adult_trigger as AT  # noqa: PLC0415
    return AT


def script_adult_shots(run: str, root: Path | None = None, AT=None) -> dict[str, dict]:
    """常设授权只认导入稿里写了 shot.adult 的镜（PS-MASTER 11-07）——不含 adult_trigger.adult_shots 里
    “出图前检查因成人画面资产被拦”的登记表镜（那些是普通镜碰到了成人资产，要项目方本人看）"""
    AT = AT or _adult_mod()
    try:
        sc = json.loads(Path(AT.script_path(run, root)).read_text(encoding="utf-8"))
    except FileNotFoundError:   # arch-ok: 还没有导入稿 = 没有成人镜
        return {}
    out: dict[str, dict] = {}
    for E in sc.get("episodes") or []:
        for S in E.get("shots") or []:
            if not S.get("adult"):
                continue
            try:
                ep, idx = int(S.get("episode") or E.get("number")), int(S.get("index"))
            except (TypeError, ValueError):
                continue
            out[f"ep{ep:02d}-S{idx}"] = {"ep": ep, "index": idx}
    return out


def untriggered_adult(run: str, root: Path | None = None, AT=None) -> list[str]:
    """导入稿 shot.adult 镜里还没进触发清单的对象 id（首帧 / 尾帧 / 视频；只看 id 和标记）"""
    AT = AT or _adult_mod()
    trig = AT.triggered(run, root)
    shots = script_adult_shots(run, root, AT)
    want = [f"{k}:{sid}" for sid, _m in sorted(shots.items(), key=lambda kv: (kv[1]["ep"], kv[1]["index"])) for k in AT.KINDS]
    return [o for o in want if o not in trig]


def sync_adult(run: str | None = None, root: Path | None = None, dry: bool = False, push: bool = True, AT=None) -> dict:
    """adult_authorization=all → 新成人镜对象自动写进触发清单（adult_trigger.apply：先审计后原子写，只加不减）"""
    run = run or _current_run(root)
    if not configured(root) or policy(run, root).get("adult_authorization") != "all":
        return {"run": run, "skipped": "本剧开项目没授权成人镜（adult_authorization≠all）", "added": []}
    AT = AT or _adult_mod()
    todo = untriggered_adult(run, root, AT)
    if not todo or dry:
        return {"run": run, "added": [], "would_add": todo if dry else [], "dry": dry}
    res = AT.apply(run, todo, ADULT_BY, ADULT_NOTE, root, via="kickoff")
    if res.get("added") and push:
        AT.push_now(root)
    return {"run": run, **res}


def live_runs(root: Path | None = None) -> list[str]:
    RN = _runs()
    r = Path(root or ROOT)
    return [k for st in LIVE_STATUSES for k in RN.list_runs(r, status=st)]


def sync_adult_all(root: Path | None = None, push: bool = True) -> list[dict]:
    """每部在产 / 准备中的剧各同步一次（owner_delegate.tick 每拍调；导入后 import_events 也调）"""
    out = []
    for run in live_runs(root):
        try:
            out.append(sync_adult(run, root, push=push))
        except Exception as e:  # noqa: BLE001  # arch-ok: 一部剧出错不拖累别的剧，原因带回调用方记日志
            out.append({"run": run, "error": f"{type(e).__name__}: {e}"[:200]})
    return out


# ------------------------------------------------------------------ 开项目确认单
def _read(p: Path, d):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):   # arch-ok: 确认单是给人看的汇总：缺文件就写“还没有”
        return d


def _sources(run: str, root: Path) -> tuple[dict, list, dict, dict]:
    RN = _runs()
    rd = Path(RN.run_dir(run, root))
    story = _read(rd / "P1_storyline.json", {}) or {}
    looks = _read(rd / "P1_looks.json", []) or []
    mp = RN.asset_manifest(run, root)
    man = _read(Path(mp), {}) if mp else {}
    voices = _read(root / "config" / "voices_v2.json", {}) or {}
    return story, looks if isinstance(looks, list) else [], man or {}, voices


def checklist(run: str | None = None, root: Path | None = None, AT=None) -> str:
    r = Path(root or ROOT)
    run = run or _current_run(r)
    story, looks, man, voices = _sources(run, r)
    pol = policy(run, r)
    rec = (load(r).get("runs") or {}).get(run) or {}
    mc = man.get("characters") or {}
    L = [f"# 开项目确认单：{story.get('title') or run}（{run}）", "",
         "> L-215：项目方的确认全部在开项目时做完；开工后系统不再等你，出问题按下面定好的规则自动兜底，事后汇报。",
         "> 总调度在对话里逐项念给项目方听；项目方说“可以 / 改成……”，用 `kickoff.py record` 记原话。", ""]
    if rec.get("confirmed_at"):
        L += [f"上次确认：{rec['confirmed_at']}（{rec.get('by') or '项目方'}）", ""]
    L += ["## 1. 角色与身份脸", "", "| 角色 | 年龄 | 身份脸 | 要你确认 |", "|---|---|---|---|"]
    for c in story.get("characters") or []:
        cid = c.get("char_id")
        has = bool((mc.get(cid) or {}).get("face"))
        L.append(f"| {c.get('name')}（{c.get('role') or ''}） | {c.get('age') or ''} | {'已登记' if has else '还没有'} | 长相描述 / 身份脸对不对 |")
    L += ["", "## 2. 造型（每集穿什么）", "", "| 角色 | 造型 | 设定图 | 用在哪几集 |", "|---|---|---|---|"]
    for lk in looks:
        cid = lk.get("char_id")
        reg = (mc.get(cid) or {}).get("looks") or {}
        sched = {str(s.get("episode")): s.get("outfit") for s in lk.get("schedule") or [] if s.get("episode")}
        for one in lk.get("looks") or []:
            lid = one.get("id")
            adult = bool((reg.get(lid) or {}).get("adult"))
            eps = "、".join(f"ep{int(e):02d}" for e, o in sorted(sched.items(), key=lambda kv: int(kv[0])) if lid in str(o).split("+")) or "按 P1 用途"
            sheet = "已登记" if (reg.get(lid) or {}).get("sheet") else "还没有"
            L.append(f"| {lk.get('name')} | {lid}{'（私密，不显示）' if adult else ''} | {sheet} | {eps} |")
    L += ["", f"规则：look_confirm = **{pol['look_confirm']}**（auto = 开工后每集造型按 P1 排期 / 逐镜登记自动确认，不再逐集问你）", ""]
    scenes = story.get("scenes") or []
    ms = man.get("scenes") or {}
    L += ["## 3. 场景", "", "| 场景 | 底图 |", "|---|---|"]
    L += [f"| {s.get('name')}（{s.get('scene_id')}） | {'已登记' if (ms.get(s.get('scene_id')) or {}).get('base') else '还没有'} |" for s in scenes]
    L += ["", "## 4. 画风", "", "- 时尚大片画风（L-127）：去塑料、不磨皮、徕卡锐利、浓郁艳丽；好莱坞镜头语言（虚化、机位一致、动机运镜）。确认或补一句你想要的。", ""]
    roles = voices.get("roles") or {}
    L += ["## 5. 声音与音乐", "", "| 角色 | 音色 |", "|---|---|"]
    L += [f"| {k} | {'已选定 ' + str(v.get('selected')) if isinstance(v, dict) and v.get('selected') else '还没选（开工后代选）'} |" for k, v in roles.items()]
    L += ["", "- 配乐：按剧情段落自动配；有指定曲风请现在说。", ""]
    try:
        AT = AT or _adult_mod()
        shots = script_adult_shots(run, r, AT)
        trig = AT.triggered(run, r)
    except Exception as e:  # noqa: BLE001  # arch-ok: 读不到成人镜清单就在确认单里写明，不挡整张单
        shots, trig = {}, set()
        L.append(f"（成人镜清单读不到：{type(e).__name__}）")
    per_ep: dict[int, int] = {}
    for _sid, m in shots.items():
        per_ep[m["ep"]] = per_ep.get(m["ep"], 0) + 1
    pending = sum(1 for sid in shots if f"first:{sid}" not in trig)
    L += ["## 6. 成人镜授权（L-216）", "",
          f"- 现在导入稿里 {len(shots)} 镜带成人标记（" + "、".join(f"ep{e:02d} {n} 镜" for e, n in sorted(per_ep.items())) + f"）；其中 {pending} 镜还没进触发清单。",
          f"- 默认：**全部授权（{pol['adult_authorization']}）**——本剧以后新导入的成人镜由系统自动写进触发清单，只在自有机器（gpu33 / gpu36 / 笔记本）出，不再问你。",
          "- 改成 none = 每个成人镜仍要你在网页“出这一镜”。", ""]
    L += ["## 7. 代选规则", "", f"- picks = **{pol['picks']}**：挑图 / 设定图 / 单品 / 音色 / 剧本闸门由系统按分数代选，一直开着；你任何时候点别的或说一句都能换（你的选择永远赢）。", ""]
    L += ["## 8. 出不来时怎么兜底", "",
          f"- asset_failure = **{pol['asset_failure']}**：资产换种子重排用尽 → 去掉容易出错的细节（logo / 字样等）再出 → 换一批远种子 → 借同一角色另一套造型最接近的通过图；都不行标“尽力版”继续，不停下来等你。",
          f"- asset_revise = **{pol['asset_revise']}**：只发一条灰色“事后可改”告知；你想改随时在对话里说。",
          f"- review_needed = **{pol['review_needed']}**：待复核只记录，不挡流水线。",
          "- 每个镜头的首帧 / 尾帧 / 视频都有“重做”按钮：点一下就重出，不确认。", ""]
    L += ["## 记录答复", "", "```", f"kickoff.py record --run {run} --by 项目方 --quote \"<原话>\" --set adult_authorization=all --set look_confirm=auto ...", "```", ""]
    return "\n".join(L)


def record(run: str, answers: dict, by: str, quote: str = "", root: Path | None = None) -> dict:
    """记项目方答复：policy 项（值要在 CHOICES 里）改规则；其余（characters / looks / style …）原话留档"""
    r = Path(root or ROOT)
    bad = {k: v for k, v in answers.items() if k in CHOICES and v not in CHOICES[k]}
    if bad:
        raise ValueError("这些规则值不认识：" + "、".join(f"{k}={v}（可选 {'/'.join(CHOICES[k])}）" for k, v in bad.items()))
    d = load(r)
    d.pop("_error", None)
    d.setdefault("schema", "nsfs.kickoff/1")
    rr = d.setdefault("runs", {}).setdefault(run, {})
    rr.setdefault("policy", {}).update({k: v for k, v in answers.items() if k in CHOICES})
    rr.setdefault("answers", {}).update({k: v for k, v in answers.items() if k not in CHOICES})
    at = time.strftime("%Y-%m-%dT%H:%M:%S")
    rr.update(confirmed_at=at, by=by)
    rr.setdefault("history", []).append({"at": at, "by": by, "quote": quote[:500], "answers": answers})
    _atomic_json(cfg_path(r), d)
    return {"run": run, "policy": policy(run, r), "confirmed_at": at}


# ------------------------------------------------------------------ CLI
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="开项目确认单（L-215 / L-216）")
    ap.add_argument("cmd", choices=["checklist", "record", "sync-adult", "policy"])
    ap.add_argument("--run", default="")
    ap.add_argument("--out", default="")
    ap.add_argument("--set", action="append", default=[], help="record：key=value")
    ap.add_argument("--by", default="项目方")
    ap.add_argument("--quote", default="")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--no-push", action="store_true")
    a = ap.parse_args(argv)
    run = a.run or None
    if a.cmd == "checklist":
        md = checklist(run)
        if a.out:
            Path(a.out).write_text(md, encoding="utf-8")
        print(md)
    elif a.cmd == "record":
        if not run:
            print("record 要写 --run", file=sys.stderr)
            return 2
        ans = dict(x.split("=", 1) for x in a.set if "=" in x)
        print(json.dumps(record(run, ans, a.by, a.quote), ensure_ascii=False, indent=1))
    elif a.cmd == "sync-adult":
        res = [sync_adult(run, dry=a.dry, push=not a.no_push)] if run else sync_adult_all(push=not a.no_push)
        print(json.dumps(res, ensure_ascii=False, indent=1))
    else:
        print(json.dumps(policy(run), ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
