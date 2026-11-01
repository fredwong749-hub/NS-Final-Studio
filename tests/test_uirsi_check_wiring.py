"""UIDEBUG：前端调用 ↔ 后端路由 静态比对（tools/uirsi/check_wiring.py）。

1) 解析器自测：模板字符串、前缀常量、跨行泛型、query、内联请求体、方法推断；
2) 全仓检查：apps/web/src 里每个 /api/ 调用都在 ns_api.app 的路由表里、方法对、必填字段都发了
   （已知、已交给 UIRSI 的问题记在 tools/uirsi/wiring_baseline.json，不许新增）。
规则：knowledge/rules/ui.yaml K-UI-007 / K-UI-008。
"""
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("check_wiring", ROOT / "tools" / "uirsi" / "check_wiring.py")
CW = importlib.util.module_from_spec(_spec)
sys.modules["check_wiring"] = CW
_spec.loader.exec_module(CW)

SPEC = {
    "paths": {
        "/api/a/{x}": {"get": {"parameters": [{"name": "x", "in": "path", "required": True}]}},
        "/api/a/{x}/save": {"put": {"requestBody": {"content": {"application/json": {"schema": {"$ref": "#/components/schemas/B"}}}}}},
        "/api/q": {"get": {"parameters": [{"name": "ep", "in": "query", "required": True}]}},
        "/api/qonly": {"post": {"parameters": [{"name": "path", "in": "query", "required": True}]}},
        "/api/t/{s}/{n}/lock": {"post": {}},
        "/api/t/{s}/{n}/unlock": {"post": {}},
        "/api/keys": {"get": {"parameters": [{"name": "type", "in": "query"}]}},
        "/api/{key}": {"get": {}},
    },
    "components": {"schemas": {"B": {"type": "object", "properties": {"text": {}, "by": {}}, "required": ["text"]}}},
}

TS = '''
const B = "/api/a";
const P = (s: string) => `/api/a/${enc(s)}`;
async function call<T>(url: string, body?: unknown): Promise<T> {
  const r = await fetch(url, body === undefined ? undefined : { method: "POST", headers: {}, body: JSON.stringify(body) });
  return r.json();
}
export const api = {
  one: (x: string) => req<import("./types").Foo>(`${B}/${x}`),
  save: (x: string) => req<{
    ok: boolean;
  }>(`${P(x)}/save`, json("PUT", { text: "a", extra: 1 })),
  saveBad: (x: string) => req<unknown>(`${P(x)}/save`, json("PUT", { by: "owner" })),
  q: () => req<unknown>("/api/q"),
  qok: (ep: number) => req<unknown>(`/api/q?ep=${ep}`),
  qonly: (p: string) => call("/api/qonly", { path: p }),
  lock: (s: string, n: number, on: boolean) => req<unknown>(`/api/t/${s}/${n}/${on ? "lock" : "unlock"}`, { method: "POST" }),
  keys: (t?: string) => req<unknown>(`/api/keys${t ? `?type=${t}` : ""}`),
  gone: () => req<unknown>("/api/nowhere/at/all"),
  wrong: () => req<unknown>("/api/keys", { method: "DELETE" }),
  // req<X>("/api/commented/out")
};
'''


def _scan(tmp_path):
    f = tmp_path / "apps" / "web" / "src" / "x.ts"
    f.parent.mkdir(parents=True)
    f.write_text(TS, encoding="utf-8")
    old = CW.ROOT
    CW.ROOT = tmp_path
    try:
        return CW.scan_file(f)
    finally:
        CW.ROOT = old


def test_parser_paths_methods_and_bodies(tmp_path):
    calls = _scan(tmp_path)
    by = {(c.method, c.path): c for c in calls}
    assert ("GET", "/api/a/{}") in by                         # ${B} 前缀 + 跨括号泛型
    assert by[("PUT", "/api/a/{}/save")].body_keys in (["text", "extra"], ["by"])   # ${P(x)} 前缀 + 跨行泛型
    assert any(c.path == "/api/q" and c.query == [] for c in calls)
    assert any(c.path == "/api/q" and c.query == ["ep"] for c in calls)
    assert by[("POST", "/api/qonly")].body_keys == ["path"]  # 可选 body 的小 helper → POST
    assert by[("GET", "/api/keys")].query == ["type"]        # ${t ? `?type=…` : ""} 算 query 不算路径
    assert not any("commented" in c.path for c in calls)      # 注释里的不算


def test_check_findings(tmp_path):
    findings, unused = CW.check(_scan(tmp_path), SPEC)
    codes = {(f.code, f.path, f.msg.split("：")[0]) for f in findings}
    assert ("E-ROUTE", "/api/nowhere/at/all", "后端没有这个路由") in codes
    assert any(f.code == "E-METHOD" and f.path == "/api/keys" for f in findings)
    assert any(f.code == "E-REQUIRED" and f.path == "/api/q" and "ep" in f.msg for f in findings)
    assert any(f.code == "E-REQUIRED" and "text" in f.msg for f in findings)       # saveBad 少了必填 text
    assert any(f.code == "W-BODY" and "extra" in f.msg for f in findings)           # 多发的字段被丢弃
    assert any(f.code == "E-BODYKIND" and f.path == "/api/qonly" for f in findings) # 发 JSON 体，后端只收 query
    assert not any(f.path.startswith("/api/t/") for f in findings)                  # lock/unlock 三元表达式能对上
    assert "POST /api/t/{s}/{n}/lock" not in unused and "POST /api/t/{s}/{n}/unlock" not in unused


def test_repo_frontend_matches_backend_routes():
    """全仓：前端每个 /api/ 调用都有后端路由、方法对、必填都发了；已知问题只能减少不能新增。"""
    spec = CW.load_openapi(None)
    calls = CW.scan_frontend()
    assert len(calls) > 50, "扫描器没找到前端调用（解析坏了？）"
    findings, _ = CW.check(calls, spec)
    base = CW.load_baseline()
    new = [f"{f.sev} {f.code} {f.method} {f.path} {f.file}:{f.line} {f.msg}" for f in findings
           if f.code.startswith("E-") and f.key() not in base]
    assert not new, "前后端没接上（修前端调用或补后端路由；交给别人修的写进 tools/uirsi/wiring_baseline.json）：\n" + "\n".join(new)
