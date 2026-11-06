"""W46 EP01-FINALIZE：视频齐 → night finalize → data/episodes/<剧>/epNN_vN.mp4 → sop_gate 整集预览 → episode_retro --auto。
沙箱（gpu33 /root/work/fredw/w46）实跑查出的缺口，逐条钉住：
① night：hold_voices 原来是死胡同（retry_assembly 只救 hold_tts / assemble_failed）→ 音色到位后回到 rendering；
② （vidgen 整份控制文件一起判的问题由 W38 hf-20261104-10 在 sop_gate.vidgen_guard 里按 video_shots_ok 修掉，W46 的 vidgen 改动已撤回）
全部写入都在 tmp_path。"""
from __future__ import annotations

import importlib
import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in ("services/post", "services/agent", "tools", "tools/series10_video", ""):
    if str(ROOT / p) not in sys.path:
        sys.path.insert(0, str(ROOT / p))

V2 = "series10_v2"


@pytest.fixture
def night_v2(monkeypatch, tmp_path):
    orig = os.environ.get("NS_RUN")
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


# ---------------------------------------------------------------- ① hold_voices 不是终态
def test_hold_voices_retries_when_voices_arrive(night_v2, monkeypatch):
    N = night_v2
    st = {"eps": {"1": {"host": "gpu33", "status": "hold_voices"}}}
    monkeypatch.setattr(N, "voices_ok", lambda: False)
    N.retry_assembly(st)
    assert st["eps"]["1"]["status"] == "hold_voices"            # 音色还没到：继续等
    monkeypatch.setattr(N, "voices_ok", lambda: True)
    N.retry_assembly(st)
    assert st["eps"]["1"]["status"] == "rendering"              # 到了：下一步 EP_RESOLVED → finalize


def test_hold_tts_path_unchanged(night_v2, monkeypatch):
    N = night_v2
    st = {"eps": {"1": {"host": "gpu33", "status": "hold_tts"}}}
    monkeypatch.setattr(N, "tts_missing", lambda: None)
    monkeypatch.setattr(N, "voices_ok", lambda: (_ for _ in ()).throw(AssertionError("hold_tts 不该查音色表")))
    N.retry_assembly(st)
    assert st["eps"]["1"]["status"] == "rendering"


# ---------------------------------------------------------------- ③ 整集硬规矩（进 data/episodes/<剧>/ 之前）
def _tl(mp4: Path, shots, **kw):
    mp4.write_bytes(b"x")
    mp4.with_suffix(".timeline.json").write_text(json.dumps({"shots": shots, "subtitles": False, "gates": {"verdict": "pass"}, **kw}),
                                                 encoding="utf-8")


def _probe(dur, kinds=("video", "audio")):
    return lambda p: {"format": {"duration": str(dur)}, "streams": [{"codec_type": k} for k in kinds]}


def test_hard_rules_pass(night_v2, tmp_path):
    mp4 = tmp_path / "ep01_PREVIEW_v1.mp4"
    _tl(mp4, _sh(11, 5.8, 64 / 11))
    hr = night_v2.episode_hard_rules(mp4, probe=_probe(63.8))
    assert hr["ok"], hr
    assert hr["shots"] == 11 and hr["max_shot_s"] == 5.8


def _sh(n, secs=5.8, script=6.0):
    return [{"shot": f"ep01-S{i}", "duration_s": secs, "script_duration_s": script} for i in range(1, n + 1)]


@pytest.mark.parametrize("dur,shots,kinds,tlkw,needle", [
    (64.0, _sh(5, script=6.0), ("video", "audio"), {}, "L-092 剧本集长"),                        # 剧本 30 s
    (64.0, _sh(11, 5.0, 12.0), ("video", "audio"), {}, "L-092 剧本集长"),                         # 剧本 132 s
    (64.0, [{"shot": "ep01-S3", "duration_s": 6.5, "script_duration_s": 6}] + _sh(10), ("video", "audio"), {}, "C-08"),
    (64.0, _sh(11), ("video", "audio", "subtitle"), {}, "C-07"),
    (64.0, _sh(11), ("video", "audio"), {"subtitles": True}, "C-07"),
    (64.0, _sh(11), ("audio",), {}, "没有视频流"),
])
def test_hard_rules_fail(night_v2, tmp_path, dur, shots, kinds, tlkw, needle):
    mp4 = tmp_path / "ep01_PREVIEW_v1.mp4"
    _tl(mp4, shots, **tlkw)
    hr = night_v2.episode_hard_rules(mp4, probe=_probe(dur, kinds))
    assert not hr["ok"] and any(needle in f for f in hr["fails"]), hr


def test_hard_rules_trimmed_length_and_verdict_only_warn(night_v2, tmp_path):
    """W46 沙箱：剪辑修头尾后实长 19–55 s、对白溢出 verdict=fail → 预览照发（只记），剧本 64 s 合规"""
    mp4 = tmp_path / "ep01_PREVIEW_v1.mp4"
    _tl(mp4, _sh(11, 4.5, 64 / 11), gates={"verdict": "fail", "overflow": [{"shot": "S1"}]})
    hr = night_v2.episode_hard_rules(mp4, probe=_probe(49.5))
    assert hr["ok"] and hr["script_s"] == 64.0, hr
    assert any("合成实长" in w for w in hr["warnings"]) and any("verdict=fail" in w for w in hr["warnings"])


