// UIRSI r12（UIDEBUG W-02：页面打开时 50–135 个并发请求排队）：同一个 GET /api/… 正在飞的时候不再发第二次，
// 刚回来 1.5 s 内的同一请求直接复用（每个调用方拿 Response.clone()）。只管 GET；POST / PUT / DELETE 照常发。
// 轮询间隔都 ≥2.5 s，不受影响；开发态 StrictMode 的重复挂载、多个组件读同一接口都会合并成一次。
const TTL = 1500;
type Entry = { p: Promise<Response>; done: number | null };
const inflight = new Map<string, Entry>();
const orig = window.fetch.bind(window);
export const netStats = { saved: 0, sent: 0 };

window.fetch = (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
  const method = (init?.method ?? (input instanceof Request ? input.method : "GET")).toUpperCase();
  const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
  if (method !== "GET" || !/\/api\//.test(url) || init?.signal || init?.body) {
    return orig(input, init);
  }
  const key = new URL(url, location.href).href;
  const e = inflight.get(key);
  if (e && (e.done == null || Date.now() - e.done < TTL)) {
    netStats.saved++;
    return e.p.then((r) => r.clone());
  }
  netStats.sent++;
  const p = orig(input, init);
  const entry: Entry = { p, done: null };
  inflight.set(key, entry);
  p.then(
    (r) => {
      entry.done = Date.now();
      if (!r.ok) inflight.delete(key); // 失败的不复用，下次照常重试
      setTimeout(() => inflight.get(key) === entry && inflight.delete(key), TTL + 50);
    },
    () => inflight.delete(key),
  );
  return p.then((r) => r.clone());
};
