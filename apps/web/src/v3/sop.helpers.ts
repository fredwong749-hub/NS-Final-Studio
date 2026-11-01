// PW-019：从 sop.tsx 挪出来的非组件导出（组件文件只导出组件，热更新才不会退化成整页重载）。
import { createContext, useContext } from "react";
import type { SopEpisode } from "../types";

export type SopCtx = { sop: SopEpisode | null; error: string | null; reload: () => void };

export const Ctx = createContext<SopCtx>({ sop: null, error: null, reload: () => undefined });

export const useSop = () => useContext(Ctx);
