"""UIDEBUG：前端调用 ↔ 后端路由 静态比对（tools/uirsi/check_wiring.py）。

扫 apps/web/src 下所有 .ts/.tsx 里以 /api/ 开头的 URL（含模板字符串、`${B}`/`${P(slug)}` 这类前缀常量），
推断 HTTP 方法、query 参数名、内联请求体字段，再和 OpenAPI 逐条对：

  E-ROUTE    前端调了、后端没有的路由（任何方法都没有）            → P0
  E-METHOD   路由在，但方法不对（GET/POST/PUT/DELETE）            → P0
  E-REQUIRED 后端必填的 query / body 字段前端没发（必 422）        → P0
  E-BODYKIND 前端发 JSON 体，后端只收 query 参数（字段读不到）     → P0
  W-QUERY    前端发了后端不认的 query 参数（被静默忽略）            → P1
  W-BODY     前端内联请求体里有后端模型没有的字段（被静默丢弃）      → P1
  I-UNUSED   后端有、前端没用到的路由（可能功能没接上）               → 信息

OpenAPI 来源（默认从代码现算，不依赖正在跑的 :8800——它可能是旧进程）：
  python tools/uirsi/check_wiring.py                 # import ns_api.app 现算
  python tools/uirsi/check_wiring.py --openapi URL|文件
  python tools/uirsi/check_wiring.py --json out.json  # 机器可读结果
退出码：有 E-* 且不在基线（tools/uirsi/wiring_baseline.json）里 → 1。
只读：不发任何请求（除非 --openapi 给的是 URL，那也只 GET openapi.json）。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from dataclasses import dataclass, field, asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WEB_SRC = ROOT / "apps" / "web" / "src"
BASELINE = Path(__file__).with_name("wiring_baseline.json")
METHODS = ("GET", "POST", "PUT", "DELETE", "PATCH")


# ---------------------------------------------------------------- JS 词法（够用即可）
def strip_comments(src: str) -> str:
    """把 // 和 /* */ 注释换成空格（保留换行，行号不变）；字符串 / 模板 / 正则字面量里的不动。"""
    out = list(src)
    i, n = 0, len(src)
    stack: list[str] = []  # 模板嵌套：'`' 表示在模板文本里，'{' 表示在 ${ } 代码里
    def blank(a: int, b: int):
        for k in range(a, b):
            if out[k] != "\n":
                out[k] = " "
    while i < n:
        c = src[i]
        in_tpl_text = stack and stack[-1] == "`"
        if in_tpl_text:
            if c == "\\":
                i += 2; continue
            if c == "`":
                stack.pop(); i += 1; continue
            if src.startswith("${", i):
                stack.append("{"); i += 2; continue
            i += 1; continue
        # 代码态
        if src.startswith("//", i):
            j = src.find("\n", i)
            j = n if j < 0 else j
            blank(i, j); i = j; continue
        if src.startswith("/*", i):
            j = src.find("*/", i + 2)
            j = n if j < 0 else j + 2
            blank(i, j); i = j; continue
        if c in "\"'":
            j = i + 1
            while j < n and src[j] != c and src[j] != "\n":
                j += 2 if src[j] == "\\" else 1
            i = j + 1; continue
        if c == "`":
            stack.append("`"); i += 1; continue
        if c == "{" and stack:
            stack.append("{"); i += 1; continue
        if c == "}" and stack and stack[-1] == "{":
            stack.pop(); i += 1; continue
        i += 1
    return "".join(out)


@dataclass
class Tok:
    start: int
    end: int
    parts: list  # [("lit", text) | ("expr", code)]


def read_string(src: str, i: int) -> Tok | None:
    """从 src[i]（引号或反引号）读一个字符串字面量。"""
    q = src[i]
    n = len(src)
    if q in "\"'":
        j, buf = i + 1, []
        while j < n and src[j] != q:
            if src[j] == "\n":
                return None
            if src[j] == "\\":
                buf.append(src[j + 1] if j + 1 < n else ""); j += 2; continue
            buf.append(src[j]); j += 1
        return Tok(i, j + 1, [("lit", "".join(buf))])
    # 模板
    j, parts, buf = i + 1, [], []
    while j < n:
        c = src[j]
        if c == "\\":
            buf.append(src[j + 1] if j + 1 < n else ""); j += 2; continue
        if c == "`":
            if buf:
                parts.append(("lit", "".join(buf)))
            return Tok(i, j + 1, parts)
        if src.startswith("${", j):
            if buf:
                parts.append(("lit", "".join(buf))); buf = []
            k = skip_code(src, j + 2, "}")
            parts.append(("expr", src[j + 2:k]))
            j = k + 1; continue
        buf.append(c); j += 1
    return None


