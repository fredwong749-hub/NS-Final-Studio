// fredw-92/U3：资产页「场景」页签（项目方新需求），接 GET /api/assets/scenes（S-back）。
// 场景卡：底图大图（没有 → “未生成底图”）、名称、时段、出现集数 / 镜数、变体（主底图 / 机位…）、定稿状态；
// 点开用同一个 AssetDrawer（kind = scene，参考用途 空间 / 风格 / 色彩 / 道具）。接口未上线 → “后端未就绪”。
// fredw-92/UXF3（UX 审查 #38）：每张卡“上传底图”（选变体）+“生成候选”（打开抽屉）；顶部“为本集缺底图的场景生成候选”：
// 每个场景一条 gen-job，提示词 = 剧本场景表原文（不改写、不补全；没有原文的跳过并说明），确认框列出数量 / 用道 / 预计时间，项目方点了才提交。
import { useEffect, useMemo, useRef, useState } from "react";
import { useStudio } from "../../store";
import type { LightEpisode } from "../api_v1_pages";
import {
  defaultImagePreset, laneText, loadLanes, loadScenes, plateUrl, sceneName, sceneNotReady, sceneTableText, submitSceneGen, timeLabel,
  uploadPlate, variantLabel, type Lane, type SceneView,
} from "./scenes_api";

const VARIANTS = ["main", "low", "top", "wide", "close", "night"];
const GEN_S = 60; // 单张预计秒数（同抽屉 / 后端 eta_s）

function status(s: SceneView): { t: string; k: "ok" | "warn" | "" } {
  const p = s.plate;
  if (!p) return { t: "", k: "" };
  if (p.s2_gate_ok || p.plate_status === "owner_confirmed") return { t: "项目方已确认", k: "ok" };
  if (p.locked) return { t: "已定稿", k: "ok" };
  if (p.url) return { t: "候选 · 未定稿", k: "warn" };
  return { t: "", k: "" };
}
const fmtMin = (s: number) => (s < 90 ? `约 ${Math.max(1, Math.round(s))} 秒` : s < 5400 ? `约 ${Math.round(s / 60)} 分钟` : `约 ${(s / 3600).toFixed(1)} 小时`);

