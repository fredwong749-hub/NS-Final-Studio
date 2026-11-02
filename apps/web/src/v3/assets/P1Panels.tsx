// UX6：资产中心 B7–B10 的只读 + 最小可编辑面板（A_assets_ia.md §5）。
//   道具·产品（B7）：衣橱里带 LoRA 的饰品只读映射 + 自建道具（名称 / 说明 / LoRA 文件 / 触发词）
//   音色（B8）：config/voices.json 只读展示；改动只写“提议”到 data/assets/proposals/（换音色属于项目方闸门，原话可选附上）
//   LoRA 总表（B9）：只读合并（gpu3 registry / models.lock / 出图指针 / 附加视频 LoRA / 衣橱 / 剧本 / 登记扩展），
//                   视频身份 LoRA 带 sha 与训练所用定妆版本，“训练数据来自旧定妆”
//   提示词模板库（B10）：容器——系统只存、编号、引用；正文由项目方 / 写作方写（by=owner | writer:<名>）
// 接口没上线（:8800 没重启）→ LoadError 写清楚，其余照常。
import { loadQuarantine, isQuarantined } from "./hub_api";
import { useEffect, useState, type ReactNode } from "react";
import { Button, Empty, LoadError, Loading, Tag } from "../../ds";
import { p1Api, type LoraTable, type PromptTemplate, type PropRow, type Proposal, type VoiceRow } from "./rev_api";
import { OwnerConfirm } from "./OwnerConfirm";

function useLoad<T>(fn: () => Promise<T>, deps: unknown[] = []): [T | null, string | null, () => void] {
  const [d, setD] = useState<T | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  useEffect(() => {
    let alive = true;
    setErr(null);
    fn().then(
      (x) => alive && setD(x),
      (e) => alive && setErr(String((e as Error).message ?? e)),
    );
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tick, ...deps]);
  return [d, err, () => setTick((n) => n + 1)];
}

function Head({ title, sub, extra }: { title?: ReactNode; sub?: ReactNode; extra?: ReactNode }) {
  return (
    <header className="ac-panel-h">
      {title && <h2>{title}</h2>}
      {sub && <span className="ds-muted ds-small">{sub}</span>}
      <span className="ds-grow" />
      {extra}
    </header>
  );
}

const short = (s?: string | null, n = 10) => (s ? `${s.slice(0, n)}…` : "—");

// ---------------------------------------------------------------- B9 LoRA 总表

