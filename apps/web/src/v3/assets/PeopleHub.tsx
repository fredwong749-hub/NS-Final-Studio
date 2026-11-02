// ASSETUX：人物资产页（#/assets?char=<人物>）。以人物为中心，一个人一页看全：
// 身份脸 → 3 套固定造型（设定图 + 部件单品）→ 衣橱单品 → 声音 → 在哪些集 / 镜出现 → 最近操作。
// 项目方原话：“我选这个图按一下就可以了……系统是在我 login 的……你不需要每个东西都要打上一个字。”
// 所以：选身份脸 / 选设定图 / 挂造型 = 点一下就生效，底部 10 秒“撤销”；删除进回收站（也能撤销）；不弹原话框。
// “我要添加这个鞋子进去作为资产，我怎么做呀？” → 右上“＋ 添加单品”，或把图片拖进页面，或 Ctrl+V 粘贴。
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { Button, Empty, LoadError, Modal, Skel, Tag } from "../../ds";
import { thumb } from "../../thumb";
import { AudioPlayer } from "../../ds/MediaPlayer";
import { assetsV1, type LightEpisode } from "../api_v1_pages";
import { ACTION_TEXT, CATS, catOf, choicesFor, hubApi, partFor, type FaceCand, type HubChar, type HubItem, type HubList, type HubLook, type Part } from "./hub_api";
import { Verdict } from "./Verdict";
import { RegenDialog } from "../RegenButton";
import { GenDock, GenPoller, GenTiles, trackGen } from "../GenState";
import type { GearRef } from "../RegenButton.helpers";
import "./people_hub.css";

