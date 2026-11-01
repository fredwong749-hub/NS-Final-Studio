// 从 AuthGate.tsx 挪出来的非组件导出（PW-019：.tsx 只导出组件，热更新才不会整页重载）
import { createContext, useContext } from "react";

export type Me = { name: string; role: string } | null;

export const Ctx = createContext<{ me: Me; logout: () => void }>({ me: null, logout: () => undefined });

export const useMe = () => useContext(Ctx);
