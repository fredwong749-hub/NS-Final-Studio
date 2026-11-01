// UIRSI r14：挑设定图（项目方任务 T3）。出图线（IMGGEN）出的设定图候选：每个角色 × 每套造型（A/B/C）× 几个种子，
// 并排大图对比，点“选这张…”= 项目方闸门（勾选本人 + 原话），记到 runs/<id>/ui_sheet_picks.json（POST /api/story-images/pick）。
// 只看、只记选择；登记成身份参考由总调度 / CONSIST 按这份记录做。
import { thumb } from "../../thumb";
import { useEffect, useMemo, useState } from "react";
import { Button, Empty, Skel, Tag } from "../../ds";
import { loadStoryImages, type StoryImg, type StoryImages } from "../storyImages";
import { showUndo } from "../../ds/Undo.helpers";

type Names = Record<string, string>;

async function loadNames(run: string | null): Promise<Names> {
  if (!run) return {};
  try {
    const r = await fetch(`/api/story-runs/${encodeURIComponent(run)}/artifact/P1`);
    if (!r.ok) return {};
    const j = (await r.json()) as { json?: { characters?: { name: string; char_id: string }[] } };
    return Object.fromEntries((j.json?.characters ?? []).map((c) => [c.char_id, c.name]));
  } catch {
    return {};
  }
}

export function SheetPicker({ only, fallbackNames }: { only?: string | null; fallbackNames?: Names }) {
  const [im, setIm] = useState<StoryImages | null>(null);
  const [names, setNames] = useState<Names>({});
  const [big, setBig] = useState<StoryImg | null>(null);
  const [tick, setTick] = useState(0);
  useEffect(() => {
    let alive = true;
    loadStoryImages(tick > 0).then((x) => {
      if (!alive) return;
      setIm(x);
      void loadNames(x.run).then((n) => alive && setNames(n));
    });
    return () => {
      alive = false;
    };
  }, [tick]);
  const [busy, setBusy] = useState<string | null>(null);
  const post = (body: Record<string, unknown>) =>
    fetch("/api/story-images/pick", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ run: im?.run, by: "owner", ...body }) }).then(async (r) => {
      if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail ?? `HTTP ${r.status}`);
    });
  /** 点选即生效；10 秒内可撤销（撤销 = 选回上一张，原来没选就取消） */
  async function pick(cid: string, x: StoryImg, prev: string | null) {
    setBusy(x.path);
    try {
      await post({ char: cid, path: x.path });
      setTick((n) => n + 1);
      showUndo(`已选定 ${nameOf(cid)} · 造型 ${x.look ?? ""} · 种子 ${x.seed ?? ""}`, async () => {
        await post(prev ? { char: cid, path: prev } : { char: cid, path: "", look: x.look });
        setTick((n) => n + 1);
      });
    } catch (e) {
      showUndo(`没选上：${(e as Error).message}`, async () => undefined, 4000);
    } finally {
      setBusy(null);
    }
  }
  const chars = useMemo(() => Object.entries(im?.chars ?? {}).filter(([c]) => !only || c === only), [im, only]);
  if (!im) return <Skel h={280} />;
  if (!chars.length) return only ? null : <Empty icon="◎" title="还没有设定图候选" sub="系统出了设定图后，这里按角色 × 造型并排显示，点“选这张”记下你的选择。" />;
  const nameOf = (c: string) => names[c] ?? fallbackNames?.[c] ?? c;

  return (
    <section className="sp-wrap" aria-label="设定图候选">
      {!only && (
        <header className="sp-h">
          <span className="ds-small ds-muted">
            {chars.length} 个角色 · 每套造型挑一张
          </span>
        </header>
      )}
      {chars.map(([cid, list]) => {
        const looks = [...new Set(list.map((x) => x.look ?? "—"))];
        const picked = im.picks?.[cid] ?? {};
        return (
          <article key={cid} className="sp-char">
            <h3>
              {nameOf(cid)} <span className="ds-muted ds-small">{cid}</span>
              <Tag tone={Object.keys(picked).filter((k) => k !== "_history").length >= looks.length ? "ok" : "warn"} size="xs">
                已选 {Object.keys(picked).length}/{looks.length} 套
              </Tag>
            </h3>
            {looks.map((lk) => {
              const cands = list.filter((x) => (x.look ?? "—") === lk);
              const pk = picked[lk]?.path;
              return (
                <div key={lk} className="sp-look">
                  <div className="sp-look-h">
                    <b>造型 {lk}</b>
                    <span className="ds-small ds-muted">{cands.length} 张候选{pk ? " · 已选" : " · 还没选"}</span>
                  </div>
                  <div className="sp-cands">
                    {cands.map((x) => {
                      const on = pk === x.path;
                      return (
                        <figure key={x.path} className={`sp-cand${on ? " on" : ""}`}>
                          <button className="sp-img" onClick={() => setBig(x)} title="点开看大图">
                            <img src={x.thumb ?? thumb(x.url, 480) ?? x.url} alt={`${nameOf(cid)} 造型 ${lk} 种子 ${x.seed ?? ""}`} loading="lazy" decoding="async" />
                          </button>
                          <figcaption>
                            <span>种子 {x.seed ?? "—"}</span>
                            {on ? (
                              <Tag tone="ok" dot size="xs">
                                已选
                              </Tag>
                            ) : (
                              <Button size="xs" variant="secondary" disabled={!!busy} onClick={() => void pick(cid, x, pk ?? null)} title="点一下就选定（记在你的账户名下，10 秒内可撤销）">
                                选这张
                              </Button>
                            )}
                          </figcaption>
                        </figure>
                      );
                    })}
                  </div>
                </div>
              );
            })}
          </article>
        );
      })}
      {big && (
        <div className="sp-big" role="dialog" aria-label="大图" onClick={() => setBig(null)}>
          <img src={big.url} alt="" />
          <span className="ds-small">{big.path} · 点任意处关闭</span>
        </div>
      )}
    </section>
  );
}
