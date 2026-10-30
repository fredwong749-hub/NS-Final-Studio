"""
gpu3 桥（docs/canvas.md §7.6）：项目方的 H3 修改 / 审计豁免请求写到 gpu3，读 gpu3 的镜头状态与「出视频」闸门。

桥地址与「请 gpu3 重出」相同：readiness.BRIDGE_URL（默认 http://127.0.0.1:15180，经隧道到 gpu3 127.0.0.1:5180），无 token。
路径与请求体只在这里定义，契约改了只改这个文件。
送达失败不做任何静默兜底：调用方把 Delivery(ok=False, code, error) 记进本地 edits.json，画布显示「未送达 gpu3」+ 重试；
409（base_sha 过期）画布显示 stale + 刷新。
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from urllib.parse import quote

from ns_api import readiness as RD

PREFIX = "/api/gpu3"
SHOT_PATH = PREFIX + "/projects/{slug}/shots/{shot_id}"                 # GET → ShotRenders
EPISODE_PATH = PREFIX + "/projects/{slug}/episodes/{ep}"                # GET → {audit_summary, shots:[ShotRenders]}
H3_EDIT_PATH = PREFIX + "/projects/{slug}/shots/{shot_id}/h3_edit"      # POST {text, by:"owner", base_sha}
OVERRIDE_PATH = PREFIX + "/projects/{slug}/shots/{shot_id}/override"    # POST {rule_id, owner_quote, by:"owner"}
RULE_PATH = PREFIX + "/rules/{rule_id}"                                 # GET → shot_audit.py --explain <id> --json
TIMEOUT_S = 10
GET_TIMEOUT_S = 4


class BridgeError(Exception):
    def __init__(self, msg: str, code: int | None = None, body=None):
        super().__init__(msg)
        self.code, self.body = code, body


def _url(path: str, **kw) -> str:
    return RD.BRIDGE_URL + path.format(**{k: quote(str(v), safe="") for k, v in kw.items()})


def _call(method: str, url: str, body: dict | None = None, timeout: float = TIMEOUT_S):
    """真正的 HTTP；测试里用假桥替换本函数。失败抛 BridgeError(code: HTTP 状态码 / None = 不可达)"""
    if method == "GET" and RD.bridge_down():      # 只读：桥刚连不上就直接失败（项目方的写操作仍然每次真试）
        raise BridgeError(f"gpu3 桥刚才不可达（{RD.BRIDGE_URL}），{int(RD.BRIDGE_DOWN_S)} 秒内不重试")
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    r = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            out = json.loads(resp.read().decode("utf-8") or "{}")
        RD.mark_bridge(True)
        return out
    except urllib.error.HTTPError as e:
        RD.mark_bridge(True)
        try:
            detail = json.loads(e.read().decode("utf-8") or "{}")
        except Exception:  # noqa: BLE001
            detail = None
        msg = (detail or {}).get("detail") if isinstance(detail, dict) else None
        raise BridgeError(f"gpu3 桥返回 {e.code}：{msg or e.reason}", e.code, detail) from e
    except (urllib.error.URLError, OSError) as e:
        RD.mark_bridge(False)
        raise BridgeError(f"gpu3 桥不可达（{RD.BRIDGE_URL}）：{e}") from e
    except ValueError as e:
        raise BridgeError(f"gpu3 桥返回的不是 JSON（{RD.BRIDGE_URL}）：{e}") from e


def h3_edit_body(text: str, base_sha: str | None) -> dict:
    return {"text": text, "by": "owner", "base_sha": base_sha}


def override_body(rule_id: str, owner_quote: str) -> dict:
    return {"rule_id": rule_id, "owner_quote": owner_quote, "by": "owner"}


def post_h3_edit(slug: str, shot_id: str, text: str, base_sha: str | None) -> dict:
    return _call("POST", _url(H3_EDIT_PATH, slug=slug, shot_id=shot_id), h3_edit_body(text, base_sha))


def post_override(slug: str, shot_id: str, rule_id: str, owner_quote: str) -> dict:
    return _call("POST", _url(OVERRIDE_PATH, slug=slug, shot_id=shot_id), override_body(rule_id, owner_quote))


def get_shot(slug: str, shot_id: str) -> dict:
    return _call("GET", _url(SHOT_PATH, slug=slug, shot_id=shot_id), timeout=GET_TIMEOUT_S)


def get_episode(slug: str, ep: int) -> dict:
    return _call("GET", _url(EPISODE_PATH, slug=slug, ep=ep), timeout=GET_TIMEOUT_S)


def get_rule(rule_id: str) -> dict:
    return _call("GET", _url(RULE_PATH, rule_id=rule_id), timeout=GET_TIMEOUT_S + 12)   # 桥侧 explain 超时 15 s
