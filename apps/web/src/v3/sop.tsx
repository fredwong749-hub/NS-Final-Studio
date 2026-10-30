// fredw-92/W4a：本集 SOP 数据只取一次，顶栏步骤条、集头“待你决定”、镜头“为什么卡住”共用
import { createContext, useContext, type ReactNode } from "react";
import { useSopEpisode } from "../components/SopBar";
import { useStudio } from "../store";
import type { SopEpisode } from "../types";

const Ctx = createContext<{ sop: SopEpisode | null; error: string | null }>({ sop: null, error: null });

export function SopProvider({ children }: { children: ReactNode }) {
  const { epNum } = useStudio();
  const v = useSopEpisode(epNum);
  return <Ctx.Provider value={v}>{children}</Ctx.Provider>;
}

export const useSop = () => useContext(Ctx);
