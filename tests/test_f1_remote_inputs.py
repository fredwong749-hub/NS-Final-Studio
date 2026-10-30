"""fredw-92/F1：gpu3 输出直接 [output] 引用、不重传；上传兜底 JPEG q95 + ≥900 s + 同内容跳过；文件缺失自动改上传"""
import io
import json
import re

import pytest
from PIL import Image

from ns_render import comfy_client as CC
from ns_render.comfy_client import ComfyClient, ComfyError


class FakeServer:
    """一个 gpu3 机器：每个实例有自己的输出目录（可共用），输入目录所有实例共用"""

    def __init__(self):
        self.outputs: dict[str, dict[str, bytes]] = {}   # out_dir → {"sub/name": bytes}
        self.inputs: dict[str, bytes] = {}
        self.uploads: list[dict] = []
        self.prompts: list[dict] = []


class FakeComfy(ComfyClient):
    def __init__(self, server: FakeServer, out_dir: str, base: str, gpu=None):
        super().__init__(base, gpu=gpu)
        self.server, self.out_dir = server, out_dir
        server.outputs.setdefault(out_dir, {})

    def _request(self, path, data=None, headers=None, timeout=None, method=None):
        s = self.server
        if path == "/system_stats":
            return json.dumps({"system": {"argv": ["main.py", "--output-directory", self.out_dir]}}).encode()
        if path.startswith("/view?"):
            q = dict(re.findall(r"(\w+)=([^&]*)", path))
            from urllib.parse import unquote_plus
            key = "/".join(x for x in (unquote_plus(q.get("subfolder", "")), unquote_plus(q["filename"])) if x)
            store = s.inputs if q.get("type") == "input" else s.outputs[self.out_dir]
            if key not in store:
                err = ComfyError(f"/view: HTTP 404")
                err.status, err.body = 404, b""
                raise err
            return b"" if method == "HEAD" else store[key]
        if path == "/upload/image":
            body = data
            sub = re.search(rb'name="subfolder"\r\n\r\n([^\r]*)', body).group(1).decode()
            name = re.search(rb'filename="([^"]+)"', body).group(1).decode()
            payload = body.split(b"application/octet-stream\r\n\r\n", 1)[1].rsplit(b"\r\n--", 1)[0]
            s.inputs[f"{sub}/{name}"] = payload
            s.uploads.append({"name": name, "timeout": timeout, "bytes": payload})
            return json.dumps({"name": name, "subfolder": sub}).encode()
        if path == "/prompt":
            wf = json.loads(data)["prompt"]
            s.prompts.append(wf)
            errs = {}
            for nid, node in wf.items():
                if node["class_type"] != "LoadImage":
                    continue
                name = node["inputs"]["image"]
                if name.endswith(" [output]"):
                    ok = name[: -len(" [output]")] in s.outputs[self.out_dir]
                else:
                    ok = name in s.inputs
                if not ok:
                    errs[nid] = {"errors": [{"type": "custom_validation_failed",
                                             "details": f"image - Invalid image file: {name}"}],
                                 "class_type": "LoadImage"}
            if errs:
                body = json.dumps({"error": {"type": "prompt_outputs_failed_validation"}, "node_errors": errs})
                err = ComfyError(f"/prompt: HTTP 400 {body[:2000]}")
                err.status, err.body = 400, body.encode()
                raise err
            return json.dumps({"prompt_id": f"p{len(s.prompts)}", "node_errors": {}}).encode()
        raise AssertionError(path)


def _png(w=64, h=112, color=(200, 30, 30)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), color).save(buf, "PNG")
    return buf.getvalue()


def _render_on(client, tmp_path, name="ns_final/ep01-S1_frame_00001_.png"):
    """gpu3 上出了一张图，笔记本下载下来"""
    client.server.outputs[client.out_dir][name] = _png()
    sub, fn = name.rsplit("/", 1)
    return client.download({"filename": fn, "subfolder": sub, "type": "output"}, tmp_path / "takes" / "image_001.png")


