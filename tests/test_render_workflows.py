"""工作流构建器的图结构测试（不连 ComfyUI、不用 GPU）。"""
from dataclasses import replace

import pytest

from ns_render import pipeline as P
from ns_render import workflows as W


def _links_ok(wf: dict):
    """所有 [节点, 输出] 引用都指向图里存在的节点"""
    for nid, node in wf.items():
        assert "class_type" in node and "inputs" in node, nid
        for key, v in node["inputs"].items():
            if isinstance(v, list) and len(v) == 2 and isinstance(v[0], str) and isinstance(v[1], int):
                assert v[0] in wf, f"{nid}.{key} -> {v[0]} 不存在"


def _by_class(wf: dict, cls: str) -> list[dict]:
    return [n for n in wf.values() if n["class_type"] == cls]


def test_qwen_t2i_structure():
    wf = W.qwen_t2i("提示词", "负面", 1088, 1920, 42, "ns_final/x")
    _links_ok(wf)
    assert not _by_class(wf, "LoadImage")
    enc = wf["20"]["inputs"]
    assert "images.image_1" not in enc and "vae" not in enc
    assert wf["34"]["inputs"]["width"] == 1088 and wf["34"]["inputs"]["height"] == 1920
    assert wf["35"]["inputs"]["noise_seed"] == 42
    assert wf["37"]["class_type"] == "ManualSigmas" and wf["38"]["inputs"]["cfg"] == 1.0
    assert wf["40"]["inputs"]["latent_image"] == ["34", 0]


def test_qwen_base_model_uses_scheduler_and_cfg():
    m = replace(W.QwenModel(), turbo=False, cfg=2.5, steps=25)
    wf = W.qwen_t2i("p", "n", 1088, 1920, 1, "x", m=m)
    _links_ok(wf)
    assert wf["37"]["class_type"] == "BasicScheduler" and wf["37"]["inputs"]["steps"] == 25
    assert wf["38"]["inputs"]["cfg"] == 2.5


def test_qwen_edit_structure():
    wf = W.qwen_edit("提示词", "负面", "ns_final/refs/abc.png", 1088, 1920, 7, "ns_final/y",
                     loras=[("a.safetensors", 0.8)])
    _links_ok(wf)
    assert wf["101"] == {"class_type": "LoadImage", "inputs": {"image": "ns_final/refs/abc.png"}}
    crop = wf["102"]["inputs"]
    # 参考图裁成画布比例
    assert wf["102"]["class_type"] == "ImageScale"
    assert (crop["width"], crop["height"], crop["crop"]) == (1088, 1920, "center")
    assert crop["image"] == ["101", 0]
    enc = wf["20"]["inputs"]
    assert enc["images.image_1"] == ["102", 0] and enc["vae"] == ["12", 0]
    assert enc["prompt"] == "提示词"
    # 画布尺寸与 t2i 一致，采样从空 latent 开始
    assert wf["34"]["inputs"]["width"] == 1088 and wf["40"]["inputs"]["latent_image"] == ["34", 0]
    # LoRA 串在 UNET 和 cache 之间
    assert wf["60"]["class_type"] == "LoraLoaderModelOnly" and wf["60"]["inputs"]["model"] == ["10", 0]
    assert wf["13"]["inputs"]["model"] == ["60", 0]
    assert wf["90"]["inputs"]["images"] == ["41", 0]


def test_edit_and_t2i_share_the_sampler_core():
    t = W.qwen_t2i("p", "n", 1088, 1920, 1, "x")
    e = W.qwen_edit("p", "n", "r.png", 1088, 1920, 1, "x")
    assert set(e) - set(t) == {"101", "102"}
    for nid in ("10", "11", "12", "13", "35", "36", "37", "38", "40", "41", "90"):
        assert t[nid] == e[nid], nid


def test_h3_fl2va_structure():
    wf = W.h3_fl2va("动作", "ns_final/f.png", 576, 1024, 243, 3, "ns_final/v", last_frame="ns_final/l.png")
    _links_ok(wf)
    h3 = wf["131"]["inputs"]
    assert h3["length"] == 243 and (h3["width"], h3["height"]) == (576, 1024)
    assert h3["first_frame"] == ["200", 0] and h3["last_frame"] == ["201", 0]
    assert wf["125"]["inputs"]["latent_image"] == ["131", 1]
    assert _by_class(wf, "LoraLoaderModelOnly")  # turbo LoRA


@pytest.mark.parametrize("n,expected", [(243, 243), (242, 243), (244, 260), (158, 158), (121, 124), (1, 5)])
def test_snap_frames(n, expected):
    assert P.snap_frames(n) == expected
    assert (P.snap_frames(n) - 5) % 17 == 0


