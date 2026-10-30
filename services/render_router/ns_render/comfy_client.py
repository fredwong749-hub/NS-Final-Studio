"""最小 ComfyUI HTTP 客户端（只用标准库）：校验、上传、提交、等待、下载。"""
import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

# 这些输入名对应模型文件，校验时要在 ComfyUI 的可选列表里
MODEL_INPUTS = ("unet_name", "clip_name", "vae_name", "lora_name", "model_name")


class ComfyError(RuntimeError):
    pass


class ComfyUnavailable(ComfyError):
    """连不上 ComfyUI（进程没起或被杀）：不重试、不换种子，整批停下"""


class ComfyClient:
    def __init__(self, base_url: str = "http://127.0.0.1:8188", timeout: float = 60):
        self.base = base_url.rstrip("/")
        self.timeout = timeout
        self.client_id = uuid.uuid4().hex
        self._object_info: dict | None = None

    def _request(self, path: str, data: bytes | None = None, headers: dict | None = None) -> bytes:
        req = urllib.request.Request(self.base + path, data=data, headers=headers or {})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            raise ComfyError(f"{path}: HTTP {e.code} {e.read()[:2000].decode('utf-8', 'replace')}") from e
        except urllib.error.URLError as e:
            raise ComfyUnavailable(f"{path}: {e.reason}") from e
        except (ConnectionError, TimeoutError) as e:
            raise ComfyUnavailable(f"{path}: {e}") from e

    def _json(self, path: str, body=None):
        data = json.dumps(body).encode() if body is not None else None
        headers = {"Content-Type": "application/json"} if body is not None else None
        return json.loads(self._request(path, data, headers))

    def system_stats(self) -> dict:
        return self._json("/system_stats")

    def object_info(self) -> dict:
        if self._object_info is None:
            self._object_info = self._json("/object_info")
        return self._object_info

    def check(self, workflow: dict) -> list[str]:
        """提交前检查：节点是否存在、模型文件是否在 ComfyUI 的列表里"""
        info = self.object_info()
        problems = []
        for nid, node in workflow.items():
            cls = node["class_type"]
            if cls not in info:
                problems.append(f"节点 {nid}: 没有 {cls}")
                continue
            spec = {**info[cls]["input"].get("required", {}), **info[cls]["input"].get("optional", {})}
            for key in MODEL_INPUTS:
                value = node["inputs"].get(key)
                if value is None or key not in spec:
                    continue
                options = spec[key][0]
                if isinstance(options, list) and value not in options:
                    problems.append(f"节点 {nid} ({cls}): 找不到 {key}={value}")
        return problems

    def upload_image(self, path: Path, subfolder: str = "ns_final") -> str:
        data = path.read_bytes()
        name = hashlib.sha256(data).hexdigest()[:16] + path.suffix.lower()
        boundary = uuid.uuid4().hex
        parts = []
        for key, value in (("subfolder", subfolder), ("overwrite", "true")):
            parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode())
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="image"; filename="{name}"\r\n'
                     f"Content-Type: application/octet-stream\r\n\r\n".encode() + data + b"\r\n")
        parts.append(f"--{boundary}--\r\n".encode())
        res = json.loads(self._request("/upload/image", b"".join(parts),
                                       {"Content-Type": f"multipart/form-data; boundary={boundary}"}))
        return f"{res['subfolder']}/{res['name']}" if res.get("subfolder") else res["name"]

    def submit(self, workflow: dict) -> str:
        res = self._json("/prompt", {"prompt": workflow, "client_id": self.client_id})
        if res.get("node_errors"):
            raise ComfyError(f"node_errors: {json.dumps(res['node_errors'], ensure_ascii=False)[:2000]}")
        return res["prompt_id"]

    def wait(self, prompt_id: str, timeout_s: float, poll_s: float = 3) -> dict:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            hist = self._json(f"/history/{prompt_id}")
            entry = hist.get(prompt_id)
            if entry:
                status = entry.get("status", {})
                if status.get("status_str") == "error":
                    msgs = [m for m in status.get("messages", []) if m[0] == "execution_error"]
                    detail = msgs[0][1].get("exception_message", "") if msgs else ""
                    raise ComfyError(f"执行失败: {detail.strip()[:1000]}")
                if status.get("completed"):
                    return entry
            time.sleep(poll_s)
        self.interrupt()
        raise ComfyError(f"超时 {timeout_s}s")

    def interrupt(self):
        try:
            self._request("/interrupt", b"{}", {"Content-Type": "application/json"})
        except ComfyError:
            pass

    def free(self, unload_models: bool = True):
        self._json("/free", {"unload_models": unload_models, "free_memory": True})

    @staticmethod
    def output_files(entry: dict) -> list[dict]:
        files = []
        for out in entry.get("outputs", {}).values():
            for items in out.values():
                if isinstance(items, list):
                    files += [i for i in items if isinstance(i, dict) and "filename" in i]
        return files

    def download(self, item: dict, dest: Path) -> Path:
        q = urllib.parse.urlencode({"filename": item["filename"], "subfolder": item.get("subfolder", ""),
                                    "type": item.get("type", "output")})
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(self._request(f"/view?{q}"))
        return dest

    def run(self, workflow: dict, timeout_s: float) -> tuple[dict, float]:
        """检查 → 提交 → 等待；返回 (history 条目, 耗时秒)"""
        problems = self.check(workflow)
        if problems:
            raise ComfyError("工作流检查不通过:\n  " + "\n  ".join(problems))
        t0 = time.monotonic()
        entry = self.wait(self.submit(workflow), timeout_s)
        return entry, time.monotonic() - t0
