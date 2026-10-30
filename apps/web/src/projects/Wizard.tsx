// 「新建剧」向导（T42，docs/SOP_production.md「自动化启动」第 1 步）
// 剧名 → 剧本三件套（实时导入校验）→ 风格 SOP（visual_bible.toml + 两镜示例，G1）→ 人物 → LoRA 计划 → 成人内容开关 → 创建
import { useEffect, useRef, useState, type ReactNode } from "react";
import { CAT_LABEL, EmptyState, LETTERS, LOOK_COLORS, Section } from "../components/assets/parts";
import {
  go,
  papi,
  type Character,
  type LookForm,
  type ProjectDetail,
  type Rule,
  type ScriptReport,
  type StyleState,
} from "./papi";

const STEPS: [string, string][] = [
  ["name", "剧名"],
  ["script", "剧本"],
  ["style", "风格 SOP"],
  ["characters", "人物"],
  ["lora", "LoRA 计划"],
  ["adult", "成人内容"],
  ["create", "创建"],
];
const KINDS: [string, string, string][] = [
  ["script", "剧本和镜头", "必填：## epNN《》、**镜N｜img**、**motion**、**sound**、**对白**…"],
  ["image_doc", "image 提示词", "数据 B 装饰状态表、数据 D 基准图、数据 E LoRA 注册表"],
  ["corrector", "纠正器", "镜头类型调参条目（特写 / 暗场 / 安全镜…）"],
];

function Steps({ slug, step }: { slug: string | null; step: string }) {
  const idx = STEPS.findIndex(([k]) => k === step);
  return (
    <ol className="wz-steps">
      {STEPS.map(([k, label], i) => (
        <li key={k} className={i === idx ? "on" : i < idx ? "done" : ""}>
          <button disabled={!slug || k === "name"} onClick={() => slug && go(`#/projects/${slug}/wizard/${k}`)}>
            <span className="wz-n">{i < idx ? "✓" : i + 1}</span>
            {label}
          </button>
        </li>
      ))}
    </ol>
  );
}

function Nav({ slug, step, canNext = true, nextLabel, onNext }: { slug: string; step: string; canNext?: boolean; nextLabel?: string; onNext?: () => Promise<void> | void }) {
  const i = STEPS.findIndex(([k]) => k === step);
  const prev = STEPS[i - 1]?.[0];
  const next = STEPS[i + 1]?.[0];
  return (
    <div className="wz-nav">
      {prev && prev !== "name" && (
        <button className="btn" onClick={() => go(`#/projects/${slug}/wizard/${prev}`)}>
          ← 上一步
        </button>
      )}
      <span className="grow" />
      {next && (
        <button
          className="btn primary big"
          disabled={!canNext}
          onClick={async () => {
            await onNext?.();
            go(`#/projects/${slug}/wizard/${next}`);
          }}
        >
          {nextLabel ?? "下一步 →"}
        </button>
      )}
    </div>
  );
}

function useErr(): [string, (e: unknown) => void, () => void] {
  const [err, setErr] = useState("");
  return [err, (e: unknown) => setErr(e instanceof Error ? e.message : String(e)), () => setErr("")];
}

// ================================================================== ① 剧名

function NameStep() {
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [err, fail] = useErr();
  return (
    <div className="wz-body narrow">
      <Section n="①" title="剧名" hint="生成 projects/<代号>/ 目录骨架（script / config / assets / data / previews / docs）">
        <label className="wz-field">
          <span>剧名</span>
          <input value={name} onChange={(e) => setName(e.target.value)} placeholder="例：雾港来信" autoFocus />
        </label>
        <label className="wz-field">
          <span>项目代号（可空）</span>
          <input value={slug} onChange={(e) => setSlug(e.target.value)} placeholder="小写字母/数字，例：wugang；空 = 自动" />
        </label>
        {err && <div className="banner">{err}</div>}
      </Section>
      <div className="wz-nav">
        <span className="grow" />
        <button
          className="btn primary big"
          disabled={!name.trim()}
          onClick={() =>
            papi.create(name.trim(), slug.trim() || undefined).then((p) => go(`#/projects/${p.slug}/wizard/script`), fail)
          }
        >
          创建项目目录 →
        </button>
      </div>
    </div>
  );
}

// ================================================================== ② 剧本三件套

function Stat({ k, v, tone }: { k: string; v: ReactNode; tone?: "ok" | "warn" | "bad" }) {
  return (
    <div className={`wz-stat${tone ? ` ${tone}` : ""}`}>
      <span className="muted small">{k}</span>
      <b>{v}</b>
    </div>
  );
}

