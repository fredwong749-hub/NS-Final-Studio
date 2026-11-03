"""PROD 11-01（fredw-2b 派）：VIDEO10 离线期间的渲染 / 编排错误逐条修成规则 + 检查。
K-OPS-306 截断首帧不卡整轮；K-OPS-307 找不到人脸模型不拖垮 build_jobs；K-OPS-308 sync 原子写、坏 JSON 不覆盖；
K-OPS-309 合成前查配音解释器 + assemble_failed 自动重试 + 失败不认旧残片；K-OPS-310 ComfyUI 中断不再记 "[]"。"""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
S10 = REPO / "tools" / "series10_video"


def _load(name):
    if str(S10) not in sys.path:
        sys.path.insert(0, str(S10))
    spec = importlib.util.spec_from_file_location(f"_t_{name}", S10 / f"{name}.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _png(p: Path, truncate=False):
    from PIL import Image
    p.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (64, 64), (120, 30, 200)).save(p, "PNG")
    if truncate:
        b = p.read_bytes()
        p.write_bytes(b[: len(b) // 2])


def _take(root: Path, ep, s, fname):
    d = root / "data" / "renders" / ep / s
    d.mkdir(parents=True, exist_ok=True)
    (d / "takes.json").write_text(json.dumps({"active": {"image": 1}, "takes": [
        {"stage": "image", "n": 1, "file": fname,
         "postflight": {"ok": True, "items": [{"id": "Q10", "status": "pass"}, {"id": "Q9", "status": "pass"}]}}]}), encoding="utf-8")   # D-VQA-01：首帧要过第 8 步验收才进视频；MERGE-VID-O：video_requires_q9=true 后还要过 Q9


def test_passed_frames_skips_truncated_png(tmp_path, monkeypatch):
    B = _load("build_jobs")
    monkeypatch.setattr(B, "ROOT", tmp_path)
    monkeypatch.setattr(B, "VID", tmp_path / "vid")
    monkeypatch.setattr(B, "FRAMES_OK", tmp_path / "vid" / "frames_ok.json")
    _png(tmp_path / "data" / "renders" / "ep01" / "S1" / "a.png")
    _png(tmp_path / "data" / "renders" / "ep01" / "S2" / "b.png", truncate=True)
    _take(tmp_path, "ep01", "S1", "renders/ep01/S1/a.png")
    _take(tmp_path, "ep01", "S2", "renders/ep01/S2/b.png")
    out = B.passed_frames()          # 以前：OSError('image file is truncated') 整轮崩
    assert "ep01-S1" in out and out["ep01-S1"]["file"].endswith(".jpg")
    assert "ep01-S2" not in out
    assert not list((tmp_path / "vid" / "inputs").glob("ep01-S2_*"))   # 半张图不留 JPEG


def test_alt_crops_without_face_models_keeps_cached(tmp_path, monkeypatch):
    B = _load("build_jobs")
    from ns_qc import face as QF
    monkeypatch.setattr(B, "ROOT", tmp_path)
    monkeypatch.setattr(B, "VID", tmp_path / "vid")
    monkeypatch.setattr(B, "ALT_SHEET", {"a": "x.png", "b": "y.png"})
    monkeypatch.setattr(QF, "find_models", lambda root: None)
    (tmp_path / "vid" / "refs_alt").mkdir(parents=True)
    (tmp_path / "vid" / "refs_alt" / "a_face_alt.png").write_bytes(b"x")
    out = B.alt_crops()              # 以前：FaceModels(*None) TypeError，build_jobs rc=1、全部集派不出
    assert out == {"a": "vid/refs_alt/a_face_alt.png"}


def test_sync_write_atomic_rejects_bad_json(tmp_path):
    S = _load("sync")
    p = tmp_path / "state_gpu33.json"
    S.write_atomic(p, b'{"shots": {"a": 1}}')
    assert json.loads(p.read_text()) == {"shots": {"a": 1}}
    S.write_atomic(p, b'{"shots": {"a": 1,')          # 服务器端读到半截 → 不覆盖本地好的
    assert json.loads(p.read_text()) == {"shots": {"a": 1}}
    assert not list(tmp_path.glob("*.part"))
    S.write_atomic(tmp_path / "x.jpg", b"\xff\xd8")
    assert (tmp_path / "x.jpg").read_bytes() == b"\xff\xd8"


def test_tts_missing_and_retry_assembly(tmp_path, monkeypatch):
    N = _load("night")
    monkeypatch.setattr(N, "LOG", tmp_path / "night.log")
    cfg = tmp_path / "config" / "voices.json"
    cfg.parent.mkdir(parents=True)
    (tmp_path / "kok").mkdir()
    (tmp_path / "sv").mkdir()   # VOICE10 11-01：tts_missing 改调 tts_preflight，模型目录也查（K-EDT-021）
    cfg.write_text(json.dumps({"speech_python": {"env": "NS_TTS_PYTHON_T", "default": str(tmp_path / "nope.exe")},
                               "tts_model": {"default_dir": str(tmp_path / "kok")},
                               "asr_model": {"default_dir": str(tmp_path / "sv")}}), encoding="utf-8")
    monkeypatch.setattr(N, "ROOT", tmp_path)
    monkeypatch.delenv("NS_TTS_PYTHON_T", raising=False)
    assert "NS_TTS_PYTHON_T" in N.tts_missing()
    st = {"eps": {"4": {"status": "assemble_failed", "finalized": 0, "assemble_err": "TtsUnavailable"},
                  "5": {"status": "assemble_failed", "finalized": 9e12},            # 刚失败 → 先不重试
                  "6": {"status": "assemble_failed", "finalized": 0, "assemble_retries": 3},   # 用完 3 次 → 停
                  "7": {"status": "hold_tts"}}}
    N.retry_assembly(st)
    assert st["eps"]["4"]["status"] == "rendering" and st["eps"]["4"]["assemble_retries"] == 1
    assert st["eps"]["5"]["status"] == "assemble_failed"
    assert st["eps"]["6"]["status"] == "assemble_failed"
    assert st["eps"]["7"]["status"] == "hold_tts"                    # 解释器还没到位
    exe = tmp_path / "py.exe"
    exe.write_bytes(b"")
    monkeypatch.setenv("NS_TTS_PYTHON_T", str(exe))
    assert N.tts_missing() is None
    N.retry_assembly(st)
    assert st["eps"]["7"]["status"] == "rendering"


def test_finalize_holds_without_tts(tmp_path, monkeypatch):
    N = _load("night")
    monkeypatch.setattr(N, "LOG", tmp_path / "night.log")
    monkeypatch.setattr(N, "voices_ok", lambda: True)
    monkeypatch.setattr(N, "tts_missing", lambda: "没有配音解释器")
    called = []
    monkeypatch.setattr(N, "ssh", lambda *a, **k: called.append(a) or "")
    st = {"eps": {"4": {"status": "rendering", "assembled_n": 0}}}
    N.finalize(4, "gpu36", st, {})
    assert st["eps"]["4"]["status"] == "hold_tts" and not called
    assert st["eps"]["4"].get("assembled_n") == 0                    # 不耗版本号


def test_vidgen_interrupted_is_labelled(monkeypatch):
    V = _load("vidgen")
    hist = {"p1": {"status": {"status_str": "error", "completed": False, "messages": [
        ["execution_start", {"timestamp": 1000}],
        ["execution_interrupted", {"timestamp": 5000, "node_type": "KSampler"}]]}, "outputs": {}}}
    lane = V.Lane.__new__(V.Lane) if hasattr(V, "Lane") else None
    if lane is None:
        pytest.skip("vidgen 没有 Lane 类")
    lane.port = 1
    monkeypatch.setattr(V, "api", lambda port, path, *a, **k: json.dumps(hist))
    r = lane.result("p1")
    assert r["interrupted"] and "interrupted" in r["error"] and "KSampler" in r["error"] and r["gpu_s"] == 4.0


def test_deploy_build_tar_skips_truncated_images(tmp_path, monkeypatch):
    import io
    import tarfile
    D = _load("deploy")
    monkeypatch.setattr(D, "ROOT", tmp_path)
    _png(tmp_path / "good.png")
    _png(tmp_path / "bad.png", truncate=True)
    (tmp_path / "jobs.json").write_text("{}", encoding="utf-8")
    blob = D.build_tar(["good.png", "bad.png", "jobs.json"], [])
    names = tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz").getnames()
    assert "good.png" in names and "jobs.json" in names and "bad.png" not in names


def _mp4(p: Path, w, h):
    import shutil
    import subprocess
    p.parent.mkdir(parents=True, exist_ok=True)
    ff = shutil.which("ffmpeg")
    if not ff:
        pytest.skip("没有 ffmpeg")
    subprocess.run([ff, "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c=gray:s={w}x{h}:d=0.5:r=24",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(p)], check=True)


def test_assembly_never_uses_proxy(tmp_path, monkeypatch):
    """K-EDT-V10：成片只用原片 / 放大版；代理不进成片；原片缺或分辨率不高于代理 → bad"""
    N = _load("night")
    monkeypatch.setattr(N, "ROOT", tmp_path)
    _mp4(tmp_path / "clips/ep01/a.mp4", 768, 1344)
    _mp4(tmp_path / "ep/ep01-S1.mp4", 540, 960)
    _mp4(tmp_path / "ep/ep01-S2.mp4", 540, 960)
    _mp4(tmp_path / "clips/ep01/low.mp4", 360, 640)
    _mp4(tmp_path / "ep/ep01-S3.mp4", 540, 960)
    man = {"shots": [
        {"shot": "ep01-S1", "index": 1, "proxy": "ep/ep01-S1.mp4", "source": "clips/ep01/a.mp4"},
        {"shot": "ep01-S2", "index": 2, "proxy": "ep/ep01-S2.mp4", "source": "clips/ep01/missing.mp4"},
        {"shot": "ep01-S3", "index": 3, "proxy": "ep/ep01-S3.mp4", "source": "clips/ep01/low.mp4"},
        {"shot": "ep01-S4", "index": 4, "excluded": "尽力版"}]}
    tl, bad = N.assembly_sources(man)
    assert [s["file"] for s in tl["shots"]] == ["clips/ep01/a.mp4"]
    assert len(bad) == 2 and "ep01-S2" in bad[0] and "ep01-S3" in bad[1]
    assert not any("ep/" in s["file"] for s in tl["shots"])
    _mp4(tmp_path / "clips/ep01/a_sr1080.mp4", 1080, 1890)
    tl, _ = N.assembly_sources(man)
    assert tl["shots"][0]["file"] == "clips/ep01/a_sr1080.mp4" and "放大版 1080×1890" in tl["shots"][0]["origin"]


def test_finalize_waits_for_originals_without_redoing_proxies(tmp_path, monkeypatch):
    N = _load("night")
    vid = tmp_path / "vid"
    monkeypatch.setattr(N, "ROOT", tmp_path)
    monkeypatch.setattr(N, "VID", vid)
    monkeypatch.setattr(N, "LOG", tmp_path / "night.log")
    monkeypatch.setattr(N, "voices_ok", lambda: True)
    monkeypatch.setattr(N, "tts_missing", lambda: None)
    called = []
    monkeypatch.setattr(N, "ssh", lambda *a, **k: called.append(a) or "")
    (vid / "episodes" / "ep04").mkdir(parents=True)
    (vid / "episodes" / "ep04" / "manifest.json").write_text(json.dumps({"t": 100, "shots": [
        {"shot": "ep04-S1", "index": 1, "proxy": "p.mp4", "source": "clips/ep04/missing.mp4"}]}), encoding="utf-8")
    (vid / "state_gpu36.json").write_text(json.dumps({"shots": {"ep04-S1": {"renders": [{"t_done": 50}]}}}), encoding="utf-8")
    st = {"eps": {"4": {"status": "rendering", "assembled_n": 0}}}
    N.finalize(4, "gpu36", st, {})
    assert not called and st["eps"]["4"]["status"] == "rendering" and "等原片 1 条" in st["eps"]["4"]["wait_msg"]


def test_deploy_push_aborts_when_probe_fails(monkeypatch):
    import subprocess
    D = _load("deploy")
    calls = []

    def fake_ssh(host, cmd, data=None, timeout=900):
        calls.append(cmd)
        return subprocess.CompletedProcess([], 255, b"", b"Connection timed out during banner exchange")
    monkeypatch.setattr(D, "ssh", fake_ssh)
    monkeypatch.setattr(D, "build_tar", lambda *a, **k: (_ for _ in ()).throw(AssertionError("不该打包")))
    assert D.push("gpu33") is False and len(calls) == 1


# ---- W5（总调度 11-01，CONSENT REFLOCK / ITERAUDIT -> VIDEO10）：手部局部大特写被拉成人像 ----
IMG_S3 = ("大特写，俯拍机位，阿岚戴皮手套的手握着记号笔，笔尖点在林晚胸口偏左的皮肤上，另一只手套按在林晚肩头，"
          "林晚的黑色漆皮束腰边缘与锁骨入画")
IMG_S8 = "大特写，俯拍，林晚的右手在暖黄台灯下攥着白色续约单，纸面被捏出数道折痕，指尖指节泛白"
LOCK = "【林晚】22岁中国成年女性，蓝发及腰，齐刘海，G罩杯，手指甲为5厘米超长透明水晶甲，镶满钻石饰品"


def _fr():
    sys.path.insert(0, str(REPO / "services" / "agent"))
    from ns_agent import framing as FR
    return FR


def test_w5_scope_expands_to_hand_and_neck_and_keeps_hair():
    FR = _fr()
    assert FR.part_name(IMG_S3) == "手与肩颈" and FR.part_name(IMG_S8) == "手"
    lead = FR.closeup_lead("大特写", "part", IMG_S3)
    assert "只有手与肩颈" in lead and "只有手这" not in lead and "不" not in lead
    lk = FR.part_lock(LOCK, FR.part_name(IMG_S3))
    assert "蓝发" in lk and "水晶甲" in lk and "成年" in lk and "齐刘海" not in lk   # 发色保留，发型 / 身材不放
    assert "蓝发" not in FR.part_lock(LOCK, "手")                                    # 纯手局部：头发不入画，不加


def test_w5_hand_crop_excludes_torso(tmp_path, monkeypatch):
    from PIL import Image, ImageDraw
    sys.path.insert(0, str(REPO / "services" / "agent"))
    from ns_agent import asset_refs as A
    im = Image.new("RGB", (300, 600), (255, 255, 255))
    d = ImageDraw.Draw(im)
    d.rectangle([110, 20, 190, 580], fill=(20, 20, 20))      # 躯干 / 围裙（整列实心）
    d.rectangle([60, 200, 90, 380], fill=(30, 30, 30))       # 左臂 + 手
    d.rectangle([210, 200, 240, 380], fill=(30, 30, 30))     # 右臂 + 手
    pair = A._hand_pair(im, A._person_box(im, 4, 296))
    p = tmp_path / "pair.png"
    pair.save(p)
    assert A.torso_share(p) <= A.HAND_TORSO_MAX
    old = im.crop((60, 20 + int(0.38 * 560), 240, 20 + int(0.62 * 560)))   # 旧裁法：外框横向整条
    q = tmp_path / "old.png"
    old.save(q)
    assert A.torso_share(q) > A.HAND_TORSO_MAX


def test_w5_writer_lint_hand_vs_neck():
    import types
    spec = importlib.util.spec_from_file_location("_wl", REPO / "tools" / "qa" / "writer_lints.py")
    WL = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(WL)
    sh = types.SimpleNamespace(cast=[], index=3, duration=4, voiceover=None, dialogue=[], motion_prompt="", extras={})
    ep = types.SimpleNamespace(looks=[])
    ids = lambda img: [i["rule_id"] for i in WL.check_shot(sh, ep, img, "大特写")]
    assert "QW-W10" in ids(IMG_S3)
    assert "QW-W10" not in ids(IMG_S8)
    assert "QW-W10" not in ids("大特写，林晚的眼睛看向肩头的手")     # 写到脸 = 脸部特写，不归这条