def skip_code(src: str, i: int, close: str) -> int:
    """从 i 开始跳过代码直到配对的 close（跳过字符串 / 模板 / 括号）。返回 close 的下标。"""
    pairs = {"(": ")", "[": "]", "{": "}"}
    stack = [close]
    n = len(src)
    while i < n:
        c = src[i]
        if c in "\"'`":
            t = read_string(src, i)
            i = (t.end if t else i + 1); continue
        if c in pairs:
            stack.append(pairs[c]); i += 1; continue
        if c in ")]}":
            if stack and c == stack[-1]:
                stack.pop()
                if not stack:
                    return i
            i += 1; continue
        i += 1
    return n


def iter_strings(src: str):
    i, n = 0, len(src)
    while i < n:
        c = src[i]
        if c in "\"'`":
            # 排除正则字面量里的引号太难，够用：只认合法闭合的
            t = read_string(src, i)
            if t is None:
                i += 1; continue
            yield t
            # 模板内部的 ${} 里还有字符串（嵌套 URL 也要找），单独递归
            if c == "`":
                for kind, txt in t.parts:
                    pass
            i = t.end; continue
        i += 1


# ---------------------------------------------------------------- 前端调用
@dataclass
class Call:
    file: str
    line: int
    path: str                 # 规范化后的路径，参数位 = {}
    method: str               # GET/POST/... 或 "?"（URL 拼在变量里，方法看不出）
    query: list = field(default_factory=list)
    body_keys: list | None = None   # 内联对象字面量的顶层键；None = 看不出
    body_spread: bool = False
    sends_body: bool = False
    kind: str = "call"        # call / href / prefix
    raw: str = ""


PREFIX_DEF = re.compile(r"(?:const|let)\s+([A-Za-z_]\w*)\s*=\s*(?:\(([^)]*)\)\s*(?::\s*\w+\s*)?=>\s*)?$")
OPT_BODY_HELPER = re.compile(r"(?:async\s+)?function\s+(\w+)\s*(?:<[^>]*>)?\s*\(\s*url[^,)]*,\s*body\?")
NAMED_VERB = {"post": "POST", "postjson": "POST", "put": "PUT", "putjson": "PUT", "patch": "PATCH", "del": "DELETE", "delete": "DELETE"}
# const q = new URLSearchParams({ a, b, ep: … }) …… `/api/x?${q}`：q 里的键就是 query 参数
USP_DEF = r"(?:const|let)\s+{name}\s*=\s*new\s+URLSearchParams\(\s*(\{{)"
METHOD_FIRST_HELPER = re.compile(r"(?:async\s+)?function\s+(\w+)\s*(?:<[^>]*>)?\s*\(\s*method\s*:")


def tpl_parts_to_path(parts, prefixes: dict) -> tuple[str, list, str]:
    """→ (规范化路径, query 参数名, 原样)。"""
    segs: list[tuple[str, str]] = []
    raw = ""
    for kind, txt in parts:
        if kind == "expr":
            m = re.fullmatch(r"\s*([A-Za-z_]\w*)\s*(\(.*\))?\s*", txt, re.S)
            if m and m.group(1) in prefixes and (m.group(2) is not None) == prefixes[m.group(1)][1]:
                segs.extend(prefixes[m.group(1)][0])
                raw += "${" + txt + "}"
                continue
        segs.append((kind, txt))
        raw += txt if kind == "lit" else "${" + txt + "}"
    path, query, in_query = "", [], False
    for kind, txt in segs:
        if kind == "lit":
            if not in_query and "?" in txt:
                a, b = txt.split("?", 1)
                path += a; in_query = True; txt = b
            if in_query:
                query += re.findall(r"(?:^|[&?])([A-Za-z_][\w.-]*)=", txt)
            else:
                path += txt
        else:
            # 表达式：里面嵌套的模板 / 字符串里出现 "?x=" / "&x=" → query 参数
            inner = re.findall(r"[?&]([A-Za-z_][\w.-]*)=", txt)
            if inner and (in_query or re.search(r"[`\"']\?", txt) or re.search(r"[`\"']&", txt)):
                query += inner
                if re.search(r"[`\"']\?", txt):
                    in_query = True
                continue
            if in_query:
                continue
            if re.search(r"[`\"']\?", txt):    # 例如 ${kind ? `?kind=${...}` : ""}
                in_query = True
                continue
            path += "{*}" if re.search(r"join\(\s*[\"']/[\"']\s*\)", txt) else "{}"
    path = re.sub(r"\{\}(\{\})+", "{}", path)
    return path, sorted(set(query)), raw