// ---------------------------------------------------------------- 人物列表（左栏，AssetCenter 用）
export function PeopleNav({ list, cur, onPick }: { list: HubList | null; cur: string | null; onPick: (cid: string) => void }) {
  if (!list)
    return (
      <div className="hub-nav">
        {[0, 1, 2, 3].map((i) => (
          <Skel key={i} h={52} r="var(--r-m)" />
        ))}
      </div>
    );
  return (
    <div className="hub-nav" role="list" aria-label="当前剧的人物">
      {list.characters.map((c) => (
        <button key={c.cid} role="listitem" className={`hub-nav-p${cur === c.cid ? " on" : ""}`} onClick={(e) => !e.altKey && onPick(c.cid)} aria-current={cur === c.cid ? "page" : undefined}>
          <span className="hub-nav-face">{c.face ? <img src={thumb(c.face.url, 96) ?? c.face.url} alt="" data-zoom-label={`${c.name} · 身份脸`} /> : <b>{c.name.slice(0, 1)}</b>}</span>
          <span className="hub-nav-t">
            <b>{c.name}</b>
            <small>
              {c.sheets}/{c.looks} 套造型 · {c.items} 件单品
            </small>
          </span>
          {c.missing > 0 ? (
            <span className="hub-dot bad" title={`资产缺图 ${c.missing} 处：出图会被拦下`}>
              {c.missing}
            </span>
          ) : null}
        </button>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------- 撤销 toast
type ToastT = { id: number; text: ReactNode; undo?: () => Promise<unknown>; retry?: () => void; err?: boolean };
function useToasts() {
  const [list, setList] = useState<ToastT[]>([]);
  const seq = useRef(0);
  const push = useCallback((t: Omit<ToastT, "id">) => {
    const id = ++seq.current;
    setList((l) => [...l.slice(-2), { ...t, id }]);
    window.setTimeout(() => setList((l) => l.filter((x) => x.id !== id)), t.err ? 12000 : 10000);
  }, []);
  const drop = (id: number) => setList((l) => l.filter((x) => x.id !== id));
  const view = createPortal(
    <div className="hub-toasts" aria-live="polite">
      {list.map((t) => (
        <div key={t.id} className={`hub-toast${t.err ? " err" : ""}`} role={t.err ? "alert" : "status"}>
          <span>{t.text}</span>
          {t.retry && (
            <button className="hub-toast-undo" onClick={() => (drop(t.id), t.retry!())}>
              再试一次
            </button>
          )}
          {t.undo && (
            <button
              className="hub-toast-undo"
              onClick={() => {
                const u = t.undo!;
                drop(t.id);
                void u().then(
                  () => push({ text: "已撤销" }),
                  (e) => push({ text: `撤销没成功：${(e as Error).message}`, err: true }),
                );
              }}
            >
              撤销
            </button>
          )}
          <i className="hub-toast-bar" />
        </div>
      ))}
    </div>,
    document.body,
  );
  return { push, view };
}

// ---------------------------------------------------------------- 大图
function Lightbox({ src, alt, onClose }: { src: string; alt: string; onClose: () => void }) {
  useEffect(() => {
    const k = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [onClose]);
  return createPortal(
    <div className="hub-lb" role="dialog" aria-label={alt} onClick={onClose}>
      <img src={src} alt={alt} />
      <span>{alt} · 点任意处或按 Esc 关闭</span>
    </div>,
    document.body,
  );
}

const STATUS: Record<string, { label: string; tone: "ok" | "warn" | "bad" | "neutral"; tip: string }> = {
  wardrobe: { label: "单品图", tone: "ok", tip: "出图时用这件单品的图做参考" },
  sheet_only: { label: "仅设定图", tone: "warn", tip: "衣橱里没有对应单品，出图时用设定图裁切做参考；建议补一张单品图" },
  missing: { label: "缺图", tone: "bad", tip: "连设定图都没有：这套造型出图会被拦下" },
  extra: { label: "附加", tone: "neutral", tip: "附加单品（不替换登记部件）：某一镜正文写到它、部位在画面里看得见时，作为附加参考进出图" },
};

// ---------------------------------------------------------------- 主页面
export function PeopleHub({ cid, onListChanged }: { cid: string; onListChanged?: () => void }) {
  const [d, setD] = useState<HubChar | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [allItems, setAllItems] = useState(false);
  const [tick, setTick] = useState(0);
  const [big, setBig] = useState<{ src: string; alt: string } | null>(null);
  const [upload, setUpload] = useState<{ file: Blob; name: string } | "pick" | null>(null);
  const [drag, setDrag] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [newLook, setNewLook] = useState(false);
  /** ↻ 再生成的目标：哪张图（底图）、用在哪 */
  // UIRSI r37（项目方 11-01 17:2x，L-086：身份脸只接受脸部裁切；后端 set_face 已 422 拦）：前端先按图的宽高比认出明显不是脸部裁切的候选
  // （后端以后若在候选里给 crop_ok / crop_why 就以后端为准），点了不调接口、直接说明；按钮和看大图、再生成都保留
  const [notCrop, setNotCrop] = useState<Record<string, string>>({});
  // UIRSI r40（项目方 23:57:52–23:58:01 九秒内连点三次，把已定的林晚造型 A 设定图换掉了；事后说“只是点着看”）：
  // ① 点图本身只看大图，必须点“用这张”才换；② 换掉项目方已定的图（owner_decisions 的锁）先一键确认“换 / 不换”；③ 换完 10 秒内可撤销（act 已有）
  type DLock = { id: string; decision: string | null; when: string | null; title: string; kind: "sheet" | "face"; match: string; regex?: string; cid?: string };
  const [locks, setLocks] = useState<DLock[]>([]);
  const [ask, setAsk] = useState<{ text: string; run: () => void } | null>(null);
  useEffect(() => {
    fetch("/api/decision-locks")
      .then((r) => (r.ok ? r.json() : { locks: [] }))
      .then((x: { locks?: DLock[] }) => setLocks(x.locks ?? []))
      .catch(() => setLocks([]));
  }, []);
  const [regenFor, setRegenFor] = useState<{ kind: "sheet" | "face" | "item"; file: string; title: string; base: string; look?: string; item_id?: string } | null>(null);
  const [askPart, setAskPart] = useState<{ it: HubItem; lk: HubLook; options: string[]; others: string[] } | null>(null);
  const { push, view: toasts } = useToasts();
  const reload = useCallback(() => setTick((n) => n + 1), []);

  useEffect(() => {
    let alive = true;
    hubApi.get(cid, allItems).then(
      (x) => alive && (setD(x), setErr(null)),
      (e) => alive && setErr(String((e as Error).message ?? e)),
    );
    return () => {
      alive = false;
    };
  }, [cid, allItems, tick]);
  useEffect(() => setD(null), [cid]);

  // 粘贴图片 = 添加单品
  useEffect(() => {
    const onPaste = (e: ClipboardEvent) => {
      const t = e.target as HTMLElement | null;
      if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.isContentEditable)) return;
      const f = [...(e.clipboardData?.items ?? [])].find((x) => x.type.startsWith("image/"))?.getAsFile();
      if (f) {
        e.preventDefault();
        setUpload({ file: f, name: "" });
      }
    };
    window.addEventListener("paste", onPaste);
    return () => window.removeEventListener("paste", onPaste);
  }, []);

  /** 点一下就生效：调接口 → 刷新 → toast 带撤销 */
  const act = useCallback(
    async (key: string, run: () => Promise<unknown>, text: ReactNode, undo?: () => Promise<unknown>) => {
      setBusy(key);
      try {
        await run();
        push({ text, undo: undo ? () => undo().then(() => (reload(), onListChanged?.())) : undefined });
        reload();
        onListChanged?.();
      } catch (e) {
        // 不只报错：说清楚 + 给“再试一次”（常见原因是接口暂时连不上）
        push({ text: `没成功：${(e as Error).message}。数据没改动，可以再试一次`, err: true, retry: () => void act(key, run, text, undo) });
      } finally {
        setBusy(null);
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [push, reload, onListChanged],
  );

  if (err) return <LoadError what={`人物 ${cid}`} err={err} retry={reload} hint="后台恢复后这里显示这个人物的全部资产；已登记的不会丢。" />;
  if (!d)
    return (
      <div className="hub" aria-busy="true">
        {/* UM-0092：加载占位只放一块（几块不同高度的占位会被当成“同一行卡片不等高”） */}
        <Skel h={880} r="var(--r-l)" />
      </div>
    );

  const cropWhy = (file: string): string | null => {
    const f = (d.faces ?? []).find((x) => x.file === file) as (FaceCand & { crop_ok?: boolean; crop_why?: string }) | undefined;
    if (f?.crop_ok === false) return f.crop_why || "后端判定不是脸部裁切";
    if (f?.crop_ok === true) return null;
    return notCrop[file] ?? null;
  };
  const setFace = (file: string) => {
    const why = cropWhy(file);
    if (why) {
      push({ text: `这张不能设为身份脸：${why}。身份脸只接受脸部裁切（大头）；整张设定图请先裁出脸部再用。这张仍可以悬停右上角放大镜看大图，或用上方 ↻ 再生成`, err: true });
      return;
    }
    const prev = d.face?.file ?? null;
    const run = () => void act(`face:${file}`, () => hubApi.face(cid, file), `${d.name}：身份脸已换成这张`, prev ? () => hubApi.face(cid, prev) : undefined);
    guardLock("face", prev, file, run);
  };
  const setSheet = (lk: HubLook, file: string) => {
    const prev = lk.sheet?.file ?? null;
    const run = () => void act(`sheet:${lk.look}:${file}`, () => hubApi.sheet(cid, lk.look, file), `造型 ${lk.look}：设定图已选定`, prev ? () => hubApi.sheet(cid, lk.look, prev) : undefined);
    guardLock("sheet", prev, file, run, `造型 ${lk.look} 设定图`);
  };
  /** 当前这张受项目方已定决策锁着、而要换成别的 → 先一键确认；否则直接换 */
  /** UIAUDIT P0-1（r43）：设定图锁的 pattern 是正则（带转义），按正则判；正则坏了才退回字面片段 */
  function hit(l: DLock, file: string): boolean {
    if (l.regex) {
      try {
        return new RegExp(l.regex).test(file);
      } catch {
        /* 正则写坏：退回字面 */
      }
    }
    return file.includes(l.match);
  }
  function guardLock(kind: "sheet" | "face", cur: string | null, next: string, run: () => void, what = "身份脸") {
    const lk = cur
      ? locks.find((l) => l.kind === kind && (kind === "face" ? l.cid === cid && cur === l.match && next !== l.match : hit(l, cur) && !hit(l, next)))
      : undefined;
    if (!lk) return run();
    const name = lk.match.split("/").pop()?.replace(/\.(png|jpe?g|webp)$/i, "") ?? lk.match;
    setAsk({ text: `这张${what}已按你 ${lk.when ?? "之前"} 的决定定为 ${name}${lk.decision ? `（${lk.decision}）` : ""}，确定要换吗？`, run });
  }
  const setPart = (lk: HubLook, part: Part, item: HubItem | null) => {
    const prev = part.item_id;
    void act(
      `map:${lk.look}:${part.label}`,
      () => hubApi.map(cid, lk.look, part.label, item?.id ?? null, "picker"),
      item ? `造型 ${lk.look} 的“${part.label}”改用单品“${item.name}”` : `造型 ${lk.look} 的“${part.label}”不再用单品，回到设定图`,
      () => hubApi.map(cid, lk.look, part.label, prev),
    );
  };
  /** choice：undefined = 默认（加为附加单品，不替换）；null = 不替换（附加）；字符串 = 替换这个部件（只在人明确选择时） */
  const toggleLook = (it: HubItem, lk: HubLook, choice?: string | null) => {
    const on = (it.looks ?? []).filter((x) => x.look === lk.look);
    if (on.length) {
      void act(
        `tog:${it.id}:${lk.look}`,
        () => Promise.all(on.map((x) => hubApi.map(cid, lk.look, x.part, null, "card"))),
        `“${it.name}”已从造型 ${lk.look} 拿下`,
        () => Promise.all(on.map((x) => hubApi.map(cid, lk.look, x.part, it.id))),
      );
    } else {
      const pk = partFor(lk, it.slot, it.name, it.zone);
      if (choice === undefined && !pk.sure) return setAskPart({ it, lk, options: pk.options, others: pk.reason === "zone" ? pk.others ?? [] : [] });
      const part = choice === undefined ? pk.part : choice ?? it.name;
      const extra = choice === undefined ? pk.extra : choice === null;
      const prev = lk.parts.find((p) => p.label === part)?.item_id ?? null;
      void act(
        `tog:${it.id}:${lk.look}`,
        () => hubApi.map(cid, lk.look, part, it.id, "card"),
        extra ? `“${it.name}”已加到造型 ${lk.look}（不替换；正文写到时作为附加参考）` : `“${it.name}”挂到造型 ${lk.look}，替换了“${part}”`,
        () => hubApi.map(cid, lk.look, part, prev),
      );
    }
  };
  const trashItem = (it: HubItem) =>
    void (async () => {
      setBusy(`trash:${it.id}`);
      try {
        const r = await hubApi.trash(cid, it.id);
        push({ text: `“${it.name}”已移到回收站`, undo: () => hubApi.restore(cid, it.id, r.entry_id, r.maps).then(() => (reload(), onListChanged?.())) });
        reload();
        onListChanged?.();
      } catch (e) {
        const imp = ((e as { detail?: { impact?: { blocked?: string[] } } }).detail?.impact?.blocked ?? []).join("；");
        push({ text: `删不了：${imp || (e as Error).message}。先在上面的造型里点 A/B/C 把它拿下，再删`, err: true, retry: () => trashItem(it) });
      } finally {
        setBusy(null);
      }
    })();
  const renameItem = (it: HubItem, name: string) => {
    if (!name.trim() || name.trim() === it.name) return;
    void act(`rn:${it.id}`, () => hubApi.rename(cid, it.id, name.trim()), `已改名为“${name.trim()}”`, () => hubApi.rename(cid, it.id, it.name));
  };

  return (
    <div
      className={`hub${drag ? " drag" : ""}`}
      onDragOver={(e) => {
        if ([...e.dataTransfer.types].includes("Files")) {
          e.preventDefault();
          setDrag(true);
        }
      }}
      onDragLeave={(e) => {
        if (e.currentTarget === e.target) setDrag(false);
      }}
      onDrop={(e) => {
        const f = [...e.dataTransfer.files].find((x) => x.type.startsWith("image/"));
        if (f) {
          e.preventDefault();
          setUpload({ file: f, name: "" }); // 名字不用文件名：对话框里查库 / 看图起名
        }
        setDrag(false);
      }}
    >
      <Hero d={d} onAdd={() => setUpload("pick")} onBig={setBig} />
      {/* L-120：再生成后的呼吸灯 / 排队 / 预计完成；完成自动刷新成候选 */}
      <GenPoller onDone={(it) => (push({ text: `再生成好了：${it.title}，在候选里` }), reload())} onFail={(it, j) => push({ text: `没出成：${it.title}（${j.error ?? "原因未知"}）`, err: true })} />
      <GenDock />

      <nav className="hub-anchors" aria-label="页内导航">
        {[
          ["hub-face", "身份脸"],
          ...d.looks.map((l) => [`hub-look-${l.look}`, `造型 ${l.look}`]),
          ["hub-schedule", "排期"],
          ["hub-wardrobe", `衣橱 ${d.items.length}`],
          ["hub-voice", "声音"],
          ["hub-appear", "出场"],
          ["hub-recent", "记录"],
        ].map(([id, t]) => (
          <a key={id} href={`#${id}`} onClick={(e) => (e.preventDefault(), document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" }))}>
            {t}
          </a>
        ))}
        {/* 回退清单 F32：缺图 / 文件未登记 警示常驻（为 0 也写，滚动时一直看得到） */}
        <span className={`hub-anchors-st${d.missing ? " bad" : ""}`} title={(d.unregistered ?? []).length ? `没登记成单品的图片：${(d.unregistered ?? []).slice(0, 12).join("、")}` : "单品目录里的图片都已登记"}>
          {d.missing ? `资产缺图 ${d.missing} 处` : "不缺图"} · 文件未登记 {(d.unregistered ?? []).length} 个
        </span>
      </nav>

      {/* ---- 身份脸 ---- */}
      <section id="hub-face" className="hub-sec">
        <SecHead
          title="身份脸"
          sub="出图时用它锁定长相。点一张候选，马上换成当前（10 秒内可撤销）。"
          extra={
            d.face ? (
              <button className="regen-btn regen-sm" onClick={() => setRegenFor({ kind: "face", file: d.face!.file, title: `${d.name} 身份脸`, base: "当前身份脸" })} title="以当前身份脸为底图，按你的要求再生成一张候选">
                ↻ 再生成
              </button>
            ) : undefined
          }
        />
        <div className="hub-faces">
          {(d.faces ?? []).map((f) => (
            <figure key={f.file} className={`hub-face${f.current ? " on" : ""}`}>
              <button className="hub-face-img" onClick={() => setBig({ src: f.url, alt: `${d.name} 身份脸${f.current ? "" : "候选"}` })} disabled={!!busy} title={f.current ? "当前身份脸 · 点开看大图" : cropWhy(f.file) ? `不能设为身份脸：${cropWhy(f.file)}（点开看大图）` : "点开看大图；要换成这张，点下面的“用这张”"} data-crop={cropWhy(f.file) ? "no" : undefined}>
                <img
                  src={thumb(f.url, 360) ?? f.url}
                  alt={`${d.name} 身份脸候选`}
                  loading="lazy"
                  onLoad={(e) => {
                    const im = e.currentTarget;
                    const r = im.naturalHeight ? im.naturalWidth / im.naturalHeight : 1;
                    if (r < 0.6 || r > 1.6) setNotCrop((m) => (m[f.file] ? m : { ...m, [f.file]: `宽高比 ${r.toFixed(2)}，不像脸部裁切` }));
                  }}
                />
                {f.current ? <span className="hub-badge ok">当前</span> : <span className="hub-hover">{cropWhy(f.file) ? "不是脸部裁切" : "看大图"}</span>}
              </button>
              <figcaption>
                {humanNote(f.note) || fileLabel(f.file)}
                {cropWhy(f.file) ? " · 不是脸部裁切" : ""}
              </figcaption>
              <Verdict
                kind="face"
                file={f.file}
                label="身份脸"
                cid={cid}
                current={f.current}
                rejected={d.rejected?.[f.file]}
                busy={!!busy}
                onUse={() => setFace(f.file)}
                onChanged={reload}
                notify={(text, undo, err) => push({ text, undo, err })}
              />
              {!f.current && f.ref_id && (
                <button
                  className="hub-face-del"
                  disabled={!!busy}
                  title="删除这张候选（进回收站，10 秒内可撤销）"
                  onClick={() =>
                    void (async () => {
                      try {
                        const r = await hubApi.trashRef(cid, f.ref_id!);
                        push({ text: "这张身份脸候选已移到回收站", undo: () => hubApi.restoreTrash(r.entry_id).then(() => reload()) });
                        reload();
                      } catch (e) {
                        push({ text: `删不了：${(e as Error).message}。数据没改动`, err: true });
                      }
                    })()
                  }
                >
                  删除
                </button>
              )}
            </figure>
          ))}
          <GenTiles where="face" />
          {!(d.faces ?? []).length && <Empty icon="◎" title="还没有身份脸" sub="系统出了设定图后，脸部裁切会出现在这里。" />}
        </div>
      </section>

      {/* ---- 3 套造型 ---- */}
      {d.looks.map((lk) => (
        <LookSection
          key={lk.look}
          cid={cid}
          name={d.name}
          lk={lk}
          items={d.items}
          busy={busy}
          onSheet={setSheet}
          onPart={setPart}
          onBig={setBig}
          rejected={d.rejected ?? {}}
          notify={(text, undo, err) => push({ text, undo, err })}
          onChangedAll={reload}
          onRegen={(l) => l.sheet && setRegenFor({ kind: "sheet", file: l.sheet.file, look: l.look, title: `${d.name} 造型 ${l.look} 设定图`, base: `造型 ${l.look} 当前设定图` })}
          onDelCand={(file) =>
            void (async () => {
              try {
                const r = await hubApi.trashObj("sheet_candidate", file);
                push({ text: `造型 ${lk.look}：这张候选已移到回收站`, undo: () => hubApi.restoreTrash(r.entry_id).then(() => reload()) });
                reload();
              } catch (e) {
                push({ text: `删不了：${(e as Error).message}。数据没改动（当前设定图不能删，先选别的再删）`, err: true });
              }
            })()
          }
          onUploadSheet={(f) => void act(`upsheet:${lk.look}`, () => hubApi.uploadSheet(cid, lk.look, f, (f as File).name || "sheet.png"), `造型 ${lk.look}：新设定图已设为当前`)}
          onRemove={
            lk.custom
              ? () =>
                  void act(`rmlook:${lk.look}`, () => hubApi.removeLook(cid, lk.look), `已撤销新造型 ${lk.look}`)
              : undefined
          }
        />
      ))}
      <div className="hub-newlook">
        <Button variant="secondary" onClick={() => setNewLook(true)}>
          ＋ 新造型
        </Button>
        <span className="ds-small ds-muted">新建一套造型（{d.name} 现在有 {d.looks.map((l) => l.look).join(" / ")}），写上场合和穿什么，再传一张设定图</span>
      </div>

      <ScheduleSection d={d} busy={busy} onSet={(ep, look, prev) => void act(`sch:${ep}`, () => hubApi.schedule(cid, ep, look), look ? `第 ${ep} 集整集改用造型 ${look}` : `第 ${ep} 集回到按剧本逐镜的造型`, () => hubApi.schedule(cid, ep, prev))} />

      {/* ---- 衣橱 ---- */}
      <Wardrobe d={d} busy={busy} allItems={allItems} setAllItems={setAllItems} onAdd={() => setUpload("pick")} onToggle={toggleLook} onTrash={trashItem} onRename={renameItem} onAddImage={(it, f) => void act(`img:${it.id}`, () => hubApi.addImage(cid, it.id, f, f.name), `“${it.name}”加了一张图`)} onBig={setBig}
        onPrimary={(it, file) => {
          const prev = it.gallery?.[0]?.file ?? null;
          void act(`prim:${it.id}`, () => hubApi.primary(cid, it.id, file), `“${it.name}”的主图换成这张（出图用它）`, prev ? () => hubApi.primary(cid, it.id, prev) : undefined);
        }}
        notify={(text, undo, err) => push({ text, undo, err })}
        onChangedAll={reload}
        onRegen={(it) => it.image && setRegenFor({ kind: "item", file: it.image.file, item_id: it.id, title: `${d.name} · ${it.name}`, base: `“${it.name}”主图` })}
        onUseRegen={(it, file) => {
          const prev = it.gallery?.[0]?.file ?? it.image?.file ?? null;
          // 撤销 = 拿掉加进去的那张、主图回到原来的（unuse-regen）；接口还没上线时退回只换主图
          let added: { file: string; prev: string | null } | null = null;
          void act(
            `useregen:${it.id}`,
            () => hubApi.useRegen(cid, it.id, file).then((r) => void (added = { file: (r as { file?: string }).file ?? file, prev: r.prev })),
            `“${it.name}”换成再生成的这张（出图用它）`,
            () => (added ? hubApi.unuseRegen(cid, it.id, added.file, added.prev).catch(() => (prev ? hubApi.primary(cid, it.id, prev) : undefined)) : Promise.resolve()),
          );
        }}
      />

      {/* ---- 声音 ---- */}
      <VoiceSection cid={cid} name={d.name} voice={d.voice} />

      <Appearances cid={cid} name={d.name} />

      {/* ---- 最近操作 ---- */}
      <section id="hub-recent" className="hub-sec">
        <SecHead title="最近操作" sub="系统按登录账户自动记下谁、何时、做了什么" />
        {d.recent?.length ? (
          <ol className="hub-recent">
            {d.recent.map((r, i) => (
              <li key={i}>
                <time>{r.at.replace("T", " ").slice(5, 16)}</time>
                <b title={r.by}>{r.by}</b>
                <span>
                  {ACTION_TEXT[r.action] ?? r.action}
                  {r.look ? ` · 造型 ${String(r.look)}` : ""}
                  {r.name ? ` · ${String(r.name)}` : ""}
                  {r.part ? ` · ${String(r.part)}` : ""}
                </span>
              </li>
            ))}
          </ol>
        ) : (
          <p className="ds-muted ds-small">还没有操作记录。</p>
        )}
      </section>

      {drag && (
        <div className="hub-drop" aria-hidden>
          <b>松手：把图片加成 {d.name} 的单品</b>
        </div>
      )}
      {upload && (
        <UploadDialog
          d={d}
          initial={upload === "pick" ? null : upload}
          onClose={() => setUpload(null)}
          onDone={({ item: it, mapped, adopted }) => {
            setUpload(null);
            push(
              adopted
                ? {
                    // 用库里已有的单品：撤销 = 映射还原 + （原来不在当前衣橱的）移回“以前登记”
                    text: mapped ? `用了库里的“${it.name}”，挂到造型 ${mapped}` : `“${it.name}”已放进当前衣橱`,
                    undo: () =>
                      Promise.all(adopted.maps.map((m) => hubApi.map(cid, m.look, m.part, m.prev)))
                        .then(() => (adopted.wasAdopted ? null : hubApi.adopt(cid, it.id, [], true)))
                        .then(() => (reload(), onListChanged?.())),
                  }
                : {
                    text: mapped ? `“${it.name}”已加入衣橱，并挂到造型 ${mapped}` : `“${it.name}”已加入 ${d.name} 的衣橱`,
                    undo: () => hubApi.trash(cid, it.id).then(() => (reload(), onListChanged?.())),
                  },
            );
            reload();
            onListChanged?.();
            window.setTimeout(() => document.getElementById(`hub-item-${it.id}`)?.scrollIntoView({ behavior: "smooth", block: "center" }), 400);
          }}
        />
      )}
      {askPart &&
        createPortal(
          <Modal
            title={`把“${askPart.it.name}”挂到造型 ${askPart.lk.look}`}
            sub={
              askPart.options.length
                ? "造型里有几件同类的部件，名字对不上，不替你猜：点一下要替换的那一项（10 秒内可撤销）。"
                : `部位对不上：“${askPart.it.name}”是${ZONE_NAME[askPart.it.zone ?? ""] ?? "这一类"}，造型 ${askPart.lk.look} 里的同类部件是 ${askPart.others.map((o) => `“${o}”`).join("、")}，不能互相替换。可以把它作为附加单品加到这套造型（正文写到时作为参考），或者换一套造型。`
            }
            onClose={() => setAskPart(null)}
            foot={
              <Button variant="ghost" onClick={() => setAskPart(null)}>
                取消
              </Button>
            }
          >
            <div className="hub-ask">
              {askPart.options.map((o) => {
                const p = askPart.lk.parts.find((x) => x.label === o);
                return (
                  <button key={o} className="hub-ask-i" onClick={() => (toggleLook(askPart.it, askPart.lk, o), setAskPart(null))}>
                    <b>替换“{o}”</b>
                    <small>现在：{p?.item_name ? `单品“${p.item_name}”` : p?.status === "missing" ? "缺图" : "只有设定图"}</small>
                  </button>
                );
              })}
              <button className="hub-ask-i" onClick={() => (toggleLook(askPart.it, askPart.lk, null), setAskPart(null))}>
                <b>不替换，作为附加单品</b>
                <small>加到造型 {askPart.lk.look}，正文写到时作为附加参考</small>
              </button>
            </div>
          </Modal>,
          document.body,
        )}
      {regenFor && (
        <RegenDialog
          title={`↻ 再生成 · ${regenFor.title}`}
          sub="写一句要改成什么样，可以再传装备图（衣服、鞋、饰品、美甲…）。出好的图会出现在候选里，点“✓ 用这张”才生效，原图不动。"
          base={regenFor.base}
          where={`资产 ${cid}${regenFor.look ? ` 造型${regenFor.look}` : ""}${regenFor.item_id ? ` ${regenFor.item_id}` : ""}`}
          chars={[{ id: cid, name: d.name }]}
          onClose={() => setRegenFor(null)}
          onSubmit={async (text: string, refs: GearRef[]) => {
            const r = await hubApi.regen(cid, { kind: regenFor.kind, file: regenFor.file, prompt: text, look: regenFor.look, item_id: regenFor.item_id, gear: refs.map((g) => ({ path: g.path, label: g.label, item_id: g.item_id })) });
            // L-119：你写的思路已由写作 API 改写成出图提示词；提示里给一句它理解的改动
            push({ text: r.rewrite ? `已提交再生成（${regenFor.title}）：${r.rewrite.zh_summary}` : `已提交再生成（${regenFor.title}），同提示词换种子`, });
            const jid = r.job?.job_id;
            if (jid) {
              const where = regenFor.kind === "sheet" ? `sheet:${regenFor.look}` : regenFor.kind === "item" ? `item:${regenFor.item_id}` : "face";
              trackGen({ id: jid, where, title: regenFor.title, summary: r.rewrite?.zh_summary });
            } else window.setTimeout(reload, 60000);
          }}
        />
      )}
      {newLook && (
        <NewLookDialog
          d={d}
          onClose={() => setNewLook(false)}
          onDone={(look, sheet) => {
            setNewLook(false);
            void act(
              `newlook:${look}`,
              async () => {
                if (sheet) await hubApi.uploadSheet(cid, look, sheet, (sheet as File).name || "sheet.png");
              },
              `新造型 ${look} 已建好${sheet ? "，设定图已设为当前" : "（还没设定图：出图时这套会缺图，传一张就好）"}`,
              () => hubApi.removeLook(cid, look),
            );
            window.setTimeout(() => document.getElementById(`hub-look-${look}`)?.scrollIntoView({ behavior: "smooth", block: "start" }), 500);
          }}
        />
      )}
      {big && <Lightbox src={big.src} alt={big.alt} onClose={() => setBig(null)} />}
      {ask && (
        <Modal
          title="换掉已定的图？"
          sub={ask.text}
          onClose={() => setAsk(null)}
          foot={
            <>
              <Button variant="secondary" onClick={() => setAsk(null)} autoFocus>
                不换
              </Button>
              <Button variant="primary" onClick={() => (ask.run(), setAsk(null))}>
                换
              </Button>
            </>
          }
        />
      )}
      {toasts}
    </div>
  );
}

/** 参考图说明转人话（后端也转；这里兜底旧接口）：by=owner、refs.face_plate 这类内部字段不显示 */
function humanNote(n: string | null | undefined) {
  const t = (n ?? "").trim();
  if (!t) return "";
  if (t.includes("项目方通过")) return "项目方通过的母版（脸部裁切）";
  if (/by\s*=\s*owner/i.test(t)) return "项目方选定的身份参考";
  const c = t.replace(/[，,]?\s*[\w./=-]*[A-Za-z_][\w./=-]*\s*同款/g, "").replace(/^[，,\s]+|[，,\s]+$/g, "");
  return /^[ -~]*$/.test(c) ? "" : c;
}

const ZONE_NAME: Record<string, string> = { upper: "上身", lower: "下装", body: "全身 / 身体", feet: "鞋", hand: "手部", neck: "颈部", waist: "腰部", face: "脸部" };

/** ＋ 新造型（UIAUDIT 回退清单 P0-3）：场合 + 穿什么（项目方写，系统只存）+ 可选设定图。一个“建好”按钮 */
function NewLookDialog({ d, onClose, onDone }: { d: HubChar; onClose: () => void; onDone: (look: string, sheet: File | null) => void }) {
  const [use, setUse] = useState("");
  const [outfit, setOutfit] = useState("");
  const [shoes, setShoes] = useState("");
  const [acc, setAcc] = useState("");
  const [sheet, setSheet] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const why = !use.trim() ? "写一下这套造型用在什么场合" : !(outfit.trim() || shoes.trim() || acc.trim()) ? "至少写一项穿什么" : null;
  async function go() {
    if (why) return;
    setBusy(true);
    setErr(null);
    try {
      const r = await hubApi.newLook(d.cid, { use: use.trim(), outfit: outfit.trim(), shoes: shoes.trim(), accessory: acc.trim() });
      onDone(r.look, sheet);
    } catch (e) {
      setErr(`没建上：${(e as Error).message}。数据没改动，可以再试一次`);
    } finally {
      setBusy(false);
    }
  }
  return createPortal(
    <Modal
      title={`给 ${d.name} 新建一套造型`}
      sub="写场合和穿什么（多件用顿号隔开），出图时按这套的部件找参考；设定图可以现在传，也可以以后在造型里传。"
      onClose={onClose}
      foot={
        <>
          <Button variant="ghost" onClick={onClose}>
            取消
          </Button>
          <Button variant="primary" disabled={!!why || busy} why={why ?? ""} onClick={() => void go()}>
            {busy ? "正在建…" : "建好"}
          </Button>
        </>
      }
    >
      <div className="hub-nl">
        <label className="hub-up-l" htmlFor="hub-nl-use">
          场合
        </label>
        <input id="hub-nl-use" className="ds-input" value={use} onChange={(e) => setUse(e.target.value)} placeholder="例如：酒会 / 出差" />
        <label className="hub-up-l" htmlFor="hub-nl-o">
          衣服
        </label>
        <input id="hub-nl-o" className="ds-input" value={outfit} onChange={(e) => setOutfit(e.target.value)} placeholder="例如：黑色缎面长裙" />
        <label className="hub-up-l" htmlFor="hub-nl-s">
          鞋
        </label>
        <input id="hub-nl-s" className="ds-input" value={shoes} onChange={(e) => setShoes(e.target.value)} placeholder="例如：银色细高跟" />
        <label className="hub-up-l" htmlFor="hub-nl-a">
          饰品
        </label>
        <input id="hub-nl-a" className="ds-input" value={acc} onChange={(e) => setAcc(e.target.value)} placeholder="例如：珍珠耳环、细银链" />
        <label className="hub-up-l">设定图（可选）</label>
        <label className="ds-btn sm hub-nl-file">
          {sheet ? `已选：${sheet.name}` : "选一张设定图"}
          <input type="file" accept="image/png,image/jpeg,image/webp" hidden onChange={(e) => setSheet(e.target.files?.[0] ?? null)} />
        </label>
        {err && (
          <p className="ds-note warn hub-up-err" role="alert">
            {err}
            <Button size="xs" variant="secondary" onClick={() => void go()}>
              再试一次
            </Button>
          </p>
        )}
      </div>
    </Modal>,
    document.body,
  );
}

/** 排期：角色 × 集（UIAUDIT 回退清单 P1-13）。每集一行：剧本逐镜登记用了哪几套（带镜数），点一套 = 整集改用它；再点 = 回到按剧本逐镜 */
function ScheduleSection({ d, busy, onSet }: { d: HubChar; busy: string | null; onSet: (ep: number, look: string | null, prev: string | null) => void }) {
  const rows = d.schedule ?? [];
  return (
    <section id="hub-schedule" className="hub-sec">
      <SecHead
        title="排期：每集用哪套造型"
        sub="默认按剧本逐镜登记（数字是镜数）。点一套 = 这一集整集改用它（集内“从第 N 镜起换装”会被覆盖）；再点一次 = 回到按剧本。10 秒内可撤销。"
      />
      {rows.length ? (
        <div className="hub-sch">
          {rows.map((r) => (
            <div key={r.ep} className="hub-sch-row">
              <b>第 {r.ep} 集</b>
              <div className="hub-sch-looks" role="group" aria-label={`第 ${r.ep} 集用哪套造型`}>
                {d.looks.map((l) => {
                  const n = r.registered[l.look] ?? 0;
                  const on = r.override ? r.override === l.look : n > 0;
                  return (
                    <button
                      key={l.look}
                      className={`hub-sch-lk${on ? " on" : ""}${r.override === l.look ? " ov" : ""}`}
                      aria-pressed={on}
                      disabled={!!busy}
                      onClick={() => onSet(r.ep, r.override === l.look ? null : l.look, r.override)}
                      title={r.override === l.look ? "整集用这套（点一下回到按剧本逐镜）" : `点一下：第 ${r.ep} 集整集改用造型 ${l.look}`}
                    >
                      {l.look}
                      {!r.override && n > 0 && <small>{n} 镜</small>}
                    </button>
                  );
                })}
              </div>
              <span className="ds-small ds-muted">{r.override ? `整集用 ${r.override}（人物页改的）` : Object.keys(r.registered).length > 1 ? "集内换装（按剧本）" : "按剧本"}</span>
            </div>
          ))}
        </div>
      ) : (
        <p className="ds-muted ds-small">还没有逐镜登记（剧本导入、系统登记造型后，这里按集列出）。</p>
      )}
    </section>
  );
}

/** 声音（UIRSI 11-01：试听统一用 ds/MediaPlayer；音色换 / A/B 在声音页 VoiceStudio，这里只听 + 跳过去） */
function VoiceSection({ cid, name, voice }: { cid: string; name: string; voice: HubChar["voice"] }) {
  const [url, setUrl] = useState<string | null>(null);
  const [line, setLine] = useState<string>("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const load = useCallback(async () => {
    setBusy(true);
    setErr(null);
    try {
      const r = await fetch("/api/voices/preview", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ cid }) });
      const j = (await r.json().catch(() => ({}))) as { url?: string; text?: string; detail?: string };
      if (!r.ok || !j.url) throw new Error(j.detail ?? `HTTP ${r.status}`);
      setUrl(j.url);
      setLine(j.text ?? "");
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  }, [cid]);
  // UIAUDIT r8：不在页面打开时自动合成试听（那是一次写缓存的请求），点 ▶ 才合成
  useEffect(() => {
    setUrl(null);
    setErr(null);
  }, [cid]);
  const desc = voice ? [voice.gender === "female" ? "女声" : voice.gender === "male" ? "男声" : null, voice.age ? `${voice.age} 岁` : null, voice.speed && voice.speed !== 1 ? `语速 ${voice.speed}` : "正常语速"].filter(Boolean).join(" · ") : "";
  return (
    <section id="hub-voice" className="hub-sec">
      <SecHead
        title="声音"
        sub={voice ? `${name}的配音音色：${desc}` : `还没给 ${name} 配音色`}
        extra={
          <a className="hub-link" href="#/sound?tab=voice">
            换音色 / A/B 对比 ›
          </a>
        }
      />
      {voice && (
        <div className="hub-voice">
          {url ? (
            <AudioPlayer src={url} title={line ? `“${line}”` : "试听"} sub={voice.note ?? undefined} />
          ) : (
            <div className="hub-voice-wait">
              <Button variant="primary" disabled={busy} onClick={() => void load()} title="用这个人物的音色念一句他自己的台词（本机配音模型，几秒钟）">
                {busy ? "正在合成…" : "▶ 试听"}
              </Button>
              {err && (
                <p className="ds-note warn hub-up-err">
                  试听还没合成出来：{err}
                  <Button size="xs" variant="secondary" onClick={() => void load()}>
                    再试一次
                  </Button>
                </p>
              )}
              {voice.note && <p className="ds-small ds-muted">{voice.note}</p>}
            </div>
          )}
        </div>
      )}
    </section>
  );
}

function fileLabel(f: string) {
  if (f.includes("face_ref2va")) return "脸部裁切（视频参考用）";
  if (f.includes("face_ref")) return "设定图脸部裁切";
  return "身份参考图";
}

function SecHead({ title, sub, extra }: { title: ReactNode; sub?: ReactNode; extra?: ReactNode }) {
  return (
    <header className="hub-sec-h">
      <div>
        <h2>{title}</h2>
        {sub && <p>{sub}</p>}
      </div>
      {extra}
    </header>
  );
}

function Hero({ d, onAdd, onBig }: { d: HubChar; onAdd: () => void; onBig: (b: { src: string; alt: string }) => void }) {
  const sheets = d.looks.filter((l) => l.sheet).length;
  return (
    <header className="hub-hero">
      <button className="hub-hero-face" onClick={() => d.face && onBig({ src: d.face.url, alt: `${d.name} 身份脸` })} title="当前身份脸 · 点开看大图" disabled={!d.face}>
        {d.face ? <img src={thumb(d.face.url, 240) ?? d.face.url} alt="" /> : <b>{d.name.slice(0, 1)}</b>}
      </button>
      <div className="hub-hero-t">
        <h1>{d.name}</h1>
        <p>
          {sheets}/{d.looks.length} 套造型已选设定图 · 衣橱 {d.items.length} 件
          {d.marker && <span title="剧本里的辨识特征（只显示）"> · {d.marker}</span>}
        </p>
        <div className="hub-hero-tags">
          {d.missing > 0 ? (
            <Tag tone="bad" dot title="缺图的部件出图会被拦下">
              资产缺图 {d.missing}
            </Tag>
          ) : (
            <Tag tone="ok" dot>
              不缺图，可以出图
            </Tag>
          )}
          {d.sheet_only > 0 && (
            <Tag tone="warn" dot title="这些部件衣橱里还没有单品图，出图时用设定图裁切；补上单品图会更准">
              {d.sheet_only} 个部件只有设定图
            </Tag>
          )}
        </div>
      </div>
      <div className="hub-hero-act">
        <Button variant="primary" onClick={onAdd}>
          ＋ 添加单品
        </Button>
        <span className="ds-small ds-muted">也可以把图片拖进来，或 Ctrl+V 粘贴</span>
      </div>
    </header>
  );
}

function LookSection({
  cid,
  name,
  lk,
  items,
  busy,
  onSheet,
  onPart,
  onBig,
  onUploadSheet,
  onRemove,
  onDelCand,
  onRegen,
  rejected,
  notify,
  onChangedAll,
}: {
  cid: string;
  name: string;
  lk: HubLook;
  items: HubItem[];
  busy: string | null;
  onSheet: (lk: HubLook, file: string) => void;
  onPart: (lk: HubLook, p: Part, it: HubItem | null) => void;
  onBig: (b: { src: string; alt: string }) => void;
  onUploadSheet: (f: File) => void;
  onRemove?: () => void;
  onDelCand: (file: string) => void;
  onRegen: (lk: HubLook) => void;
  rejected: Record<string, { reasons: string[]; note: string }>;
  notify: (text: string, undo?: () => Promise<unknown>, err?: boolean) => void;
  onChangedAll: () => void;
}) {
  const [pick, setPick] = useState<string | null>(null);
  void cid;
  return (
    <section id={`hub-look-${lk.look}`} className="hub-sec hub-look">
      <SecHead
        title={
          <>
            <span className="hub-letter">{lk.look}</span>造型 {lk.look}
          </>
        }
        sub={lk.use}
        extra={
          <div className="hub-look-counts">
            {lk.counts.missing > 0 && (
              <Tag tone="bad" dot>
                缺图 {lk.counts.missing}
              </Tag>
            )}
            {lk.counts.sheet_only > 0 && (
              <Tag tone="warn" dot>
                仅设定图 {lk.counts.sheet_only}
              </Tag>
            )}
            <Tag tone="ok" dot>
              单品图 {lk.counts.wardrobe}
            </Tag>
            {lk.sheet && (
              <button className="regen-btn regen-sm" onClick={() => onRegen(lk)} title="以当前设定图为底图，加装备图和要求再生成一张候选">
                ↻ 再生成
              </button>
            )}
            <label className="ds-btn sm" title="给这套造型传一张设定图（设为当前；原来的留在候选里）">
              上传设定图
              <input type="file" accept="image/png,image/jpeg,image/webp" hidden onChange={(e) => (e.target.files?.[0] && onUploadSheet(e.target.files[0]), (e.target.value = ""))} />
            </label>
            {onRemove && (
              <Button size="sm" variant="ghost" onClick={onRemove} title="撤销这套新建的造型（记录留档，不删文件）">
                撤销这套造型
              </Button>
            )}
          </div>
        }
      />
      <div className="hub-look-body">
        <div className="hub-sheet">
          {lk.sheet ? (
            <button className="hub-sheet-main" onClick={() => onBig({ src: lk.sheet!.url, alt: `${name} 造型 ${lk.look} 设定图` })} title="当前设定图 · 点开看大图">
              <img src={thumb(lk.sheet.url, 960) ?? lk.sheet.url} alt={`${name} 造型 ${lk.look} 设定图`} />
              <span className="hub-badge ok">当前设定图</span>
            </button>
          ) : (
            <div className="hub-sheet-main empty">
              <b>还没选设定图</b>
              <span>{lk.candidates.length ? "在下面的候选里点一张" : "右上“上传设定图”传一张；没有设定图，这套造型出图时会缺图"}</span>
            </div>
          )}
          {lk.candidates.length > 0 && (
            <div className="hub-cands" role="list" aria-label={`造型 ${lk.look} 设定图候选`}>
              {lk.candidates.map((c) => (
                <div key={c.file} role="listitem" className="hub-candw">
                <button
                  className={`hub-cand${c.current ? " on" : ""}`}
                  disabled={!!busy}
                  onClick={() => onBig({ src: c.url, alt: `造型 ${lk.look} 种子 ${c.seed}` })}
                  title={c.current ? "当前设定图 · 点开看大图" : "点开看大图；要换成这张，点下面的“用这张”（UIRSI r40：点图本身不再直接换）"}
                >
                  <img src={c.thumb ?? thumb(c.url, 360) ?? c.url} alt={`造型 ${lk.look} 候选 种子 ${c.seed ?? ""}`} loading="lazy" data-zoom-label={`${name} · 造型${lk.look} · 设定图候选${c.seed ? ` · 种子 ${c.seed}` : ""}${c.current ? " · 当前" : ""}`} />
                  <span>{c.current ? "✓ 当前" : `种子 ${c.seed ?? "—"} · 看大图`}</span>
                </button>
                <Verdict
                  kind="sheet"
                  file={c.file}
                  label={`造型 ${lk.look} 的设定图`}
                  cid={cid}
                  current={c.current}
                  rejected={rejected[c.file]}
                  busy={!!busy}
                  onUse={() => onSheet(lk, c.file)}
                  onChanged={onChangedAll}
                  notify={notify}
                />
                {!c.current && (
                  <button className="hub-face-del" disabled={!!busy} onClick={() => onDelCand(c.file)} title="删除这张候选（进回收站，10 秒内可撤销；当前设定图不能删）">
                    删除
                  </button>
                )}
                </div>
              ))}
              <GenTiles where={`sheet:${lk.look}`} />
            </div>
          )}
          {lk.candidates.length === 0 && <div className="hub-cands"><GenTiles where={`sheet:${lk.look}`} /></div>}
        </div>
        <div className="hub-parts">
          <h3>这套造型包含</h3>
          <ul>
            {lk.parts.map((p) => {
              const st = STATUS[p.status] ?? STATUS.extra;
              const k = `${p.label}`;
              const choices = choicesFor(items, p);
              return (
                <li key={k} className={`hub-part st-${p.status}`}>
                  <button className="hub-part-row" onClick={() => setPick(pick === k ? null : k)} aria-expanded={pick === k} title="点开换单品">
                    <span className="hub-part-thumb">{p.item_image ? <img src={thumb(p.item_image.url, 120) ?? p.item_image.url} alt="" data-zoom-label={`${name} · 造型${lk.look} · ${p.slot_name} · ${p.item_name ?? p.label}`} /> : <i>{p.slot_name.slice(0, 1)}</i>}</span>
                    <span className="hub-part-t">
                      <small>{p.slot_name}</small>
                      <b>{p.label}</b>
                      {p.item_name && <em>单品：{p.item_name}</em>}
                      {p.quarantine && (
                        <em className="hub-part-q" title={p.quarantine.why}>
                          暂停：“{p.quarantine.item_name}”待项目方确认
                        </em>
                      )}
                    </span>
                    <Tag tone={st.tone} size="xs" title={st.tip}>
                      {st.label}
                    </Tag>
                  </button>
                  {pick === k && (
                    <div className="hub-pick">
                      {choices.length ? (
                        choices.map((it) => (
                          <button key={it.id} className={`hub-pick-i${it.id === p.item_id ? " on" : ""}`} disabled={!!busy || it.id === p.item_id} title={it.id === p.item_id ? `“${p.label}”现在用的就是这件` : busy ? "正在保存上一步，稍等" : `改用“${it.name}”`} onClick={() => (onPart(lk, p, it), setPick(null))}>
                            {it.image ? <img src={thumb(it.image.url, 120) ?? it.image.url} alt="" data-zoom-label={`${name} · 造型${lk.look} · ${it.slot_name} · ${it.name}`} /> : <i />}
                            <span>{it.name}</span>
                          </button>
                        ))
                      ) : (
                        <span className="ds-small ds-muted">衣橱里还没有“{p.slot_name}”类单品，先“＋ 添加单品”。</span>
                      )}
                      {p.item_id && (
                        <button className="hub-pick-i none" disabled={!!busy} onClick={() => (onPart(lk, p, null), setPick(null))}>
                          <i />
                          <span>不用单品（用设定图）</span>
                        </button>
                      )}
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        </div>
      </div>
    </section>
  );
}

function Wardrobe({
  d,
  busy,
  allItems,
  setAllItems,
  onAdd,
  onToggle,
  onTrash,
  onRename,
  onAddImage,
  onBig,
  onPrimary,
  onRegen,
  onUseRegen,
  notify,
  onChangedAll,
}: {
  d: HubChar;
  busy: string | null;
  allItems: boolean;
  setAllItems: (v: boolean) => void;
  onAdd: () => void;
  onToggle: (it: HubItem, lk: HubLook) => void;
  onTrash: (it: HubItem) => void;
  onRename: (it: HubItem, name: string) => void;
  onAddImage: (it: HubItem, f: File) => void;
  onBig: (b: { src: string; alt: string }) => void;
  onPrimary: (it: HubItem, file: string) => void;
  onRegen: (it: HubItem) => void;
  onUseRegen: (it: HubItem, file: string) => void;
  notify: (text: string, undo?: () => Promise<unknown>, err?: boolean) => void;
  onChangedAll: () => void;
}) {
  const [cat, setCat] = useState<string>("all");
  const [edit, setEdit] = useState<string | null>(null);
  const counts = useMemo(() => {
    const m = new Map<string, number>();
    for (const it of d.items) m.set(catOf(it), (m.get(catOf(it)) ?? 0) + 1);
    return m;
  }, [d.items]);
  const list = d.items.filter((it) => cat === "all" || catOf(it) === cat);
  return (
    <section id="hub-wardrobe" className="hub-sec">
      <SecHead
        title="衣橱单品"
        sub="衣服、鞋、饰品、指甲、包……每件一张图。点 A / B / C 就挂到那套造型，出图时用它做参考。"
        extra={
          <Button variant="primary" size="sm" onClick={onAdd}>
            ＋ 添加单品
          </Button>
        }
      />
      <div className="hub-cats" role="tablist" aria-label="按类别看">
        <button role="tab" aria-selected={cat === "all"} className={cat === "all" ? "on" : ""} onClick={() => setCat("all")}>
          全部 <small>{d.items.length}</small>
        </button>
        {CATS.filter((c) => counts.get(c.id) || ["outfit", "shoes", "accessory", "nails", "bag"].includes(c.id)).map((c) => (
          <button key={c.id} role="tab" aria-selected={cat === c.id} className={cat === c.id ? "on" : ""} onClick={() => setCat(c.id)}>
            {c.name} <small>{counts.get(c.id) ?? 0}</small>
          </button>
        ))}
      </div>
      <div className="hub-items">
        {list.map((it) => (
          <article key={it.id} id={`hub-item-${it.id}`} className={`hub-item${(it.looks ?? []).length ? "" : " loose"}`}>
            <button className="hub-item-img" onClick={() => it.image && onBig({ src: it.image.url, alt: it.name })} disabled={!it.image} title={it.image ? "点开看大图" : "没有图"}>
              {it.image ? <img src={thumb(it.image.url, 360) ?? it.image.url} alt={it.name} loading="lazy" data-zoom-label={`${d.name} · ${it.slot_name} · ${it.name}`} /> : <span>没有图</span>}
              <span className="hub-item-cat">{it.slot_name}</span>
              {it.source === "hub_upload" && <span className="hub-item-new">上传</span>}
              {(it.gallery ?? []).length > 1 && <span className="hub-item-n">{(it.gallery ?? []).length} 张图</span>}
            </button>
            {(it.gallery ?? []).length > 1 && (
              <div className="hub-item-gal">
                {(it.gallery ?? []).map((g, i) => (
                  <div key={g.file} className="hub-item-galrow">
                    <button onClick={() => onBig({ src: g.url, alt: `${it.name} · 第 ${i + 1} 张` })} title={i === 0 ? "主参考图（出图用这张）" : `第 ${i + 1} 张`}>
                      <img src={thumb(g.url, 120) ?? g.url} alt="" loading="lazy" data-zoom-label={`${d.name} · ${it.slot_name} · ${it.name} · 第 ${i + 1} 张${i === 0 ? "（主图）" : ""}`} />
                    </button>
                    <Verdict
                      kind="item_image"
                      file={g.file}
                      label={`“${it.name}”的图`}
                      cid={d.cid}
                      current={i === 0}
                      rejected={d.rejected?.[g.file]}
                      busy={!!busy}
                      onUse={() => onPrimary(it, g.file)}
                      onChanged={onChangedAll}
                      notify={notify}
                    />
                  </div>
                ))}
              </div>
            )}
            {(it.regen ?? []).length > 0 && (
              <div className="hub-item-gal" aria-label="再生成的候选">
                {(it.regen ?? []).map((g) => (
                  <div key={g.file} className="hub-item-galrow">
                    <button onClick={() => onBig({ src: g.url, alt: `${it.name} · 再生成候选` })} title="再生成的候选（点开看大图）">
                      <img src={thumb(g.url, 120) ?? g.url} alt="" loading="lazy" data-zoom-label={`${d.name} · ${it.slot_name} · ${it.name} · 再生成候选`} />
                    </button>
                    <Verdict kind="item_image" file={g.file} label={`“${it.name}”的再生成图`} cid={d.cid} current={false} rejected={d.rejected?.[g.file]} busy={!!busy} onUse={() => onUseRegen(it, g.file)} onChanged={onChangedAll} notify={notify} />
                  </div>
                ))}
                <GenTiles where={`item:${it.id}`} />
              </div>
            )}
            {(it.regen ?? []).length === 0 && <div className="hub-item-gal"><GenTiles where={`item:${it.id}`} /></div>}
            <div className="hub-item-b">
              {edit === it.id ? (
                <input
                  className="ds-input hub-item-name-in"
                  autoFocus
                  defaultValue={it.name}
                  aria-label="单品名称"
                  onBlur={(e) => (onRename(it, e.target.value), setEdit(null))}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") (e.target as HTMLInputElement).blur();
                    if (e.key === "Escape") setEdit(null);
                  }}
                />
              ) : (
                <button className="hub-item-name" onClick={() => setEdit(it.id)} title="点一下改名">
                  {it.name}
                </button>
              )}
              {it.note && (
                <p className="hub-item-note" title={it.note}>
                  {it.note}
                </p>
              )}
              <div className="hub-item-looks" role="group" aria-label="挂到造型">
                <span className="hub-item-lbl">挂到造型</span>
                {d.looks.map((lk) => {
                  const on = (it.looks ?? []).some((x) => x.look === lk.look);
                  const ex = (it.looks ?? []).find((x) => x.look === lk.look)?.extra;
                  return (
                    <button
                      key={lk.look}
                      className={`hub-lk${on ? " on" : ""}${ex ? " ex" : ""}`}
                      aria-pressed={on}
                      disabled={!!busy}
                      onClick={() => onToggle(it, lk)}
                      title={on ? `在造型 ${lk.look} 里${ex ? "（附加，正文写到时作为参考）" : `：${(it.looks ?? []).filter((x) => x.look === lk.look).map((x) => x.part).join("、")}`} · 点一下拿下` : `点一下加到造型 ${lk.look}（不替换）`}
                    >
                      {lk.look}
                    </button>
                  );
                })}
                <span className="hub-item-state" title={(it.looks ?? []).map((x) => `造型 ${x.look}：${x.extra ? "附加（正文写到时作为参考）" : `替换“${x.part}”`}`).join("；")}>
                  {(it.looks ?? []).length ? `已挂到 ${(it.looks ?? []).map((x) => `${x.look}·${x.extra ? "附加" : x.part}`).join("、")}` : "还没挂到造型"}
                </span>
              </div>
              <div className="hub-item-tools">
                {it.image && (
                  <button className="hub-item-add" onClick={() => onRegen(it)} title="以这件的主图为底图，按你的要求再生成一张候选">
                    ↻ 再生成
                  </button>
                )}
                <label className="hub-item-add" title="给这件单品再加一张图（另一角度）">
                  ＋图
                  <input type="file" accept="image/png,image/jpeg,image/webp" hidden onChange={(e) => (e.target.files?.[0] && onAddImage(it, e.target.files[0]), (e.target.value = ""))} />
                </label>
                <button className="hub-item-del" onClick={() => onTrash(it)} disabled={!!busy} title="删除（进回收站，可撤销）" aria-label={`删除 ${it.name}`}>
                  删除
                </button>
              </div>
            </div>
          </article>
        ))}
        <button className="hub-item hub-add" onClick={onAdd}>
          <span className="hub-add-plus" aria-hidden>
            ＋
          </span>
          <b>添加单品</b>
          <span>点这里选图，或把图片拖进来 / Ctrl+V 粘贴</span>
        </button>
      </div>
      {d.items_hidden > 0 || allItems ? (
        <button className="hub-more" onClick={() => setAllItems(!allItems)}>
          {allItems ? "只看当前剧用到的单品" : `显示以前登记的单品（${d.items_hidden} 件，当前剧的造型没用到）`}
        </button>
      ) : null}
    </section>
  );
}

function Appearances({ cid, name }: { cid: string; name: string }) {
  const [eps, setEps] = useState<LightEpisode[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    let alive = true;
    assetsV1.episodes().then(
      (x) => alive && setEps(x),
      (e) => alive && setErr(String((e as Error).message ?? e)),
    );
    return () => {
      alive = false;
    };
  }, []);
  const rows = useMemo(
    () =>
      (eps ?? [])
        .map((e) => ({ n: e.number, title: e.title, shots: e.shots.filter((s) => (s.characters ?? []).some((c) => c.character === cid)).map((s) => s.id) }))
        .filter((r) => r.shots.length),
    [eps, cid],
  );
  const total = rows.reduce((a, r) => a + r.shots.length, 0);
  return (
    <section id="hub-appear" className="hub-sec">
      <SecHead title="出场" sub={eps ? (rows.length ? `${name} 出现在 ${rows.length} 集 · ${total} 镜。点镜头号回到画布。` : `当前剧本里还没有 ${name} 的镜头。`) : "正在读分镜…"} />
      {err && <p className="ds-note bad">分镜读不到：{err}</p>}
      {!eps && !err && <Skel h={480} />}{/* 先占住约 10 集的高度：分镜读到前后页面高度不跳，滚到底不会因为晚到的内容“又长出一截”（UIAUDIT r8 衣橱滚不到底） */}
      <div className="hub-appear">
        {rows.map((r) => (
          <div key={r.n} className="hub-ep">
            <b>第 {r.n} 集</b>
            <span className="ds-muted ds-small hub-ep-t" title={r.title}>
              {r.title} · {r.shots.length} 镜
            </span>
            <div className="hub-ep-shots">
              {r.shots.map((s) => (
                <a key={s} href={`#${s}`} title={`在画布打开 ${s}`}>
                  {s.replace(/^ep\d+-/, "")}
                </a>
              ))}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

// ---------------------------------------------------------------- 添加单品
// 项目方 11-01：“这里的报错，我不知道怎么样修改呀？……我想添加一些衣服到我的库里面去。”
// 选图后先问后端（check-image，不写任何东西）：
//   · 这张图已经在库里 → 不是错误：显示那件单品（图 + 名字 + 在哪），主按钮“用这件，挂到所选造型”一键完成，
//     次按钮“仍作为新单品添加（另起名）”；
//   · 不在库里 → 看图起一个人话名字（逻辑模型，关推理），可改；永远不用文件名。
export type DoneInfo = { item: HubItem; mapped: string | null; adopted?: { wasAdopted: boolean; maps: { look: string; part: string; prev: string | null }[] } };

function UploadDialog({ d, initial, onClose, onDone }: { d: HubChar; initial: { file: Blob; name: string } | null; onClose: () => void; onDone: (x: DoneInfo) => void }) {
  const [file, setFile] = useState<Blob | null>(initial?.file ?? null);
  const [name, setName] = useState("");
  const [nameSrc, setNameSrc] = useState<"existing" | "model" | "none" | "typed">("none");
  const [cat, setCat] = useState<string | null>(null);
  const [looks, setLooks] = useState<Set<string>>(new Set());
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<{ msg: string; retry?: () => void } | null>(null);
  const [check, setCheck] = useState<"idle" | "checking" | "done">("idle");
  const [dup, setDup] = useState<{ item: HubItem; inCurrent: boolean } | null>(null);
  const [asNew, setAsNew] = useState(false); // 重复图仍要另起一件
  const [partSel, setPartSel] = useState<Record<string, string>>({}); // 每套造型替换哪一项（"" = 不替换，作为额外）
  const inp = useRef<HTMLInputElement>(null);
  const seq = useRef(0);
  // 预览地址在 effect 里建、在 cleanup 里收（StrictMode 下 effect 会跑两遍：useMemo 建的地址会被第一遍 cleanup 收掉，图就裂了）
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    if (!file) return setUrl(null);
    const u = URL.createObjectURL(file);
    setUrl(u);
    return () => URL.revokeObjectURL(u);
  }, [file]);
  useEffect(() => {
    if (!initial) inp.current?.click();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const fname = (f: Blob) => (f as File).name || `paste.${(f.type.split("/")[1] || "png").replace("jpeg", "jpg")}`;

  /** 查库 + 起名。ignoreDup = 已决定另起一件，只要名字 */
  const runCheck = useCallback(
    async (f: Blob, ignoreDup: boolean, c: string | null) => {
      const my = ++seq.current;
      setCheck("checking");
      setErr(null);
      try {
        const r = await hubApi.check(d.cid, f, fname(f), c, ignoreDup);
        if (my !== seq.current) return;
        if (r.dup && !ignoreDup) {
          setDup({ item: r.dup, inCurrent: r.dup_in_current });
          setCat(catOf(r.dup));
        } else {
          setDup(null);
          if (r.suggested.cat && !c) setCat(r.suggested.cat);
        }
        // 名字：已有单品名 > 看图起的名 > 空着让人写；项目方自己改过就不覆盖
        setNameSrc((src) => {
          if (src === "typed") return src;
          setName(ignoreDup && r.suggested.source === "existing" ? "" : r.suggested.name);
          return r.suggested.name ? r.suggested.source : "none";
        });
      } catch (e) {
        if (my === seq.current) setErr({ msg: `没查成：${(e as Error).message}。可以直接填名称添加，或者`, retry: () => void runCheck(f, ignoreDup, c) });
      } finally {
        if (my === seq.current) setCheck("done");
      }
    },
    [d.cid],
  );
  const pick = (f: Blob) => {
    setFile(f);
    setDup(null);
    setAsNew(false);
    setNameSrc((s) => (s === "typed" ? s : "none"));
    void runCheck(f, false, cat);
  };
  useEffect(() => {
    if (initial?.file) void runCheck(initial.file, false, null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  // 对话框开着时粘贴 = 换图
  useEffect(() => {
    const on = (e: ClipboardEvent) => {
      const f = [...(e.clipboardData?.items ?? [])].find((x) => x.type.startsWith("image/"))?.getAsFile();
      if (f) {
        e.preventDefault();
        e.stopImmediatePropagation();
        pick(f);
      }
    };
    window.addEventListener("paste", on, true);
    return () => window.removeEventListener("paste", on, true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const useDup = dup && !asNew;
  const slot = useDup ? dup.item.slot : (CATS.find((c) => c.id === cat)?.slot ?? null);
  const label = useDup ? dup.item.name : name.trim() || "单品";
  const pickOf = (l: HubLook) => {
    const pk = partFor(l, slot ?? "", label, useDup ? dup.item.zone : null);
    const sel = partSel[l.look];
    if (sel === undefined) return pk; // 没手动选：默认加为附加单品，不替换
    return { ...pk, part: sel || label, extra: !sel, sure: true };
  };
  const targets = d.looks.filter((l) => looks.has(l.look)).map((l) => ({ look: l.look, ...pickOf(l) }));
  const lookNames = targets.map((t) => t.look).join("、");

  async function adoptDup() {
    if (!dup) return;
    setBusy(true);
    setErr(null);
    try {
      const r = await hubApi.adopt(d.cid, dup.item.id, targets.map(({ look, part }) => ({ look, part })));
      onDone({ item: dup.item, mapped: targets.length ? lookNames : null, adopted: { wasAdopted: r.was_adopted, maps: r.mapped } });
    } catch (e) {
      setErr({ msg: `没成功：${(e as Error).message}`, retry: () => void adoptDup() });
    } finally {
      setBusy(false);
    }
  }
  const why = !file ? "先选一张图" : check === "checking" ? "正在看这张图…" : !cat ? "选一下类别" : !name.trim() ? "写个名称" : null;
  async function addNew() {
    if (why || !file) return;
    setBusy(true);
    setErr(null);
    try {
      const r = await hubApi.upload(d.cid, file, fname(file), cat!, name.trim(), targets.map(({ look, part }) => ({ look, part })), note.trim(), asNew);
      onDone({ item: r.item, mapped: targets.length ? lookNames : null });
    } catch (e) {
      const det = (e as { detail?: { dup?: boolean } }).detail;
      if (det?.dup) {
        // 别人刚登记了同一张图：转成“用这件”
        void runCheck(file, false, cat);
      } else setErr({ msg: `没加上：${(e as Error).message}`, retry: () => void addNew() });
    } finally {
      setBusy(false);
    }
  }

  return createPortal(
    <Modal
      title={`给 ${d.name} 添加单品`}
      sub="加进来马上就是参考资产：挂到哪套造型，那套造型出图时就用这张图。"
      onClose={onClose}
      wide
      foot={
        useDup ? (
          <>
            <Button variant="ghost" onClick={onClose}>
              取消
            </Button>
            <Button variant="secondary" disabled={busy} onClick={() => (setAsNew(true), setNameSrc("none"), void runCheck(file!, true, cat))}>
              仍作为新单品添加（另起名）
            </Button>
            <Button variant="primary" disabled={busy} onClick={() => void adoptDup()}>
              {busy ? "正在用…" : targets.length ? (targets.some((t) => !t.extra) ? `用这件，挂到造型 ${lookNames}（有替换）` : `用这件，加到造型 ${lookNames}（不替换）`) : dup.inCurrent ? "用这件（已在当前衣橱）" : "用这件，放进当前衣橱"}
            </Button>
          </>
        ) : (
          <>
            <Button variant="ghost" onClick={onClose}>
              取消
            </Button>
            <Button variant="primary" disabled={!!why || busy} why={why ?? ""} onClick={() => void addNew()}>
              {busy ? "正在加…" : targets.length ? (targets.some((t) => !t.extra) ? `添加，并挂到造型 ${lookNames}（有替换）` : `添加，并加到造型 ${lookNames}（不替换）`) : "添加"}
            </Button>
          </>
        )
      }
    >
      <div className="hub-up">
        <div
          className={`hub-up-img${file ? "" : " empty"}`}
          onClick={() => inp.current?.click()}
          onDragOver={(e) => e.preventDefault()}
          onDrop={(e) => {
            e.preventDefault();
            e.stopPropagation();
            const f = [...e.dataTransfer.files].find((x) => x.type.startsWith("image/"));
            if (f) pick(f);
          }}
          role="button"
          tabIndex={0}
          aria-label="选择图片"
        >
          {url ? <img src={url} alt="要添加的图片" /> : <span>点这里选图，或拖图片进来 / Ctrl+V 粘贴</span>}
          {url && <span className="hub-up-re">换一张</span>}
          <input
            ref={inp}
            type="file"
            accept="image/png,image/jpeg,image/webp"
            hidden
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) pick(f);
              e.target.value = "";
            }}
          />
        </div>
        <div className="hub-up-f">
          {check === "checking" && (
            <p className="hub-up-checking" role="status">
              正在看这张图：查库里有没有、起个名字…
            </p>
          )}
          {useDup ? (
            <div className="hub-dup" role="status">
              <b className="hub-dup-h">这件已经在 {d.name} 的库里</b>
              <div className="hub-dup-card">
                {dup.item.image ? <img src={thumb(dup.item.image.url, 240) ?? dup.item.image.url} alt="" /> : <i />}
                <div>
                  <b>{dup.item.name}</b>
                  <span>
                    {dup.item.slot_name} · {dup.inCurrent ? "在当前衣橱里" : "以前登记的单品（当前剧还没用）"}
                    {(dup.item.looks ?? []).length ? ` · 已在造型 ${[...new Set(dup.item.looks.map((x) => x.look))].join("、")}` : ""}
                  </span>
                </div>
              </div>
              <p className="ds-small ds-muted">不用重复上传。选好要挂的造型，点“用这件”就行；它会出现在当前衣橱里。</p>
            </div>
          ) : (
            <>
              <label className="hub-up-l">类别</label>
              <div className="hub-up-cats" role="radiogroup" aria-label="类别">
                {CATS.map((c) => (
                  <button key={c.id} role="radio" aria-checked={cat === c.id} className={cat === c.id ? "on" : ""} onClick={() => setCat(c.id)}>
                    {c.name}
                  </button>
                ))}
              </div>
              <label className="hub-up-l" htmlFor="hub-up-name">
                名称
                {nameSrc === "model" && <small className="hub-up-src">　看图起的，可以改</small>}
              </label>
              <div className="hub-up-name">
                <input
                  id="hub-up-name"
                  className="ds-input"
                  value={name}
                  onChange={(e) => (setName(e.target.value), setNameSrc("typed"))}
                  placeholder={check === "checking" ? "正在起名…" : "例如：黑色漆皮细带捆绑内衣"}
                />
                {file && (
                  <Button size="sm" variant="ghost" disabled={check === "checking"} onClick={() => (setNameSrc("none"), void runCheck(file, true, cat))} title="让逻辑模型看图重新起一个名字">
                    ↻ 起个名
                  </Button>
                )}
              </div>
              <label className="hub-up-l" htmlFor="hub-up-note">
                备注（可不填）
              </label>
              <input id="hub-up-note" className="ds-input" value={note} onChange={(e) => setNote(e.target.value)} placeholder="例如：部位、材质、尺寸" />
            </>
          )}
          <label className="hub-up-l">挂到哪套造型（可多选，也可以先不挂）</label>
          <div className="hub-up-looks">
            {d.looks.map((l) => {
              const on = looks.has(l.look);
              const t = slot ? pickOf(l) : null;
              return (
                <div key={l.look} className="hub-up-lookw">
                <button
                  key={l.look}
                  className={`hub-up-look${on ? " on" : ""}`}
                  aria-pressed={on}
                  onClick={() => setLooks((s) => (s.has(l.look) ? new Set([...s].filter((x) => x !== l.look)) : new Set([...s, l.look])))}
                >
                  {l.sheet ? <img src={thumb(l.sheet.url, 240) ?? l.sheet.url} alt="" /> : <i />}
                  <span>
                    <b>造型 {l.look}</b>
                    <small>{!t ? l.use : !t.extra ? `替换“${t.part}”` : `加到造型 ${l.look}（不替换）`}</small>
                  </span>
                </button>
                {on && t && t.options.length > 0 && (
                  <select
                    className="ds-input hub-up-part"
                    aria-label={`造型 ${l.look} 替换哪一项`}
                    value={t.extra ? "" : t.part}
                    onChange={(e) => setPartSel((m) => ({ ...m, [l.look]: e.target.value }))}
                  >
                    <option value="">加到造型 {l.look}（不替换）</option>
                    {t.options.map((o) => (
                      <option key={o} value={o}>
                        改为替换“{o}”{t.suggest === o ? "（名字最像）" : ""}
                      </option>
                    ))}
                  </select>
                )}
                </div>
              );
            })}
          </div>
          {err && (
            <p className="ds-note warn hub-up-err" role="alert">
              {err.msg}
              {err.retry && (
                <Button size="xs" variant="secondary" onClick={err.retry}>
                  再试一次
                </Button>
              )}
            </p>
          )}
        </div>
      </div>
    </Modal>,
    document.body,
  );
}
