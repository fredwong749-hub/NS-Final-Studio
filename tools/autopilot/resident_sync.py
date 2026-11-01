"""服务器常驻生产的同步（WORKFLOW 11-01，总调度 16:55 根因修法；规则 K-OPS-W07）。

项目方 16:55：“显卡现在还没有在跑……先把显卡的问题给 fix 掉”。跳板 194relay 每次握手 6–7 s 且反复强制断连，
笔记本经隧道派单 7 张卡只有 1–2 张在跑。改为：两台服务器各跑本机负责集的 producer + night（直接调本机 ComfyUI，
fwd.py 把 1818x 转到本机 8188/8189/8191），笔记本只做控制面。复用 offline_20261101 那套目录（repo/ venv/ bin/ fwd.py start.sh stop.sh）。

  push HOST [--code-only]   笔记本 → 服务器：按清单比对（大小 / 修改时间），只发不同的文件；分批 tar（每批 ≤ 24 MB），
                            每批失败重试 5 次（退避），发完再对一次清单，没到的（含被断连截断的）重发 = 文件级断点续传
  pull HOST                 服务器 → 笔记本：上次并回之后服务器改过的文件分批拉到 data/_offline_pull/<host>/，校验大小后
                            交 ops/offline/merge_pull.py（按集只收负责那台的、新者为准、截断文件不覆盖、先备份）
  restart HOST              服务器上重放补丁（ops/offline/resident_prep.py）+ 热重启 producer / night（不动 fwd）
  switch [HOST…]            一条命令切到常驻：push（代码 + 数据）→ restart → health
  recover [HOST...]         跳板恢复后的一键动作：查进程 -> push -> 补丁 + 热重启 -> health -> 服务器上 Pika 冒烟一镜 -> 起 loop
  smoke HOST [SHOT]         服务器本机 Pika 冒烟（后台提交 + 短 ssh 轮询结果）
  alive HOST                常驻进程（fwd / producer / night）在不在
  auto                      无人值守：等跳板 TCP 恢复 → switch → loop
  health HOST               服务器侧每张卡利用率 / 队列 / producer 心跳 / night 心跳；空闲但有活 ≥ 10 分钟写报警
  loop                      常驻：5 分钟一次 health；20 分钟两台各 pull 一次；代码有改动就 push --code-only + restart
不删任何文件（两边都不删）。日志 ops/logs/resident_sync.log，状态 data/autopilot/resident_sync.json。
"""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tarfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools/autopilot"))
import runs as _RUNS  # noqa: E402
# K-OPS-W17 / SYSARCH 4-6：主 run 从 config/pipeline/runs.json 读，不写死；本工具驱动服务器 → strict（缺 runs.json 直接失败，K-OPS-F09）
RUN_ID = _RUNS.primary_run(strict=True)
RUN_REL = f"data/pipeline/runs/{RUN_ID}"
OFF = "/root/work/fredw/offline_20261101"
R = OFF + "/repo"
def _partition_hosts() -> dict[str, list[int]]:
    """NETFIX 22:2x：按集归属改读 config/netfix/partition.json（images ∪ video；laptop 不是服务器，不在内）；读不到用旧分集"""
    try:
        part = json.loads((ROOT / "config/netfix/partition.json").read_text(encoding="utf-8"))
        out = {}
        for kind in ("images", "video"):
            for h, eps in (part.get(kind) or {}).items():
                if h != "laptop":
                    out.setdefault(h, set()).update(int(x) for x in eps)
        if out:
            return {h: sorted(v) for h, v in sorted(out.items())}
    except (OSError, ValueError):
        pass
    return {"gpu33": [1, 3, 5], "gpu36": [2, 4, 6, 7, 8, 9, 10]}


HOSTS = _partition_hosts()     # gpu33 GPU2 坏卡永不用（道表里本来就没有）
CODE_DIRS = ["tools", "services", "packages", "config", "knowledge", "ops"]
DATA_DIRS = ["data", "assets", "docs/series10_video"]
SKIP_PARTS = {"node_modules", ".venv", "__pycache__", ".git", "_offline_pull", "leases", ".pytest_cache"}
SKIP_PREFIX = ("data/_quarantine", "data/_offline_pull", "data/cache/", "data/ab/", "data/api_8800", "data/review_pages/",
               "data/qa/iter_gate/", "data/autopilot/repair_chain/", "data/staging", "ops/logs/", "data/lb/")
SKIP_NAMES = {"control.json", "heartbeat.json", "producer.pid", "registry.json", "night.pid", "night_control.json"}
SSH = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=40", "-o", "ServerAliveInterval=15", "-o", "ServerAliveCountMax=4"]
BATCH = 24 * 1024 * 1024
STATE = ROOT / "data/autopilot/resident_sync.json"
LOG = ROOT / "ops/logs/resident_sync.log"