def top_level_keys(obj_src: str) -> tuple[list, bool]:
    """'{ a, b: 1, ...x, "c": 2 }' → (['a','b','c'], spread?)"""
    body = obj_src.strip()[1:-1]
    keys, spread, i, n, start = [], False, 0, len(body), 0
    items = []
    while i <= n:
        if i == n or body[i] == ",":
            items.append(body[start:i]); start = i + 1; i += 1; continue
        c = body[i]
        if c in "\"'`":
            t = read_string(body, i); i = t.end if t else i + 1; continue
        if c in "([{":
            i = skip_code(body, i + 1, {"(": ")", "[": "]", "{": "}"}[c]) + 1; continue
        i += 1
    for it in items:
        it = it.strip()
        if not it:
            continue
        if it.startswith("..."):
            spread = True; continue
        m = re.match(r"""["']?([A-Za-z_$][\w$]*)["']?\s*(?::|$)""", it)
        if m:
            keys.append(m.group(1))
    return keys, spread


def enclosing_call(src: str, start: int):
    """URL 字面量是某个调用的第一个实参（或 call("POST", url) 的第二个）→ (函数名, 方法实参或 None)。"""
    i = start - 1
    while i >= 0 and src[i].isspace():
        i -= 1
    method_arg = None
    if i >= 0 and src[i] == ",":
        j = i - 1
        while j >= 0 and src[j].isspace():
            j -= 1
        m = re.search(r"[\"'](GET|POST|PUT|DELETE|PATCH)[\"']$", src[max(0, j - 10):j + 1])
        if not m:
            return None
        method_arg = m.group(1)
        i = j - len(m.group(0))
        while i >= 0 and src[i].isspace():
            i -= 1
    if i < 0 or src[i] != "(":
        return None
    i -= 1
    while i >= 0 and src[i].isspace():
        i -= 1
    if i >= 0 and src[i] == ">":
        depth = 0
        while i >= 0:
            if src[i] == ">" and src[i - 1:i + 1] != "=>":
                depth += 1
            elif src[i] == "<":
                depth -= 1
                if depth == 0:
                    i -= 1
                    break
            i -= 1
    while i >= 0 and src[i].isspace():
        i -= 1
    j = i
    while j >= 0 and (src[j].isalnum() or src[j] in "_$."):
        j -= 1
    name = src[j + 1:i + 1]
    if not name:
        return None
    return name.split(".")[-1], method_arg