export function LoraTablePanel() {
  const [d, err, retry] = useLoad<LoraTable>(() => p1Api.loras());
  // ASSETUX 11-01：隔离区里的 LoRA（如已证伪的 lin_wan_qi）不再列出
  const [q, setQ] = useState<Set<string> | null>(null);
  useEffect(() => void loadQuarantine().then(setQ), []);
  const rows = (d?.loras ?? []).filter((r) => !isQuarantined(q, r.file));
  const hidden = (d?.loras.length ?? 0) - rows.length;
  return (
    <section className="ac-panel">
      <Head sub="只读合并：出图 / 视频 · 所属 · 状态 · sha · 来源；视频身份模型 记训练所用定妆版本" />
      {err && <LoadError what="模型总表" err={err} retry={retry} hint="后台恢复后这里列出全部模型；身份模型 在左栏“身份模型”里照常看。" />}
      {!d && !err && <Loading />}
      {d && (
        <>
          <p className="ds-small ds-muted">
            {hidden > 0 && <>已移进隔离区的 {hidden} 个不再列出。</>}
            视频身份模型 总开关：{d.video_identity_enabled ? <Tag tone="ok">开</Tag> : <Tag>关（全部镜头不挂）</Tag>} · 登记新版本（训练完成后）一律是“候选”，采用 / 作废由登录的项目方点选。
          </p>
          <div className="ac-tbl-wrap">
            <table className="ac-tbl">
              <thead>
                <tr>
                  <th>文件</th>
                  <th>阶段</th>
                  <th>所属</th>
                  <th>状态</th>
                  <th>sha256</th>
                  <th>触发词 · 强度</th>
                  <th>版本 / 训练</th>
                  <th>来源</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.file}>
                    <td>
                      <code>{r.file}</code>
                      {r.slot && (
                        <div className="ds-small ds-muted">
                          指针 <code>{r.slot}</code>
                        </div>
                      )}
                    </td>
                    <td>{r.stage}</td>
                    <td>{r.owner ?? (r.items?.length ? r.items.map((i) => i.name).join("、") : "—")}</td>
                    <td>
                      <Tag tone={r.status === "accepted" ? "ok" : r.status === "training" || r.status === "candidate" ? "warn" : "neutral"}>{statusName(r.status)}</Tag>
                    </td>
                    <td className="num">{r.sha_missing ? <Tag tone="warn">没有 sha</Tag> : <code title={r.sha256 ?? ""}>{short(r.sha256)}</code>}</td>
                    <td>
                      {r.triggers.join(" / ") || "—"}
                      {r.strength != null && <span className="ds-muted"> · {Array.isArray(r.strength) ? r.strength.join("–") : r.strength}</span>}
                    </td>
                    <td>
                      {r.versions.length ? (
                        r.versions.map((v) => (
                          <div key={v.lora_id} className="ds-small">
                            {v.lora_id} {v.step ? `· step ${v.step}` : ""} <Tag size="s">{statusName(v.status)}</Tag>
                            {v.identity_outdated && <Tag size="s" tone="stale">训练数据来自旧定妆</Tag>}
                            <div className="ds-muted">定妆 {short(v.from_identity_rev, 6)} · sha {short(v.sha256, 8)}</div>
                          </div>
                        ))
                      ) : (
                        <span className="ds-muted ds-small">没登记版本</span>
                      )}
                    </td>
                    <td className="ds-small ds-muted">{r.sources.join(" · ")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {d.datasets.length > 0 && (
            <>
              <h4 className="ds-section-t">训练数据集</h4>
              <div className="ac-tbl-wrap">
                <table className="ac-tbl">
                  <thead>
                    <tr>
                      <th>数据集</th>
                      <th>触发词</th>
                      <th>张数</th>
                      <th>和当前定妆母版</th>
                    </tr>
                  </thead>
                  <tbody>
                    {d.datasets.map((x) => (
                      <tr key={x.dir}>
                        <td>
                          <code>{x.manifest}</code>
                        </td>
                        <td>{x.trigger ?? "—"}</td>
                        <td className="num">{x.count}</td>
                        <td>
                          {Object.keys(x.identity_outdated).length
                            ? Object.entries(x.identity_outdated).map(([s, o]) => (
                                <Tag key={s} tone={o ? "stale" : "ok"}>
                                  {s}：{o ? "母版已换（训练数据来自旧定妆）" : "一致"}
                                </Tag>
                              ))
                            : <span className="ds-muted ds-small">数据集里没有母版</span>}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </>
      )}
    </section>
  );
}
function statusName(s: string | null | undefined) {
  return ({ accepted: "已采用", candidate: "候选", training: "训练中", void: "作废", listed: "已登记" } as Record<string, string>)[s ?? ""] ?? s ?? "—";
}

// ---------------------------------------------------------------- B8 音色

export function VoicesPanel() {
  const [d, err, retry] = useLoad(() => p1Api.voices());
  const [edit, setEdit] = useState<VoiceRow | null>(null);
  return (
    <section className="ac-panel">
      <Head title="音色" sub="要换音色：点“提议修改”，你确认后生效" />
      {err && <LoadError what="音色" err={err} retry={retry} hint="后台恢复后这里列出全部音色。" />}
      {!d && !err && <Loading />}
      {d && (
        <div className="ac-tbl-wrap">
          <table className="ac-tbl">
            <thead>
              <tr>
                <th>角色</th>
                <th>说话人 sid</th>
                <th>音色名</th>
                <th>语速</th>
                <th>版本</th>
                <th>待处理提议</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {d.characters.map((v) => (
                <tr key={v.cid}>
                  <td>
                    <b>{v.name}</b> <span className="ds-muted ds-small">{v.cid}</span>
                  </td>
                  <td className="num">{v.sid}</td>
                  <td>
                    <code>{v.voice}</code>
                  </td>
                  <td className="num">{v.speed}</td>
                  <td>{v.seq ? `v${v.seq}` : short(v.rev, 6)}</td>
                  <td>{v.pending.length ? v.pending.map((p) => <ProposalLine key={p.proposal_id} p={p} />) : <span className="ds-muted">—</span>}</td>
                  <td>
                    <Button size="xs" onClick={() => setEdit(v)}>
                      提议修改…
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {edit && (
        <VoiceProposalForm
          v={edit}
          onClose={() => {
            setEdit(null);
            retry();
          }}
        />
      )}
    </section>
  );
}

function ProposalLine({ p }: { p: Proposal }) {
  return (
    <div className="ds-small" title={p.file}>
      {Object.entries((p.to as Record<string, unknown>) ?? {})
        .map(([k, v]) => `${k} → ${String(v)}`)
        .join("，")}{" "}
      <span className="ds-muted">{p.created_at.slice(5, 16).replace("T", " ")}</span>
      {(p as { owner_confirmed?: boolean }).owner_confirmed || p.owner_quote ? <Tag size="s" tone="ok">项目方已确认</Tag> : <Tag size="s" tone="warn">待项目方确认</Tag>}
    </div>
  );
}

function VoiceProposalForm({ v, onClose }: { v: VoiceRow; onClose: () => void }) {
  const [sid, setSid] = useState(String(v.sid));
  const [voice, setVoice] = useState(v.voice);
  const [speed, setSpeed] = useState(String(v.speed));
  const changes: Record<string, unknown> = {};
  if (sid !== String(v.sid)) changes.sid = Number(sid);
  if (voice !== v.voice) changes.voice = voice;
  if (speed !== String(v.speed)) changes.speed = Number(speed);
  const n = Object.keys(changes).length;
  return (
    <OwnerConfirm
      title={`提议修改音色 · ${v.name}`}
      sub="先记成提议，不会马上换；换音色要你本人确认"
      okText={n ? `写提议（${n} 项）` : "写提议"}
      okDisabled={n ? null : "先改一项（sid / 音色名 / 语速）"}
      lines={[
        <div key="f" className="ac-form">
          <label>
            说话人 sid
            <input className="ds-input" value={sid} onChange={(e) => setSid(e.target.value)} inputMode="numeric" />
          </label>
          <label>
            音色名
            <input className="ds-input" value={voice} onChange={(e) => setVoice(e.target.value)} />
          </label>
          <label>
            语速
            <input className="ds-input" value={speed} onChange={(e) => setSpeed(e.target.value)} inputMode="decimal" />
          </label>
        </div>,
        "你登录着项目方账户：提交即标“项目方已确认”。",
      ]}
      gated
      quoteOptional
      gateLabel="换音色"
      onClose={onClose}
      onConfirm={async (quote) => {
        if (!n) throw new Error("没有改动");
        const p = await p1Api.voiceProposal(v.cid, changes, quote ? "owner" : "canvas", quote || undefined);
        return `已写提议：${p.file}`;
      }}
    />
  );
}

// ---------------------------------------------------------------- B7 道具·产品

export function PropsPanel() {
  const [d, err, retry] = useLoad(() => p1Api.props());
  const [form, setForm] = useState<{ id?: string; name: string; kind: string; lora_file: string; trigger: string; note: string } | null>(null);
  const own = (d?.props ?? []).filter((p) => p.editable);
  const [undo, setUndo] = useState<{ id: string; name: string; err?: string } | null>(null);
  const mapped = (d?.props ?? []).filter((p) => !p.editable);
  return (
    <section className="ac-panel">
      <Head
        title="自建道具·产品"
        sub={d ? `自建 ${own.length} · 衣橱映射 ${mapped.length}（只读，迁不迁由项目方决定）` : undefined}
        extra={
          <Button size="sm" disabled={!!err} why="道具接口还没上线（等 API 重启）" onClick={() => setForm({ name: "", kind: "product", lora_file: "", trigger: "", note: "" })}>
            新建道具…
          </Button>
        }
      />
      {err && <LoadError what="道具表" err={err} retry={retry} hint="下面的卡片（衣橱里带模型的饰品）照常显示；自建道具等后台恢复后出现。" />}
      {undo && (
        <p className={`ds-note ${undo.err ? "warn" : "ok"}`} role="status">
          {undo.err ? `“${undo.name}”删不了：${undo.err}。数据没改动` : `“${undo.name}”已移到回收站。`}
          {!undo.err && (
            <Button size="xs" variant="secondary" onClick={() => void fetch(`/api/trash/${encodeURIComponent(undo.id)}/restore`, { method: "POST" }).then(() => (setUndo(null), retry()))}>
              撤销
            </Button>
          )}
        </p>
      )}
      {d && !own.length && <p className="ds-small ds-muted">还没有自建道具。下面的卡片是从衣橱映射过来的（带产品模型 的饰品）。</p>}
      {own.length > 0 && (
        <div className="ac-tbl-wrap">
          <table className="ac-tbl">
            <thead>
              <tr>
                <th>名称</th>
                <th>类型</th>
                <th>模型 · 触发词</th>
                <th>说明</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {own.map((p: PropRow) => (
                <tr key={p.id}>
                  <td>
                    <b>{p.name}</b> <span className="ds-muted ds-small">{p.id}</span>
                  </td>
                  <td>{p.kind}</td>
                  <td>
                    {p.lora_file ? <code>{p.lora_file}</code> : "—"} {p.trigger ?? ""}
                  </td>
                  <td className="ds-small">{p.note ?? ""}</td>
                  <td>
                    <Button size="xs" variant="ghost" onClick={() => setForm({ id: p.id, name: p.name, kind: p.kind, lora_file: p.lora_file ?? "", trigger: p.trigger ?? "", note: p.note ?? "" })}>
                      改…
                    </Button>
                    <Button
                      size="xs"
                      variant="ghost"
                      title="删除这条自建道具（进回收站，可撤销；图片和 模型文件保留）"
                      onClick={() =>
                        void fetch(`/api/trash/object?type=prop&id=${encodeURIComponent(p.id)}&reason=${encodeURIComponent("资产中心删除道具")}`, { method: "DELETE" })
                          .then(async (r) => {
                            const j = (await r.json().catch(() => ({}))) as { entry_id?: string; detail?: unknown };
                            if (!r.ok || !j.entry_id) throw new Error(typeof j.detail === "string" ? j.detail : `HTTP ${r.status}`);
                            setUndo({ id: j.entry_id, name: p.name });
                            retry();
                          })
                          .catch((e) => setUndo({ id: "", name: p.name, err: (e as Error).message }))
                      }
                    >
                      删除
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {form && (
        <OwnerConfirm
          title={form.id ? `改道具 · ${form.name}` : "新建道具·产品"}
          sub="只改道具的名字和说明，不动衣橱、不出图"
          okText="保存"
          lines={[
            <div key="f" className="ac-form">
              <label>
                名称
                <input className="ds-input" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
              </label>
              <label>
                类型
                <input className="ds-input" value={form.kind} onChange={(e) => setForm({ ...form, kind: e.target.value })} placeholder="product / jewellery / phone…" />
              </label>
              <label>
                模型文件
                <input className="ds-input" value={form.lora_file} onChange={(e) => setForm({ ...form, lora_file: e.target.value })} placeholder="xxx.safetensors（可空）" />
              </label>
              <label>
                触发词
                <input className="ds-input" value={form.trigger} onChange={(e) => setForm({ ...form, trigger: e.target.value })} />
              </label>
              <label className="full">
                说明
                <input className="ds-input" value={form.note} onChange={(e) => setForm({ ...form, note: e.target.value })} />
              </label>
            </div>,
          ]}
          onClose={() => {
            setForm(null);
            retry();
          }}
          onConfirm={async () => {
            const b = { name: form.name, kind: form.kind, lora_file: form.lora_file || undefined, trigger: form.trigger || undefined, note: form.note || undefined };
            const r = form.id ? await p1Api.updateProp(form.id, b) : await p1Api.createProp(b);
            return `已保存 ${r.name}`;
          }}
        />
      )}
    </section>
  );
}

// ---------------------------------------------------------------- B10 提示词模板库

export function TemplatesPanel() {
  const [d, err, retry] = useLoad(() => p1Api.templates());
  const [form, setForm] = useState<{ t?: PromptTemplate; name: string; kind: string; text: string; by: string } | null>(null);
  return (
    <section className="ac-panel">
      <Head
        sub="容器：系统只存、编号、记谁引用了第几版；正文由项目方或写作模型写，系统不生成、不改写"
        extra={
          <Button size="sm" disabled={!!err} why="模板接口还没上线（等 API 重启）" onClick={() => setForm({ name: "", kind: "portrait", text: "", by: "owner" })}>
            新建模板…
          </Button>
        }
      />
      {err && <LoadError what="提示词模板" err={err} retry={retry} hint="后台恢复后这里列出提示词模板。每镜的提示词在画布精修右栏“提示词”里看和改。" />}
      {!d && !err && <Loading />}
      {d && !d.templates.length && <Empty icon="¶" title="还没有模板" sub="立绘、场景底图、视频提示词格式模板放在这里；由项目方或写作模型新建，正文原样保存，每次修改存为新版本。" />}
      {d && d.templates.length > 0 && (
        <div className="ac-tpl-list">
          {d.templates.map((t) => (
            <article key={t.id} className="ac-tpl">
              <div className="ds-row">
                <b>{t.name}</b>
                <Tag>{t.kind_label}</Tag>
                <Tag tone="accent">v{t.current_v}</Tag>
                <span className="ds-muted ds-small">
                  {t.id} · 共 {t.versions.length} 版 · 最近 {t.current?.by} {t.current?.at.slice(5, 16).replace("T", " ")}
                </span>
                <span className="ds-grow" />
                <Button size="xs" variant="ghost" onClick={() => setForm({ t, name: t.name, kind: t.kind, text: t.current?.text ?? "", by: "owner" })}>
                  存新版本…
                </Button>
              </div>
              <pre>{t.current?.text}</pre>
            </article>
          ))}
        </div>
      )}
      {form && (
        <OwnerConfirm
          title={form.t ? `存新版本 · ${form.t.name}（现在 v${form.t.current_v}）` : "新建提示词模板"}
          sub="正文原样保存；旧版本保留"
          okText="保存"
          lines={[
            <div key="f" className="ac-form">
              {!form.t && (
                <>
                  <label>
                    名称
                    <input className="ds-input" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
                  </label>
                  <label>
                    类型
                    <select className="ds-input" value={form.kind} onChange={(e) => setForm({ ...form, kind: e.target.value })}>
                      {Object.entries(d?.kinds ?? {}).map(([k, v]) => (
                        <option key={k} value={k}>
                          {v}
                        </option>
                      ))}
                    </select>
                  </label>
                </>
              )}
              <label>
                谁写的
                <select className="ds-input" value={form.by} onChange={(e) => setForm({ ...form, by: e.target.value })}>
                  <option value="owner">项目方本人</option>
                  <option value="writer">写作模型</option>
                </select>
              </label>
              <label className="full">
                正文
                <textarea className="ds-input" value={form.text} onChange={(e) => setForm({ ...form, text: e.target.value })} />
              </label>
            </div>,
          ]}
          onClose={() => {
            setForm(null);
            retry();
          }}
          onConfirm={async () => {
            const r = form.t ? await p1Api.updateTemplate(form.t.id, { text: form.text, by: form.by }) : await p1Api.createTemplate({ name: form.name, kind: form.kind, text: form.text, by: form.by });
            return `已保存 ${r.id} v${r.current_v}`;
          }}
        />
      )}
    </section>
  );
}
