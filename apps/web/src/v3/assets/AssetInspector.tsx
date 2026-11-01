// UX5：资产详情抽屉（A §3.2–3.5、B §6.2）——状态、版本栈（对比 / 回滚入口）、哪些镜头在用（反查）、影响面与重出。
// 编辑仍走原来的资产编辑抽屉（AssetDrawer：换参考 / 生成 / 上传），这里不另做一套写入。
// UX6：“回到这版”接上 B P1 set-current（二次确认；定妆 / 身份 LoRA / 音色要项目方原话，后端缺原话 403；
// 配置型只写提议）；形象 / 单品读后端版本链（同一资产 id），以前复制出的 <id>-vN 只映射显示为“历史复制”。
import { useEffect, useMemo, useState } from "react";
import { thumb } from "../../thumb";
import { Verdict } from "./Verdict";
import { Button, Drawer, Empty, LoadError, Loading, StatusTag, Tag } from "../../ds";
import { ASSET_STATUS } from "../../ds/helpers";
import type { CharacterAssets, LookView, WardrobeItemView } from "../../types";
import type { LightEpisode } from "../api_v1_pages";
import { loadScene, type SceneDetail, type SceneView } from "../pages/scenes_api";
import { TYPE_NAME, slotName, type AssetCardData } from "./center";
import { usageText } from "./AssetCard.helpers";
import { CompareView, type CmpSide } from "./CompareView";
import { type ImpactSource } from "./ImpactDrawer";
import { p1Api, revApi, type AssetChain, type RevDetail } from "./rev_api";
import { OwnerConfirm } from "./OwnerConfirm";

/** 资产 → 用到它的镜头（按集摘要里每镜的人物 + 形象算；场景用场景详情接口） */
function shotsOf(c: AssetCardData, eps: LightEpisode[] | null): string[] {
  if (!eps) return [];
  const out: string[] = [];
  const looks =
    c.type === "look" ? new Set([c.id]) : c.type === "item" || c.type === "prop" ? new Set(((c.raw as { w: WardrobeItemView }).w.used_by_looks ?? []) as string[]) : null;
  for (const ep of eps)
    for (const s of ep.shots)
      for (const ch of s.characters ?? []) {
        if (c.type === "character" ? ch.character === c.id : looks ? !!ch.look_id && looks.has(ch.look_id) && (!c.owner || ch.character === c.owner.id) : false) {
          out.push(s.id);
          break;
        }
      }
  return out;
}

interface Ver {
  key: string;
  label: string;
  url?: string | null;
  sub?: string;
  current?: boolean;
  usedBy?: number;
  /** 账本版本：rev + 有没有快照 */
  rev?: string;
  snap?: boolean;
  /** 形象版本链上的文件 */
  file?: string;
}

