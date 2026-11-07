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
  lifecycle [--dry|--apply] W18：主剧阶段 ≥ 出图 → 自动起 producer（笔记本 restart_producer.ps1 / 服务器 request_restart）；≥ 尾帧 → night
  run_sync [HOST…] [--dry]  W40：在产剧 run 级产物（sop_gate 证据 / 派生参考图 / asset_jobs / 导入稿 / 资产清单）增量推服务器（loop 每 2 分钟）
  vqa [--dry]               W40：gpu36 看图 :8870 + watcher + 人数检测 :8893（GPU1，不碰 GPU2）+ 其内网入口，不在就拉起；gpu33 内网入口；score_infra 上限报警（loop 每 5 分钟）
  loop                      常驻：5 分钟一次 health；20 分钟两台各 pull 一次；代码有改动就 push --code-only + restart
不删任何文件（两边都不删）。日志 ops/logs/resident_sync.log，状态 data/autopilot/resident_sync.json。
"""
from __future__ import annotations

import io
import json
import os
import re
import shutil
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
# SYSARCH 4-2 ②（K-OPS-W26）：服务器根目录 / venv / 渲染道一律读 config/factory/hosts.json（tools/factory/hosts.py），读不到就 raise
sys.path.insert(0, str(ROOT / "tools/factory"))
import hosts as _HOSTS  # noqa: E402
SERVERS = ("gpu33", "gpu36")


def _server_root() -> str:
    roots = {h: _HOSTS.server_root(h) for h in SERVERS}
    if len(set(roots.values())) != 1:            # 本工具的远程模板只用一个仓库根：两台不一致就失败关闭
        raise _HOSTS.HostsError(f"两台服务器 repo 不一致：{roots}")
    return roots[SERVERS[0]]


R = _server_root()
OFF = R.rsplit("/", 1)[0]                        # 离线根（FREEZE_TS / run / logs / venv 都在它下面）
PY = {h: _HOSTS.python(h) for h in SERVERS}
def _partition_live(root: Path) -> dict:
    """L-209 S2.3：分区唯一一份（tools/netfix/partition.load：过期借道 / 临时 hold 已剔除）"""
    d = str(Path(__file__).resolve().parents[1] / "netfix")
    if d not in sys.path:
        sys.path.insert(0, d)
    import partition as PT  # noqa: PLC0415
    return PT.load(root)


def _partition_hosts() -> dict[str, list[int]]:
    """按集归属读分区唯一一份 data/state/netfix/partition.json（L-209 S2.3；images ∪ video；laptop 不是服务器，不在内）；读不到用旧分集"""
    try:
        part = _partition_live(ROOT)
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
SKIP_NAMES = {"control.json", "heartbeat.json", "producer.pid", "registry.json", "night.pid", "night_control.json",
              "run_phase.json", "registry_merged.json"}   # S2.4：run 级阶段只由笔记本算，不回拉；S2.5：合并登记表同（只推不拉）
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


def run_required_data(run: str) -> set[str]:
    """一部非主剧的出图必需文件：用它自己的导入稿跑 preflight_deps（frame_job.build_first 实际读的参考图），
    加它在 asset_refs.json 里登记的造型 / 设定图 / 每镜造型文件、设定图登记里指向的图，以及全部解析层（resolution_layers.yaml）"""
    sys.path.insert(0, str(ROOT / "tools/pipeline"))
    for p in ("services/agent", "services/render_router", "packages/schema"):
        if str(ROOT / p) not in sys.path:
            sys.path.insert(0, str(ROOT / p))
    import image_jobs as IJ
    import preflight_deps as PD
    from ns_agent import asset_refs as AR
    out = set(PD.preflight_deps(script=IJ.load_import(run), include_sources=False)["files"])
    out.add(f"data/import/runs/{run}/script_v2.json")
    for key in ("looks_file", "sheets_file", "shot_looks_file"):
        for f in AR.chain_files(run, key):
            rel = f.relative_to(AR.ROOT).as_posix()
            out.add(rel)
            if key == "sheets_file":
                try:
                    for rec in (json.loads(f.read_text(encoding="utf-8")) or {}).values():
                        if isinstance(rec, dict) and rec.get("file"):
                            out.add(str(rec["file"]).replace("\\", "/"))
                except (OSError, ValueError) as e:
                    log("run_required_data", run, "设定图登记读不了", rel, repr(e)[:120])
    try:
        import yaml
        reg = yaml.safe_load((ROOT / "config/policies/resolution_layers.yaml").read_text(encoding="utf-8")) or {}
        out |= {x["path"] for x in (reg.get("layers") or []) + (reg.get("global") or [])}
    except (OSError, ValueError, ImportError) as e:
        log("run_required_data", run, "解析层登记读不了", repr(e)[:120])
    return {f for f in out if (ROOT / f).is_file()}


def required_data() -> set[str]:
    """生产必需、服务器副本可能缺的数据：remote_preflight 的资产图清单（选定设定图 / 身份脸 / 单品图）+ 首帧作业参考图"""
    sys.path.insert(0, str(ROOT / "tools/pipeline"))
    # 总调度 01:2x（K-OPS-W13）：清单 = producer preflight（I1–I9）实际用到的文件——直接复用 frame_job.build_first 的作业依赖
    # （tools/pipeline/preflight_deps.py），不再自己另列一份（01:14 场景底图漏列，服务器 I5 每单挡）
    import preflight_deps as PD
    out = set(PD.preflight_deps()["files"])
    for run in [r for r in _RUNS.list_runs(status="producing") if r != RUN_ID]:   # K-OPS-W28：每部在产的非主剧也算（第二季造型图 / 登记）
        try:
            out |= run_required_data(run)
        except Exception as e:  # noqa: BLE001
            log("required_data", run, "第二季等额外剧依赖算不出", repr(e)[:200])
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
LINK_KBPS = 1500                                               # FIX-ORCH O4（11-06）：主连接 / 独立 hk 连接实测 MB/s 级（11-01 跳板 17–20 KB/s 已过时，按旧值估 25 MB 要 23 分钟 → 推送被吓退）


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


def atomic_install_cmd(dest: str) -> str:
    """A-12（FACTORY 11-02 21:3x）：临时目录 $T 里解好的文件逐个 mv 到仓库（同一文件系统 rename = 原子替换），
    读方永远读到整份旧文件或整份新文件；以前 cp -a 原地覆盖，takes.json 等可能被读到写了一半。最后清掉空的临时目录"""
    return (f'(cd $T && find . -type f -print0 | while IFS= read -r -d "" f; do mkdir -p "{dest}/$(dirname "$f")"; '
            f'mv -f "$f" "{dest}/$f"; done); rm -rf $T')


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
            ssh(host, f"set -e; T=$(mktemp -d {OFF}/.push.XXXXXX); tar xf - -C $T; " + atomic_install_cmd(R) + "; echo ok",
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


def restart_vidgen(host: str) -> str:
    """FIX-A 11-05（gpu36 vidgen 跑了 37 h 的旧代码）：night-only / all 重启只换 night.py，不换视频执行器 vidgen。
    笔记本侧调 tools/series10_video/deploy.py stop → start（当前剧；deploy 自己经 rssh 在该机执行）。失败只记日志、不挡重启。"""
    outs = []
    for act in ("stop", "start"):
        try:
            r = subprocess.run([sys.executable, str(ROOT / "tools/series10_video/deploy.py"), act, host], cwd=str(ROOT),
                               capture_output=True, timeout=180)
            outs.append(f"vidgen {act}: " + (r.stdout + r.stderr).decode("utf-8", "replace").strip()[-120:])
        except Exception as e:  # noqa: BLE001  # arch-ok: vidgen 重启失败不阻断 night 重启，记进输出让人看到
            outs.append(f"vidgen {act} 失败：{e!r}"[:160])
    return chr(10).join(outs)


def restart(host: str, mode: str = DEFAULT_MODE) -> str:
    prep_arg = "video-only" if mode == "night-only" else ""
    out = ssh(host, f"cd {R} && {PY[host]} ops/offline/resident_prep.py {host} {prep_arg} && bash {R}/ops/offline/resident_restart.sh {host} {mode}",
              timeout=300)
    txt = out.decode("utf-8", "replace")
    if mode in ("night-only", "all"):
        txt += chr(10) + restart_vidgen(host)
    log("restart", host, txt.strip().replace("\n", " | ")[-400:])
    return txt


# ---------------------------------------------------------------- 当前版本视频必拉（K-OPS-W24，总调度 11-02 派；DEBUG-RSI 查出缺 68 条）
# 22:2x 跳板慢时 pull 只拉成片 / manifest 入选 / 放大版 / 预览 mp4，takes.json 里 active.video 指向的版本视频从不回笔记本，
# 胶片总览悬停预览没有片。现走香港线路，active.video 一律拉回，拉完按服务器报的大小核对。
REMOTE_ACTIVE_VIDEOS = r"""
import json, glob, os
out = {}
for f in glob.glob("data/renders/ep*/*/takes.json") + glob.glob("data/renders/*/ep*/*/takes.json"):   # W-SCAN 11-07: V2 = renders/<run>/epNN/Sx
    try:
        d = json.load(open(f, encoding="utf-8"))
    except Exception:
        continue
    n = (d.get("active") or {}).get("video")
    if n is None:
        continue
    t = next((x for x in d.get("takes") or [] if x.get("n") == n and x.get("stage") == "video"), None)
    if not t or not t.get("file"):
        continue
    p = "data/" + str(t["file"]).lstrip("/")
    if os.path.isfile(p):
        out[p] = os.path.getsize(p)
print(json.dumps(out))
"""


def active_video_paths(doc: dict) -> list[str]:
    """一份 takes.json → 当前版本视频的仓库相对路径（data/renders/...）；没有当前视频返回 []"""
    n = ((doc or {}).get("active") or {}).get("video")
    if n is None:
        return []
    t = next((x for x in doc.get("takes") or [] if x.get("n") == n and x.get("stage") == "video"), None)
    return ["data/" + str(t["file"]).lstrip("/")] if t and t.get("file") else []


def remote_active_videos(host: str) -> dict[str, int]:
    """服务器上 takes.json 的 active.video 且文件在 → {相对路径: 字节数}"""
    raw = ssh(host, f"cd {R} && python3 -", data=REMOTE_ACTIVE_VIDEOS.encode(), timeout=300, tries=3)
    txt = raw.decode("utf-8", "replace")
    return json.loads([ln for ln in txt.splitlines() if ln.startswith("{")][-1])


def _local_ok(rel: str, size: int) -> bool:
    p = ROOT / rel
    return p.is_file() and p.stat().st_size == size


def pull_active_videos(host: str, dry: bool = False, batch_mb: float = 64.0) -> dict:
    """补拉：服务器 active.video 里笔记本没有（或大小不符）的片，分批 tar 拉回，按服务器大小核对后原子写进仓库对应路径"""
    av = remote_active_videos(host)
    todo = sorted(k for k, v in av.items() if not _local_ok(k, v))
    res = {"host": host, "active_videos": len(av), "missing": len(todo), "got": 0, "bad": [], "mb": round(sum(av[k] for k in todo) / 1e6, 1)}
    if dry or not todo:
        res["todo"] = todo[:200]
        log("pull_active_videos", host, json.dumps({k: res[k] for k in ("active_videos", "missing", "mb")}, ensure_ascii=False), "dry" if dry else "")
        return res
    global BATCH
    old, BATCH = BATCH, int(batch_mb * 1024 * 1024)
    try:
        for b in batches(todo, {k: (av[k],) for k in todo}):
            blob = ssh(host, f"cd {R} && tar cf - -T - 2>/dev/null; true", data="\n".join(b).encode(), timeout=1800)
            try:
                with tarfile.open(fileobj=io.BytesIO(blob)) as tf:
                    for m in tf.getmembers():
                        if not m.isfile() or ".." in m.name or m.name.startswith("/") or m.name not in av:
                            continue
                        data = tf.extractfile(m).read()
                        if len(data) != av[m.name]:
                            res["bad"].append(m.name)
                            continue
                        p = ROOT / m.name
                        p.parent.mkdir(parents=True, exist_ok=True)
                        tmp = p.with_name(p.name + ".pulltmp")
                        tmp.write_bytes(data)
                        os.replace(tmp, p)
                        os.utime(p, (m.mtime, m.mtime))
                        res["got"] += 1
            except tarfile.TarError as e:
                log("pull_active_videos", host, "批次 tar 读不全", repr(e)[:120])
                res["bad"] += b
    finally:
        BATCH = old
    res["verified"] = sum(1 for k in todo if _local_ok(k, av[k]))
    log("pull_active_videos", host, json.dumps({k: res[k] for k in ("active_videos", "missing", "got", "verified", "mb")}, ensure_ascii=False),
        "不收", len(res["bad"]))
    return res


# ---------------------------------------------------------------- 非主剧临时 control 按 partition 自动生成（K-OPS-W25 修订，总调度 12:0x）
# NETFIX 的 dispatch.py 按 run 写 control 上线前的过渡：每拍从 config/netfix/partition.json ∩ 该 run 已准备好的集算 only，
# hold 同主剧规则；内容变了才推。服务器上已有、但不是本函数写的 control（dispatch_by.by 不以 TEMP_CTL_BY 开头）一律不碰。
TEMP_CTL_BY = "WORKFLOW 临时"


def run_control_for(host: str, run: str, part: dict | None = None, ready: dict | None = None) -> dict:
    sys.path.insert(0, str(ROOT / "tools/netfix"))
    import dispatch as D
    part = part or D.partition()
    rs = D.ready_shots(D.run_ready(run) if ready is None else ready)
    eps = sorted(set(part["images"].get(host) or []))
    only = sorted({x.split("/", 1)[1] if x.startswith(run + "/") else x for e in eps if e in rs for x in rs[e]
                   if "/" not in x or x.startswith(run + "/")})
    hold = sorted({ln for h, ls in (part.get("lanes") or {}).items() if h != host for ln in ls} | set(part.get("retired_lanes") or []))
    return {"paused": False, "run": run, "only": only or ["__none__"], "hold_lanes": hold,
            "dispatch_by": {"by": f"{TEMP_CTL_BY}（resident_sync.sync_run_controls，按 partition.json 自动生成；dispatch.py 按 run 写 control 上线后停用）",
                            "host": host, "partition_eps": eps, "rule": "K-OPS-N04 同一按集分区；K-OPS-W25 防两台重复派"}}


def extra_runs_local() -> list[str]:
    return [r for r in _RUNS.list_runs(status="producing") if r != RUN_ID]


def sync_run_controls(host: str) -> list[str]:
    """每个非主在产剧：算 control → 和上次推的比 → 变了才推（只覆盖本函数写的或缺失的文件）"""
    st = jl(STATE, {}) or {}
    hs = st.setdefault(host, {}).setdefault("run_controls", {})
    pushed = []
    for run in extra_runs_local():
        ctl = run_control_for(host, run)
        key = json.dumps({k: ctl[k] for k in ("only", "hold_lanes", "paused")}, sort_keys=True)
        if hs.get(run) == key:
            continue
        body = json.dumps(ctl, ensure_ascii=False, indent=1).encode()
        rel = f"data/producer/runs/{run}/control.json"
        out = ssh(host, f"cd {R} && mkdir -p data/producer/runs/{run} && "
                        f"if [ -f {rel} ] && ! grep -q '{TEMP_CTL_BY}' {rel}; then echo SKIP_OWNED; else "
                        f"cat > {rel}.new && mv {rel}.new {rel} && echo PUSHED; fi", data=body, timeout=60, tries=2).decode("utf-8", "replace")
        if "PUSHED" in out:
            hs[run] = key
            pushed.append(run)
            log("run_control", host, run, "only", len(ctl["only"]), "eps", ctl["dispatch_by"]["partition_eps"])
        elif "SKIP_OWNED" in out:
            hs[run] = key
            log("run_control", host, run, "服务器上已有非临时 control（dispatch.py 接管），不覆盖")
    js(STATE, st)
    return pushed


def ensure_runs(host: str) -> str:
    """服务器上给 runs.json 里 producing 的非主剧各保一个 producer serve --run（ops/offline/ensure_runs.sh，K-OPS-W25）；
    有新拉起的才记日志"""
    out = ssh(host, f"bash {R}/ops/offline/ensure_runs.sh {host}", timeout=180, tries=2).decode("utf-8", "replace").strip()
    if "started" in out or "DEAD" in out:
        log("ensure_runs", host, out.replace("\n", " | ")[-300:])
    return out


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
    try:                                     # K-OPS-W24：takes.json 当前版本视频一律拉回（笔记本没有 / 大小不符的都拉，不只本轮新改的）
        for rel, size in remote_active_videos(host).items():
            if rel in files or not _local_ok(rel, size):
                files.setdefault(rel, size)
                need_mp4.add(rel)
    except Exception as e:  # noqa: BLE001
        log("pull", host, "active.video 清单取不到", repr(e)[:160])
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
    out["hb"] = json.load(open(R + "/__PD__/heartbeat.json"))
except Exception:
    out["hb"] = None
out["ns"] = 0
for _f in ("night_state.json", "night_heartbeat.json"):   # FIX-NIGHT2：night 第一轮 5–15 min 不写 state，心跳文件在子步骤之间写
    try:
        out["ns"] = max(out["ns"], os.stat(R + "/data/pipeline/runs/__RUN__/video/" + _f).st_mtime)
    except OSError:
        pass
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
    out["ctrl"] = json.load(open(R + "/__PD__/control.json"))
except Exception:
    out["ctrl"] = {}
print(json.dumps(out))
"""
IDLE_ALERT_MIN = 10        # 总调度 16:55：GPU 空闲但有待派任务超过 10 分钟要报警
def _lanes_from_hosts() -> dict[str, dict[str, int]]:
    """{host: {gpu: 本机 comfy 端口}}：hosts.json 里启用的出图道（gpu33 GPU2 坏卡、gpu36:2 看图卡 enabled=false，都不列）"""
    out = {h: {str(rec["gpu"]): int(rec["comfy_port"]) for rec in _HOSTS.lanes(h, role="image").values()} for h in SERVERS}
    if not all(out.values()):
        raise _HOSTS.HostsError(f"hosts.json 有服务器没有启用的出图道：{out}")
    return out


