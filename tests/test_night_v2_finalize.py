"""W16 · NIGHT-FIX（REVIEW-G4b cut B P0-1）：night.py 对资产包剧（NS_RUN=series10_v2）的 finalize 能走到合成。
① tts_missing() 按剧取音色表（tts_preflight(run=RUN_ID)），不再因 VoiceRunRequired 每集 hold_tts；
② finalize 起 tools/assemble_episode.py 时带 --run，合成器按剧解析导入稿 / 音色 / 配乐，不再被 guard 退出 2；
③ assemble_episode 不给 --run 时对资产包剧照旧拒绝（旧口径不变），给 --run 但没 --sources-from 也拒绝（不按 V1 data/renders 找片）。
全部写入都在 tmp_path（night 的 VID / LOG / EPS_OUT 指到临时 run 目录），不写真实 data/。"""
from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in ("services/post", "services/agent", "tools", "tools/series10_video", ""):
    if str(ROOT / p) not in sys.path:
        sys.path.insert(0, str(ROOT / p))

V2, V1 = "series10_v2", "series10_v1"


@pytest.fixture
def night_v2(monkeypatch, tmp_path):
    import os
    orig = os.environ.get("NS_RUN")          # night 导入时会写 NS_RUN；收尾还原原值再重载，不影响后面的用例
    import night as N
    os.environ["NS_RUN"] = V2
    N = importlib.reload(N)
    vid = tmp_path / "run" / V2 / "video"
    vid.mkdir(parents=True)
    monkeypatch.setattr(N, "VID", vid)
    monkeypatch.setattr(N, "LOG", vid / "night.log")
    monkeypatch.setattr(N, "EPS_OUT", tmp_path / "episodes" / V2)
    try:
        yield N
    finally:
        monkeypatch.undo()
        if orig is None:
            os.environ.pop("NS_RUN", None)
        else:
            os.environ["NS_RUN"] = orig
        importlib.reload(N)


def test_tts_missing_passes_run(night_v2, monkeypatch):
    N = night_v2
    assert N.RUN_ID == V2 and not N.LEGACY
    import ns_post.tts as T
    seen = {}

    def fake(cfg=None, *, speakers=None, root=None, run=None):
        seen["run"] = run
        return []
    monkeypatch.setattr(T, "tts_preflight", fake)
    assert N.tts_missing() is None and seen["run"] == V2


def test_tts_missing_v2_real_voice_table_not_run_required(night_v2):
    why = night_v2.tts_missing() or ""
    assert "音色表读不了" not in why and "资产包模式" not in why     # 修前：VoiceRunRequired → 每集 hold_tts


def _assemble(argv, monkeypatch):
    import assemble_episode as AE
    monkeypatch.setattr(sys, "argv", ["assemble_episode.py", *argv])
    return AE.main()


def test_assemble_episode_refuses_v2_without_run(monkeypatch):
    import ns_post.tts as T
    monkeypatch.setattr(T, "_current_run", lambda: V2)
    assert _assemble(["ep01", "--lines-only"], monkeypatch) == 2          # 旧口径不变


def test_assemble_episode_run_requires_sources(monkeypatch, capsys):
    assert _assemble(["ep01", "--run", V2, "--lines-only"], monkeypatch) == 2
    assert "--sources-from" in capsys.readouterr().err


def test_assemble_episode_resolves_inputs_by_run(monkeypatch, tmp_path):
    import assemble_episode as AE
    from tools.autopilot import runs as RUNS
    tl = tmp_path / "tl.json"
    tl.write_text('{"shots": []}', encoding="utf-8")
    a = AE.argparse.Namespace(sources_from=str(tl), script=None, music_dir=None, no_bgm=False)
    assert AE.resolve_run_inputs(V2, a) is None
    assert Path(a.script) == RUNS.script_path(V2, ROOT) != ROOT / "data/import/script_v2.json"
    assert Path(a.music_dir) == ROOT / "data" / "music" / V2
    a1 = AE.argparse.Namespace(sources_from=None, script=None, music_dir=None, no_bgm=False)
    assert AE.resolve_run_inputs(V1, a1) is None and Path(a1.script) == ROOT / "data/import/script_v2.json"
    assert a1.music_dir is None                                            # V1 照旧（Settings 默认）