def test_hard_rules_tail_hold_not_counted(night_v2, tmp_path):
    mp4 = tmp_path / "ep01_PREVIEW_v1.mp4"
    _tl(mp4, _sh(9, 6.0, 6.0) + [{"shot": "ep01-S10", "duration_s": 5.0, "picture_s": 5.0, "script_duration_s": 5.0},
              {"shot": "ep01-S11", "duration_s": 6.0, "picture_s": 7.5, "script_duration_s": 5.0}], tail_hold_s=1.5)   # 末镜 6 s + 尾帧定格 1.5 s
    hr = night_v2.episode_hard_rules(mp4, probe=_probe(64))
    assert hr["ok"] and hr["max_shot_s"] == 6.0 and hr["tail_hold_s"] == 1.5, hr


def test_hard_rules_no_timeline_fails_closed(night_v2, tmp_path):
    mp4 = tmp_path / "x.mp4"
    mp4.write_bytes(b"x")
    hr = night_v2.episode_hard_rules(mp4, probe=_probe(64))
    assert not hr["ok"] and any("timeline" in f for f in hr["fails"])


def test_ffprobe_uses_server_shim_form_and_sees_subtitles(night_v2, monkeypatch, tmp_path):
    """服务器 ffprobe 是兼容壳：只认 -show_streams -show_format -of json（别的写法输出 {}）、看不见字幕流（04:1x gpu33 实测）"""
    import subprocess as sp
    seen = []

    def fake_run(args, **kw):
        assert kw.get("timeout"), "子进程必须带 timeout"
        seen.append(args)
        if "ffprobe" in args[0]:
            assert args[1:6] == ["-v", "error", "-show_streams", "-show_format", "-of"] or "-show_streams" in args
            return sp.CompletedProcess(args, 0, json.dumps({"format": {"duration": "64.0"}, "streams": [{"codec_type": "video"}]}), "")
        return sp.CompletedProcess(args, 1, "", "  Stream #0:2(chi): Subtitle: mov_text (tx3g)\n")
    monkeypatch.setattr(night_v2.subprocess, "run", fake_run)
    d = night_v2._ffprobe(tmp_path / "x.mp4")
    assert [s["codec_type"] for s in d["streams"]] == ["video", "subtitle"]
    monkeypatch.setattr(night_v2.subprocess, "run", lambda args, **kw: sp.CompletedProcess(args, 0, "{}", ""))
    assert "error" in night_v2._ffprobe(tmp_path / "x.mp4")                      # 壳不认的写法 → {} → 判不了 = 失败关闭


# ---------------------------------------------------------------- ④ finalize：硬规矩不过不发布；过了接复盘
def _finalize_env(N, monkeypatch, tmp_path, hard_ok: bool):
    """finalize 里服务器 / 子进程全部换成假的：代理 / 同步 / 放大 / 合成 / 导演 / 报告；合成器在 _work 落一个片 + timeline"""
    EPS = N.EPS_OUT
    (EPS / "_work").mkdir(parents=True, exist_ok=True)
    st = {"eps": {"1": {"host": "gpu33", "status": "rendering"}}}
    man = {"t": 0, "shots": [{"shot": "ep01-S1", "index": 1, "proxy": "p.mp4", "source": "s.mp4"}]}
    (N.VID / "episodes" / "ep01").mkdir(parents=True)
    (N.VID / "episodes" / "ep01" / "manifest.json").write_text(json.dumps(man), encoding="utf-8")
    monkeypatch.setattr(N, "voices_ok", lambda: True)
    monkeypatch.setattr(N, "tts_missing", lambda: None)
    monkeypatch.setattr(N, "ssh", lambda host, cmd, timeout=600: "")
    monkeypatch.setattr(N, "assembly_sources", lambda m, stills=None: ({"shots": [{"index": 1, "kind": "video", "file": "s.mp4"}]}, []))
    calls = []

    def fake_run(args, timeout=3600):
        calls.append(args[1] if len(args) > 1 else args[0])
        if "assemble_episode.py" in " ".join(map(str, args)):
            out = EPS / "_work" / "ep01_PREVIEW_v1.mp4"
            out.write_bytes(b"x")
            out.with_suffix(".timeline.json").write_text("{}", encoding="utf-8")
        return 0, "{}"
    monkeypatch.setattr(N, "run", fake_run)
    monkeypatch.setattr(N, "episode_hard_rules", lambda p, probe=None: {"ok": hard_ok, "fails": [] if hard_ok else ["L-092 集长 30s"]})
    monkeypatch.setattr(N, "bgm_after_assembly", lambda *a, **k: {})
    retro = []
    monkeypatch.setattr(N, "retro_after_assembly", lambda ep: retro.append(ep) or {"episode": ep, "done": "ok"})
    return st, retro


def test_finalize_publishes_and_runs_retro(night_v2, monkeypatch, tmp_path):
    N = night_v2
    st, retro = _finalize_env(N, monkeypatch, tmp_path, hard_ok=True)
    N.finalize(1, "gpu33", st, dict(N.DEFAULT_CTRL))
    x = st["eps"]["1"]
    assert x["status"] == "assembled" and (N.EPS_OUT / "ep01_v1.mp4").is_file()
    assert retro == [1] and x["retro"]["episode"] == 1 and x["hard_rules"]["ok"]


