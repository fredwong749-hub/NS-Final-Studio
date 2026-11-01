// PRODUCER（总调度 11-01）：#/script-create?run=… 上的“自动制作中”面板。
// 项目方原话：“自动执行对应制作,人类不应该点,坏了,系统自动做”。制作由常驻服务 tools/autopilot/producer.py 推进，
// 这里只读 GET /api/producer/status（data/producer/registry.json，与 GPUVIEW 渲染任务同一份），实时显示：
// 每集一句话 + 每镜 首帧 / 尾帧 / 视频 的状态、在等什么、在哪条道做、第几次（n/3）、自动修复原因；每集 声音 / 配乐 / 合成 / 审片页。
// 只有项目方本人的事（闸门）才出现“要你处理”的卡片；暂停 / 继续 = 项目方覆盖。手动按钮仍在页头“⋯ 手动插队 / 重做”里（G10 不删）。
// 样式类名 ns-prod*（归 UIPIXEL）；没有样式时也能读。
import { useCallback, useEffect, useState } from "react";
import { Button, Tag, type Tone } from "../ds";
import { useLiveEvent } from "./live";

type Obj = {
  id: string;
  kind: string;
  label: string;
  status: "pending" | "ready" | "running" | "passed" | "failed" | "best_effort";
  attempts?: number;
  max_attempts?: number | null;
  last_error?: string | null;
  reason?: string | null;
  waiting_for?: string | null;
  where?: string | null;
  review?: string | null;
};
type Shot = { shot: string; index: number; objects: Record<string, Obj> };
type Ep = { ep: number; title?: string; headline: string; objects: Record<string, Obj>; shots: Shot[]; counts: Record<string, number> };
type Gate = { id: string; gate: string; what: string; where: string; status: string; at: string };
type LogRow = { ts: string; ev: string; obj?: string; reason?: string; why?: string; lane?: string; attempt?: number; next?: string; error?: string };
type Status = {
  run?: string;
  active?: boolean;
  service_alive?: boolean;
  heartbeat_age_s?: number | null;
  paused?: boolean;
  paused_by?: string | null;
  updated?: string;
  counts?: Record<string, number>;
  episodes?: Ep[];
  gates?: Gate[];
  lanes?: Record<string, { free: boolean; why?: string | null }>;
  log?: LogRow[];
  note?: string;
};

const ST: Record<Obj["status"], [string, Tone]> = {
  pending: ["等前一步", "neutral"],
  ready: ["排队", "info"],
  running: ["进行中", "busy"],
  passed: ["已通过", "ok"],
  failed: ["没过", "bad"],
  best_effort: ["尽力", "warn"],
};
const EV: Record<string, string> = {
  dispatch: "派出",
  rendered: "出完",
  passed: "通过",
  content_fail: "没过，自动重出",
  best_effort: "标尽力",
  infra_error: "基础设施出错，换道重来（不计次）",
  preflight_block: "出图前检查没过",
  owner_gate: "停在你的闸门",
  video_release: "自动放行出视频",
  pause: "暂停",
  resume: "继续",
  na: "不需要尾帧",
};

// UIMASTER UM-0245…0259：格子里只给项目方看人话；会话名 / 道号 / 脚本名只放悬停提示（技术细节）
const DOING: Record<string, string> = { first: "出首帧", last: "出尾帧", video: "出视频" };
const AGENT_WORDS: [RegExp, string][] = [
  [/ASSETMASTER\s*frames_v2/g, "资产组在出"],
  [/VIDEO10\s*night\.py/g, "视频队列"],
  [/\bVIDEO10\b/g, "视频"],
  [/\bVOICE10\b/g, "配音"],
  [/\bBGM10\b/g, "配乐"],
  [/\bPRODUCER\b/g, "系统"],
  [/\bASSETMASTER\b/g, "资产组"],
  [/gpu(33|36):(\d)/g, "显卡 $1-$2"],
  [/config\/voices\.json[^）)]*/g, "演员表"],
  [/data\/music\/series10\/ep\d+\.wav/g, "本集配乐"],
  [/（缺时合成用 --no-bgm[^）]*）/g, ""],
  [/K-[A-Z]+-[A-Z0-9]+/g, ""],
];
function plain(t?: string | null): string {
  let s = t ?? "";
  for (const [re, w] of AGENT_WORDS) s = s.replace(re, w);
  return s.replace(/（\s*）/g, "").trim();
}
function cellText(o: Obj): string {
  const n = o.max_attempts && (o.attempts ?? 0) > 0 && o.status !== "passed" ? ` · 第 ${o.attempts}/${o.max_attempts} 次` : "";
  const word = o.status === "running" ? DOING[o.kind] ?? "进行中" : o.status === "passed" ? "已定下" : ST[o.status]?.[0] ?? o.status;
  return `${word}${n}`;
}
function cellTip(o: Obj): string {
  return [
    o.label,
    o.reason,
    o.review && `待目检：${o.review}`,
    o.waiting_for && `在等：${o.waiting_for}`,
    o.where && `技术细节：${o.where}`,
    o.last_error && `上次错误：${o.last_error}`,
  ]
    .filter(Boolean)
    .join("\n");
}