export default function ScenesTab({ onOpen }: { eps?: LightEpisode[] | null; onOpen: (s: SceneView, label: string) => void }) {
  const studio = useStudio();
  const ep = studio.epNum;
  const [list, setList] = useState<SceneView[] | null>(null);
  const [err, setErr] = useState<{ t: string; notReady: boolean } | null>(null);
  const [q, setQ] = useState("");
  const [onlyEp, setOnlyEp] = useState(false);
  const [reload, setReload] = useState(0);
  const [upload, setUpload] = useState<SceneView | null>(null);
  const [batch, setBatch] = useState(false);
  const [submitted, setSubmitted] = useState<Record<string, string>>({});

  useEffect(() => {
    let alive = true;
    loadScenes()
      .then((r) => alive && setList(r))
      .catch((e) => alive && setErr({ t: String((e as Error)?.message ?? e), notReady: sceneNotReady(e) }));
    return () => {
      alive = false;
    };
  }, [reload]);

  if (err)
    return err.notReady ? (
      <div className="v3p-notready">场景列表暂时读不到，后台恢复后自动显示。</div>
    ) : (
      <p className="v3p-err">{err.t}</p>
    );
  if (!list) return <p className="v3p-muted">加载场景…</p>;
  const shown = list.filter(
    (s) =>
      (!onlyEp || (s.episodes ?? []).includes(ep)) &&
      (!q || `${sceneName(s)} ${s.scene_id} ${s.description?.space ?? ""}`.toLowerCase().includes(q.toLowerCase())),
  );
  const nPlate = list.filter((s) => plateUrl(s)).length;
  const nLocked = list.filter((s) => s.plate?.locked || s.plate?.s2_gate_ok).length;
  const epMissing = list.filter((s) => (s.episodes ?? []).includes(ep) && !plateUrl(s));
  // UXF5（审查 N15）：按钮上的数字 = 点开后真正会提交的个数（缺场景表原文的会被跳过，单独写）
  const epSubmit = epMissing.filter((s) => sceneTableText(s)).length;
  const epNoText = epMissing.length - epSubmit;

  return (
    <>
      <div className="v3p-scenebar">
        <b>{list.length} 个场景</b>
        <span className="v3p-muted">
          有底图 {nPlate} · 已定稿 {nLocked} · 未生成 {list.length - nPlate}
        </span>
        <label className="v3p-chk">
          <input type="checkbox" checked={onlyEp} onChange={(e) => setOnlyEp(e.target.checked)} /> 只看第 {ep} 集用到的
        </label>
        <span className="grow" />
        <button
          className="btn-mini"
          onClick={() => setBatch(true)}
          title={`第 ${ep} 集缺底图 ${epMissing.length} 个：能提交 ${epSubmit} 个${epNoText ? `，${epNoText} 个剧本场景表里没有描述会跳过` : ""}。确认框里会列出每个场景要发的原文、用道和预计时间，你点了才提交`}
        >
          为第 {ep} 集缺底图的场景生成候选（{epSubmit} 个）{epNoText ? ` · ${epNoText} 个缺原文` : ""}…
        </button>
        <input className="v3p-scenesearch" placeholder="按名字筛选" value={q} onChange={(e) => setQ(e.target.value)} aria-label="按名字筛选场景" />
      </div>
      {!shown.length && <p className="v3p-muted">{list.length ? "没有符合的场景。" : "还没有场景。"}</p>}
      <div className="v3p-scenes">
        {shown.map((s) => {
          const url = plateUrl(s);
          const name = sceneName(s);
          const st = status(s);
          const label = `场景 · ${name}`;
          const times = s.description?.times?.length ? s.description.times : s.description?.time_of_day ? [s.description.time_of_day] : [];
          const vars = (s.variants ?? []).filter((v) => v.variant !== "main");
          const eps = s.episodes ?? [];
          const text = sceneTableText(s);
          const sub = submitted[s.scene_id];
          return (
            <div key={s.scene_id} className="v3p-scene">
              {url ? (
                <button className="v3p-scene-img" onClick={() => onOpen(s, label)} title={`${name} · 点开编辑`}>
                  <img src={url} alt="" loading="lazy" />
                  {st.t && <span className={`v3p-badge v3p-scene-st ${st.k}`}>{st.t}</span>}
                </button>
              ) : (
                <div className="v3p-scene-img none">
                  {sub && <span className="v3p-badge busy v3p-scene-sub">{sub}</span>}
                  <span className="v3p-scene-none">无底图</span>
                  <div className="v3p-scene-acts">
                    <button className="btn-mini" onClick={() => setUpload(s)}>上传底图</button>
                    <button className="btn-mini v3p-scene-gen" onClick={() => onOpen(s, label)} title="打开编辑器：选参考、写提示词、生成，结果进修改链">生成候选</button>
                  </div>
                </div>
              )}
              <div className="v3p-scene-meta">
                <b title={s.scene_id}>{name}</b>
                <span className="v3p-muted">
                  出现 {s.episode_count ?? eps.length} 集 · {s.shot_count ?? 0} 镜
                  {eps.length ? `（第 ${eps[0]}${eps.length > 1 ? `–${eps[eps.length - 1]}` : ""} 集）` : ""}
                </span>
                {text ? (
                  <span className="v3p-scene-text" title={text}>{text}</span>
                ) : (
                  <span className="v3p-scene-text warn" title="批量生成只发剧本场景表原文；这一场没有，就不会批量提交">剧本场景表没有这一场的描述</span>
                )}
                {(times.length > 0 || vars.length > 0) && (
                  <div className="v3p-scene-vars">
                    {times.map((t) => (
                      <span key={`t:${t}`} className="v3p-badge" title="时段">{timeLabel(t)}</span>
                    ))}
                    {vars.map((v) => (
                      <span key={v.variant} className={`v3p-badge${v.locked ? " ok" : ""}`} title={v.locked ? "已定稿" : "候选"}>
                        {variantLabel(v.variant)}
                        {v.locked ? " ✓" : ""}
                      </span>
                    ))}
                  </div>
                )}
              </div>
              {url && (
                <div className="v3p-scene-acts row">
                  <button className="btn-mini" onClick={() => onOpen(s, label)}>编辑 / 定稿</button>
                  <button className="btn-mini" onClick={() => setUpload(s)}>上传底图</button>
                </div>
              )}
            </div>
          );
        })}
      </div>
      {upload && (
        <UploadDialog
          s={upload}
          onClose={() => setUpload(null)}
          onDone={(msg) => {
            studio.notify(msg);
            setUpload(null);
            setReload((n) => n + 1);
          }}
          onErr={(m) => studio.notify(m, "err")}
        />
      )}
      {batch && (
        <BatchDialog
          ep={ep}
          scenes={epMissing}
          onClose={() => setBatch(false)}
          onDone={(ok, failed) => {
            setSubmitted((m) => ({ ...m, ...Object.fromEntries(ok.map((id) => [id, "候选生成中"])) }));
            studio.notify(`已提交 ${ok.length} 个场景底图候选${failed.length ? `；${failed.length} 个失败：${failed.join("；")}` : ""}。结果在各场景的编辑器修改链里，满意再存版本 / 定稿`, failed.length ? "err" : "ok");
            setBatch(false);
          }}
        />
      )}
    </>
  );
}

