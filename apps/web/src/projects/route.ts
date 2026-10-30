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
