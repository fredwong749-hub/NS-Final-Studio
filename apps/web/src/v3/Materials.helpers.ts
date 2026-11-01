// PW-019：从 Materials.tsx 挪出来的非组件导出（组件文件只导出组件，热更新才不会退化成整页重载）。


export type Item = { key: string; label: string; reason: string; who: string };

export type ShotMat = { id: string; ready: boolean; missing: Item[]; conflicts: Item[] };

export type EpMat = { episode: number; episode_items: Item[]; shots: ShotMat[] };

export const TTL_MS = 30_000;

export const cache = new Map<number, { at: number; p: Promise<EpMat | null> }>();

export function loadReadiness(ep: number, fresh = false): Promise<EpMat | null> {
  if (fresh) cache.delete(ep);
  return load(ep);
}

export function load(ep: number): Promise<EpMat | null> {
  const hit = cache.get(ep);
  if (hit && Date.now() - hit.at < TTL_MS) return hit.p;
  const p = fetch(`/api/episodes/${ep}/readiness`)
    .then((r) => (r.ok ? (r.json() as Promise<EpMat>) : null))
    .catch(() => null);
  cache.set(ep, { at: Date.now(), p });
  return p;
}