LANES = _lanes_from_hosts()


def producer_rel(run: str) -> str:
    """该剧 producer 目录（相对项目根）：legacy 剧 = data/producer，其它 = data/producer/runs/<run>（= runs.producer_dir）"""
    return "data/producer" if _RUNS.is_legacy(run) else f"data/producer/runs/{run}"


def producer_run_mismatch(hb: dict, run: str) -> str | None:
    """ISS-1103-033310-5833：心跳里的 run 身份和应跑的剧对不上 → 返回人话原因；None = 对得上（或心跳是空的，交给心跳超时报警）"""
    if not hb or hb.get("exited"):
        return None
    got = hb.get("run")
    if not got:
        return f"心跳没有 run 身份（旧代码，按启动时缓存的剧在跑），应为 {run}：需要 restart 一次"
    return None if got == run else f"在为 {got} 跑，应为 {run}"


def health(host: str) -> dict:
    """服务器侧健康：每张卡利用率、本机 ComfyUI 队列、producer 心跳、night_state 更新时间、可派镜数；
    空闲但有活 ≥ 10 分钟 → data/qa/alerts.jsonl（与 infra_watchdog 同一报警文件 / 同一开关语义）"""
    probe = (REMOTE_HEALTH.replace("__RUN__", RUN_ID).replace("__R__", R).replace("__HOST__", host).replace("__LANES__", json.dumps(LANES[host]))
             .replace("__PD__", producer_rel(RUN_ID)))     # ISS-1103-033310-5833：看主剧自己的 producer 目录，不看 V1 的 data/producer
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
           "producer_paused": hb.get("paused"), "producer_run": hb.get("run"), "night_state_age_min": round((now - int(d.get("ns") or 0)) / 60, 1),
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
    wrong = producer_run_mismatch(hb, RUN_ID)
    res["producer_run_mismatch"] = wrong
    W.alert(ws, f"A-RESIDENT-PROD-RUN-{host}", bool(wrong), "crit", f"{host} 常驻 producer {wrong}")
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
if rel in ("data/netfix/laptop_ctrl.json", "data/netfix/override_state.json") or rel.endswith("/episode_state.json") or rel.endswith("/run_phase.json") or rel.endswith("/registry_merged.json"):   # 快照：整文件覆盖（S2.2 集关闭标记 / S2.4 run 级阶段 / S2.5 合并登记表只有笔记本算）
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


def episode_state_tick() -> None:
    """L-209 S2.2（W-S22）：每部在产剧重算 data/pipeline/runs/<run>/episode_state.json（变了才原子写；off = 不写）。出错只记日志"""
    try:
        import episode_state as ES
    except ImportError as e:   # arch-ok: 模块没部署 = 不算（执行器读不到文件 = 没有集关闭，旧行为）
        log("episode_state", "模块缺", repr(e)[:160])
        return
    for run in run_sync_runs():
        try:
            ES.compute(run, ROOT, log=log)
        except Exception as e:  # noqa: BLE001
            log("episode_state", run, "重算失败", repr(e)[:200])


_RP_LAST = {"t": 0.0}


def run_phase_tick(min_gap_s: float = 20.0) -> None:
    """L-209 S2.4（W-S234）：每部在产剧算 data/pipeline/runs/<run>/run_phase.json（变了或满 5 分钟才原子写；off = 不写）。
    push_control 每台调一次 → min_gap_s 内不重复算。出错只记日志"""
    if time.time() - _RP_LAST["t"] < min_gap_s:
        return
    _RP_LAST["t"] = time.time()
    try:
        import run_phase as RP
    except Exception as e:   # noqa: BLE001  # arch-ok: 模块没部署 / 坏了 = 不算（服务器读不到中心文件 = 本机自算，旧行为）
        log("run_phase", "模块缺", repr(e)[:160])
        return
    RP.tick(run_sync_runs(), ROOT, log=log)


_RM_LAST = {"t": 0.0}


def registry_merged_tick(min_gap_s: float = 20.0) -> None:
    """L-209 S2.5（W-S25）：每部在产剧把两台拉回的登记表合并成 data/producer/runs/<run>/registry_merged.json（唯一合并函数
    registry_merged.merge；变了或满 5 分钟才原子写；off = 不写）。push_control 每台调一次 → min_gap_s 内不重复算。出错只记日志"""
    if time.time() - _RM_LAST["t"] < min_gap_s:
        return
    _RM_LAST["t"] = time.time()
    try:
        import registry_merged as RMG
    except Exception as e:   # noqa: BLE001  # arch-ok: 模块没部署 / 坏了 = 不算（读者读不到合并表 = 退回本机登记表，旧行为）；复审 11-07 不能拖垮 push_control
        log("registry_merged", "模块缺", repr(e)[:160])
        return
    RMG.tick(run_sync_runs(), ROOT, log=log)


def push_control(host: str, force: bool = False) -> dict:
    """NETFIX 接口（总调度 22:2x）：master_rejects.json、ready_episodes.json 变了才推；到服务器按对象合并（K-OPS-Q20），
    服务器上更晚的对象不被笔记本旧值盖回去"""
    import hashlib
    episode_state_tick()                 # L-209 S2.2：推之前先按口径重算集关闭标记（含自动重开）
    run_phase_tick()                     # L-209 S2.4：推之前算一次 run 级阶段（两台登记表合并）
    registry_merged_tick()               # L-209 S2.5：推之前合并一次登记表（推两台只读）
    st = jl(STATE, {}) or {}
    hs = st.setdefault(host, {}).setdefault("control_sha", {})
    done = {}
    for rel in control_files():          # W40：含每部在产剧的 run 级 ready 清单（L-178）
        f = ROOT / rel
        if not f.is_file():
            continue
        sha = hashlib.sha256(f.read_bytes()).hexdigest()[:16]
        if hs.get(rel) == sha and not force:
            continue
        tmpn = "/tmp/ctl_" + rel.replace("/", "__")        # W40：旧路径与 run 级都叫 ready_episodes.json，临时名按全路径区分
        ssh(host, f"cat > {tmpn}", data=f.read_bytes(), timeout=300, tries=4)
        code = REMOTE_MERGE.replace("__R__", R)
        ssh(host, f"cat > /tmp/ctl_merge.py", data=code.encode(), timeout=120, tries=4)
        out = ssh(host, f"{PY[host]} /tmp/ctl_merge.py {rel} {tmpn}", timeout=120, tries=4)
        hs[rel] = sha
        done[rel] = out.decode("utf-8", "replace").strip()
    js(STATE, st)
    if done:
        log("push_control", host, done)
    if {k for k in done if not k.endswith("/registry_merged.json")}:     # S2.5：只有合并登记表变了不用重算服务器 control
        try:      # NETFIX：推完在服务器上按分区 ∩ 已准备集 ∩ 笔记本全局暂停 重算本机 producer 的 control
            out = ssh(host, f"cd {R} && {PY[host]} tools/netfix/dispatch.py server-control {host} "
                            f"--laptop-ctrl data/netfix/laptop_ctrl.json --write", timeout=120, tries=3)
            log("server-control", host, out.decode("utf-8", "replace").strip().replace(chr(10), " | ")[-300:])
        except Exception as e:  # noqa: BLE001
            log("server-control error", host, repr(e)[:200])
    return done


def lan_proxy_keepalive() -> str:
    """NETFIX：gpu36 看图服务开放内网给 gpu33（/root/work/fredw/netfix/lan_proxy.sh 幂等保活），每个 health 拍调一次"""
    out = ssh("gpu36", "bash /root/work/fredw/netfix/lan_proxy.sh", timeout=60, tries=2)
    return out.decode("utf-8", "replace").strip()[-200:]


def review_lan_proxy_host() -> str | None:
    """L-207：审图位内网入口要起在哪台（config/pipeline/lane_roles.json enabled + review.lan_proxy.enabled → review.lane 的主机）；关 / 没配 = None"""
    d = jl(ROOT / "config/pipeline/lane_roles.json", {}) or {}
    rv = d.get("review") or {}
    if not d.get("enabled") or not (rv.get("lan_proxy") or {}).get("enabled"):
        return None
    return str(rv.get("lane") or "").split(":")[0] or None


def review_lan_proxy_keepalive(host: str | None = None) -> str:
    """L-207：gpu33 审图位看图分发器开放内网给 gpu36 视频打分（仓库里的 tools/netfix/review_lan_proxy.sh，幂等保活；参数全在 lane_roles.json）。
    host 不是审图台 / 开关关 = 不跑（返回 skip）"""
    want = review_lan_proxy_host()
    host = host or want
    if not want or host != want:
        return "skip"
    out = ssh(host, f"cd {R} && bash tools/netfix/review_lan_proxy.sh", timeout=60, tries=2)
    return out.decode("utf-8", "replace").strip()[-200:]


def sync_pause(host: str) -> str | None:
    """全局暂停 / 恢复只对笔记本 producer 执行；每拍把笔记本的暂停状态同步到服务器 producer（NETFIX 接口 5）"""
    c = jl(ROOT / "data/producer/control.json", {}) or {}
    want = "pause" if c.get("paused") else "resume"
    st = jl(STATE, {}) or {}
    hs = st.setdefault(host, {})
    if hs.get("pause_synced") == want:
        return None
    ssh(host, f"cd {R} && {PY[host]} tools/autopilot/producer.py {want} --by SYNC_LAPTOP "
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
    ssh(host, f"cd {R} && {PY[host]} tools/autopilot/producer.py pause --by RESTART_DRAIN --note '重启前排空'", timeout=120, tries=3)
    import restart_queue as RQ                 # K-OPS-W23：与重启队列同一排空口径（只看 ComfyUI 执行中 + 排队，≤ 90 s；打分积压不算）
    dr = RQ.drain(host, sys.modules[__name__])
    log("restart_guarded", host, "排空", json.dumps(dr, ensure_ascii=False))
    txt = restart(host)
    ssh(host, f"cd {R} && {PY[host]} tools/autopilot/producer.py resume --by RESTART_DRAIN --note '重启完成'", timeout=120, tries=3)
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
AUTOFLOW_PARTS = {"core": 1200, "line3": 900, "api": 960}      # 线 → 子进程超时（s）；api 必须 > flow.api_restart_tick 900 > ps1 600（RESTARTFIX-O：外层先超时 taskkill /T 会连刚起的 API 一起杀）


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


FACTORY_SYNC_EVERY_S = 600        # FACTORY 11-02：每 10 分钟 tools/factory/sync.py auto（期望 refs 表变了才补推），超时 900 s
FACTORY_SYNC_TIMEOUT_S = 900


def factory_sync_thread(every_s: int | None = None) -> None:
    every_s = every_s or FACTORY_SYNC_EVERY_S
    while True:
        t0 = time.time()
        out_p = ROOT / "ops/logs/factory_sync_auto.out"
        try:
            with open(out_p, "wb") as f:
                pr = subprocess.Popen([sys.executable, "-X", "utf8", str(ROOT / "tools/factory/sync.py"), "auto"], cwd=ROOT,
                                      stdin=subprocess.DEVNULL, stdout=f, stderr=subprocess.STDOUT, env={**os.environ, "PYTHONUTF8": "1"})
                try:
                    rc = pr.wait(timeout=FACTORY_SYNC_TIMEOUT_S)
                except subprocess.TimeoutExpired:
                    if os.name == "nt":
                        subprocess.run(["taskkill", "/PID", str(pr.pid), "/T", "/F"], capture_output=True, timeout=30)
                    else:
                        pr.kill()
                    rc = "timeout"
            tail = out_p.read_bytes()[-200:].decode("utf-8", "replace").strip()
            log("factory_sync_auto", json.dumps({"rc": rc, "secs": round(time.time() - t0, 1), "tail": tail}, ensure_ascii=False))
        except Exception as e:  # noqa: BLE001
            log("factory_sync_auto error", repr(e)[:300])
        time.sleep(max(1.0, every_s - (time.time() - t0)))


RELEASE_TICK = True                # W17 RELEASE-AUTO：发版流水线每拍检查（开关以 config/pipeline/release.json enabled 为准）


def release_thread(every_s: int | None = None) -> None:
    """W17：tools/autopilot/release_tick.tick()——release_request.json 复审全过 → 拼树 → cut --dry → cut → deploy --verify，
    deployed + handover → L-152 换代。cut / deploy 都是子进程，可能跑几个小时，所以单独线程，不拖 health / 重启队列"""
    import release_tick as RT
    last = None
    while True:
        t0 = time.time()
        every = every_s or 60
        try:
            every = every_s or int(RT.load_sv().release_cfg().get("every_s") or 60)
            r = RT.tick(rs=sys.modules[__name__])
            sig = json.dumps(r, ensure_ascii=False, sort_keys=True, default=str)
            if sig != last and (r.get("release") or {}).get("status") not in ("idle", "disabled", None):
                log("release_tick", sig[:600])
            last = sig
        except Exception as e:  # noqa: BLE001
            log("release_tick error", repr(e)[:300])
        time.sleep(max(1.0, every - (time.time() - t0)))


EPISODE_RUN_TICK = True            # CODER-RES：episode_run 常驻（开关以 config/pipeline/episode_run.json enabled 为准，每拍重读）
EPISODE_RUN_CFG = ROOT / "config/pipeline/episode_run.json"
EPISODE_RUN_HB = ROOT / "data/autopilot/episode_run_heartbeat.json"


def episode_run_cfg(path: Path | None = None) -> dict:
    d = jl(path or EPISODE_RUN_CFG, {}) or {}
    return {"enabled": bool(d.get("enabled", False)), "interval_s": max(60, int(d.get("interval_s") or 300)),
            "targets": [t for t in d.get("targets") or [] if t.get("run") and t.get("ep")]}


def episode_run_tick_once(cfg: dict | None = None, tick_fn=None, hb_path: Path | None = None) -> dict:
    """每个 target 推进一次；单个 target 抛错只记日志，不影响其它。心跳 / 摘要写 episode_run_heartbeat.json（原子）"""
    cfg = cfg or episode_run_cfg()
    out: dict = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(time.time() + 9 * 3600)) + "+09:00", "enabled": cfg["enabled"], "targets": {}}
    if cfg["enabled"]:
        if tick_fn is None:
            sys.path.insert(0, str(ROOT / "tools/master"))
            import episode_run as ER
            tick_fn = ER.tick_once
        for t in cfg["targets"]:
            k = f"{t['run']}/ep{int(t['ep']):02d}"
            try:
                r = tick_fn(t["run"], int(t["ep"]))
                out["targets"][k] = {x: r.get(x) for x in ("status", "stopped_at", "exit", "msg")}
            except Exception as e:  # noqa: BLE001
                out["targets"][k] = {"status": "error", "msg": repr(e)[:200]}
                log("episode_run error", k, repr(e)[:300])
    hp = hb_path or EPISODE_RUN_HB
    hp.parent.mkdir(parents=True, exist_ok=True)
    tmp = hp.with_suffix(".json.part")
    tmp.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, hp)
    return out