def log(*a):
    line = time.strftime("%F %T ") + " ".join(str(x) for x in a)
    try:                                   # 04:12 实测：Start-Process 拉起时 stdout 是 cp1252，中文 print 抛错把整个 loop 带崩
        print(line, flush=True)
    except (UnicodeEncodeError, OSError, ValueError):
        try:
            sys.stdout.buffer.write((line + "\n").encode("utf-8", "replace"))
            sys.stdout.flush()
        except Exception:  # noqa: BLE001
            pass
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def jl(p, d=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return d


def js(p, d):
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    t = p.with_suffix(".tmp")
    t.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(t, p)


def ssh(host: str, cmd: str, data: bytes | None = None, timeout: int = 900, tries: int = 5) -> bytes:
    """带重试的远程命令（SYSARCH 4-1，WORKFLOW 同意）：rssh.run_retry 走常驻主连接；rc=255（连接层）或超时按 10/20/30/40 s 退避重试，
    远端命令自己的非 0 不重试（35 个调用方核过无依赖）；超时杀进程由 rssh 负责。最后仍失败抛 RuntimeError"""
    r = _rssh().run_retry(host, cmd, input=data, timeout=timeout, tries=tries, backoff_s=10)
    if r.returncode == 0:
        return r.stdout
    err = (r.stderr or b"").decode("utf-8", "replace")[-300:]
    log("ssh fail", host, f"rc={r.returncode}", err.strip().replace("\n", " ")[:200])
    raise RuntimeError(f"ssh {host} 失败（rc={r.returncode}，tries={tries}）：{err}")


def _rssh():
    """K-OPS-N07 / SYSARCH 4-1：远程命令统一走 tools/netfix/rssh.run_retry（笔记本走常驻主连接；服务器上 OFFLINE_SELF 调本机 = 本机执行）"""
    import importlib.util
    spec = importlib.util.spec_from_file_location("_rssh_41", Path(__file__).resolve().parents[2] / "tools/netfix/rssh.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def skipped(rel: str) -> bool:
    parts = rel.split("/")
    return (any(p in SKIP_PARTS for p in parts) or rel.startswith(SKIP_PREFIX) or parts[-1] in SKIP_NAMES
            or rel.endswith((".tmp", ".pyc", ".log.1")))


def local_manifest(dirs: list[str]) -> dict[str, tuple[int, float]]:
    out = {}
    for d in dirs:
        base = ROOT / d
        if not base.exists():
            continue
        for dp, dn, fn in os.walk(base):
            dn[:] = [x for x in dn if x not in SKIP_PARTS]
            for f in fn:
                p = Path(dp) / f
                rel = p.relative_to(ROOT).as_posix()
                if skipped(rel):
                    continue
                try:
                    st = p.stat()
                except OSError:
                    continue
                out[rel] = (st.st_size, st.st_mtime)
    return out


def remote_manifest(host: str, dirs: list[str]) -> dict[str, tuple[int, float]]:
    raw = ssh(host, f"cd {R} && find {' '.join(dirs)} -type f -printf '%p\\t%s\\t%T@\\n' 2>/dev/null; true", timeout=600)
    out = {}
    for ln in raw.decode("utf-8", "replace").splitlines():
        try:
            p, s, t = ln.split("\t")
            out[p] = (int(s), float(t))
        except ValueError:
            continue
    return out


def diff_push(loc: dict, rem: dict) -> list[str]:
    """本地有、远端没有，或大小不同且本地更新（或远端是本地的截断），或大小同但本地明显更新"""
    out = []
    for rel, (s, t) in loc.items():
        r = rem.get(rel)
        if r is None or (r[0] != s and (t >= r[1] - 2 or r[0] < s)) or (r[0] == s and t > r[1] + 2):
            out.append(rel)
    return sorted(out)


def batches(files: list[str], sizes: dict) -> list[list[str]]:
    out, cur, n = [], [], 0
    for f in files:
        s = sizes.get(f, (0,))[0]
        if cur and n + s > BATCH:
            out.append(cur)
            cur, n = [], 0
        cur.append(f)
        n += s
    if cur:
        out.append(cur)
    return out


def tar_bytes(files: list[str]) -> bytes:
    """K-OPS-C04（CODE-RSI 11-01）：先整份读进内存再按实际字节数写成员。原来 tf.add 先按 stat 写头再读文件，
    打包途中文件被别的 loop 截短 → copyfileobj 抛 OSError（被吞），头里的长度对不上，后面的成员整体错位：
    服务器上这个文件变成“原文 + 下一个成员的头 + 0”，下一个文件丢失（tests/test_push_check.py 复现）。
    stat 在读之前取：读之后又被改 → 本地 mtime 更新，下一轮清单比对会补发。"""
    bio = io.BytesIO()
    with tarfile.open(fileobj=bio, mode="w", format=tarfile.PAX_FORMAT) as tf:
        for f in files:
            p = ROOT / f
            try:
                st = p.stat()
                data = p.read_bytes()
            except OSError:
                continue          # 文件没了：下一轮清单比对自然不再要它
            ti = tarfile.TarInfo(f)
            ti.size, ti.mtime, ti.mode = len(data), st.st_mtime, st.st_mode & 0o777
            tf.addfile(ti, io.BytesIO(data))
    return bio.getvalue()


LIVE_PREFIX = ("data/renders/", "data/producer/", f"{RUN_REL}/", "data/import/", "data/assets/",
               "data/looks/", "data/music/series10/", "data/episodes/series10/", "data/assetmaster/sheets_v2/adopted/")


def required_data() -> set[str]:
    """生产必需、服务器副本可能缺的数据：remote_preflight 的资产图清单（选定设定图 / 身份脸 / 单品图）+ 首帧作业参考图"""
    sys.path.insert(0, str(ROOT / "tools/pipeline"))
    # 总调度 01:2x（K-OPS-W13）：清单 = producer preflight（I1–I9）实际用到的文件——直接复用 frame_job.build_first 的作业依赖
    # （tools/pipeline/preflight_deps.py），不再自己另列一份（01:14 场景底图漏列，服务器 I5 每单挡）
    import preflight_deps as PD
    out = set(PD.preflight_deps()["files"])
    # VOICE10 11-01（K-EDT-022，总调度授权对接）：成片在服务器合成 → 每个说话人的参考音频 / 音色元数据也是生产必需
    # （config/voices.json characters[].ref_wav / asset；缺了 ns_post.tts.tts_preflight 会 hold_tts）
    try:
        vc = json.loads((ROOT / "config/voices.json").read_text(encoding="utf-8"))
        for c in (vc.get("characters") or {}).values():
            out |= {str(c[k]).replace("\\", "/") for k in ("ref_wav", "asset") if c.get(k)}
    except (OSError, ValueError):
        pass
    return out


def wanted(rel: str, rem: dict, loc: dict, freeze: float, need: set) -> bool:
    """代码目录：都要。数据：服务器已有且不同 / 生产必需清单里 / 服务器副本冻结之后笔记本新产生的生产数据（不整盘推 5 GB）"""
    if not rel.startswith(("data/", "assets/", "docs/")):
        return True
    return rel in rem or rel in need or (loc[rel][1] > freeze and rel.startswith(LIVE_PREFIX))


TIER1_EXT = (".py", ".yaml", ".yml", ".json", ".md", ".txt", ".sh", ".toml", ".cfg", ".ini")
TIER1_DATA = ("data/import/script_v2.json",   # master_rejects / ready_episodes 不走整文件覆盖，由 push_control 按对象合并推（K-OPS-Q20）
              f"{RUN_REL}/assets/first_frame_jobs.json", f"{RUN_REL}/video/recipe_choice.json",
              f"{RUN_REL}/assets/sheets_chosen.json", f"{RUN_REL}/assets/shot_looks.json")
TIER1_DATA_PREFIX = ("data/assets/identity_refs/",)          # 身份脸（项目方挑定，小图）
TIER1_SMALL = 2 * 1024 * 1024
BATCH_TIMEOUT_S = 300                                          # 总调度 00:01：单批卡住超过 5 分钟就杀掉 ssh 重连（2 MB 批在 15 KB/s 下约 140 s）
WARN_MB = 20                                                   # K-OPS-W09：单次推送超过 20 MB 必须先报估计耗时
LINK_KBPS = 18                                                 # 跳板实测 17–20 KB/s（总调度 18:03；16:24 推 11.8 MB 约 10 分钟）


def tier_of(rel: str, size: int) -> int:
    """1 = 代码与小配置（先推，推完就能起卡）；2 = 大文件 / 数据成品（后台慢慢补，缺哪张 preflight 挡哪一镜）"""
    if rel.startswith(tuple(d + "/" for d in CODE_DIRS)):
        return 1 if rel.endswith(TIER1_EXT) and size <= TIER1_SMALL else 2
    if rel in TIER1_DATA or (rel.startswith(TIER1_DATA_PREFIX) and size <= TIER1_SMALL):
        return 1
    return 2


def estimate(files: list[str], loc: dict) -> dict:
    mb = sum(loc[f][0] for f in files) / 1e6
    return {"files": len(files), "mb": round(mb, 2), "eta_min": round(mb * 1000 / LINK_KBPS / 60, 1)}


TIER1_REMOTE_DATA = ["data/import", "data/assets/identity_refs", f"{RUN_REL}/assets",
                     f"{RUN_REL}/video"]


def push_dirs(code_only: bool = False, tier: int = 2) -> tuple[list[str], list[str]]:
    """→ (本地清单目录, 远端清单目录)。push 与 tools/qa/push_check.py 共用（CODE-RSI 11-01，总调度：目录计算抽成函数）。
    K-OPS-C05：只有 tier 1 才不列整个 data/（只列 TIER1_REMOTE_DATA）；tier 2 必须列 data/，否则服务器已有的数据
    永远被当成“缺”，三轮都整批重发（push_check 模拟：轮次差异 [1665, 932, 932]）"""
    dirs = CODE_DIRS + ([] if code_only or tier == 1 else DATA_DIRS) + (["data"] if tier == 1 else [])
    rem_dirs = [d for d in dirs if d != "data" or tier != 1] + (list(TIER1_REMOTE_DATA) if tier == 1 else [])
    return dirs, rem_dirs


class PushGateFailed(RuntimeError):
    """推送前检查（tools/qa/push_check.py，K-OPS-C03）没过：不推、不起常驻"""


_GATE_OK: dict[tuple[int, bool], float] = {}
GATE_TTL_S = 900


def push_gate(tier: int = 2, code_only: bool = False) -> dict:
    """K-OPS-C03（总调度 11-01 定）：push / recover / video_up / bringup / switch / loop 推送前必须本地模拟一次并 PASS。
    同一档（tier, code_only）15 分钟内过过、且之后代码目录没改 → 复用结果；否则重跑。不过 → PushGateFailed。
    NS_PUSH_GATE=off 只给 push_check 自己的模拟用（避免递归），人不得用它绕过"""
    if os.environ.get("NS_PUSH_GATE") == "off":
        return {"skipped": "NS_PUSH_GATE=off"}
    key = (int(tier), bool(code_only))
    t = _GATE_OK.get(key)
    if t and time.time() - t < GATE_TTL_S and not code_changed_since(t):
        return {"cached": t}
    cmd = [sys.executable, str(ROOT / "tools/qa/push_check.py"), "--tier", str(tier)] + (["--code-only"] if code_only else [])
    t0 = time.time()
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=1800,
                       env={**os.environ, "PYTHONUTF8": "1", "NS_PUSH_GATE": "off"})
    tail = (r.stdout or r.stderr or "").strip().splitlines()[-6:]
    log("push_gate", f"tier{tier}", "code_only" if code_only else "", f"rc={r.returncode}", " | ".join(tail)[-400:])
    if r.returncode != 0:
        raise PushGateFailed(f"推送前检查不通过（tier {tier}），不推、不起常驻：{' | '.join(tail)[-300:]}（详情 data/qa/push_check/last.json）")
    _GATE_OK[key] = t0
    return {"passed": t0}


def push(host: str, code_only: bool = False, tier: int = 2, yes: bool = False, batch_mb: float = 2.0,
         gate: bool = True) -> dict:
    """tier=1：只推代码 / 小配置 / 身份脸 / 作业清单（目标 ≤ 10 MB）；tier=2：再推大文件与生产数据（低优先级、可中断续推）。
    超过 WARN_MB 时不带 yes 只报估计耗时、不推（K-OPS-W09）。每批 ≤ batch_mb，断了下次从清单差异接着推（文件级续传）。
    推之前先过 push_gate（K-OPS-C03）；gate=False 只给 push_check 的本地模拟用"""
    if gate:
        push_gate(tier, code_only)
    dirs, rem_dirs = push_dirs(code_only, tier)
    loc = local_manifest(dirs)
    sent_total = 0
    freeze = float(ssh(host, f"cat {OFF}/FREEZE_TS 2>/dev/null || echo 0").strip() or 0)
    need = required_data()
    for rnd in range(3):                    # 发 → 复核清单 → 补发（截断 / 丢批）
        rem = remote_manifest(host, rem_dirs)
        todo = [f for f in diff_push(loc, rem) if wanted(f, rem, loc, freeze, need)]
        todo = [f for f in todo if tier_of(f, loc[f][0]) <= tier]
        est = estimate(todo, loc)
        log("push", host, f"tier{tier}", "round", rnd + 1, "差异", est["files"], "个文件", f"{est['mb']} MB", f"预计 {est['eta_min']} 分钟")
        if not todo:
            break
        if est["mb"] > WARN_MB and not yes:
            log("push", host, f"超过 {WARN_MB} MB：先报估计耗时，不推（加 --yes 才推）")
            return {"host": host, "sent": 0, "estimate": est, "blocked": "over_warn"}
        global BATCH
        BATCH = int(batch_mb * 1024 * 1024)
        for i, b in enumerate(batches(todo, loc)):
            blob = tar_bytes(b)
            # 先解到临时目录再搬进 repo：一批传到一半断了不会留下截断文件（K-OPS-W02）
            ssh(host, f"set -e; T=$(mktemp -d {OFF}/.push.XXXXXX); tar xf - -C $T; cp -a $T/. {R}/; rm -rf $T; echo ok",
                data=blob, timeout=BATCH_TIMEOUT_S)
            sent_total += len(b)
            log("push", host, f"tier{tier} batch {i + 1}", len(b), "files", f"{len(blob) / 1e6:.2f} MB")
        loc = local_manifest(dirs)
    st = jl(STATE, {}) or {}
    st.setdefault(host, {})["last_push"] = time.time()
    st[host]["last_push_tier"] = tier
    js(STATE, st)
    return {"host": host, "sent": sent_total}


DEFAULT_MODE = "all"     # ⤴ 总调度 22:2x（NETFIX）：服务器 producer 和 night 都起（取代 18:4x 的 night-only）；producer 的 only 由 dispatch.py 算


def restart(host: str, mode: str = DEFAULT_MODE) -> str:
    prep_arg = "video-only" if mode == "night-only" else ""
    out = ssh(host, f"cd {R} && {OFF}/venv/bin/python ops/offline/resident_prep.py {host} {prep_arg} && bash {R}/ops/offline/resident_restart.sh {host} {mode}",
              timeout=300)
    txt = out.decode("utf-8", "replace")
    log("restart", host, txt.strip().replace("\n", " | ")[-400:])
    return txt


def pull(host: str) -> dict:
    st = jl(STATE, {}) or {}
    since = int((st.get(host) or {}).get("last_pull") or int(ssh(host, f"cat {OFF}/FREEZE_TS").strip() or 0))
    t0 = int(time.time()) - 5
    raw = ssh(host, f"cd {R} && find data docs/series10_video -type f -newermt @{since} ! -name '*.tmp' "
                    f"! -path 'data/producer/leases/*' -printf '%p\\t%s\\n' 2>/dev/null; true", timeout=600)
    files = {}
    for ln in raw.decode("utf-8", "replace").splitlines():
        try:
            p, s = ln.split("\t")
            files[p] = int(s)
        except ValueError:
            pass
    dst = ROOT / "data/_offline_pull" / host
    got, bad = 0, []
    # NETFIX 22:2x：先拉 json 与图（小、画布 / 审片页要用），mp4 只拉“需要的”：成片（data/episodes/）和各集 manifest 入选的原片 / 放大版
    small = [f for f in files if not f.lower().endswith(".mp4")]
    need_mp4 = set()
    for f in files:
        if f.lower().endswith(".mp4") and (f.startswith("data/episodes/") or "_sr1080" in f or "/_preview/" in f):
            need_mp4.add(f)
    for mf in [f for f in small if f.endswith("/manifest.json")]:
        try:
            raw = ssh(host, f"cat {R}/{mf}", timeout=120, tries=2)
            for sh in (json.loads(raw).get("shots") or []):
                for k in ("source", "proxy"):
                    if sh.get(k) and sh[k] in files:
                        need_mp4.add(sh[k])
        except Exception:  # noqa: BLE001
            pass
    names = sorted(small) + sorted(need_mp4)
    skipped_mp4 = len([f for f in files if f.lower().endswith(".mp4")]) - len(need_mp4)
    for b in batches(names, {k: (v,) for k, v in files.items()}):
        lst = "\n".join(b).encode()
        blob = ssh(host, f"cd {R} && tar cf - -T - 2>/dev/null; true", data=lst, timeout=1200)
        try:
            with tarfile.open(fileobj=io.BytesIO(blob)) as tf:
                for m in tf.getmembers():
                    if not m.isfile() or ".." in m.name or m.name.startswith("/"):
                        continue
                    data = tf.extractfile(m).read()
                    if len(data) != files.get(m.name, -1):       # 截断 / 远端正在写 → 这次不收，下次再拉
                        bad.append(m.name)
                        continue
                    p = dst / m.name
                    p.parent.mkdir(parents=True, exist_ok=True)
                    p.write_bytes(data)
                    os.utime(p, (m.mtime, m.mtime))
                    got += 1
        except tarfile.TarError as e:
            log("pull", host, "批次 tar 读不全（断连）", repr(e)[:120], "→ 下次重拉")
            bad += b
    log("pull", host, "since", since, "文件", len(files), "收", got, "不收", len(bad), "按需跳过 mp4", skipped_mp4)
    r = subprocess.run([sys.executable, str(ROOT / "ops/offline/merge_pull.py")], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=900, cwd=ROOT,
                       env={**os.environ, "PYTHONUTF8": "1", "MERGE_ONLY_HOST": host})
    log("merge", host, r.stdout.strip().splitlines()[-1:] if r.stdout.strip() else r.stderr[-300:])
    if not bad and r.returncode == 0:
        st = jl(STATE, {}) or {}
        st.setdefault(host, {})["last_pull"] = t0
        js(STATE, st)
    return {"host": host, "files": len(files), "got": got, "bad": len(bad), "merge_rc": r.returncode}


REMOTE_HEALTH = r"""
import json, subprocess, time, urllib.request, os
R = "__R__"; LANES = json.loads('__LANES__')
out = {"gpus": {}, "queues": {}, "now": time.time()}
for ln in subprocess.run(["nvidia-smi", "--query-gpu=index,utilization.gpu,memory.used", "--format=csv,noheader,nounits"],
                         capture_output=True, text=True).stdout.splitlines():
    i, u, m = [x.strip() for x in ln.split(",")]
    out["gpus"][i] = {"util": int(u), "mem": int(m)}
for g, port in LANES.items():
    try:
        q = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{port}/queue", timeout=5).read())
        out["queues"][g] = len(q["queue_running"]) + len(q["queue_pending"])
    except Exception:
        out["queues"][g] = None
try:
    out["hb"] = json.load(open(R + "/data/producer/heartbeat.json"))
except Exception:
    out["hb"] = None
try:
    out["ns"] = os.stat(R + "/data/pipeline/runs/__RUN__/video/night_state.json").st_mtime
except OSError:
    out["ns"] = 0
try:
    st = json.load(open(R + "/data/pipeline/runs/__RUN__/video/state___HOST__.json"))
    jobs = json.load(open(R + "/data/pipeline/runs/__RUN__/video/jobs.json"))
    try:
        allowed = set((json.load(open(R + "/config/pipeline/video_policy.json")).get("pika_only") or {}).get("allowed") or [])
    except Exception:
        allowed = set()
    readyv = {m["shot"] for m in jobs.get("shots", []) for v in (m.get("variants") or {}).values()
              if str(v.get("status")) in ("ready", "lint_error") and (not allowed or v.get("recipe") in allowed)}
    # 可派 = vidgen 没收尾、且重编后的 jobs.json 里真有能派的 Pika 变体（旧 state 的 pending 但没变体 ≠ 有活）
    out["disp"] = sum(1 for sid, r in st["shots"].items()
                      if r.get("status") not in ("done", "best_effort", "blocked", "waiting_frame") and sid in readyv)
except Exception:
    out["disp"] = 0
try:
    out["ctrl"] = json.load(open(R + "/data/producer/control.json"))
except Exception:
    out["ctrl"] = {}
print(json.dumps(out))
"""
IDLE_ALERT_MIN = 10        # 总调度 16:55：GPU 空闲但有待派任务超过 10 分钟要报警
LANES = {"gpu33": {"0": 8188, "1": 8189, "3": 8191}, "gpu36": {"0": 8188, "1": 8189, "2": 8190}}   # gpu33 GPU2 坏卡不列


def health(host: str) -> dict:
    """服务器侧健康：每张卡利用率、本机 ComfyUI 队列、producer 心跳、night_state 更新时间、可派镜数；
    空闲但有活 ≥ 10 分钟 → data/qa/alerts.jsonl（与 infra_watchdog 同一报警文件 / 同一开关语义）"""
    probe = REMOTE_HEALTH.replace("__RUN__", RUN_ID).replace("__R__", R).replace("__HOST__", host).replace("__LANES__", json.dumps(LANES[host]))
    raw = ssh(host, "python3 -", data=probe.encode(), timeout=120, tries=2).decode("utf-8", "replace")
    d = json.loads([ln for ln in raw.splitlines() if ln.startswith("{")][-1])
    gpus, kv = d["gpus"], d
    lanes = {g: gpus.get(g, {}) | {"queue": d["queues"].get(g)} for g in LANES[host]}
    now = int(d["now"])
    hb = d.get("hb") or {}
    idle = all((x.get("util") or 0) < 5 and not x.get("queue") for x in lanes.values())
    disp = int(d.get("disp") or 0)
    pending = disp > 0          # 总调度 22:09：只数真有可派的视频变体；producer 在途（暂停中）不算
    st = jl(STATE, {}) or {}
    hs = st.setdefault(host, {})
    hs["idle_since"] = (hs.get("idle_since") or time.time()) if (idle and pending) else None
    idle_min = (time.time() - hs["idle_since"]) / 60 if hs.get("idle_since") else 0
    res = {"host": host, "lanes": lanes, "gpu2_broken_skipped": host == "gpu33", "dispatchable": disp,
           "producer_hb_age_min": round((now - float(hb.get("t") or 0)) / 60, 1) if hb else None,
           "producer_paused": hb.get("paused"), "night_state_age_min": round((now - int(d.get("ns") or 0)) / 60, 1),
           "idle_min": round(idle_min, 1), "at": time.strftime("%F %T")}
    hs["health"] = res
    js(STATE, st)
    sys.path.insert(0, str(Path(__file__).parent))
    import infra_watchdog as W
    ws = jl(W.STATE, {}) or {}
    W.alert(ws, f"A-IDLE-{host}", idle_min >= IDLE_ALERT_MIN, "crit",
            f"{host} 渲染卡全部空闲 {idle_min:.0f} 分钟，但还有活（可派视频 {disp} 镜 / producer 在途 {hb.get('inflight')}）")
    prod_expected = (d.get("ctrl") or {}).get("paused_by") != "LAPTOP_IMAGES"   # 18:4x 分工：服务器 producer 不起，不报
    res["producer_expected"] = prod_expected
    W.alert(ws, f"A-RESIDENT-PROD-{host}", prod_expected and (res["producer_hb_age_min"] is None or res["producer_hb_age_min"] >= 10), "crit",
            f"{host} 常驻 producer 心跳 {res['producer_hb_age_min']} 分钟没更新")
    W.alert(ws, f"A-RESIDENT-NIGHT-{host}", res["night_state_age_min"] >= 20, "crit",
            f"{host} 常驻 night.py 的 night_state.json {res['night_state_age_min']} 分钟没更新（卡住或已退出）")
    js(W.STATE, ws)
    log("health", host, json.dumps({k: res[k] for k in ("lanes", "dispatchable", "producer_hb_age_min", "night_state_age_min",
                                                          "idle_min")}, ensure_ascii=False))
    return res


def code_changed_since(t: float) -> bool:
    for rel, (_s, mt) in local_manifest(CODE_DIRS).items():
        if mt > t:
            return True
    return False


CONTROL_FILES = ["data/producer/master_rejects.json", "data/autopilot/ready_episodes.json", "data/netfix/laptop_ctrl.json",
                 "data/netfix/override_state.json"]   # NETFIX 23:4x：临时覆盖状态，server-control 据此知道某台已交还
OVERWRITE_FILES = {"data/netfix/laptop_ctrl.json", "data/netfix/override_state.json"}      # 笔记本 control 的快照：整文件覆盖
REMOTE_MERGE = r"""
import json, os, sys
R = "__R__"; rel = sys.argv[1]; src = sys.argv[2]
def ts(v):
    best = ""
    if isinstance(v, dict):
        for k, x in v.items():
            if str(k).endswith("at") and isinstance(x, str) and x[:2] == "20":
                best = max(best, x)
            elif isinstance(x, (dict, list)):
                best = max(best, ts(x))
    elif isinstance(v, list):
        for x in v:
            best = max(best, ts(x))
    return best
new = json.load(open(src, encoding="utf-8"))
dst = os.path.join(R, rel)
try:
    cur = json.load(open(dst, encoding="utf-8"))
except Exception:
    cur = {}
out = dict(cur)
if rel in ("data/netfix/laptop_ctrl.json", "data/netfix/override_state.json"):          # 快照：整文件覆盖
    tmp = os.path.join(R, rel) + ".tmp"
    os.makedirs(os.path.dirname(tmp), exist_ok=True)
    json.dump(new, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    os.replace(tmp, os.path.join(R, rel))
    print("overwrote", rel)
    sys.exit(0)
items = new.get("episodes") if rel.endswith("ready_episodes.json") else new
tgt = out.setdefault("episodes", {}) if rel.endswith("ready_episodes.json") else out
base = (cur.get("episodes") or {}) if rel.endswith("ready_episodes.json") else cur
n = 0
for k, v in (items or {}).items():
    if k not in base or ts(v) >= ts(base.get(k)):     # 按对象：笔记本这边更晚（或一样）就用笔记本的；服务器上更晚的不盖
        if base.get(k) != v:
            tgt[k] = v; n += 1
if rel.endswith("ready_episodes.json"):
    out.update({k: v for k, v in new.items() if k != "episodes"})
tmp = dst + ".tmp"
os.makedirs(os.path.dirname(dst), exist_ok=True)
json.dump(out, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
os.replace(tmp, dst)
print("merged", rel, n)
"""


def push_control(host: str, force: bool = False) -> dict:
    """NETFIX 接口（总调度 22:2x）：master_rejects.json、ready_episodes.json 变了才推；到服务器按对象合并（K-OPS-Q20），
    服务器上更晚的对象不被笔记本旧值盖回去"""
    import hashlib
    st = jl(STATE, {}) or {}
    hs = st.setdefault(host, {}).setdefault("control_sha", {})
    done = {}
    for rel in CONTROL_FILES:
        f = ROOT / rel
        if not f.is_file():
            continue
        sha = hashlib.sha256(f.read_bytes()).hexdigest()[:16]
        if hs.get(rel) == sha and not force:
            continue
        ssh(host, f"cat > /tmp/ctl_{Path(rel).name}", data=f.read_bytes(), timeout=300, tries=4)
        code = REMOTE_MERGE.replace("__R__", R)
        ssh(host, f"cat > /tmp/ctl_merge.py", data=code.encode(), timeout=120, tries=4)
        out = ssh(host, f"{OFF}/venv/bin/python /tmp/ctl_merge.py {rel} /tmp/ctl_{Path(rel).name}", timeout=120, tries=4)
        hs[rel] = sha
        done[rel] = out.decode("utf-8", "replace").strip()
    js(STATE, st)
    if done:
        log("push_control", host, done)
        try:      # NETFIX：推完在服务器上按分区 ∩ 已准备集 ∩ 笔记本全局暂停 重算本机 producer 的 control
            out = ssh(host, f"cd {R} && {OFF}/venv/bin/python tools/netfix/dispatch.py server-control {host} "
                            f"--laptop-ctrl data/netfix/laptop_ctrl.json --write", timeout=120, tries=3)
            log("server-control", host, out.decode("utf-8", "replace").strip().replace(chr(10), " | ")[-300:])
        except Exception as e:  # noqa: BLE001
            log("server-control error", host, repr(e)[:200])
    return done


def lan_proxy_keepalive() -> str:
    """NETFIX：gpu36 看图服务开放内网给 gpu33（/root/work/fredw/netfix/lan_proxy.sh 幂等保活），每个 health 拍调一次"""
    out = ssh("gpu36", "bash /root/work/fredw/netfix/lan_proxy.sh", timeout=60, tries=2)
    return out.decode("utf-8", "replace").strip()[-200:]


def sync_pause(host: str) -> str | None:
    """全局暂停 / 恢复只对笔记本 producer 执行；每拍把笔记本的暂停状态同步到服务器 producer（NETFIX 接口 5）"""
    c = jl(ROOT / "data/producer/control.json", {}) or {}
    want = "pause" if c.get("paused") else "resume"
    st = jl(STATE, {}) or {}
    hs = st.setdefault(host, {})
    if hs.get("pause_synced") == want:
        return None
    ssh(host, f"cd {R} && {OFF}/venv/bin/python tools/autopilot/producer.py {want} --by SYNC_LAPTOP "
              f"--note '笔记本 producer 全局{want}（{c.get('paused_by') or ''}）同步'", timeout=120, tries=3)
    hs["pause_synced"] = want
    js(STATE, st)
    log("sync_pause", host, want, c.get("paused_by"))
    return want


AUTO_CODE_PUSH = False             # ⤴ 取代“代码一变就推 + 重启”（K-OPS-W14）；要临时打开须总调度批准
RESTART_MIN_GAP_S = 1800           # 30 分钟内最多重启一次
RESIDENT_MODULE_DIRS = ("tools/autopilot/producer.py", "tools/series10_video/", "services/agent/ns_agent/", "services/render_router/ns_render/",
                        "services/recipes/", "packages/", "tools/gen_contract/", "tools/netfix/", "config/")


def resident_imports_changed(since: float) -> list[str]:
    """常驻进程（producer / night / vidgen）实际会加载的文件里，since 之后改过的；改的是别的（测试、文档、前端、本工具）不算"""
    out = []
    for rel, (_s, mt) in local_manifest(CODE_DIRS).items():
        if mt > since and rel.startswith(RESIDENT_MODULE_DIRS) and rel.endswith((".py", ".json", ".yaml", ".yml")):
            out.append(rel)
    return out


def request_restart(host: str, reason: str, by: str = "WORKFLOW resident_sync", urgent: bool = False) -> dict:
    """统一入口（DJ-20）：任何要重启服务器常驻的地方都只写请求，由 loop 每拍 restart_queue.process 合并执行"""
    import restart_queue as RQ
    return RQ.request(host, reason, by, urgent)


def restart_guarded(host: str, drain_timeout_s: int = 900) -> str | None:
    """只在常驻实际 import 的文件变了才重启；30 分钟内最多一次；重启前先排空（producer pause → 等心跳 inflight=0）"""
    st = jl(STATE, {}) or {}
    hs = st.setdefault(host, {})
    last = float(hs.get("last_restart") or 0)
    if time.time() - last < RESTART_MIN_GAP_S:
        log("restart_guarded", host, "30 分钟内已重启过，跳过")
        return None
    changed = resident_imports_changed(last or float(hs.get("last_push") or 0))
    if not changed:
        log("restart_guarded", host, "常驻加载的文件没变，不重启")
        return None
    ssh(host, f"cd {R} && {OFF}/venv/bin/python tools/autopilot/producer.py pause --by RESTART_DRAIN --note '重启前排空'", timeout=120, tries=3)
    import restart_queue as RQ                 # K-OPS-W23：与重启队列同一排空口径（只看 ComfyUI 执行中 + 排队，≤ 90 s；打分积压不算）
    dr = RQ.drain(host, sys.modules[__name__])
    log("restart_guarded", host, "排空", json.dumps(dr, ensure_ascii=False))
    txt = restart(host)
    ssh(host, f"cd {R} && {OFF}/venv/bin/python tools/autopilot/producer.py resume --by RESTART_DRAIN --note '重启完成'", timeout=120, tries=3)
    hs["last_restart"] = time.time()
    js(STATE, st)
    log("restart_guarded", host, f"重启（常驻文件变了 {len(changed)} 个，例 {changed[:3]}）")
    return txt


def puller_took_over(host: str) -> bool:
    """NETFIX 01:5x：puller 接管传图的判据——data/netfix/puller_status.json 里这台的 acked_total 比第一次看到时增长了
    （说明 FACTORY 的 outbox 钩子在服务器上真写、puller 真在拉）。一旦成立就记进状态，此后这台不再做 20 分钟定时 pull"""
    st = jl(STATE, {}) or {}
    hs = st.setdefault(host, {})
    if hs.get("pull_handed_to_puller"):
        return True
    ps = jl(ROOT / "data/netfix/puller_status.json", {}) or {}
    cur = int(((ps.get("hosts") or {}).get(host) or {}).get("acked_total") or 0)
    base = hs.get("puller_acked_base")
    if base is None:
        hs["puller_acked_base"] = cur
        js(STATE, st)
        return False
    if cur > int(base):
        hs["pull_handed_to_puller"] = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "acked_total": cur, "base": base}
        js(STATE, st)
        log("pull", host, f"puller 已接管（acked_total {base} → {cur}），停掉 20 分钟定时 pull")
        return True
    return False