def scan_file(path: Path) -> list[Call]:
    src = strip_comments(path.read_text(encoding="utf-8"))
    rel = path.relative_to(ROOT).as_posix()
    opt_body = set(OPT_BODY_HELPER.findall(src))
    method_first = set(METHOD_FIRST_HELPER.findall(src))
    toks = list(iter_strings(src))
    # 前缀常量：const B = "/api/x"；const P = (slug) => `/api/projects/${...}`
    prefixes: dict[str, tuple[list, bool]] = {}
    for t in toks:
        lit0 = t.parts[0][1] if t.parts and t.parts[0][0] == "lit" else ""
        if not lit0.startswith("/api/"):
            continue
        head = src[max(0, t.start - 120):t.start]
        m = PREFIX_DEF.search(head)
        if m:
            prefixes[m.group(1)] = (t.parts, m.group(2) is not None)
    calls: list[Call] = []

    def emit(t: Tok, parts):
        p, q, raw = tpl_parts_to_path(parts, prefixes)
        mq = re.search(r"\?\$\{\s*([A-Za-z_]\w*)(?:\.toString\(\))?\s*\}", raw)
        if mq:
            md = re.search(USP_DEF.format(name=re.escape(mq.group(1))), src[:t.start])
            if md:
                end = skip_code(src, md.start(1) + 1, "}")
                ks, _sp = top_level_keys(src[md.start(1):end + 1])
                q = sorted(set(q) | set(ks))
        if not p.startswith("/api/"):
            return
        line = src.count("\n", 0, t.start) + 1
        head = src[max(0, t.start - 160):t.start]
        if PREFIX_DEF.search(head):
            calls.append(Call(rel, line, p, "?", q, kind="prefix", raw=raw)); return
        if re.search(r"(href|src)\s*=\s*\{?\s*$", head):
            calls.append(Call(rel, line, p, "GET", q, kind="href", raw=raw)); return
        # 找包着它的函数调用 NAME<...>( …（泛型可跨行、可含括号，倒着配对）
        cm = enclosing_call(src, t.start)
        if not cm:
            calls.append(Call(rel, line, p, "?", q, kind="expr", raw=raw)); return
        callee, method_arg = cm
        verb = NAMED_VERB.get(callee.lower())
        close = skip_code(src, t.end, ")")
        args = src[t.end:close]
        method, sends, keys, spread = None, False, None, False
        if method_arg:
            method = method_arg
            rest = args.lstrip()
            if rest.startswith(","):
                sends = True
        mm = re.search(r"""method\s*:\s*["'`](GET|POST|PUT|DELETE|PATCH)["'`]""", args)
        if mm:
            method = mm.group(1)
        mj = re.search(r"""\b(?:json|body|jsonBody)\s*\(\s*["'](GET|POST|PUT|DELETE|PATCH)["']\s*,""", args)
        if mj:
            method, sends = mj.group(1), True
        mp = re.search(r"\bpost\s*\(", args)
        if mp and not method:
            inner_close = skip_code(args, mp.end(), ")")
            inner = args[mp.end():inner_close]
            mpu = re.search(r""",\s*["'](PUT|POST|DELETE|PATCH)["']\s*$""", inner)
            method, sends = (mpu.group(1) if mpu else "POST"), True
        if re.search(r"\bupload\s*\(", args) and not method:
            method, sends = "POST", False
        if "JSON.stringify" in args or re.search(r"\bbody\s*:", args):
            sends = True if "JSON.stringify" in args else sends
        if method is None and verb:
            method = verb
            rest = args.lstrip()
            sends = rest.startswith(",") and bool(rest[1:].strip())
        if method is None and callee in opt_body:
            rest = args.lstrip()
            if rest.startswith(",") and rest[1:].strip():
                method, sends = "POST", True
            else:
                method = "GET"
        if method is None and callee in method_first:
            method = "GET"
        if method is None:
            method = "GET"
        # 内联请求体字段
        if sends:
            mo = (re.search(r"(?:JSON\.stringify\s*\(|\b(?:json|body|jsonBody)\s*\(\s*[\"'][A-Z]+[\"']\s*,|\bpost\s*\()\s*(\{)", args)
                  or (re.search(r"^\s*,\s*(\{)", args) if (callee in opt_body or method_arg) else None))
            if mo:
                end = skip_code(args, mo.start(1) + 1, "}")
                keys, spread = top_level_keys(args[mo.start(1):end + 1])
        if re.search(r"FormData|\bfd\b", args):
            sends = False  # multipart，不比 JSON 体
        calls.append(Call(rel, line, p, method, q, keys, spread, sends, "call", raw))

    for t in toks:
        lit0 = t.parts[0] if t.parts else ("lit", "")
        first_is_api = lit0[0] == "lit" and lit0[1].startswith("/api/")
        first_is_prefix = lit0[0] == "expr" and re.fullmatch(r"\s*([A-Za-z_]\w*)\s*(\(.*\))?\s*", lit0[1], re.S) \
            and re.fullmatch(r"\s*([A-Za-z_]\w*)", lit0[1].split("(")[0]).group(1) in prefixes
        if first_is_api or first_is_prefix:
            emit(t, t.parts)
    return calls


def scan_frontend(src_dir: Path = WEB_SRC) -> list[Call]:
    out = []
    for p in sorted(src_dir.rglob("*")):
        if p.suffix not in (".ts", ".tsx") or ".bak" in p.name or p.name.endswith(".d.ts"):
            continue
        out += scan_file(p)
    return out


