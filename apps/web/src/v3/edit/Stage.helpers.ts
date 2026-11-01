// PW-019：从 Stage.tsx 挪出来的非组件导出（组件文件只导出组件，热更新才不会退化成整页重载）。


/** , / . 逐帧（24 fps）；作用到大格里所有视频（并排对比时两边一起） */
export function stepFrames(root: HTMLElement | null, dir: -1 | 1) {
  root?.querySelectorAll<HTMLVideoElement>(".v3e-stage video[data-play]").forEach((v) => {
    v.pause();
    v.currentTime = Math.max(0, Math.min((v.duration || 0) - 0.001, v.currentTime + dir / 24));
  });
}
