// UIRSI 11-01：“↻ 再生成”按钮 + 弹窗（项目方原话：“添加一个生成按钮,基于现在再生成一个新的图”；
// “在这个图,你加个生成按钮,弹出需求提示词输入框,upload对应的装备(衣服,鞋子,视频,美甲等)图片,然后生图”）。
// 什么都不写、不传 → 同提示词、同参考、同参数，换一个 seed 再出一张；写了要求 / 传了装备图 → 在这一张上按要求改。
// 新图进版本链、旧图保留；过了契约才自动设为当前（G3），没过就留在版本里可手动挑。
import { useEffect, useId, useMemo, useRef, useState } from "react";
import { Button, Modal } from "../ds";
import { hubApi } from "./assets/hub_api";
import { GEAR_CATS, regenTake, registerGear, type GearCat, type GearRef, type RegenStage } from "./RegenButton.helpers";
import "./regen.css";

type Char = { id: string; name: string };
type Row = { key: number; cid: string; cat: GearCat; file: File | null; preview: string | null };

let seq = 0;
/** 视觉隐藏（仍在可访问树和 textContent 里） */
const VH = { position: "absolute", width: 1, height: 1, padding: 0, margin: -1, overflow: "hidden", clip: "rect(0 0 0 0)", whiteSpace: "nowrap", border: 0 } as const;

export function RegenButton({ shot, stage, n, label, chars, onDone, size = "xs", compact = false }: {
  shot: string;
  stage: RegenStage;
  n: number;
  /** “首帧” / “尾帧” */
  label: string;
  /** 本镜人物（装备图登记到谁名下）；不给就从资产中心取全剧人物 */
  chars?: Char[];
  onDone?: (msg: string, kind?: "ok" | "err") => void;
  size?: "xs" | "sm";
  /** UIRSI r35：画布审片行的帧格只有约 78px 宽，整条“↻ 再生成”会折到标签下面、压在人物脸上 → 只露“↻”。
   *  “再生成”三个字仍在按钮里（视觉隐藏，读屏 / 文字查找都还是“↻ 再生成”），悬停提示不变 */
  compact?: boolean;
}) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button
        type="button"
        className={`regen-btn regen-${size}`}
        onClick={(e) => (e.stopPropagation(), setOpen(true))}
        title={`基于这张${label} #${n} 再生成一张新的：可以写要求、传装备图；不写不传 = 同提示词同参考换个随机种子。新图进版本链，旧图保留`}
      >
        {compact ? (
          <>
            ↻<span style={VH}> 再生成</span>
          </>
        ) : (
          "↻ 再生成"
        )}
      </button>
      {open && (
        <RegenDialog
          title={`↻ 再生成 · ${shot} ${label} #${n}`}
          sub="新图进这一镜的版本链，旧图保留；过了检查才自动设为当前，没过也能在版本里手动挑"
          base={`${label} #${n}`}
          where={shot}
          note="这里只收图片（视频文件不作参考）；要换镜头视频，用视频格的“只重出视频（首尾帧不动）”。"
          chars={chars}
          onClose={() => setOpen(false)}
          onSubmit={async (text, refs) => {
            await regenTake(shot, stage, n, { instruction: text, refs });
            const reused = refs.filter((r) => r.reused).length;
            const msg = `${shot} ${label}：已提交再生成（基于 #${n}${refs.length ? `，${refs.length} 张装备图${reused ? `，其中 ${reused} 张库里已有、直接用` : "已登记进资产库"}` : ""}）。出完进版本链，过了检查才设为当前`;
            const unchecked = refs.filter((r) => r.unchecked).length;
            // UIAUDIT P2：查重接口没通时照样登记了 → 提示可能重复（到人物页衣橱看一下）
            onDone?.(unchecked ? `${msg}。注意：有 ${unchecked} 张装备图没能查重，资产库里可能重复，请到人物页衣橱看一下` : msg);
          }}
        />
      )}
    </>
  );
}

/** 通用弹窗（ASSETUX 资产图“再生成”也用它）：要求输入框 + 最多 4 张装备图（先登记进资产库），提交交给 onSubmit。
 *  onSubmit 抛错 → 弹窗里显示“没提交成功：…”，不关；成功 → 关闭 */