# ---------------------------------------------------------------- OpenAPI
def load_openapi(src: str | None) -> dict:
    if src is None:
        sys.path[:0] = [str(ROOT / "services" / "api"), str(ROOT / "packages")]
        from ns_api.app import app  # noqa: WPS433
        return app.openapi()
    if src.startswith("http"):
        with urllib.request.urlopen(src, timeout=20) as r:
            return json.loads(r.read().decode("utf-8"))
    return json.loads(Path(src).read_text(encoding="utf-8"))


def route_regex(p: str) -> re.Pattern:
    out = ""
    for piece in re.split(r"(\{[^}]+\})", p):
        if piece.startswith("{"):
            out += ".+" if piece.endswith(":path}") or piece in ("{rel}", "{path}") else "[^/]+"
        else:
            out += re.escape(piece)
    return re.compile("^" + out + "$")


def call_regex(p: str) -> re.Pattern:
    out = ""
    for piece in re.split(r"(\{\*?\})", p):
        out += ".*" if piece == "{*}" else "[^/?]*" if piece == "{}" else re.escape(piece)
    return re.compile("^" + out + "$")


def match_routes(call_path: str, paths: dict) -> list[str]:
    """先认字面完全匹配，再认路由参数吃掉前端字面（正向），最后才认前端 ${…} 吃掉路由字面（反向，
    例如 takes/${n}/${on ? "lock" : "unlock"}）；"/{path}"（SPA 兜底）不算。"""
    sample = call_path.replace("{*}", "X1/X2").replace("{}", "X1")
    exact = [p for p in paths if p == call_path.replace("{*}", "{}")]
    if exact:
        return exact
    key = lambda p: -len(re.sub(r"\{[^}]+\}", "", p))  # 字面越多越优先（/api/revisions/keys 胜过 /{key}）
    fwd = sorted((p for p in paths if p != "/{path}" and route_regex(p).match(sample)), key=key)
    if fwd:
        return fwd
    rx = call_regex(call_path)
    return sorted((p for p in paths if p != "/{path}" and rx.match(re.sub(r"\{[^}]+\}", "X1", p))), key=key)


def resolve(schema: dict, spec: dict) -> dict:
    seen = 0
    while isinstance(schema, dict) and "$ref" in schema and seen < 10:
        ref = schema["$ref"].split("/")[-1]
        schema = spec.get("components", {}).get("schemas", {}).get(ref, {})
        seen += 1
    if isinstance(schema, dict) and "anyOf" in schema:
        objs = [resolve(s, spec) for s in schema["anyOf"]]
        objs = [o for o in objs if o.get("type") == "object" or "properties" in o]
        if len(objs) == 1:
            return objs[0]
    if isinstance(schema, dict) and "allOf" in schema and len(schema["allOf"]) == 1:
        return resolve(schema["allOf"][0], spec)
    return schema


@dataclass
class Finding:
    code: str
    sev: str
    file: str
    line: int
    method: str
    path: str
    route: str
    msg: str

    def key(self) -> str:
        return f"{self.code}|{self.file}|{self.method} {self.path}|{self.msg}"


