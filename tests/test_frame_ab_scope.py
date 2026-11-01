"""scope=ab 实验图（RESEARCH 11-01，总调度 fredw-2b 方案 ②）：走唯一出图路径的同一套作业 / preflight / 图 / 后处理，
但不写 takes.json、不进 auto_current / rescore / 契约账本，产物只在 data/ab/<实验>/。纯 CPU，假 ComfyUI。"""
import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in ("services/agent", "packages/schema", "services/render_router", "services/api", "tools/pipeline"):
    if str(ROOT / p) not in sys.path:
        sys.path.insert(0, str(ROOT / p))

from ns_render import pipeline as P  # noqa: E402
from ns_render import unified_frame as UF  # noqa: E402
from ns_schema.script import ScriptImport  # noqa: E402

SCRIPT = ROOT / "data" / "import" / "script_v2.json"
pytestmark = pytest.mark.skipif(not SCRIPT.exists(), reason="系统剧本不在本机")
SHOT = "ep01-S1"
SUFFIX_WORD = "焦点锐利"


def _png(p: Path):
    from PIL import Image
    p.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (1152, 2016), (120, 110, 100)).save(p)


class Fake:
    base = "http://127.0.0.1:18189"

    def __init__(self):
        self.workflows = []
        self.ns_tag = None

    def upload_image(self, path, subfolder="ns_final"):
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
    calls = {"add_take": 0, "pf_write": 0, "postflight": 0}
    monkeypatch.setattr(P, "_add_take", lambda *a, **k: calls.__setitem__("add_take", calls["add_take"] + 1))
    monkeypatch.setattr(UF, "_pf_write", lambda *a, **k: calls.__setitem__("pf_write", calls["pf_write"] + 1))
    monkeypatch.setattr(UF, "_postflight", lambda *a, **k: calls.__setitem__("postflight", calls["postflight"] + 1) or {"ok": None})
    script = ScriptImport.model_validate(json.loads(SCRIPT.read_text(encoding="utf-8")))
    return script, data, calls


def _prompt_nodes(wf):
    return [n["inputs"].get("prompt") for n in wf.values() if "TextEncodeQwenImage" in n.get("class_type", "")]


def test_ab_render_never_touches_takes_or_contract_ledger(env):
    script, data, calls = env
    fake = Fake()
    rec = UF.render_ab(fake, script, SHOT, experiment="realism_ab", tier="g1", seed=7,
                       prompt_edits=[[SUFFIX_WORD, "光从侧前方落在脸颊上"]], tag={"agent": "RESEARCH"})
    assert calls == {"add_take": 0, "pf_write": 0, "postflight": 0}
    assert not list((data / "renders").rglob("takes.json"))                  # 生产版本表一个都没建
    assert rec["scope"] == "ab" and rec["file"].startswith("ab/realism_ab/ep01-S1/")
    assert (data / rec["file"]).exists() and (data / rec["raw_file"]).exists()
    lines = (data / "ab" / "realism_ab" / "takes.jsonl").read_text(encoding="utf-8").splitlines()
    assert json.loads(lines[-1])["id"] == rec["id"]
    sent = _prompt_nodes(fake.workflows[0])[0]
    assert SUFFIX_WORD not in sent and "光从侧前方落在脸颊上" in sent    # 改写真的进了送模型的提示词
    assert fake.ns_tag == {"agent": "RESEARCH"}


def test_ab_lora_override_reaches_graph(env):
    script, _data, _calls = env
    fake = Fake()
    rec = UF.render_ab(fake, script, SHOT, experiment="realism_ab", tier="g2", seed=7,
                       overrides={"loras": [{"name": "civitai/niceasians_qwen21.safetensors", "strength": 0.6}]})
    names = [n["inputs"].get("lora_name") for n in fake.workflows[0].values() if "Lora" in n.get("class_type", "")]
    assert "civitai/niceasians_qwen21.safetensors" in names
    assert "krea2_film_texture_qwen21.safetensors" not in names
    assert rec["overrides"]["loras"][0]["strength"] == 0.6


def test_ab_bad_edit_and_bad_names_fail_loudly(env):
    script, _data, _calls = env
    with pytest.raises(ValueError):
        UF.render_ab(Fake(), script, SHOT, experiment="realism_ab", tier="g1", prompt_edits=[["不存在的原文xyz", "a"]])
    with pytest.raises(ValueError):
        UF.render_ab(Fake(), script, SHOT, experiment="../renders", tier="g1")
    with pytest.raises(ValueError):
        UF.render_ab(Fake(), script, SHOT, experiment="realism_ab", tier="G 1")


def test_production_graph_unchanged_without_overrides(env):
    """默认参数不变：不传 overrides 的 build_graph 与改动前同一套预设（frame_v9，krea2 0.5）"""
    script, _data, _calls = env
    from ns_agent import frame_job as FJ
    ep, shot = P.find_shot(script, SHOT)
    job = FJ.build_first("series10_v1", ep, shot, script.globals)
    a = UF.build_graph(job, 1, lambda p: Path(p).name, "x")[0]
    b = UF.build_graph(job, 1, lambda p: Path(p).name, "x", overrides=None)[0]
    assert a == b
    names = [n["inputs"].get("lora_name") for n in a.values() if "Lora" in n.get("class_type", "")]
    assert names == ["krea2_film_texture_qwen21.safetensors"]


def test_api_scope_ab_validation_and_yield(monkeypatch):
    from fastapi import HTTPException
    from ns_api import frame_jobs as FJA
    submitted = []
    monkeypatch.setattr(FJA.J, "submit", lambda kind, *a, **k: submitted.append(kind) or {"job_id": "x", "kind": kind})
    base = dict(stage="first", mode="regen", scope="ab", experiment="realism_ab", ab_tier="g1", gpu=1)
    for bad in (dict(stage="last"), dict(mode="instruct", instruction="x"), dict(experiment="A B"), dict(ab_tier=""),
                dict(scope="prod"), dict(prompt_edits=[["only_one"]])):
        with pytest.raises(HTTPException):
            FJA._create_frame_job(SHOT, FJA.FrameJobBody(**{**base, **bad}))
    monkeypatch.setattr(FJA, "lane_busy", lambda gpu: True)
    with pytest.raises(HTTPException) as e:
        FJA._create_frame_job(SHOT, FJA.FrameJobBody(**base))
    assert e.value.status_code == 409 and not submitted               # 生产在用这条道 → 让道，不排队
    monkeypatch.setattr(FJA, "lane_busy", lambda gpu: False)
    out = FJA._create_frame_job(SHOT, FJA.FrameJobBody(**base))
    assert submitted == ["frame_ab"] and out["kind"] == "frame_ab"     # 不是 "frame"：list_frame_jobs / 画布看不到
