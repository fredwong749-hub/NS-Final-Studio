// PW-019：从 MediaPlayer.tsx 挪出来的非组件导出（组件文件只导出组件，热更新才不会退化成整页重载）。


// ---------------------------------------------------------------- 全站单例：同一时间只响一个
export let current: HTMLAudioElement | HTMLVideoElement | null = null;

export function claim(el: HTMLAudioElement | HTMLVideoElement) {
  if (current && current !== el) current.pause();
  current = el;
}

export const fmt = (s: number) => {
  if (!Number.isFinite(s) || s < 0) return "0:00";
  const m = Math.floor(s / 60);
  const r = Math.floor(s % 60);
  return `${m}:${String(r).padStart(2, "0")}`;
};

// ---------------------------------------------------------------- 波形（解码一次，按 URL 缓存）
export const peaksCache = new Map<string, Promise<number[] | null>>();

export function loadPeaks(src: string, bins = 160): Promise<number[] | null> {
  const key = `${src}#${bins}`;
  const hit = peaksCache.get(key);
  if (hit) return hit;
  const p = (async () => {
    try {
      const AC = window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
      if (!AC) return null;
      const buf = await (await fetch(src)).arrayBuffer();
      if (buf.byteLength > 60 * 1024 * 1024) return null; // 太大的整集文件不画波形，只给进度条
      const ctx = new AC();
      const audio = await ctx.decodeAudioData(buf);
      void ctx.close();
      const ch = audio.getChannelData(0);
      const step = Math.max(1, Math.floor(ch.length / bins));
      const out: number[] = [];
      for (let i = 0; i < bins; i++) {
        let m = 0;
        for (let j = i * step; j < Math.min(ch.length, (i + 1) * step); j += 4) m = Math.max(m, Math.abs(ch[j]));
        out.push(m);
      }
      const top = Math.max(0.01, ...out);
      return out.map((v) => v / top);
    } catch {
      return null;
    }
  })();
  peaksCache.set(key, p);
  return p;
}
