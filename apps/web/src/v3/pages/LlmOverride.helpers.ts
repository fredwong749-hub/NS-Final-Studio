// 从 LlmOverride.tsx 挪出来的非组件导出（PW-019：.tsx 只导出组件，热更新才不会整页重载）
import { useCallback, useEffect, useState } from "react";
import { errText, isNotReady, llmApi, type LlmChoice, type Providers } from "../api_v1_pages";

export function useProviders() {
  const [data, setData] = useState<Providers | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [notReady, setNotReady] = useState(false);
  const reload = useCallback(async () => {
    try {
      const d = await llmApi.providers();
      setData(d);
      setErr(null);
      setNotReady(false);
    } catch (e) {
      setErr(errText(e));
      setNotReady(isNotReady(e));
    }
  }, []);
  useEffect(() => {
    void reload();
  }, [reload]);
  return { data, err, notReady, reload, setData };
}

/** 某用途的默认选择（purposes 表 + 该服务商默认参数） */
export function purposeDefault(d: Providers | null, purpose: string): LlmChoice | null {
  if (!d) return null;
  const p = d.purposes.find((x) => x.id === purpose);
  const pv = d.providers.find((x) => x.id === p?.provider) ?? null;
  if (!p || !pv) return null;
  return { provider: pv.id, model: p.model || pv.default_model, params: { ...pv.params } };
}

export const KEY = (where: string) => `ns.llm.at.${where}`;

export function loadAt(where: string): LlmChoice | null {
  try {
    const s = localStorage.getItem(KEY(where));
    return s ? (JSON.parse(s) as LlmChoice) : null;
  } catch {
    return null;
  }
}

export function saveAt(where: string, v: LlmChoice | null) {
  try {
    if (v) localStorage.setItem(KEY(where), JSON.stringify(v));
    else localStorage.removeItem(KEY(where));
  } catch {
    /* 隐私模式 */
  }
}

/** 某个按钮处的覆盖：初值 = 此处默认（本机），null = 跟随用途默认 */
export function useLlmOverride(where: string) {
  const [v, setV] = useState<LlmChoice | null>(() => loadAt(where));
  return [v, setV] as const;
}
