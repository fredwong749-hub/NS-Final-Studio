export type ImgSt = "loading" | "slow" | "retry" | "ok" | "gone";
export const IMG_RETRIES = 4;
export const imgWord: Record<ImgSt, string> = { loading: "", slow: "原图传输中", retry: "原图传输中", ok: "", gone: "文件不在" };
