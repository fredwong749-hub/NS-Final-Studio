"""本地看图模型的多实例分发（GOLDEN-O 11-03，项目方 02:1x“GPU 全速”；CAST-S 实测看图排队约 2 分钟是出图链路的瓶颈）。

根因：ns_agent.vqa.client.generate 只要笔记本 127.0.0.1:8870（4080 单实例）在线就只用它，常驻隧道 127.0.0.1:8871 → gpu36 看图路由
（GPU2 上 2 个 nf4 实例）闲着。这里按两边 /health 的排队量选负载最轻的一个（负载 ÷ 实例数），多个出图子进程同时问时自然分到两台。
硬规则 K-REV-V01 不变：只认本机地址（127.0.0.1 / localhost；8871 是到自家 gpu36 的 ssh 隧道），图片绝不发往任何外部 API。
缓存键 / 缓存目录 / 请求格式与 client.generate 完全相同（同一张图同一个问题，两条路的结论共用一份缓存）。两边都不在 → 退回 client.generate（ssh 管道）。

    python tools/pipeline/vlm_pool.py status        # 看两边负载、本次会选哪一边
"""
from __future__ import annotations

import base64
import json
import os
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in ("services/agent",):
    if str(ROOT / _p) not in sys.path:
        sys.path.insert(0, str(ROOT / _p))

LOCAL = ("127.0.0.1", "localhost")


def endpoints() -> list[dict]:
    """[{url, remote}]：本机实例（读得到本机路径）+ 到 gpu36 的常驻隧道（要先把图转成字节）。端口取 config/vqa.json model.port 与 port+1（client 同口径）"""
    from ns_agent.vqa import client as C
    u = C._url()
    base, port = u.rsplit(":", 1)
    port = int(port.split("/")[0])
    return [{"url": f"{base}:{port}", "remote": False}, {"url": f"{base}:{port + 1}", "remote": True}]


def _is_local(url: str) -> bool:
    return url.split("//", 1)[-1].split(":", 1)[0].split("/", 1)[0] in LOCAL


def health(url: str, timeout: float = 3) -> dict | None:
    if not _is_local(url):
        raise ValueError(f"K-REV-V01：看图服务只能是本机地址，拒绝 {url}")
    try:
        with urllib.request.urlopen(url + "/health", timeout=timeout) as r:
            return json.loads(r.read())
    except (OSError, ValueError):   # arch-ok: 探不到 = 这一边不在，不选它
        return None


def load_of(h: dict) -> float:
    """负载 = (排队 + 在跑 + 1) ÷ 实例数；路由（gpu36）报 instances / inflight，单实例（笔记本）只报 queue"""
    n = max(1, int(h.get("instances") or 1))
    busy = int(h.get("queue") or 0) + sum(int(v or 0) for v in (h.get("inflight") or {}).values())
    return (busy + 1) / n


def choose(probe=None) -> dict | None:
    """负载最轻的在线实例；一样轻时优先多实例那边。都不在 = None"""
    probe = probe or health
    best = None
    for ep in endpoints():
        h = probe(ep["url"])
        if not h:
            continue
        # 单实例闲置会卸载（idle_unload_s），再问要先装载约 10 s：记半个排队位
        cand = {**ep, "load": load_of(h) + (0.5 if h.get("loaded") is False else 0), "instances": int(h.get("instances") or 1)}
        if best is None or (cand["load"], -cand["instances"]) < (best["load"], -best["instances"]):
            best = cand
    return best


def generate(req: dict, *, wait_s: float = 1800, refresh: bool = False, label: str = "", probe=None, post=None) -> dict:
    """与 client.generate 同签名同返回：{text, seconds, gpu, cached, key, via} 或 {error}"""
    from ns_agent.vqa import client as C
    key = C._key(req)
    C.CACHE.mkdir(parents=True, exist_ok=True)
    cf = C.CACHE / f"{key}.json"
    if cf.exists() and not refresh:
        return {**json.loads(cf.read_text(encoding="utf-8")), "cached": True, "key": key}
    ep = choose(probe)
    if ep is None:
        return C.generate(req, wait_s=wait_s, refresh=refresh, label=label)
    if not _is_local(ep["url"]):
        raise ValueError(f"K-REV-V01：看图服务只能是本机地址，拒绝 {ep['url']}")
    body = {"system": req.get("system"), "text": req["text"], "key": key, "wait_s": wait_s, "label": label,
            "max_new_tokens": int((C.cfg().get("model") or {}).get("max_new_tokens", 900)),
            "images": [dict(im) for im in req["images"]], "refresh": refresh}
    if ep["remote"]:                    # 隧道那头是 gpu36，读不到本机路径：缩图转字节（client 同一做法）
        for im in body["images"]:
            if "path" in im and Path(im["path"]).exists():
                im["b64"] = base64.b64encode(C._shrink(Path(im["path"]), im.get("max_pixels"))).decode()
                im.pop("path")
    res = (post or C._post_local)(ep["url"], body, wait_s + 120)
    if "error" not in res:
        res["key"] = key
        tmp = cf.with_name(f"{cf.name}.{os.getpid()}.{id(res)}.tmp")   # 原子写：并发命中同一 key 的读者不会读到半个缓存
        tmp.write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, cf)
    res["via"] = ep["url"]
    return res


def inspect_image(subject: str, prompt: str, references: list[str] | None = None, **kw) -> dict:
    """Q9 出图复核（client.inspect_image 同一份请求 / 解析），只是请求经本分发器走负载最轻的实例"""
    from ns_agent.vqa import client as C
    from ns_agent.vqa import rubric
    req = rubric.build_image_request(subject, prompt, references, extra_refs=kw.pop("extra_refs", None), spec=kw.pop("spec", None))
    return C._finish(req, generate(req, **kw), "image", str(subject))


def main(argv=None) -> int:
    for ep in endpoints():
        h = health(ep["url"])
        print(ep["url"], "remote" if ep["remote"] else "local", "离线" if not h else f"load={load_of(h):.2f} instances={h.get('instances') or 1} queue={h.get('queue')} inflight={h.get('inflight')}")
    print("选：", (choose() or {}).get("url"))
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