def _compiled(prompt: str):
    return P.CompiledShot(shot_id="ep01-S1", adult=False, adult_reasons=[], image_prompt=prompt,
                          image_negative="", image_loras=[], video_prompt="", video_negative="", video_loras=[])


def test_face_reference_only_for_locked_character():
    assert P.face_reference(_compiled("【林晚】22岁中国成年女性，厨房")) is not None
    assert P.face_reference(_compiled("清晨写字楼旋转门")) is None
    name, path = P.face_reference(_compiled("【林晚】x"))
    assert name == "林晚" and path.name == "lin_wan.png"


def test_face_refs_only_from_owner_supplied_character_folder():
    # 只允许 assets/characters/<角色>/（有来源记录）；assets/linwan/ 来源未确认，禁止使用
    for path in P.CHARACTER_REFS.values():
        rel = path.relative_to(P.ROOT).as_posix()
        assert rel.startswith("assets/characters/"), rel
        assert path.with_suffix(".provenance.json").exists(), rel


# ------------------------------------------------------------------ 参考图来源闸门

def _approval(tmp_path, monkeypatch, cfg):
    f = tmp_path / "face_reference.json"
    if cfg is not None:
        import json
        f.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(P, "FACE_REF_APPROVAL", f)


def _adult(prompt="【林晚】x"):
    c = _compiled(prompt)
    c.adult = True
    return c


@pytest.mark.parametrize("cfg", [None, {"approved_for_adult": False, "approved_by": None, "note": "待确认"},
                                 {"approved_for_adult": True, "approved_by": None},  # 缺批准人也不算
                                 {"approved_for_adult": "true", "approved_by": "x"}])
def test_gate_refuses_adult_until_approved(tmp_path, monkeypatch, cfg):
    _approval(tmp_path, monkeypatch, cfg)
    assert not P.face_ref_approved()
    with pytest.raises(P.ComfyError, match="成人镜头"):
        P.check_face_lock_allowed(_adult())
    P.check_face_lock_allowed(_compiled("【林晚】x"))  # 非成人允许
    monkeypatch.setattr(P, "FACE_LOCK_DEFAULT", True)
    assert P.face_lock_default() is False  # 未批准不作为默认


def test_gate_allows_adult_when_approved(tmp_path, monkeypatch):
    _approval(tmp_path, monkeypatch, {"approved_for_adult": True, "approved_by": "项目方", "note": "ok"})
    P.check_face_lock_allowed(_adult())


class _NoGpuClient:
    def object_info(self):
        return {"LoraLoaderModelOnly": {"input": {"required": {"lora_name": [[]]}}}}

    def upload_image(self, *a, **k):
        raise AssertionError("闸门必须在上传参考图之前拒绝")

    def run(self, *a, **k):
        raise AssertionError("闸门必须在提交之前拒绝")


def test_render_image_refuses_reference_edit_on_adult_shot(tmp_path, monkeypatch):
    _approval(tmp_path, monkeypatch, {"approved_for_adult": False, "approved_by": None})
    monkeypatch.setattr(P, "RENDERS", tmp_path / "renders")   # 沙箱：不受项目归属闸门影响
    monkeypatch.setattr(P, "compile_with_edits", lambda script, shot_id, loras, **k: _adult())
    monkeypatch.setattr(P, "shot_looks_map", lambda shot_id: {})
    monkeypatch.setattr(P, "load_edit", lambda shot_id: P.ShotEdit())
    monkeypatch.setattr(P, "_next_n", lambda shot_id, stage: 1)
    with pytest.raises(P.ComfyError, match="拒绝使用参考编辑"):
        P.render_image(_NoGpuClient(), None, "ep99-S1", face_lock=True)


def test_repo_approval_file_is_well_formed():
    # 批准必须写明由谁、何时批准（项目方 2026-10-30 已确认）
    import json
    cfg = json.loads(P.FACE_REF_APPROVAL.read_text(encoding="utf-8"))
    if cfg.get("approved_for_adult"):
        assert cfg.get("approved_by") and cfg.get("approved_at") and cfg.get("note")


# ------------------------------------------------------------------ 非成人：Base 模型 + 防裸露负面 + 裸露质检

def test_non_adult_model_follows_switch(monkeypatch):
    c = _compiled("清晨写字楼")
    monkeypatch.setattr(P, "NON_ADULT_USE_BASE", False)
    assert P.image_model(c) == P.QWEN_TURBO
    monkeypatch.setattr(P, "NON_ADULT_USE_BASE", True)
    assert P.image_model(c) == P.QWEN_BASE and not P.QWEN_BASE.turbo and P.QWEN_BASE.cfg > 1