# ---------------------------------------------------------------- DISTILL 编排器每拍（K-OPS-W22，DISTILL 11-02 / 总调度定 decider=code）
AUTOFLOW_TICK = True
AUTOFLOW_EVERY_S = 60
AUTOFLOW_TIMEOUT_S = 1200         # 最长一拍约 2 + 10 + 6 分钟（交稿推进 + line3 打分 600 s + :8800 守护 360 s；总调度 04:1x 定 20 分钟），超时连子进程树一起杀
AUTOFLOW_LOG_EVERY = 30           # 正常拍每 30 拍记一行日志；失败 / 超时 / 输出变化每次都记
# 04:2x 总调度：一拍串行会被 :8800 守护 / line3 打分拖住（04:17:49 那拍卡在 api_restart_guard，last_tick 停 4 分钟）
# → 拆成三条线各自线程 + 子进程（tools/autopilot/tick_parts.py），core 每 60 s 必写 last_tick，line3 / api 上一次没完就跳过
AUTOFLOW_PARTS = {"core": 1200, "line3": 900, "api": 600}      # 线 → 子进程超时（s）


def autoflow_tick_once(timeout_s: int = AUTOFLOW_TIMEOUT_S, dry: bool = False, part: str | None = None) -> dict:
    """跑一拍：part=None → tools/autopilot/run.py tick（整拍串行，备用）；part=core|line3|api → tick_parts.py 的那一条线。
    子进程，输出写文件防管道卡死；超时 taskkill /T"""
    out_p = ROOT / f"ops/logs/autoflow_tick{'_' + part if part else ''}.out"
    out_p.parent.mkdir(parents=True, exist_ok=True)
    if part:
        cmd = [sys.executable, "-X", "utf8", str(ROOT / "tools/autopilot/tick_parts.py"), part] + (["--dry-run"] if dry else [])
    else:
        cmd = [sys.executable, "-X", "utf8", str(ROOT / "tools/autopilot/run.py"), "tick"] + (["--dry-run"] if dry else [])
    t0 = time.time()
    with open(out_p, "wb") as f:
        pr = subprocess.Popen(cmd, cwd=ROOT, stdin=subprocess.DEVNULL, stdout=f, stderr=subprocess.STDOUT,
                              env={**os.environ, "PYTHONUTF8": "1"})
        try:
            rc = pr.wait(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(pr.pid), "/T", "/F"], capture_output=True, timeout=30)
            else:
                pr.kill()
            rc = "timeout"
    try:
        tail = out_p.read_bytes()[-400:].decode("utf-8", "replace").strip()
    except OSError:
        tail = ""
    return {"rc": rc, "secs": round(time.time() - t0, 1), "tail": tail}


