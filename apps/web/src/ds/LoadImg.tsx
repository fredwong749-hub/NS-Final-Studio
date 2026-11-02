// NAVIA：大图还在从服务器传回时显示“原图传输中”，不显示空白或裂图（项目方 20:1x）。
// 过程：加载中（超过 0.3 s 才出提示，避免缓存图闪一下）→ 失败时自动重试 4 次（间隔 3 / 6 / 9 / 12 秒，文件可能正在同步）→ 仍然没有才写“文件不在”。
import { useEffect, useState, type ImgHTMLAttributes } from "react";
import "./loadimg.css";

type St = "loading" | "slow" | "retry" | "ok" | "gone";
export const IMG_RETRIES = 4;
export const imgWord: Record<St, string> = { loading: "", slow: "原图传输中", retry: "原图传输中", ok: "", gone: "文件不在" };

export function LoadImg({ src, onLoad, onError, style, alt = "", ...rest }: ImgHTMLAttributes<HTMLImageElement> & { src: string }) {
  const [st, setSt] = useState<St>("loading");
  const [tries, setTries] = useState(0);
  useEffect(() => {
    setSt("loading");
    setTries(0);
  }, [src]);
  useEffect(() => {
    if (st !== "loading") return;
    const t = window.setTimeout(() => setSt((s) => (s === "loading" ? "slow" : s)), 300);
    return () => window.clearTimeout(t);
  }, [st, tries, src]);
  useEffect(() => {
    if (st !== "retry") return;
    const t = window.setTimeout(() => (setTries((n) => n + 1), setSt("loading")), 3000 * (tries + 1));
    return () => window.clearTimeout(t);
  }, [st, tries]);
  const real = tries ? `${src}${src.includes("?") ? "&" : "?"}r=${tries}` : src;
  return (
    <>
      <img
        {...rest}
        src={real}
        alt={alt}
        style={{ ...style, opacity: st === "ok" ? undefined : 0 }}
        onLoad={(e) => (setSt("ok"), onLoad?.(e))}
        onError={(e) => {
          if (tries < IMG_RETRIES) setSt("retry");
          else setSt("gone");
          onError?.(e);
        }}
      />
      {(st === "slow" || st === "retry" || st === "gone") && (
        <span className={`img-xfer${st === "gone" ? " gone" : ""}`} role="img" aria-label={alt || imgWord[st]} data-state={st}>
          {st !== "gone" && <i aria-hidden="true" />}
          {imgWord[st]}
        </span>
      )}
    </>
  );
}
