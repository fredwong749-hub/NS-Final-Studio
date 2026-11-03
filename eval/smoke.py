"""W26 SMOKE-GATE：Phase R 冒烟门（RSI 实施包 §4）。入口 eval/run_smoke.ps1 → 本文件 run。

固定 3 镜迷你剧本 eval/smoke/P4_smoke.md → 剧 smoke_v2（config/pipeline/runs.json 登记，平时 paused），逐门脚本判定 G1–G8：
  每门 = 采集（collect_gN：调现成 CLI / 函数、读文件，只读或只写 smoke_v2 自己的目录）+ 判定（judge_gN：纯函数，证据 → ok）。
  不许用 LLM 判任何门；不改渲染 / producer 代码；过不去就记失败门 + 原因。评分表 = eval/smoke_rubric.md。
输出：控制台表（门 | 通过/失败 | 证据 | 耗时）、eval/results/<YYYYMMDD-HHMM>.json（schema nsfs.smoke/1）、退出码 = 失败门数。

清目录 = 隔离不删（CLAUDE.md 红线）：上一次的 smoke_v2 产物整目录挪到 data/quarantine/smoke_v2/<时间>/。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVAL = ROOT / "eval"
SMOKE = EVAL / "smoke"
RUN = "smoke_v2"
EP = 1
SCHEMA = "nsfs.smoke/1"
GATES = ["G1", "G2", "G3", "G4", "G5", "G6", "G7", "G8"]
GATE_NAME = {"G1": "启动", "G2": "输入", "G3": "角色", "G4": "生成", "G5": "合成", "G6": "规格", "G7": "幂等", "G8": "无人值守"}
# smoke_v2 的全部产物目录（每次先整目录隔离；G7 比对这些目录的结构）
SMOKE_DIRS = ["data/pipeline/runs/smoke_v2", "data/import/runs/smoke_v2", "data/pipeline/sop_gate/smoke_v2",
              "data/pipeline/asset_jobs/smoke_v2", "data/renders/smoke_v2", "data/producer/runs/smoke_v2",
              "data/episodes/smoke_v2", "data/autopilot/runs/smoke_v2"]
STRUCT_DIRS = SMOKE_DIRS[:4]           # G7 第二遍只重跑 G2 结构（不重出图）→ 只比这四个
# 3 镜迷你剧本按设计过不了的生产校验（validate_qwen_script：一集 6–8 镜 / 60–120 秒）；其余 block 一律算 G2 失败
EXPECTED_VALIDATE_BLOCKS = {"QW-E2", "QW-E3"}
CONFIG_IMPORTS = ["tools.autopilot.runs", "tools.master.sop_gate", "ns_schema.script", "ns_agent.frame_job",
                  "ns_agent.gen_contract.preflight", "ns_agent.asset_refs", "ns_render.pipeline", "ns_render.unified_frame",
                  "ns_render.image_params", "ns_post.assemble", "ns_api.app"]
PROCS = {"autoflow_resident": "autoflow_resident.py", "tunnel_supervisor": "tunnel_supervisor.py"}
OOM_RE = re.compile(r"out of memory|CUDA_ERROR_OUT_OF_MEMORY|\bOOM\b|torch\.cuda\.OutOfMemoryError", re.I)
TIMEOUT_RE = re.compile(r"timed? ?out|超时", re.I)
VOLATILE_KEYS = {"at", "imported_at", "created_at", "generated_at", "updated_at", "ts", "t", "started_at", "done_at", "mtime"}
TS_IN_NAME = re.compile(r"\d{8}[-_T]?\d{4,6}")
# W32：:8800 冷启动慢（R2 16:52 G1 “TimeoutError: timed out”）→ 单次 30 s、失败再试 2 次（共 3 次）；G1 / G8 都走这里
API_TIMEOUT_S = 30.0
API_RETRIES = 2
API_RETRY_SLEEP_S = 3.0
# W32：G4 / G3 只认本剧本次窗口自己出的版本（W26b：adopt 会把 V1 旧图登记进 smoke_v2 的 takes）
RENDERS_PREFIX = f"renders/{RUN}/"       # take.file 相对 data/
STAGE_KIND = {"image": "first", "last": "last", "video": "video"}
T0_SLACK_S = 2.0
REF_SUFFIX = re.compile(r"\s+\(.*\)$")   # 参考里 "data/renders/…/frame.png (image v3)" 的说明后缀


# ------------------------------------------------------------------ 小工具
def py() -> str:
    p = ROOT / ".venv/Scripts/python.exe"
    return str(p) if p.is_file() else sys.executable


def sh(cmd: list[str], timeout: float, env: dict | None = None) -> tuple[int, str]:
    """跑一条命令（stdin 关死 = 不可能等人输入）；超时 → rc=124"""
    e = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1", **(env or {})}
    try:
        p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=timeout, env=e, stdin=subprocess.DEVNULL)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except subprocess.TimeoutExpired as ex:
        out = ex.stdout.decode("utf-8", "replace") if isinstance(ex.stdout, bytes) else (ex.stdout or "")
        return 124, out + f"\n[smoke] 超时 {timeout:.0f}s"
    except OSError as ex:
        return 127, f"[smoke] 起不来：{ex}"


def jl(p: Path, default=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return default


def http_json(url: str, timeout: float = 10.0):
    """→ (status, json|None, err)"""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            body = r.read()
            try:
                return r.status, json.loads(body.decode("utf-8")), ""
            except ValueError:
                return r.status, None, "not json"
    except Exception as ex:  # noqa: BLE001  采集：连不上 = 证据里写原因
        code = getattr(ex, "code", 0) or 0
        return code, None, f"{type(ex).__name__}: {ex}"[:200]


def http_json_retry(url: str, timeout: float = API_TIMEOUT_S, retries: int = API_RETRIES,
                    sleep_s: float = API_RETRY_SLEEP_S):
    """→ (status, json|None, err, attempts)。200 即停；其余（超时 / 拒连 / 5xx）再试，最多 1 + retries 次"""
    st, d, err, n = 0, None, "", 0
    for n in range(1, retries + 2):
        st, d, err = http_json(url, timeout=timeout)
        if st == 200:
            break
        if n <= retries:
            time.sleep(sleep_s)
    return st, d, err, n


def port_open(host: str, port: int, timeout: float = 3.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def rel(p: Path) -> str:
    try:
        return Path(p).resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return Path(p).as_posix()


def sha_file(p: Path) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def runs_mod():
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from tools.autopilot import runs as RN
    return RN


def sop_gate_mod():
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from tools.master import sop_gate as SG
    return SG


def preset() -> dict:
    return jl(SMOKE / "preset.json", {}) or {}


# ------------------------------------------------------------------ 清目录（隔离不删）+ 模板
def quarantine_smoke(root: Path, stamp: str, dirs: list[str] = SMOKE_DIRS) -> list[str]:
    """把上次残留的 smoke_v2 目录整目录挪到 data/quarantine/smoke_v2/<stamp>/（不删文件）；返回挪走了哪些"""
    moved = []
    for d in dirs:
        src = root / d
        if src.exists():
            dst = root / "data/quarantine/smoke_v2" / stamp / d.replace("/", "__")
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))
            moved.append(d)
    return moved


def seed_from_template(root: Path, smoke: Path = SMOKE) -> list[str]:
    """干净模板 → data/pipeline/runs/smoke_v2（P1 / 造型 = series10_v2 只读拷贝，v1_leak 白名单要本剧 P1）+ P4_ep01.md"""
    rd = root / "data/pipeline/runs" / RUN
    shutil.copytree(smoke / "template/pipeline_run", rd)
    shutil.copy2(smoke / "P4_smoke.md", rd / "P4_ep01.md")
    files = sorted(rel(p) if root == ROOT else p.relative_to(root).as_posix() for p in rd.rglob("*") if p.is_file())
    if seed_schedule(root, smoke):
        files.append(HUB_EP_LOOKS_REL)
    return files


# 本集造型排期文件（全局，{project:{cid:{"集号":造型}}}）= ns_agent.asset_refs.HUB_EP_LOOKS（测试核对两者一致）
HUB_EP_LOOKS_REL = "data/looks/hub_episode_looks.json"


def seed_schedule(root: Path, smoke: Path = SMOKE) -> bool:
    """W26b R2：模板 template/hub_episode_looks.json 的 smoke_v2 条目 → 全局排期文件的 smoke_v2 键（整键替换，别的剧一个字不动）。
    已一致不写（幂等）；原子替换。返回是否写了。模板没有 / 排期文件读不出 → 不写（读不出交给 episode_ready 报，不覆盖坏文件）"""
    tpl = jl(smoke / "template/hub_episode_looks.json", None)
    want = (tpl or {}).get(RUN) if isinstance(tpl, dict) else None
    if not isinstance(want, dict):
        return False
    p = root / HUB_EP_LOOKS_REL
    if p.exists():
        d = jl(p, None)
        if not isinstance(d, dict):
            return False
    else:
        d = {}
    if d.get(RUN) == want:
        return False
    d[RUN] = want
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".smoke.tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, p)
    return True


# ------------------------------------------------------------------ 结构指纹（G7）
def _norm_name(s: str) -> str:
    return TS_IN_NAME.sub("<ts>", s)


def _strip_volatile(o):
    if isinstance(o, dict):
        return {k: _strip_volatile(v) for k, v in sorted(o.items()) if k not in VOLATILE_KEYS}
    if isinstance(o, list):
        return [_strip_volatile(x) for x in o]
    return o


def tree_fingerprint(root: Path, dirs: list[str]) -> dict:
    """{相对路径（时间戳归一）: 内容指纹}：.json 去掉时间字段后哈希，其它文件按字节哈希；→ {files, sha}"""
    files: dict[str, str] = {}
    for d in dirs:
        base = root / d
        if not base.exists():
            continue
        for p in sorted(base.rglob("*")):
            if not p.is_file() or p.suffix in (".tmp", ".lock", ".pid"):
                continue
            k = _norm_name(p.relative_to(root).as_posix())
            if p.suffix == ".json":
                d0 = jl(p, None)
                blob = json.dumps(_strip_volatile(d0), ensure_ascii=False, sort_keys=True).encode("utf-8") if d0 is not None \
                    else p.read_bytes()
            else:
                blob = p.read_bytes()
            files[k] = hashlib.sha256(blob).hexdigest()[:16]
    sha = hashlib.sha256(json.dumps(files, sort_keys=True).encode("utf-8")).hexdigest()[:16]
    return {"files": files, "sha": sha}


# ------------------------------------------------------------------ 判定（纯函数：证据 → (ok, why)）
def judge_g1(f: dict) -> tuple[bool, str]:
    bad = []
    if f.get("api_status") != 200:
        bad.append(f"API :8800 /api/sop/status 不通（{f.get('api_status')} {f.get('api_err', '')}；"
                   f"试 {f.get('api_attempts', 1)} 次 × {f.get('api_timeout_s', API_TIMEOUT_S):.0f}s）")
    for k in PROCS:
        if not (f.get("procs") or {}).get(k):
            bad.append(f"进程 {k} 不在")
    if not f.get("vqa_8870"):
        bad.append("本机看图 :8870 /health 不通")
    if f.get("config_errors"):
        bad.append(f"配置读不了 {len(f['config_errors'])} 个（例 {f['config_errors'][0]}）")
    if f.get("import_errors"):
        bad.append(f"关键模块 import 失败 {len(f['import_errors'])} 个（例 {f['import_errors'][0]}）")
    return (not bad), "；".join(bad) or "API / 进程 / 8870 / 配置 / import 全部正常"


def judge_g2(f: dict) -> tuple[bool, str]:
    bad = []
    extra = sorted(set(f.get("validate_blocks") or []) - EXPECTED_VALIDATE_BLOCKS)
    if extra:
        bad.append(f"导入校验有预期外 block：{extra}")
    if f.get("import_rc") != 0:
        bad.append(f"import_script 失败 rc={f.get('import_rc')}：{f.get('import_why', '')}")
    if f.get("shots") != 3:
        bad.append(f"导入稿 ep01 镜数 {f.get('shots')} ≠ 3")
    if not f.get("assets_ready"):
        bad.append(f"资产就绪没过：{f.get('assets_why', '')}")
    pr = f.get("prompts") or {}
    if not pr.get("ok"):
        bad.append(f"提示词没过：{pr.get('why', '没跑到')}")
    return (not bad), "；".join(bad) or "导入 + 资产就绪 + 3/3 镜提示词编译 preflight 过"


def judge_g3(f: dict) -> tuple[bool, str]:
    bad = []
    rows = f.get("refs") or {}
    if len(rows) != 3:
        bad.append(f"编译探针只拿到 {len(rows)}/3 镜")
    for n, r in sorted(rows.items()):
        if r.get("error"):
            bad.append(f"镜{n} 编译出错 {r['error'][:120]}")
        elif not r.get("face_files"):
            bad.append(f"镜{n} 没有解析出身份脸")
        elif r.get("missing_refs"):
            bad.append(f"镜{n} 参考文件不存在 {r['missing_refs'][:2]}")
    rr = f.get("render_refs")
    if rr is None:
        bad.append("producer log.jsonl 没有（G4 没出图）→ 出图参考按名加载无法核对")
    else:
        for o in (f"{k}:ep{EP:02d}-S{n}" for n in (1, 2, 3) for k in ("first", "last")):
            row = rr.get(o) or {}
            if not row.get("ok"):
                bad.append(f"{o} 出图参考没按名加载：{(row.get('why') or '没有记录')[:100]}")
    return (not bad), "；".join(bad) or "3 镜身份脸 / 设定图按名解析到文件；6 个对象本次 rendered 版本的参考列表非空、文件全在、含身份脸"


def judge_g4(f: dict) -> tuple[bool, str]:
    bad = []
    if f.get("skipped"):
        return False, f"未执行：{f['skipped']}"
    if f.get("rc") == 124:
        bad.append(f"超时（{f.get('timeout_s')}s）")
    elif f.get("rc") not in (0, None):
        bad.append(f"producer 退出码 {f.get('rc')}")
    for k in ("first", "last", "video"):
        have = f.get(k) or {}
        miss = [n for n in ("1", "2", "3") if not have.get(n)]
        if miss:
            bad.append(f"{ {'first': '首帧', 'last': '尾帧', 'video': '视频'}[k] } 缺镜 {miss}")
    if bad and f.get("excluded_count"):
        bad.append(f"另有 {f['excluded_count']} 个版本不算（adopt / 旧窗口 / 不在 renders/{RUN}/，例 {(f.get('excluded') or [''])[0][:80]}）")
    if f.get("oom"):
        bad.append(f"日志有 OOM：{f['oom'][0][:120]}")
    if f.get("timeouts"):
        bad.append(f"日志有超时：{f['timeouts'][0][:120]}")
    return (not bad), "；".join(bad) or "本次窗口 3 首帧 + 3 尾帧 + 3 段视频都是自己出的（非 adopt）且有文件，无 OOM / 超时"


def judge_g5(f: dict) -> tuple[bool, str]:
    if f.get("skipped"):
        return False, f"未执行：{f['skipped']}"
    if f.get("rc") != 0:
        return False, f"assemble_episode 退出码 {f.get('rc')}：{f.get('tail', '')[:160]}"
    if not f.get("mp4"):
        return False, "没有拼出 mp4"
    if f.get("placeholders"):
        return False, f"成片里有 {f['placeholders']} 镜是静帧占位（不是生成视频）"
    return True, f"拼出 {f['mp4']}"


def judge_g6(f: dict) -> tuple[bool, str]:
    if f.get("skipped"):
        return False, f"未执行：{f['skipped']}"
    want, out = f.get("want") or {}, f.get("probe") or {}
    if not out:
        return False, f"ffprobe 读不出：{f.get('err', '')}"
    bad = []
    tol = float(want.get("duration_tol_s", 2.0))
    if out.get("duration") is None or abs(float(out["duration"]) - float(want.get("duration", 0))) > tol:
        bad.append(f"时长 {out.get('duration')}s ≠ 剧本 {want.get('duration')}s ±{tol}")
    if (out.get("width"), out.get("height")) != (want.get("width"), want.get("height")):
        bad.append(f"分辨率 {out.get('width')}×{out.get('height')} ≠ {want.get('width')}×{want.get('height')}")
    if out.get("fps") is None or abs(float(out["fps"]) - float(want.get("fps", 0))) > 0.01:
        bad.append(f"帧率 {out.get('fps')} ≠ {want.get('fps')}")
    return (not bad), "；".join(bad) or f"{out['duration']:.2f}s {out['width']}×{out['height']} {out['fps']}fps 合规"


def judge_g7(f: dict) -> tuple[bool, str]:
    bad = []
    if f.get("residue_before"):
        bad.append(f"清目录后仍有残留：{f['residue_before'][:3]}")
    a, b = f.get("first") or {}, f.get("second") or {}
    if not a.get("files"):
        bad.append("第一遍没有产物可比")
    elif a.get("sha") != b.get("sha"):
        fa, fb = a.get("files") or {}, b.get("files") or {}
        diff = sorted(set(fa) ^ set(fb)) + sorted(k for k in set(fa) & set(fb) if fa[k] != fb[k])
        bad.append(f"两遍结构不一致 {len(diff)} 处（例 {diff[:3]}）")
    if not f.get("second_g2_ok", False) and f.get("first_g2_ok", False):
        bad.append("第二遍 G2 没过（第一遍过了）→ 依赖上次残留")
    return (not bad), "；".join(bad) or f"两遍结构指纹一致 {a.get('sha')}（{len(a.get('files') or {})} 个文件）"


def judge_g8(f: dict) -> tuple[bool, str]:
    bad = []
    if f.get("owner_points"):
        bad.append(f"等项目方的点 {len(f['owner_points'])} 个（例 {f['owner_points'][0][:120]}）")
    if f.get("queue_status") != 200:
        bad.append(f"owner_queue 读不到（{f.get('queue_status')} {f.get('queue_err', '')}）→ 无法证明零人工")
    if not f.get("pipeline_complete"):
        bad.append("流水线没走到成片（G5 未过）→ 无法证明全程无人值守")
    return (not bad), "；".join(bad) or "owner_queue / sop_gate 零等项目方点位，全程 stdin 关闭跑完"


JUDGES = {"G1": judge_g1, "G2": judge_g2, "G3": judge_g3, "G4": judge_g4, "G5": judge_g5, "G6": judge_g6, "G7": judge_g7, "G8": judge_g8}


# ------------------------------------------------------------------ 采集
def collect_g1() -> dict:
    st, _d, err, tries = http_json_retry(f"http://127.0.0.1:8800/api/sop/status?run={RUN}")
    vst, _v, _e = http_json("http://127.0.0.1:8870/health", timeout=8)
    procs = {k: False for k in PROCS}
    rc, out = (sh(["powershell.exe", "-NoProfile", "-Command",
                   "Get-CimInstance Win32_Process | ForEach-Object { $_.CommandLine }"], 60) if os.name == "nt"
               else sh(["ps", "-eo", "args"], 30))
    for k, needle in PROCS.items():
        procs[k] = needle in out
    cfg_err = []
    for p in sorted((ROOT / "config").rglob("*")):
        if p.suffix not in (".json", ".yaml", ".yml") or not p.is_file() or "examples" in p.parts:
            continue
        try:
            if p.suffix == ".json":
                json.loads(p.read_text(encoding="utf-8-sig"))
            else:
                import yaml
                yaml.safe_load(p.read_text(encoding="utf-8"))
        except Exception as ex:  # noqa: BLE001  采集：读不了的配置记下来
            cfg_err.append(f"{rel(p)}: {type(ex).__name__}: {str(ex)[:80]}")
    code = ("import sys,importlib;sys.path[:0]=['.','packages/schema','services/render_router','services/agent','services/recipes',"
            "'services/post','services/api'];bad=[]\n"
            f"for m in {CONFIG_IMPORTS!r}:\n"
            "  try: importlib.import_module(m)\n"
            "  except Exception as e: bad.append(m+': '+type(e).__name__+': '+str(e)[:100])\n"
            "print('SMOKE_IMPORT_BAD', bad)")
    rc2, out2 = sh([py(), "-X", "utf8", "-c", code], 300)
    m = re.search(r"SMOKE_IMPORT_BAD (\[.*\])", out2)
    imp_err = eval(m.group(1)) if m else [f"import 探针没输出 rc={rc2}：{out2.strip()[-160:]}"]  # noqa: S307  自己打印的 list repr
    return {"api_status": st, "api_err": err, "api_attempts": tries, "api_timeout_s": API_TIMEOUT_S, "procs": procs, "vqa_8870": vst == 200, "vqa_status": vst,
            "config_errors": cfg_err, "import_errors": imp_err}


def _validate_blocks(md: Path) -> tuple[list[str], str]:
    rc, out = sh([py(), "-X", "utf8", str(ROOT / "tools/validate_qwen_script.py"), str(md), "--json"], 900)
    try:
        d = json.loads(out[out.index("{"):])
    except ValueError:
        return ["<validate 没有 JSON>"], out[-200:]
    blocks = sorted({i.get("rule_id") for e in d.get("episodes") or [] for i in e.get("issues") or [] if i.get("level") == "block"})
    return blocks, ""


def write_autoflow(rd: Path, md: Path, blocks: list[str], import_rc: int) -> None:
    """smoke_v2 没有写手链（不跑 LLM）：导入闸门 / 导入两段证据由冒烟脚本按真实结果写（decider=smoke_harness，sop_gate 照常读）"""
    sha = sha_file(md)
    gate_ok = not (set(blocks) - EXPECTED_VALIDATE_BLOCKS)
    d = {"schema": "nsfs.autoflow/1", "run": RUN, "episode": EP, "budget_usd": 0.0, "source": "eval/smoke.py",
         "stages": [{"id": "gate", "name": "导入闸门", "status": "ok" if gate_ok else "blocked", "decider": "smoke_harness",
                     "detail": f"validate block={blocks}（{sorted(EXPECTED_VALIDATE_BLOCKS)} 是 3 镜夹具的预期项）"},
                    {"id": "import", "name": "导入", "status": "imported" if import_rc == 0 else "import_failed",
                     "decider": "smoke_harness", "sha256": sha}]}
    (rd / f"autoflow_ep{EP:02d}.json").write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")


def collect_g2() -> dict:
    """导入 → 资产就绪 → 提示词（调现成函数 / CLI；只写 smoke_v2 自己的目录）"""
    RN, SG = runs_mod(), sop_gate_mod()
    rd = RN.run_dir(RUN, ROOT)
    md = rd / f"P4_ep{EP:02d}.md"
    f: dict = {}
    f["validate_blocks"], _ = _validate_blocks(md)
    out = RN.import_path(RUN, ROOT)
    out.parent.mkdir(parents=True, exist_ok=True)
    rc, txt = sh([py(), "-X", "utf8", str(ROOT / "tools/import_script.py"), "--script", str(md), "-o", str(out), "--no-timeline"], 900)
    f["import_rc"] = rc
    f["import_why"] = next((ln.strip() for ln in reversed(txt.splitlines()) if "拒绝" in ln or "Error" in ln), txt.strip()[-160:])
    write_autoflow(rd, md, f["validate_blocks"], rc)
    doc = jl(out, {}) or {}
    e = next((x for x in doc.get("episodes") or [] if int(x.get("number") or -1) == EP), {})
    f["shots"] = len(e.get("shots") or [])
    f["shot_seconds"] = [float(s.get("duration") or 0) for s in e.get("shots") or []]
    if rc != 0:
        f["assets_ready"], f["assets_why"] = False, "导入失败，没跑"
        return f
    rc3, txt3 = sh([py(), "-X", "utf8", str(ROOT / "tools/master/episode_ready.py"), "--run", RUN, "--episode", str(EP), "--json"], 900)
    try:
        res = json.loads(txt3[txt3.index("{"):])
    except ValueError:
        res = {"ready": False, "gaps": [{"what": f"episode_ready 没有 JSON rc={rc3}"}]}
    f["assets_ready"] = bool(res.get("ready")) and not res.get("gaps")
    f["asset_gaps"] = [f"{g.get('kind', '')}:{g.get('who', '')}:{g.get('what', '')}"[:160] for g in res.get("gaps") or []]
    f["assets_why"] = f"{len(f['asset_gaps'])} 个缺口（例 {f['asset_gaps'][:2]}）" if f["asset_gaps"] else ""
    if f["assets_ready"]:   # 全部就绪才记 _ready（无缺口 → 不生成资产作业，符合“避免资产作业”）
        if str(ROOT / "tools/pipeline") not in sys.path:
            sys.path.insert(0, str(ROOT / "tools/pipeline"))
        import asset_jobs as AJ
        AJ.generate(RUN, EP, root=ROOT, res=res)
        sh([py(), "-X", "utf8", str(ROOT / "tools/master/sop_gate.py"), "probe-prompts", "--run", RUN, "--episode", str(EP)], 1200)
    r = SG.check_prompts(ROOT, RUN, EP)                 # 本阶段：3 镜编译 + preflight 证据
    j = SG.judge(RUN, EP, "出图", root=ROOT)              # 剧本 → 导入闸门 → 资产就绪 → 提示词 全部有证据 = “走到提示词”
    f["prompts"] = {"ok": bool(r.get("ok")) and bool(j.get("ok")), "why": (r.get("why", "") + "；" + "；".join(j.get("missing") or []))[:300]}
    f["prompt_file"] = rel(ROOT / "data/pipeline/sop_gate" / RUN / f"ep{EP:02d}_prompts.json")
    return f


def collect_g3_compile() -> dict:
    env = runs_mod().run_env(RUN, ROOT)
    rc, out = sh([py(), "-X", "utf8", str(SMOKE / "refs_probe.py"), "--run", RUN, "--episode", str(EP)], 600, env=env)
    m = re.search(r"SMOKE_REFS (\{.*\})", out)
    return {"refs": json.loads(m.group(1)) if m else {}, "probe_rc": rc, "probe_tail": "" if m else out.strip()[-200:]}


def producer_log(root: Path = ROOT) -> list[dict] | None:
    """data/producer/runs/smoke_v2/log.jsonl 逐行 JSON；没有日志 → None"""
    log = root / "data/producer/runs" / RUN / "log.jsonl"
    if not log.is_file():
        return None
    out = []
    for ln in log.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            ev = json.loads(ln)
        except ValueError:
            continue
        if isinstance(ev, dict):
            out.append(ev)
    return out


def _obj_key(obj) -> str:
    """'smoke_v2/first:ep01-S1' / 'first:ep01-S1' → 'first:ep01-S1'"""
    return str(obj or "").split("/")[-1]


def _ev_in_window(ev: dict, t0: float | None) -> bool:
    if t0 is None:
        return True
    try:
        return float(ev.get("t")) >= t0 - T0_SLACK_S
    except (TypeError, ValueError):
        return False                       # 没有时间戳的事件不算本次窗口


def adopted_takes(events: list[dict] | None) -> set[tuple[str, int]]:
    """log.jsonl ev=adopt 的 (对象, 版本号)：这些版本是接手登记来的（W26b：会混进 V1 旧图），不算本次产物"""
    out = set()
    for ev in events or []:
        if ev.get("ev") == "adopt" and ev.get("take") is not None:
            try:
                out.add((_obj_key(ev.get("obj")), int(ev["take"])))
            except (TypeError, ValueError):
                continue
    return out


def _take_epoch(root: Path, take: dict) -> float | None:
    """版本时间：created_at（producer 本机时间，可带时区）→ epoch；读不了退文件 mtime"""
    ca = take.get("created_at")
    if ca:
        try:
            from datetime import datetime
            return datetime.fromisoformat(str(ca)).timestamp()
        except ValueError:
            pass
    fp = root / "data" / str(take.get("file") or "")
    return fp.stat().st_mtime if take.get("file") and fp.is_file() else None


def fresh_take_why(root: Path, take: dict, n_shot: int, adopted: set, t0: float | None) -> str:
    """评分表 G4：本次窗口（t0 之后）+ 文件在 data/renders/smoke_v2/ 下且存在 + 不是 adopt 来的
    （log ev=adopt 的版本排除、params.origin.adopted_by 排除）+ 首/尾帧要 take.producer.lane 非空。→ '' = 算数，否则 = 排除理由"""
    stage = take.get("stage")
    kind = STAGE_KIND.get(stage, stage)
    obj = f"{kind}:ep{EP:02d}-S{n_shot}"
    f = str(take.get("file") or "").replace("\\", "/")
    if f.startswith("data/"):
        f = f[5:]
    if not f.startswith(RENDERS_PREFIX):
        return f"文件不在 data/{RENDERS_PREFIX} 下（{f[:80]}）"
    if not (root / "data" / f).is_file():
        return f"文件不存在（{f[:80]}）"
    if take.get("bad"):
        return f"坏图（{str(take['bad'])[:60]}）"
    try:
        n = int(take.get("n"))
    except (TypeError, ValueError):
        n = None
    if (obj, n) in adopted:
        return "adopt 来的版本（log ev=adopt）"
    if ((take.get("params") or {}).get("origin") or {}).get("adopted_by"):
        return "adopt 来的版本（params.origin.adopted_by）"
    if stage in ("image", "last") and not ((take.get("producer") or {}).get("lane") if isinstance(take.get("producer"), dict) else None):
        return "不是 producer 出的（take.producer.lane 空）"
    if t0 is not None:
        ts = _take_epoch(root, take)
        if ts is None or ts < t0 - T0_SLACK_S:
            return "不是本次窗口出的（早于 t0）"
    return ""


def _shot_takes(root: Path, n: int) -> list[dict]:
    td = jl(root / "data/renders" / RUN / f"ep{EP:02d}" / f"S{n}" / "takes.json", {}) or {}
    return [t for t in td.get("takes") or [] if isinstance(t, dict)]


def take_ref_files(take: dict) -> list[str]:
    """本版本按名加载的参考文件（身份脸 / 设定图 / 参考板）：take.references ∪ take.refs ∪ asset_refs.slots[].file
    （take 上或 take.contract 里的 asset_refs）；去掉 “ (image vN)” 说明后缀，去重保序"""
    out: list[str] = []
    ar_list = [take.get("asset_refs"), (take.get("contract") or {}).get("asset_refs") if isinstance(take.get("contract"), dict) else None]
    cands = list(take.get("references") or []) + list(take.get("refs") or [])
    for ar in ar_list:
        if isinstance(ar, dict):
            cands += [s.get("file") for s in ar.get("slots") or [] if isinstance(s, dict)]
    for r in cands:
        if isinstance(r, str) and r.strip():
            r = REF_SUFFIX.sub("", r.strip()).replace("\\", "/")
            if r not in out:
                out.append(r)
    return out


def _ref_exists(root: Path, r: str) -> bool:
    return (root / r).is_file() or (root / "data" / r).is_file()


def render_refs(root: Path = ROOT, faces: dict | None = None, t0: float | None = None) -> dict | None:
    """评分表 G3 出图侧（W32，不靠 ComfyUI 文本日志）：每个对象（3 首帧 + 3 尾帧）要有本次窗口的 log ev=rendered，
    其 take 号在 takes.json 里是本次自己出的版本（fresh_take_why 为空），且该版本参考文件列表非空、文件全在、
    并含编译侧按名解析出的身份脸（faces[n] 给了才查；至少一张）。没有日志 → None。
    → {obj: {ok, take, lane, refs, missing, faces_hit, why}}"""
    events = producer_log(root)
    if events is None:
        return None
    adopted = adopted_takes(events)
    rendered: dict[str, list[tuple[int, str]]] = {}
    for ev in events:
        if ev.get("ev") == "rendered" and _ev_in_window(ev, t0):
            try:
                rendered.setdefault(_obj_key(ev.get("obj")), []).append((int(ev.get("take")), str(ev.get("lane") or "")))
            except (TypeError, ValueError):
                continue
    out = {}
    for n in (1, 2, 3):
        takes = _shot_takes(root, n)
        want_faces = [REF_SUFFIX.sub("", f).replace("\\", "/") for f in ((faces or {}).get(str(n)) or (faces or {}).get(n) or [])]
        for kind, stage in (("first", "image"), ("last", "last")):
            key = f"{kind}:ep{EP:02d}-S{n}"
            row = {"ok": False, "take": None, "lane": None, "refs": [], "missing": [], "faces_hit": [], "why": ""}
            hits = rendered.get(key) or []
            if not hits:
                row["why"] = "本次窗口没有 ev=rendered"
            for tn, lane in reversed(hits):          # 最近一次优先；任一版本合格即过
                t = next((x for x in takes if x.get("stage") == stage and x.get("n") == tn), None)
                if t is None:
                    row.update(take=tn, lane=lane, why=f"rendered v{tn} 在 takes.json 里找不到")
                    continue
                why = fresh_take_why(root, t, n, adopted, t0)
                refs = take_ref_files(t)
                miss = [r for r in refs if not _ref_exists(root, r)]
                fh = [f for f in want_faces if f in refs]
                if not why and not refs:
                    why = "参考文件列表为空（references / refs / asset_refs）"
                elif not why and miss:
                    why = f"参考文件不存在 {miss[:2]}"
                elif not why and want_faces and not fh:
                    why = f"没有按名加载身份脸（要 {want_faces[:2]}）"
                row = {"ok": not why, "take": tn, "lane": lane, "refs": refs, "missing": miss, "faces_hit": fh, "why": why}
                if row["ok"]:
                    break
            out[key] = row
    return out


def _takes_files(root: Path, n: int, stage: str, adopted: set | None = None, t0: float | None = None,
                 excluded: list | None = None) -> list[str]:
    out = []
    for t in _shot_takes(root, n):
        if t.get("stage") != stage or not t.get("file"):
            continue
        why = fresh_take_why(root, t, n, adopted or set(), t0)
        if why:
            if excluded is not None:
                excluded.append(f"S{n} {stage} v{t.get('n')}：{why}")
            continue
        p = root / "data" / str(t["file"]).replace("\\", "/").removeprefix("data/")
        out.append(rel(p) if root == ROOT else p.relative_to(root).as_posix())
    return out


def scan_g4_outputs(root: Path = ROOT, t0: float | None = None) -> dict:
    """评分表 G4：只数本次窗口（t0 之后）、data/renders/smoke_v2/ 下、非 adopt 的版本；视频 = takes.json stage=video
    同规则（不要求 producer.lane，视频是 VIDEO 工人出的）∪ data/pipeline/runs/smoke_v2/video/clips/ep01 下 mtime ≥ t0 的 mp4"""
    vid = root / "data/pipeline/runs" / RUN / "video/clips" / f"ep{EP:02d}"
    events = producer_log(root)
    adopted = adopted_takes(events)
    excluded: list[str] = []
    f = {"first": {}, "last": {}, "video": {}, "t0": t0}
    for n in (1, 2, 3):
        f["first"][str(n)] = _takes_files(root, n, "image", adopted, t0, excluded)
        f["last"][str(n)] = _takes_files(root, n, "last", adopted, t0, excluded)
        clips = []
        for p in sorted(vid.glob(f"ep{EP:02d}-S{n}__*.mp4")) if vid.is_dir() else []:
            if t0 is not None and p.stat().st_mtime < t0 - T0_SLACK_S:
                excluded.append(f"S{n} video {p.name}：不是本次窗口出的（早于 t0）")
            else:
                clips.append(p.name)
        f["video"][str(n)] = _takes_files(root, n, "video", adopted, t0, excluded) + clips
    f["excluded"] = excluded[:30]
    f["excluded_count"] = len(excluded)
    log = root / "data/producer/runs" / RUN / "log.jsonl"
    txt = log.read_text(encoding="utf-8", errors="replace") if log.is_file() else ""
    f["oom"] = [ln for ln in txt.splitlines() if OOM_RE.search(ln)][:5]
    f["timeouts"] = [ln for ln in txt.splitlines() if TIMEOUT_RE.search(ln) and '"ev": "rendered"' not in ln][:5]
    return f


def collect_g4(pre_ok: bool, pre_why: str) -> dict:
    t0 = time.time()                       # W32：G4 窗口起点；G3 出图侧 / G4 产物只认 t0 之后（facts["t0"] 带出）
    if not pre_ok:
        return {"skipped": f"前置没过（{pre_why}）", **scan_g4_outputs(t0=t0)}
    RN, SG = runs_mod(), sop_gate_mod()
    gate = SG.judge(RUN, EP, "出图", root=ROOT)
    if not gate.get("ok"):
        return {"skipped": f"sop_gate 出图闸门不放行：{'；'.join(gate.get('missing') or [])[:200]}", **scan_g4_outputs(t0=t0)}
    tmo = float(((preset().get("gate_timeout_s") or {}).get("G4")) or 1500)
    RN.set_status(RUN, "producing", by="eval/smoke.py（W26）", why="冒烟 G4 窗口：临时放行 producer", root=ROOT)
    try:
        rc, out = sh([py(), "-u", "-X", "utf8", str(ROOT / "tools/autopilot/producer.py"), "once", "--run", RUN, "--wait"], tmo)
    finally:
        RN.set_status(RUN, "paused", by="eval/smoke.py（W26）", why="冒烟 G4 窗口结束：翻回 paused（常驻进程不碰）", root=ROOT)
    f = {"rc": rc, "timeout_s": tmo, "tail": out.strip()[-300:], **scan_g4_outputs(t0=t0)}
    f["oom"] = f["oom"] + [ln for ln in out.splitlines() if OOM_RE.search(ln)][:3]
    return f


def collect_g5(pre_ok: bool, pre_why: str) -> dict:
    if not pre_ok:
        return {"skipped": f"前置没过（{pre_why}）"}
    od = ROOT / "data/episodes" / RUN
    od.mkdir(parents=True, exist_ok=True)
    rc, out = sh([py(), "-X", "utf8", str(ROOT / "tools/assemble_episode.py"), f"ep{EP:02d}", "--run", RUN, "--out", str(od),
                  "--no-asr", "--fake-tts", "--no-bgm", "--4k", "off", "--no-color-match"], 1800)
    mp4 = sorted(od.glob(f"ep{EP:02d}*.mp4"))
    tl = jl(od / f"ep{EP:02d}.timeline.json", {}) or {}
    ph = sum(1 for s in (tl.get("shots") or tl.get("sources") or []) if isinstance(s, dict) and
             (s.get("placeholder") or s.get("kind") == "placeholder"))
    return {"rc": rc, "tail": out.strip()[-300:], "mp4": rel(mp4[0]) if mp4 else None, "placeholders": ph}


def ffprobe_bin() -> str | None:
    base = Path(os.environ.get("LOCALAPPDATA", r"C:\Users\fredw\AppData\Local")) / "Microsoft/WinGet/Packages"
    for p in sorted(base.glob("Gyan.FFmpeg_*/ffmpeg-*/bin/ffprobe.exe")):
        return str(p)
    return shutil.which("ffprobe")


def ffprobe(path: Path) -> tuple[dict, str]:
    b = ffprobe_bin()
    if not b:
        return {}, "找不到 ffprobe"
    rc, out = sh([b, "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height,r_frame_rate:format=duration",
                  "-of", "json", str(path)], 120)
    try:
        d = json.loads(out[out.index("{"):])
        s = (d.get("streams") or [{}])[0]
        num, _, den = str(s.get("r_frame_rate", "0/1")).partition("/")
        return {"width": s.get("width"), "height": s.get("height"), "fps": round(float(num) / float(den or 1), 3),
                "duration": float((d.get("format") or {}).get("duration"))}, ""
    except (ValueError, TypeError, ZeroDivisionError):
        return {}, out.strip()[-200:]


def collect_g6(g5: dict, shot_seconds: list[float]) -> dict:
    if not g5.get("mp4"):
        return {"skipped": "G5 没有 mp4"}
    o = preset().get("output") or {}
    want = {"duration": round(sum(shot_seconds), 3), "width": o.get("width", 1080), "height": o.get("height", 1920),
            "fps": o.get("fps", 24), "duration_tol_s": o.get("duration_tol_s", 2.0)}
    pr, err = ffprobe(ROOT / g5["mp4"])
    return {"want": want, "probe": pr, "err": err, "ffprobe": ffprobe_bin()}


def owner_points(root: Path = ROOT) -> tuple[list[str], int, str]:
    """等项目方的点：sop_gate 阶段视图 pending_owner + owner_queue 里 smoke_v2 的条目 + autoflow awaiting_owner"""
    pts = []
    try:
        v = sop_gate_mod().stage_view(RUN, root)
        for e in v.get("episodes") or []:
            if e.get("pending_owner"):
                pts.append(f"sop_gate ep{e.get('episode')} pending_owner={e.get('pending_owner')}")
    except Exception as ex:  # noqa: BLE001
        pts.append(f"sop_gate stage_view 出错：{type(ex).__name__}: {ex}"[:160])
    st, d, err, tries = http_json_retry(f"http://127.0.0.1:8800/api/owner/queue?run={RUN}")
    if st != 200:
        err = f"{err}（试 {tries} 次 × {API_TIMEOUT_S:.0f}s）"
    if st == 200:
        items = d.get("items") if isinstance(d, dict) else d
        for it in items or []:
            if RUN in json.dumps(it, ensure_ascii=False):
                pts.append(f"owner_queue {str(it.get('id') if isinstance(it, dict) else it)[:100]}")
    af = jl(root / "data/pipeline/runs" / RUN / f"autoflow_ep{EP:02d}.json", {}) or {}
    for s in af.get("stages") or []:
        if s.get("decider") == "owner" or str(s.get("status", "")).startswith("awaiting_owner"):
            pts.append(f"autoflow {s.get('id')} {s.get('status')}")
    return pts, st, err


# ------------------------------------------------------------------ 主流程
def gate(rec: list, gid: str, facts: dict, t0: float) -> bool:
    ok, why = JUDGES[gid](facts)
    rec.append({"id": gid, "name": GATE_NAME[gid], "ok": ok, "evidence": {"why": why, **facts}, "secs": round(time.time() - t0, 1)})
    return ok


def code_sha() -> str:
    rc, out = sh(["git", "rev-parse", "--short", "HEAD"], 30)
    return out.strip() if rc == 0 else "unknown"


def run_all(stamp: str) -> dict:
    t_all = time.time()
    rec: list[dict] = []
    notes = ["preset.json 的 image / video 低参数未生效：现有 preset 机制没有按剧覆盖入口（只有全局 config/render_quality.json + 驳回 rung.preset），"
             "冒烟不改渲染代码 / 全局配置", "owner_override.json 未生效：owner_delegate / final_tier 只读主配置，没有按剧覆盖入口"]
    # G1
    t = time.time()
    g1 = gate(rec, "G1", collect_g1(), t)
    # G2（每次先隔离清空 smoke_v2 → 模板）
    t = time.time()
    moved = quarantine_smoke(ROOT, stamp + "-a")
    residue = [d for d in SMOKE_DIRS if (ROOT / d).exists()]
    seeded = seed_from_template(ROOT)
    f2 = {**collect_g2(), "quarantined": moved, "seeded": len(seeded)}
    g2 = gate(rec, "G2", f2, t)
    fp1 = tree_fingerprint(ROOT, STRUCT_DIRS)
    # G3（编译侧）→ G4 → G3（出图侧关键字）
    t3 = time.time()
    f3 = collect_g3_compile()
    s3 = time.time() - t3
    t = time.time()
    f4 = collect_g4(g2, "G2 没过" if not g2 else "")
    rec_g4_secs = time.time() - t
    f3["render_refs"] = render_refs(faces={n: (r or {}).get("face_files") or [] for n, r in (f3.get("refs") or {}).items()},
                                    t0=f4.get("t0"))
    t3b = time.time()
    gate(rec, "G3", f3, t3b - s3)
    g4 = gate(rec, "G4", f4, time.time() - rec_g4_secs)
    t = time.time()
    f5 = collect_g5(g4, "G4 没过" if not g4 else "")
    g5 = gate(rec, "G5", f5, t)
    t = time.time()
    gate(rec, "G6", collect_g6(f5, f2.get("shot_seconds") or []), t)
    # G7：同输入第二遍（只跑 G2 结构，不重出图）
    t = time.time()
    moved2 = quarantine_smoke(ROOT, stamp + "-b")
    residue2 = [d for d in SMOKE_DIRS if (ROOT / d).exists()]
    seed_from_template(ROOT)
    f2b = collect_g2()
    fp2 = tree_fingerprint(ROOT, STRUCT_DIRS)
    gate(rec, "G7", {"residue_before": residue + residue2, "first": fp1, "second": fp2, "first_g2_ok": g2,
                     "second_g2_ok": judge_g2(f2b)[0], "quarantined_second": moved2}, t)
    # G8
    t = time.time()
    pts, qst, qerr = owner_points()
    gate(rec, "G8", {"owner_points": pts, "queue_status": qst, "queue_err": qerr, "pipeline_complete": g5,
                     "stdin": "DEVNULL（全部子进程）"}, t)
    rec.sort(key=lambda r: GATES.index(r["id"]))
    passed = sum(1 for r in rec if r["ok"])
    return {"schema": SCHEMA, "run_id": RUN, "stamp": stamp, "code_sha": code_sha(), "gates": rec, "passed": passed,
            "score": round(passed / len(GATES), 4), "score_text": f"{passed}/{len(GATES)}", "total_secs": round(time.time() - t_all, 1),
            "notes": notes}


def validate_result(d: dict) -> list[str]:
    """nsfs.smoke/1 结构校验（测试与写盘前都用）"""
    bad = []
    for k in ("schema", "gates", "score", "total_secs", "run_id", "code_sha", "notes"):
        if k not in d:
            bad.append(f"缺 {k}")
    if d.get("schema") != SCHEMA:
        bad.append("schema 不对")
    ids = [g.get("id") for g in d.get("gates") or []]
    if ids != GATES:
        bad.append(f"gates 顺序 / 个数不对：{ids}")
    for g in d.get("gates") or []:
        if not isinstance(g.get("ok"), bool) or not isinstance(g.get("secs"), (int, float)) or "evidence" not in g:
            bad.append(f"{g.get('id')} 字段不全")
    n = sum(1 for g in d.get("gates") or [] if g.get("ok") is True)
    if abs(float(d.get("score", -1)) - n / 8) > 1e-6:
        bad.append("score ≠ 通过门数 / 8")
    return bad


def table(d: dict) -> str:
    lines = ["门  | 结果 | 耗时(s) | 证据", "----|------|---------|-----"]
    for g in d["gates"]:
        lines.append(f"{g['id']} {g.get('name', '')} | {'通过' if g['ok'] else '失败'} | {g['secs']:>7.1f} | {g['evidence'].get('why', '')[:220]}")
    lines.append(f"分数 {d['score_text'] if 'score_text' in d else d['score']}  总耗时 {d['total_secs']}s  run={d['run_id']}  code={d['code_sha']}")
    return "\n".join(lines)


def write_result(d: dict, out_dir: Path = EVAL / "results") -> Path:
    bad = validate_result(d)
    if bad:
        raise ValueError("结果不合 nsfs.smoke/1：" + "；".join(bad))
    out_dir.mkdir(parents=True, exist_ok=True)
    p = out_dir / f"{d['stamp']}.json"
    p.write_text(json.dumps(d, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    return p


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["run"])
    ap.parse_args(argv)
    stamp = time.strftime("%Y%m%d-%H%M")
    d = run_all(stamp)
    p = write_result(d)
    print(table(d))
    print(f"结果 → {rel(p)}")
    return sum(1 for g in d["gates"] if not g["ok"])


if __name__ == "__main__":
    sys.exit(main())