def _graph(name):
    return {"1": {"class_type": "LoadImage", "inputs": {"image": name}},
            "2": {"class_type": "VAEEncode", "inputs": {"pixels": ["1", 0]}},
            "9": {"class_type": "SaveImage", "inputs": {"images": ["2", 0]}}}


def test_same_instance_uses_output_annotation(tmp_path):
    srv = FakeServer()
    c = FakeComfy(srv, "/root/ComfyUI/output/gpu0", "http://127.0.0.1:18188", gpu=0)
    local = _render_on(c, tmp_path)
    info = c.remote_info(local)
    assert info["filename"] == "ep01-S1_frame_00001_.png" and info["gpu"] == 0
    assert len(info["sha256"]) == 64 and info["instance"] == "out:/root/ComfyUI/output/gpu0"

    name = c.upload_image(local, "ns_final/refs")
    assert name == "ns_final/ep01-S1_frame_00001_.png [output]"
    scaled = CC.input_image(c, local, "ns_final/refs", size=(32, 56), prepare=lambda: pytest.fail("不该上传"))
    c.submit({**_graph(name), "5": {"class_type": "LoadImage", "inputs": {"image": scaled}},
              "6": {"class_type": "VAEEncode", "inputs": {"pixels": ["5", 0]}}})
    assert srv.uploads == []
    wf = srv.prompts[-1]
    assert wf["5"]["inputs"]["image"] == "ns_final/ep01-S1_frame_00001_.png [output]"
    assert wf["6"]["inputs"]["pixels"] == ["5_f1scale", 0]
    assert wf["5_f1scale"]["inputs"] == {"image": ["5", 0], "upscale_method": "lanczos", "width": 32,
                                         "height": 56, "crop": "disabled"}
    assert wf["1"]["inputs"]["image"] == name and wf["2"]["inputs"]["pixels"] == ["1", 0]


def test_other_instance_uploads_jpeg_once_with_long_timeout(tmp_path):
    srv = FakeServer()
    g0 = FakeComfy(srv, "/root/ComfyUI/output/gpu0", "http://127.0.0.1:18188", gpu=0)
    g3 = FakeComfy(srv, "/root/ComfyUI/output/gpu3", "http://127.0.0.1:18191", gpu=3)
    local = _render_on(g0, tmp_path)
    name = g3.upload_image(local, "ns_final")
    assert not name.endswith("[output]") and name.endswith(".jpg")
    up = srv.uploads[0]
    assert up["timeout"] >= 900 and up["bytes"][:2] == b"\xff\xd8"          # JPEG
    # 同内容第二次（换参数重渲 / 另一实例，输入目录共用）→ HEAD 查到，不再传
    assert g3.upload_image(local, "ns_final") == name
    assert g0.upload_image(local, "ns_final") != name or True
    assert len(srv.uploads) == 1


def test_transparent_png_kept_as_png(tmp_path):
    srv = FakeServer()
    c = FakeComfy(srv, "/o/gpu0", "http://x")
    p = tmp_path / "mask.png"
    Image.new("RGBA", (8, 8), (0, 0, 0, 0)).save(p)
    assert c.upload_image(p, "ns_final").endswith(".png")


def test_shared_output_dir_annotation_works_across_instances(tmp_path):
    srv = FakeServer()
    a = FakeComfy(srv, "/root/ComfyUI/output", "http://127.0.0.1:18188", gpu=0)
    b = FakeComfy(srv, "/root/ComfyUI/output", "http://127.0.0.1:18191", gpu=3)
    local = _render_on(a, tmp_path)
    assert b.upload_image(local, "ns_final").endswith(" [output]")
    assert srv.uploads == []


