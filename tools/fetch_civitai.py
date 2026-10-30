"""
按 Civitai 模型编号下载 Qwen Image 2.1 版本的 LoRA 到本机 ComfyUI（research v8 第 8 节）。

    uv run python tools/fetch_civitai.py 2728005 1862761 2808492 2406218

挑选规则：baseModel 含 "Qwen" 且含 "2.1" 的最新版本；找不到就报出可选版本，不乱下。
记录写进 comfy/models.lock 的 downloads 段（url、文件名、sha256）。
"""
import hashlib
import json
import os
import sys
import urllib.request
from pathlib import Path

LORAS = Path("C:/Users/fredw/Documents/Codex/Apps/ComfyUI/models/loras")
LOCK = Path(__file__).resolve().parent.parent / "comfy" / "models.lock"
UA = {"User-Agent": "ns-final-studio/0.1"}
# 需要登录的模型用环境变量 CIVITAI_TOKEN（项目方设置的用户级环境变量）；不打印、不落盘
if os.environ.get("CIVITAI_TOKEN"):
    UA["Authorization"] = f"Bearer {os.environ['CIVITAI_TOKEN']}"


def get_json(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
        return json.load(r)


def pick_version(model):
    for v in model.get("modelVersions", []):
        base = (v.get("baseModel") or "").lower()
        if "qwen" in base and "2.1" in base:
            return v
    return None


def download(url, dest):
    tmp = dest.with_suffix(dest.suffix + ".part")
    h = hashlib.sha256()
    headers = {"User-Agent": UA["User-Agent"]}   # 不带 Authorization（见调用处）
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=120) as r, open(tmp, "wb") as f:
        while chunk := r.read(1 << 20):
            f.write(chunk)
            h.update(chunk)
    tmp.replace(dest)
    return h.hexdigest()


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    lock = json.loads(LOCK.read_text(encoding="utf-8"))
    lock.setdefault("downloads", [])
    for mid in sys.argv[1:]:
        model = get_json(f"https://civitai.com/api/v1/models/{mid}")
        v = pick_version(model)
        if not v:
            print(f"{mid} {model.get('name')}: 没有 Qwen 2.1 版本，可选：",
                  [(x.get("name"), x.get("baseModel")) for x in model.get("modelVersions", [])])
            continue
        f = next((x for x in v["files"] if x.get("primary")), v["files"][0])
        dest = LORAS / f["name"]
        if dest.exists():
            print(f"{mid}: 已存在 {dest.name}")
            continue
        print(f"{mid} {model['name']} / {v['name']} ({v['baseModel']}) -> {f['name']} {f.get('sizeKB', 0) / 1024:.0f}MB", flush=True)
        try:
            # token 走 URL 参数：带 Authorization 头跟随重定向到存储服务器会被拒（400）
            url = v["downloadUrl"]
            if os.environ.get("CIVITAI_TOKEN"):
                url += ("&" if "?" in url else "?") + "token=" + os.environ["CIVITAI_TOKEN"]
            sha = download(url, dest)
        except Exception as e:  # 需要登录或网络错误时报出，不中断其它下载
            tok = os.environ.get("CIVITAI_TOKEN")   # QA-10：不打印 token
            msg = str(e).replace(tok, "***") if tok else str(e)
            print(f"  下载失败：{msg}")
            continue
        lock["downloads"].append({"civitai_model": int(mid), "version": v["name"], "base": v["baseModel"],
                                  "file": f["name"], "url": v["downloadUrl"], "sha256": sha})
        LOCK.write_text(json.dumps(lock, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  完成 sha256={sha[:16]}…", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