def episode_run_thread(every_s: int | None = None) -> None:
    """episode_run 常驻线程：与 release_thread 同生命周期（daemon、异常只记日志、每拍重读配置）。tick 里的远程 / 子进程调用各有超时"""
    last = None
    while True:
        t0 = time.time()
        every = every_s or 300
        try:
            cfg = episode_run_cfg()
            every = every_s or cfg["interval_s"]
            r = episode_run_tick_once(cfg)
            sig = json.dumps(r.get("targets"), ensure_ascii=False, sort_keys=True, default=str)
            if cfg["enabled"] and sig != last:
                log("episode_run", sig[:600])
            last = sig
        except Exception as e:  # noqa: BLE001
            log("episode_run error", repr(e)[:300])
        time.sleep(max(1.0, every - (time.time() - t0)))


# ---------------------------------------------------------------- W18 PRODUCER-LIFECYCLE：主剧到“出图”就自动起 producer / night（L-154 / C-16）
# 每拍：runs.json primary（preparing / producing）的 sop_gate 唯一阶段视图 →
#   ① 有一集已到“出图”且 status=preparing → sop_gate.promote（与 producer.maybe_promote 同一规则；promote.auto=true 才写，status_history by=auto:…）
#   ② producer：本集阶段 ∈ {出图, 出图检测, 尾帧, 视频} → 笔记本（restart_producer.ps1）+ 负责该集出图分区的服务器（request_restart）
#   ③ night：本集阶段 ≥ 尾帧（未完成）→ 负责该集视频分区的服务器
#   心跳新鲜（≤ hb_stale_min）= 在跑，不动（幂等）；起过后 grace_min 内不重复起；连续 max_fails 次起不来 → report_issue（P0，阻断，只报一次）。
#   阶段 < 出图一律不起（C-16）；阶段 < 尾帧 night 不起——服务器请求带 mode=producer-only（restart_queue 按 mode 执行之前退化为 all，见交付说明）。
#   开关：config/pipeline/sop_gate.json lifecycle.apply（默认 false = 只算计划、写日志，不起不写；总调度在 cut B deploy 后放开）。
LIFECYCLE_TICK = True
LIFECYCLE_STATE = ROOT / "data/autopilot/lifecycle.json"
LC_PRODUCER_STAGES = ("出图", "出图检测", "尾帧", "视频")
LC_NIGHT_FROM = "尾帧"
LC_DEFAULT = {"apply": False, "hb_stale_min": 5, "grace_min": 10, "night_grace_min": 20, "max_fails": 3, "health_max_age_min": 15,
              "laptop_ps1": "ops/autostart/restart_producer.ps1"}
LC_WHO = "resident_sync.lifecycle"


def lc_grace_min(cfg: dict, kind: str) -> float:
    """起过之后等心跳的宽限：night 目标 ≥ night_grace_min（默认 20 min——night 刚起的第一轮 sync / register / build 要 5–15 min，
    FIX-NIGHT2：10 min 宽限 + 8 min 心跳判死 = 刚起就被再次重启，自我打败）；其它目标 grace_min"""
    g = float(cfg.get("grace_min") or 10)
    return max(g, float(cfg.get("night_grace_min") or 20)) if kind == "night" else g


def lifecycle_cfg(root: Path = ROOT) -> dict:
    d = jl(Path(root) / "config/pipeline/sop_gate.json", {}) or {}
    return {**LC_DEFAULT, **(d.get("lifecycle") or {}), "_promote": d.get("promote") or {}}


def _lc_mod(root: Path, rel: str, name: str):
    import importlib.util as _u
    key = f"{name}:{Path(root).resolve()}"
    if key not in _LC_MODS:
        sp = _u.spec_from_file_location(name, Path(root) / rel if (Path(root) / rel).is_file() else ROOT / rel)
        m = _u.module_from_spec(sp)
        sp.loader.exec_module(m)
        _LC_MODS[key] = m
    return _LC_MODS[key]


_LC_MODS: dict = {}


def lifecycle_stage(root: Path, run: str) -> dict:
    """{status, legacy, episodes: [{episode, stage, stage_index}], stages} —— 只读 sop_gate.stage_view（唯一阶段口径）"""
    sg = _lc_mod(root, "tools/master/sop_gate.py", "ns_sop_gate_lc")
    reg = (jl(Path(root) / "config/pipeline/runs.json", {}) or {}).get("runs") or {}
    v = sg.stage_view(run, Path(root))
    return {"status": (reg.get(run) or {}).get("status"), "legacy": bool(v.get("legacy")), "stages": list(v.get("stages") or sg.STAGES),
            "episodes": [{"episode": e["episode"], "stage": e["stage"], "stage_index": e["stage_index"]} for e in v.get("episodes") or []]}


def lifecycle_partition(root: Path = ROOT) -> dict:
    d = _partition_live(Path(root)) or {}      # L-209 S2.3：唯一一份 data/state/netfix/partition.json
    return {k: {h: [int(x) for x in eps] for h, eps in (d.get(k) or {}).items() if h != "laptop"} for k in ("images", "video")}


def lifecycle_want(st: dict, part: dict) -> dict:
    """纯函数：→ {producer_eps, night_eps, targets: {目标: {kind, host, eps, mode}}}；目标 = laptop:producer / <host>:producer / <host>:night"""
    stages = st["stages"]
    p_idx = {stages.index(s) for s in LC_PRODUCER_STAGES if s in stages}
    n_from = stages.index(LC_NIGHT_FROM) if LC_NIGHT_FROM in stages else 6
    prod = sorted(e["episode"] for e in st["episodes"] if e["stage_index"] in p_idx)
    night = sorted(e["episode"] for e in st["episodes"] if n_from <= e["stage_index"] < len(stages))
    t: dict[str, dict] = {}
    if prod:
        t["laptop:producer"] = {"kind": "producer", "host": "laptop", "eps": prod, "mode": None}
    for h, eps in sorted((part.get("images") or {}).items()):
        mine = sorted(set(eps) & set(prod))
        if mine:
            t[f"{h}:producer"] = {"kind": "producer", "host": h, "eps": mine}
    for h, eps in sorted((part.get("video") or {}).items()):
        mine = sorted(set(eps) & set(night))
        if mine:
            t[f"{h}:night"] = {"kind": "night", "host": h, "eps": mine}
    for k, v in t.items():                       # 服务器一次重启 = producer + night 同起（resident_restart.sh all）；该机没有该起 night 的集 → producer-only
        if v["host"] != "laptop":
            v["mode"] = "all" if f"{v['host']}:night" in t else "producer-only"
    return {"producer_eps": prod, "night_eps": night, "targets": t}


def lifecycle_heartbeats(root: Path, run: str, hosts, now: float | None = None, max_age_min: float = 15) -> dict:
    """{目标: 心跳分钟数 | None=没有心跳 | "unknown"=服务器健康记录过期（判不了，不起）}。
    笔记本 = runs.producer_dir(run)/heartbeat.json（exited / draining 的不算在跑）；服务器 = health() 写进 STATE 的 producer / night 年龄。
    口径（W18b P1-1）：笔记本心跳 state 不是 draining / exited（含没写 state、running、paused 等）且年龄 ≤ hb_stale_min（默认 5 分钟，
    ≥ producer 一拍最长时长：import_err 重试单次就能超 2 分钟）→ lifecycle_tick 判 running、不动；draining / exited → 这里返回 None（= 没有心跳）"""
    now = now or time.time()
    out: dict = {}
    pd = Path(root) / producer_rel(run)
    hb = jl(pd / "heartbeat.json", {}) or {}
    live = hb.get("t") and not hb.get("exited") and hb.get("state") not in ("exited", "draining") and hb.get("run") in (None, run)
    out["laptop:producer"] = round((now - float(hb["t"])) / 60, 1) if live else None
    st = jl(Path(root) / "data/autopilot/resident_sync.json", {}) or {}
    for h in hosts:
        hh = (st.get(h) or {}).get("health") or {}
        try:
            age = (now - time.mktime(time.strptime(hh["at"], "%Y-%m-%d %H:%M:%S"))) / 60
        except (KeyError, ValueError, TypeError):
            age = None
        if age is None or age > max_age_min:
            out[f"{h}:producer"] = out[f"{h}:night"] = "unknown"
            continue
        pa = hh.get("producer_hb_age_min")
        out[f"{h}:producer"] = None if (pa is None or hh.get("producer_run_mismatch")) else float(pa)
        na = hh.get("night_state_age_min")
        out[f"{h}:night"] = None if na is None else float(na)
    return out


def _laptop_start(root: Path, ps1: str, run: str) -> dict:
    try:
        r = subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(Path(root) / ps1), "-Run", run], cwd=root,
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600, stdin=subprocess.DEVNULL)
        out = ((r.stdout or "") + (r.stderr or "")).strip()
        return {"ok": r.returncode == 0 and "restarted" in out, "rc": r.returncode, "out": out[-300:]}
    except (OSError, subprocess.TimeoutExpired) as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"[:300]}


def _server_start(host: str, reason: str, mode: str) -> dict:
    """DJ-20：服务器只写重启请求（restart_queue 合并 / 排空后执行）；请求带 mode，同一台已有待办请求就不重复写"""
    import restart_queue as RQ
    if RQ.pending(host):
        return {"ok": True, "dedup": True, "pending": [r.get("id") for r in RQ.pending(host)]}
    rec = {"id": __import__("uuid").uuid4().hex[:12], "at": time.strftime("%Y-%m-%dT%H:%M:%S"), "t": time.time(), "host": host,
           "reason": reason, "by": LC_WHO, "urgent": False, "mode": mode}
    RQ._append(RQ.REQ, rec)
    return {"ok": True, "request": rec["id"], "mode": mode}


def _rq_state(host: str, req_id: str | None) -> dict:
    """W18b P1-2：restart_queue 里 lifecycle 自己那条请求的状态 → {pending: 该机还有没执行的请求, done_t: req_id 被执行（restart_done 记录）的时间 | None}"""
    import restart_queue as RQ
    done_t = None
    if req_id:
        for d in RQ._lines(RQ.DONE):
            if req_id in (d.get("request_ids") or []):
                try:
                    done_t = time.mktime(time.strptime(str(d.get("at"))[:19], "%Y-%m-%dT%H:%M:%S"))
                except ValueError:
                    done_t = time.time()                 # 时间坏了：按“刚执行”算（多等一个 grace，不提前算失败）
    return {"pending": bool(RQ.pending(host)), "done_t": done_t}


def _lc_live(root: Path, line: str) -> None:
    try:
        _lc_mod(root, "tools/master/report_issue.py", "ns_report_issue_lc")._insert_live(f"{time.strftime('%H:%M')} {line}",
                                                                                           Path(root) / "docs/master/V2_LIVE.md")
    except OSError:  # arch-ok: V2_LIVE 写不进去不拦生命周期（lifecycle.json 是权威）
        pass


def _lc_issue(root: Path, run: str, ep: int, target: str, what: str) -> str | None:
    ri = _lc_mod(root, "tools/master/report_issue.py", "ns_report_issue_lc")
    rec = ri.report(run, ep, "生命周期:" + target, LC_WHO, what, True,
                    "看 ops/logs/resident_sync.log lifecycle 行 + 目标机日志；修好后删 data/autopilot/lifecycle.json 里该目标的 attempts",
                    issues=Path(root) / "data/pipeline/issues.jsonl", live=Path(root) / "docs/master/V2_LIVE.md")
    return rec.get("id")


# W-FIX-PIPE #6（SCAN_20261107，L-212）：导入稿 / 资产清单一变提示词证据就过期，但 sop_gate.auto_probe_stale 只在有人调 require_backoff
# （producer 派单 / asset_worker）时才起——没人派（证据过期 → 阶段停在“提示词” → 不起 producer）= 死锁，11-07 夜 ep02 35 帧 5 道空等数小时。
# 改：lifecycle_tick 每拍（60 s）对过了导入闸门的集查一次 check_prompts，证据要刷新 → 笔记本（编译在这里）调同一个 auto_probe_stale
# （锁 / pid / 退避都在那里），每集至少隔 auto_probe_tick_min 分钟（config/pipeline/sop_gate.json，默认 5）才再触发一次。
AUTO_PROBE_STATE = ROOT / "data/autopilot/auto_probe.json"
AUTO_PROBE_TICK_MIN = 5.0


