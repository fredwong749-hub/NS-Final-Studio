// PW-019：从 MaterialsDrawer.tsx 挪出来的非组件导出（组件文件只导出组件，热更新才不会退化成整页重载）。


export const openMaterials = () => window.dispatchEvent(new CustomEvent("ns:materials"));