def test_non_adult_extra_negative():
    c = _compiled("清晨写字楼")
    c.image_negative = "动漫脸、水印"
    neg = P.image_negative(c)
    assert neg.startswith("动漫脸、水印、")
    for w in P.NON_ADULT_NEGATIVE_EXTRA.split("、"):
        assert w in neg
    assert P.image_negative(replace(c, image_negative=neg)) == neg  # 不重复追加
    a = replace(c, adult=True)
    assert P.image_negative(a) == "动漫脸、水印" and P.image_model(a) == P.QWEN_TURBO


class _FakeClient:
    def __init__(self):
        self.workflows = []

    def object_info(self):
        return {"LoraLoaderModelOnly": {"input": {"required": {"lora_name": [[]]}}}}

    def upload_image(self, *a, **k):
        return "ref.png"

    def run(self, wf, timeout_s):
        self.workflows.append(wf)
        return {"outputs": {"90": {"images": [{"filename": f"x{len(self.workflows)}.png"}]}}}, 1.0

    output_files = staticmethod(P.ComfyClient.output_files)

    def download(self, item, dest):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(item["filename"].encode())
        return dest


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    monkeypatch.setattr(P, "DATA", tmp_path)
    monkeypatch.setattr(P, "RENDERS", tmp_path / "renders")
    monkeypatch.setattr(P, "QC_LOG", tmp_path / "renders" / "qc_log.jsonl")
    monkeypatch.setattr(P, "compile_with_edits", lambda script, shot_id, loras: _compiled("清晨写字楼"))
    return tmp_path


# 单候选、不评分、不调色：等价于旧的“质检不过换种子重抽”流程（假图片字节不能调色）
SIMPLE = {"candidates": 1, "rounds": 3, "score_fn": None, "grade": False}


def _qc_sequence(results):
    it = iter(results)
    return lambda path: {"nudity": next(it), "hits": [], "clip_bare": 0.0}


def test_flagged_takes_are_kept_but_not_activated(sandbox):
    client = _FakeClient()
    take = P.render_image(client, None, "ep99-S1", qc_fn=_qc_sequence([True, True, False]), **SIMPLE)
    data = P.load_takes("ep99-S1")
    assert take.n == 3 and data["active"]["image"] == 3
    assert [t["qc"]["nudity"] for t in data["takes"]] == [True, True, False]
    assert len({t["seed"] for t in data["takes"]}) == 3  # 每次换种子
    assert (P.shot_dir("ep99-S1") / "frame.png").read_bytes() == b"x3.png"
    assert len(P.QC_LOG.read_text(encoding="utf-8").splitlines()) == 2
    # 当前开关选的模型 + 防裸露负面
    wf = client.workflows[0]
    assert wf["10"]["inputs"]["unet_name"] == P.image_model(_compiled("清晨写字楼")).unet
    assert "裸背" in wf["20"]["inputs"]["negative_prompt"]
    with pytest.raises(P.QCRejected):
        P.set_active("ep99-S1", "image", 1)


def test_gives_up_after_retries_without_activating(sandbox):
    with pytest.raises(P.ComfyError, match="裸露质检"):
        P.render_image(_FakeClient(), None, "ep99-S2", qc_fn=_qc_sequence([True] * 3), **SIMPLE)
    data = P.load_takes("ep99-S2")
    assert len(data["takes"]) == SIMPLE["rounds"] and "image" not in data["active"]
    assert not (P.shot_dir("ep99-S2") / "frame.png").exists()


def test_qc_sweep_deactivates_flagged_active_take(sandbox):
    P.render_image(_FakeClient(), None, "ep99-S3", qc_fn=_qc_sequence([False]), **SIMPLE)
    data = P.load_takes("ep99-S3")
    data["takes"][0].pop("qc")  # 模拟没质检过的旧版本
    P._save_takes("ep99-S3", data)
    flagged = P.qc_sweep("ep99-S3", adult=False, qc_fn=_qc_sequence([True]))
    assert [t["n"] for t in flagged] == [1]
    assert "image" not in P.load_takes("ep99-S3")["active"]
    assert not (P.shot_dir("ep99-S3") / "frame.png").exists()
    assert P.qc_sweep("ep99-S3", adult=True, qc_fn=_qc_sequence([])) == []


def test_unavailable_server_is_not_retried(sandbox):
    class Dead(_FakeClient):
        def run(self, wf, timeout_s):
            self.workflows.append(wf)
            raise P.ComfyUnavailable("/prompt: connection refused")
    client = Dead()
    with pytest.raises(P.ComfyUnavailable):
        P.render_image(client, None, "ep99-S4", qc_fn=_qc_sequence([]), **SIMPLE)
    assert len(client.workflows) == 1
    assert not (P.shot_dir("ep99-S4") / "errors.json").exists()
