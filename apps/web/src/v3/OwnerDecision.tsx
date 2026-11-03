// fredw-92/UXF1（审查 #8）：「待你决定」在画布里直接拍板——确认造型 / 锁定样片参数 / 验收成片 / 采纳剧本加强 / 确认场景底板。
// 只给项目方本人点：必须勾“我是项目方本人”+ 填原话；后端 POST /api/sop/owner-decision（by=owner），
// 记录与命令行（tools/sop_owner.py、tools/s1_gate.py、ns_agent.looks confirm）同一份逻辑。agent 不调用这里。
import { useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import { useStudio } from "../store";
import type { LookPerson, SopOwnerAction } from "../types";
import { useSop } from "./sop.helpers";
import { useCharAssets, resolveLook } from "./looks";
import { stageWords } from "./words";

import { DECIDABLE, actionTitle, isLookWaiting, lookWaitText, routeMissing } from "./OwnerDecision.helpers";
type Body = {
  gate: string;
  by: "owner";
  quote: string;
  character?: string;
  episodes?: string;
  episode?: number;
  rework?: boolean;
  scene_id?: string;
};

async function postDecision(b: Body): Promise<{ ok: boolean }> {
  const r = await fetch("/api/sop/owner-decision", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(b) });
  if (!r.ok) {
    let detail: string | null = null;
    try {
      const j = await r.json();
      if (j?.detail) detail = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
    } catch {
      /* 非 JSON */
    }
    // UIFIX-F 11-03：以前把所有 404 都说成“后端还没有这个接口（API 需要重启一次）”——“没有这个角色：卓琳”这种资源 404 也被这么报。
    // 接口真不在 = 入口早已隐藏（useOwnerDecisionApi），这里只剩资源 / 校验错误，照后端原话说
    throw new Error(routeMissing(r.status, detail) ? "这个确认入口现在不可用，稍后再试" : detail || `记录失败（${r.status}）`);
  }
  return r.json();
}

/** V2CUT-O 11-03：本集全部人物的造型卡（人名 + 本集造型 + 缩略图；没就绪的人写原因）。通知中心的确认卡用同一组字段 */
export function LookPeople({ people, onNav }: { people: LookPerson[]; onNav?: () => void }) {
  return (
    <div className="v3-owner-people">
      {people.map((p) => (
        <div key={p.cid} className="v3-owner-look">
          {p.thumb_url ? <img src={p.thumb_url} alt={p.display_name} /> : <span className="v3-owner-noimg" title={p.thumb_note ?? undefined}>{p.display_name.slice(0, 1)}</span>}
          <div>
            <b>{p.display_name}</b>
            <small>本集用：{p.look_name}</small>
            {p.thumb_note ? <small>{p.thumb_note}</small> : null}
            {!p.ready && p.wait ? <small className="v3-owner-wait">{p.wait}</small> : null}
          </div>
        </div>
      ))}
      <small>
        看大图、换造型：
        <a href="#/assets" onClick={onNav}>
          资产页
        </a>
      </small>
    </div>
  );
}

