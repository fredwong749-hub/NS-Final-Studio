// UX6：二次确认框（回到这版 / 保留旧版 / 改动提议）。
// gated = 项目方闸门（定妆 / 身份 LoRA / 音色 / 保留旧版）：必须填项目方原话，请求体带 by=owner + owner_quote，后端缺了就 403。
// 系统只转交原话，不判断原话内容。
import { useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { Button, Modal } from "../../ds";

export function OwnerConfirm({
  title,
  sub,
  lines,
  gated,
  quoteOptional: _quoteOptional,
  gateLabel,
  okText = "确认",
  okDisabled,
  quotePlaceholder = "备注（可空）",
  danger,
  onClose,
  onConfirm,
}: {
  title: ReactNode;
  sub?: ReactNode;
  lines?: ReactNode[];
  gated?: boolean;
  /** 显示原话框但不强制（例如“提议”：项目方附原话 = 已确认，不附 = 待确认） */
  quoteOptional?: boolean;
  gateLabel?: string | null;
  okText?: string;
  /** 不能提交的原因（有值 = 确认按钮禁用并在悬停里写原因） */
  okDisabled?: string | null;
  quotePlaceholder?: string;
  danger?: boolean;
  onClose: () => void;
  /** 返回提示文字（成功）；抛错 = 失败，框不关 */
  onConfirm: (quote: string) => Promise<string | void>;
}) {
  const [quote, setQuote] = useState("");
  const [step, setStep] = useState<1 | 2>(1);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);
  // 项目方 2026-10-31：“很多事情只有一个确认按钮就可以……你不需要每个东西都要打上一个字”——登录即本人，
  // 不再要求原话、不再两步确认；只有不可逆的（danger）点两下，也不打字。备注可选。
  const need = false;
  async function go() {
    if (danger && step === 1) return setStep(2);
    setBusy(true);
    setErr(null);
    try {
      const m = await onConfirm(quote.trim());
      setDone(m || "已完成");
    } catch (e) {
      const msg = String((e as Error)?.message ?? e);
      setErr((e as { status?: number })?.status === 403 ? `后台拒绝（403）：${msg}` : msg);
    } finally {
      setBusy(false);
    }
  }
  // 挂到 body：从抽屉里打开时也盖住整个页面（不受抽屉层叠上下文影响）
  return createPortal(
    <Modal
      title={title}
      sub={sub}
      onClose={onClose}
      foot={
        done ? (
          <Button variant="primary" onClick={onClose}>
            关闭
          </Button>
        ) : (
          <>
            <Button variant="ghost" onClick={onClose}>
              取消
            </Button>
            <Button variant={danger ? "danger" : "primary"} disabled={busy || !!need || !!okDisabled} why={okDisabled || ""} onClick={() => void go()}>
              {busy ? "提交中…" : step === 1 ? okText : `确定：${okText}`}
            </Button>
          </>
        )
      }
    >
      {lines?.map((l, i) => (
        <div key={i} className="ds-small oc-line">
          {l}
        </div>
      ))}
      {gated && !done && (
        <details className="oc-gate">
          <summary className="ds-small ds-muted">{gateLabel ? `${gateLabel} · ` : ""}记在你的账户名下（可选：加一句备注）</summary>
          <textarea className="ds-input oc-quote" rows={2} value={quote} onChange={(e) => setQuote(e.target.value)} placeholder={quotePlaceholder.replace("项目方原话（原样记下）", "备注（可空）")} aria-label="备注（可选）" />
        </details>
      )}
      {step === 2 && !done && <p className="ds-note warn">这一步不能撤回，再点一次确定。</p>}
      {err && (
        <p className="ds-note bad" role="alert">
          {err}
        </p>
      )}
      {done && <p className="ds-note ok">{done}</p>}
    </Modal>,
    document.body,
  );
}
