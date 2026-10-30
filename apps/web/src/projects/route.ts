import { useEffect, useState } from "react";

export function isProjectsRoute(hash: string) {
  return hash.startsWith("#/projects") || hash.startsWith("#/inbox");
}

export function useHash() {
  const [hash, setHash] = useState(window.location.hash);
  useEffect(() => {
    const on = () => setHash(window.location.hash);
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return hash;
}

/** fredw-b3：画布最后停留的位置（store 写入 sessionStorage），回画布时恢复选中的镜头 */
export function lastCanvas() {
  try {
    return sessionStorage.getItem("ns.lastCanvas") || "#/";
  } catch {
    return "#/";
  }
}
