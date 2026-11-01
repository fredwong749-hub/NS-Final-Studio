// fredw-92/W4a：本集 SOP 数据只取一次，顶栏步骤条、集头“待你决定”、镜头“为什么卡住”共用
// fredw-92/UXF1：加 reload()——项目方在“待你决定”里拍板后立即重取（不等 30 s 轮询）
import { useCallback, useEffect, useState, type ReactNode } from "react";
import { api } from "../api";
import { useStudio } from "../store";
import type { SopEpisode } from "../types";
import { Ctx } from "./sop.helpers";

export function SopProvider({ children }: { children: ReactNode }) {
  const { epNum } = useStudio();
  const [sop, setSop] = useState<SopEpisode | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [rev, setRev] = useState(0);
  const reload = useCallback(() => setRev((r) => r + 1), []);
  useEffect(() => {
    if (epNum == null) return;
    let alive = true;
    const load = () =>
      api.sopEpisode(epNum).then(
        (d) => alive && (setSop(d), setError(null)),
        (e: Error) => alive && setError(e.message),
      );
    // UIRSI r16（首屏）：SOP 全量计算 0.5–1 s，和本集剧本（/api/episodes/N，画布行靠它）同时请求会互相拖慢到 2 s；
    // 首次晚 700 ms 再取，让镜头行先出来（项目方在“待你决定”里点了 reload 时立即取）
    const first = window.setTimeout(load, rev ? 0 : 700);
    const t = setInterval(load, 30000);
    return () => {
      alive = false;
      window.clearTimeout(first);
      clearInterval(t);
    };
  }, [epNum, rev]);
  // 换集时清空（同集 reload 不清，免得“待你决定”条闪一下）
  useEffect(() => setSop(null), [epNum]);
  return <Ctx.Provider value={{ sop, error, reload }}>{children}</Ctx.Provider>;
}