export function AssetInspector({
  c,
  eps,
  onClose,
  onEdit,
  onOpenChar,
  onImpact,
  onChanged,
}: {
  c: AssetCardData;
  eps: LightEpisode[] | null;
  onClose: () => void;
  onEdit?: () => void;
  onOpenChar?: (id: string) => void;
  onImpact: (s: ImpactSource) => void;
  /** ASSETUX：在抽屉里改了东西（例如选定场景底图）→ 资产中心刷新 */
  onChanged?: () => void;
}) {
  const [rev, setRev] = useState<RevDetail | null>(null);
  const [revErr, setRevErr] = useState<string | null>(null);
  const [scene, setScene] = useState<SceneDetail | null>(null);
  const [cmp, setCmp] = useState<[CmpSide, CmpSide] | null>(null);
  const [pick, setPick] = useState<string[]>([]);
  const [chain, setChain] = useState<AssetChain | null>(null);
  const [chainErr, setChainErr] = useState<string | null>(null);
  const [back, setBack] = useState<Ver | null>(null);
  const [tick, setTick] = useState(0);
  useEffect(() => {
    setRev(null);
    setRevErr(null);
    setPick([]);
    setChain(null);
    setChainErr(null);
    if (c.revKey) revApi.key(c.revKey).then(setRev, (e) => setRevErr(String((e as Error).message ?? e)));
    if (c.type === "look" || c.type === "item" || c.type === "prop") p1Api.chain(c.id).then(setChain, (e) => setChainErr(String((e as Error).message ?? e)));
    if (c.type === "scene") loadScene(c.id).then(setScene, () => setScene(null));
  }, [c.uid, c.revKey, c.type, c.id, tick]);

  const shots = useMemo(() => (c.type === "scene" ? (scene?.usage?.shots ?? []).map((s) => s.shot_id) : shotsOf(c, eps)), [c, eps, scene]);
  const vers: Ver[] = useMemo(() => {
    if (chain && chain.versions.length)
      return chain.versions.map((v, i) => ({
        key: `${v.file}${i}`,
        label: v.version != null ? `v${v.version}` : v.label ?? "原始",
        url: v.url,
        sub: [v.variant, v.source, v.label && v.version != null ? v.label : null, v.at?.slice(5, 16).replace("T", " ")].filter(Boolean).join(" · "),
        current: v.current,
        file: v.file,
      }));
    if (c.type === "item" || c.type === "prop") {
      const w = (c.raw as { w: WardrobeItemView }).w;
      return (w.image_urls ?? []).map((im, i) => ({ key: `${im.file}${i}`, label: `v${im.version}`, url: im.url, sub: `${im.variant} · ${im.source}${im.created_at ? ` · ${im.created_at.slice(5, 16).replace("T", " ")}` : ""}`, current: i === 0 }));
    }
    if (c.type === "scene" && scene) {
      const list = scene.version_list ?? [];
      return list.map((v, i) => ({ key: `${v.version ?? v.n ?? i}-${v.variant ?? ""}`, label: `v${v.version ?? v.n ?? i + 1}${v.variant && v.variant !== "main" ? ` · ${v.variant}` : ""}`, url: v.url, sub: v.created_at?.slice(5, 16).replace("T", " "), current: (v.version ?? v.n) === scene.plate?.version }));
    }
    if (rev)
      return rev.versions.map((v) => ({
        key: v.rev,
        rev: v.rev,
        snap: !!v.has_snapshot,
        label: `v${v.seq ?? "?"}`,
        sub: `${v.at?.slice(5, 16).replace("T", " ") ?? ""} · ${v.by === "baseline" ? "首次登记" : v.by === "observed" ? "未经系统的改动" : v.by === "owner" ? `项目方${v.owner_quote ? `「${v.owner_quote}」` : ""}` : v.by ?? ""}${v.rollback ? " · 回滚" : ""}`,
        current: v.state === "current",
        usedBy: v.used_by,
      }));
    return [];
  }, [c, scene, rev, chain]);
  const imgVers = vers.filter((v) => v.url);

  const ch = (c.raw as { ch?: CharacterAssets })?.ch;
  const lk = (c.raw as { lk?: LookView })?.lk;
  const w = (c.raw as { w?: WardrobeItemView })?.w;
  const sc = c.type === "scene" ? (c.raw as SceneView) : null;
  const useTxt = usageText(c);
  const impactSrc: ImpactSource | null = c.revKey
    ? { kind: "key", key: c.revKey, label: c.name }
    : shots.length
      ? { kind: "shots", shots, label: `${c.owner ? `${c.owner.name} · ` : ""}${c.name}`, stages: ["image"] }
      : null;

  const byEp = new Map<string, string[]>();
  for (const s of shots) byEp.set(s.split("-")[0], [...(byEp.get(s.split("-")[0]) ?? []), s]);

  return (
    <Drawer
      title={
        <>
          <span className="ds-muted">{TYPE_NAME[c.type]} · </span>
          {c.name}
        </>
      }
      onClose={onClose}
      foot={
        <>
          {c.type === "character" && onOpenChar && (
            <Button variant="primary" onClick={() => onOpenChar(c.id)}>
              打开角色详情
            </Button>
          )}
          {onEdit && (
            <Button variant={c.type === "character" ? "secondary" : "primary"} onClick={onEdit} title="资产编辑器：换参考图 / 生成候选 / 上传；存新版本后，用它的镜头会标记">
              编辑 · 生成…
            </Button>
          )}
          <span className="grow" />
          <Button disabled={!impactSrc} why="还没有镜头用到它" onClick={() => impactSrc && onImpact(impactSrc)} title="会影响哪些镜头、预计 GPU 时间；可勾选排队重出">
            影响面 · 重出…
          </Button>
        </>
      }
    >
      {sc && <ScenePlatePick sc={sc} onChanged={onChanged} />}
      <div className="ac-insp-hero">
        {c.thumb ? <img src={c.thumb} alt="" /> : <span className="ac-ph big">{c.name.slice(0, 1)}</span>}
        <div>
          <div className="ds-row">
            <StatusTag s={c.status} />
            {c.version ? <Tag>当前 v{c.version}</Tag> : null}
            {c.owner && <Tag tone="accent">{c.owner.name}</Tag>}
          </div>
          <p className="ds-muted ds-small">{ASSET_STATUS[c.status].tip}</p>
          <dl className="ds-kv">
            {useTxt && (
              <>
                <dt>用在</dt>
                <dd>{useTxt.replace(/^用在 /, "")}</dd>
              </>
            )}
            {c.sub && (
              <>
                <dt>说明</dt>
                <dd>{c.sub}</dd>
              </>
            )}
            {c.statusNote && (
              <>
                <dt>状态</dt>
                <dd>{c.statusNote}</dd>
              </>
            )}
            {!!c.missing?.length && (
              <>
                <dt>缺</dt>
                <dd className="ac-miss">{c.missing.join("、")}</dd>
              </>
            )}
            {w && (
              <>
                <dt>槽位</dt>
                <dd>{slotName(w.slot)}</dd>
                {w.lora_file && (
                  <>
                    <dt>LoRA</dt>
                    <dd>
                      <code>{w.lora_file}</code>
                      {w.trigger ? ` · 触发词 ${w.trigger}` : ""}
                    </dd>
                  </>
                )}
              </>
            )}
            {lk && ch && (
              <>
                <dt>部件</dt>
                <dd>{Object.entries(lk.items ?? {}).map(([k, v]) => `${slotName(k)} ${(v as string[]).length}`).join(" · ") || "—"}</dd>
              </>
            )}
            {sc?.description?.space && (
              <>
                <dt>剧本描述</dt>
                <dd>{sc.description.space}</dd>
              </>
            )}
            {c.revKey && (
              <>
                <dt>依赖键</dt>
                <dd>
                  <code>{c.revKey}</code>
                </dd>
              </>
            )}
          </dl>
        </div>
      </div>

      <h4 className="ds-section-t">
        版本 {vers.length ? `· ${vers.length}` : ""}
        {imgVers.length > 1 && (
          <Button
            size="xs"
            variant="ghost"
            className="ac-cmp-btn"
            disabled={pick.length !== 2}
            why="勾两版再对比"
            onClick={() => {
              const [a, b] = pick.map((k) => imgVers.find((v) => v.key === k)!);
              setCmp([
                { url: a.url!, label: a.label, sub: a.sub },
                { url: b.url!, label: b.label, sub: b.sub },
              ]);
            }}
          >
            对比所选 {pick.length}/2
          </Button>
        )}
      </h4>
      {c.revKey && revErr && <LoadError what="版本账本" err={revErr} hint="资产本身照常可用；版本列表等 API 重启后出现。" />}
      {c.revKey && !rev && !revErr && <Loading />}
      {!vers.length && !(c.revKey && (!rev || revErr)) && (
        <p className="ds-muted ds-small">
          {c.type === "look" ? `当前 v${c.version ?? 1}。还没有存过新版本：在“编辑 · 生成…”里选“存为这个形象的新版本”，就会进这条版本链（资产 id 不变）。` : c.type === "character" ? "定妆 / 身份参考的版本在“身份 LoRA”和账本里记；打开角色详情看全部参考图。" : "还没有别的版本。"}
        </p>
      )}
      {!!vers.length && (
        <ol className="ac-vers">
          {vers.map((v) => (
            <li key={v.key} className={v.current ? "cur" : ""}>
              {v.url ? (
                <label className="ac-ver-th">
                  <img src={v.url} alt="" loading="lazy" />
                  {imgVers.length > 1 && (
                    <input
                      type="checkbox"
                      checked={pick.includes(v.key)}
                      onChange={(e) => setPick((p) => (e.target.checked ? [...p.filter((x) => x !== v.key), v.key].slice(-2) : p.filter((x) => x !== v.key)))}
                      aria-label={`选 ${v.label} 对比`}
                    />
                  )}
                </label>
              ) : (
                <span className="ac-ver-dot" aria-hidden="true" />
              )}
              <span className="ac-ver-t">
                <b>{v.label}</b> {v.current ? <Tag tone="ok">当前</Tag> : <Tag>旧版</Tag>}
                <small>{v.sub}</small>
                {v.usedBy != null && <small>用在 {v.usedBy} 格（盖过章的）</small>}
              </span>
              {!v.current && <BackBtn v={v} c={c} rev={rev} revErr={revErr} chain={chain} onBack={setBack} />}
            </li>
          ))}
        </ol>
      )}
      {!!chain?.copies.length && (
        <>
          <h4 className="ds-section-t">
            历史复制 · {chain.copies.length} <small className="ds-muted">（以前“存为新版本”复制出的独立资产，只映射显示，不合并、不删）</small>
          </h4>
          <div className="ac-copies">
            {chain.copies.map((k) => (
              <div key={k.asset_id} className="ac-copy">
                {k.url ? <img src={k.url} alt="" loading="lazy" /> : <span className="ac-ph">{(k.version ?? "?").toString()}</span>}
                <Tag>历史复制</Tag>
                <code>{k.asset_id}</code>
                <span className="ds-muted ds-small">{[k.label, k.at?.slice(5, 16).replace("T", " "), k.exists ? null : "已不在资产库"].filter(Boolean).join(" · ")}</span>
              </div>
            ))}
          </div>
        </>
      )}
      {chainErr && (c.type === "look" || c.type === "item" || c.type === "prop") && (
        <p className="ds-small ds-muted">版本链接口还没上线（等 API 重启），先显示资产里已有的图片版本。</p>
      )}
      {rev?.unregistered && <p className="ds-note warn">当前版本没登记过：文件被直接改过（没经过系统）。用它出过的镜头会标“依赖已更新”。</p>}

      <h4 className="ds-section-t">
        哪些镜头在用 {shots.length ? `· ${shots.length} 镜` : ""}
        {c.type !== "scene" && shots.length > 0 && <small className="ds-muted"> （按集摘要算：人物 + 形象）</small>}
      </h4>
      {!eps && c.type !== "scene" ? (
        <Loading />
      ) : !shots.length ? (
        <Empty icon="—" title={c.revKey ? "按镜头逐个记录的用法在“影响面”里看" : "还没有镜头用它"} sub={c.revKey ? "出图预设 / 视频基底 / 音色等，点下面“影响面 · 重出…”按真实盖章算。" : undefined} />
      ) : (
        <div className="ac-usage">
          {[...byEp.entries()].map(([ep, ss]) => (
            <div key={ep} className="ac-usage-ep">
              <b>第 {Number(ep.slice(2))} 集</b>
              <span>
                {ss.slice(0, 40).map((s) => (
                  <a key={s} href={`#${s}`} className="ac-shot" title={`在画布打开 ${s}`}>
                    {s.split("-")[1]}
                  </a>
                ))}
                {ss.length > 40 && <span className="ds-muted ds-small"> 等 {ss.length} 镜</span>}
              </span>
            </div>
          ))}
        </div>
      )}
      {back && (
        <OwnerConfirm
          title={`回到 ${back.label} · ${c.name}`}
          sub={back.rev ? <code>{c.revKey}</code> : "形象版本链"}
          gated={!!(back.rev && rev?.gated)}
          gateLabel={rev?.gate_label}
          okText="回到这版"
          quotePlaceholder={`备注（可空），例如：${c.name} 回到 ${back.label}`}
          lines={
            back.rev
              ? [
                  "当前版本会先自动存一份快照，之后还能再回来。",
                  rev?.config_backed ? "这类内容在 config/ 里：系统不直接改，只写一份提议（data/assets/proposals/），确认后由系统写入。" : "母版 / 脸图文件会从快照恢复；配置里的指针（如有不同）写成提议。",
                  "用旧版出过的镜头会自动恢复“不过期”；用新版出的镜头会标“依赖已更新”。不自动重出。",
                ]
              : ["把这一版设回形象的当前预览：用到这个形象的镜头会标为过期，不自动重出。"]
          }
          onClose={() => {
            setBack(null);
            setTick((n) => n + 1);
          }}
          onConfirm={async (quote) => {
            if (back.rev && c.revKey) {
              const r = await p1Api.setCurrent(c.revKey, back.rev, rev?.gated ? "owner" : "canvas", quote || undefined);
              return r.applied ? `已回到 ${back.label}${r.restored?.length ? `（恢复了 ${r.restored.length} 个文件）` : ""}` : r.proposal ? `已写提议 ${r.proposal.file}：${r.message}` : r.message;
            }
            const r = await p1Api.chainSetCurrent(c.id, back.file!);
            return r.changed ? `已设回 ${back.label}${r.affected_shots?.length ? `；${r.affected_shots.length} 镜标为过期` : ""}` : "已经是当前版本";
          }}
        />
      )}
      {cmp && <CompareView a={cmp[0]} b={cmp[1]} title={`版本对比 · ${c.name}`} onClose={() => setCmp(null)} />}
    </Drawer>
  );
}

