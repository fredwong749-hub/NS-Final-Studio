// 从 TopBarV3.tsx 挪出来的非组件导出（PW-019：.tsx 只导出组件，热更新才不会整页重载）

/** 新页面路由（W4c 的页面挂在 #/…） */
export const V3_PAGES = ["#/script-create", "#/models", "#/assets", "#/cut", "#/trash", "#/audit", "#/sound", "#/overview", "#/script-chat", "#/script-ab", "#/settings"] as const;

export type V3Page = (typeof V3_PAGES)[number];
export const pageOf = (hash: string): V3Page | null => V3_PAGES.find((p) => hash === p || hash.startsWith(`${p}/`) || hash.startsWith(`${p}?`)) ?? null;
