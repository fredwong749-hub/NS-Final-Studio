import os

# 测试里不在后台重建 data/state_timeline.json（需要时由测试自己打开）
os.environ.setdefault("NS_TIMELINE_AUTOBUILD", "0")
# 总调度 11-02 19:1x（K-OPS-F24）：测试不许依赖“真实当前剧”（primary 会切换：19:0x 切到还没剧本的 series10_v2，6 个测试一起红）。
# 读真实仓库数据的测试一律钉到已冻结的 V1 真实数据；临时目录里的测试照读自己的 runs.json（runs.primary_run 只对真实仓库生效）
os.environ.setdefault("NS_PRIMARY_RUN", "series10_v1")
# OVERSIGHT-F 第 14 轮 P2（总调度 11-02）：派人请求（judge_request / review_request，autoflow_agent._inbox_write）一律写到临时目录，
# 任何测试都不会写进真实 data/master/inbox/（data/master 在 real-data-guard 的 data/ 监视范围内，写了当场报错）
import tempfile as _tempfile  # noqa: E402
os.environ.setdefault("NSFS_INBOX_DIR", _tempfile.mkdtemp(prefix="nsfs_inbox_"))


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _no_live_gpu3_bridge(monkeypatch):
    """测试一律不碰真实的 gpu3 桥（隧道 127.0.0.1:15180 可能开着）：默认按“不可达”处理，需要的测试自己换假桥"""
    try:
        from ns_api import gpu3_bridge as GB
    except Exception:  # noqa: BLE001
        return

    def _down(*a, **k):
        raise GB.BridgeError("gpu3 桥在测试里不可达（tests/conftest.py）")
    monkeypatch.setattr(GB, "_call", _down)


@pytest.fixture(autouse=True)
def _no_remote_index_writes(monkeypatch):
    """fredw-92/F1：测试里 ComfyClient.download 记 gpu3 输出名只记在内存，不写 data/cache/comfy_remote_outputs.json"""
    try:
        from ns_render import comfy_client as CC
    except Exception:  # noqa: BLE001
        return
    monkeypatch.setattr(CC, "remote_index", CC.RemoteIndex(None))


@pytest.fixture(autouse=True)
def _auto_final_off_by_default(monkeypatch):
    """fredw-92/VB：config/render_quality.json 的 auto_final_on_lock 由项目方 2026-10-31 改成 true（生产设置），
    测试按契约默认值 false 跑；显式传 path 的调用仍读那个文件（测这个开关本身时用）。"""
    from ns_render import final_tier as FT
    orig = FT.auto_final_on_lock
    monkeypatch.setattr(FT, "auto_final_on_lock", lambda path=None, run=None: orig(path, run) if path is not None else False)


@pytest.fixture(autouse=True)
def _image_check_off_by_default(monkeypatch):
    """fredw-92/UXF1：假 ComfyUI 出的都是 64×112 小图——坏图检查（ns_render.image_check）测试里默认关，
    测这条规则的测试自己打开（tests/test_bad_image_uxf1.py）"""
    try:
        from ns_render import image_check as IC
    except Exception:  # noqa: BLE001
        return
    monkeypatch.setattr(IC, "ENABLED", False)


@pytest.fixture(autouse=True)
def _drain_jobs_before_unpatch(monkeypatch):
    """fredw-92/UXF1：根因修复——测试结束时后台任务线程还在跑，monkeypatch 先撤掉了 P.DATA，任务就把假 ComfyUI 的
    64×112 测试图写进了真数据目录（2026-10-31 03:02 ep02-S1 首帧 #5）。这个夹具依赖 monkeypatch，所以收尾时
    先于 monkeypatch 撤销执行：排队的任务取消、正在跑的等它跑完。"""
    yield
    import sys
    J = sys.modules.get("ns_api.jobs")
    if J is not None and hasattr(J, "drain"):
        left = J.drain(timeout_s=60.0)
        assert not left, f"测试结束 60 s 后仍有任务在跑：{left}"