def auto_probe_tick(root: Path, run: str, episodes: list, now: float, dry: bool, probe_fn=None, check_fn=None) -> dict:
    """→ {epNN: {why, action: started|running|cooldown|debounce|would_probe|skip|error}}；只看 stage_index > 导入闸门 的集"""
    sg = _lc_mod(root, "tools/master/sop_gate.py", "ns_sop_gate_lc")
    cfg = jl(Path(root) / "config/pipeline/sop_gate.json", {}) or {}
    gap = float(cfg.get("auto_probe_tick_min") or AUTO_PROBE_TICK_MIN) * 60
    gate_i = sg.STAGES.index("导入闸门")
    sp = AUTO_PROBE_STATE if Path(root) == ROOT else Path(root) / "data/autopilot/auto_probe.json"
    sd = jl(sp, {}) or {}
    out: dict = {}
    for e in episodes:
        if int(e.get("stage_index") or 0) <= gate_i:
            continue
        ep = int(e["episode"])
        try:
            r = (check_fn or sg.check_prompts)(Path(root), run, ep)
        except Exception as ex:  # noqa: BLE001  # arch-ok: 判不了 = 本集这拍不探，记下原因
            out[f"ep{ep:02d}"] = {"action": "error", "why": f"check_prompts：{type(ex).__name__}: {ex}"[:200]}
            continue
        why = str(r.get("why") or "")
        if r.get("ok") or not sg._is_stale_evidence([why]):
            continue
        k = f"{run}:ep{ep:02d}"
        last = float((sd.get(k) or {}).get("t") or 0)
        a = {"why": why[:160]}
        if now - last < gap:
            a.update(action="debounce", next_s=round(gap - (now - last)))
        elif dry:
            a["action"] = "would_probe"
        else:
            res = (probe_fn or sg.auto_probe_stale)(run, ep, Path(root), [why], now)
            a["action"] = res or "skip"
            if res == "started":
                sd[k] = {"t": now, "at": time.strftime("%F %T", time.localtime(now)), "why": why[:160]}
                js(sp, sd)
            if res not in ("running", "cooldown"):       # 在跑 / 退避中每拍都会命中，不刷日志
                log("auto_probe", json.dumps({"run": run, "ep": ep, **a}, ensure_ascii=False))
        out[f"ep{ep:02d}"] = a
    return out


def lifecycle_tick(root: Path = ROOT, dry: bool | None = None, now: float | None = None, stage_fn=None, hb_fn=None,
                   laptop_fn=None, server_fn=None, promote_fn=None, issue_fn=None, live_fn=None, rq_fn=None, probe_fn=None) -> dict:
    """一拍。dry=None → 按 lifecycle.apply 决定（apply=false 即 dry）。返回完整计划 + 每个目标的动作（dry 下 would_*）。
    W18b P1-2：服务器目标的 attempts 数的是“restart_queue 真执行过、执行后 grace_min 仍没有心跳”的次数，不是写了几次请求——
    该机还有待办请求 = queued（不计数、不再写）；执行了还在 grace 内 = waiting；连续 max_fails 次执行后仍没心跳才登记 P0"""
    root = Path(root)
    cfg = lifecycle_cfg(root)
    dry = (not cfg.get("apply")) if dry is None else dry
    now = now or time.time()
    run = str((jl(root / "config/pipeline/runs.json", {}) or {}).get("primary") or "")
    out: dict = {"run": run, "dry": dry, "at": time.strftime("%F %T", time.localtime(now)), "actions": {}}
    if not run:
        out["skip"] = "runs.json 没有 primary"
        return out
    st = (stage_fn or lifecycle_stage)(root, run)
    out["status"], out["episodes"] = st.get("status"), st.get("episodes")
    if st.get("legacy"):
        out["skip"] = f"{run} 是 legacy（V1 不走 V2 生命周期）"
        return out
    if st.get("status") not in ("preparing", "producing"):
        out["skip"] = f"runs.json status={st.get('status')}（只有 preparing / producing 会自动起；paused / archived = 项目方 / 总调度停的，不动）"
        return out
    try:                                         # W-FIX-PIPE #6：过了导入闸门、提示词证据过期的集 → 笔记本自动 probe-prompts（去抖）
        out["auto_probe"] = auto_probe_tick(root, run, st.get("episodes") or [], now, dry, probe_fn=probe_fn)
    except Exception as e:  # noqa: BLE001  # arch-ok: 自动探针出错不拦生命周期（下一拍再试），记日志
        out["auto_probe"] = {"error": f"{type(e).__name__}: {e}"[:200]}
        log("auto_probe error", out["auto_probe"]["error"])
    want = lifecycle_want(st, lifecycle_partition(root))
    out.update(producer_eps=want["producer_eps"], night_eps=want["night_eps"])
    if not want["targets"]:
        out["skip"] = "没有任何一集到“出图”（C-16：阶段 < 出图 不起 producer / night）"
        return out
    # ① promote（preparing → producing）
    if st["status"] == "preparing":
        auto = bool((cfg.get("_promote") or {}).get("auto"))
        try:
            if promote_fn:
                res = promote_fn(run, root, apply=auto and not dry)
            else:
                sg = _lc_mod(root, "tools/master/sop_gate.py", "ns_sop_gate_lc")
                res = sg.promote(run, root, by=f"auto:{LC_WHO}", apply=auto and not dry)
        except Exception as e:  # noqa: BLE001  # arch-ok: 判不了 = 不提升、不起（失败关闭）
            res = {"promote": False, "why": f"promote 出错：{type(e).__name__}: {e}"[:300]}
        out["promote"] = {k: res.get(k) for k in ("promote", "applied", "episodes", "why")} | {"auto": auto}
        if res.get("applied"):
            (live_fn or _lc_live)(root, f"✅ 自动提升（{LC_WHO}，L-154）：{run} preparing → producing，{res.get('why')}")
        elif not res.get("promote"):
            out["skip"] = f"{run} 仍 preparing 且 sop_gate.promote 判不可进：{str(res.get('why'))[:200]}（不起）"
            return out
        elif not dry and not auto:
            out["skip"] = f"{run} 可提升但 promote.auto=false（等总调度 sop_gate.py promote --apply），不起"
            return out
    # ②③ 起 producer / night
    hosts = sorted({v["host"] for v in want["targets"].values() if v["host"] != "laptop"})
    hbs = (hb_fn or lifecycle_heartbeats)(root, run, hosts, now, float(cfg["health_max_age_min"]))
    sd = jl(LIFECYCLE_STATE if root == ROOT else root / "data/autopilot/lifecycle.json", {}) or {}
    started_hosts: dict = {}                   # host → 本拍 / 待办的请求 id（None = 这台这拍已处理，不再写）
    for tgt, v in want["targets"].items():
        rec = sd.setdefault(tgt, {})
        hb = hbs.get(tgt)
        a = {"kind": v["kind"], "host": v["host"], "eps": v["eps"], "hb_age_min": hb, "attempts": int(rec.get("attempts") or 0)}
        if hb == "unknown":
            a["action"] = "unknown"
            a["why"] = f"{v['host']} 健康记录超过 {cfg['health_max_age_min']} 分钟没更新（ssh / health 不通），判不了，不起"
        elif hb is not None and hb <= float(cfg["hb_stale_min"]):
            a["action"] = "running"
            if rec.get("attempts") or rec.get("issue"):
                rec.update(attempts=0, issue=None, recovered_at=time.strftime("%F %T", time.localtime(now)))
            if not dry:
                rec.pop("req_id", None), rec.pop("req_counted", None)
        elif v["host"] != "laptop" and v["host"] in started_hosts:
            a["action"] = "merged"
            a["why"] = f"同一台 {v['host']} 这拍已经起过 / 有待办请求（一次重启 producer + night 同起）"
            if started_hosts[v["host"]] and not dry:
                rec.update(req_id=started_hosts[v["host"]], req_counted=False, last_try=now)
        else:
            q = None
            if v["host"] != "laptop":                       # P1-2：先看 restart_queue 里的真实执行情况
                try:
                    q = (rq_fn or _rq_state)(v["host"], rec.get("req_id"))
                except Exception as e:  # noqa: BLE001  # arch-ok: 队列读不了 = 当作还在排队（不写新请求、不计失败）
                    q = {"pending": True, "error": f"{type(e).__name__}: {e}"[:200]}
                if rec.get("req_id") and q.get("done_t") is not None and not rec.get("req_counted"):
                    if now - float(q["done_t"]) < lc_grace_min(cfg, v["kind"]) * 60:
                        q = {**q, "grace": True}
                    elif not dry:
                        rec.update(attempts=int(rec.get("attempts") or 0) + 1, req_counted=True)
                        a["attempts"] = rec["attempts"]
            if q and q.get("pending"):
                a["action"] = "queued"
                a["why"] = (f"{v['host']} 还有没执行的重启请求（restart_queue 30 分钟间隔 / 排空中），等它执行，不计失败、不再写请求"
                            + (f"；{q['error']}" if q.get("error") else ""))
                started_hosts[v["host"]] = None
            elif q and q.get("grace"):
                a["action"] = "waiting"
                a["why"] = f"restart_queue {round((now - float(q['done_t'])) / 60, 1)} 分钟前执行了重启，{lc_grace_min(cfg, v['kind']):.0f} 分钟内等心跳"
                started_hosts[v["host"]] = None
            elif v["host"] == "laptop" and rec.get("last_try") and now - float(rec["last_try"]) < lc_grace_min(cfg, v["kind"]) * 60:
                a["action"] = "waiting"
                a["why"] = f"{round((now - float(rec['last_try'])) / 60, 1)} 分钟前刚起过，{lc_grace_min(cfg, v['kind']):.0f} 分钟内不重复起"
            elif int(rec.get("attempts") or 0) >= int(cfg["max_fails"]):
                a["action"] = "gave_up"
                if not rec.get("issue") and not dry:
                    what = "自动拉起" if v["host"] == "laptop" else "restart_queue 真执行重启"
                    rec["issue"] = (issue_fn or _lc_issue)(root, run, min(v["eps"]), tgt,
                                                            f"【P0】{tgt} 连续 {rec['attempts']} 次{what}后仍没有心跳（第 {v['eps']} 集到“出图”以后等它）")
                a["issue"] = rec.get("issue")
                if v["host"] != "laptop":
                    started_hosts[v["host"]] = None
            else:
                reason = (f"W18 生命周期：{run} 第 {v['eps']} 集已到“{'出图' if v['kind'] == 'producer' else LC_NIGHT_FROM}”以后，"
                          f"{tgt} {'没有心跳' if hb is None else f'心跳 {hb} 分钟没更新'}")
                if v["host"] == "laptop":
                    a["how"] = f"powershell -File {cfg['laptop_ps1']} -Run {run}（restart_producer.ps1：先暂停排空 → 停旧 → serve --run {run} → 恢复）"
                else:
                    a["how"] = (f"resident_sync.request_restart({v['host']!r}, mode={v['mode']}) → restart_queue 排空后执行 "
                                f"ops/offline/resident_restart.sh {v['host']} {v['mode']}")
                if dry:
                    a["action"] = "would_start"
                    if v["host"] != "laptop":
                        started_hosts[v["host"]] = None
                elif v["host"] == "laptop":
                    r = (laptop_fn or _laptop_start)(root, cfg["laptop_ps1"], run)
                    rec.update(attempts=int(rec.get("attempts") or 0) + 1, last_try=now, last_result=r)
                    a.update(action="started", result=r, attempts=rec["attempts"])
                    (live_fn or _lc_live)(root, f"{'✅' if r.get('ok') else '❌'} 自动拉起（{LC_WHO}）{tgt}：{reason}（第 {rec['attempts']} 次）")
                else:                                       # 只写请求：attempts 不加（等 restart_queue 执行后再看心跳）
                    r = (server_fn or _server_start)(v["host"], reason, v["mode"])
                    rid = r.get("request") or ((r.get("pending") or [None])[-1] if r.get("dedup") else None)
                    rec.update(last_try=now, last_result=r, req_id=rid, req_counted=False)
                    a.update(action="requested", result=r, attempts=int(rec.get("attempts") or 0))
                    started_hosts[v["host"]] = rid
                    (live_fn or _lc_live)(root, f"{'✅' if r.get('ok') else '❌'} 自动拉起（{LC_WHO}）{tgt}：{reason}"
                                                f"（已写重启请求，restart_queue 执行后算第 {int(rec.get('attempts') or 0) + 1} 次）")
        out["actions"][tgt] = a
    if not dry:
        js(LIFECYCLE_STATE if root == ROOT else root / "data/autopilot/lifecycle.json", sd)
    return out


def lifecycle_thread(every_s: int = 60) -> None:
    """独立线程（不拖 health / 重启队列）：每 60 s 一拍；计划变了才写日志"""
    last = None
    while True:
        t0 = time.time()
        try:
            r = lifecycle_tick()
            sig = json.dumps({k: r.get(k) for k in ("skip", "status", "producer_eps", "night_eps")}
                             | {"a": {t: a.get("action") for t, a in (r.get("actions") or {}).items()}}, ensure_ascii=False, sort_keys=True)
            if sig != last:
                log("lifecycle", json.dumps(r, ensure_ascii=False, default=str)[:900])
            last = sig
        except Exception as e:  # noqa: BLE001
            log("lifecycle error", repr(e)[:300])
        time.sleep(max(5.0, every_s - (time.time() - t0)))


# ------------------------------------------------------------------ W40 SYNC+VQA-RESIDENT（总调度 11-04 01:4x；L-163 自动化写在代码上）
# STATE 坏点①：服务器 producer 依赖的笔记本产物不自动同步（L-178/179/180，ISS-1103-181531 / 181720：11-03 晚全靠手工 tar 推 gpu33）。
# STATE 坏点②：gpu36 看图服务（127.0.0.1:8870 server.py + watcher）不在 resident 管辖，死了没人知道 → Q9/Q10 untested → score_infra 循环
# （ISS-1103-220512）。两件都做成 loop 里的独立守护线程，失败 report_issue 阻断（连续失败才登，恢复前不重登），不静默。
W40_WHO = "resident_sync.W40"
RUN_SYNC_TICK = True
RUN_SYNC_EVERY_S = 120
RUN_SYNC_STATE = ROOT / "data/autopilot/run_sync.json"
RUN_SYNC_FAIL_REPORT = 2                    # 连续 2 拍失败才登记阻断卡点（一拍断线不报）
RUN_SYNC_BIG = 512 * 1024                   # 单文件 ≥ 512 KB 算大文件：走 <host>-hk 单独传（FONG-QUICK：大文件不走 -t）
RUN_SYNC_SMALL_BATCH = 2 * 1024 * 1024      # 小文件走命令主连接 stdin tar，每批 ≤ 2 MB
RUN_SYNC_BIG_BATCH = 32 * 1024 * 1024       # 大文件每个 tar ≤ 32 MB，经 rssh.bulk_put（sftp <host>-hk）传到 {OFF}/.inbox 再原子安装
RUN_SYNC_MTIME_SLACK = 2.0
# 不推的：写手包 / 评审 / 作废稿 / 备份（服务器不读）；服务器自己写的（producer 状态、sop_gate 退避、视频状态）；追加日志
RUN_SYNC_SKIP_PARTS = {"writer_tasks", "writer_out", "writer_tasks_void", "writer_out_void", "judge_p1", "superseded", "backups",
                       "_recheck", "metrics", "hollywood", "video"}
RUN_SYNC_SKIP_PART_PREFIX = ("_rejected",)
RUN_SYNC_SKIP_NAMES = {"_producer.json", "_sop_backoff.json", "_recheck"}
RUN_SYNC_SKIP_EXT = (".log", ".jsonl", ".bak", ".done", ".tmp")


def run_sync_runs() -> list[str]:
    """要同步的剧：主剧 + runs.json 里 status=producing 的（第二季等），去重保序"""
    out = [RUN_ID]
    try:
        out += [r for r in _RUNS.list_runs(status="producing") if r not in out]
    except Exception as e:  # noqa: BLE001
        log("run_sync", "在产剧列表读不了，只同步主剧", repr(e)[:160])
    return out


