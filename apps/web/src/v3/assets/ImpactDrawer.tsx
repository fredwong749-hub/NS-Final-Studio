// UX5：资产改版 → 影响面清单 → 勾选排队重出（B_revision §4 / §6.3、C_research #4 #5 #13 #15）。
// - 影响面：POST /api/revisions/impact（依赖账本里的键）或 /api/revisions/impact-shots（形象 / 单品 / 场景），都只读。
// - 已定稿的格默认不勾（项目方定稿的再标一层）；GPU 时间按勾选的格现算（近期同类任务耗时中位数 × 格数 ÷ 可用道数）。
// - 排队重出只调用已有的整集出片接口：每集一个任务、只含勾选的镜头、mode=review（出完等项目方定稿，旧定稿保留）。
// - 资产改了只“标记”，不自动重出；这个抽屉是唯一会排任务的地方，而且要再确认一次。
import { useEffect, useMemo, useState } from "react";
import { useStudio } from "../../store";
import { Button, Drawer, Empty, LoadError, Loading, Modal, Seg, Tag } from "../../ds";
import { fmtDur } from "../../ds/helpers";
import { revApi, STAGE_NAME, type Impact, type ImpactCell, type Stage } from "./rev_api";

export type ImpactSource = { kind: "key"; key: string; label: string } | { kind: "shots"; shots: string[]; label: string; stages?: Stage[] };

const cellId = (c: ImpactCell) => `${c.shot_id}|${c.stage}`;
const shotNo = (id: string) => id.split("-")[1] ?? id;