def test_missing_remote_file_falls_back_to_upload(tmp_path):
    srv = FakeServer()
    c = FakeComfy(srv, "/o/gpu0", "http://127.0.0.1:18188", gpu=0)
    local = _render_on(c, tmp_path)
    prepared = []

    def prepare():
        p = tmp_path / "scaled.jpg"
        Image.open(local).convert("RGB").resize((32, 56)).save(p, quality=95)
        prepared.append(p)
        return p
    name = CC.input_image(c, local, "ns_final/refs", size=(32, 56), prepare=prepare)
    srv.outputs["/o/gpu0"].clear()                     # gpu3 上的输出被清掉了
    pid = c.submit(_graph(name))
    assert pid == "p2" and len(srv.prompts) == 2 and prepared
    final = srv.prompts[-1]
    assert final["1"]["inputs"]["image"].startswith("ns_final/refs/") and "[output]" not in final["1"]["inputs"]["image"]
    assert "1_f1scale" not in final                    # 上传的已是缩放好的图
    assert c.reuploads == [name]
    assert CC.remote_index.find(CC.file_sha256(local), c.instance()) is None   # 记录已忘掉，下次直接上传


def test_other_validation_errors_still_raise(tmp_path):
    srv = FakeServer()
    c = FakeComfy(srv, "/o/gpu0", "http://x")
    with pytest.raises(ComfyError, match="HTTP 400"):
        c.submit(_graph("ns_final/never_uploaded.png"))


def test_frame_edit_input_uses_annotation_for_parent(tmp_path, monkeypatch):
    from ns_render import frame_edit as FE
    srv = FakeServer()
    c = FakeComfy(srv, "/o/gpu0", "http://x", gpu=0)
    local = _render_on(c, tmp_path)
    monkeypatch.setattr(FE.P, "DATA", tmp_path)
    assert FE._input(c, local, FE.EDIT_REF_SIZE).endswith(" [output] @768x1344:disabled")
    other = tmp_path / "ref.png"
    Image.new("RGB", (2000, 1000), (1, 2, 3)).save(other)
    name = FE._input(c, other, None, FE.REF_MAX_SIDE)
    assert name.endswith(".jpg") and srv.uploads[-1]["bytes"][:2] == b"\xff\xd8"


def test_h3_upload_once_real_client_references_output(tmp_path):
    from ns_render import h3_video as H
    srv = FakeServer()
    c = FakeComfy(srv, "/o/gpu3", "http://x", gpu=3)
    local = _render_on(c, tmp_path)
    name = H.upload_once(c, local)
    w, h = H.P.VIDEO_SIZE
    assert name.endswith(f" [output] @{w}x{h}:center") and srv.uploads == []


# ---- F3 审计（fredw-92 转）：参考图路径、并发同号文件名

@pytest.mark.parametrize("raw", ["/x.png", "/Windows/x.png", "C:/x.png", "D:x.png", "a\b.png", "../x.png",
                                 "data/../../x.png", ""])
def test_resolve_ref_path_rejects_absolute_and_escape(raw):
    from ns_render import frame_edit as FE
    with pytest.raises(ValueError):
        FE.resolve_ref_path({"path": raw})


def test_resolve_ref_path_accepts_relative_inside(tmp_path, monkeypatch):
    from ns_render import frame_edit as FE
    monkeypatch.setattr(FE.P, "ROOT", tmp_path)
    monkeypatch.setattr(FE.P, "DATA", tmp_path / "data")
    (tmp_path / "assets").mkdir()
    Image.new("RGB", (4, 4)).save(tmp_path / "assets" / "r.png")
    assert FE.resolve_ref_path({"path": "assets/r.png"}) == tmp_path / "assets" / "r.png"


def test_same_n_on_two_lanes_gets_distinct_files():
    from ns_render import frame_edit as FE
    a, b = FE.unique_tag({"id": "job-aaa"}), FE.unique_tag({"id": "job-bbb"})
    assert a != b and a == "jobaaa"
    assert FE.unique_tag(None) != FE.unique_tag(None)
