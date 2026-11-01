"""K-REN-134 全系统只有一条出图路径（总调度 2026-11-01 P0）。

项目方原话：“你现在生成的人物不是林晚真实的形象……肯定有 bug……修复 reference 图片的 bug”。查实画布“重出首帧”走旧换脸式两步
（图1 = 旧首帧构图，图2 = 旧母版裁切 master_face_b8e7b00b6756）。这里锁死：画布重出提交的 ComfyUI 图 = 唯一构建函数
（ns_agent.frame_job.build_first → ns_render.unified_frame.build_graph）的输出，逐字段一致。纯 CPU，假 ComfyUI。
"""
import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in ("services/agent", "packages/schema", "services/render_router", "tools/pipeline"):
    if str(ROOT / p) not in sys.path:
        sys.path.insert(0, str(ROOT / p))

from ns_render import frame_edit as FE  # noqa: E402
from ns_render import pipeline as P  # noqa: E402
from ns_render import unified_frame as UF  # noqa: E402
from ns_schema.script import ScriptImport  # noqa: E402

SCRIPT = ROOT / "data" / "import" / "script_v2.json"
pytestmark = pytest.mark.skipif(not SCRIPT.exists(), reason="系统剧本不在本机")
SHOT = "ep01-S1"


def _png(p: Path):
    from PIL import Image
    p.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (1152, 2016), (120, 110, 100)).save(p)


class Fake:
    base = "http://127.0.0.1:18189"

    def __init__(self):
        self.workflows, self.uploads = [], []

    def upload_image(self, path, subfolder="ns_final"):
        self.uploads.append(str(path))
        return f"{subfolder}/{Path(path).name}"

    def run(self, wf, timeout_s):
        self.workflows.append(copy.deepcopy(wf))
        return {"outputs": {"9": {"images": [{"filename": "x.png", "subfolder": "", "type": "output"}]}}}, 1.0

    output_files = staticmethod(P.ComfyClient.output_files)

    def download(self, item, dest):
        _png(Path(dest))
        return dest


@pytest.fixture
def env(tmp_path, monkeypatch):
    data = tmp_path / "data"
    (data / "renders").mkdir(parents=True)
    monkeypatch.setattr(P, "DATA", data)
    monkeypatch.setattr(P, "RENDERS", data / "renders")
    monkeypatch.setattr(UF, "_postflight", lambda final_rel, job, host: {"ok": None, "skipped": "test"})
    # 11-01 事故：后台 postflight 线程活过了夹具，把临时数据写进真实 data/renders/ep01/S1/takes.json。测试里线程一律同步跑完
    monkeypatch.setattr(UF, "_spawn", lambda fn, args, name: fn(*args))
    return ScriptImport.model_validate(json.loads(SCRIPT.read_text(encoding="utf-8")))


def test_script_maps_to_asset_project(env):
    assert UF.project_for(env) == "series10_v1"


def test_canvas_regen_graph_equals_unified_builder(env):
    from ns_agent import frame_job as FJ
    fake = Fake()
    t = FE.regen(fake, env, SHOT, "image", seed=4242)
    assert len(fake.workflows) == 1                          # 一张图，没有“构图 → 换脸”两步
    ep, shot = P.find_shot(env, SHOT)
    job = FJ.build_first("series10_v1", ep, shot, env.globals)
    want, _eff, _sent = UF.build_graph(job, 4242, lambda p: f"ns_final/refs/{Path(p).name}", f"ns_final/{SHOT}_image_v9")
    assert fake.workflows[0] == want                         # 逐字段一致
    prompt = next(n["inputs"]["prompt"] for n in want.values() if "TextEncodeQwenImage" in n["class_type"])
    assert "本镜头的画面构图" not in prompt and "换成图2" not in prompt
    assert prompt.startswith("图1是林晚的脸部参考")
    assert [Path(u).name for u in fake.uploads] == [Path(r).name for r in job["refs"]]
    _man = json.loads((Path(__file__).resolve().parents[1] / "data/assets/identity_refs/manifest.json").read_text(encoding="utf-8"))
    assert Path(job["refs"][0]).name == Path(_man["chars"]["lin_wan"]["file"]).name   # 项目方登记的身份脸（L-086：A-s202 高清裁切），不是旧母版 master_face
    assert "master_face" not in json.dumps(want) and "lin_wan_qi" not in json.dumps(want)
    assert t["path"].startswith("unified_frame") and t["contract"]["preflight"]["ok"]


