// PW-019：PeopleHub.tsx 只导出组件；人物列表的读取 hook 放这里（模块级缓存）
import { useEffect, useState } from "react";
import { hubApi, type HubList } from "./hub_api";

let listCache: Promise<HubList> | null = null;
export function useHubList(tick = 0) {
  const [d, setD] = useState<HubList | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    let alive = true;
    if (tick > 0 || !listCache) listCache = hubApi.list();
    listCache.then(
      (x) => alive && (setD(x), setErr(null)),
      (e) => {
        listCache = null;
        if (alive) setErr(String((e as Error).message ?? e));
      },
    );
    return () => {
      alive = false;
    };
  }, [tick]);
  return { list: d, err };
}
