"""fredw-92/ND：资产生成 gen-jobs 收 preset / params / label（只增不改）；@identity = 人物身份 LoRA + 触发词放最前。"""
from __future__ import annotations

from tests.test_ref_switch_w5 import FakeComfy, _wait, env, script  # noqa: F401  (fixtures)
from ns_api import jobs as J
from ns_api import asset_edit as AED


def _ident(monkeypatch):
    monkeypatch.setattr(AED, "identity_loras", lambda asset: [{"file": "lin_wan_qi_v1.safetensors", "strength": 0.8,
                                                               "trigger": "lnwan_qi"}] if asset.get("character") == "lin_wan" else [])


def test_gen_job_preset_c_identity_lora_and_label(env, monkeypatch):
    c, store, root = env
    fc = FakeComfy()
    monkeypatch.setattr(J, "client_factory", lambda gpu: fc)
    _ident(monkeypatch)
    r = c.post("/api/assets/lin_wan/gen-jobs", json={"prompt": "原话", "preset": "c_turbo_texture", "gpu": 0,
                                                    "label": "候选·待复审", "seed": 7})
    assert r.status_code == 200, r.text
    job = _wait(c, r.json()["job_id"])
    assert job["state"] == "done", job
    wf = fc.submitted[0]
    assert wf["20"]["inputs"]["prompt"] == "lnwan_qi, 原话"                 # 触发词最前，其余原样
    loras = {n["inputs"]["lora_name"]: n["inputs"]["strength_model"] for n in wf.values()
             if n.get("class_type") == "LoraLoaderModelOnly"}
    assert loras.get("lin_wan_qi_v1.safetensors") == 0.6                     # 预设 C 的 @identity 强度
    assert "krea2_film_texture_qwen21.safetensors" in loras
    rec = job["result"]
    assert rec["label"] == "候选·待复审" and rec["preset"] == "c_turbo_texture"
    assert rec["effective"]["width"] == 768 and rec["effective"]["height"] == 1344 and rec["size"] == [768, 1344]


def test_gen_job_no_preset_is_unchanged_and_bad_params_422(env, monkeypatch):
    c, store, root = env
    fc = FakeComfy()
    monkeypatch.setattr(J, "client_factory", lambda gpu: fc)
    _ident(monkeypatch)
    r = c.post("/api/assets/lin_wan/gen-jobs", json={"prompt": "原话", "gpu": 0})
    job = _wait(c, r.json()["job_id"])
    wf = fc.submitted[0]
    assert wf["20"]["inputs"]["prompt"] == "原话"
    assert not any(n.get("class_type") == "LoraLoaderModelOnly" for n in wf.values())
    assert "label" not in job["result"] and "preset" not in job["result"]
    assert c.post("/api/assets/lin_wan/gen-jobs", json={"prompt": "x", "preset": "nope"}).status_code == 422
    assert c.post("/api/assets/lin_wan/gen-jobs", json={"prompt": "x", "params": {"bogus": 1}}).status_code == 422
    # 宽高覆盖（三视图横幅）
    r = c.post("/api/assets/lin_wan/gen-jobs", json={"prompt": "x", "preset": "c_turbo_texture", "gpu": 0,
                                                    "width": 1344, "height": 768})
    job = _wait(c, r.json()["job_id"])
    assert job["result"]["effective"]["width"] == 1344