def autoflow_thread(every_s: int = AUTOFLOW_EVERY_S, part: str | None = None) -> None:
    """独立线程：每 every_s 秒一拍；上一拍没完不会开下一拍（同一线程串行），不拖住推送循环。part=一条线（见 AUTOFLOW_PARTS）"""
    n, last_tail = 0, None
    tmo = AUTOFLOW_PARTS.get(part, AUTOFLOW_TIMEOUT_S) if part else AUTOFLOW_TIMEOUT_S
    while True:
        t0 = time.time()
        try:
            r = autoflow_tick_once(timeout_s=tmo, part=part)
            n += 1
            bad = r["rc"] != 0
            if bad or r["tail"][-200:] != last_tail or n % AUTOFLOW_LOG_EVERY == 1:
                log("autoflow_tick", part or "all", json.dumps({"n": n, **r, "tail": r["tail"][-200:]}, ensure_ascii=False))
            last_tail = r["tail"][-200:]
        except Exception as e:  # noqa: BLE001
            log("autoflow_tick error", repr(e)[:300])
        time.sleep(max(1.0, every_s - (time.time() - t0)))


def loop(pull_every_s: int = 1200, health_every_s: int = 300):
    """5 分钟一次健康 / 报警；20 分钟一次并回；代码有改动 → 推代码 + 服务器热重启（每台独立，一台断连不影响另一台）"""
    last_pull = {h: 0.0 for h in HOSTS}
    if AUTOFLOW_TICK:                    # DISTILL 编排器每拍：独立守护线程，60 s 一拍（K-OPS-W22）
        import threading
        for part in AUTOFLOW_PARTS:
            threading.Thread(target=autoflow_thread, kwargs={"part": part}, name=f"autoflow_{part}", daemon=True).start()
        log("autoflow_tick", "三条线线程已启动", list(AUTOFLOW_PARTS), AUTOFLOW_EVERY_S, "s 一拍")
    while True:
        for h in HOSTS:
            try:
                health(h)
            except Exception as e:  # noqa: BLE001
                log("health error", h, repr(e)[:200])
            try:                                 # DJ-20 重启队列：合并各方请求，30 分钟一次、先排空，紧急插队记审计（K-OPS-W16）
                import restart_queue as RQ
                RQ.process(h)
            except Exception as e:  # noqa: BLE001
                log("restart_queue error", h, repr(e)[:200])
            try:                                 # NETFIX 接口：控制小文件变了就推（按对象合并 / 快照覆盖），推完 server-control
                push_control(h)
                if h == "gpu36":
                    lan_proxy_keepalive()
            except Exception as e:  # noqa: BLE001
                log("control sync error", h, repr(e)[:200])
            if time.time() - last_pull[h] < pull_every_s:
                continue
            try:
                # 总调度 01:2x（DEBUG_r1：20:55–00:23 因“代码有变”重启服务器常驻 22 次，每次作废租约、不等在途）：
                # loop 不再推代码、不再重启——版本统一走 system_version deploy（服务器运行时归 FACTORY）；这里只做 health / 控制文件 / 并回
                if AUTO_CODE_PUSH:
                    st = jl(STATE, {}) or {}
                    if code_changed_since((st.get(h) or {}).get("last_push") or 0):
                        push(h, code_only=True)
                        if resident_imports_changed(float((st.get(h) or {}).get("last_restart") or 0)):
                            request_restart(h, "代码推送：常驻加载的文件变了", "WORKFLOW resident_sync loop")
                if not puller_took_over(h):          # NETFIX puller 真在拉（acked_total 增长）之后，这台不再定时 pull
                    pull(h)
                last_pull[h] = time.time()
            except Exception as e:  # noqa: BLE001
                log("loop error", h, repr(e)[:300])
        time.sleep(health_every_s)