/** “回到这版”：能回才亮；不能回写清原因；闸门类旁边标“需你本人确认” */
function BackBtn({ v, c, rev, revErr, chain, onBack }: { v: Ver; c: AssetCardData; rev: RevDetail | null; revErr: string | null; chain: AssetChain | null; onBack: (v: Ver) => void }) {
  let why: string | null = null;
  if (v.rev) {
    if (revErr) why = "版本账本读不到";
    else if (!v.snap) why = "这一版是 P1 之前登记的，只记了指纹、没留内容快照，不能自动回到这版（可以对比、看影响面）";
  } else if (v.file && chain) {
    if (chain.kind !== "look") why = "单品当前图按“偏好角度 + 最新版本”自动取，回到旧版要等单品主图指针；现在可以对比、另存";
  } else why = c.type === "scene" ? "场景底图在“编辑 · 生成…”里的底图版本里定稿" : "版本链接口还没上线（等 API 重启）";
  return (
    <span className="ac-ver-act">
      <Button size="xs" variant="ghost" disabled={!!why} why={why ?? undefined} onClick={() => onBack(v)}>
        回到这版
      </Button>
      {v.rev && rev?.gated && <small>需你本人确认</small>}
    </span>
  );
}

/** ASSETUX 11-01（数据对不上）：场景底图候选 = 登记的 role=space 暂定底图 + 出图线候选；点一下设为当前（画布定稿，不冒充项目方确认） */
type PlateCand = { file: string; url: string | null; source: string; note?: string; ref_id?: string | null; sha256?: string | null };
function ScenePlatePick({ sc, onChanged }: { sc: SceneView; onChanged?: () => void }) {
  const cands = ((sc as unknown as { plate_candidates?: PlateCand[] }).plate_candidates ?? []).filter((x) => x.url);
  // 定稿后当前底图是复制出来的 plate.png：按内容（sha256）对回是哪张候选
  const plateSha = (sc.plate as { sha256?: string | null } | undefined)?.sha256 ?? null;
  const [cur, setCur] = useState<string | null>(
    ((sc as unknown as { plate_candidates?: PlateCand[] }).plate_candidates ?? []).find((x) => plateSha && x.sha256 === plateSha)?.file ?? sc.plate?.file ?? null,
  );
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<{ t: string; bad?: boolean; retry?: () => void; retryLabel?: string } | null>(null);
  const [gone, setGone] = useState<Set<string>>(new Set());
  const [rej, setRej] = useState<Record<string, { reasons: string[]; note: string }>>({});
  const [rejTick, setRejTick] = useState(0);
  useEffect(() => {
    let alive = true;
    fetch("/api/asset-rejects")
      .then((r) => (r.ok ? r.json() : { rejected: {} }))
      .then((j: { rejected?: Record<string, { reasons: string[]; note: string }> }) => alive && setRej(j.rejected ?? {}))
      .catch(() => undefined);
    return () => {
      alive = false;
    };
  }, [rejTick]);
  if (!cands.length) return null;
  async function del(x: PlateCand) {
    setMsg(null);
    try {
      const r = await fetch(`/api/trash/object?type=asset_ref&id=${encodeURIComponent(`${sc.scene_id}/${x.ref_id}`)}&confirm=true&reason=${encodeURIComponent("资产中心删除场景参考")}`, { method: "DELETE" });
      const j = (await r.json().catch(() => ({}))) as { entry_id?: string; detail?: unknown };
      if (!r.ok || !j.entry_id) throw new Error(typeof j.detail === "string" ? j.detail : `HTTP ${r.status}`);
      setGone((g) => new Set([...g, x.file]));
      const entry = j.entry_id;
      setMsg({
        t: "已移到回收站。",
        retry: () =>
          void fetch(`/api/trash/${encodeURIComponent(entry)}/restore`, { method: "POST" }).then((rr) => {
            if (rr.ok) setGone((g) => new Set([...g].filter((f) => f !== x.file)));
            setMsg({ t: rr.ok ? "已撤销删除" : "撤销没成功，可以去回收站还原", bad: !rr.ok });
            onChanged?.();
          }),
        retryLabel: "撤销",
      });
      onChanged?.();
    } catch (e) {
      setMsg({ t: `删不了：${(e as Error).message}。数据没改动`, bad: true });
    }
  }
  const provisional = (sc.plate as { provisional?: boolean } | undefined)?.provisional;
  async function pick(f: string) {
    setBusy(f);
    setMsg(null);
    try {
      const r = await fetch(`/api/assets/scenes/${encodeURIComponent(sc.scene_id)}/plate-pick`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ file: f }) });
      if (!r.ok) throw new Error(((await r.json().catch(() => ({}))) as { detail?: string }).detail ?? `HTTP ${r.status}`);
      setCur(f);
      setMsg({ t: "已设为当前底图（画布定稿；项目方确认另算）" });
      onChanged?.();
    } catch (e) {
      setMsg({ t: `没设上：${(e as Error).message}。数据没改动`, bad: true, retry: () => void pick(f) });
    } finally {
      setBusy(null);
    }
  }
  return (
    <section className="ac-insp-plates" aria-label="底图候选">
      <h3>
        底图候选 <span className="ds-muted ds-small">{provisional ? "现在显示的是暂定底图（参考图），点一张设为当前" : "点一张设为当前"}</span>
      </h3>
      <div className="ac-insp-plates-g">
        {cands.map((x) => (
          <div key={x.file} className="ac-insp-platew">
            <button className={`ac-insp-plate${cur === x.file ? " on" : ""}`} disabled={!!busy || gone.has(x.file)} onClick={() => void pick(x.file)} title={x.note || x.file}>
              <img src={thumb(x.url, 360) ?? x.url ?? ""} alt="" loading="lazy" data-zoom-label={`${sc.name ?? sc.scene_id} · 场景底图候选${cur === x.file ? " · 当前" : ""}`} />
              <span>{gone.has(x.file) ? "已删除" : busy === x.file ? "正在设…" : cur === x.file ? "✓ 当前" : x.source === "ref" ? "已登记 · 设为当前" : "新出的候选 · 设为当前"}</span>
            </button>
            {!gone.has(x.file) && (
              <Verdict
                kind="scene_plate"
                file={x.file}
                label="场景底图"
                current={cur === x.file}
                rejected={rej[x.file]}
                busy={!!busy}
                onUse={() => void pick(x.file)}
                onChanged={() => setRejTick((n) => n + 1)}
                notify={(t, undo, err) => setMsg({ t, bad: err, retry: undo ? () => void undo().then(() => (setMsg({ t: "已撤销" }), setRejTick((n) => n + 1))) : undefined, retryLabel: undo ? "撤销" : undefined })}
              />
            )}
            {x.ref_id && cur !== x.file && !gone.has(x.file) && (
              <button className="ac-insp-plate-del" disabled={!!busy} onClick={() => void del(x)} title="删除这张参考（进回收站，可撤销）">
                删除
              </button>
            )}
          </div>
        ))}
      </div>
      {msg && (
        <p className={`ds-note ${msg.bad ? "warn" : "ok"}`} role="status">
          {msg.t}
          {msg.retry && (
            <Button size="xs" variant="secondary" onClick={msg.retry}>
              {msg.retryLabel ?? "再试一次"}
            </Button>
          )}
        </p>
      )}
    </section>
  );
}
