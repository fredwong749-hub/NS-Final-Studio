// 项目方稳定通道（PW-019 / 总调度 11-01）：项目方的 :5173 不再连开发服务器，只看“过了闸门”的生产构建。
// - 静态文件：读 builds/current.txt 指向的那一份构建（换版 = 改这个指针，原子、不停服；回滚 = 指回上一份）。
// - /api、/files：原样转发到 :8800（流式，SSE /api/events 照常工作；Cookie / 登录不变）。
// - 老标签页里的 vite 客户端断线后会探测 / 再整页刷新 → 自动落到稳定版，同一个地址不用重开。
// 用法：node server.mjs            （端口 STABLE_PORT，默认 5173；后端 STABLE_API，默认 http://127.0.0.1:8800）
import http from "node:http";
import { createReadStream, existsSync, readFileSync, statSync } from "node:fs";
import { join, dirname, extname, normalize } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const BUILDS = join(HERE, "builds");
const PORT = +(process.env.STABLE_PORT || 5173);
const HOST = process.env.STABLE_HOST || "127.0.0.1";
const API = new URL(process.env.STABLE_API || "http://127.0.0.1:8800");
const TYPES = { ".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".mjs": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8", ".json": "application/json; charset=utf-8", ".svg": "image/svg+xml", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp", ".ico": "image/x-icon", ".woff2": "font/woff2", ".woff": "font/woff", ".map": "application/json", ".txt": "text/plain; charset=utf-8" };

let ptr = { at: 0, dir: null };
function currentDir() {
  const now = Date.now();
  if (now - ptr.at < 2000 && ptr.dir) return ptr.dir;
  try {
    const name = readFileSync(join(BUILDS, "current.txt"), "utf8").trim();
    const d = join(BUILDS, name);
    if (existsSync(join(d, "index.html"))) ptr = { at: now, dir: d };
  } catch { /* 还没有构建 */ }
  return ptr.dir;
}

function proxy(req, res) {
  const opts = { host: API.hostname, port: API.port || 80, method: req.method, path: req.url, headers: { ...req.headers, host: `${API.hostname}:${API.port}` } };
  const up = http.request(opts, (r) => {
    const h = { ...r.headers };
    res.writeHead(r.statusCode || 502, h);
    if (String(h["content-type"] || "").includes("text/event-stream")) res.flushHeaders?.();
    r.pipe(res);
  });
  up.on("error", () => { if (!res.headersSent) res.writeHead(502, { "content-type": "application/json; charset=utf-8" }); res.end(JSON.stringify({ detail: "后台暂时连不上（:8800），稍后自动重试" })); });
  req.on("aborted", () => up.destroy());
  res.on("close", () => up.destroy());
  req.pipe(up);
}

function send(res, file, cache) {
  const st = statSync(file);
  res.writeHead(200, { "content-type": TYPES[extname(file).toLowerCase()] || "application/octet-stream", "content-length": st.size, "cache-control": cache });
  createReadStream(file).pipe(res);
}

const server = http.createServer((req, res) => {
  const url = new URL(req.url, "http://x");
  if (url.pathname.startsWith("/api/") || url.pathname === "/api" || url.pathname.startsWith("/files/")) return proxy(req, res);
  if (url.pathname === "/__stable") {
    res.writeHead(200, { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" });
    let name = null;
    try { name = readFileSync(join(BUILDS, "current.txt"), "utf8").trim(); } catch { /* */ }
    return res.end(JSON.stringify({ build: name, port: PORT }));
  }
  const dir = currentDir();
  if (!dir) { res.writeHead(503, { "content-type": "text/plain; charset=utf-8", "retry-after": "10" }); return res.end("稳定版还在第一次构建，请 1 分钟后刷新"); }
  if (req.method !== "GET" && req.method !== "HEAD") { res.writeHead(405); return res.end(); }
  const rel = normalize(decodeURIComponent(url.pathname)).replace(/^([/\\])+/, "");
  const file = join(dir, rel);
  if (rel && file.startsWith(dir) && existsSync(file) && statSync(file).isFile()) {
    // 带指纹的资源永久缓存；其余（含 index.html）每次都问
    return send(res, file, /^assets[/\\]/.test(rel) ? "public, max-age=31536000, immutable" : "no-cache");
  }
  // 资源 404 不回首页（避免把 HTML 当 JS）；页面路由回 index.html（单页应用）
  if (/^assets[/\\]/.test(rel)) { res.writeHead(404); return res.end(); }
  return send(res, join(dir, "index.html"), "no-store");
});
server.listen(PORT, HOST, () => console.log(`稳定通道 http://${HOST}:${PORT} → ${currentDir() ?? "（还没有构建）"}；/api → ${API.origin}`));
