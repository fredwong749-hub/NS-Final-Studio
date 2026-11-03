// 从 OwnerDecision.tsx 挪出来的非组件导出（PW-019：.tsx 只导出组件，热更新才不会整页重载）

import { useEffect, useState } from "react";
import type { SopOwnerAction } from "../types";

/** 界面里能直接拍板的关口（其余仍只显示说明） */
export const DECIDABLE = new Set(["look", "G3", "G4", "G5", "plate"]);

/** 芯片上的短标题：去掉关口代号，角色用中文名 */
export function actionTitle(a: SopOwnerAction): string {
  if (a.gate === "look" && a.per_episode) return a.title;   // V2CUT-O：后端已给“确认第 N 集造型：人名…”（不含 id）
  if (a.gate === "look" && a.character_name) return `确认造型：${a.character_name}`;
  return a.title.replace(/（G\d）/g, "").replace(/\bG\d\b\s*/g, "").trim();
}

// ---------------------------------------------------------------- UIFIX-F 11-03：造型确认属于资产阶段

/** 造型确认入口还不能开：人物的身份脸没选定 / 没进清单 / 本集没排期（后端 asset_ready=false，口径 tools/master/episode_ready） */
export const isLookWaiting = (a: SopOwnerAction) => a.gate === "look" && a.asset_ready === false;

/** 给项目方看的一句话（不露 id、不露命令行） */
export const lookWaitText = (a: SopOwnerAction) => a.asset_wait || `${a.character_name ?? a.character ?? "这个人物"}的形象还在出候选，选定后再确认造型`;

/** 后端回的 404 / 405 是“没有这个接口”（API 比网页旧）还是资源不存在（例如“没有这个角色”）——只有前者算接口缺失 */
export const routeMissing = (status: number, detail: string | null | undefined) =>
  status === 405 || (status === 404 && (!detail || /^(Not Found|404 |没有这个接口)/.test(detail)));

let apiState: boolean | null = null; // null = 还没探过
let apiProbe: Promise<boolean> | null = null;
/** 探一次 POST /api/sop/owner-decision 在不在：空 body 只会被校验拦下（422 / 400 / 403），不会记录任何决定；
 *  404（没有这个接口）/ 405 → 不在，入口整个隐藏，而不是让项目方点了以后才报错 */
export function probeOwnerDecisionApi(): Promise<boolean> {
  if (apiState != null) return Promise.resolve(apiState);
  if (!apiProbe)
    apiProbe = fetch("/api/sop/owner-decision", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" })
      .then(async (r) => {
        if (r.ok) return true;
        let detail: string | null = null;
        try {
          const j = await r.json();
          detail = typeof j?.detail === "string" ? j.detail : j?.detail ? JSON.stringify(j.detail) : null;
        } catch {
          /* 非 JSON */
        }
        return !routeMissing(r.status, detail);
      })
      .catch(() => true) // 连不上后台：不是“接口不存在”，入口照显示，点了再报连接错误
      .then((ok) => {
        apiState = ok;
        apiProbe = null;
        return ok;
      });
  return apiProbe;
}
/** 测试 / 后台重连后重探 */
export const resetOwnerDecisionApi = () => {
  apiState = null;
};
export const ownerDecisionApiState = () => apiState;

/** 组件里用：true = 接口在；false = 不在（入口隐藏）；null = 还没探到（先按在显示，探到不在再收起） */
export function useOwnerDecisionApi(): boolean | null {
  const [ok, setOk] = useState<boolean | null>(apiState);
  useEffect(() => {
    let alive = true;
    void probeOwnerDecisionApi().then((v) => alive && setOk(v));
    return () => {
      alive = false;
    };
  }, []);
  return ok;
}

/** 「待你决定」里能显示成可点芯片的动作：接口在、且不是“资产还没就绪”的造型确认 */
export const chipVisible = (a: SopOwnerAction, api: boolean | null) => api !== false && !isLookWaiting(a);