def run_media_dirs(run: str) -> list[str]:
    """W46：night finalize（服务器上合成整集）按剧读的声音 / 配乐资产目录——config/voices_v2.json 各候选 ref_wav 所在的顶层目录
    （data/assets/voices_v2）、config/music_v2.json 曲库文件目录（data/music/v2_style）、集级 BGM 目录 data/music/<剧>。
    11-04 03:2x 实测两台服务器都没有 data/assets/voices_v2 → ns_post.run_media.voice_config 校验失败 → night 每集 hold_voices。
    只收 config 里登记了 run = 本剧的；读不到 = 不加（不影响别的同步项）"""
    out = []
    try:
        for name in ("voices_v2.json", "music_v2.json"):
            d = jl(ROOT / "config" / name, {}) or {}
            if d.get("run") not in (None, run) and name == "music_v2.json":
                continue
            for m in re.finditer(r'"(?:ref_wav|file|sample_wav)"\s*:\s*"(data/(?:assets|music)/[^/"]+)/', json.dumps(d, ensure_ascii=False)):
                out.append(m.group(1))
        if not _is_legacy_run(run):
            out.append(f"data/music/{run}")
    except Exception as e:  # noqa: BLE001  # arch-ok: 媒体目录推导失败只少推这一项，记日志
        log("run_sync", "声音 / 配乐目录推导失败", repr(e)[:160])
    return [d for d in dict.fromkeys(out) if (ROOT / d).is_dir()]


def _is_legacy_run(run: str) -> bool:
    reg = jl(ROOT / "config/pipeline/runs.json", {}) or {}
    return run == reg.get("legacy_unprefixed_run")


def run_sync_sources(run: str) -> tuple[list[str], list[str]]:
    """→ (目录, 单文件)：服务器侧 sop_gate / producer 读的 run 级产物（tools/master/sop_gate.py check_* 的读路径）+ 派生参考图 + 资产清单"""
    dirs = [f"data/pipeline/runs/{run}",               # P4_epNN.md / autoflow_epNN.json / assets/ / images/（refcrops、refboards + _derived_index.json）/ looks / continuity
            f"data/pipeline/sop_gate/{run}",           # epNN_prompts.json（提示词证据）
            f"data/pipeline/asset_jobs/{run}",         # _ready_epNN.json（资产就绪）
            f"data/import/runs/{run}"]                 # 导入稿 script_v2.json（sop_gate.episodes_of / shots_of）
    dirs += run_media_dirs(run)
    files = []
    mf = (((jl(ROOT / "config/pipeline/runs.json", {}) or {}).get("runs") or {}).get(run) or {}).get("assets_manifest")
    if mf:
        files.append(str(mf).replace("\\", "/"))       # sop_gate.prompt_fingerprint 的 manifest_sha
    return dirs, files


def run_sync_skip(rel: str) -> bool:
    parts = rel.split("/")
    return (skipped(rel) or any(p in RUN_SYNC_SKIP_PARTS or p.startswith(RUN_SYNC_SKIP_PART_PREFIX) for p in parts[:-1])
            or parts[-1] in RUN_SYNC_SKIP_NAMES or rel.endswith(RUN_SYNC_SKIP_EXT) or ".bak-" in parts[-1])


def run_sync_local(runs: list[str] | None = None) -> tuple[dict, list[str]]:
    """→ (本地清单 {rel: (size, mtime)}, 远端要列的路径)"""
    loc, rem_paths = {}, []
    for run in runs or run_sync_runs():
        dirs, files = run_sync_sources(run)
        rem_paths += dirs + files
        for rel, v in local_manifest(dirs).items():
            if not run_sync_skip(rel):
                loc[rel] = v
        for rel in files:
            p = ROOT / rel
            if p.is_file():
                st = p.stat()
                loc[rel] = (st.st_size, st.st_mtime)
    return loc, sorted(set(rem_paths))


def run_sync_todo(loc: dict, rem: dict, slack: float = RUN_SYNC_MTIME_SLACK) -> list[str]:
    """只推“服务器没有”或“笔记本比服务器新”的；服务器更新的不盖（W38 等在服务器上直接改的证据不被旧值盖回去）。小文件先"""
    out = [rel for rel, (s, t) in loc.items() if rel not in rem or t > rem[rel][1] + slack]
    return sorted(out, key=lambda f: (loc[f][0], f))


def _pack(files: list[str], loc: dict, cap: int) -> list[list[str]]:
    out, cur, n = [], [], 0
    for f in files:
        s = loc[f][0]
        if cur and n + s > cap:
            out.append(cur)
            cur, n = [], 0
        cur.append(f)
        n += s
    if cur:
        out.append(cur)
    return out


def _install_stdin(host: str, blob: bytes, ssh_fn=None) -> None:
    (ssh_fn or ssh)(host, f"set -e; T=$(mktemp -d {OFF}/.push.XXXXXX); tar xf - -C $T; " + atomic_install_cmd(R) + "; echo ok",
                    data=blob, timeout=BATCH_TIMEOUT_S, tries=3)