export function OwnerDecisionDialog({ a, onClose }: { a: SopOwnerAction; onClose: () => void }) {
  const st = useStudio();
  const { reload } = useSop();
  const [me] = useState(true);
  const [quote, setQuote] = useState("");
  const [allEps, setAllEps] = useState(false);
  const [rework, setRework] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      e.stopImmediatePropagation();
      e.preventDefault();
      onClose();
    };
    window.addEventListener("keydown", h, true);
    return () => window.removeEventListener("keydown", h, true);
  }, [onClose]);

  const ep = st.epNum;
  const eps = a.episodes ?? [];
  // 造型：本集视角默认只确认本集；可选“全部未确认的集”
  const lookEps = allEps ? eps : eps.includes(ep) ? [ep] : eps.slice(0, 1);
  // V2CUT-O 11-03：资产包剧每集一条（a.people：人名 / 本集造型 / 缩略图都由后端给），不再按角色 id 去旧造型库查“本集用”
  const perEp = a.gate === "look" && !!a.per_episode;
  const lookPeople = useMemo(() => {
    if (a.gate !== "look" || perEp) return null;
    const seen = st.episode?.shots.flatMap((s) => s.characters).find((c) => c.character === a.character);
    return seen ?? null;
  }, [a.gate, a.character, st.episode, perEp]);

  // fredw-92/UXF5（审查 #31 / #39）：形象图和名字与资产页、参考条同一个解析（v3/looks.ts），不再一边“形象 A · 默认”一边“默认”
  const charAssets = useCharAssets(a.gate === "look" && !perEp ? a.character : null);
  const lookShown = charAssets ? resolveLook(charAssets, lookPeople?.look_id ?? charAssets.default_look_id) : null;

  // UIFIX-F 11-03：造型确认属于资产阶段——身份脸没选定的人不开确认，弹窗只说一句话
  const waiting = isLookWaiting(a);
  const decidable = DECIDABLE.has(a.gate) && a.actionable && !waiting;
  // 项目方 2026-10-31：登录即本人，一个按钮确认；不再勾选“我是本人”、不再必填原话（备注可选）
  const can = decidable && !busy;
  void me;
  const verb =
    perEp
      ? `确认第 ${a.episode ?? eps[0]} 集全部造型`
      : a.gate === "look"
      ? `确认${a.character_name ?? a.character}的造型（第 ${lookEps.join("、")} 集）`
      : a.gate === "G4"
        ? `锁定第 ${a.episode ?? 1} 集样片的出图参数`
        : a.gate === "G5"
          ? rework
            ? `第 ${a.episode} 集成片返工`
            : `验收第 ${a.episode} 集成片（发布）`
          : a.gate === "G3"
            ? "采纳 v3 剧本加强"
            : a.gate === "plate"
              ? `确认场景底板 ${a.scene_id ?? ""}`
              : actionTitle(a);

  const submit = async () => {
    if (!can) return;
    setBusy(true);
    setErr(null);
    const b: Body = { gate: a.gate, by: "owner", quote: quote.trim() };
    if (perEp) b.episodes = String(a.episode ?? eps[0]);
    else if (a.gate === "look") Object.assign(b, { character: a.character, episodes: compactEps(lookEps) });
    if (a.gate === "G4") b.episode = a.episode ?? 1;
    if (a.gate === "G5") Object.assign(b, { episode: a.episode, rework });
    if (a.gate === "plate") b.scene_id = a.scene_id;
    try {
      await postDecision(b);
      st.notify(`已记录：${verb}`);
      reload();
      onClose();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return createPortal(
    <div className="modal-back" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal v3-owner" role="dialog" aria-label={actionTitle(a)}>
        <div className="modal-head">
          <b>{actionTitle(a)}</b>
          <button className="btn-mini" onClick={onClose}>
            关闭 Esc
          </button>
        </div>
        <div className="modal-body">
          {waiting ? <p className="v3-owner-wait">{perEp ? a.waiting_on.join("；") : lookWaitText(a)}</p> : <p className="v3-owner-why">{stageWords(a.why.replace(/^S\d[：:]\s*/, ""))}</p>}
          {perEp && <LookPeople people={a.people ?? []} onNav={onClose} />}
          {a.gate === "look" && !perEp && !waiting && (
            <div className="v3-owner-look">
              {lookShown?.url ?? lookPeople?.face_url ? <img src={(lookShown?.url ?? lookPeople?.face_url)!} alt="" /> : <span className="v3-owner-noimg">{(a.character_name ?? "?").slice(0, 1)}</span>}
              <div>
                <b>{a.character_name ?? a.character}</b>
                {(lookShown || lookPeople) && <small>本集用：{lookShown?.title ?? (lookPeople?.look_name || lookPeople?.look_label || "默认形象")}</small>}
                <small>
                  看形象大图、换造型：
                  <a href="#/assets" onClick={onClose}>
                    资产页
                  </a>
                </small>
              </div>
            </div>
          )}
          {a.gate === "look" && !perEp && eps.length > 1 && (
            <div className="v3-owner-scope">
              <label>
                <input type="radio" checked={!allEps} onChange={() => setAllEps(false)} /> 只确认第 {eps.includes(ep) ? ep : eps[0]} 集
              </label>
              <label>
                <input type="radio" checked={allEps} onChange={() => setAllEps(true)} /> 全部未确认的 {eps.length} 集
              </label>
            </div>
          )}
          {a.gate === "G5" && (
            <div className="v3-owner-scope">
              <label>
                <input type="radio" checked={!rework} onChange={() => setRework(false)} /> 验收通过，发布
              </label>
              <label>
                <input type="radio" checked={rework} onChange={() => setRework(true)} /> 返工（备注里写原因）
              </label>
            </div>
          )}
          {!a.actionable && !waiting && (
            <div className="v3-owner-wait">
              <b>还不能做，先等：</b>
              <ul>
                {a.waiting_on.map((w, i) => (
                  <li key={i}>{w}</li>
                ))}
              </ul>
            </div>
          )}
          {decidable ? (
            <>
              <label className="v3-owner-quote">
                <span>备注（可空；记在你的账户名下）</span>
                <textarea rows={3} value={quote} onChange={(e) => setQuote(e.target.value)} placeholder={a.gate === "G5" && rework ? "例：第 3 集节奏太慢，S4–S6 重剪" : "例：这套造型可以，第 2 集就用它"} />
              </label>
            </>
          ) : (
            a.actionable && !waiting && <p className="v3-owner-wait">这一项在界面里还不能直接确认。</p>
          )}
          {err && <p className="v3-owner-err">没记上：{err}</p>}
          {/* UIFIX-F 11-03：不再显示“等价的命令行”（项目方界面不露命令行 / 技术词；记录逻辑本就与命令行同一份） */}
        </div>
        <div className="modal-foot">
          <button className="btn" onClick={onClose}>
            取消
          </button>
          {decidable && (
            <button className={`btn ${a.gate === "G5" && rework ? "bad" : "primary"}`} disabled={!can} onClick={() => void submit()} title="记在你的账户名下">
              {busy ? "记录中…" : verb}
            </button>
          )}
        </div>
      </div>
    </div>,
    document.body,
  );
}

/** [1,2,3,5] → "1-3,5"（后端 parse_episode_list 认的格式） */
function compactEps(nums: number[]): string {
  const a = [...new Set(nums)].sort((x, y) => x - y);
  const out: string[] = [];
  for (let i = 0; i < a.length; ) {
    let j = i;
    while (j + 1 < a.length && a[j + 1] === a[j] + 1) j++;
    out.push(i === j ? String(a[i]) : `${a[i]}-${a[j]}`);
    i = j + 1;
  }
  return out.join(",");
}