function UploadDialog({ s, onClose, onDone, onErr }: { s: SceneView; onClose: () => void; onDone: (m: string) => void; onErr: (m: string) => void }) {
  const [variant, setVariant] = useState("main");
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const preview = useMemo(() => (file ? URL.createObjectURL(file) : null), [file]);
  useEffect(() => () => {
    if (preview) URL.revokeObjectURL(preview);
  }, [preview]);
  useEffect(() => {
    const k = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [onClose]);
  const vars = [...new Set([...VARIANTS, ...(s.variants ?? []).map((v) => v.variant)])];
  async function go() {
    if (!file) return;
    setBusy(true);
    try {
      const v = await uploadPlate(s.scene_id, file, variant);
      onDone(`已存为“${sceneName(s)}”的底图版本 v${v.version ?? ""}（${variantLabel(variant)}，未定稿）；在“编辑 / 定稿”里定稿`);
    } catch (e) {
      onErr(`上传底图：${sceneNotReady(e) ? "后端未就绪" : (e as Error).message}`);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="v3p-modal-wrap" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="v3p-modal" role="dialog" aria-label={`上传底图 · ${sceneName(s)}`}>
        <h3>上传底图 · {sceneName(s)}</h3>
        <div className="v3p-modal-body">
          <div>
            <div className="v3p-muted v3p-small">存成哪种底图</div>
            <div className="v3p-variants">
              {vars.map((k) => (
                <button key={k} className={`btn-mini${variant === k ? " on" : ""}`} onClick={() => setVariant(k)}>
                  {variantLabel(k)}
                </button>
              ))}
            </div>
          </div>
          <div className="v3p-scene-acts row">
            <button className="btn-mini" onClick={() => fileRef.current?.click()}>{file ? "换一张…" : "选图片…"}</button>
            <span className="v3p-muted v3p-small">{file ? file.name : "存为新的底图版本，原底图不动；不自动定稿"}</span>
            <input ref={fileRef} type="file" accept="image/*" hidden onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
          </div>
          {preview && <img src={preview} alt="" style={{ maxHeight: 260, maxWidth: "100%", objectFit: "contain", alignSelf: "flex-start", borderRadius: 6 }} />}
        </div>
        <div className="v3p-modal-foot">
          <button className="btn-mini" onClick={onClose}>取消</button>
          <button className="btn-mini on" disabled={!file || busy} onClick={() => void go()}>{busy ? "上传中…" : "存为底图版本"}</button>
        </div>
      </div>
    </div>
  );
}

function BatchDialog({ ep, scenes, onClose, onDone }: { ep: number; scenes: SceneView[]; onClose: () => void; onDone: (ok: string[], failed: string[]) => void }) {
  const [lanes, setLanes] = useState<Lane[] | null>(null);
  const [lanesErr, setLanesErr] = useState<string | null>(null);
  const [preset, setPreset] = useState<{ id: string; label: string } | null | undefined>(undefined);
  const [busy, setBusy] = useState(0);
  const ok = scenes.map((s) => ({ s, text: sceneTableText(s) })).filter((x): x is { s: SceneView; text: string } => !!x.text);
  const skip = scenes.filter((s) => !sceneTableText(s));
  useEffect(() => {
    loadLanes().then(setLanes, (e) => setLanesErr((e as Error).message));
    defaultImagePreset().then(setPreset);
  }, []);
  useEffect(() => {
    const k = (e: KeyboardEvent) => e.key === "Escape" && !busy && onClose();
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [onClose, busy]);
  const usable = (lanes ?? []).filter((l) => l.ok !== false && l.reachable !== false);
  const load = usable.reduce((a, l) => a + (l.load_s ?? 0), 0);
  const eta = usable.length ? (load + ok.length * GEN_S) / usable.length : ok.length * GEN_S;
  async function go() {
    const done: string[] = [];
    const failed: string[] = [];
    for (const [i, { s, text }] of ok.entries()) {
      setBusy(i + 1);
      try {
        await submitSceneGen(s.scene_id, text, preset?.id);
        done.push(s.scene_id);
      } catch (e) {
        failed.push(`${sceneName(s)}：${(e as Error).message}`);
      }
    }
    setBusy(0);
    onDone(done, failed);
  }
  return (
    <div className="v3p-modal-wrap" onMouseDown={(e) => e.target === e.currentTarget && !busy && onClose()}>
      <div className="v3p-modal" role="dialog" aria-label="批量生成场景底图候选">
        <h3>为第 {ep} 集缺底图的场景生成候选</h3>
        <div className="v3p-modal-body">
          <div className="v3p-modal-stats">
            <span><b>{ok.length}</b>个生成任务</span>
            <span><b>{skip.length}</b>个跳过（没有场景表原文）</span>
            <span><b>{usable.length || "…"}</b>条道自动分配</span>
            <span>{ok.length ? <><b>{fmtMin(eta)}</b>预计{load > 0 ? `（卡上已有约 ${Math.round(load / 60)} 分钟的活排在前面）` : ""}</> : "没有能提交的场景"}</span>
          </div>
          <div className="v3p-lanes">
            {lanesErr ? <span className="v3p-warn v3p-small">读不到渲染道：{lanesErr}</span> : !lanes ? <span className="v3p-muted v3p-small">读取渲染道…</span> : lanes.map((l) => (
              <span key={l.id} className={`v3p-badge${l.ok === false ? " warn" : l.activity === "idle" ? " ok" : " busy"}`}>{laneText(l)}</span>
            ))}
          </div>
          <span className="v3p-muted v3p-small">
            每个场景发一条：提示词 = 下面的剧本场景表原文（原样，不改写、不补全），不带参考图、不选底图；出图参数用{" "}
            {preset === undefined ? "…" : preset ? `默认预设「${preset.label}」` : "后端默认"}。结果进各场景编辑器的修改链，存版本 / 定稿仍由你点。
          </span>
          {ok.length > 0 && (
            <div className="v3p-batchlist">
              {ok.map(({ s, text }) => (
                <div key={s.scene_id} className="v3p-batchrow">
                  <b>{sceneName(s)}</b>
                  <pre>{text}</pre>
                </div>
              ))}
            </div>
          )}
          {skip.length > 0 && (
            <div className="v3p-batchlist">
              <span className="v3p-warn v3p-small">这些场景剧本场景表里没有描述，不能批量提交（提示词要写进剧本场景表，或在编辑器里单独写）：</span>
              <span className="v3p-muted v3p-small">{skip.map((s) => sceneName(s)).join("、")}</span>
            </div>
          )}
          {!scenes.length && <span className="v3p-muted">第 {ep} 集用到的场景都有底图了。</span>}
        </div>
        <div className="v3p-modal-foot">
          <button className="btn-mini" disabled={!!busy} onClick={onClose}>取消</button>
          <button className="btn-mini on" disabled={!ok.length || !!busy || preset === undefined} onClick={() => void go()}>
            {busy ? `提交中 ${busy}/${ok.length}…` : `提交 ${ok.length} 个生成任务`}
          </button>
        </div>
      </div>
    </div>
  );
}