export function ImpactDrawer({ src, onClose }: { src: ImpactSource; onClose: () => void }) {
  const st = useStudio();
  const [stageSet, setStageSet] = useState<"image" | "frames" | "video">(() => (src.kind === "shots" && src.stages?.includes("video") ? "video" : "image"));
  const stages: Stage[] = stageSet === "image" ? ["image"] : stageSet === "frames" ? ["image", "last"] : ["video"];
  const [imp, setImp] = useState<Impact | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [sel, setSel] = useState<Set<string>>(new Set());
  const [onlyEp, setOnlyEp] = useState<number | null>(null);
  const [confirm, setConfirm] = useState(false);
  const [done, setDone] = useState<{ ep: number; ok: boolean; msg: string }[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [reload, setReload] = useState(0);

  useEffect(() => {
    let alive = true;
    setImp(null);
    setErr(null);
    const p = src.kind === "key" ? revApi.impact([src.key]) : revApi.impactShots(src.shots, stages, src.label);
    p.then(
      (d) => {
        if (!alive) return;
        setImp(d);
        const lockedIds = new Set(d.cells.filter((c) => c.locked).map(cellId));
        setSel(new Set(d.cells.filter((c) => c.default_selected && !lockedIds.has(cellId(c))).map(cellId)));
      },
      (e) => alive && setErr(String((e as Error).message ?? e)),
    );
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [src.kind === "key" ? src.key : src.shots.join(","), stageSet, reload]);

  // 同一镜同一格的当前版和定稿版不同时，后端给两行；界面上合成一格（重出也只算一次），有一版定稿就算定稿
  const cells = useMemo(() => {
    const m = new Map<string, ImpactCell>();
    for (const c of imp?.cells ?? []) {
      const k = cellId(c);
      const o = m.get(k);
      m.set(k, o ? { ...o, locked: o.locked || c.locked, owner_locked: o.owner_locked || c.owner_locked, active: o.active || c.active, estimated: o.estimated && c.estimated, chain: o.chain.length ? o.chain : c.chain, default_selected: o.default_selected && c.default_selected } : c);
    }
    return [...m.values()];
  }, [imp]);
  const byEp = useMemo(() => {
    const m = new Map<number, ImpactCell[]>();
    for (const c of cells) {
      const k = c.episode ?? 0;
      m.set(k, [...(m.get(k) ?? []), c]);
    }
    return [...m.entries()].sort((a, b) => a[0] - b[0]);
  }, [cells]);
  const shown = onlyEp ? byEp.filter(([e]) => e === onlyEp) : byEp;
  const selCells = cells.filter((c) => sel.has(cellId(c)));
  const per = imp?.gpu_estimate_s.per_job;
  const lanes = imp?.gpu_estimate_s.lanes ?? 1;
  const jobs = new Set(selCells.map(cellId)).size;
  const serial = per ? selCells.reduce((a, c) => a + (c.stage === "video" ? per.video : per.frame), 0) : 0;
  const selEps = [...new Set(selCells.map((c) => c.episode ?? 0))].sort((a, b) => a - b);
  const toggle = (ids: string[], on: boolean) =>
    setSel((s) => {
      const n = new Set(s);
      for (const i of ids) on ? n.add(i) : n.delete(i);
      return n;
    });

  async function run() {
    setBusy(true);
    const out: { ep: number; ok: boolean; msg: string }[] = [];
    for (const ep of selEps) {
      const cs = selCells.filter((c) => (c.episode ?? 0) === ep);
      const shots = [...new Set(cs.map((c) => c.shot_id))];
      const stg = [...new Set(cs.map((c) => c.stage))] as Stage[];
      try {
        await revApi.rerun(ep, shots, stg, `rev:${src.kind === "key" ? src.key : src.label}`);
        out.push({ ep, ok: true, msg: `已排进第 ${ep} 集整集出片：${shots.length} 镜 · ${stg.map((x) => STAGE_NAME[x]).join(" / ")}` });
      } catch (e) {
        out.push({ ep, ok: false, msg: `第 ${ep} 集没排上：${String((e as Error).message ?? e)}` });
      }
    }
    setBusy(false);
    setDone(out);
    setConfirm(false);
    if (out.some((x) => x.ok)) st.notify(`修改重出已排队（${out.filter((x) => x.ok).length} 集），出完等你定稿`);
  }

  const c = imp?.counts;
  return (
    <Drawer
      wide
      title={<>影响面 · {src.label}</>}
      onClose={onClose}
      foot={
        <>
          <span className="ds-muted ds-small">
            {imp ? (
              <>
                已勾 <b>{jobs}</b> 格 · {selEps.length} 集 · 预计 GPU {fmtDur(serial / lanes)}（{lanes} 道并行；串行 {fmtDur(serial)}）
              </>
            ) : (
              "影响面读到后才能勾选"
            )}
          </span>
          <span className="grow" />
          <Button onClick={onClose}>关闭</Button>
          <Button variant="primary" disabled={!jobs || busy} why={!imp ? "影响面还没读到" : "先勾选要重出的格子"} onClick={() => setConfirm(true)}>
            排队重出 {jobs ? `${jobs} 格` : ""}
          </Button>
        </>
      }
    >
      <p className="ds-note info">
        资产改了只<b>标记</b>用到它的镜头，不会自动重出。这里勾选要重出的格子再排队：<b>已定稿的默认不勾</b>；重出走整集出片（出完等你定稿，旧定稿保留，可随时对比回去）。
      </p>
      <div className="ds-row ac-imp-tools">
        {src.kind === "shots" && (
          <Seg
            value={stageSet}
            onChange={setStageSet}
            label="重出哪一格"
            options={[
              ["image", "首帧"],
              ["frames", "首帧 + 尾帧"],
              ["video", "视频"],
            ]}
          />
        )}
        <span className="ds-grow" />
        {imp && byEp.length > 1 && (
          <Button size="sm" variant="ghost" onClick={() => setOnlyEp(onlyEp ? null : st.epNum)} title="只看当前集">
            {onlyEp ? "看全部集" : `只看第 ${st.epNum} 集`}
          </Button>
        )}
        {imp && (
          <>
            <Button size="sm" variant="ghost" onClick={() => setSel(new Set(cells.filter((x) => !x.locked).map(cellId)))}>
              勾全部未定稿
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setSel(new Set())}>
              全不勾
            </Button>
          </>
        )}
      </div>

      {err && (
        <LoadError
          what="影响面"
          err={err}
          retry={() => setReload((n) => n + 1)}
          hint={src.kind === "shots" ? `用到它的镜头（按集摘要估计）：${src.shots.length} 镜。定稿状态要等新接口上线才知道，所以先不能勾选重出。` : undefined}
        />
      )}
      {err && src.kind === "shots" && <ShotChipsPlain shots={src.shots} />}
      {!imp && !err && <Loading text="正在算影响面…" />}

      {imp && (
        <>
          <div className="ac-imp-sum">
            <div>
              <b>{c!.shots}</b>
              <span>镜</span>
            </div>
            <div>
              <b>{c!.cells}</b>
              <span>格</span>
            </div>
            <div>
              <b>{c!.locked}</b>
              <span>已定稿（默认不勾）</span>
            </div>
            <div>
              <b>{c!.owner_locked}</b>
              <span>其中项目方定稿</span>
            </div>
            <div>
              <b>{c!.estimated}</b>
              <span>估计（旧版本没盖章）</span>
            </div>
          </div>
          {imp.requires_owner && (
            <p className="ds-note warn">
              这类改动是项目方闸门：{imp.owner_reasons.join("；")}。系统只排重出、不改资产本身；换版本本身要项目方本人确认。
            </p>
          )}
          {!cells.length && <Empty icon="✓" title="没有镜头受影响" sub="没有哪一镜的当前版本或定稿版本用到它。" />}
          {shown.map(([ep, cs]) => {
            const ids = cs.map(cellId);
            const nOn = ids.filter((i) => sel.has(i)).length;
            return (
              <section key={ep} className="ac-imp-ep">
                <header>
                  <label className="ds-check">
                    <input
                      type="checkbox"
                      checked={nOn === ids.length && ids.length > 0}
                      ref={(el) => {
                        if (el) el.indeterminate = nOn > 0 && nOn < ids.length;
                      }}
                      onChange={(e) => toggle(ids, e.target.checked)}
                    />
                    <b>第 {ep} 集</b>
                  </label>
                  <span className="ds-muted ds-small">
                    {(["image", "last", "video"] as Stage[])
                      .map((s) => [s, cs.filter((x) => x.stage === s).length] as const)
                      .filter(([, n]) => n)
                      .map(([s, n]) => `${STAGE_NAME[s]} ${n}`)
                      .join(" · ")}
                    {" · "}已勾 {nOn}
                  </span>
                </header>
                <div className="ac-imp-cells">
                  {cs.map((x) => {
                    const id = cellId(x);
                    return (
                      <label key={id} className={`ac-imp-cell${sel.has(id) ? " on" : ""}${x.locked ? " locked" : ""}`} title={`${x.shot_id} ${STAGE_NAME[x.stage]} #${x.take_n}${x.active ? "（当前）" : ""}${x.locked ? "（已定稿）" : ""}${x.chain.length ? `\n定稿后会连带：${x.chain.map((k) => (k === "cut" ? "成片" : STAGE_NAME[k as Stage])).join("、")}` : ""}${x.estimated ? "\n估计：这一版出的时候还没记录用了哪个版本" : x.from_v ? `\n当时用的是 v${x.from_v}` : ""}`}>
                        <input type="checkbox" checked={sel.has(id)} onChange={(e) => toggle([id], e.target.checked)} />
                        <b>{shotNo(x.shot_id)}</b>
                        <span>{STAGE_NAME[x.stage]}</span>
                        {x.locked && <Tag tone={x.owner_locked ? "ok" : "warn"}>{x.owner_locked ? "定稿" : "自动定"}</Tag>}
                        {x.estimated && <i className="ac-est" title="估计">≈</i>}
                      </label>
                    );
                  })}
                </div>
              </section>
            );
          })}
        </>
      )}

      {done && (
        <div className="ac-imp-done">
          {done.map((d) => (
            <p key={d.ep} className={`ds-note ${d.ok ? "info" : "warn"}`}>
              {d.msg}
            </p>
          ))}
        </div>
      )}

      {confirm && imp && (
        <Modal
          title={`排队重出 ${jobs} 格？`}
          sub="每集一个整集出片任务，只含勾选的镜头。出完是“候选 · 待你定稿”，不会自动定稿，旧定稿一直保留。"
          onClose={() => setConfirm(false)}
          foot={
            <>
              <Button onClick={() => setConfirm(false)}>取消</Button>
              <Button variant="primary" disabled={busy} onClick={() => void run()}>
                {busy ? "正在排队…" : `确认排队（${selEps.length} 集）`}
              </Button>
            </>
          }
        >
          <dl className="ds-kv">
            {selEps.map((ep) => {
              const cs = selCells.filter((x) => (x.episode ?? 0) === ep);
              return [
                <dt key={`t${ep}`}>第 {ep} 集</dt>,
                <dd key={`d${ep}`}>
                  {[...new Set(cs.map((x) => shotNo(x.shot_id)))].join(" ")} · {[...new Set(cs.map((x) => STAGE_NAME[x.stage]))].join(" / ")}
                </dd>,
              ];
            })}
            <dt>预计 GPU</dt>
            <dd>
              {fmtDur(serial / lanes)}（{lanes} 道并行），串行 {fmtDur(serial)}
            </dd>
            <dt>已定稿</dt>
            <dd>{selCells.filter((x) => x.locked).length} 格也勾上了：重出后旧定稿保留，等你选</dd>
          </dl>
          {serial / lanes > 7200 && <p className="ds-note warn">预计超过 2 小时，正在跑的任务会往后排。</p>}
        </Modal>
      )}
    </Drawer>
  );
}

function ShotChipsPlain({ shots }: { shots: string[] }) {
  const by = new Map<string, string[]>();
  for (const s of shots) {
    const [ep] = s.split("-");
    by.set(ep, [...(by.get(ep) ?? []), s]);
  }
  return (
    <div className="ac-usage">
      {[...by.entries()].map(([ep, ss]) => (
        <div key={ep} className="ac-usage-ep">
          <b>第 {Number(ep.slice(2))} 集</b>
          <span>
            {ss.map((s) => (
              <a key={s} href={`#${s}`} className="ac-shot">
                {shotNo(s)}
              </a>
            ))}
          </span>
        </div>
      ))}
    </div>
  );
}
export { ShotChipsPlain };