FRAMES_PREFIX = ("data/renders/", f"{RUN_REL}/assets/", "data/producer/master_rejects.json")


def push_frames(host: str, batch_mb: float = 2.0) -> dict:
    """总调度 18:4x 分工：首帧由笔记本 producer 出，推给服务器当视频输入。上次推之后改过的 data/renders/**（takes.json + 版本图）
    与 series10 assets 的 JSON，小文件优先、每批 ≤ batch_mb、先解到临时目录再搬入；断了下次按清单差异接着推"""
    st = jl(STATE, {}) or {}
    since = float((st.get(host) or {}).get("last_frames_push") or 0)
    if not since:          # 第一次：从服务器副本冻结时刻起（不整盘推 3.9 GB 的 renders）
        since = float(ssh(host, f"cat {OFF}/FREEZE_TS 2>/dev/null || echo 0").strip() or 0)
    t0 = time.time() - 5
    allm = local_manifest(["data/renders", f"{RUN_REL}/assets", "data/producer"])
    loc = {}
    for k, v in allm.items():
        if not k.startswith(FRAMES_PREFIX) or v[1] <= since:
            continue
        if k.startswith("data/renders/") and not k.endswith("takes.json"):
            continue                      # 版本图只推“当前版本”那一张（下面按 takes.json 的 active 补）
        loc[k] = v
    for k in [x for x in loc if x.endswith("takes.json")]:
        d = jl(ROOT / k, {}) or {}
        act = d.get("active") or {}
        for t in d.get("takes") or []:
            if act.get(t.get("stage")) == t.get("n") and t.get("file"):
                f = "data/" + str(t["file"]).replace("\\", "/").lstrip("/")
                if f in allm:
                    loc[f] = allm[f]
    if not loc:
        return {"host": host, "sent": 0}
    rem = remote_manifest(host, sorted({"/".join(k.split("/")[:3]) for k in loc}))
    todo = sorted(diff_push(loc, rem), key=lambda f: loc[f][0])          # 小文件优先（takes.json 先到，图后到）
    est = estimate(todo, loc)
    log("push_frames", host, "差异", est["files"], "个文件", f"{est['mb']} MB", f"预计 {est['eta_min']} 分钟")
    global BATCH
    BATCH = int(batch_mb * 1024 * 1024)
    sent = 0
    for b in batches(todo, loc):
        ssh(host, f"set -e; T=$(mktemp -d {OFF}/.push.XXXXXX); tar xf - -C $T; cp -a $T/. {R}/; rm -rf $T; echo ok",
            data=tar_bytes(b), timeout=BATCH_TIMEOUT_S)
        sent += len(b)
    st = jl(STATE, {}) or {}
    st.setdefault(host, {})["last_frames_push"] = t0
    js(STATE, st)
    log("push_frames", host, "推完", sent, "个文件")
    return {"host": host, "sent": sent}


