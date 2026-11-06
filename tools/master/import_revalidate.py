"""导入稿按现行规则复验（W-GATE 11-06；总调度 PS-MASTER 21:2x 核实的根因）。

问题：导入闸门（autoflow gate + producer.import_staged 的 validate_qwen_script / writer_lints）只在导入那一刻判一次。
之后新加的写作规则（QW-L12 / L13 / L14，对应项目方 L-201 / L-203）不会回头查已经导入的集——ep02–ep04 在现行校验器下
有 9–11 个 QW-L14 block，sop_gate 仍显示“已过导入闸门”，producer 会照着项目方已驳回过的写法出图。

做法：
  ruleset_fingerprint(root)   规则集指纹 = writer_lints.RULES（id + 级别）+ 各级别开关 + 校验链源码 sha（validate_qwen_script /
                              writer_lints / acting_lints / vqa script_lint / rubric_code）。加一条规则或改级别 → 指纹变。
  imported_source(run, ep)    当前导入的那份稿：导入稿 sources 里最后一个 episodes 含本集的条目（path + sha256）；
                              没有 → autoflow_epNN.json import.sha256 在 P4_epNN*.md / staging/P4_epNN*.md 里按 sha 找；
                              记录的文件后来被改过 → 按记录的 sha 在同一批候选里找原稿，找不到就复验现文件并注明。
  revalidate(run, ep)         对该稿跑 validate_qwen_script --episode N --json（与 producer.import_staged 同一校验器），
                              结果按 (稿 sha, 指纹) 缓存在 data/pipeline/sop_gate/<run>/import_revalidate.json（原子写），命中不再跑。
                              新算出 block > 0 → 写一行 data/pipeline/sop_gate/import_revalidate.jsonl，并开一条卡点
                              （data/pipeline/issues.jsonl，大脑快照 issues_open 可见；同一稿同一组 block 计数只开一次）。

模式（config/pipeline/sop_gate.json import_revalidate.mode）：off / report（默认，只显示、只记录，不挡任何东西）/
enforce（block > 0 的集不能进 enforce_from 阶段，默认“出图”；开 enforce = 项目方决策，代码已实现未启用）。
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODES = ("off", "report", "enforce")
DEFAULT = {"mode": "report", "enforce_from": "出图", "timeout_s": 30}   # 闸门路径（producer 每拍）：校验器正常 ~3.5 s，30 s 封顶
ERR_TTL_S = 900                # 校验器出错 / 解析不出本集：结果在本进程记 15 分钟，期间不重跑（producer 每拍每镜都判，不能每次起子进程）
VALIDATOR = "tools/validate_qwen_script.py"
LINTS = "tools/qa/writer_lints.py"
SRC_FILES = (VALIDATOR, LINTS, "tools/qa/acting_lints.py", "tools/vqa/script_lint.py", "tools/script_rsi/rubric_code.py")
LEVEL_KEYS = ("WRITER_LINT_LEVEL", "L201_LEVEL", "RUBRIC_LEVEL")
_MEMO: dict = {}


def cfg_of(sop_cfg: dict | None) -> dict:
    c = (sop_cfg or {}).get("import_revalidate")
    c = {**DEFAULT, **(c if isinstance(c, dict) else {})}
    if c.get("mode") not in MODES:
        c["mode"] = "report"              # 写错的模式按默认 report（只显示，不挡）
    return c


def _src(root: Path, rel: str) -> Path:
    """夹具根目录有自己的校验链文件就用它的，否则用本仓库的"""
    p = Path(root) / rel
    return p if p.is_file() else ROOT / rel


def _sha_file(p: Path) -> str | None:
    try:
        return hashlib.sha256(p.read_bytes()).hexdigest()
    except OSError:   # arch-ok: 文件缺 = 没有 sha（调用方按“找不到稿”处理）
        return None


def _stamp(p: Path):
    try:
        st = p.stat()
        return (str(p), st.st_mtime_ns, st.st_size)
    except OSError:   # arch-ok: 文件缺 → 戳记为 None，指纹里照样体现
        return (str(p), None, None)


def _lint_rules(path: Path) -> tuple[list, dict]:
    """writer_lints.RULES 的 (id, 级别) 与级别开关；按文件戳记缓存（producer 每拍都会判，不能每次都重载模块）"""
    key = ("rules",) + _stamp(path)
    if key in _MEMO:
        return _MEMO[key]
    sp = importlib.util.spec_from_file_location(f"wl_fp_{abs(hash(key))}", path)
    m = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(m)
    rules = sorted((str(k), str((v or ("",))[0])) for k, v in (getattr(m, "RULES", {}) or {}).items())
    levels = {k: getattr(m, k) for k in LEVEL_KEYS if isinstance(getattr(m, k, None), str)}
    _MEMO[key] = (rules, levels)
    return rules, levels


def ruleset_fingerprint(root: Path = ROOT) -> dict:
    """{fp, rules: [[id, 级别]…], levels, src: {文件: sha 前 12}}；fp = 前三者的 sha256 前 16 位"""
    paths = [_src(root, r) for r in SRC_FILES]
    key = ("fp",) + tuple(_stamp(p) for p in paths)
    if key in _MEMO:
        return _MEMO[key]
    rules, levels = _lint_rules(_src(root, LINTS))
    src = {r: (_sha_file(p) or "")[:12] for r, p in zip(SRC_FILES, paths)}
    body = json.dumps({"rules": rules, "levels": levels, "src": src}, ensure_ascii=False, sort_keys=True)
    out = {"fp": hashlib.sha256(body.encode("utf-8")).hexdigest()[:16], "rules": rules, "levels": levels, "src": src}
    _MEMO[key] = out
    return out


def _abs(root: Path, p: str) -> Path:
    """导入稿里记的是写入时那台机器的绝对路径（笔记本 D:\\NS-Final Studio\\data\\…；服务器 /…/data/…）。
    原样在 → 用它；否则统一成 / 分隔后从 data/ 起按本根目录重拼（Linux 上 Windows 路径不是“绝对路径”，不能靠 is_absolute 判）"""
    q = Path(p)
    try:
        if q.is_absolute() and q.is_file():
            return q
    except OSError:   # arch-ok: 路径非法 = 按重拼处理
        pass
    norm = str(p).replace("\\", "/")
    parts = [x for x in norm.split("/") if x]
    if "data" in parts:
        return Path(root).joinpath(*parts[parts.index("data"):])
    if re.match(r"^[A-Za-z]:/", norm) or norm.startswith("/"):
        return q
    return Path(root).joinpath(*parts)


def _candidates(root: Path, run: str, ep: int) -> list[Path]:
    d = Path(root) / "data/pipeline/runs" / run
    pat = f"P4_ep{int(ep):02d}*.md"
    return sorted(d.glob(pat)) + sorted((d / "staging").glob(pat))


def _by_sha(root: Path, run: str, ep: int, sha: str) -> Path | None:
    for c in _candidates(root, run, ep):
        if _sha_file(c) == sha:
            return c
    return None


def imported_source(run: str, ep: int, root: Path = ROOT, import_doc: dict | None = None, autoflow: dict | None = None) -> dict | None:
    """{path, recorded_sha, sha, note} 或 None（找不到当前导入的稿）"""
    rec = None
    for s in (import_doc or {}).get("sources") or []:
        if isinstance(s, dict) and int(ep) in [int(x) for x in (s.get("episodes") or []) if str(x).lstrip("-").isdigit()]:
            rec = s                                               # 最后一个含本集的来源 = 当前导入的稿
    if rec and rec.get("path"):
        p, want = _abs(root, str(rec["path"])), rec.get("sha256")
    else:
        im = next((x for x in (autoflow or {}).get("stages") or [] if x.get("id") == "import"), {})
        want = im.get("sha256")
        p = _by_sha(root, run, ep, want) if want else None
        if p is None:
            return None
    got = _sha_file(p)
    if want and got != want:
        alt = _by_sha(root, run, ep, want)
        if alt is not None:
            return {"path": alt, "recorded_sha": want, "sha": want, "note": f"原记录文件已改，按 sha 找到原稿 {alt.name}"}
        if got is None:
            return None
        return {"path": p, "recorded_sha": want, "sha": got, "note": "导入后原稿文件被改过（sha 不符），复验的是现文件"}
    if got is None:
        return None
    return {"path": p, "recorded_sha": want, "sha": got, "note": ""}


def run_validator(root: Path, path: Path, ep: int, timeout_s: float) -> dict:
    """与 producer.import_staged 同一校验器（子进程，隔离 sys.path）；返回 validate() 的 JSON 报告"""
    r = subprocess.run([sys.executable, str(_src(root, VALIDATOR)), str(path), "--episode", str(int(ep)), "--json"],
                       capture_output=True, cwd=str(root), timeout=timeout_s, env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    try:
        return json.loads(r.stdout.decode("utf-8"))
    except ValueError as e:
        raise RuntimeError(f"校验器没给 JSON（rc={r.returncode}）：{r.stderr.decode('utf-8', 'replace')[-200:]}") from e


RUNNER = run_validator          # 测试换掉


def _cache_path(root: Path, run: str) -> Path:
    return Path(root) / "data/pipeline/sop_gate" / run / "import_revalidate.json"


def _read_json(p: Path) -> dict:
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):   # arch-ok: 缓存缺 / 坏 = 重算（缓存不是证据）
        return {}
    return d if isinstance(d, dict) else {}


def _write_json(p: Path, d: dict) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f"{p.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, p)


def _append(p: Path, rec: dict) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(p, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        os.write(fd, (json.dumps(rec, ensure_ascii=False) + "\n").encode("utf-8"))
    finally:
        os.close(fd)


def by_rule(rep: dict) -> dict[str, int]:
    out: dict[str, int] = {}
    for k, n in (rep.get("counts") or {}).items():
        rid, _, lvl = str(k).partition("|")
        if lvl == "block":
            out[rid] = out.get(rid, 0) + int(n)
    return dict(sorted(out.items(), key=lambda x: (-x[1], x[0])))


def summary(res: dict | None) -> str:
    """“导入稿按现行规则复验：block N（QW-L14×k…）”"""
    if not res:
        return ""
    if res.get("error"):
        return f"导入稿按现行规则复验：没跑成（{str(res['error'])[:80]}）"
    n = int(res.get("blocking") or 0)
    rules = "、".join(f"{k}×{v}" for k, v in list((res.get("by_rule") or {}).items())[:4])
    return f"导入稿按现行规则复验：block {n}" + (f"（{rules}）" if n and rules else "") + (f"；{res['note']}" if res.get("note") else "")


def _report_issue(root: Path, run: str, ep: int, res: dict) -> None:
    """新算出 block > 0：开一条卡点（大脑快照 issues_open 读 data/pipeline/issues.jsonl）。不写 V2_LIVE，不阻断"""
    sp = importlib.util.spec_from_file_location("report_issue_for_revalidate", ROOT / "tools/master/report_issue.py")
    m = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(m)
    m.report(run, int(ep), "导入闸门复验", "W-GATE", f"ep{int(ep):02d} {summary(res)}（{res.get('source')}）", False,
             fix_hint="按现行写作规则返修该集分镜后重新导入；import_revalidate.mode=enforce 由项目方决定是否开",
             issues=Path(root) / "data/pipeline/issues.jsonl", live=None)


def revalidate(run: str, ep: int, root: Path = ROOT, import_doc: dict | None = None, autoflow: dict | None = None,
               cfg: dict | None = None, runner=None) -> dict | None:
    """当前导入稿按现行规则复验（缓存键 = 稿 sha + 规则集指纹）。找不到导入稿 → None。
    返回 {episode, source, text_sha, fp, blocking, by_rule, note, cached, at[, error]}；本函数从不抛（report 模式不能挡东西）"""
    try:
        src = imported_source(run, ep, root, import_doc, autoflow)
    except Exception as e:  # noqa: BLE001  找稿出错 = 当没找到（只是复验，不是闸门本体）
        return {"episode": int(ep), "error": f"找导入稿出错：{e!r}"[:200], "blocking": None, "cached": False}
    if not src:
        return None
    try:
        fp = ruleset_fingerprint(root)["fp"]
    except Exception as e:  # noqa: BLE001
        return {"episode": int(ep), "error": f"规则指纹算不出：{e!r}"[:200], "blocking": None, "cached": False}
    key = f"ep{int(ep):02d}|{src['sha']}|{fp}"
    mk = ("res", str(Path(root).resolve()), run, key)
    if mk in _MEMO:
        return {**_MEMO[mk], "cached": True}
    ek = ("err",) + mk[1:]
    if ek in _MEMO and time.time() - _MEMO[ek][0] < ERR_TTL_S:      # 出错结果记 ERR_TTL_S，期间不重跑校验器
        return {**_MEMO[ek][1], "cached": True}
    cp = _cache_path(root, run)
    cache = _read_json(cp)
    hit = (cache.get("results") or {}).get(key)
    if isinstance(hit, dict) and not hit.get("error"):
        _MEMO[mk] = hit
        return {**hit, "cached": True}
    c = cfg or DEFAULT
    try:
        rel = src["path"].relative_to(root).as_posix()
    except ValueError:
        rel = str(src["path"])
    res = {"episode": int(ep), "source": rel, "text_sha": src["sha"], "fp": fp, "note": src.get("note") or "",
           "at": time.strftime("%Y-%m-%dT%H:%M:%S+09:00", time.gmtime(time.time() + 9 * 3600))}   # JST
    try:
        rep = (runner or RUNNER)(Path(root), src["path"], int(ep), float(c.get("timeout_s") or DEFAULT["timeout_s"]))
        res.update(blocking=int(rep.get("blocking") or 0), by_rule=by_rule(rep), episodes_found=rep.get("episodes_found"))
        if not rep.get("episodes_found"):
            res["error"] = "校验器在该稿里没解析出本集"
    except Exception as e:  # noqa: BLE001  校验器自身出错：记错误（本进程 ERR_TTL_S 内不重跑），不写文件缓存
        res.update(blocking=None, by_rule={}, error=repr(e)[:200])
    if res.get("error"):
        _MEMO[ek] = (time.time(), res)
        return {**res, "cached": False}
    _MEMO[mk] = res
    try:      # 落盘失败（Windows 上 os.replace 撞文件锁 PermissionError 等）不能传进闸门：结果照样返回
        results = {k: v for k, v in (cache.get("results") or {}).items() if not k.startswith(f"ep{int(ep):02d}|")}   # 本集旧键丢掉
        results[key] = res
        reported = dict(cache.get("reported") or {})
        _write_json(cp, {"_doc": "tools/master/import_revalidate.py 缓存：键 = epNN|导入稿 sha|规则集指纹", "fp": fp, "results": results,
                         "reported": reported})
        _append(Path(root) / "data/pipeline/sop_gate/import_revalidate.jsonl",
                {"at": res["at"], "run": run, "episode": int(ep), "source": rel, "text_sha": src["sha"][:12], "fp": fp,
                 "blocking": res["blocking"], "by_rule": res["by_rule"]})
    except Exception as e:  # noqa: BLE001
        sys.stderr.write(f"[import_revalidate] 缓存 / 遥测没写上：{e!r}\n")
        return {**res, "cached": False}
    if res["blocking"]:
        sig = f"ep{int(ep):02d}|{src['sha']}|" + json.dumps(res["by_rule"], sort_keys=True)
        if sig not in reported:
            try:
                _report_issue(root, run, ep, res)
                reported[sig] = res["at"]
                _write_json(cp, {**_read_json(cp), "reported": reported})
            except Exception as e:  # noqa: BLE001  卡点没写上不影响复验结果
                sys.stderr.write(f"[import_revalidate] 卡点没写上：{e!r}\n")
    return {**res, "cached": False}


def enforce_blocks(res: dict | None, cfg: dict) -> bool:
    """enforce 模式下本集是否要挡（block > 0）。report / off 永远 False"""
    return cfg.get("mode") == "enforce" and bool(res) and not res.get("error") and int(res.get("blocking") or 0) > 0
