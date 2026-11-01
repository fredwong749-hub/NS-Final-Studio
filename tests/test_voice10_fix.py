"""VOICE10 2026-11-01（fredw-2b 派，夜间计划 W6）：series10 合成不再因为 TTS 失败。

- K-EDT-019：同一集同一角色说同一句（ep04 S1/S2“今天特意早点回来。”）只合成一次，不报“TTS did not write …tmp.wav”。
- K-EDT-020：speakers.py 解析出的说话人 id 都在 config/voices.json 里有音色；旧 60 集配角称呼已隔离、不参与解析。
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "post"))

from ns_post import speakers  # noqa: E402
from ns_post.tts import FakeTts, Voice, synthesize_cached  # noqa: E402

VOICES = json.loads((ROOT / "config" / "voices.json").read_text(encoding="utf-8"))
CAST = ["lin_wan", "gu_chen", "chen_yu", "ch_a_lan"]


class CountingTts(FakeTts):
    def __init__(self):
        super().__init__()
        self.batches: list[list[Path]] = []

    def synthesize(self, items):
        self.batches.append([p for _, _, p in items])
        super().synthesize(items)


def test_duplicate_line_same_voice_synthesized_once(tmp_path):
    """ep04 根因：两个相同 (台词, 音色) 请求 → 旧代码把同一个 tmp 放进 todo 两次，第二次找不到 tmp 报错。"""
    v = Voice("chen_yu", 77, "x", 1.0)
    tts = CountingTts()
    paths = synthesize_cached(tts, [("今天特意早点回来。", v), ("累不累？", v), ("今天特意早点回来。", v)], tmp_path)
    assert paths[0] == paths[2] and paths[0] != paths[1]
    assert all(p.is_file() for p in paths)
    assert len(tts.batches) == 1 and len(tts.batches[0]) == 2          # 重复句只合成一次
    assert not list(tmp_path.glob("*.tmp.wav"))
    # 再合成一次全部命中缓存，不调后端
    synthesize_cached(tts, [("今天特意早点回来。", v)], tmp_path)
    assert len(tts.batches) == 1


def test_named_speakers_all_have_voices():
    chars = VOICES["characters"]
    for token, sid in speakers.NAMED:
        assert sid in chars, f"speakers.NAMED 里的 {token} → {sid} 在 config/voices.json 没有音色"
    for sid in speakers.MALES:
        assert chars.get(sid, {}).get("gender") == "male", sid
    for _, sid in speakers.MALE_NAMES:
        assert sid in speakers.MALES
    assert speakers.DEFAULT_MALE in chars and speakers.LEAD in chars


def test_legacy_60ep_titles_quarantined():
    named_tokens = {t for t, _ in speakers.NAMED}
    for token, sid in speakers.LEGACY_60EP_TITLES:
        assert token not in named_tokens and sid not in VOICES["characters"]
    assert speakers.speaker_from_note("画外，店员的招呼声") == (None, "none")


def test_series10_cast_voices_complete():
    """D-VOC-04/05/06 同口径：4 位角色都有 series10_v1 音色、不是旧 Kokoro、参考音频在且 sha 对得上。"""
    import hashlib
    assert VOICES.get("series") == "series10_v1"
    for cid in CAST:
        c = VOICES["characters"][cid]
        assert c.get("series") == "series10_v1", cid
        assert c.get("engine") == "cosyvoice3_zs", cid
        assert c.get("voice") != "zf_067"
        ref = ROOT / c["ref_wav"]
        assert ref.is_file(), ref
        assert hashlib.sha256(ref.read_bytes()).hexdigest() == c["ref_sha256"], cid
        meta = json.loads((ROOT / c["asset"]).read_text(encoding="utf-8"))
        assert meta.get("ref_text") or c.get("ref_text"), f"{cid} 缺 ref_text（RemoteCloneBackend 需要）"


def test_every_series10_line_resolves_to_a_voice():
    from ns_post.tts import voice_for
    script = json.loads((ROOT / "data" / "import" / "script_v2.json").read_text(encoding="utf-8"))
    seen = set()
    for ep in script["episodes"]:
        for line in speakers.resolve_episode(ep, VOICES.get("line_overrides") or {}):
            voice_for(VOICES, line.speaker, voiceover=line.kind == "voiceover")
            seen.add(line.speaker)
    assert seen <= set(VOICES["characters"])


def test_tts_preflight_reports_each_missing_piece(tmp_path):
    """K-EDT-021：合成前一次查完；缺参考音频 / ref_text / 远端模型 / 说话人都要点名，齐了返回空。"""
    import hashlib
    from ns_post.tts import tts_preflight
    exe = tmp_path / "py.exe"
    exe.write_bytes(b"")
    (tmp_path / "kok").mkdir()
    (tmp_path / "sv").mkdir()
    ref = tmp_path / "a" / "ref.wav"
    ref.parent.mkdir()
    ref.write_bytes(b"RIFF")
    (tmp_path / "a" / "meta.json").write_text(json.dumps({"ref_text": "坐稳"}), encoding="utf-8")
    cfg = {"speech_python": {"default": str(exe)}, "tts_model": {"default_dir": str(tmp_path / "kok")},
           "asr_model": {"default_dir": str(tmp_path / "sv")},
           "remote_tts": {"host": "gpu36", "base_dir": "/x", "model_dirs": {"cosyvoice3_zs": "/m"}},
           "characters": {"ch_a_lan": {"engine": "cosyvoice3_zs", "ref_wav": "a/ref.wav", "asset": "a/meta.json",
                                       "ref_sha256": hashlib.sha256(b"RIFF").hexdigest()}}}
    assert tts_preflight(cfg, root=tmp_path) == []
    assert any("piercer" in m for m in tts_preflight(cfg, speakers=["piercer"], root=tmp_path))
    bad = json.loads(json.dumps(cfg))
    bad["characters"]["ch_a_lan"]["ref_sha256"] = "0" * 64
    bad["remote_tts"]["model_dirs"] = {}
    (tmp_path / "a" / "meta.json").write_text("{}", encoding="utf-8")
    miss = tts_preflight(bad, root=tmp_path)
    assert any("sha" in m for m in miss) and any("ref_text" in m for m in miss) and any("model_dirs" in m for m in miss)
    bad["speech_python"] = {"env": "NS_TTS_PYTHON_NOPE", "default": str(tmp_path / "nope.exe")}
    assert any("NS_TTS_PYTHON_NOPE" in m for m in tts_preflight(bad, root=tmp_path))


def test_tts_preflight_on_this_project_config():
    """本机真实配置：series10 四位角色 + 旁白的音色前提都齐（笔记本上解释器 / 模型不在时只报那两项，不报音色）。"""
    from ns_post.tts import tts_preflight
    miss = tts_preflight(VOICES, root=ROOT)
    assert not [m for m in miss if not m.startswith(("没有配音解释器", "没有 tts_model", "没有 asr_model"))], miss


def test_remote_clone_runs_locally_on_its_own_host(tmp_path, monkeypatch):
    """K-EDT-022：服务器常驻合成时 night 就在 gpu36 上，RemoteCloneBackend 不能 ssh 自己；OFFLINE_SELF == host → 本机执行。"""
    import subprocess
    from ns_post import tts
    calls = []

    def fake(cmd, timeout):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    cfg = {"remote_tts": {"host": "gpu36", "base_dir": "/r"}}
    monkeypatch.delenv("NS_TTS_REMOTE_LOCAL", raising=False)
    monkeypatch.setenv("OFFLINE_SELF", "gpu33")
    assert not tts.RemoteCloneBackend(cfg, runner=fake).local          # gpu33 → 照旧 ssh gpu36
    monkeypatch.setenv("OFFLINE_SELF", "gpu36")
    b = tts.RemoteCloneBackend(cfg, runner=fake)
    assert b.local
    b._ssh("mkdir -p /r/jobs/x")
    b._scp("/tmp/a.json", "gpu36:/r/jobs/x/request.json")
    b._scp("gpu36:/r/jobs/x/000.wav", "/out/000.wav")
    assert calls == [["bash", "-c", "mkdir -p /r/jobs/x"], ["cp", "/tmp/a.json", "/r/jobs/x/request.json"],
                     ["cp", "/r/jobs/x/000.wav", "/out/000.wav"]]


def test_setting_falls_back_to_posix_default(tmp_path, monkeypatch):
    from ns_post import tts
    d = tmp_path / "kok"
    d.mkdir()
    cfg = {"tts_model": {"env_dir": "NS_KOK_T", "default_dir": "/nonexistent/kok", "default_dir_posix": str(d)}}
    monkeypatch.delenv("NS_KOK_T", raising=False)
    monkeypatch.setattr(tts.os, "name", "posix")
    assert tts._setting(cfg, "tts_model", "env_dir", "default_dir") == str(d)
    monkeypatch.setattr(tts.os, "name", "nt")
    assert tts._setting(cfg, "tts_model", "env_dir", "default_dir") is None   # 笔记本不误用 Linux 路径


def test_voices_json_has_server_paths_matching_setup_script():
    setup = (ROOT / "tools" / "voice10" / "speech_setup.sh").read_text(encoding="utf-8")
    for sec, key in (("speech_python", "default_posix"), ("tts_model", "default_dir_posix"), ("asr_model", "default_dir_posix")):
        v = VOICES[sec][key]
        assert v.startswith("/root/work/fredw/speech/"), v
        assert v.replace("/root/work/fredw/speech", "$S").replace("$S/models", "$M").split("/")[-1] in setup


def test_kokoro_model_only_needed_for_kokoro_speakers(tmp_path):
    """K-EDT-022：series10 全是克隆音色 → 服务器没下 Kokoro 也能合成；有 Kokoro 音色的说话人才要求模型目录。"""
    from ns_post.tts import KokoroBackend, TtsUnavailable, Voice, tts_preflight
    exe = tmp_path / "py.exe"
    exe.write_bytes(b"")
    (tmp_path / "sv").mkdir()
    cfg = {"speech_python": {"default": str(exe)}, "asr_model": {"default_dir": str(tmp_path / "sv")},
           "tts_model": {"default_dir": str(tmp_path / "nope")},
           "characters": {"old": {"engine": "kokoro", "sid": 3}}}
    assert tts_preflight(cfg, speakers=[], root=tmp_path) == []
    assert any("tts_model" in m for m in tts_preflight(cfg, speakers=["old"], root=tmp_path))
    kb = KokoroBackend(cfg)                     # 构造不再因为没有 Kokoro 模型就失败
    kb.synthesize([])
    import pytest
    with pytest.raises(TtsUnavailable):
        kb.synthesize([("你好", Voice("old", 3), tmp_path / "a.wav")])


def test_local_hosts_and_gpus_by_host(monkeypatch):
    """总调度方案 (b)：gpu33 自装 CosyVoice3、本机合成走 CPU（GPU2 坏卡、0/1/3 出片道）；gpu36 仍用 GPU2。"""
    from ns_post import tts
    rt = VOICES["remote_tts"]
    assert set(rt["local_hosts"]) == {"gpu33", "gpu36"} and rt["gpus_by_host"]["gpu33"] == []
    monkeypatch.delenv("NS_TTS_REMOTE_LOCAL", raising=False)
    monkeypatch.setenv("OFFLINE_SELF", "gpu33")
    assert tts.remote_is_local(rt) and tts.remote_gpus(rt) == []
    monkeypatch.setenv("OFFLINE_SELF", "gpu36")
    assert tts.remote_is_local(rt) and tts.remote_gpus(rt) == [2]
    monkeypatch.delenv("OFFLINE_SELF")
    assert not tts.remote_is_local(rt) and tts.remote_gpus(rt) == list(rt["gpus"])   # 笔记本：ssh gpu36


def test_cosy_setup_dry_run(tmp_path):
    """cosy_setup.sh install 按锁文件装、可重复执行；缺锁文件直接停（不瞎装）。"""
    import os
    import shutil
    import subprocess
    import pytest
    bash = shutil.which("bash")
    if not bash:
        pytest.skip("no bash")
    lock, binp = tmp_path / "lock", tmp_path / "bin"
    lock.mkdir()
    binp.mkdir()
    (lock / "python_version.txt").write_text("3.12.4\n")
    (lock / "venv_freeze.txt").write_text("torch==2.3.1+cu121\nfoo @ file:///x\nnumpy==1.26.4\n")
    (lock / "overlay_freeze.txt").write_text("transformers==4.51.3\n")
    (lock / "cosy_commit.txt").write_text("abc123\n")
    stub = binp / "python3.12"
    stub.write_text("#!/bin/sh\n")
    stub.chmod(0o755)
    script = (ROOT / "tools" / "voice10" / "cosy_setup.sh").as_posix()

    def sh(lockdir):
        env = {**os.environ, "DRY": "1", "COSY_BASE": (tmp_path / "base").as_posix(),
               "PATH": binp.as_posix() + os.pathsep + os.environ.get("PATH", "")}
        return subprocess.run([bash, script, "install", Path(lockdir).as_posix()], capture_output=True, text=True,
                              encoding="utf-8", errors="replace", env=env, timeout=60)
    r = sh(lock)
    assert r.returncode == 0, r.stdout + r.stderr
    out = r.stdout
    assert "whl/cu121" in out and "transformers==4.51.3" in out and "git checkout -q abc123" in out
    assert "29e01c4e8d000f4bcd70751be16fa94bf3d85a18" in out and "hf-mirror.com" in out
    assert "file:///x" not in out
    r2 = sh(tmp_path / "nolock")
    assert r2.returncode == 1 and "缺锁文件" in r2.stdout