REBUILD_CHECK = r"""
import json, collections
d = json.load(open("data/pipeline/runs/__RUN__/video/jobs.json"))
c = collections.Counter(); holds = []
for m in d["shots"]:
    for k, v in (m.get("variants") or {}).items():
        c[(v.get("recipe"), str(v.get("status"))[:5])] += 1
        if str(v.get("status")).startswith("hold"):
            holds.append((m["shot"], k, v.get("status")))
    if not m.get("variants"):
        holds.append((m["shot"], "-", m.get("route")))
non_pika_ready = sum(n for (r, st), n in c.items() if r != "i2va_pika_flex" and st == "ready")
import re, glob
FACE = re.compile(r"\b(?:facing|faces|turned toward|turns toward|toward)\s+(?:the\s+)?(?:camera|lens|viewer)\b", re.I)
def _e3(t):
    return bool(FACE.search(" ".join(re.findall(r"The frame keeps[^.]*\.", t or ""))))
rl_e3 = [(m["shot"], k) for m in d["shots"] for k, v in (m.get("variants") or {}).items()
         if str(v.get("status")).startswith("ready") and _e3(v.get("prompt"))]
rl_e3_files = [f for f in glob.glob("data/pipeline/runs/__RUN__/video/prompts/*.txt") if _e3(open(f, encoding="utf-8").read())]
print(json.dumps({"built_at": d.get("built_at"), "shots": len(d["shots"]), "dist": {f"{r}|{st}": n for (r, st), n in c.items()},
                  "non_pika_ready": non_pika_ready, "rl_e3_ready": len(rl_e3), "rl_e3_examples": rl_e3[:10],
                  "rl_e3_prompt_files": len(rl_e3_files), "holds": holds[:200]}, ensure_ascii=False))
"""


def rebuild_jobs(host: str) -> dict:
    """服务器本机按 L-088 重编 jobs.json（读服务器上的导入稿 + 首帧），核对非 Pika ready 变体 = 0"""
    # AUDIT 22:13：重编前把旧 prompts/ 整个挪进隔离区（不删），免得 16:56 的旧编译稿（含“朝向镜头”句）留着
    q = f"data/_quarantine_20261101/prompts_{time.strftime('%Y%m%d-%H%M%S')}"
    out = ssh(host, f"cd {R} && V={RUN_REL}/video && if [ -d $V/prompts ]; then mkdir -p {q} && mv $V/prompts {q}/ && "
                    f"echo quarantined_prompts {q}; fi; mkdir -p $V/prompts; "
                    f"PYTHONUTF8=1 {OFF}/venv/bin/python tools/series10_video/build_jobs.py >/tmp/build_jobs.out 2>&1; "
                    f"tail -c 300 /tmp/build_jobs.out; {OFF}/venv/bin/python -", data=REBUILD_CHECK.replace("__RUN__", RUN_ID).encode(), timeout=2400, tries=3)
    txt = out.decode("utf-8", "replace")
    res = json.loads([ln for ln in txt.splitlines() if ln.startswith("{")][-1])
    js(ROOT / f"data/autopilot/resident/jobs_rebuild_{host}.json", res)
    log("rebuild_jobs", host, json.dumps({k: res[k] for k in ("built_at", "shots", "non_pika_ready", "dist")}, ensure_ascii=False)[:400])
    return res


def video_up(host: str) -> dict:
    """视频侧常驻（总调度 18:4x）：第一级推送 → 新首帧增量 → prep（producer 保持暂停）→ 服务器本机重编 jobs.json，
    非 Pika ready 必须 = 0 → 只起 night（vidgen 由 night 部署；派单前再按政策查，K-OPS-Q24）。
    push 内先过推送前检查（K-OPS-C03），不过抛 PushGateFailed → 不起 night"""
    push(host, tier=1, yes=True)
    v = verify_sha(host)                      # 第一级逐个核 sha（总调度 18:5x）
    if v["mismatch"]:
        raise RuntimeError(f"{host} 第一级 sha 仍有 {len(v['mismatch'])} 个不一致：{v['mismatch'][:5]}")
    push_frames(host)
    push_control(host, force=True)            # master_rejects + ready_episodes 按对象合并（NETFIX 接口）
    res = rebuild_jobs(host)
    if res.get("non_pika_ready"):
        raise RuntimeError(f"{host} 重编后仍有 {res['non_pika_ready']} 个非 Pika ready 变体，不起 night")
    if res.get("rl_e3_ready"):          # AUDIT 20:15：重编后 RL-E3（系统句朝向镜头）必须 0 命中才起 night
        raise RuntimeError(f"{host} 重编后仍有 {res['rl_e3_ready']} 个 ready 变体带朝向镜头的系统句（RL-E3）：{res.get('rl_e3_examples')}")
    txt = ssh(host, f"cd {R} && {OFF}/venv/bin/python ops/offline/resident_prep.py {host} video-only && "
                    f"bash {R}/ops/offline/resident_restart.sh {host} night-only", timeout=300).decode("utf-8", "replace")
    log("video_up", host, txt.strip().replace(chr(10), " | ")[-400:])
    return res