def check(calls: list[Call], spec: dict) -> tuple[list[Finding], list[str]]:
    paths = spec["paths"]
    used: set[tuple[str, str]] = set()
    out: list[Finding] = []
    for c in calls:
        routes = match_routes(c.path, paths)
        if not routes and c.kind == "prefix":
            routes = sorted(p for p in paths if p.startswith(c.path.rstrip("/") + "/"))
        if not routes:
            out.append(Finding("E-ROUTE", "P0", c.file, c.line, c.method, c.path, "", "后端没有这个路由"))
            continue
        if c.method == "?":
            for r in routes:
                for m in paths[r]:
                    used.add((m.upper(), r))
            continue
        hit = next((r for r in routes if c.method.lower() in paths[r]), None)
        if not hit:
            have = sorted({m.upper() for r in routes for m in paths[r]})
            out.append(Finding("E-METHOD", "P0", c.file, c.line, c.method, c.path, routes[0],
                               f"后端此路由只有 {','.join(have)}"))
            continue
        for r in routes:
            if c.method.lower() in paths[r]:
                used.add((c.method, r))
        op = paths[hit][c.method.lower()]
        params = op.get("parameters", [])
        qnames = {p["name"] for p in params if p.get("in") == "query"}
        for p in params:
            if p.get("in") == "query" and p.get("required") and p["name"] not in c.query and c.kind != "prefix":
                # 请求体里带同名字段也读不到（query 必填）
                out.append(Finding("E-REQUIRED", "P0", c.file, c.line, c.method, c.path, hit,
                                   f"必填 query 参数 {p['name']} 没发"))
        for q in c.query:
            if q not in qnames:
                out.append(Finding("W-QUERY", "P1", c.file, c.line, c.method, c.path, hit,
                                   f"query 参数 {q} 后端不认（被忽略；后端有：{','.join(sorted(qnames)) or '无'}）"))
        rb = op.get("requestBody")
        if c.sends_body and not rb and c.method != "GET" and not (c.body_keys == [] and not c.body_spread):
            out.append(Finding("E-BODYKIND", "P0" if qnames else "P2", c.file, c.line, c.method, c.path, hit,
                               "前端发 JSON 体，后端不读请求体" + (f"（只收 query：{','.join(sorted(qnames))}）" if qnames else "")))
        if rb and c.body_keys is not None:
            sch = resolve(rb.get("content", {}).get("application/json", {}).get("schema", {}), spec)
            props = sch.get("properties")
            if props is not None:
                req = set(sch.get("required", []))
                missing = [k for k in sorted(req) if k not in c.body_keys]
                if missing and not c.body_spread:
                    out.append(Finding("E-REQUIRED", "P0", c.file, c.line, c.method, c.path, hit,
                                       f"请求体必填字段没发：{','.join(missing)}"))
                extra = [k for k in c.body_keys if k not in props]
                if extra and sch.get("additionalProperties") is not True:
                    out.append(Finding("W-BODY", "P1", c.file, c.line, c.method, c.path, hit,
                                       f"请求体字段后端模型没有（被静默丢弃）：{','.join(extra)}"))
    unused = sorted(f"{m.upper()} {p}" for p, ops in paths.items() for m in ops
                    if (m.upper(), p) not in used and m.upper() in METHODS and p != "/{path}")
    return out, unused


def load_baseline() -> set[str]:
    if BASELINE.exists():
        return set(json.loads(BASELINE.read_text(encoding="utf-8")).get("known", []))
    return set()


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--openapi", help="URL 或文件；不给 = import ns_api.app 现算")
    ap.add_argument("--json", help="结果写到这个文件")
    ap.add_argument("--calls", action="store_true", help="列出全部前端调用")
    ap.add_argument("--unused", action="store_true", help="列出后端没被前端用到的路由")
    ap.add_argument("--write-baseline", action="store_true", help="把当前 E-* 写成基线（只在确认交给别人修时用）")
    a = ap.parse_args(argv)
    spec = load_openapi(a.openapi)
    calls = scan_frontend()
    findings, unused = check(calls, spec)
    base = load_baseline()
    errs = [f for f in findings if f.code.startswith("E-")]
    new_errs = [f for f in errs if f.key() not in base]
    if a.calls:
        for c in calls:
            print(f"{c.method:6} {c.path:60} {c.file}:{c.line} q={c.query} body={c.body_keys}")
    for f in findings:
        mark = "" if f.key() not in base else " [基线]"
        print(f"{f.sev} {f.code:10} {f.method:6} {f.path}  → {f.route or '-'}  {f.file}:{f.line}  {f.msg}{mark}")
    if a.unused:
        print("\n后端未被前端用到：")
        for u in unused:
            print("  ", u)
    print(f"\n前端调用 {len(calls)} 处；问题 {len(findings)}（E {len(errs)}，其中新 {len(new_errs)}）；后端未用路由 {len(unused)}")
    if a.json:
        Path(a.json).write_text(json.dumps({"calls": [asdict(c) for c in calls], "findings": [asdict(f) for f in findings],
                                            "unused": unused}, ensure_ascii=False, indent=1), encoding="utf-8")
    if a.write_baseline:
        BASELINE.write_text(json.dumps({"known": sorted(f.key() for f in errs),
                                        "note": "已知、已交给 UIRSI 修的前端问题；修好后删掉对应行"}, ensure_ascii=False, indent=1),
                            encoding="utf-8")
    return 1 if new_errs else 0


if __name__ == "__main__":
    sys.exit(main())