def _install_bulk(host: str, blob: bytes, ssh_fn=None, bulk_fn=None) -> str:
    """大文件：tar 落本机临时文件 → rssh.bulk_put（sftp 经 <host>-hk 单独一条连接）→ 命令主连接只发一句解包 + 原子安装。
    bulk 不可用（非 Windows / NS_BULK_UPLOAD=off）或失败 → 退回命令主连接 stdin（记日志，不当成功也不吞）。→ 走的哪条路"""
    import tempfile
    name = f"rs_{int(time.time() * 1000)}_{os.getpid()}.tar"
    fd, tmp = tempfile.mkstemp(suffix=".tar")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(blob)
        res = (bulk_fn or _rssh().bulk_put)(host, [(tmp, name)], f"{OFF}/.inbox", timeout=max(300, len(blob) // 200_000 + 120))
    finally:
        try:
            os.unlink(tmp)            # 本机临时 tar（自己刚写的传输件，不是项目文件）
        except OSError as e:
            log("run_sync", host, "本机临时 tar 删不掉", tmp, repr(e)[:80])
    if res is None or getattr(res, "returncode", 1) != 0:
        err = "" if res is None else (getattr(res, "stderr", b"") or b"")[-200:].decode("utf-8", "replace")
        log("run_sync", host, "hk 单独传不可用 / 失败 → 退回命令主连接", f"{len(blob) / 1e6:.2f} MB", err.replace("\n", " "))
        _install_stdin(host, blob, ssh_fn)
        return "stdin"
    (ssh_fn or ssh)(host, f"set -e; T=$(mktemp -d {OFF}/.push.XXXXXX); tar xf {OFF}/.inbox/{name} -C $T; rm -f {OFF}/.inbox/{name}; "
                          + atomic_install_cmd(R) + "; echo ok", timeout=BATCH_TIMEOUT_S, tries=3)
    return "hk"


def _w40_issue(step: str, what: str, fix_hint: str, run: str | None = None, ep: int = 0) -> str | None:
    ri = _lc_mod(ROOT, "tools/master/report_issue.py", "ns_report_issue_w40")
    rec = ri.report(run or RUN_ID, ep, step, W40_WHO, what, True, fix_hint,
                    issues=ROOT / "data/pipeline/issues.jsonl", live=ROOT / "docs/master/V2_LIVE.md")
    return rec.get("id")


def _w40_fail(st: dict, key: str, what: str, step: str, fix_hint: str, after: int, issue_fn=None) -> str | None:
    """连续失败计数；到 after 次且这一段失败还没登记过 → 登记阻断卡点一次（恢复后 _w40_ok 清掉，下次再坏再登）"""
    rec = st.setdefault(key, {})
    rec["fails"] = int(rec.get("fails") or 0) + 1
    rec["last_error"] = what[:300]
    rec["last_fail_at"] = time.strftime("%F %T")
    if rec["fails"] >= after and not rec.get("issue"):
        try:
            rec["issue"] = (issue_fn or _w40_issue)(step, what, fix_hint)
        except Exception as e:  # noqa: BLE001
            log("W40 report_issue 失败", key, repr(e)[:200])        # 登记失败也留痕：下拍再试
        log("W40 登记阻断卡点", key, rec.get("issue"), what[:200])
    return rec.get("issue")


def _w40_ok(st: dict, key: str) -> None:
    rec = st.setdefault(key, {})
    if rec.get("fails"):
        log("W40 恢复", key, f"之前连续失败 {rec.get('fails')} 拍", "卡点" if rec.get("issue") else "", rec.get("issue") or "")
    rec.update(fails=0, issue=None, last_ok_at=time.strftime("%F %T"))


def _stat_now(rel: str) -> tuple | None:
    try:
        st = (ROOT / rel).stat()
    except OSError:
        return None           # 推完被移走 / 改名：同样按“途中变了”处理，下拍清单自然不再要它
    return (st.st_size, st.st_mtime)


def run_sync_authoritative(runs: list[str] | None = None) -> list[str]:
    """笔记本为唯一真源的单文件（run_sync_sources 的 files：资产包清单 assets_v2/manifest.json）——服务器 sop_gate 提示词证据指纹
    （manifest_sha）拿它算，两边必须逐字节一致"""
    out = []
    for run in runs or run_sync_runs():
        out += run_sync_sources(run)[1]
    return list(dict.fromkeys(out))


def run_sync_sha_todo(host: str, loc: dict, rem: dict | None = None, runs: list[str] | None = None, ssh_fn=None) -> list[str]:
    """W46（总调度 04:0x 令 ③）：mtime 规则“服务器更新的不盖”对这几个真源文件会误判——11-04 03:5x gpu36 的
    assets_v2/manifest.json 与笔记本 / gpu33 不同（09f9… vs 8e89…），而服务器副本的 mtime 比笔记本晚（04:0x 实测两台都比笔记本晚 6–13 s），
    笔记本这份不算“更新” → 不推 → gpu36 上 ep01 提示词证据判“过期”。这里对真源单文件比 sha：远端有且 sha 不同 → 推（不看 mtime）。
    只查 mtime 规则会放过的那种（远端在、且远端 mtime 比笔记本新过余量 = 判成“服务器更新”；正常 tar 推送 mtime 相同）；远端读不到 / 解析不了 = 不加"""
    files = [f for f in run_sync_authoritative(runs) if f in loc
             and (rem is None or (f in rem and rem[f][1] > loc[f][1] + RUN_SYNC_MTIME_SLACK))]
    if not files:
        return []
    import hashlib
    try:
        raw = (ssh_fn or ssh)(host, f"cd {R} && sha256sum {' '.join(files)} 2>/dev/null; true", timeout=120)
        rem = {}
        for ln in (raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw)).splitlines():
            parts = ln.split(None, 1)
            if len(parts) == 2 and len(parts[0]) == 64:
                rem[parts[1].strip().lstrip("*")] = parts[0]
        out = []
        for f in files:
            if f in rem and rem[f] != hashlib.sha256((ROOT / f).read_bytes()).hexdigest():
                out.append(f)
        return out
    except Exception as e:  # noqa: BLE001  # arch-ok: sha 比对失败只少这一项，mtime 规则照常
        log("run_sync", host, "真源文件 sha 比对失败", repr(e)[:160])
        return []


def run_sync_tick(host: str, dry: bool = False, ssh_fn=None, bulk_fn=None, rem_fn=None, issue_fn=None, runs=None) -> dict:
    """一拍：在产剧 run 级产物（ready 清单另由 push_control 按对象合并推）→ host 增量同步 → 复核 → 失败登记。返回本拍摘要"""
    st = jl(RUN_SYNC_STATE, {}) or {}
    key = f"sync:{host}"
    res = {"host": host, "at": time.strftime("%F %T")}
    try:
        loc, rem_paths = run_sync_local(runs)
        rem = (rem_fn or remote_manifest)(host, rem_paths)
        todo = run_sync_todo(loc, rem)
        shad = [f for f in run_sync_sha_todo(host, loc, rem, runs, ssh_fn) if f not in todo]
        if shad:
            res["sha_mismatch"] = shad
            todo += shad
        res.update(local=len(loc), todo=len(todo), mb=round(sum(loc[f][0] for f in todo) / 1e6, 2), sample=todo[:5])
        if dry or not todo:
            res["sent"] = 0
            if not dry:
                _w40_ok(st, key)
            return res
        small = [f for f in todo if loc[f][0] < RUN_SYNC_BIG]
        big = [f for f in todo if loc[f][0] >= RUN_SYNC_BIG]
        via = {"stdin": 0, "hk": 0}
        for b in _pack(small, loc, RUN_SYNC_SMALL_BATCH):
            _install_stdin(host, tar_bytes(b), ssh_fn)
            via["stdin"] += len(b)
        for b in _pack(big, loc, RUN_SYNC_BIG_BATCH):
            via[_install_bulk(host, tar_bytes(b), ssh_fn, bulk_fn)] += len(b)
        rem2 = (rem_fn or remote_manifest)(host, rem_paths)
        moved = [f for f in todo if _stat_now(f) != loc[f]]       # 推的途中笔记本又改了（asset_worker 等在写）→ 下拍按新清单再推，不算失败
        left = [f for f in todo if f not in moved and (f not in rem2 or rem2[f][0] != loc[f][0])]
        res.update(sent=len(todo) - len(left) - len(moved), via=via, left=left[:20], changed_during=len(moved))
        if left:
            raise RuntimeError(f"推完复核仍缺 / 大小不符 {len(left)} 个（例 {left[:3]}）")
        _w40_ok(st, key)
    except Exception as e:  # noqa: BLE001
        res["error"] = repr(e)[:300]
        _w40_fail(st, key, f"笔记本 → {host} 的 run 级产物同步失败（连续 {int((st.get(key) or {}).get('fails') or 0) + 1} 拍）：{repr(e)[:200]}",
                  "同步", f"看 ops/logs/resident_sync.log 的 run_sync 行；手工补：resident_sync.py run_sync {host}；"
                         f"大文件走 {host}-hk（FONG-QUICK），检查 tunnel_supervisor", RUN_SYNC_FAIL_REPORT, issue_fn)
    finally:
        st[f"last:{host}"] = res
        js(RUN_SYNC_STATE, st)
    log("run_sync", host, json.dumps({k: res.get(k) for k in ("todo", "mb", "sent", "via", "changed_during", "error") if k in res}, ensure_ascii=False),
        ("例 " + ", ".join(res.get("sample") or [])[:200]) if res.get("todo") else "无差异")
    return res


# ---------------------------------------------------------------- W46 RELAY：出图机 → 视频机的首尾帧中继（总调度 04:0x 定）
# 项目方 03:5x：“gpu36 也并行一起跑这样更快”→ ep01 视频段可放 gpu36（partition video 改给 gpu36 时）。前提①：通过的首尾帧要到 gpu36。
# 原机制都不行：push_frames 只在手动 video_up 里调；run_sync 不含 data/renders；笔记本的 ep01 takes.json 与 gpu33 已分叉（active 版本号不同、
# 文件缺），不能用笔记本那份。做法：以出图机（partition images）为真源，经笔记本两条常驻主连接 ssh src tar | ssh dst 安装，
# 只传“视频归 dst、出图归别机”的集：每镜 takes.json + 当前 image / last 文件。安装时只覆盖不删；takes.json 合并 = 出图机的
# image / last（及其它非视频阶段）+ 视频机自己的 video 版本与 active.video（视频机 register_takes 登记的不被冲掉）。
# 不是跨机共享出图（work_stealing=false 照旧）：出图机照常出，视频机只读。开关 NS_RELAY_FRAMES=off；每 RELAY_EVERY_S 一拍。
RELAY_EVERY_S = 60                 # FIX-ORCH O4（L-205 KPI）：300 → 60 s；另外每 RELAY_POLL_S 看一眼 puller 回执，出图机有新成品就立刻中继
RELAY_POLL_S = 15
RELAY_STATE = ROOT / "data/autopilot/relay_frames.json"
RELAY_TIMEOUT_S = 600
RELAY_FAIL_REPORT = 3

def merge_takes(src, dst):
    out = dict(src)
    keep = [t for t in (dst or {}).get("takes") or [] if t.get("stage") == "video"]
    out["takes"] = [t for t in src.get("takes") or [] if t.get("stage") != "video"] + keep
    act = dict(src.get("active") or {})
    act.pop("video", None)
    if ((dst or {}).get("active") or {}).get("video") is not None:
        act["video"] = dst["active"]["video"]
    out["active"] = act
    return out


import inspect as _inspect
RELAY_MERGE_SRC = "\n" + _inspect.getsource(merge_takes)   # 远端安装脚本内嵌同一段源码（本地与远端同一份；W46：不再 exec，静态检查能看到定义）

RELAY_LIST = r"""
import hashlib, json, os, sys
run, eps = sys.argv[1], [int(x) for x in sys.argv[2].split(",") if x]
def sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()
out = {}
for ep in eps:
    base = "data/renders/%s/ep%02d" % (run, ep)
    if not os.path.isdir(base):
        continue
    for sd in sorted(os.listdir(base)):
        tj = base + "/" + sd + "/takes.json"
        if not os.path.isfile(tj):
            continue
        try:
            d = json.load(open(tj, encoding="utf-8"))
        except ValueError:
            continue
        out[tj] = [os.path.getsize(tj), sha(tj)]
        act = d.get("active") or {}
        for t in d.get("takes") or []:
            st = t.get("stage")
            if st in ("image", "last") and act.get(st) == t.get("n") and t.get("file"):
                f = "data/" + str(t["file"]).replace(chr(92), "/").lstrip("/")
                if f.startswith("data/renders/%s/" % run) and os.path.isfile(f):
                    out[f] = [os.path.getsize(f), None]
print(json.dumps(out))
"""

RELAY_INSTALL = r"""
import fcntl, io, json, os, sys, tarfile, time
MERGE
PREFIX = sys.argv[1]          # 本剧渲染根（runs.renders_dir 相对路径 + "/"，调用方传）
blob = sys.stdin.buffer.read()
done = []
with tarfile.open(fileobj=io.BytesIO(blob)) as tf:
    for m in tf.getmembers():
        n = m.name
        if not m.isfile() or ".." in n or not n.startswith(PREFIX):
            continue
        data = tf.extractfile(m).read()
        os.makedirs(os.path.dirname(n), exist_ok=True)
        tmp = n + ".relay.tmp"
        if n.endswith("/takes.json"):
            lk = open(os.path.join(os.path.dirname(n), "takes.json.lock"), "a+")
            t0 = time.time()
            while True:
                try:
                    fcntl.flock(lk.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError:
                    if time.time() - t0 > 60:
                        raise
                    time.sleep(0.2)
            try:
                try:
                    cur = json.load(open(n, encoding="utf-8")) if os.path.isfile(n) else None
                except ValueError:
                    cur = None
                new = merge_takes(json.loads(data.decode("utf-8")), cur)
                open(tmp, "w", encoding="utf-8").write(json.dumps(new, ensure_ascii=False, indent=1))
                os.replace(tmp, n)
            finally:
                fcntl.flock(lk.fileno(), fcntl.LOCK_UN)
                lk.close()
        else:
            open(tmp, "wb").write(data)
            os.utime(tmp, (m.mtime, m.mtime))
            os.replace(tmp, n)
        done.append(n)
print(json.dumps({"installed": len(done)}))
""".replace("MERGE", RELAY_MERGE_SRC)


def _renders_prefix(run: str) -> str:
    """本剧渲染根的仓库相对前缀（runs.renders_dir，K-OPS-F24；V2 = data/renders/<剧>/）"""
    return _RUNS.renders_dir(run, ROOT).relative_to(ROOT).as_posix() + "/"


def relay_pairs(run: str, part: dict | None = None) -> list[tuple[str, str, int]]:
    """→ [(出图机, 视频机, 集)]：partition（按剧 runs.<剧> 优先，同 night.partition_hosts 口径）里视频归 dst、出图归另一台服务器的集"""
    if part is None:
        sys.path.insert(0, str(ROOT / "tools/netfix"))
        import dispatch as _D
        part = _D.read_partition()
    sec = ((part or {}).get("runs") or {}).get(run) or part or {}
    img = {int(e): h for h, eps in (sec.get("images") or (part or {}).get("images") or {}).items() for e in eps}
    vid = {int(e): h for h, eps in (sec.get("video") or (part or {}).get("video") or {}).items() for e in eps}
    return sorted((img[e], h, e) for e, h in vid.items() if e in img and img[e] != h and img[e] in HOSTS and h in HOSTS)


def relay_video_frames(run: str | None = None, part: dict | None = None, ssh_fn=None, state_path: Path | None = None) -> dict:
    """一拍：每对（出图机 → 视频机）列出真源上的 takes.json（带 sha）+ 当前首尾帧文件 → 只传变了的（takes.json 按上次中继的 sha，
    图按视频机上没有 / 大小不同）→ 视频机按 RELAY_INSTALL 安装（合并 takes.json，原子替换，不删）。返回摘要"""
    run = run or RUN_ID
    fn = ssh_fn or ssh
    sp = state_path or RELAY_STATE
    st = jl(sp, {}) or {}
    res = {"run": run, "pairs": []}
    groups: dict[tuple[str, str], list[int]] = {}
    for src, dst, ep in relay_pairs(run, part):
        groups.setdefault((src, dst), []).append(ep)
    for (src, dst), eps in sorted(groups.items()):
        key = f"relay:{src}>{dst}"
        row = {"src": src, "dst": dst, "eps": eps}
        try:
            arg = f"{run} {','.join(map(str, eps))}"
            have = json.loads(fn(src, f"cd {R} && python3 - {arg}", data=RELAY_LIST.encode(), timeout=RELAY_TIMEOUT_S).decode("utf-8", "replace").strip().splitlines()[-1])
            imgs = [f for f in have if not f.endswith("/takes.json")]
            q = "".join(f"[ -f '{f}' ] && stat -c '%n\t%s' '{f}'; " for f in imgs) + "true"
            got = {}
            for ln in fn(dst, f"cd {R} && {q}", timeout=RELAY_TIMEOUT_S).decode("utf-8", "replace").splitlines():
                a = ln.split("\t")
                if len(a) == 2:
                    got[a[0]] = int(a[1])
            sent_sha = (st.get(key) or {}).get("takes_sha") or {}
            todo = [f for f, (size, h) in have.items() if (f.endswith("/takes.json") and sent_sha.get(f) != h)
                    or (not f.endswith("/takes.json") and got.get(f) != size)]
            todo = sorted(f for f in todo if not f.endswith("/takes.json")) + sorted(f for f in todo if f.endswith("/takes.json"))   # 先图后账：账到时图已在
            row.update(listed=len(have), todo=len(todo), mb=round(sum(have[f][0] for f in todo) / 1e6, 2))
            if todo:
                lst = "\n".join(todo).encode()
                blob = fn(src, f"cd {R} && tar cf - -T - 2>/dev/null; true", data=lst, timeout=RELAY_TIMEOUT_S)
                out = fn(dst, f"cd {R} && python3 -c {shlex_quote(RELAY_INSTALL)} {shlex_quote(_renders_prefix(run))}", data=blob, timeout=RELAY_TIMEOUT_S)
                row["installed"] = json.loads(out.decode("utf-8", "replace").strip().splitlines()[-1]).get("installed")
                rec = st.setdefault(key, {})
                rec.setdefault("takes_sha", {}).update({f: have[f][1] for f in todo if f.endswith("/takes.json")})
            _w40_ok(st, key)
        except Exception as e:  # noqa: BLE001
            row["error"] = repr(e)[:300]
            _w40_fail(st, key, f"{src} → {dst} 首尾帧中继失败（集 {eps}）：{repr(e)[:200]}", "视频",
                      f"看 ops/logs/resident_sync.log 的 relay 行；手工：resident_sync.py relay；视频机缺首尾帧 = 视频段不派", RELAY_FAIL_REPORT)
        res["pairs"].append(row)
        log("relay", src, ">", dst, json.dumps({k: row.get(k) for k in ("eps", "todo", "mb", "installed", "error") if k in row}, ensure_ascii=False))
    js(sp, st)
    return res


def _local_lock(p: Path, wait_s: float = 60):
    """跨进程锁 takes.json.lock（与 ns_render.pipeline._file_lock 同一个文件：Windows msvcrt / Linux fcntl）"""
    import contextlib

    @contextlib.contextmanager
    def cm():
        f = open(p, "a+b")
        t0 = time.time()
        try:
            while True:
                try:
                    if os.name == "nt":
                        import msvcrt
                        f.seek(0)
                        msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError:
                    if time.time() - t0 > wait_s:
                        raise TimeoutError(f"拿不到 {p}")
                    time.sleep(0.2)
            yield
        finally:
            try:
                if os.name == "nt":
                    import msvcrt
                    f.seek(0)
                    msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
            f.close()
    return cm()


def relay_pull_laptop(run: str | None = None, part: dict | None = None, ssh_fn=None, state_path: Path | None = None,
                      root: Path | None = None) -> dict:
    """W46（总调度 04:4x 定：ep01 以 gpu33 为准）：中继的同一批集，出图机 → 笔记本回拉（笔记本 takes.json 已分叉）。
    takes.json：出图机的 image / last 段覆盖、笔记本自己的 video 段与 active.video 保留（merge_takes），第一次覆盖前留
    <takes.json>.bak-w46-pull（已有不覆盖）；当前首尾帧文件：本机没有 / 大小不同才拉。增量：takes.json 按上次回拉的远端 sha"""
    run = run or RUN_ID
    root = root or ROOT
    fn = ssh_fn or ssh
    sp = state_path or RELAY_STATE
    st = jl(sp, {}) or {}
    res = {"run": run, "pulls": []}
    groups: dict[str, list[int]] = {}
    for src, _dst, ep in relay_pairs(run, part):
        groups.setdefault(src, []).append(ep)
    for src, eps in sorted(groups.items()):
        key = f"pull:{src}>laptop"
        row = {"src": src, "eps": eps}
        try:
            have = json.loads(fn(src, f"cd {R} && python3 - {run} {','.join(map(str, eps))}", data=RELAY_LIST.encode(),
                                 timeout=RELAY_TIMEOUT_S).decode("utf-8", "replace").strip().splitlines()[-1])
            sent_sha = (st.get(key) or {}).get("takes_sha") or {}
            todo = [f for f, (size, h) in have.items()
                    if (f.endswith("/takes.json") and sent_sha.get(f) != h)
                    or (not f.endswith("/takes.json") and not ((root / f).is_file() and (root / f).stat().st_size == size))]
            todo = sorted(f for f in todo if not f.endswith("/takes.json")) + sorted(f for f in todo if f.endswith("/takes.json"))
            row.update(listed=len(have), todo=len(todo), mb=round(sum(have[f][0] for f in todo) / 1e6, 2))
            if todo:
                blob = fn(src, f"cd {R} && tar cf - -T - 2>/dev/null; true", data="\n".join(todo).encode(), timeout=RELAY_TIMEOUT_S)
                n, backed = 0, []
                with tarfile.open(fileobj=io.BytesIO(blob)) as tf:
                    for m in tf.getmembers():
                        if not m.isfile() or ".." in m.name or not m.name.startswith(_renders_prefix(run)) or m.name not in todo:
                            continue
                        data = tf.extractfile(m).read()
                        dst = root / m.name
                        dst.parent.mkdir(parents=True, exist_ok=True)
                        tmp = dst.with_name(dst.name + ".relay.tmp")
                        if m.name.endswith("/takes.json"):
                            with _local_lock(dst.with_name("takes.json.lock")):
                                cur = jl(dst, None)
                                bak = dst.with_name("takes.json.bak-w46-pull")
                                if dst.is_file() and not bak.exists():
                                    shutil.copy2(dst, bak)
                                    backed.append(str(bak.relative_to(root)).replace("\\", "/"))
                                tmp.write_text(json.dumps(merge_takes(json.loads(data.decode("utf-8")), cur), ensure_ascii=False, indent=1),
                                               encoding="utf-8")
                                os.replace(tmp, dst)
                        else:
                            tmp.write_bytes(data)
                            os.utime(tmp, (m.mtime, m.mtime))
                            os.replace(tmp, dst)
                        n += 1
                row.update(installed=n, backups=backed)
                st.setdefault(key, {}).setdefault("takes_sha", {}).update({f: have[f][1] for f in todo if f.endswith("/takes.json")})
            _w40_ok(st, key)
        except Exception as e:  # noqa: BLE001
            row["error"] = repr(e)[:300]
            _w40_fail(st, key, f"{src} → 笔记本 首尾帧回拉失败（集 {eps}）：{repr(e)[:200]}", "视频",
                      "看 ops/logs/resident_sync.log 的 relay_pull 行；手工：resident_sync.py relay", RELAY_FAIL_REPORT)
        res["pulls"].append(row)
        log("relay_pull", src, "> laptop", json.dumps({k: row.get(k) for k in ("eps", "todo", "mb", "installed", "backups", "error") if k in row},
                                                     ensure_ascii=False)[:400])
    js(sp, st)
    return res


def shlex_quote(s: str) -> str:
    import shlex
    return shlex.quote(s)


def relay_signal() -> dict:
    """O4 事件触发（便宜：只读笔记本本地文件，不连服务器）：puller 每并回一条服务器 outbox（打分完成的首尾帧）acked_total 就 +1
    → {host: acked_total}。变了 = 出图机有新成品，不等定时拍"""
    ps = jl(ROOT / "data/netfix/puller_status.json", {}) or {}
    return {h: int(((ps.get("hosts") or {}).get(h) or {}).get("acked_total") or 0) for h in HOSTS}


def relay_due(now: float, last_t: float, sig: dict, last_sig: dict | None, every_s: float = RELAY_EVERY_S) -> str | None:
    """→ "timer" / "outbox" / None"""
    if now - last_t >= every_s:
        return "timer"
    if last_sig is not None and sig != last_sig:
        return "outbox"
    return None


def relay_thread(every_s: int = RELAY_EVERY_S, poll_s: float = RELAY_POLL_S, sleep=time.sleep, ticks: int | None = None,
                 sig_fn=None, tick_fn=None) -> None:
    """每 every_s 秒一拍 relay_video_frames，另每 poll_s 秒看 puller 回执，出图机有新成品立刻拍一次（O4）；
    NS_RELAY_FRAMES=off 只停这条线；分区里没有“视频归别机”的集 = 空转。ticks / sig_fn / tick_fn 给测试用"""
    sig_fn = sig_fn or relay_signal

    def _tick():
        for run in run_sync_runs():
            relay_video_frames(run)
            relay_pull_laptop(run)        # 同一批集回拉笔记本（以出图机为准）
    tick_fn = tick_fn or _tick
    last_t, last_sig, n = 0.0, None, 0
    while ticks is None or n < ticks:
        n += 1
        try:
            sig = sig_fn()
        except Exception:  # noqa: BLE001  # arch-ok: 回执读不了 = 只按定时拍
            sig = last_sig
        why = relay_due(time.time(), last_t, sig, last_sig, every_s)
        if why:
            last_t, last_sig = time.time(), sig
            if os.environ.get("NS_RELAY_FRAMES", "").lower() not in ("off", "0", "no"):
                try:
                    tick_fn()
                except Exception as e:  # noqa: BLE001
                    log("relay error", repr(e)[:300])
        elif last_sig is None:
            last_sig = sig
        sleep(max(1.0, float(poll_s)))


def run_sync_thread(every_s: int = RUN_SYNC_EVERY_S) -> None:
    """每 every_s 秒对每台服务器跑一拍 run_sync_tick（一台失败不影响另一台）；NS_RUN_SYNC=off 只停这条线"""
    while True:
        t0 = time.time()
        if os.environ.get("NS_RUN_SYNC", "").lower() not in ("off", "0", "no"):
            for h in HOSTS:
                try:
                    run_sync_tick(h)
                except Exception as e:  # noqa: BLE001
                    log("run_sync error", h, repr(e)[:300])
        time.sleep(max(5.0, every_s - (time.time() - t0)))


def control_files() -> list[str]:
    """push_control 推的控制小文件：固定的 + 每部在产剧的 run 级 ready 清单（runs.ready_paths；V2 只认 data/autopilot/runs/<run>/，
    L-178 / ISS-1103-181531：以前只推旧路径 data/autopilot/ready_episodes.json，服务器 producer 对 V2 永远 only=__none__）"""
    out = list(CONTROL_FILES)
    for run in run_sync_runs():
        try:
            for p in _RUNS.ready_paths(run, ROOT):
                rel = Path(p).relative_to(ROOT).as_posix()
                if rel not in out:
                    out.append(rel)
        except Exception as e:  # noqa: BLE001
            log("control_files", run, "ready 路径算不出", repr(e)[:160])
        try:      # L-210 / W-ADULT：项目方在网页点的成人镜触发清单（只有笔记本 API 写；服务器 producer 只读）
            rel = (Path(_RUNS.producer_dir(run, ROOT)) / "owner_triggers.json").relative_to(ROOT).as_posix()
            if rel not in out:
                out.append(rel)
        except Exception as e:  # noqa: BLE001
            log("control_files", run, "触发清单路径算不出", repr(e)[:160])
        try:      # 复审 11-07：V2 项目方“修改 / 重出”写在 data/producer/runs/<run>/master_rejects.json，以前只推旧路径 → 服务器 producer 永远看不到
            rel = (Path(_RUNS.producer_dir(run, ROOT)) / "master_rejects.json").relative_to(ROOT).as_posix()
            if rel not in out:
                out.append(rel)
        except Exception as e:  # noqa: BLE001
            log("control_files", run, "修改清单路径算不出", repr(e)[:160])
        rel = f"data/pipeline/runs/{run}/episode_state.json"   # L-209 S2.2：集关闭标记（只有笔记本写；服务器 producer / night / vidgen 只读）
        if rel not in out:
            out.append(rel)
        rel = f"data/pipeline/runs/{run}/run_phase.json"       # L-209 S2.4：run 级阶段（只有笔记本算；服务器 producer / night / lane_roles 读）
        if rel not in out:
            out.append(rel)
        try:      # L-209 S2.5：两台合并登记表（只有笔记本写；服务器只读，producer 按开关比对 / 取别台事实）
            rel = (Path(_RUNS.producer_dir(run, ROOT)) / "registry_merged.json").relative_to(ROOT).as_posix()
            if rel not in out:
                out.append(rel)
        except Exception as e:  # noqa: BLE001
            log("control_files", run, "合并登记表路径算不出", repr(e)[:160])
    return out


# ---- 坏点②：gpu36 看图服务纳入 resident 管辖
VQA_TICK = True
VQA_EVERY_S = 300                          # 与 health 同拍
VQA_HOST = "gpu36"
VQA_STATE = ROOT / "data/autopilot/vqa_guard.json"
VQA_DOWN_REPORT = 2                        # 拉起后仍连续 2 拍（10 分钟）/health 不通 → 阻断卡点
VQA_LAN_REPORT = 2                         # gpu33 → 10.0.0.36:8870 连续 2 拍不通（本机通）→ 阻断卡点
VQA_STUCK_S = 1800                         # 有排队但 30 分钟没出一个结论 → 阻断卡点（不自动杀：线上重启先审）
SCORE_INFRA_WINDOW_S = 1800
SCORE_INFRA_MAX = 12                       # 30 分钟内某台 producer score_infra / rescore_timeout ≥ 12 次 = 循环（ISS-1103-220512）→ 报警


def vqa_env() -> dict:
    """看图服务启动环境：照 tools/vqa/deploy_offline.sh（gpu36：VQA_GPUS=1 让道模式 + ComfyUI 端口），卡号读 config/vqa.json model.gpus；
    gpu36:2 坏卡 / 专用卡一律剔除（红线）"""
    m = (jl(ROOT / "config/vqa.json", {}) or {}).get("model") or {}
    gpus = [int(g) for g in (m.get("gpus") or [1]) if int(g) != 2] or [1]   # W45 11-04：固定 GPU1（GPU0 让给 Pika）
    ports = m.get("comfy_ports") or {"0": 8188, "1": 8189}
    return {"VQA_GPUS": ",".join(map(str, gpus)), "VQA_COMFY": ",".join(f"{g}:{ports.get(str(g), 8188 + g)}" for g in gpus),
            "port": int(m.get("port") or 8870), "lan_url": m.get("lan_url") or "http://10.0.0.36:8870"}


REMOTE_VQA = r"""
import json, os, subprocess, time, urllib.request
START = __START__; SVCS = json.loads(r'''__SVCS__''')
out = {"now": time.time(), "started": [], "services": {}}
def pids(script, extra):
    # 按 argv 认：argv[0] 是 python、某个参数正好是这个脚本（11-03 22:0x 手工起留下的 bash -c 外壳命令行里也带脚本路径，pgrep -f 会误数）
    found = []
    try:
        names = os.listdir("/proc")
    except OSError as e:
        out.setdefault("errors", []).append("proc " + repr(e)[:80])
        return found
    for d in names:
        if not d.isdigit() or int(d) == os.getpid():
            continue
        try:
            argv = open("/proc/" + d + "/cmdline", "rb").read().decode("utf-8", "replace").split("\0")
        except OSError:
            continue          # 进程刚退出
        if argv and "python" in os.path.basename(argv[0]) and script in argv[1:] and all(x in argv for x in extra):
            found.append(int(d))
    return found
def health(port):
    try:
        return json.loads(urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=8).read()), None
    except Exception as e:
        return None, repr(e)[:160]
def spawn(sv):
    os.makedirs(os.path.dirname(sv["log"]), exist_ok=True)
    p = subprocess.Popen(sv["argv"], cwd=sv["cwd"], env={**os.environ, **sv["env"]}, stdin=subprocess.DEVNULL,
                         stdout=open(sv["log"], "ab"), stderr=subprocess.STDOUT, start_new_session=True)
    if sv.get("pidf"):
        os.makedirs(os.path.dirname(sv["pidf"]), exist_ok=True)
        with open(sv["pidf"], "w") as f:
            f.write(str(p.pid))
    return p.pid
for sv in SVCS:
    r = {"pids": pids(sv["script"], sv.get("match") or [])}
    if sv.get("port"):
        r["health"], r["health_error"] = health(sv["port"])
    # 端口有人应答（如 router / proxy 占着）就不起；没有健康端口的（watcher / 内网转发）只看进程
    down = (r.get("health") is None) if sv.get("port") else True
    script_ok = os.path.isfile(sv["script"] if sv["script"].startswith("/") else os.path.join(sv["cwd"], sv["script"]))
    if START and down and not r["pids"] and script_ok:
        r["started"] = spawn(sv)
        out["started"].append([sv["name"], r["started"]])
    out["services"][sv["name"]] = r
if out["started"]:
    time.sleep(8)
    for sv in SVCS:
        r = out["services"][sv["name"]]
        r["pids"] = pids(sv["script"], sv.get("match") or [])
        if sv.get("port"):
            r["health"], r["health_error"] = health(sv["port"])
S = out["services"]
out["server_pids"] = (S.get("vqa") or {}).get("pids") or []
out["watcher_pids"] = (S.get("watcher") or {}).get("pids") or []
out["health"] = (S.get("vqa") or {}).get("health")
if (S.get("vqa") or {}).get("health_error"):
    out["health_error"] = S["vqa"]["health_error"]
print(json.dumps(out))
"""

REMOTE_LAN = r"""
import json, urllib.request
try:
    h = json.loads(urllib.request.urlopen("__URL__/health", timeout=8).read())
    print(json.dumps({"ok": True, "queue": h.get("queue"), "loaded": h.get("loaded")}))
except Exception as e:
    print(json.dumps({"ok": False, "error": repr(e)[:160]}))
"""

REMOTE_SCORE_INFRA = r"""
import json, time, collections
P = "__P__"; WIN = __WIN__
now = time.time(); c = collections.Counter(); objs = set(); errs = collections.Counter(); last = 0
try:
    lines = open(P, encoding="utf-8", errors="replace").read().splitlines()[-3000:]
except OSError as e:
    print(json.dumps({"error": repr(e)[:160], "now": now})); raise SystemExit(0)
for ln in lines:
    try:
        e = json.loads(ln)
    except ValueError:
        continue
    t = float(e.get("t") or 0)
    if e.get("ev") in ("score_infra", "rescore_timeout") and t >= now - WIN:
        c[e["ev"]] += 1; objs.add(str(e.get("obj"))); errs[str(e.get("error") or "")[:60]] += 1; last = max(last, t)
print(json.dumps({"now": now, "counts": dict(c), "n": sum(c.values()), "objs": sorted(objs)[:20], "errors": errs.most_common(3), "last": last}))
"""


def _remote_json(host: str, script: str, ssh_fn=None, timeout: int = 90) -> dict:
    raw = (ssh_fn or ssh)(host, "python3 -", data=script.encode("utf-8"), timeout=timeout, tries=2).decode("utf-8", "replace")
    rows = [ln for ln in raw.splitlines() if ln.startswith("{")]
    if not rows:
        raise RuntimeError(f"{host} 探测没有 JSON 输出：{raw[-200:]}")
    return json.loads(rows[-1])


ANOMALY_PORT = 8893
ANOMALY_GPU_DEFAULT = 1                    # W38 02:1x 实测 GPU1 可用；原 ops/factory/anomaly_resident.sh 写死 GPU2 = 坏卡红线


def anomaly_gpu() -> int:
    """人数检测常驻用哪张卡：config/vqa.json anomaly.gpu（没有就 1）；2 一律拒（gpu36:2 红线）→ 退回 1"""
    g = ((jl(ROOT / "config/vqa.json", {}) or {}).get("anomaly") or {}).get("gpu", ANOMALY_GPU_DEFAULT)
    try:
        g = int(g)
    except (TypeError, ValueError):
        g = ANOMALY_GPU_DEFAULT
    return ANOMALY_GPU_DEFAULT if g == 2 else g


def vqa_services(host: str = VQA_HOST) -> list[dict]:
    """gpu36 上 resident 管的四个进程（起法照 tools/vqa/deploy_offline.sh 与 ops/factory/anomaly_resident.sh，但卡号在这里定、不碰 GPU2）：
    vqa 看图 :8870 / watcher / anomaly 人数检测 :8893 / anomaly 的内网入口 10.0.0.36:8893（8870 的内网入口由 lan_proxy_keepalive 管）"""
    env = vqa_env()
    fw = OFF.rsplit("/", 1)[0]                       # = config/vqa.json model.dir 的上级（与 OFF 同根，不另写死）
    b = fw + "/vqa"
    lan_host = env["lan_url"].split("//", 1)[-1].split(":", 1)[0]
    return [
        {"name": "vqa", "port": env["port"], "script": b + "/server.py", "cwd": b, "argv": [b + "/venv/bin/python", "-u", b + "/server.py"],
         "env": {"VQA_GPUS": env["VQA_GPUS"], "VQA_COMFY": env["VQA_COMFY"], "HF_HOME": b + "/hf", "PYTHONUNBUFFERED": "1"},
         "log": b + "/logs/server.log", "pidf": b + "/server.pid"},
        {"name": "watcher", "script": "tools/vqa/watch.py", "cwd": R, "argv": [b + "/venv/bin/python", "-u", "tools/vqa/watch.py"],
         "env": {"OFFLINE_SELF": host, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}, "log": OFF + "/logs/vqa.out", "pidf": OFF + "/run/vqa.pid"},
        {"name": "anomaly", "port": ANOMALY_PORT, "script": "tools/vqa/anomaly_server.py", "cwd": R,
         "argv": [fw + "/venv/bin/python", "-u", "tools/vqa/anomaly_server.py"],
         "env": {"CUDA_VISIBLE_DEVICES": str(anomaly_gpu()), "CUDA_DEVICE_ORDER": "PCI_BUS_ID", "ANOMALY_PORT": str(ANOMALY_PORT),
                 "ANOMALY_COMFY_ROOT": fw + "/comfy", "NS_SCORE_THREADS": "4", "OMP_NUM_THREADS": "4", "MKL_NUM_THREADS": "4"},
         "log": fw + "/factory/logs/anomaly_resident.log", "pidf": fw + "/factory/run/anomaly_resident.pid"},
        {"name": "anomaly_lan", "script": "tools/netfix/lan_proxy.py", "match": [str(ANOMALY_PORT)], "cwd": R,
         "argv": ["python3", "tools/netfix/lan_proxy.py", "--bind", lan_host, "--port", str(ANOMALY_PORT), "--allow", "10.0.0.33",
                  "--target", f"127.0.0.1:{ANOMALY_PORT}"],
         "env": {}, "log": fw + "/factory/logs/anomaly_lan_proxy.log", "pidf": fw + "/factory/run/anomaly_lan_proxy.pid"},
    ]


def vqa_probe(host: str = VQA_HOST, start: bool = True, ssh_fn=None) -> dict:
    script = (REMOTE_VQA.replace("__START__", "True" if start else "False")
              .replace("__SVCS__", json.dumps(vqa_services(host), ensure_ascii=False)))
    return _remote_json(host, script, ssh_fn, timeout=150)


def score_infra_probe(host: str, run: str = RUN_ID, ssh_fn=None) -> dict:
    script = (REMOTE_SCORE_INFRA.replace("__P__", f"{R}/{producer_rel(run)}/log.jsonl").replace("__WIN__", str(SCORE_INFRA_WINDOW_S)))
    return _remote_json(host, script, ssh_fn)


def vqa_tick(ssh_fn=None, issue_fn=None, live_fn=None, start: bool = True) -> dict:
    """一拍：① gpu36 本机探 /health + server / watcher 进程，不在就按 deploy_offline.sh 的口径拉起（只起不在的、不杀在跑的）；
    ② 从 gpu33 经 lan_proxy 探 10.0.0.36:8870（producer 实际走的路）；③ 每台 producer 的 score_infra 次数（ISS-1103-220512）。
    拉起成功 → V2_LIVE 一行；拉起后仍不通 / 卡住 / 内网不通 / score_infra 超上限 → report_issue 阻断（每段只登一次）"""
    st = jl(VQA_STATE, {}) or {}
    res = {"at": time.strftime("%F %T")}
    live = live_fn or (lambda line: _lc_live(ROOT, line))
    try:
        p = vqa_probe(VQA_HOST, start=start, ssh_fn=ssh_fn)
        h = p.get("health") or None
        res.update(local_ok=bool(h), server=len(p.get("server_pids") or []), watcher=len(p.get("watcher_pids") or []), started=p.get("started"),
                   loaded=(h or {}).get("loaded"), queue=(h or {}).get("queue"), served=(h or {}).get("served"),
                   health_error=p.get("health_error"))
        an = (p.get("services") or {}).get("anomaly") or {}
        res.update(anomaly=len(an.get("pids") or []), anomaly_loaded=(an.get("health") or {}).get("loaded"),
                   anomaly_lan_proxy=len(((p.get("services") or {}).get("anomaly_lan") or {}).get("pids") or []))
        if p.get("started"):
            live(f"🔧 resident_sync（W40）：{VQA_HOST} {[x[0] for x in p['started']]} 不在 → 已自动拉起（人数检测卡 GPU{anomaly_gpu()}，不碰 GPU2）；"
                 f"看图 /health {'通' if h else '暂未通'}，人数检测 /health {'通' if an.get('health') else '暂未通'}（加载中下拍再看）")
        if "anomaly" in (p.get("services") or {}):
            if an.get("health"):
                _w40_ok(st, "vqa:anomaly")
            else:
                _w40_fail(st, "vqa:anomaly", f"{VQA_HOST} 人数检测 127.0.0.1:{ANOMALY_PORT}/health 不通（进程 {res['anomaly']} 个；"
                                             f"{'本拍已自动拉起' if any(x[0] == 'anomaly' for x in p.get('started') or []) else '进程在但不应答'}）："
                                             f"{an.get('health_error')} → QB count=untested → score_infra 循环", "出图检测",
                          f"gpu36 上看 factory/logs/anomaly_resident.log；起法 ops/factory/anomaly_resident.sh（GPU{anomaly_gpu()}，GPU2 红线）",
                          VQA_DOWN_REPORT, issue_fn)
        if h:
            _w40_ok(st, "vqa:health")
            now = float(p.get("now") or time.time())
            q, last_job = int(h.get("queue") or 0), float(h.get("last_job") or h.get("started") or now)
            if q > 0 and now - last_job > VQA_STUCK_S:
                _w40_fail(st, "vqa:stuck", f"{VQA_HOST} 看图服务排队 {q} 张，{int((now - last_job) / 60)} 分钟没出一个结论"
                                           f"（loaded={h.get('loaded')} waiting={h.get('why_waiting')}）", "看图",
                          "看 /root/work/…/vqa/logs/server.log；卡在等显存就查 ComfyUI 队列；确认后手工重启 server.py", 1, issue_fn)
            else:
                _w40_ok(st, "vqa:stuck")
        else:
            _w40_fail(st, "vqa:health", f"{VQA_HOST} 看图服务 127.0.0.1:{vqa_env()['port']}/health 不通（server 进程 {res['server']} 个、"
                                        f"watcher {res['watcher']} 个；{'本拍已自动拉起' if p.get('started') else '进程在但不应答'}）：{p.get('health_error')}",
                      "看图", "gpu36 上看 vqa/logs/server.log；进程在但不应答需人工重启（resident 不杀在跑的进程）", VQA_DOWN_REPORT, issue_fn)
    except Exception as e:  # noqa: BLE001
        res["error"] = repr(e)[:300]
        _w40_fail(st, "vqa:health", f"{VQA_HOST} 看图服务探测失败：{repr(e)[:200]}", "看图",
                  "检查 gpu36 命令主连接（tunnel_supervisor）；连上后下一拍自动探测 / 拉起", VQA_DOWN_REPORT + 1, issue_fn)
    lan_from = [x for x in HOSTS if x != VQA_HOST]
    an_url = vqa_env()["lan_url"].rsplit(":", 1)[0] + f":{ANOMALY_PORT}"
    for src in lan_from:
        try:
            alan = _remote_json(src, REMOTE_LAN.replace("__URL__", an_url), ssh_fn)
            res[f"anomaly_lan_from_{src}"] = alan
            if alan.get("ok") or not res.get("anomaly_loaded"):
                _w40_ok(st, f"vqa:anomaly_lan:{src}")
            else:
                _w40_fail(st, f"vqa:anomaly_lan:{src}", f"{src} → {an_url} 人数检测内网入口不通（gpu36 本机通）：{alan.get('error')}",
                          "出图检测", "gpu36 上 anomaly 的 lan_proxy（tools/netfix/lan_proxy.py --port 8893）；resident 下拍会补起", VQA_LAN_REPORT, issue_fn)
        except Exception as e:  # noqa: BLE001
            res[f"anomaly_lan_from_{src}"] = {"error": repr(e)[:160]}
        try:
            lan = _remote_json(src, REMOTE_LAN.replace("__URL__", vqa_env()["lan_url"]), ssh_fn)
            res[f"lan_from_{src}"] = lan
            if lan.get("ok"):
                _w40_ok(st, f"vqa:lan:{src}")
            elif res.get("local_ok"):                                  # 本机通、内网不通 = lan_proxy 的事
                try:
                    lan_proxy_keepalive()
                except Exception as e:  # noqa: BLE001
                    log("vqa_tick lan_proxy_keepalive", repr(e)[:160])
                _w40_fail(st, f"vqa:lan:{src}", f"{src} → {vqa_env()['lan_url']} 看图内网入口不通（gpu36 本机通）：{lan.get('error')}",
                          "看图", "gpu36 上 bash netfix/lan_proxy.sh；查 10.0.0.33→10.0.0.36:8870 防火墙", VQA_LAN_REPORT, issue_fn)
        except Exception as e:  # noqa: BLE001
            res[f"lan_from_{src}"] = {"error": repr(e)[:160]}
    for hst in HOSTS:
        try:
            si = score_infra_probe(hst, ssh_fn=ssh_fn)
            res[f"score_infra_{hst}"] = si.get("n")
            if int(si.get("n") or 0) >= SCORE_INFRA_MAX:
                _w40_fail(st, f"score_infra:{hst}",
                          f"{hst} producer 30 分钟内 score_infra / rescore_timeout {si.get('n')} 次（{si.get('counts')}，"
                          f"涉及 {len(si.get('objs') or [])} 个对象，例 {(si.get('objs') or [])[:3]}，错误 {si.get('errors')}）= 只重打分循环"
                          f"（ISS-1103-220512）；gpu36 看图本拍：server={res.get('server')} loaded={res.get('loaded')} queue={res.get('queue')} "
                          f"内网={((res.get('lan_from_gpu33') or {}).get('ok'))}", "出图检测",
                          "看图通 → 查 producer 打分链路（ns_render postflight remote_error）；看图不通 → 先修 gpu36 看图；"
                          "producer 侧重打分次数上限需改 producer.py（W38 所有）", 1, issue_fn)
            else:
                _w40_ok(st, f"score_infra:{hst}")
        except Exception as e:  # noqa: BLE001
            res[f"score_infra_{hst}"] = {"error": repr(e)[:160]}
    st["last"] = res
    js(VQA_STATE, st)
    log("vqa_tick", json.dumps(res, ensure_ascii=False)[:600])
    return res


def vqa_thread(every_s: int = VQA_EVERY_S) -> None:
    while True:
        t0 = time.time()
        if os.environ.get("NS_VQA_GUARD", "").lower() not in ("off", "0", "no"):
            try:
                vqa_tick()
            except Exception as e:  # noqa: BLE001
                log("vqa_tick error", repr(e)[:300])
        time.sleep(max(5.0, every_s - (time.time() - t0)))


def loop(pull_every_s: int = 1200, health_every_s: int = 300):
    """5 分钟一次健康 / 报警；20 分钟一次并回；代码有改动 → 推代码 + 服务器热重启（每台独立，一台断连不影响另一台）"""
    last_pull = {h: 0.0 for h in HOSTS}
    if AUTOFLOW_TICK:                    # DISTILL 编排器每拍：独立守护线程，60 s 一拍（K-OPS-W22）
        import threading
        for part in AUTOFLOW_PARTS:
            threading.Thread(target=autoflow_thread, kwargs={"part": part}, name=f"autoflow_{part}", daemon=True).start()
        log("autoflow_tick", "三条线线程已启动", list(AUTOFLOW_PARTS), AUTOFLOW_EVERY_S, "s 一拍")
    if FACTORY_SYNC_EVERY_S:             # FACTORY 11-02：参考板一变就重建期望 refs 表并补推（sync.py auto，没变化什么都不做），独立线程、失败只记日志
        import threading
        threading.Thread(target=factory_sync_thread, name="factory_sync_auto", daemon=True).start()
    if RELEASE_TICK:                     # W17：发版流水线（复审通过标记 → 拼树 → dry → cut → deploy --verify → 换代 L-152）
        import threading
        threading.Thread(target=release_thread, name="release_tick", daemon=True).start()
    if EPISODE_RUN_TICK:                 # CODER-RES：episode_run 常驻（无人值守推进一集；config/pipeline/episode_run.json enabled）
        import threading
        threading.Thread(target=episode_run_thread, name="episode_run", daemon=True).start()
    if LIFECYCLE_TICK:                   # W18：主剧到“出图”自动起 producer / night（开关 sop_gate.json lifecycle.apply，默认只算计划）
        import threading
        threading.Thread(target=lifecycle_thread, name="lifecycle_tick", daemon=True).start()
    if RUN_SYNC_TICK:                    # W40 坏点①：在产剧 run 级产物（sop_gate 证据 / 派生参考图 / 资产清单 / 导入稿）每 2 分钟增量同步两台
        import threading
        threading.Thread(target=run_sync_thread, name="run_sync", daemon=True).start()
        threading.Thread(target=relay_thread, name="relay_frames", daemon=True).start()   # W46：出图机 → 视频机首尾帧中继
        log("run_sync", "线程已启动", RUN_SYNC_EVERY_S, "s 一拍", list(HOSTS))
    if VQA_TICK:                         # W40 坏点②：gpu36 看图服务 / watcher 探测 + 不在就拉起 + 内网入口 + score_infra 上限报警（与 health 同拍）
        import threading
        threading.Thread(target=vqa_thread, name="vqa_guard", daemon=True).start()
        log("vqa_guard", "线程已启动", VQA_EVERY_S, "s 一拍", VQA_HOST)
    while True:
        try:                                     # FIX-ORCH O2（L-202 按镜）：资产按镜齐了的镜并进 ready（本地文件），下面 push_control 照常推
            import episode_pipeline as _EPL
            for _run in _RUNS.list_runs(ROOT):
                _EPL.sync_shot_ready(_run, push=lambda _h: None)
        except Exception as e:  # noqa: BLE001
            log("shot_ready error", repr(e)[:200])
        for h in HOSTS:
            try:
                health(h)
            except Exception as e:  # noqa: BLE001
                log("health error", h, repr(e)[:200])
            try:                                 # K-OPS-W25：额外剧的临时 control 按 partition 自动生成（先于拉起，防全派）
                sync_run_controls(h)
            except Exception as e:  # noqa: BLE001
                log("run_control error", h, repr(e)[:200])
            try:                                 # K-OPS-W25：额外剧（第二季等）的 producer serve --run 挂了就拉起（只起不在的，STOP 时不起）
                ensure_runs(h)
            except Exception as e:  # noqa: BLE001
                log("ensure_runs error", h, repr(e)[:200])
            try:                                 # DJ-20 重启队列：合并各方请求，30 分钟一次、先排空，紧急插队记审计（K-OPS-W16）
                import restart_queue as RQ
                RQ.process(h)
            except Exception as e:  # noqa: BLE001
                log("restart_queue error", h, repr(e)[:200])
            try:                                 # NETFIX 接口：控制小文件变了就推（按对象合并 / 快照覆盖），推完 server-control
                push_control(h)
                if h == "gpu36":
                    lan_proxy_keepalive()
                if h == review_lan_proxy_host():          # L-207：审图位（gpu33）内网入口保活（开关 lane_roles.json review.lan_proxy）
                    review_lan_proxy_keepalive(h)
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
        ssh(host, f"set -e; T=$(mktemp -d {OFF}/.push.XXXXXX); tar xf - -C $T; " + atomic_install_cmd(R) + "; echo ok",
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
                    f"PYTHONUTF8=1 {PY[host]} tools/series10_video/build_jobs.py >/tmp/build_jobs.out 2>&1; "
                    f"tail -c 300 /tmp/build_jobs.out; {PY[host]} -", data=REBUILD_CHECK.replace("__RUN__", RUN_ID).encode(), timeout=2400, tries=3)
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
    txt = ssh(host, f"cd {R} && {PY[host]} ops/offline/resident_prep.py {host} video-only && "
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
            ssh(host, f"set -e; T=$(mktemp -d {OFF}/.push.XXXXXX); tar xf - -C $T; " + atomic_install_cmd(R) + "; echo ok",
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
        ssh(host, f"set -e; T=$(mktemp -d {OFF}/.push.XXXXXX); tar xf - -C $T; " + atomic_install_cmd(R) + "; echo ok",
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
def _smoke_lane(host: str) -> tuple[int, str]:
    """冒烟用的道：hosts.json 里该机最后一条启用的出图道（本机端口 + 输出目录）；原来写死的 gpu36:2 是死口（L-100 改看图卡）"""
    ln = sorted(_HOSTS.lanes(host, role="image"))[-1]
    rec = _HOSTS.lanes(host, role="image")[ln]
    return int(rec["comfy_port"]), _HOSTS.comfy_output(ln)


SMOKE_LANE = {h: _smoke_lane(h) for h in SERVERS}


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
    ssh(host, f"rm -f /tmp/resident_smoke_result.json; setsid nohup {PY[host]} /tmp/resident_smoke.py "
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
    elif cmd == "pull-active-videos":          # 补拉当前版本视频：pull-active-videos <host> [--dry]
        print(json.dumps(pull_active_videos(argv[1], dry="--dry" in argv), ensure_ascii=False))
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
    elif cmd == "lifecycle":     # W18：lifecycle [--dry|--apply]（不给 = 按 sop_gate.json lifecycle.apply）
        dry = True if "--dry" in argv else (False if "--apply" in argv else None)
        print(json.dumps(lifecycle_tick(dry=dry), ensure_ascii=False, indent=1, default=str))
    elif cmd == "run_sync":      # W40：run_sync [HOST…] [--dry]（不给 HOST = 两台）
        for h in [a for a in argv[1:] if not a.startswith("--")] or list(HOSTS):
            print(json.dumps(run_sync_tick(h, dry="--dry" in argv), ensure_ascii=False)[:2000])
    elif cmd == "relay":         # W46：relay [--pairs]（--pairs = 只打印按 partition 算出的 出图机→视频机 集，不传）
        if "--pairs" in argv:
            print(json.dumps(relay_pairs(RUN_ID), ensure_ascii=False))
        else:
            print(json.dumps(relay_video_frames(), ensure_ascii=False, indent=1)[:3000])
            print(json.dumps(relay_pull_laptop(), ensure_ascii=False, indent=1)[:3000])
        if "--loop" in argv:                  # W46：常驻没重启时单独跑这条线（同一份代码，每 RELAY_EVERY_S 一拍）
            relay_thread()
    elif cmd == "vqa":           # W40：vqa [--dry]（--dry = 只探不拉起）
        print(json.dumps(vqa_tick(start="--dry" not in argv), ensure_ascii=False, indent=1)[:3000])
    elif cmd == "loop":
        loop()
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