def local_sha(rel: str) -> str:
    import hashlib
    h = hashlib.sha256()
    with open(ROOT / rel, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def tier1_files() -> list[str]:
    loc = local_manifest(CODE_DIRS + ["data"])
    return sorted(f for f, (sz, _t) in loc.items() if tier_of(f, sz) == 1 and (not f.startswith("data/") or (ROOT / f).is_file()))


def verify_sha(host: str, files: list[str] | None = None, fix: bool = True) -> dict:
    """总调度 18:5x：判差异只比大小 / 修改时间不够——第一级推送的文件逐个核 sha256（本地 vs 服务器 sha256sum）；
    不一致 / 服务器缺 → fix 时强制重推这几项再核一次；结果写 data/autopilot/resident/sha_<host>.json（K-OPS-W09）"""
    files = files if files is not None else tier1_files()
    want = {f: local_sha(f) for f in files}
    lst = "\n".join(files).encode()
    raw = ssh(host, f"cd {R} && xargs -d '\\n' -r sha256sum 2>/dev/null; true", data=lst, timeout=900, tries=4).decode("utf-8", "replace")
    got = {}
    for ln in raw.splitlines():
        parts = ln.split(None, 1)
        if len(parts) == 2:
            got[parts[1].strip().lstrip("*")] = parts[0]
    bad = [f for f in files if got.get(f) != want[f]]
    fixed = []
    if bad and fix:
        loc = {f: ((ROOT / f).stat().st_size, (ROOT / f).stat().st_mtime) for f in bad}
        for b in batches(bad, loc):
            ssh(host, f"set -e; T=$(mktemp -d {OFF}/.push.XXXXXX); tar xf - -C $T; cp -a $T/. {R}/; rm -rf $T; echo ok",
                data=tar_bytes(b), timeout=BATCH_TIMEOUT_S)
        again = verify_sha(host, bad, fix=False)
        fixed = [f for f in bad if f not in again["mismatch"]]
        bad = again["mismatch"]
    res = {"host": host, "at": time.strftime("%F %T"), "checked": len(files), "mismatch": bad, "fixed": fixed}
    js(ROOT / f"data/autopilot/resident/sha_{host}.json", res)
    log("verify_sha", host, "核", len(files), "个；不一致", len(bad), "；重推修好", len(fixed))
    return res


ASSET_DIRS = [f"{RUN_REL}/images/refcrops", f"{RUN_REL}/images/refboards"]


def push_required(host: str, batch_mb: float = 2.0) -> dict:
    """出图必需的资产（preflight I3 / I4 读的）：选定设定图、身份脸、单品映射图、首帧作业参考图 + refcrops / refboards。
    23:29 实测：gpu36 producer 起来后 ep02 每 20 s 被 I3“林晚 造型A 没有设定图”挡——IMGFIX 22:05 换回 v2_s202 的设定图与重裁
    refcrops 属 tier 2 大文件没推。按清单比对只推缺的 / 不同的，小文件先（K-OPS-W09 分级、文件级续传）"""
    need = required_data()
    loc_all = local_manifest(["data"])
    files = {f for f in need if f in loc_all}
    # ⤴ 不整目录推 refcrops / refboards（23:30 实测 612 个 325 MB、预计 5 小时）：只推现行作业引用到的（required_data 已含）
    loc = {f: loc_all[f] for f in files}
    rem_dirs = sorted({"/".join(f.split("/")[:-1]) for f in files})
    rem = remote_manifest(host, rem_dirs) if rem_dirs else {}
    todo = sorted(diff_push(loc, rem), key=lambda f: loc[f][0])
    est = estimate(todo, loc)
    log("push_required", host, "差异", est["files"], "个文件", f"{est['mb']} MB", f"预计 {est['eta_min']} 分钟")
    global BATCH
    BATCH = int(batch_mb * 1024 * 1024)
    sent = 0
    bl = batches(todo, loc)
    for i, b in enumerate(bl):
        log("push_required", host, f"batch {i + 1}/{len(bl)} 开始", len(b), "files", f"{sum(loc[f][0] for f in b) / 1e6:.2f} MB")   # 心跳
        ssh(host, f"set -e; T=$(mktemp -d {OFF}/.push.XXXXXX); tar xf - -C $T; cp -a $T/. {R}/; rm -rf $T; echo ok",
            data=tar_bytes(b), timeout=BATCH_TIMEOUT_S)
        sent += len(b)
        log("push_required", host, f"batch {i + 1}/{len(bl)} 完成，累计 {sent} 个")
    rem2 = remote_manifest(host, rem_dirs) if rem_dirs else {}
    left = diff_push(loc, rem2)
    log("push_required", host, "推完", sent, "；复核仍缺", len(left))
    # NETFIX 交接（总调度 23:3x）：资产到位后它自动把笔记本的临时出图覆盖切回服务器——在这里留标记
    mk = ROOT / "data/autopilot/assets_ready.json"
    d = jl(mk, {}) or {}
    # 总调度 01:2x：推送方不写 ready——推完只记 pushed；由 FACTORY 在服务器上跑 dryrun preflight，0 挡后才写 ready=true
    d[host] = {**(d.get(host) or {}), "ready": False, "pushed": not left, "at": time.strftime("%Y-%m-%dT%H:%M:%S"), "sent": sent,
               "missing": left[:50], "checked": len(loc), "by": "WORKFLOW resident_sync.push_required",
               "awaiting": "FACTORY 服务器 dryrun preflight 0 挡后写 ready"}
    js(mk, d)
    return {"host": host, "sent": sent, "estimate": est, "missing": len(left)}


REMOTE_SMOKE = r"""
import json, sys, time, uuid, urllib.request, subprocess, os
R = "__R__"; PORT = __PORT__; OUTDIR = "__OUTDIR__"; SID = "__SID__"
job = json.load(open("/tmp/resident_smoke_job.json"))
def api(path, data=None, ctype="application/json", timeout=120):
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}{path}", data=data, headers={"Content-Type": ctype} if data else {})
    return urllib.request.urlopen(req, timeout=timeout).read()
def upload(rel):
    b = "----rs" + uuid.uuid4().hex; p = os.path.join(R, rel); name = "rs_" + os.path.basename(p)
    head = ("--" + b + "\r\nContent-Disposition: form-data; name=\"image\"; filename=\"" + name + "\"\r\nContent-Type: image/png\r\n\r\n").encode()
    tail = ("\r\n--" + b + "\r\nContent-Disposition: form-data; name=\"overwrite\"\r\n\r\ntrue\r\n--" + b + "--\r\n").encode()
    return json.loads(api("/upload/image", head + open(p, "rb").read() + tail, "multipart/form-data; boundary=" + b))["name"]
g = job["graph"]
for n in g.values():
    for k, v in list((n.get("inputs") or {}).items()):
        if isinstance(v, str) and v.startswith("@"):
            n["inputs"][k] = upload(job["inputs"][v])
    if n["class_type"] == "SaveVideo":
        n["inputs"]["filename_prefix"] = "ns_final/pika_smoke_resident/" + SID
body = {"prompt": g, "client_id": "resident-smoke-" + uuid.uuid4().hex[:6],
        "extra_data": {"ns_tag": {"agent": "WORKFLOW", "kind": "video", "label": "Pika smoke (resident)"}}}
pid = json.loads(api("/prompt", json.dumps(body).encode()))["prompt_id"]
res = {"prompt_id": pid, "t0": time.time()}
json.dump(res, open("/tmp/resident_smoke_result.json", "w"))
while True:
    h = json.loads(api("/history/" + pid))
    if pid in h and h[pid].get("status", {}).get("completed") is not None:
        break
    time.sleep(10)
res["status"] = h[pid]["status"].get("status_str")
for node in h[pid].get("outputs", {}).values():
    for key in ("images", "videos", "gifs"):
        for im in node.get(key) or []:
            if str(im.get("filename", "")).endswith(".mp4"):
                res["file"] = "/".join(x for x in (OUTDIR, im.get("subfolder"), im["filename"]) if x)
res["wall_s"] = round(time.time() - res["t0"], 1)
if res.get("file"):
    meta = json.load(open("/tmp/resident_smoke_meta.json"))
    env = dict(os.environ, OMP_NUM_THREADS="4",
               PATH="/root/claude-kimi-ns-studio-v1/env/ffmpeg/bin:/root/work/fredw/tools_bin:" + os.environ["PATH"])
    r = subprocess.run(["/root/work/fredw/venv_idm/bin/python", R + "/tools/series10_video/score_clip.py", res["file"],
                        "/tmp/resident_smoke.jpg", json.dumps(meta)], capture_output=True, text=True, cwd=R, env=env, timeout=1800)
    line = [x for x in r.stdout.splitlines() if x.startswith("{")]
    res["score"] = json.loads(line[-1]) if line else {"error": r.stderr[-500:]}
json.dump(res, open("/tmp/resident_smoke_result.json", "w"))
"""
SMOKE_LANE = {"gpu33": (8191, "/root/claude-kimi-ns-studio-v1/ComfyUI/output/gpu3"), "gpu36": (8190, "/root/work/fredw/comfy/output/gpu2")}


def smoke(host: str, sid: str = "ep01-S3", wait_s: int = 2400) -> dict:
    """服务器上的 Pika 冒烟：笔记本用生产编译链编一镜（recipe_choice.json 的默认配方）→ 发到服务器 → 服务器本机提交、等出片、
    score_clip 打分（后台进程，短 ssh 轮询结果，扛跳板断连）→ data/autopilot/pika_smoke/<shot>__resident_<host>.json"""
    sys.path[:0] = [str(ROOT / p) for p in ("tools/series10_video", "services/recipes", "packages/schema", "services/agent",
                                             "services/render_router")]
    import build_jobs as B
    reg, specs, frames = B.R.load(), B.load_specs(), B.passed_frames()
    ch = B.recipe_choice()
    rid = ch["face_default"] if specs[sid].faces else ch["noface_default"]
    var = B.compile_variant(specs[sid], reg, rid, 1, "pk_res", frames)
    if var.get("status") != "ready":
        raise RuntimeError(f"{sid} 编译不是 ready：{var.get('status')}")
    meta = {"refs": B.score_refs(specs[sid], reg), "prompt": var["prompt"], "size": None,
            "first_frame": var["inputs"].get("@first_frame")}
    ssh(host, "cat > /tmp/resident_smoke_job.json", data=json.dumps({"graph": var["graph"], "inputs": var["inputs"]}).encode())
    ssh(host, "cat > /tmp/resident_smoke_meta.json", data=json.dumps(meta, ensure_ascii=False).encode())
    port, outdir = SMOKE_LANE[host]
    code = REMOTE_SMOKE.replace("__R__", R).replace("__PORT__", str(port)).replace("__OUTDIR__", outdir).replace("__SID__", sid)
    ssh(host, "cat > /tmp/resident_smoke.py", data=code.encode())
    ssh(host, f"rm -f /tmp/resident_smoke_result.json; setsid nohup {OFF}/venv/bin/python /tmp/resident_smoke.py "
              f"</dev/null >/tmp/resident_smoke.out 2>&1 & echo started")
    log("smoke", host, sid, rid, "已在服务器后台提交")
    t0, res = time.time(), {}
    while time.time() - t0 < wait_s:
        time.sleep(30)
        try:
            res = json.loads(ssh(host, "cat /tmp/resident_smoke_result.json 2>/dev/null || echo '{}'", tries=3) or b"{}")
        except Exception:  # noqa: BLE001
            continue
        if "score" in res or res.get("status") == "error":
            break
    res.update(shot=sid, recipe=rid, host=host, lane=port)
    js(ROOT / "data/autopilot/pika_smoke" / f"{sid}__resident_{host}.json", res)
    log("smoke", host, sid, "结果", json.dumps({k: res.get(k) for k in ("prompt_id", "status", "wall_s")}, ensure_ascii=False))
    return res


ALIVE_SH = ("for n in fwd producer night; do f=__OFF__/run/$n.pid; p=$(cat $f 2>/dev/null); "
            "if [ -n \"$p\" ] && kill -0 $p 2>/dev/null; then echo \"$n $p alive\"; else echo \"$n dead\"; fi; done")


def alive(host: str) -> str:
    return ssh(host, ALIVE_SH.replace("__OFF__", OFF), tries=3).decode().strip()


def recover(hosts=None, smoke_host: str = "gpu33") -> None:
    """跳板恢复后的一键动作（总调度 17:4x）：① 两台常驻进程在不在 ② 推最新代码 + 生产必需数据 ③ 补丁 + 热重启
    ④ 服务器上 Pika 冒烟一镜 ⑤ 起周期并回 loop。每步写 ops/logs/resident_sync.log；一台失败不挡另一台。
    推送前检查不过（K-OPS-C03）→ 整个 recover 停下：不推、不重启、不冒烟、不起 loop"""
    try:
        push_gate(2)
    except PushGateFailed as e:
        log("recover", "停：", str(e)[:400])
        return
    for h in (hosts or list(HOSTS)):
        try:
            log("recover", h, "① 进程：", alive(h).replace("\n", "；"))
            push(h)
            log("recover", h, "③", restart(h).strip().replace("\n", "；")[-300:])
            log("recover", h, "③ 重启后：", alive(h).replace("\n", "；"))
            health(h)
        except Exception as e:  # noqa: BLE001
            log("recover error", h, repr(e)[:300])
    try:
        smoke(smoke_host)
    except Exception as e:  # noqa: BLE001
        log("recover smoke error", repr(e)[:300])
    subprocess.Popen([sys.executable, "-u", str(Path(__file__)), "loop"], cwd=ROOT, stdin=subprocess.DEVNULL,
                     stdout=open(ROOT / "ops/logs/resident_sync.out.log", "a"), stderr=subprocess.STDOUT,
                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "DETACHED_PROCESS", 0))
    log("recover", "⑤ 周期并回 loop 已起")