@pytest.fixture(autouse=True)
def _no_live_train_lock_ssh(monkeypatch):
    """fredw-92/G36：测试不经 ssh 去 gpu33 / gpu36 读训练锁（按无锁）；需要的测试自己换 train_lock_fn"""
    try:
        from ns_api import jobs as J
    except Exception:  # noqa: BLE001
        return
    monkeypatch.setattr(J, "train_lock_fn", lambda server: set())
    monkeypatch.setattr(J, "_train_cache", {})


# ---------------------------------------------------------------- fredw-92/UXF4：任务记录永远不写真实 data/
# 根因（2026-10-31 03:52–04:16 顶栏“失败 9”）：tests/test_bad_image_uxf1.py::test_drain_cancels_queued 没换 P.DATA 就
# J.submit("frame", "ep02-S1", 0, …)——submit 立即 persist 到真实 data/jobs/v1（params={}、queued），drain 取消只改内存；
# API 下次启动 restore() 把这些 queued 记录标成“API 重启中断”。每跑一次全量测试多一条。
# 修法：P.DATA 还是真实数据目录时，jobs 的持久化目录与整集出片的落盘目录一律指到 tmp_path（测试自己换了 P.DATA 的照旧跟着它走）。

def _real_data_dir():
    from ns_render import pipeline as P
    return P.ROOT / "data"


@pytest.fixture(autouse=True)
def _jobs_persist_isolated(tmp_path, monkeypatch):
    try:
        from ns_api import jobs as J
        from ns_render import pipeline as P
    except Exception:  # noqa: BLE001
        return
    real = _real_data_dir().resolve()
    safe = tmp_path / "_isolated_data"

    def base():
        d = P.DATA
        try:
            return safe if d.resolve() == real else d
        except OSError:
            return safe

    monkeypatch.setattr(J, "jobs_dir", lambda: base() / "jobs" / "v1")
    try:
        from ns_api import episode_produce as EPR
        monkeypatch.setattr(EPR.Producer, "dir", lambda self: self._root or (base() / "jobs" / "episodes"))
    except Exception:  # noqa: BLE001
        pass


@pytest.fixture(autouse=True, scope="session")
def _no_test_jobs_in_real_data():
    """跑完全部测试：本进程里提交过的任务（J._jobs）一个都不能出现在真实 data/jobs/v1，整集出片也不能写真实 data/jobs/episodes。
    （API 正在跑的真实任务由 API 进程写，不在本进程的 _jobs 里，不会误报。）"""
    real = _real_data_dir()
    ep_dir = real / "jobs" / "episodes"
    before = {p.name: p.stat().st_mtime for p in ep_dir.glob("*.json")} if ep_dir.is_dir() else {}
    yield
    import sys
    J = sys.modules.get("ns_api.jobs")
    leaked = []
    if J is not None:
        leaked = [jid for jid in list(getattr(J, "_jobs", {})) if (real / "jobs" / "v1" / f"{jid}.json").exists()]
    EPR = sys.modules.get("ns_api.episode_produce")
    if EPR is not None and ep_dir.is_dir():
        pr = getattr(EPR, "PRODUCER", None)
        for p in ep_dir.glob("*.json"):
            if p.name not in before and pr is not None and any(r.get("id") and p.stem == f"ep{int(n):02d}"
                                                                 for n, r in pr.runs.items()):
                leaked.append(str(p))
    assert not leaked, f"测试把任务记录写进了真实 data/jobs：{leaked}"


@pytest.fixture(autouse=True)
def _login_as_owner(request, monkeypatch, tmp_path_factory):
    """UIRSI 账户登录（2026-10-31）：项目方闸门改为从登录会话取身份。整个 app 的测试默认以“登录的项目方”身份请求
    （以前靠请求体 by=owner + 原话）；审计日志写到临时目录，不进真实 data/audit。
    测“未登录 / 非项目方”的用例：标 @pytest.mark.anon，或在 test_auth_uirsi 里用自己的临时项目根。"""
    try:
        from ns_api import auth as A
    except Exception:  # noqa: BLE001
        return
    if request.module.__name__.endswith("test_auth_uirsi"):
        return
    d = tmp_path_factory.mktemp("audit")
    monkeypatch.setattr(A, "_audit_dir", lambda: d)
    if "anon" in request.keywords:
        return
    monkeypatch.setattr(A, "user_of", lambda req: {"name": "测试项目方", "role": "owner"})


