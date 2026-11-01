// 声音 · 音色：能听、能比、能换、能改（项目方 2026-10-31：“声音模型那边，我需要监听它的播放……接不接受？能不能修改？我连播放按钮都没有”）。
// 每个人物一行：▶ 试听当前音色（默认念这个人物在剧本里的第一句台词，可改台词）→ 挑附近的音色逐个听 → A/B 连播对比 → “用这个音色”一键换（10 秒可撤销）；
// 语速可调后再听。旁白（远端复刻音色）列出已有样本，能听、能 A/B、点选记下。
// 后端：POST /api/voices/preview（本机 Kokoro，CPU，不花钱）、GET /api/voices/candidates、POST /api/voices/{cid}/select、GET /api/voices/narrator-samples。
import { useEffect, useState } from "react";
import { Button, Empty, LoadError, Skel, Tag } from "../../ds";
import { showUndo } from "../../ds/Undo.helpers";
import { AudioAB, AudioPlayer } from "../../ds/MediaPlayer";

type Ch = { cid: string; name: string; gender?: string; sid?: number; voice?: string; speed?: number; note?: string | null };
type Sample = { name: string; url: string; group: string };

async function previewUrl(body: { cid: string; sid?: number; speed?: number; text?: string }): Promise<string> {
  const r = await fetch("/api/voices/preview", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.detail ?? `HTTP ${r.status}`);
  return j.url as string;
}

// VOICE10（2026-11-01，项目方一键答复“重做候选我来挑”）：series10 有台词的人物只从 data/assets/voices/<cid>_cand/ 取候选
// （GET /api/voices/s10，后端只列过了自动检查的），不再给他们列 Kokoro 的“附近音色”；A = 现在配置里的音色念同样两句（后端合成好、
// 量好时长）；“用 B” = POST /api/voices/{cid}/pick（登录点选即生效，审计自动记），10 秒内可撤销。没挑之前一律标“待你挑”，不替他默认选。
type S10Cand = { cand: string; url: string; ref_url: string; seconds: number | null; text: string; instruct: string; seed: number; checks: { cer?: number; f0_hz?: number; hnr_db?: number; duration_s?: number }; asr?: string; voice: string };
type S10Cur = { kind: string; label: string; voice?: string; cand?: string; url?: string; seconds?: number | null; text?: string; error?: string };
type S10Ch = { cid: string; name: string; gender?: string; age?: number; voice_phrase?: string; current: S10Cur; candidates: S10Cand[]; status: "待你挑" | "已选" | "自动选"; decision?: { quote?: string; reason?: string; auto?: boolean } | null };

const secs = (s?: number | null) => (s == null ? "" : `${s.toFixed(1)} 秒`);