export function RegenDialog({ title, sub, base, where = "", chars, note, onClose, onSubmit }: {
  title: string;
  sub?: string;
  /** 底图叫什么（“首帧 #12”“设定图 v3”），用在说明文字里 */
  base: string;
  /** 记进装备图备注（例：镜头号 ep02-S3 / 资产 id），以后能对回是从哪儿传的 */
  where?: string;
  chars?: Char[];
  onClose: () => void;
  onSubmit: (text: string, refs: GearRef[]) => Promise<void>;
  /** 弹窗底部的补充说明（画布传“只收图片 / 视频去视频格重出”；资产页不传 = 不显示） */
  note?: string;
}) {
  const [text, setText] = useState("");
  const [rows, setRows] = useState<Row[]>([]);
  const [all, setAll] = useState<Char[] | null>(chars?.length ? chars : null);
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const ta = useRef<HTMLTextAreaElement>(null);
  const tid = useId();
  useEffect(() => ta.current?.focus(), []);
  useEffect(() => {
    if (all) return;
    hubApi
      .list()
      .then((l) => setAll(l.characters.map((c) => ({ id: c.cid, name: c.name }))))
      .catch(() => setAll([]));
  }, [all]);
  useEffect(() => () => rows.forEach((r) => r.preview && URL.revokeObjectURL(r.preview)), [rows]);
  const people = all ?? [];
  const addRow = () => setRows((rs) => [...rs, { key: ++seq, cid: people[0]?.id ?? "", cat: "shoes", file: null, preview: null }]);
  const patch = (k: number, p: Partial<Row>) => setRows((rs) => rs.map((r) => (r.key === k ? { ...r, ...p } : r)));
  const filled = rows.filter((r) => r.file);
  const missingWho = filled.some((r) => !r.cid);
  const mode = filled.length ? "换装备参考再改" : text.trim() ? "按要求改" : "同提示词换种子";
  const what = useMemo(
    () =>
      filled.length
        ? `以 ${base} 为底图，把${filled.map((r) => GEAR_CATS.find((c) => c.id === r.cat)?.name).join("、")}换成上传的样子${text.trim() ? "，并按你写的要求改" : ""}`
        : text.trim()
          ? `以 ${base} 为底图，按你写的要求改`
          : `同一段提示词、同一组参考、同样的参数，换一个随机种子再出一张`,
    [filled, text, base],
  );

  const submit = async () => {
    setErr(null);
    try {
      const refs: GearRef[] = [];
      for (const [i, r] of filled.entries()) {
        setBusy(`登记装备图 ${i + 1}/${filled.length}…`);
        refs.push(await registerGear(r.cid, r.file!, r.cat, undefined, where));
      }
      setBusy("提交出图…");
      await onSubmit(text, refs);
      onClose();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  };

  return (
    <Modal
      title={title}
      sub={sub}
      onClose={busy ? () => {} : onClose}
      foot={
        <>
          <span className="regen-mode" title={what}>
            {mode}
          </span>
          <Button variant="ghost" size="sm" onClick={onClose} disabled={!!busy} title={busy ? "正在提交，稍等" : "不出图，关掉"}>
            取消
          </Button>
          <Button
            variant="primary"
            size="sm"
            onClick={() => void submit()}
            disabled={!!busy || missingWho}
            title={missingWho ? "装备图要选登记到哪个人物名下" : busy ?? what}
          >
            {busy ?? "生成"}
          </Button>
        </>
      }
    >
      <div className="regen-body" onClick={(e) => e.stopPropagation()}>
        <label className="regen-l" htmlFor={tid}>
          要求 / 提示词<small>（可不写；不写不传图 = 同提示词换个种子）</small>
        </label>
        <textarea
          id={tid}
          ref={ta}
          className="regen-ta"
          rows={3}
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="例：换成侧脸；手里拿咖啡杯；鞋换成上传的这双"
        />
        <div className="regen-l">
          装备参考图<small>（衣服、鞋、美甲、饰品…；会登记进资产库对应人物名下，不改其他镜头的造型）</small>
        </div>
        {rows.map((r) => (
          <div className="regen-row" key={r.key}>
            <label className="regen-drop" title="选一张图片（png / jpg / webp）">
              {r.preview ? <img src={r.preview} alt="装备图" /> : <span>选图</span>}
              <input
                type="file"
                accept="image/png,image/jpeg,image/webp"
                onChange={(e) => {
                  const f = e.target.files?.[0] ?? null;
                  if (r.preview) URL.revokeObjectURL(r.preview);
                  patch(r.key, { file: f, preview: f ? URL.createObjectURL(f) : null });
                }}
              />
            </label>
            <select className="ds-input" value={r.cat} onChange={(e) => patch(r.key, { cat: e.target.value as GearCat })} aria-label="类别">
              {GEAR_CATS.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
            <select className="ds-input" value={r.cid} onChange={(e) => patch(r.key, { cid: e.target.value })} aria-label="谁的装备">
              {!r.cid && <option value="">选人物…</option>}
              {people.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
            <button type="button" className="regen-x" onClick={() => setRows((rs) => rs.filter((x) => x.key !== r.key))} title="去掉这张" aria-label="去掉这张">
              ×
            </button>
          </div>
        ))}
        <button type="button" className="regen-add" onClick={addRow} disabled={all === null || rows.length >= 4} title={rows.length >= 4 ? "一次最多 4 张" : all === null ? "正在读人物列表" : "加一张装备图"}>
          + 加一张装备图
        </button>
        {note && <p className="regen-note">{note}</p>}
        {err && (
          <p className="regen-err" role="alert">
            没提交成功：{err}
          </p>
        )}
      </div>
    </Modal>
  );
}