def test_prompt_override_keeps_slot_lines(env):
    fake = Fake()
    FE.regen(fake, env, SHOT, "image", seed=1, prompt="特写，林晚抬眼")
    p = next(n["inputs"]["prompt"] for n in fake.workflows[0].values() if "TextEncodeQwenImage" in n["class_type"])
    assert p.startswith("图1是林晚的脸部参考") and "特写，林晚抬眼" in p


def test_registered_size_equals_requested_size(env):
    """11-01 bug：frame_v9 出图 1.5× 放大 → lanczos 缩回 768×1344 → USM；登记的这一版文件尺寸必须等于 params 记的交付尺寸，
    不能被判“坏图：尺寸不符”，且过检查才设为当前"""
    from PIL import Image
    from ns_render import image_check as IC
    fake = Fake()
    t = FE.regen(fake, env, SHOT, "image", seed=99)
    eff = t["params"]["effective"]
    w, h = Image.open(P.DATA / t["file"]).size
    assert (w, h) == (eff["width"], eff["height"]) == (768, 1344)
    assert t["params"]["post"]["rendered_size"] == [1152, 2016] and t["params"]["post"]["file"] == t["file"]
    assert IC.check_take(t, P.DATA) is None and not t.get("bad")
    # G3（项目方 11-01，PRODUCER）：过坏图检查还不够——契约（postflight）过了才由 auto_current.on_contract 设为当前
    assert (P.load_takes(SHOT).get("active") or {}).get("image") != t["n"] or         (t.get("contract") or {}).get("postflight", {}).get("ok") is True


def test_postflight_survives_process_death(env, monkeypatch):
    """进程在 postflight 算到一半死掉（只落了 pending 标记）→ 重启后的扫描把结果补上；再扫一次不重算（幂等）"""
    calls = []
    monkeypatch.setattr(UF, "_postflight", lambda final_rel, job, host: calls.append(final_rel) or
                        {"ok": True, "items": [{"id": "Q1", "status": "pass"}], "blocking": []})
    monkeypatch.setattr(UF, "_spawn", lambda fn, args, name: None)   # “线程没跑完就死了”
    fake = Fake()
    t = FE.regen(fake, env, SHOT, "image", seed=5)
    pf = P.load_takes(SHOT)["takes"][-1]["contract"]["postflight"]
    assert pf["status"] == "pending" and pf["ok"] is None and not calls
    assert (SHOT, "image", t["n"]) in UF.pending_takes()
    done = UF.sweep_once()                                   # “重启后”扫描
    assert (SHOT, "image", t["n"]) in done and len(calls) == 1
    pf = P.load_takes(SHOT)["takes"][-1]["contract"]["postflight"]
    assert pf["status"] == "done" and pf["ok"] is True
    assert UF.sweep_once() == [] and len(calls) == 1         # 幂等


def test_postflight_failure_retries_then_errors(env, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("ssh down")
    monkeypatch.setattr(UF, "_postflight", boom)
    monkeypatch.setattr(UF, "_spawn", lambda fn, args, name: None)
    t = FE.regen(Fake(), env, SHOT, "image", seed=6)
    for _ in range(UF.PF_MAX_ATTEMPTS):
        UF.sweep_once()
    pf = P.load_takes(SHOT)["takes"][-1]["contract"]["postflight"]
    assert pf["status"] == "error" and pf["ok"] is False and pf["attempts"] == UF.PF_MAX_ATTEMPTS
    assert (SHOT, "image", t["n"]) not in UF.pending_takes()



def test_no_background_write_into_real_data(env, tmp_path):
    """夹具结束后不得有后台线程写真实 data/renders（11-01 事故回归）"""
    import threading
    real = Path(__file__).resolve().parents[1] / "data" / "renders" / "ep01" / "S1" / "takes.json"
    before = real.stat().st_mtime if real.exists() else None
    FE.regen(Fake(), env, SHOT, "image", seed=77)
    assert not [t for t in threading.enumerate() if t.name.startswith("postflight-")]
    assert (real.stat().st_mtime if real.exists() else None) == before