export function VoiceStudio() {
  const [chars, setChars] = useState<Ch[] | null>(null);
  const [s10, setS10] = useState<S10Ch[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  const [names, setNames] = useState<string[] | null>(null);
  const [showOld, setShowOld] = useState(false);
  useEffect(() => {
    fetch("/api/voices/in-script")
      .then((r) => (r.ok ? r.json() : { names: [] }))
      .then((d: { names: string[] }) => setNames(d.names), () => setNames([]));
  }, []);
  useEffect(() => {
    fetch("/api/voices")
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then((d: { characters: Ch[] }) => setChars(d.characters), (e: Error) => setErr(e.message));
    fetch("/api/voices/s10")
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then((d: { characters: S10Ch[] }) => setS10(d.characters), (e: Error) => setErr(`series10 候选：${e.message}`));
  }, [tick]);
  if (err) return <LoadError what="音色" err={err} retry={() => setTick((n) => n + 1)} />;
  if (!chars || !names || !s10) return <Skel h={240} />;
  if (!chars.length && !s10.length) return <Empty icon="♪" title="还没有人物音色" />;
  // series10 的人走新候选（S10Row）；其余有 Kokoro 编号的人 = 旧剧本人物，收起；剧本里有、两边都没有的人单独标出来
  const s10Ids = new Set(s10.map((c) => c.cid));
  const s10Names = new Set(s10.map((c) => c.name));
  const inScript = (c: Ch) => !names.length || names.includes(c.name);
  const legacy = chars.filter((c) => c.sid != null && c.cid !== "narrator" && !s10Ids.has(c.cid) && !s10Names.has(c.name));
  const rows = legacy.filter((c) => showOld || inScript(c));
  const oldN = legacy.filter((c) => !inScript(c)).length;
  const missing = names.filter((n) => !s10Names.has(n) && !chars.some((c) => c.name === n));
  const todo = s10.filter((c) => c.status === "待你挑").length;
  return (
    <section className="vs-wrap">
      <p className="ds-small ds-muted">
        新剧每个有台词的人物都有几个新做的候选音色（文字设计的合成声，念的是这个人物自己的两句台词）。点“候选 N”就和现在的音色 A/B 对比，满意点“用 B”立刻换（10 秒内可撤销）。
        {todo > 0 && <b> 还有 {todo} 个人物待你挑。</b>}
      </p>
      {s10.map((c) => (
        <S10Row key={c.cid} c={c} onChanged={() => setTick((n) => n + 1)} />
      ))}
      {rows.map((c) => (
        <VoiceRow key={c.cid} c={c} onChanged={() => setTick((n) => n + 1)} />
      ))}
      {missing.map((n) => (
        <article key={n} className="vs-row">
          <header className="vs-h">
            <b>{n}</b>
            <Tag tone="warn" size="xs">还没有音色</Tag>
            <span className="ds-small ds-muted">这个人物在新剧本里有台词，还没有配音色；配好后这里就能试听和换</span>
          </header>
        </article>
      ))}
      {oldN > 0 && (
        <button className="ds-btn ghost sm" onClick={() => setShowOld((v) => !v)}>
          {showOld ? "收起" : `旧剧本里的人物（${oldN}）`}
        </button>
      )}
      <Narrator />
    </section>
  );
}

function S10Row({ c, onChanged }: { c: S10Ch; onChanged: () => void }) {
  const [pick, setPick] = useState<S10Cand | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const cur = c.current;
  const label = (k: S10Cand) => `候选 ${c.candidates.indexOf(k) + 1}`;
  const curCand = cur.kind === "cand" ? c.candidates.find((k) => k.cand === cur.cand) : undefined;
  const curLabel = curCand ? label(curCand) : cur.label;
  const choose = async (k: S10Cand) => {
    setMsg(null);
    const r = await fetch(`/api/voices/${encodeURIComponent(c.cid)}/pick`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ cand: k.cand, by: "owner" }) });
    const j = await r.json().catch(() => ({}));
    if (!r.ok) return setMsg(j.detail ?? `HTTP ${r.status}`);
    setPick(null);
    onChanged();
    showUndo(`${c.name} 用了${label(k)}`, async () => {
      const u = await fetch(`/api/voices/pick-undo/${encodeURIComponent(j.undo_id)}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ by: "owner" }) });
      if (!u.ok) setMsg((await u.json().catch(() => ({}))).detail ?? `撤销没成功：HTTP ${u.status}`);
      onChanged();
    });
  };
  const sub = (k: S10Cand) => [secs(k.seconds), k.checks.f0_hz ? `音高 ${Math.round(k.checks.f0_hz)} Hz` : "", k.checks.cer != null ? `回听错字率 ${Math.round(k.checks.cer * 100)}%` : ""].filter(Boolean).join(" · ");
  return (
    <article className="vs-row">
      <header className="vs-h">
        <b>{c.name}</b>
        {c.status === "已选" ? (
          <Tag tone="ok" size="xs">已选 · {curLabel}</Tag>
        ) : c.status === "自动选" ? (
          <Tag tone="info" size="xs" title={`按自动检查选的（项目方原话：${c.decision?.quote ?? ""}）
${c.decision?.reason ?? ""}`}>
            按检查自动选 · {curLabel}（可一键换）
          </Tag>
        ) : (
          <Tag tone="warn" size="xs">待你挑</Tag>
        )}
        {c.voice_phrase && (
          <span className="ds-small ds-muted vs-note" title="写作模型 P1 里给这个人物写的声音描述（原文）">
            {c.voice_phrase}
          </span>
        )}
      </header>
      <div className="vs-ctl">
        <span className="ds-small">
          现在：{curLabel}
          {cur.seconds != null && <span className="ds-muted"> · {secs(cur.seconds)}</span>}
        </span>
        {cur.error && <span className="ds-small vs-err">{cur.error}</span>}
      </div>
      {cur.url && !pick && <AudioPlayer src={cur.url} title={`现在的音色 · ${curLabel}`} sub={cur.text} compact />}
      {c.candidates.length ? (
        <div className="vs-cands">
          <span className="ds-small ds-muted">挑一个候选听：</span>
          {c.candidates.map((k) => (
            <button key={k.cand} className={`vs-cand${pick?.cand === k.cand ? " on" : ""}`} title={`${k.voice}\n设计描述：${k.instruct}\nseed ${k.seed}\n${sub(k)}\n回听：${k.asr ?? ""}`} onClick={() => setPick(pick?.cand === k.cand ? null : k)}>
              {label(k)}
              {curCand?.cand === k.cand && <b className="vs-cur">现在在用</b>}
            </button>
          ))}
        </div>
      ) : (
        <p className="ds-small ds-muted">候选还在做，做好、过了自动检查就会出现在这里</p>
      )}
      {pick && cur.url && (
        <AudioAB
          a={{ src: cur.url, label: `A · 现在：${curLabel}`, sub: secs(cur.seconds) }}
          b={{ src: pick.url, label: `B · ${label(pick)}`, sub: sub(pick) }}
          picked={curCand?.cand === pick.cand ? "b" : null}
          onPick={(k) => (k === "b" ? void choose(pick) : setPick(null))}
        />
      )}
      {pick && !cur.url && (
        <div className="vs-ctl">
          <AudioPlayer src={pick.url} title={label(pick)} sub={sub(pick)} compact />
          <Button size="sm" variant="primary" onClick={() => void choose(pick)}>
            用这个
          </Button>
        </div>
      )}
      {msg && <p className="ds-small vs-err">{msg}</p>}
    </article>
  );
}

function VoiceRow({ c, onChanged }: { c: Ch; onChanged: () => void }) {
  const [text, setText] = useState("");
  const [speed, setSpeed] = useState(c.speed ?? 1);
  const [cands, setCands] = useState<number[] | null>(null);
  const [pick, setPick] = useState<number | null>(null);
  const [cur, setCur] = useState<string | null>(null); // 当前音色试听地址（播放器用全站统一的 MediaPlayer）
  const [alt, setAlt] = useState<string | null>(null); // 候选音色试听地址
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const make = async (sid: number, spd = speed) => {
    setMsg(null);
    setBusy(`${sid}`);
    try {
      return await previewUrl({ cid: c.cid, sid, speed: spd, text: text || undefined });
    } catch (e) {
      setMsg((e as Error).message);
      return null;
    } finally {
      setBusy(null);
    }
  };
  const openCands = () =>
    fetch(`/api/voices/candidates?cid=${encodeURIComponent(c.cid)}`)
      .then((r) => r.json())
      .then((d: { near: number[] }) => setCands(d.near.filter((s) => s !== c.sid)));
  const select = async (sid: number) => {
    const prev = { sid: c.sid!, speed: c.speed ?? 1 };
    const r = await fetch(`/api/voices/${encodeURIComponent(c.cid)}/select`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ sid, speed, by: "owner" }) });
    if (!r.ok) return setMsg((await r.json().catch(() => ({}))).detail ?? `HTTP ${r.status}`);
    onChanged();
    showUndo(`${c.name} 换了音色`, async () => {
      await fetch(`/api/voices/${encodeURIComponent(c.cid)}/select`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ sid: prev.sid, speed: prev.speed, by: "owner" }) });
      onChanged();
    });
  };
  return (
    <article className="vs-row">
      <header className="vs-h">
        <b>{c.name}</b>
        {c.note && (
          <span className="ds-small ds-muted vs-note" title={`${c.note}（音色编号 ${c.sid}）`}>
            {c.note}
          </span>
        )}
      </header>
      <div className="vs-ctl">
        <Button variant="primary" size="sm" disabled={!!busy} onClick={async () => setCur(await make(c.sid!))}>
          {busy === `${c.sid}` ? "合成中…" : cur ? "↻ 重新合成" : "▶ 试听"}
        </Button>
        <input className="ds-input vs-text" value={text} onChange={(e) => setText(e.target.value)} placeholder="试听台词（空 = 剧本里这个人物的第一句）" />
        <label className="vs-speed">
          语速 {speed.toFixed(2)}
          <input type="range" min={0.8} max={1.25} step={0.05} value={speed} onChange={(e) => setSpeed(Number(e.target.value))} />
        </label>
        {speed !== (c.speed ?? 1) && (
          <Button size="sm" onClick={() => void select(c.sid!)} title="只改语速，音色不变">
            用这个语速
          </Button>
        )}
        {!cands && (
          <Button size="sm" variant="ghost" onClick={() => void openCands()}>
            换音色…
          </Button>
        )}
      </div>
      {cur && !alt && <AudioPlayer src={cur} title="现在的音色" sub={text || "剧本里的第一句台词"} compact />}
      {cands && (
        <div className="vs-cands">
          <span className="ds-small ds-muted">挑一个候选听：</span>
          {cands.map((sid, i) => (
            <button
              key={sid}
              className={`vs-cand${pick === sid ? " on" : ""}`}
              disabled={!!busy}
              title={`音色编号 ${sid}`}
              onClick={async () => {
                setPick(sid);
                const [a, b] = await Promise.all([cur ? Promise.resolve(cur) : make(c.sid!), make(sid)]);
                if (a) setCur(a);
                setAlt(b);
              }}
            >
              {busy === `${sid}` ? "…" : `候选 ${i + 1}`}
            </button>
          ))}
        </div>
      )}
      {cur && alt && pick != null && (
        <AudioAB
          a={{ src: cur, label: "A · 现在的音色" }}
          b={{ src: alt, label: `B · 候选 ${(cands?.indexOf(pick) ?? 0) + 1}` }}
          onPick={(k) => (k === "b" ? void select(pick) : setAlt(null))}
        />
      )}
      {msg && <p className="ds-small vs-err">{msg}</p>}
    </article>
  );
}

function Narrator() {
  const [d, setD] = useState<{ current: string | null; samples: Sample[] } | null>(null);
  const [a, setA] = useState<Sample | null>(null);
  const [b, setB] = useState<Sample | null>(null);
  useEffect(() => {
    fetch("/api/voices/narrator-samples")
      .then((r) => (r.ok ? r.json() : null))
      .then(setD, () => setD(null));
  }, []);
  if (!d || !d.samples.length) return null;
  const pickSample = async (s: Sample) => {
    const r = await fetch("/api/voices/narrator/proposals", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ changes: { voice: s.name }, by: "owner", note: `旁白选用样本 ${s.name}` }),
    });
    showUndo(r.ok ? `旁白选了 ${s.name}（下次合成按这个配）` : `没记上：HTTP ${r.status}`, async () => undefined, r.ok ? 6000 : 4000);
  };
  return (
    <article className="vs-row">
      <header className="vs-h">
        <b>旁白</b>
        <span className="ds-small ds-muted">旁白用远端复刻音色，这里列出已经合成好的样本：点 ▶ 听，选两个可以 A/B 连播</span>
      </header>
      {groupSamples(d.samples).map(([g, list]) => (
      <div key={g} className="vs-group">
      <span className="vs-group-h">{g}</span>
      <div className="vs-cands">
        {list.map((s) => (
          <span key={s.url} className={`vs-sample${a?.url === s.url ? " a" : ""}${b?.url === s.url ? " b" : ""}${isCurrent(s.name) ? " cur" : ""}`}>
            <button className="vs-cand" onClick={() => (a && !b && a.url !== s.url ? setB(s) : (setA(s), setB(null)))} title={s.group ? `${s.group} / ${s.name}` : s.name}>
              ▶ {sampleName(s.name)}
              {isCurrent(s.name) && <b className="vs-cur">现在在用</b>}
            </button>
          </span>
        ))}
      </div>
      </div>
      ))}
      {a && b && <AudioAB a={{ src: a.url, label: `A · ${sampleName(a.name)}` }} b={{ src: b.url, label: `B · ${sampleName(b.name)}` }} onPick={(k) => void pickSample(k === "a" ? a : b)} />}
      {a && !b && (
        <div className="vs-ctl">
          <AudioPlayer src={a.url} title={sampleName(a.name)} sub="再点一个样本就能 A/B 对比" compact />
          <Button size="sm" variant="primary" onClick={() => void pickSample(a)}>
            旁白用这个
          </Button>
        </div>
            )}
    </article>
  );
}

const STYLE: Record<string, string> = { A: "深夜电台", B: "时尚播客", C: "有声书", D: "知性丝绒" };
/** 现在旁白用的是 QAg（深夜电台 · 温柔；config/voices.json narrator） */
const isCurrent = (n: string) => /(^|_)QAg$/.test(n);
/** 样本分组：第二轮设计音色（Q）/ 第二轮复刻对照（X）/ 第一轮女声 / 其他 */
function groupSamples(list: Sample[]): [string, Sample[]][] {
  const g = new Map<string, Sample[]>();
  for (const s of list) {
    const k = /(^|_)Q[A-D][a-z]$/.test(s.name) ? "设计音色（第二轮，推荐）" : /(^|_)X[A-D][a-z]$/.test(s.name) ? "复刻对照（第二轮）" : /z[fm]_\d{3}/.test(s.name) ? "现成女声（第一轮）" : "其他试听";
    g.set(k, [...(g.get(k) ?? []), s]);
  }
  const order = ["设计音色（第二轮，推荐）", "复刻对照（第二轮）", "现成女声（第一轮）", "其他试听"];
  return order.filter((k) => g.has(k)).map((k) => [k, g.get(k)!]);
}

/** 样本文件名 → 人话：QAg → “深夜电台 · 温柔”；zf_072_sp105 → “女声 072 · 稍快”（文件名放悬停） */
function sampleName(n: string): string {
  const q = /(?:^|_)([QX])([A-D])([a-z])$/.exec(n);
  if (q) return `${STYLE[q[2]] ?? `风格 ${q[2]}`} · ${q[3] === "g" ? "温柔" : "明亮"}${q[1] === "X" ? "（复刻）" : ""}`;
  const v = /z([fm])_(\d{3})/.exec(n);
  const sp = /sp(\d{3})/.exec(n);
  const speed = sp ? (Number(sp[1]) > 100 ? " · 稍快" : Number(sp[1]) < 100 ? " · 稍慢" : "") : "";
  if (v) return `${v[1] === "f" ? "女声" : "男声"} ${v[2]}${speed}`;
  const e = /ep(\d+)_S(\d+)/.exec(n);
  if (e) return `第 ${Number(e[1])} 集 镜 ${e[2]} 实际旁白`;
  return n.replace(/_/g, " ");
}