def test_finalize_hard_rule_fail_not_published(night_v2, monkeypatch, tmp_path):
    N = night_v2
    st, retro = _finalize_env(N, monkeypatch, tmp_path, hard_ok=False)
    N.finalize(1, "gpu33", st, dict(N.DEFAULT_CTRL))
    x = st["eps"]["1"]
    assert x["status"] == "assemble_failed" and "硬规矩不过" in x["assemble_err"]
    assert not list(N.EPS_OUT.glob("ep01*.mp4")) and retro == []      # sop_gate“整集预览”不会被不合规的片放行


def test_retro_after_assembly_calls_auto(night_v2, monkeypatch, tmp_path):
    N = night_v2
    root = tmp_path / "root"
    (root / "tools/master").mkdir(parents=True)
    (root / "tools/master/episode_retro.py").write_text(
        "def auto(run, ep, root):\n    return {'episode': ep, 'run': run, 'root': str(root)}\n", encoding="utf-8")
    monkeypatch.setattr(N, "ROOT", root)
    res = N.retro_after_assembly(1)
    assert res == {"episode": 1, "run": V2, "root": str(root)}
    (root / "tools/master/episode_retro.py").write_text("def auto(run, ep, root):\n    raise RuntimeError('x')\n", encoding="utf-8")
    assert "error" in N.retro_after_assembly(1)                        # 复盘出错只记，不抛


# ---------------------------------------------------------------- ⑤ run_sync 带上声音 / 配乐资产（服务器 night 合成要读）
def test_run_sync_pushes_voice_and_music_dirs(monkeypatch, tmp_path):
    from tools.autopilot import resident_sync as RS
    monkeypatch.setattr(RS, "ROOT", tmp_path)
    monkeypatch.setattr(RS, "log", lambda *a: None)
    (tmp_path / "config/pipeline").mkdir(parents=True)
    (tmp_path / "config/pipeline/runs.json").write_text(json.dumps({"primary": V2, "legacy_unprefixed_run": "series10_v1"}), encoding="utf-8")
    (tmp_path / "config/voices_v2.json").write_text(json.dumps({"roles": {"lead_f": {"candidates": [
        {"ref_wav": "data/assets/voices_v2/lead_f/b/ref.wav"}]}}}), encoding="utf-8")
    (tmp_path / "config/music_v2.json").write_text(json.dumps({"run": V2, "tracks": [{"file": "data/music/v2_style/A.flac"}]}),
                                                   encoding="utf-8")
    for d in ("data/assets/voices_v2/lead_f/b", "data/music/v2_style", f"data/music/{V2}"):
        (tmp_path / d).mkdir(parents=True)
    dirs, _files = RS.run_sync_sources(V2)
    assert {"data/assets/voices_v2", "data/music/v2_style", f"data/music/{V2}"} <= set(dirs)
    # 曲库登记的是别的剧 → 不推它的曲库；目录不存在 → 不列
    (tmp_path / "config/music_v2.json").write_text(json.dumps({"run": "other", "tracks": [{"file": "data/music/v2_style/A.flac"}]}),
                                                   encoding="utf-8")
    assert "data/music/v2_style" not in RS.run_media_dirs(V2)
    assert RS.run_media_dirs("series10_v1") == ["data/assets/voices_v2"]


# ---------------------------------------------------------------- ⑥ 出图机 → 视频机首尾帧中继（总调度 04:0x 定，gpu36 视频段前提①）
def _rs():
    from tools.autopilot import resident_sync as RS
    return RS


def test_relay_merge_keeps_dst_video():
    RS = _rs()
    src = {"takes": [{"stage": "image", "n": 2}, {"stage": "last", "n": 1}], "active": {"image": 2, "last": 1}}
    dst = {"takes": [{"stage": "image", "n": 1}, {"stage": "video", "n": 1, "file": "v.mp4"}], "active": {"image": 1, "video": 1}}
    out = RS.merge_takes(src, dst)
    assert out["active"] == {"image": 2, "last": 1, "video": 1}
    assert [(t["stage"], t["n"]) for t in out["takes"]] == [("image", 2), ("last", 1), ("video", 1)]
    assert RS.merge_takes(src, None)["active"] == {"image": 2, "last": 1}


def test_relay_pairs_from_partition():
    RS = _rs()
    part = {"images": {"gpu33": [1, 3], "gpu36": [2]}, "video": {"gpu33": [3], "gpu36": [1, 2]}}
    assert RS.relay_pairs(V2, part) == [("gpu33", "gpu36", 1)]            # ep02 出图 / 视频同机、ep03 同机 → 不中继
    assert RS.relay_pairs(V2, {"images": {"gpu33": [1]}, "video": {"gpu33": [1]}}) == []
    per_run = {"images": {"gpu33": [1]}, "video": {"gpu33": [1]}, "runs": {V2: {"video": {"gpu36": [1]}}}}
    assert RS.relay_pairs(V2, per_run) == [("gpu33", "gpu36", 1)]        # 按剧分区优先（night.partition_hosts 同口径）
    assert RS.relay_pairs(V2, {"images": {"laptop": [1]}, "video": {"gpu36": [1]}}) == []   # 只在两台服务器之间


def _host_tree(root: Path, takes: dict, files: dict):
    d = root / f"data/renders/{V2}/ep01/S1"
    d.mkdir(parents=True, exist_ok=True)
    (d / "takes.json").write_text(json.dumps(takes), encoding="utf-8")
    for rel, data in files.items():
        (root / "data" / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / "data" / rel).write_bytes(data)