def pytest_configure(config):
    config.addinivalue_line("markers", "anon: 这个用例以“未登录”身份请求（不套用默认的项目方登录会话）")
    config.addinivalue_line("markers", "real_clip: 这个用例要加载真 CLIP（默认换成假向量，见 _fake_clip）")
    config.addinivalue_line("markers", "real_data: 这个用例确实要读写真实 data/（只放行这一个用例；ITERAUDIT K-OPS-Q03）")


# ---------------------------------------------------------------- ITERAUDIT 11-01：真实数据写保护（规则 K-OPS-Q03）
# 根因（11-01 03:15）：tests/test_unified_frame.py 的后台 postflight 线程活过了夹具，monkeypatch 已把 P.RENDERS 还原成真实路径，
# 线程把测试数据写进了真实 data/renders/ep01/S1/takes.json。三层防护：
#   ① 会话期间 P.DATA / P.RENDERS 等数据根默认指向临时目录（monkeypatch 还原也只还原到临时目录）；
#   ② tools/qa/real_data_guard.py：本进程任何线程写真实 <仓库>/data 一律抛错并记账（吞掉异常也会在会话结束报出）；
#   ③ 会话结束：测试起的非守护线程不得还活着；几份真实文件（takes.json 等）的 mtime 不得变。
# 确实要读写真实数据的用例：标 @pytest.mark.real_data（只放行这一个用例）。
import sys as _sys  # noqa: E402
import threading as _threading  # noqa: E402
from pathlib import Path as _Path  # noqa: E402

_sys.path.insert(0, str(_Path(__file__).resolve().parents[1] / "tools" / "qa"))
import real_data_guard as _RDG  # noqa: E402

_GUARD_START: dict = {}
# 数据根：(模块, 属性, 相对临时根的子路径)
_SANDBOX_ROOTS = [("ns_render.pipeline", "DATA", ""), ("ns_render.pipeline", "RENDERS", "renders"),
                  ("ns_api.live", "DATA", ""), ("ns_api.script_inbox", "DATA", ""),
                  ("ns_post.assemble", "DATA", ""), ("ns_post.colormatch", "DATA", ""),
                  ("ns_post.tts", "CACHE_DIR", "cache/tts"), ("ns_render.refs", "CACHE", "cache/refs"),
                  ("ns_agent.comfy_tag", "HEARTBEAT_DIR", "gpu_heartbeats"),
                  ("ns_agent.asset_refs", "DERIVED_OUT", "derived")]   # 编译时新生成的 refboards / refcrops 写沙盒（总调度 11-03）


_GUARD_OFF = os.environ.get("NS_REAL_DATA_GUARD") == "off"   # 只用于排查“没有守卫时是否也失败”；报告记 ok=false，iter_gate T1 不认


def pytest_sessionstart(session):
    _GUARD_START["threads"] = {t.ident for t in _threading.enumerate()}
    _GUARD_START["sentinels"] = _RDG.sentinels()
    if not _GUARD_OFF:
        _RDG.install()