def main(argv):
    if not argv:
        print(__doc__)
        return 2
    cmd = argv[0]
    if cmd == "push":
        tier = 1 if "--tier1" in argv else 2
        print(push(argv[1], "--code-only" in argv, tier=tier, yes="--yes" in argv))
    elif cmd == "pull":
        print(pull(argv[1]))
    elif cmd == "restart":
        print(restart(argv[1], "producer-only" if "--producer-only" in argv else ("all" if "--all" in argv else DEFAULT_MODE)))
    elif cmd == "switch":        # 一条命令切到常驻：两台各 push（代码 + 数据）→ prep + 重启 → health；一台失败不影响另一台
        for h in (argv[1:] or list(HOSTS)):
            try:
                push(h)
                restart(h)
                print(json.dumps(health(h), ensure_ascii=False))
            except Exception as e:  # noqa: BLE001
                log("switch error", h, repr(e)[:300])
    elif cmd == "auto":          # 跳板不通时等它恢复（每 30 s 测一次 TCP），通了就 switch 再进 loop（总调度 16:55 指令的无人值守版）
        import socket
        while True:
            try:
                socket.create_connection(("sz194.instameta.org", 19422), timeout=8).close()
                break
            except OSError:
                time.sleep(30)
        log("auto", "跳板恢复 → switch")
        main(["switch"])
        loop()
    elif cmd == "recover":
        recover(argv[1:] or None)
    elif cmd == "smoke":
        print(json.dumps(smoke(argv[1], *(argv[2:3] or ["ep01-S3"])), ensure_ascii=False)[:1500])
    elif cmd == "alive":
        print(alive(argv[1]))
    elif cmd == "bringup":       # 总调度 18:23：跳板时通时断也要尽快起卡——等跳板 → 第一级推送 → producer-only 起常驻 → health；失败重来
        import socket
        todo = argv[1:] or list(HOSTS)
        while todo:
            try:
                socket.create_connection(("sz194.instameta.org", 19422), timeout=8).close()
            except OSError:
                time.sleep(20)
                continue
            for h in list(todo):
                try:
                    push(h, tier=1, yes=True)
                    restart(h, "producer-only")
                    a = alive(h)
                    log("bringup", h, a.replace(chr(10), "；"))
                    if "producer" in a and "producer dead" not in a:
                        todo.remove(h)
                        try:
                            health(h)
                        except Exception as e:  # noqa: BLE001
                            log("bringup health error", h, repr(e)[:200])
                except Exception as e:  # noqa: BLE001
                    log("bringup error", h, repr(e)[:300])
            if todo:
                time.sleep(20)
        log("bringup", "两台 producer 已起（night 等 jobs.json 按 L-088 重编后再起）")
    elif cmd == "verify_sha":
        print(json.dumps(verify_sha(argv[1]), ensure_ascii=False)[:1500])
    elif cmd == "push_control":
        print(push_control(argv[1], force="--force" in argv))
    elif cmd == "push_required":            # 可给多台：按顺序一台推完再推下一台（共用跳板带宽），断了重试
        for h in argv[1:]:
            for _try in range(5):
                try:
                    print(push_required(h))
                    break
                except Exception as e:  # noqa: BLE001
                    log("push_required error", h, repr(e)[:200])
                    time.sleep(60)
    elif cmd == "push_frames":
        print(push_frames(argv[1]))
    elif cmd == "rebuild_jobs":
        print(json.dumps(rebuild_jobs(argv[1]), ensure_ascii=False)[:2000])
    elif cmd == "video_up":       # 跳板恢复后：两台各 video_up（失败重来，一台不挡另一台）
        import socket
        todo = argv[1:] or list(HOSTS)
        while todo:
            try:
                socket.create_connection(("sz194.instameta.org", 19422), timeout=8).close()
            except OSError:
                time.sleep(20)
                continue
            for h in list(todo):
                try:
                    video_up(h)
                    todo.remove(h)
                except Exception as e:  # noqa: BLE001
                    log("video_up error", h, repr(e)[:300])
            if todo:
                time.sleep(30)
        log("video_up", "两台视频常驻已起（只派重编后 jobs.json 里的 Pika 变体）")
    elif cmd == "health":
        print(json.dumps(health(argv[1]), ensure_ascii=False, indent=1))
    elif cmd == "loop":
        loop()
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
