// UIRSI r14（技术分：缩略图）：列表 / 格子里的图走 /api/thumb 的 JPEG 缩略图（后端按宽度缓存），原图只在点开大图时取。
// 不是 /files/… 的地址（已经是缩略图、外链、data:）原样返回。
export function thumb(url: string | null | undefined, w = 360): string | null {
  if (!url) return null;
  // 只认数据文件（/files/…）和资产图（资产文件接口，带 path 参数）；用正则判断，不是一次请求
  if (!(url.startsWith("/files/") || /^\/api\/assets\/file\?path=/.test(url)) || /\/_thumbs\//.test(url)) return url;
  return `/api/thumb?src=${encodeURIComponent(url)}&w=${w}`;
}