@pytest.fixture(autouse=True, scope="session")
def _data_sandbox(tmp_path_factory):
    import importlib
    if not _GUARD_START:          # pytest_sessionstart 没跑到（只收集了子目录）时兜底
        pytest_sessionstart(None)
    # 沙盒放在仓库里（不在 data/ 下）：不少代码对数据路径做 relative_to(ROOT)，放系统临时目录会抛 ValueError
    import shutil as _shutil
    root = _Path(__file__).resolve().parents[1] / ".pytest_sandbox" / f"{os.getpid()}"
    _shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True, exist_ok=True)
    if _GUARD_OFF:
        yield root
        return
    mp = pytest.MonkeyPatch()
    real = {}
    for mod, attr, sub in _SANDBOX_ROOTS:
        try:
            m = importlib.import_module(mod)
        except Exception:  # noqa: BLE001
            continue
        if hasattr(m, attr):
            real[(mod, attr)] = getattr(m, attr)
            d = root / sub if sub else root
            d.mkdir(parents=True, exist_ok=True)
            mp.setattr(m, attr, d)
    _GUARD_START["real_roots"] = real
    yield root
    mp.undo()
    _shutil.rmtree(root, ignore_errors=True)


@pytest.fixture(autouse=True)
def _real_data_optin(request, monkeypatch):
    """@pytest.mark.real_data：这个用例用真实数据根，且放行写保护（只在用例期间）"""
    if "real_data" not in request.keywords:
        yield
        return
    import importlib
    for (mod, attr), v in _GUARD_START.get("real_roots", {}).items():
        monkeypatch.setattr(importlib.import_module(mod), attr, v)
    with _RDG.allow():
        yield


def pytest_sessionfinish(session, exitstatus):
    import json
    import time
    deadline = time.time() + 10
    leftover = []
    for t in _threading.enumerate():
        if t.ident in _GUARD_START.get("threads", set()) or t is _threading.current_thread() or t.daemon:
            continue
        t.join(max(0.1, deadline - time.time()))
        if t.is_alive():
            leftover.append(t.name)
    _RDG.uninstall()
    now = _RDG.sentinels()
    changed = [p for p, m in _GUARD_START.get("sentinels", {}).items() if now.get(p) != m]
    viol = [{k: v for k, v in x.items() if k != "stack"} for x in _RDG.VIOLATIONS]
    rep = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "violations": viol, "leftover_threads": leftover,
           "sentinels_changed": changed, "guard_off": _GUARD_OFF,
           "ok": not (viol or leftover or changed or _GUARD_OFF)}
    try:
        out = _Path(__file__).resolve().parents[1] / "data" / "qa" / "test_guard_last.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError:
        pass
    tr = session.config.pluginmanager.get_plugin("terminalreporter")
    w = (tr.write_line if tr else print)
    w(f"[real-data-guard] 写真实数据 {len(viol)} 次；遗留非守护线程 {len(leftover)}；真实哨兵文件被改 {len(changed)}")
    for x in viol[:30]:
        w(f"[real-data-guard]   {x['op']} {x['path']} ← {x['test']}（线程 {x['thread']}）")
    for n in leftover:
        w(f"[real-data-guard]   遗留线程 {n}")
    for p in changed:
        w(f"[real-data-guard]   哨兵被改 {p}")
    if not rep["ok"]:
        session.exitstatus = 1


# ---------------------------------------------------------------- REFLOCK 11-01：出图后契约在测试里不连机器、不留线程
# 根因（ITERAUDIT 守卫抓到）：frame_edit.regen → unified_frame.postflight_async 起后台线程 → _postflight → remote_score.postflight_full
# 真的 ssh 到 gpu33 打分，并在用例结束后写 data/cache/reflock_remote_refs_gpu33.json（与 03:15 事故同型）。修法：
#   ① remote_score.ssh 在测试里一律抛错（没有任何用例能连机器；要测协议的用例自己换假 ssh，见 test_imgperf_lanes）；
#   ② unified_frame._postflight 默认返回“测试跳过”（ok=None，不算通过）；要测它的用例自己换；
#   ③ unified_frame._spawn 同步执行：postflight 在用例内跑完，线程不会活过用例。
@pytest.fixture(autouse=True)
def _no_remote_scoring(monkeypatch):
    p = str(_Path(__file__).resolve().parents[1] / "tools" / "gen_contract")
    if p not in _sys.path:
        _sys.path.insert(0, p)
    try:
        import remote_score as RS
    except Exception:  # noqa: BLE001
        RS = None
    if RS is not None:
        def _no_ssh(host, *a, **k):
            raise RuntimeError(f"测试里不许 ssh 到 {host}（tests/conftest.py _no_remote_scoring）")
        monkeypatch.setattr(RS, "ssh", _no_ssh)
    try:
        from ns_render import unified_frame as UF
    except Exception:  # noqa: BLE001
        return
    monkeypatch.setattr(UF, "_postflight", lambda final_rel, job, host: {"ok": None, "skipped": "test", "items": []})
    monkeypatch.setattr(UF, "_spawn", lambda fn, args, name: fn(*args))