function ScriptStep({ slug }: { slug: string }) {
  const [rep, setRep] = useState<ScriptReport | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [err, fail, clear] = useErr();
  useEffect(() => {
    papi.report(slug).then(setRep, fail);
  }, [slug]); // eslint-disable-line react-hooks/exhaustive-deps
  const send = (kind: string, f: File | undefined) => {
    if (!f) return;
    setBusy(kind);
    clear();
    papi
      .uploadScript(slug, kind, f)
      .then(setRep, fail)
      .finally(() => setBusy(null));
  };
  const [lo, hi] = rep?.shots_rule ?? [6, 8];
  return (
    <div className="wz-body">
      <Section n="②" title="上传剧本三件套" hint="选好文件立即导入并校验；原件只读保存在 script/，同名改动会留备份">
        <div className="wz-files">
          {KINDS.map(([kind, label, hint]) => {
            const name = rep?.files?.[kind];
            return (
              <label key={kind} className={`wz-drop${name ? " has" : ""}`}
                onDragOver={(e) => e.preventDefault()}
                onDrop={(e) => {
                  e.preventDefault();
                  send(kind, e.dataTransfer.files[0]);
                }}>
                <input type="file" accept=".md,.txt,.markdown" hidden onChange={(e) => send(kind, e.target.files?.[0])} />
                <b>
                  {label}
                  {kind === "script" && <span className="req">必填</span>}
                </b>
                <span className="muted small">{hint}</span>
                <span className={name ? "ok-text" : "muted"}>{busy === kind ? "导入中…" : name ? `✓ ${name}` : "点击或拖入 .md"}</span>
              </label>
            );
          })}
        </div>
        {err && <div className="banner">{err}</div>}
      </Section>

      {rep && (rep.fatal.length > 0 || rep.episodes !== undefined) && (
        <Section n="" title="导入校验" hint="集数 × 镜数、时长、对白解析、触发词、装饰状态表" extra={
          rep.ok ? <span className="chip chip-ok">可以继续</span> : <span className="chip chip-bad">有致命问题</span>}>
          {rep.fatal.map((f) => (
            <div key={f} className="wz-msg bad">⛔ {f}</div>
          ))}
          {rep.episodes !== undefined && (
            <>
              <div className="wz-stats">
                <Stat k="集数" v={rep.episodes} />
                <Stat k="镜头" v={rep.shots} />
                <Stat k={`每集镜数（应 ${lo}–${hi}）`} v={`${Math.min(...(rep.per_episode ?? []).map((e) => e.shots))}–${Math.max(...(rep.per_episode ?? []).map((e) => e.shots))}`}
                  tone={(rep.per_episode ?? []).every((e) => e.shots >= lo && e.shots <= hi) ? "ok" : "warn"} />
                <Stat k="时长（剧本写明 / 默认 10 秒）" v={`${rep.durations?.script} / ${rep.durations?.default}`} tone={rep.durations?.default ? "warn" : "ok"} />
                <Stat k="单镜时长" v={`${rep.durations?.min}–${rep.durations?.max} 秒`} />
                <Stat k="对白句 / 有对白的镜" v={`${rep.dialogue?.lines} / ${rep.dialogue?.shots}`} />
                <Stat k="触发词（声明 / 用到）" v={`${rep.triggers?.declared.length} / ${Object.keys(rep.triggers?.used ?? {}).length}`}
                  tone={rep.triggers?.unknown.length ? "warn" : "ok"} />
                <Stat k="装饰状态区间" v={rep.decor?.ranges ?? 0} tone={rep.decor?.missing.length ? "warn" : rep.decor?.ranges ? "ok" : "warn"} />
                <Stat k="成人镜头（关键词判定）" v={rep.adult_shots} />
                <Stat k="纠正器条目" v={rep.corrector?.rule_count ?? "—"} />
              </div>
              <div className="wz-cols">
                <div className="wz-col">
                  <div className="sub-title">角色锁（人物步骤按这里建卡）</div>
                  {(rep.character_locks ?? []).map((c) => (
                    <div key={c.name} className="wz-lock">
                      <b>【{c.name}】</b> <span className="muted">{c.description}</span>
                    </div>
                  ))}
                  <div className="sub-title">触发词</div>
                  <div className="badges">
                    {rep.triggers?.declared.map((t) => (
                      <span key={t} className={`chip ${rep.triggers?.without_file.includes(t) ? "chip-warn" : "chip-ok"}`}
                        title={rep.triggers?.without_file.includes(t) ? "数据 E 里没有 LoRA 文件：渲染时自动去掉" : "已登记 LoRA 文件"}>
                        {t} ×{rep.triggers?.used[t] ?? 0}
                      </span>
                    ))}
                    {rep.triggers?.unknown.map((t) => (
                      <span key={t} className="chip chip-bad" title="剧本用了，但触发词表里没有">
                        {t}?
                      </span>
                    ))}
                  </div>
                  {rep.decor && rep.decor.states.length > 0 && (
                    <>
                      <div className="sub-title">装饰状态</div>
                      <div className="badges">
                        {rep.decor.states.map((s) => (
                          <span key={s} className="chip">{s}</span>
                        ))}
                        {rep.decor.missing.length > 0 && <span className="chip chip-warn">缺：ep{rep.decor.missing.join(", ep")}</span>}
                      </div>
                    </>
                  )}
                </div>
                <div className="wz-col">
                  <div className="sub-title">逐集</div>
                  <table className="wz-table">
                    <thead>
                      <tr>
                        <th>集</th>
                        <th>标题</th>
                        <th>镜</th>
                        <th>成人</th>
                        <th>秒</th>
                        <th>对白</th>
                        <th>装饰</th>
                        <th>问题</th>
                      </tr>
                    </thead>
                    <tbody>
                      {rep.per_episode?.map((e) => (
                        <tr key={e.number} className={e.issues.length ? "warn" : ""}>
                          <td className="tnum">ep{String(e.number).padStart(2, "0")}</td>
                          <td>{e.title}{e.high_intensity && " 🔴"}</td>
                          <td className="tnum">{e.shots}</td>
                          <td className="tnum">{e.adult || ""}</td>
                          <td className="tnum">{e.seconds}</td>
                          <td className="tnum">{e.dialogue_lines}</td>
                          <td>{e.decor ?? "—"}</td>
                          <td className="small">{e.issues.join("；")}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </>
          )}
          {rep.warnings.length > 0 && (
            <details className="wz-warnings" open={rep.warnings.length <= 6}>
              <summary>警告 {rep.warnings.length} 条（不阻塞，进入异常队列）</summary>
              {rep.warnings.map((w, i) => (
                <div key={i} className="wz-msg warn">⚠ {w}</div>
              ))}
            </details>
          )}
        </Section>
      )}
      <Nav slug={slug} step="script" canNext={!!rep?.ok} />
    </div>
  );
}

// ================================================================== ③ 风格 SOP

function Text({ label, value, onChange, rows = 1, hint }: { label: string; value: string; onChange: (v: string) => void; rows?: number; hint?: string }) {
  return (
    <label className="wz-field">
      <span>
        {label}
        {hint && <em className="muted small"> {hint}</em>}
      </span>
      {rows > 1 ? <textarea rows={rows} value={value} onChange={(e) => onChange(e.target.value)} /> : <input value={value} onChange={(e) => onChange(e.target.value)} />}
    </label>
  );
}

function Slider({ label, value, onChange, hint }: { label: string; value: number; onChange: (v: number) => void; hint?: string }) {
  return (
    <label className="wz-field wz-slider">
      <span>
        {label} <b className="tnum">{value.toFixed(2)}</b>
        {hint && <em className="muted small"> {hint}</em>}
      </span>
      <input type="range" min={0} max={1} step={0.05} value={value} onChange={(e) => onChange(Number(e.target.value))} />
    </label>
  );
}

function RulesEditor({ rules, onChange, matchLabel }: { rules: Rule[]; onChange: (r: Rule[]) => void; matchLabel: string }) {
  const set = (i: number, patch: Partial<Rule>) => onChange(rules.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  return (
    <div className="wz-rules">
      {rules.map((r, i) => (
        <div key={i} className="wz-rule">
          <input className="wz-rule-id mono" value={r.id} onChange={(e) => set(i, { id: e.target.value })} placeholder="id" />
          <input value={r.match.join("、")} onChange={(e) => set(i, { match: e.target.value.split(/[、,，]\s*/).filter(Boolean) })}
            placeholder={matchLabel} title={matchLabel} />
          <input className="wz-rule-term" value={r.term} onChange={(e) => set(i, { term: e.target.value })} placeholder="追加的措辞" />
          <button className="btn-mini" onClick={() => onChange(rules.filter((_, j) => j !== i))} title="删除">
            ✕
          </button>
        </div>
      ))}
      <button className="btn-mini" onClick={() => onChange([...rules, { id: `rule${rules.length + 1}`, match: [], term: "" }])}>
        ＋ 加一条
      </button>
    </div>
  );
}

function StyleStep({ slug }: { slug: string }) {
  const [st, setSt] = useState<StyleState | null>(null);
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, fail, clear] = useErr();
  const [ver, setVer] = useState(0);
  useEffect(() => {
    papi.style(slug).then(setSt, fail);
  }, [slug]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!st) return <div className="empty">{err || "加载中…"}</div>;
  const f = st.form;
  const up = (patch: Partial<typeof f>) => {
    setSt({ ...st, form: { ...f, ...patch } });
    setDirty(true);
  };
  const save = async () => {
    setBusy(true);
    clear();
    try {
      const r = await papi.saveStyle(slug, st.form);
      setSt({ ...st, toml: r.toml, preview: r.preview, saved: true, confirmed: null });
      setDirty(false);
    } catch (e) {
      fail(e);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="wz-body">
      <div className="wz-split">
        <div className="wz-form">
          <Section n="③" title="画面：镜头 / 质感 / 色调" hint="生成 config/visual_bible.toml（模板 templates/visual_bible.template.toml）">
            <Text label="镜头感" value={f.lens} onChange={(v) => up({ lens: v })} hint="剧本后缀没写 Leica/徕卡 时追加" />
            <Text label="调色 / 色调" value={f.palette} onChange={(v) => up({ palette: v })} />
            <label className="wz-check">
              <input type="checkbox" checked={f.use_script_suffix} onChange={(e) => up({ use_script_suffix: e.target.checked })} />
              剧本里有“每条img统一后缀”时优先用剧本的
            </label>
            <Text label="统一风格后缀（剧本没有时）" value={f.fallback_suffix} onChange={(v) => up({ fallback_suffix: v })} rows={3} />
            <Text label="风格负面词" value={f.style_negative} onChange={(v) => up({ style_negative: v })} />
            <div className="wz-colorref">
              <div className="wz-colorref-img">
                {f.color_reference ? <img src={`${papi.file(slug, f.color_reference)}?v=${ver}`} alt="色调参考" /> : <span className="muted small">未上传</span>}
              </div>
              <div className="grow">
                <div className="sub-title">色调参考图（首尾帧出图后向它做色调迁移）</div>
                <label className="btn">
                  上传参考图
                  <input type="file" accept="image/*" hidden onChange={(e) => {
                    const file = e.target.files?.[0];
                    if (!file) return;
                    papi.uploadColorRef(slug, file).then((r) => {
                      setSt({ ...st, form: { ...st.form, color_reference: r.color_reference }, toml: r.toml, preview: r.preview, confirmed: null, saved: true });
                      setVer((v) => v + 1);
                    }, fail);
                  }} />
                </label>
                <Slider label="色调匹配力度" value={f.color_match_strength} onChange={(v) => up({ color_match_strength: v })} />
              </div>
            </div>
          </Section>
          <Section n="" title="写实（只作质感）" hint="research v8：写实 LoRA 只加胶片质感，不改项目方认可的人物长相">
            <Slider label="写实质感强度（krea2 胶片质感 LoRA）" value={f.realism_texture_strength} onChange={(v) => up({ realism_texture_strength: v })} hint="推荐 0.3–0.5" />
          </Section>
          <Section n="" title="材质规则" hint="镜头原文出现关键词就追加（原文已含则跳过），并作为评分必查项">
            <RulesEditor rules={f.materials} onChange={(materials) => up({ materials })} matchLabel="关键词（、分隔）" />
          </Section>
          <Section n="" title="镜头类型规则（纠正器）" hint="特写 / 暗场等；非成人镜头另加安全镜条目">
            <RulesEditor rules={f.shot_rules} onChange={(shot_rules) => up({ shot_rules })} matchLabel="镜头关键词（、分隔）" />
            <div className="wz-row2">
              <Text label="非成人镜头追加" value={f.safe_term} onChange={(v) => up({ safe_term: v })} />
              <Text label="非成人镜头负面" value={f.safe_negative} onChange={(v) => up({ safe_negative: v })} />
            </div>
          </Section>
          <Section n="" title="声音规则" hint="docs/intimate_audio.md：主角固定声线、只让一人发声；配乐基调交 gpu3 生成 BGM">
            <Text label="默认环境声（soundscape）" value={f.soundscape_default} onChange={(v) => up({ soundscape_default: v })} rows={2} />
            <Text label="主角声线" value={f.voice_rule} onChange={(v) => up({ voice_rule: v })} />
            <label className="wz-check">
              <input type="checkbox" checked={f.single_voice} onChange={(e) => up({ single_voice: e.target.checked })} />
              亲密 / 多人镜头只让一人发声
            </label>
            <Text label="全剧配乐风格（BGM）" value={f.bgm_style} onChange={(v) => up({ bgm_style: v })} />
          </Section>
        </div>
        <aside className="wz-aside">
          <div className="wz-aside-sticky">
            <div className="wz-aside-head">
              <b>示例提示词（2 个真实镜头）</b>
              <span className="grow" />
              <button className="btn" disabled={busy} onClick={save}>
                {busy ? "保存中…" : dirty ? "保存并刷新预览" : "刷新预览"}
              </button>
            </div>
            {dirty && <div className="wz-msg warn">表单有改动，保存后预览与 toml 才更新</div>}
            {err && <div className="banner">{err}</div>}
            {st.preview.length === 0 && <EmptyState text="先导入剧本才有示例镜头" />}
            {st.preview.map((p) => (
              <div key={p.shot} className="wz-preview">
                <div className="wz-preview-head">
                  <span className="chip chip-accent">{p.shot}</span>
                  <span className="muted small">{p.episode_title}</span>
                </div>
                {p.parts.map((x) => (
                  <div key={x.label} className="wz-part">
                    <span className="wz-part-k">{x.label}</span>
                    <span className="wz-part-v">{x.text}</span>
                  </div>
                ))}
                <div className="wz-part neg">
                  <span className="wz-part-k">负面</span>
                  <span className="wz-part-v">{p.negative}</span>
                </div>
              </div>
            ))}
            <div className="muted small">按视觉圣经 [assembly] 顺序预览；正式出图以编译器为准。</div>
            {st.toml && (
              <details className="wz-toml">
                <summary>config/visual_bible.toml</summary>
                <pre>{st.toml}</pre>
              </details>
            )}
            <div className="wz-g1">
              {st.confirmed ? (
                <span className="chip chip-ok">G1 已确认 · {st.confirmed.by} · {st.confirmed.at}</span>
              ) : (
                <button className="btn primary" disabled={!st.saved || dirty} onClick={() =>
                  papi.confirmStyle(slug, "项目方").then((c) => setSt({ ...st, confirmed: c }), fail)}>
                  G1 确认风格定稿
                </button>
              )}
            </div>
          </div>
        </aside>
      </div>
      <Nav slug={slug} step="style" canNext={!!st.confirmed && !dirty} />
    </div>
  );
}

// ================================================================== ④ 人物

const LOOK_FIELDS: [keyof LookForm, string][] = [
  ["outfit", CAT_LABEL.outfit],
  ["shoes", CAT_LABEL.shoes],
  ["makeup", CAT_LABEL.makeup],
  ["hair", CAT_LABEL.hair],
  ["nails", CAT_LABEL.nails],
  ["accessory", CAT_LABEL.accessory],
];
const REALISM: [Character["realism"], string][] = [
  ["low", "轻（0.3）"],
  ["mid", "中（0.5）"],
  ["high", "强（0.7）"],
];

function CharacterCard({ slug, c, onChange, color }: { slug: string; c: Character; onChange: (c: Character) => void; color: string }) {
  const [draft, setDraft] = useState<Character>(c);
  const [dirty, setDirty] = useState(false);
  const [err, fail, clear] = useErr();
  const fileRef = useRef<HTMLInputElement>(null);
  useEffect(() => {
    setDraft(c);
  }, [c]);
  const up = (patch: Partial<Character>) => {
    setDraft({ ...draft, ...patch });
    setDirty(true);
  };
  const save = () => {
    clear();
    papi
      .saveCharacter(slug, c.id, {
        realism: draft.realism, makeup: draft.makeup ?? "", nails: draft.nails ?? "", hair: draft.hair ?? "",
        shoes: draft.shoes ?? "", wardrobe: draft.wardrobe ?? "", looks: draft.looks, schedule: draft.schedule,
      })
      .then((r) => {
        onChange(r);
        setDirty(false);
      }, fail);
  };
  const setLook = (i: number, patch: Partial<LookForm>) => up({ looks: draft.looks.map((l, j) => (j === i ? { ...l, ...patch } : l)) });
  return (
    <section className={`wz-char${c.confirmed ? " ok" : ""}`} style={{ borderTopColor: color }}>
      <div className="wz-char-head">
        <b className="wz-char-name">{c.name}</b>
        <span className="muted small mono">{c.id}</span>
        <span className="grow" />
        {c.confirmed ? <span className="chip chip-ok">已确认</span> : <span className="chip chip-warn">待确认</span>}
      </div>
      <div className="muted small wz-char-lock">角色锁：{c.description}</div>

      <div className="sub-title">参考图（项目方提供；只取脸与发型，造型照的衣服/项链/背景不会进镜头）</div>
      <div className="wz-refs">
        {c.references.map((r) => (
          <div key={r} className="wz-ref">
            <img src={papi.file(slug, r)} alt="" />
            <button className="btn-mini" title="移除（会撤销确认）" onClick={() => papi.removeReference(slug, c.id, r).then(onChange, fail)}>
              ✕
            </button>
          </div>
        ))}
        <button className="wz-ref add" onClick={() => fileRef.current?.click()}>
          ＋ 上传
        </button>
        <input ref={fileRef} type="file" accept="image/*" multiple hidden onChange={async (e) => {
          const files = Array.from(e.target.files ?? []);
          let last: Character | null = null;
          for (const f of files) {
            try {
              last = await papi.addReference(slug, c.id, f);
            } catch (er) {
              fail(er);
            }
          }
          if (last) onChange(last);
          e.target.value = "";
        }} />
      </div>
      <label className={`wz-confirm${c.confirmed ? " on" : ""}${c.references.length ? "" : " off"}`}>
        <input type="checkbox" checked={c.confirmed} disabled={!c.references.length}
          onChange={(e) => papi.confirmCharacter(slug, c.id, e.target.checked, "项目方").then(onChange, fail)} />
        <span>
          <b>此角色为 AI 生成的虚构成年人</b>
          <span className="muted small">
            {c.confirmed ? ` 已记录 ${c.approved_by} · ${c.approved_at}（config/face_reference.json）` : c.references.length ? " 必须由项目方本人勾选" : " 先上传参考图"}
          </span>
        </span>
      </label>

      <div className="wz-row2">
        <div className="wz-field">
          <span>写实强度（只作质感）</span>
          <div className="seg">
            {REALISM.map(([k, label]) => (
              <button key={k} className={draft.realism === k ? "on" : ""} onClick={() => up({ realism: k })}>
                {label}
              </button>
            ))}
          </div>
        </div>
        <Text label="发型" value={draft.hair ?? ""} onChange={(v) => up({ hair: v })} />
      </div>
      <div className="wz-row2">
        <Text label="妆容" value={draft.makeup ?? ""} onChange={(v) => up({ makeup: v })} />
        <Text label="美甲" value={draft.nails ?? ""} onChange={(v) => up({ nails: v })} />
      </div>
      <div className="wz-row2">
        <Text label="日常穿搭规则" value={draft.wardrobe ?? ""} onChange={(v) => up({ wardrobe: v })} />
        <Text label="鞋（默认）" value={draft.shoes ?? ""} onChange={(v) => up({ shoes: v })} />
      </div>

      <div className="sub-title">造型 A / B / C（空格沿用上面的默认值；写进 data/looks，资产页可继续细化）</div>
      <div className="wz-looks">
        {draft.looks.map((lk, i) => (
          <div key={i} className="wz-look" style={{ borderLeftColor: LOOK_COLORS[i % LOOK_COLORS.length] }}>
            <div className="wz-look-head">
              <span className="wz-letter" style={{ background: LOOK_COLORS[i % LOOK_COLORS.length] }}>{lk.label}</span>
              <input value={lk.name ?? ""} onChange={(e) => setLook(i, { name: e.target.value })} placeholder="造型名（通勤 / 夜场…）" />
              {i > 0 && (
                <button className="btn-mini" onClick={() => up({ looks: draft.looks.filter((_, j) => j !== i), schedule: draft.schedule.filter((s) => s.look !== lk.label) })}>
                  ✕
                </button>
              )}
            </div>
            {LOOK_FIELDS.map(([k, label]) => (
              <label key={k} className="wz-look-f">
                <span>{label}</span>
                <input value={(lk[k] as string) ?? ""} onChange={(e) => setLook(i, { [k]: e.target.value })} />
              </label>
            ))}
          </div>
        ))}
        {draft.looks.length < 6 && (
          <button className="wz-look add" onClick={() => {
            const used = new Set(draft.looks.map((l) => l.label));
            up({ looks: [...draft.looks, { label: LETTERS.find((l) => !used.has(l)) ?? "Z" }] });
          }}>
            ＋ 造型 {LETTERS.find((l) => !draft.looks.some((x) => x.label === l))}
          </button>
        )}
      </div>
      <div className="sub-title">造型排期（第一个造型为默认；这里只写例外集段）</div>
      <div className="wz-sched">
        {draft.schedule.map((s, i) => (
          <div key={i} className="wz-sched-row">
            <select value={s.look} onChange={(e) => up({ schedule: draft.schedule.map((x, j) => (j === i ? { ...x, look: e.target.value } : x)) })}>
              {draft.looks.map((l) => (
                <option key={l.label} value={l.label}>造型 {l.label}{l.name ? `·${l.name}` : ""}</option>
              ))}
            </select>
            <input value={s.episodes} placeholder="集段：1-10, 12" onChange={(e) => up({ schedule: draft.schedule.map((x, j) => (j === i ? { ...x, episodes: e.target.value } : x)) })} />
            <button className="btn-mini" onClick={() => up({ schedule: draft.schedule.filter((_, j) => j !== i) })}>
              ✕
            </button>
          </div>
        ))}
        <button className="btn-mini" disabled={draft.looks.length < 2}
          onClick={() => up({ schedule: [...draft.schedule, { look: draft.looks[1]?.label ?? "A", episodes: "" }] })}>
          ＋ 排期
        </button>
      </div>
      {err && <div className="banner">{err}</div>}
      <div className="wz-char-foot">
        <span className="grow" />
        <button className="btn primary" disabled={!dirty} onClick={save}>
          {dirty ? "保存人物设置" : "已保存"}
        </button>
      </div>
    </section>
  );
}

function CharactersStep({ slug }: { slug: string }) {
  const [chars, setChars] = useState<Character[] | null>(null);
  const [err, fail] = useErr();
  useEffect(() => {
    papi.characters(slug).then((r) => setChars(r.characters), fail);
  }, [slug]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!chars) return <div className="empty">{err || "加载中…"}</div>;
  const done = chars.filter((c) => c.confirmed).length;
  return (
    <div className="wz-body">
      <div className="wz-intro">
        <b>④ 人物</b>
        <span className="muted">按剧本角色锁每人一张卡。每个角色都要上传参考图，并由项目方确认为 AI 生成的虚构成年人；母版在开始生产后的 G2 选定。</span>
        <span className="grow" />
        <span className={`chip ${done === chars.length ? "chip-ok" : "chip-warn"}`}>已确认 {done}/{chars.length}</span>
      </div>
      {chars.length === 0 && <EmptyState text="剧本里没有角色锁" />}
      <div className="wz-chars">
        {chars.map((c, i) => (
          <CharacterCard key={c.id} slug={slug} c={c} color={LOOK_COLORS[i % LOOK_COLORS.length]}
            onChange={(n) => setChars(chars.map((x) => (x.id === n.id ? n : x)))} />
        ))}
      </div>
      <Nav slug={slug} step="characters" canNext={chars.length > 0 && done === chars.length} />
    </div>
  );
}

// ================================================================== ⑤ LoRA / ⑥ 成人 / ⑦ 创建

const LORA_HINT: Record<string, string> = {
  identity_image: "母版 + 多角度底板 30–40 张 → Qwen Image 2.1 身份 LoRA（笔记本 ai-toolkit）",
  identity_h3: "H3 视频身份 LoRA（gpu3，约 9–11 小时整卡）",
  jewellery: "Blender 精确建模 + 写实化（gpu3）",
  wardrobe: "无人商品图 + 合成试穿（gpu3）",
  pose: "Blender 体位预设 + 写实化（gpu3，docs/pose_library.md）",
};

function useProject(slug: string): [ProjectDetail | null, (p: ProjectDetail) => void, string] {
  const [p, setP] = useState<ProjectDetail | null>(null);
  const [err, fail] = useErr();
  useEffect(() => {
    papi.get(slug).then(setP, fail);
  }, [slug]); // eslint-disable-line react-hooks/exhaustive-deps
  return [p, setP, err];
}

function LoraStep({ slug }: { slug: string }) {
  const [p, , err] = useProject(slug);
  const [plan, setPlan] = useState<Record<string, boolean> | null>(null);
  useEffect(() => {
    if (p && !plan) setPlan(p.settings?.lora_plan && Object.keys(p.settings.lora_plan).length ? p.settings.lora_plan
      : { identity_image: true, identity_h3: true, jewellery: false, wardrobe: false, pose: false });
  }, [p, plan]);
  if (!p || !plan) return <div className="empty">{err || "加载中…"}</div>;
  return (
    <div className="wz-body narrow">
      <Section n="⑤" title="LoRA 计划" hint="勾选本剧需要训练的 LoRA；训练排在 gpu3 GPU1，剧本里的触发词注册后自动生效">
        {Object.entries(p.lora_kinds ?? {}).map(([k, label]) => (
          <label key={k} className={`wz-opt${plan[k] ? " on" : ""}`}>
            <input type="checkbox" checked={!!plan[k]} onChange={(e) => setPlan({ ...plan, [k]: e.target.checked })} />
            <span>
              <b>{label}</b>
              <span className="muted small">{LORA_HINT[k]}</span>
            </span>
          </label>
        ))}
      </Section>
      <Nav slug={slug} step="lora" onNext={async () => {
        await papi.saveSettings(slug, { lora_plan: plan });
      }} />
    </div>
  );
}

function AdultStep({ slug }: { slug: string }) {
  const [p, , err] = useProject(slug);
  const [on, setOn] = useState<boolean | null>(null);
  useEffect(() => {
    if (p && on === null) setOn(!!p.settings?.adult_content);
  }, [p, on]);
  if (!p || on === null) return <div className="empty">{err || "加载中…"}</div>;
  return (
    <div className="wz-body narrow">
      <Section n="⑥" title="成人内容" hint="只有开 / 关">
        <div className="wz-switch">
          <button className={`wz-sw${!on ? " on" : ""}`} onClick={() => setOn(false)}>
            <b>关</b>
            <span className="muted small">成人镜头不出图、不出视频（gpu3 跳过）</span>
          </button>
          <button className={`wz-sw${on ? " on adult" : ""}`} onClick={() => setOn(true)}>
            <b>开</b>
            <span className="muted small">成人镜头的首尾帧与视频只在 gpu3 出；笔记本从不出成人画面</span>
          </button>
        </div>
        <div className="muted small">开启后，生产时仍需项目方在「待办」里授权「交 gpu3」才会开始。</div>
      </Section>
      <Nav slug={slug} step="adult" onNext={async () => {
        await papi.saveSettings(slug, { adult_content: on });
      }} />
    </div>
  );
}

function CreateStep({ slug }: { slug: string }) {
  const [p, setP, err0] = useProject(slug);
  const [err, fail] = useErr();
  if (!p) return <div className="empty">{err0 || "加载中…"}</div>;
  const ready = p.status === "ready";
  const lora = Object.entries(p.settings?.lora_plan ?? {}).filter(([, v]) => v).map(([k]) => p.lora_kinds?.[k] ?? k);
  return (
    <div className="wz-body narrow">
      <Section n="⑦" title={ready ? "项目已创建" : "创建项目"} hint={`projects/${p.slug}/`}>
        <div className="wz-checks">
          {p.readiness?.checks.map((c) => (
            <div key={c.key} className={`wz-checkrow ${c.ok ? "ok" : "bad"}`}>
              <span>{c.ok ? "✓" : "✕"}</span> {c.label}
              {!c.ok && (
                <button className="link" onClick={() => go(`#/projects/${slug}/wizard/${c.key === "lora" ? "lora" : c.key}`)}>
                  去处理
                </button>
              )}
            </div>
          ))}
        </div>
        <div className="wz-summary">
          <div><span className="muted">剧名</span> {p.name}</div>
          <div><span className="muted">集数</span> {p.episodes}</div>
          <div><span className="muted">成人内容</span> {p.settings?.adult_content ? "开" : "关"}</div>
          <div><span className="muted">LoRA</span> {lora.length ? lora.join("、") : "不训练"}</div>
        </div>
        {err && <div className="banner">{err}</div>}
      </Section>
      <div className="wz-nav">
        <button className="btn" onClick={() => go(`#/projects/${slug}/wizard/adult`)}>
          ← 上一步
        </button>
        <span className="grow" />
        {ready ? (
          <button className="btn primary big" onClick={() => go(`#/projects/${slug}/board`)}>
            去进度看板 →
          </button>
        ) : (
          <button className="btn primary big" disabled={!p.readiness?.ok} onClick={() => papi.finalize(slug).then(setP, fail)}>
            创建项目
          </button>
        )}
      </div>
    </div>
  );
}

// ================================================================== 外壳

export function Wizard({ slug, step }: { slug: string | null; step: string }) {
  const [name, setName] = useState("");
  useEffect(() => {
    if (slug) papi.get(slug).then((p) => setName(p.name), () => setName(""));
  }, [slug]);
  let body: ReactNode;
  if (!slug) body = <NameStep />;
  else if (step === "script") body = <ScriptStep slug={slug} />;
  else if (step === "style") body = <StyleStep slug={slug} />;
  else if (step === "characters") body = <CharactersStep slug={slug} />;
  else if (step === "lora") body = <LoraStep slug={slug} />;
  else if (step === "adult") body = <AdultStep slug={slug} />;
  else body = <CreateStep slug={slug} />;
  return (
    <div className="pj-page wz">
      <div className="pj-head">
        <h2>新建剧{name && <span className="muted"> · {name}</span>}</h2>
        <Steps slug={slug} step={slug ? step : "name"} />
      </div>
      {body}
    </div>
  );
}