def _fake_ssh(roots: dict, calls: list):
    """把 relay 发出的远端命令在本机两个临时“主机”目录里执行（真跑 RELAY_LIST / RELAY_INSTALL 源码，不连网）"""
    import io
    import shlex
    import subprocess
    import tarfile

    def fn(host, cmd, data=None, timeout=900, tries=5):
        assert timeout, "必须带 timeout"
        calls.append((host, cmd[:40]))
        root = roots[host]
        body = cmd.split("&& ", 1)[1]
        if body.startswith("python3 - "):
            r = subprocess.run([sys.executable, "-", *body.split()[2:]], input=data, cwd=root, capture_output=True, timeout=60)
            return r.stdout
        if body.startswith("python3 -c "):
            parts = shlex.split(body)
            r = subprocess.run([sys.executable, "-c", parts[2], *parts[3:]], input=data, cwd=root, capture_output=True, timeout=60)
            assert r.returncode == 0, r.stderr
            return r.stdout
        if body.startswith("tar cf - -T -"):
            bio = io.BytesIO()
            with tarfile.open(fileobj=bio, mode="w") as tf:
                for f in data.decode().splitlines():
                    tf.add(str(root / f), arcname=f)
            return bio.getvalue()
        out = []
        for f in [x for x in re.findall(r"\[ -f '([^']+)' \]", body)]:
            if (root / f).is_file():
                out.append(f"{f}\t{(root / f).stat().st_size}")
        return "\n".join(out).encode()
    return fn


import re  # noqa: E402


@pytest.mark.skipif(sys.platform.startswith("win"), reason="RELAY_INSTALL 用 fcntl（服务器 Linux）；gpu33 remote_pytest 上跑")
def test_relay_end_to_end_merges_and_is_incremental(tmp_path):
    RS = _rs()
    a, b = tmp_path / "gpu33", tmp_path / "gpu36"
    img = f"renders/{V2}/ep01/S1/takes/image_002_x_raw_post.png"
    old = f"renders/{V2}/ep01/S1/takes/image_001_y_raw_post.png"
    _host_tree(a, {"takes": [{"stage": "image", "n": 1, "file": old}, {"stage": "image", "n": 2, "file": img, "postflight": {"ok": True}}],
                   "active": {"image": 2}}, {img: b"PNG2", old: b"PNG1"})
    _host_tree(b, {"takes": [{"stage": "video", "n": 1, "file": "v.mp4"}], "active": {"video": 1}}, {})
    part = {"images": {"gpu33": [1]}, "video": {"gpu36": [1]}}
    calls = []
    sp = tmp_path / "relay.json"
    res = RS.relay_video_frames(V2, part, ssh_fn=_fake_ssh({"gpu33": a, "gpu36": b}, calls), state_path=sp)
    row = res["pairs"][0]
    assert row["todo"] == 2 and row["installed"] == 2 and "error" not in row          # 当前首帧 + takes.json；旧版本图不传
    assert (b / "data" / img).read_bytes() == b"PNG2" and not (b / "data" / old).exists()
    got = json.loads((b / f"data/renders/{V2}/ep01/S1/takes.json").read_text(encoding="utf-8"))
    assert got["active"] == {"image": 2, "video": 1} and [t["stage"] for t in got["takes"]] == ["image", "image", "video"]
    res2 = RS.relay_video_frames(V2, part, ssh_fn=_fake_ssh({"gpu33": a, "gpu36": b}, calls), state_path=sp)
    assert res2["pairs"][0]["todo"] == 0                                                 # 没变 = 不传（视频机合并后的 sha 不触发重传）


def test_relay_failure_counts_without_raising(tmp_path, monkeypatch):
    RS = _rs()
    monkeypatch.setattr(RS, "log", lambda *a: None)
    seen = []
    monkeypatch.setattr(RS, "_w40_issue", lambda step, what, hint: seen.append(what) or "ISS-x")

    def boom(host, cmd, data=None, timeout=900, tries=5):
        raise RuntimeError("rc=255")
    sp = tmp_path / "relay.json"
    for _ in range(RS.RELAY_FAIL_REPORT):
        res = RS.relay_video_frames(V2, {"images": {"gpu33": [1]}, "video": {"gpu36": [1]}}, ssh_fn=boom, state_path=sp)
        assert "rc=255" in res["pairs"][0]["error"]
    assert len(seen) == 1                                                                 # 连续 3 拍失败登记一次卡点


def test_run_sync_sha_mismatch_pushes_even_if_server_newer(monkeypatch, tmp_path):
    RS = _rs()
    import hashlib
    monkeypatch.setattr(RS, "ROOT", tmp_path)
    monkeypatch.setattr(RS, "log", lambda *a: None)
    (tmp_path / "assets_v2").mkdir()
    (tmp_path / "assets_v2/manifest.json").write_bytes(b"NEW")
    monkeypatch.setattr(RS, "run_sync_authoritative", lambda runs=None: ["assets_v2/manifest.json"])
    loc = {"assets_v2/manifest.json": (3, 100.0)}
    other = hashlib.sha256(b"OLD").hexdigest()
    same = hashlib.sha256(b"NEW").hexdigest()
    assert RS.run_sync_sha_todo("gpu36", loc, ssh_fn=lambda h, c, timeout=0: f"{other}  assets_v2/manifest.json\n".encode()) == \
        ["assets_v2/manifest.json"]
    assert RS.run_sync_sha_todo("gpu36", loc, ssh_fn=lambda h, c, timeout=0: f"{same}  assets_v2/manifest.json\n".encode()) == []
    assert RS.run_sync_sha_todo("gpu36", loc, ssh_fn=lambda h, c, timeout=0: b"ok") == []          # 读不到 = 不加
    # 和 mtime 规则合起来：服务器 mtime 更新（200 > 100）→ run_sync_todo 不推；sha 不同 → 照推
    newer = {"assets_v2/manifest.json": (3, 200.0)}
    assert RS.run_sync_todo(loc, newer) == []
    assert RS.run_sync_sha_todo("gpu36", loc, newer, ssh_fn=lambda h, c, timeout=0: f"{other}  assets_v2/manifest.json\n".encode()) == \
        ["assets_v2/manifest.json"]
    # 笔记本更新的（mtime 规则本来就推）→ 不多跑一次远端 sha
    assert RS.run_sync_sha_todo("gpu36", loc, {"assets_v2/manifest.json": (3, 50.0)},
                                ssh_fn=lambda *a, **k: (_ for _ in ()).throw(AssertionError("不该查 sha"))) == []