function Cell({ o }: { o?: Obj }) {
  if (!o) return <td>—</td>;
  const [, tone] = ST[o.status] ?? ["", "neutral"];
  const note = o.status === "passed" ? "" : plain(o.status === "pending" || o.status === "ready" ? o.waiting_for ?? o.reason : o.reason ?? o.waiting_for);
  return (
    <td className={`ns-prod-cell st-${o.status}`} title={cellTip(o)} style={{ verticalAlign: "top", maxWidth: 260, overflowWrap: "anywhere" }}>
      <Tag tone={tone} dot size="s">
        {cellText(o)}
      </Tag>
      {o.review && (
        <div className="ds-small" title={`${o.review}（只记录，不挡；留给总调度看印样）`}>
          <Tag tone="warn" size="s">
            待目检
          </Tag>{" "}
          {plain(o.review)}
        </div>
      )}
      {note && <div className="ds-small ds-muted">{note}</div>}
    </td>
  );
}

export function ProducerPanel({ run }: { run: string }) {
  const [s, setS] = useState<Status | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [open, setOpen] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const load = useCallback(() => {
    fetch(`/api/producer/status?run=${encodeURIComponent(run)}`)
      .then(async (r) => {
        if (r.status === 404) throw new Error("制作监督接口还没接上（API 需要重启一次）");
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return (await r.json()) as Status;
      })
      // PW-009：读失败（如 :8800 重启窗口 502）保留上一次的数据，只加一个“暂时读不到”的小标记，不卸整块
      .then((d) => (setS(d), setErr(null)), (e: Error) => setErr(e.message));
  }, [run]);
  useEffect(() => {
    load();
    const t = window.setInterval(load, 15000);
    return () => window.clearInterval(t);
  }, [load]);
  // 制作状态一变，PRODUCER 重写 runs/<run>/_producer.json → live.py 推 stage 事件；素材 / 任务变化也顺带重取
  useLiveEvent((e) => (e.type === "stage" && (!e.run || e.run === run)) || ["frame", "lastframe", "video", "job", "cut"].includes(e.type), load, 1500);

  async function post(path: string, body: unknown) {
    setBusy(true);
    try {
      await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      load();
    } finally {
      setBusy(false);
    }
  }

  if (err && !s) {
    return (
      <section className="ns-prod" aria-label="自动制作">
        <Tag tone="warn" dot>
          自动制作状态读不到
        </Tag>{" "}
        <span className="ds-small ds-muted">{err}</span>
      </section>
    );
  }
  // PW-003：首屏骨架与真实内容同结构（页头 + 10 集各一行），数据到了不撑高
  if (!s)
    return (
      <section className="ns-prod ns-prod-skel" aria-hidden>
        <header className="ns-prod-h">
          <Tag tone="neutral" dot>
            自动制作
          </Tag>
        </header>
        <div className="ns-prod-eps">
          {Array.from({ length: 10 }, (_, i) => (
            <div key={i} className="ns-prod-ep">
              <button type="button" className="ns-prod-ep-h" disabled>
                <b>第 {i + 1} 集</b> <span className="ds-small ds-muted">…</span>
              </button>
            </div>
          ))}
        </div>
      </section>
    );
  if (s.note && !s.episodes) {
    return (
      <section className="ns-prod" aria-label="自动制作">
        <span className="ds-small ds-muted">{s.note}</span>
      </section>
    );
  }
  const eps = s.episodes ?? [];
  const gates = (s.gates ?? []).filter((g) => g.status === "open");
  const head: [string, Tone] = !s.service_alive ? ["制作监督没在跑（开机自启会拉起）", "bad"] : s.paused ? [`已暂停${s.paused_by ? `（${s.paused_by}）` : ""}`, "warn"] : ["自动制作中", "busy"];
  const c = s.counts ?? {};
  const fixes = (s.log ?? []).filter((l) => ["content_fail", "best_effort", "infra_error", "preflight_block", "video_release", "owner_gate"].includes(l.ev)).slice(-8).reverse();
  return (
    <section className="ns-prod" aria-label="自动制作" style={{ position: "relative", clear: "both", overflow: "hidden" }}>
      <header className="ns-prod-h">
        <Tag tone={head[1]} dot>
          {head[0]}
        </Tag>
        <span className="ds-small ds-muted" title="全部对象（剧本 / 导入 / 资产 / 每镜首帧尾帧视频 / 每集声音配乐合成审片页）">
          通过 {c.passed ?? 0} · 进行中 {c.running ?? 0} · 排队 {c.ready ?? 0} · 等前一步 {c.pending ?? 0}
          {c.best_effort ? ` · 尽力 ${c.best_effort}` : ""}
          {c.failed ? ` · 没过 ${c.failed}` : ""}
          {s.heartbeat_age_s != null ? ` · ${Math.round(s.heartbeat_age_s)} 秒前更新` : ""}
        </span>
        {err && (
          <Tag tone="warn" size="s" title={err}>
            暂时读不到，显示的是上一次
          </Tag>
        )}
        <span style={{ marginLeft: "auto" }}>
          {s.paused ? (
            <Button size="xs" disabled={busy} onClick={() => void post("/api/producer/resume", { by: "owner" })} title="继续自动制作">
              继续
            </Button>
          ) : (
            <Button size="xs" variant="ghost" disabled={busy || !s.service_alive} why="制作监督没在跑" onClick={() => void post("/api/producer/pause", { by: "owner" })} title="暂停：不再派新活，在跑的跑完">
              暂停
            </Button>
          )}
        </span>
      </header>
      {gates.length > 0 && (
        <div className="ns-prod-gates" role="alert">
          <b>要你处理（{gates.length}）</b>
          {gates.map((g) => (
            <div key={g.id} className="ns-prod-gate">
              <span>{plain(g.what)}</span> <span className="ds-small ds-muted">在：{plain(g.where)}</span>{" "}
              <Button size="xs" disabled={busy} onClick={() => void post("/api/producer/gate", { id: g.id, by: "owner" })}>
                已处理
              </Button>
            </div>
          ))}
        </div>
      )}
      <div className="ns-prod-eps">
        {eps.map((e) => (
          <div key={e.ep} className={`ns-prod-ep${open === e.ep ? " on" : ""}`}>
            <button type="button" className="ns-prod-ep-h" onClick={() => setOpen(open === e.ep ? null : e.ep)} aria-expanded={open === e.ep} title={`第 ${e.ep} 集：${e.headline}`}>
              <b>第 {e.ep} 集</b> <span className="ds-small">{plain(e.headline)}</span>
            </button>
            {open === e.ep && (
              <div className="ns-prod-ep-b">
                <div className="ns-prod-tw" style={{ overflowX: "auto", maxWidth: "100%" }}>
                <table className="ns-prod-t" style={{ tableLayout: "fixed", width: "100%" }}>
                  <thead>
                    <tr>
                      <th>镜</th>
                      <th>首帧</th>
                      <th>尾帧</th>
                      <th>视频</th>
                    </tr>
                  </thead>
                  <tbody>
                    {e.shots.map((sh) => (
                      <tr key={sh.shot}>
                        <td>
                          <b>{sh.shot.split("-")[1]}</b>
                          {sh.objects.assets?.status === "failed" && (
                            <div className="ds-small" title={sh.objects.assets.reason ?? ""}>
                              <Tag tone="bad" size="s">
                                资料不全
                              </Tag>
                            </div>
                          )}
                        </td>
                        <Cell o={sh.objects.first} />
                        <Cell o={sh.objects.last} />
                        <Cell o={sh.objects.video} />
                      </tr>
                    ))}
                  </tbody>
                </table>
                </div>
                <div className="ns-prod-epobjs ds-small">
                  {(["voice", "bgm", "assembly", "preview"] as const).map((k) => {
                    const o = e.objects[k];
                    if (!o) return null;
                    return (
                      <span key={k} title={cellTip(o)} style={{ marginRight: 12 }}>
                        {o.label}：
                        <Tag tone={ST[o.status]?.[1] ?? "neutral"} size="s">
                          {ST[o.status]?.[0] ?? o.status}
                        </Tag>{" "}
                        <span className="ds-muted">{o.status === "passed" ? "" : plain(o.waiting_for ?? o.reason ?? "")}</span>
                      </span>
                    );
                  })}
                </div>
              </div>
            )}
          </div>
        ))}
      </div>
      {fixes.length > 0 && (
        <details className="ns-prod-log">
          <summary className="ds-small">自动修复记录（最近 {fixes.length} 条）</summary>
          <ul className="ds-small">
            {fixes.map((l, i) => (
              <li key={i}>
                {l.ts.slice(11)} {l.obj ?? ""} {EV[l.ev] ?? l.ev}
                {plain(l.reason ?? l.why ?? "")}
                {l.next ? ` → ${l.next}` : ""}
              </li>
            ))}
          </ul>
        </details>
      )}
    </section>
  );
}