def test_finalize_v2_reaches_assembly(night_v2, monkeypatch, tmp_path):
    """修前：status = hold_tts（tts_missing）或 assemble_failed（assemble_episode 退出 2）；修后：进入合成并产出成片"""
    N = night_v2
    import ns_post.tts as T
    monkeypatch.setattr(T, "tts_preflight", lambda cfg=None, *, speakers=None, root=None, run=None:
                        [] if run == V2 else ["音色表读不了：没传 run"])
    monkeypatch.setattr(N, "voices_ok", lambda: True)
    monkeypatch.setattr(N, "ssh", lambda host, cmd, timeout=600: "")
    monkeypatch.setattr(N, "bgm_after_assembly", lambda *a, **k: {})
    # W46：finalize 加了整集硬规矩（假 mp4 读不了时长）与复盘接力（tests/test_w46_finalize.py 单测），这里只测合成路径
    monkeypatch.setattr(N, "episode_hard_rules", lambda p, probe=None: {"ok": True, "fails": []})
    monkeypatch.setattr(N, "retro_after_assembly", lambda ep: {"episode": ep})
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"\0")
    ep_dir = N.VID / "episodes" / "ep01"
    ep_dir.mkdir(parents=True)
    (ep_dir / "manifest.json").write_text(json.dumps({"shots": [{"index": 1, "shot": "ep01-S1", "proxy": "p.mp4"}]}),
                                          encoding="utf-8")
    monkeypatch.setattr(N, "assembly_sources", lambda man: ({"shots": [
        {"index": 1, "kind": "video", "file": str(clip), "origin": "test"}]}, []))
    calls = []

    def fake_run(args, timeout=3600):
        calls.append(args)
        tool = args[1].replace("\\", "/")
        if tool == "tools/assemble_episode.py":
            rc = _assemble([*args[2:], "--lines-only"], monkeypatch)   # 真跑合成器的参数解析 + 按剧取输入（只列台词，不出片）
            if rc == 0:
                ver = args[args.index("--variant") + 1]
                out = Path(args[args.index("--out") + 1])
                out.mkdir(parents=True, exist_ok=True)
                (out / f"ep01_x_{ver}.mp4").write_bytes(b"\0")
            return rc, ""
        if tool == "tools/director/finish.py":
            return 0, "{}"
        return 0, ""
    monkeypatch.setattr(N, "run", fake_run)
    st = {"eps": {"1": {}}}
    N.finalize(1, "gpu36", st, {"bgm": "off"})
    x = st["eps"]["1"]
    asm = [c for c in calls if c[1].replace("\\", "/") == "tools/assemble_episode.py"]
    assert asm and asm[0][asm[0].index("--run") + 1] == V2
    assert x["status"] == "assembled", x
    assert Path(x["final"]).parent == N.EPS_OUT and Path(x["final"]).is_file()


# ---- 11-04：服务器合成缺 ns_schema + 重开漏洞 ----
def test_child_env_makes_assembly_importable_without_install(night_v2):
    """未安装项目、无 PYTHONPATH 的子进程（python -S 去掉 site-packages / 可编辑安装）也要能 import 合成链"""
    import os
    import subprocess
    env = night_v2.child_env()
    env = {k: v for k, v in env.items() if k != "PYTHONHOME"}
    code = "import ns_schema.h3_lint, ns_agent.h3_prompt, ns_post; print('ok')"
    r = subprocess.run([sys.executable, "-S", "-c", code], capture_output=True, text=True, env=env, cwd=str(night_v2.ROOT), timeout=120)
    # -S 丢掉 site-packages：第三方依赖若缺只能算环境问题，但绝不能是 ns_schema 找不到
    assert "No module named 'ns_schema'" not in r.stderr, r.stderr
    assert "No module named 'ns_agent'" not in r.stderr, r.stderr
    bare = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    r0 = subprocess.run([sys.executable, "-S", "-c", "import ns_schema"], capture_output=True, text=True, env=bare, cwd=os.getcwd(), timeout=120)
    assert r0.returncode != 0   # 对照：没有 PYTHONPATH 时确实导不进（复现服务器症状）


def test_reopen_assembled_when_sig_changed_even_if_all_done(night_v2, monkeypatch):
    monkeypatch.setattr(night_v2, "ep_sig", lambda ep, host: "NEW")
    st = {"eps": {"1": {"host": "h", "status": "assembled", "resolved_sig": "OLD"},
                  "2": {"host": "h", "status": "assembled", "resolved_sig": "NEW"}}}
    night_v2.reopen_changed(st)
    assert st["eps"]["1"]["status"] == "rendering" and st["eps"]["2"]["status"] == "assembled"


def test_assemble_failed_sig_changed_resets_retries(night_v2, monkeypatch):
    monkeypatch.setattr(night_v2, "ep_sig", lambda ep, host: "NEW")
    st = {"eps": {"1": {"host": "h", "status": "assemble_failed", "resolved_sig": "OLD", "assemble_retries": 3,
                        "finalized": __import__("time").time()},
                  "2": {"host": "h", "status": "assemble_failed", "resolved_sig": "NEW", "assemble_retries": 3,
                        "finalized": 0}}}
    night_v2.retry_assembly(st)
    assert st["eps"]["1"]["status"] == "rendering" and st["eps"]["1"]["assemble_retries"] == 0
    assert st["eps"]["2"]["status"] == "assemble_failed"   # 同输入用完 3 次 = 仍停住