@pytest.fixture(autouse=True)
def _fake_clip(request, monkeypatch):
    """测试不加载真 CLIP ViT-L（笔记本 CPU 上首载 + 滑窗要几十秒，EDITDEL 的 30 s 等待会超时）：embed / embed_text 换成
    按像素均值确定的小向量（可复现、快）。要真 CLIP 的用例标 @pytest.mark.real_clip。"""
    if "real_clip" in request.keywords:
        return
    try:
        import numpy as np
        from ns_agent.gen_contract import metrics as M
    except Exception:  # noqa: BLE001
        return

    def _vec(seed_vals):
        v = np.asarray(seed_vals, dtype=np.float32)
        v = np.concatenate([v, np.ones(768 - len(v), np.float32) * 0.1])
        return v / np.linalg.norm(v)

    def embed(images):
        out = []
        for im in images:
            a = np.asarray(im.convert("RGB").resize((4, 4)), dtype=np.float32).reshape(-1) / 255.0
            out.append(_vec(a))
        return np.stack(out) if out else np.zeros((0, 768), np.float32)

    def embed_text(texts):
        return np.stack([_vec([(hash(t) % 97) / 97.0] * 8) for t in texts]) if texts else np.zeros((0, 768), np.float32)
    def probe(img, texts):
        n = len(texts)
        return [round(1.0 / n, 4)] * n
    monkeypatch.setattr(M, "embed", embed)
    monkeypatch.setattr(M, "embed_text", embed_text)
    monkeypatch.setattr(M, "probe", probe)
    monkeypatch.setattr(M, "_clip", lambda: (_ for _ in ()).throw(RuntimeError("测试里不加载真 CLIP（标 real_clip）")))


# ---------------------------------------------------------------- ITERAUDIT 11-01：tools/ 同名脚本歧义守卫（K-OPS-Q11）
import script_name_guard as _SNG  # noqa: E402

_SNG.install()


@pytest.fixture(autouse=True)
def _ambiguous_script_cache_fresh():
    """每个用例前：缓存里若是“另一个 run.py”，先清掉，让 import 按当前 sys.path 重新解析"""
    _SNG.evict_stale()
    yield


# ---------------------------------------------------------------- ITERAUDIT 11-01：模块级任务登记表按用例隔离
# 根因：ns_api.cuts.JOBS（整集合成任务表，进程级 dict）在 tests/test_cuts_ux5.py 里留下第 2 集一个“running”的假进程
# （FakeProc.returncode=None，fixture 只在开头 clear、收尾不清）；之后 tests/test_editdel.py::test_trash_cut_candidate_and_edit_version
# 删 ep02 成片时 trash._impact_cut 判“第 2 集正在合成” → 409 → KeyError 'files'。只在全量顺序下出现。
# 修法：每个用例换一张新的空任务表，结束自动还原（产品代码按模块属性取 JOBS，不受影响）。
_PER_TEST_REGISTRIES = [("ns_api.cuts", "JOBS")]


@pytest.fixture(autouse=True)
def _fresh_module_registries(monkeypatch):
    for mod, attr in _PER_TEST_REGISTRIES:
        m = _sys.modules.get(mod)
        if m is None:
            try:
                import importlib
                m = importlib.import_module(mod)
            except Exception:  # noqa: BLE001
                continue
        if isinstance(getattr(m, attr, None), dict):
            monkeypatch.setattr(m, attr, {})
    yield