# ---------------------------------------------------------------- ⑦ 服务器 ffprobe 兼容壳（gpu36 没有真 ffprobe；原壳只认两种写法）
def _shim(monkeypatch):
    import importlib.util as u
    sp = u.spec_from_file_location("ffprobe_shim_w46", ROOT / "tools/series10_video/ffprobe_shim.py")
    m = u.module_from_spec(sp)
    sp.loader.exec_module(m)
    monkeypatch.setattr(m, "info", lambda p: ([{"index": 0, "codec_type": "video", "codec_name": "h264", "width": 768, "height": 1344,
                                                 "r_frame_rate": "24/1"}, {"index": 1, "codec_type": "audio", "codec_name": "aac"}],
                                                {"filename": p, "duration": "5.17"}))
    monkeypatch.setattr(m, "count_frames", lambda p, stream="v:0": 124)
    return m


@pytest.mark.parametrize("argv,want", [
    (["-v", "error", "-select_streams", "v:0", "-count_packets", "-show_entries", "stream=nb_read_packets", "-of", "csv=p=0"], "124"),   # ns_post count_frames
    (["-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "csv=p=0"], "768,1344"),               # dejudder 旧写法
    (["-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1"], "5.17"),
    (["-v", "error", "-select_streams", "v:0", "-show_entries", "stream=r_frame_rate", "-of", "csv=p=0"], "24/1"),
])
def test_shim_emulates_common_forms(monkeypatch, capsys, argv, want):
    m = _shim(monkeypatch)
    assert m.emulate([*argv, "x.mp4"]) == 0
    assert capsys.readouterr().out.strip() == want


def test_shim_json_form_unchanged(monkeypatch, capsys):
    m = _shim(monkeypatch)
    m.emulate(["-v", "error", "-show_streams", "-show_format", "-of", "json", "x.mp4"])
    d = json.loads(capsys.readouterr().out)
    assert [s["codec_type"] for s in d["streams"]] == ["video", "audio"] and d["format"]["duration"] == "5.17"


def test_shim_prefers_working_real_ffprobe(monkeypatch, tmp_path):
    m = _shim(monkeypatch)
    monkeypatch.setattr(m, "REAL_CANDIDATES", [str(tmp_path / "nope")])
    assert m.real_ffprobe() is None                                    # gpu36：没有 → 仿真
    src = (ROOT / "tools/series10_video/ffprobe_shim.py").read_text(encoding="utf-8")
    assert src.count("timeout=") >= 3                                   # 子进程都带 timeout


def test_dejudder_wh_uses_shim_form(monkeypatch):
    import subprocess as sp
    sys.path.insert(0, str(ROOT / "tools"))
    np = pytest.importorskip("numpy")  # noqa: F841
    import importlib.util as u
    spec = u.spec_from_file_location("dejudder_w46", ROOT / "tools/dejudder.py")
    try:
        DJ = u.module_from_spec(spec)
        spec.loader.exec_module(DJ)
    except ImportError as e:                                            # motion_judder 依赖 cv2
        pytest.skip(str(e))
    seen = {}

    def fake(args, **kw):
        seen.update(args=args, timeout=kw.get("timeout"))
        return sp.CompletedProcess(args, 0, json.dumps({"streams": [{"codec_type": "video", "width": 768, "height": 1344}]}), "")
    monkeypatch.setattr(DJ.subprocess, "run", fake)
    assert DJ.video_wh(Path("x.mp4")) == (768, 1344)
    assert "-show_streams" in seen["args"] and seen["timeout"]


# ---------------------------------------------------------------- ⑧ 部分预览（总调度 04:2x：有几镜拼几镜）
def test_partial_due_rule():
    import importlib.util as u
    sp = u.spec_from_file_location("partial_w46", ROOT / "tools/master/partial_preview.py")
    PP = u.module_from_spec(sp)
    sp.loader.exec_module(PP)
    assert not PP.due(2, None) and PP.due(3, None)                  # ≥3 镜才第一次拼
    assert not PP.due(4, 3) and PP.due(5, 3)                        # 之后每多 2 镜
    assert PP.due(1, None, force=True) and not PP.due(0, None, force=True)


def test_partial_video_shots_own_prefix_only(tmp_path):
    import importlib.util as u
    sp = u.spec_from_file_location("partial_w46b", ROOT / "tools/master/partial_preview.py")
    PP = u.module_from_spec(sp)
    sp.loader.exec_module(PP)
    base = tmp_path / f"data/renders/{V2}/ep01"
    for s, f in (("S1", f"renders/{V2}/ep01/S1/takes/video_001.mp4"), ("S2", "renders/ep01/S2/takes/video_001.mp4"), ("S3", None)):
        (base / s).mkdir(parents=True)
        d = {"takes": [{"stage": "video", "n": 1, "file": f}] if f else [], "active": {"video": 1} if f else {}}
        (base / s / "takes.json").write_text(json.dumps(d), encoding="utf-8")
        if f:
            (tmp_path / "data" / f).parent.mkdir(parents=True, exist_ok=True)
            (tmp_path / "data" / f).write_bytes(b"x")
    assert PP.video_shots(V2, 1, tmp_path) == ["ep01-S1"]           # S2 是 V1 前缀（C-14）不算
    vid = tmp_path / f"data/pipeline/runs/{V2}/video"
    (vid / "clips/ep01").mkdir(parents=True)
    (vid / "clips/ep01/ep01-S3__v1_s1.mp4").write_bytes(b"x")
    rel = f"data/pipeline/runs/{V2}/video/clips/ep01/ep01-S3__v1_s1.mp4"
    (vid / "state_gpu36.json").write_text(json.dumps({"shots": {
        "ep01-S3": {"status": "done", "chosen": "v1", "renders": [{"variant": "v1", "file": rel}]},
        "ep01-S4": {"status": "rendering", "chosen": None, "renders": [{"variant": "v1", "state": "submitted"}]}}}), encoding="utf-8")
    assert PP.video_shots(V2, 1, tmp_path) == ["ep01-S1", "ep01-S3"]   # vidgen 出完还没登记进 takes.json 的也算


def test_partial_output_not_seen_by_sop_gate(tmp_path):
    """部分预览写 data/episodes/<剧>/_partial/：sop_gate.check_preview 只认顶层 epNN*.mp4 → 不放行复盘 / 下一集"""
    from tools.master import sop_gate as SG
    d = tmp_path / SG._episodes_rel(V2) / "_partial"
    d.mkdir(parents=True)
    (d / "ep01_preview_partial_0430.mp4").write_bytes(b"x")
    assert not SG.check_preview(tmp_path, V2, 1)["ok"]
    (d.parent / "ep01_v1.mp4").write_bytes(b"x")
    assert SG.check_preview(tmp_path, V2, 1)["ok"]


def test_label_still_and_takes_video(tmp_path, monkeypatch):
    pytest.importorskip("PIL")
    import tools.assemble_series as AS
    p = AS.label_still(tmp_path / "S4.png", "ep01-S4")
    from PIL import Image
    im = Image.open(p)
    assert im.size == (1080, 1920) and im.getpixel((5, 5)) == (0, 0, 0) and max(im.convert("L").getextrema()) > 100
    monkeypatch.setattr(AS, "ROOT", tmp_path)
    rd = tmp_path / f"data/renders/{V2}"
    monkeypatch.setattr(AS.RUNS, "renders_dir", lambda run, root=None: rd)
    monkeypatch.setattr(AS, "RUN_ID", V2)
    (rd / "ep01/S2/takes").mkdir(parents=True)
    (rd / "ep01/S2/takes/video_003.mp4").write_bytes(b"x")
    (rd / "ep01/S2/takes.json").write_text(json.dumps({"takes": [{"stage": "video", "n": 3, "file": f"renders/{V2}/ep01/S2/takes/video_003.mp4"}],
                                                       "active": {"video": 3}}), encoding="utf-8")
    assert AS.own_active_video("ep01-S2") == (f"data/renders/{V2}/ep01/S2/takes/video_003.mp4", 3)
    assert AS.own_active_video("ep01-S5") is None


def test_relay_pull_laptop_overwrites_frames_keeps_video_and_backs_up(tmp_path):
    RS = _rs()
    a, lap = tmp_path / "gpu33", tmp_path / "laptop"
    img = f"renders/{V2}/ep01/S3/takes/image_001_g_raw_post.png"
    _host_tree(a, {"takes": [{"stage": "image", "n": 1, "file": img, "postflight": {"ok": True}}], "active": {"image": 1}}, {img: b"G33"})
    (a / f"data/renders/{V2}/ep01/S3").mkdir(parents=True, exist_ok=True)
    (a / f"data/renders/{V2}/ep01/S1/takes.json").rename(a / f"data/renders/{V2}/ep01/S3/takes.json")
    d = lap / f"data/renders/{V2}/ep01/S3"
    d.mkdir(parents=True)
    forked = {"takes": [{"stage": "image", "n": 12, "file": "x.png"}, {"stage": "video", "n": 2, "file": "v.mp4"}], "active": {"image": 12, "video": 2}}
    (d / "takes.json").write_text(json.dumps(forked), encoding="utf-8")
    part = {"images": {"gpu33": [1]}, "video": {"gpu36": [1]}}
    calls = []
    sp = tmp_path / "relay.json"
    res = RS.relay_pull_laptop(V2, part, ssh_fn=_fake_ssh({"gpu33": a}, calls), state_path=sp, root=lap)
    row = res["pulls"][0]
    assert "error" not in row and row["installed"] == 2, row
    got = json.loads((d / "takes.json").read_text(encoding="utf-8"))
    assert got["active"] == {"image": 1, "video": 2}                                  # gpu33 为准 + 笔记本视频段保留
    assert json.loads((d / "takes.json.bak-w46-pull").read_text(encoding="utf-8")) == forked
    assert (lap / "data" / img).read_bytes() == b"G33"
    assert not any("python3 -c" in c[1] for c in calls)                                # 源机只读
    res2 = RS.relay_pull_laptop(V2, part, ssh_fn=_fake_ssh({"gpu33": a}, calls), state_path=sp, root=lap)
    assert res2["pulls"][0]["todo"] == 0


# ---------------------------------------------------------------- ⑨ 帧数根因：17k+5 向上对齐把 6 s 拉成 6.58 s（gpu36 ep01-S2/S3 实测）
def test_cap_frames_c08():
    sys.path.insert(0, str(ROOT / "services/recipes"))
    sys.path.insert(0, str(ROOT / "packages/schema"))
    from ns_recipes.compiler import cap_frames_c08
    from ns_schema.shot_spec import frames_for_seconds
    assert frames_for_seconds(6.0) == 158                         # 官方对齐本身不变
    assert cap_frames_c08(158, 6.0) == 141 and 141 / 24 <= 6.0     # 5.875 s；Pika 12 fps ≈ 71 帧 ≤ 72
    assert cap_frames_c08(frames_for_seconds(5.0), 5.0) == 124     # 5.17 s 本来就 ≤ 6，不动
    assert cap_frames_c08(frames_for_seconds(5.5), 5.5) == 141     # 132 → 141（5.875 s）
    assert cap_frames_c08(175, 7.0) == 175                         # 剧本本身 > 6 s 的不在这里改（导入闸门挡）
    for sec in (3, 4, 4.5, 5, 5.5, 5.9, 6):
        n = cap_frames_c08(frames_for_seconds(sec), sec)
        assert n / 24 <= 6.0 and (n - 5) % 17 == 0


# ---------------------------------------------------------------- ⑩ 合成前单镜裁到 ≤ 6.0 s（已出的 6.58 s 片兜底）
def _ct():
    import importlib.util as u
    sp = u.spec_from_file_location("clip_trim_w46", ROOT / "tools/series10_video/clip_trim.py")
    m = u.module_from_spec(sp)
    sp.loader.exec_module(m)
    return m


def test_trim_le_only_when_over(tmp_path):
    CT = _ct()
    src = tmp_path / "ep01-S2__v1_s1.mp4"
    src.write_bytes(b"x")
    calls = []

    def fake_run(args, **kw):
        assert kw.get("timeout")
        calls.append(args)
        Path(args[-1]).write_bytes(b"trimmed")
        import subprocess as sp
        return sp.CompletedProcess(args, 0, b"", b"")
    assert CT.trim_le(src, run=fake_run, dur=lambda p: 5.17) == src and not calls        # 不超：原样
    out = CT.trim_le(src, run=fake_run, dur=lambda p: 6.58)
    assert out.name == "ep01-S2__v1_s1_le6.mp4" and out.read_bytes() == b"trimmed" and src.read_bytes() == b"x"
    a = calls[0]
    assert a[a.index("-t") + 1] == "6.000" and "-ss" not in a                             # 尾部裁、从首帧起
    assert CT.trim_le(src, run=fake_run, dur=lambda p: 6.58) == out and len(calls) == 1    # 已裁过且更新 → 复用
    assert CT.trim_le(src, run=fake_run, dur=lambda p: 0.0) == src                        # 读不到时长 = 不裁


def test_assembly_sources_uses_trimmed_clip(night_v2, monkeypatch, tmp_path):
    N = night_v2
    root = tmp_path / "root"
    monkeypatch.setattr(N, "ROOT", root)
    src = root / "data/clips/ep01-S2__v1_s1.mp4"
    proxy = root / "data/proxy/ep01-S2.mp4"
    for f in (src, proxy):
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(b"x")
    le6 = src.with_name(src.stem + "_le6.mp4")
    le6.write_bytes(b"y")
    monkeypatch.setattr(N, "clip_wh", lambda p: (540, 960) if "proxy" in str(p) else (768, 1344))
    import clip_trim
    monkeypatch.setattr(clip_trim, "trim_le", lambda p, *a, **k: le6)
    tl, bad = N.assembly_sources({"shots": [{"shot": "ep01-S2", "index": 2, "proxy": "data/proxy/ep01-S2.mp4",
                                              "source": "data/clips/ep01-S2__v1_s1.mp4"}]})
    assert not bad and tl["shots"][0]["file"].endswith("_le6.mp4") and "裁到 ≤6 s" in tl["shots"][0]["origin"]


# ---------------------------------------------------------------- ⑪ 冲刺规则：每镜先各出 1 条，再出第 2 变体（总调度 05:3x）
def test_first_take_first():
    import vidgen as VG
    shots = {s: {"variants": {"v1": {}, "r24": {}}} for s in ("ep01-S1", "ep01-S2", "ep01-S4")}
    recs = {"ep01-S2": {"status": "retry", "renders": [{"variant": "v1", "state": "scored"}]},
            "ep01-S1": {"status": "pending", "renders": []}, "ep01-S4": {"status": "pending", "renders": []}}
    todo = [("ep01-S1", "v1"), ("ep01-S2", "r24"), ("ep01-S4", "v1")]
    assert VG.first_take_first(todo, shots, recs) == [("ep01-S1", "v1"), ("ep01-S4", "v1")]     # S2 第 2 变体等
    recs["ep01-S1"]["renders"] = [{"variant": "v1", "state": "submitted"}]
    recs["ep01-S4"]["renders"] = [{"variant": "v1", "state": "submitted"}]
    assert VG.first_take_first([("ep01-S2", "r24")], shots, recs) == [("ep01-S2", "r24")]        # 都起跑了 → 放行重试
    recs["ep01-S4"] = {"status": "pending", "renders": []}
    assert VG.first_take_first([("ep01-S2", "r24")], shots, recs, {"first_take_first": False}) == [("ep01-S2", "r24")]
    shots["ep01-S9"] = {"variants": {}}                                                            # 没变体（等首帧）的镜不算
    recs.pop("ep01-S4"); shots.pop("ep01-S4")
    assert VG.first_take_first([("ep01-S2", "r24")], shots, recs) == [("ep01-S2", "r24")]


def test_night_ready_sig_includes_last_frames():
    src = (ROOT / "tools/series10_video/night.py").read_text(encoding="utf-8")
    body = src.split("def loop_once", 1)[1].split("\ndef ", 1)[0]
    assert "passed_lasts" in body and '"lasts": lasts' in body


# ---------------------------------------------------------------- ⑫ 已登记的 > 6 s 当前视频换成 _le6（总调度 05:4x：不重出）
class _FakeP:
    def __init__(self, root, takes):
        self.DATA, self.takes, self.mut = root, takes, []

    def load_takes(self, shot):
        return self.takes[shot]

    def mutate_takes(self, shot, fn, **kw):
        fn(self.takes[shot])
        self.mut.append(kw.get("op"))


class _FakeRT:
    def __init__(self, P):
        self.P, self.items = P, []

    def register(self, item, label=""):
        self.items.append(item)
        d = self.P.takes[item["shot"]]
        n = max(t["n"] for t in d["takes"] if t["stage"] == "video") + 1
        d["takes"].append({"stage": "video", "n": n, "file": str(Path(item["file"]).relative_to(self.P.DATA)).replace("\\", "/"),
                           "params": {}})
        if item["postflight"]["ok"]:
            d["active"]["video"] = n
        return {"status": "registered", "n": n, "active": item["postflight"]["ok"]}


def _tt():
    import importlib.util as u
    sys.path.insert(0, str(ROOT / "tools/series10_video"))
    sp = u.spec_from_file_location("trim_takes_w46", ROOT / "tools/series10_video/trim_takes.py")
    m = u.module_from_spec(sp)
    sp.loader.exec_module(m)
    return m


def test_trim_takes_replaces_long_active_keeps_original(tmp_path):
    TT = _tt()
    rel = f"renders/{V2}/ep01/S2/takes/video_001_pipeline_65244543.mp4"
    (tmp_path / rel).parent.mkdir(parents=True)
    (tmp_path / rel).write_bytes(b"x")
    le6 = tmp_path / rel.replace(".mp4", "_le6.mp4")
    le6.write_bytes(b"y")
    takes = {"ep01-S2": {"takes": [{"stage": "video", "n": 1, "file": rel, "postflight": {"ok": True, "items": []}}], "active": {"video": 1}}}
    P = _FakeP(tmp_path, takes)
    RT = _FakeRT(P)
    durs = {str(tmp_path / rel): 6.58, str(le6): 6.0}
    r = TT.fix_shot("ep01-S2", P, RT, dur=lambda p: durs[str(p)], trim=lambda p: le6)
    assert r["status"] == "registered" and r["from_n"] == 1 and r["n"] == 2 and r["active"]
    d = takes["ep01-S2"]
    assert d["active"]["video"] == 2 and any(t["n"] == 1 for t in d["takes"])                   # 原版保留
    assert next(t for t in d["takes"] if t["n"] == 2)["params"]["trimmed_from"] == 1
    assert RT.items[0]["postflight"]["items"][-1]["id"] == "C08"
    assert TT.fix_shot("ep01-S2", P, RT, dur=lambda p: 6.0)["status"] == "ok"                   # 再跑：当前已 ≤6 s，不动


def test_trim_takes_short_or_failed_gate(tmp_path):
    TT = _tt()
    rel = f"renders/{V2}/ep01/S10/takes/video_001.mp4"
    (tmp_path / rel).parent.mkdir(parents=True)
    (tmp_path / rel).write_bytes(b"x")
    takes = {"ep01-S10": {"takes": [{"stage": "video", "n": 1, "file": rel, "postflight": {"ok": False}}], "active": {"video": 1}}}
    P = _FakeP(tmp_path, takes)
    RT = _FakeRT(P)
    assert TT.fix_shot("ep01-S10", P, RT, dur=lambda p: 5.17)["status"] == "ok"
    le6 = tmp_path / "le6.mp4"
    le6.write_bytes(b"y")
    r = TT.fix_shot("ep01-S10", P, RT, dur=lambda p: 6.58 if "le6" not in str(p) else 6.0, trim=lambda p: le6)
    assert r["status"] == "registered" and not r["active"] and takes["ep01-S10"]["active"]["video"] == 1   # 原版门没过 → 不设当前


def test_night_calls_trim_takes_after_register():
    src = (ROOT / "tools/series10_video/night.py").read_text(encoding="utf-8")
    body = src.split("def loop_once", 1)[1].split("\ndef ", 1)[0]
    assert body.index("register_takes.py") < body.index("trim_takes.py") < body.index("retry_assembly(st)")
