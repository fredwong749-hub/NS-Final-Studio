// W5 UIUX 11-03（项目方 L-155：“uiux 变得很难用，难理解，把它修了吧”；L-146 旧功能不删只移位）。
// 全站页面登记表——唯一一份：
//   · 每页顶部那一句“这页是什么、你在这能做什么”（PageIntro）
//   · 404 页列出能去的地方（NotFound）
//   · 设置 ▾ 菜单和 #/settings 页底部“全部页面”索引
//   · tests/test_ui_stepbar.py 用它核对：每个旧路由都有一个入口（步骤条 / 待办 / 设置 / 总览）
import type { V3Page } from "./TopBarV3.helpers";

export type PageWhere = "步骤条" | "待办" | "设置" | "设置 › 高级" | "总览" | "旧地址自动跳转";
export interface PageInfo {
  /** 地址（不带 ?参数） */
  hash: V3Page | "#epNN" | "#/projects" | "#/inbox";
  /** 页面名（中文、短） */
  name: string;
  /** 顶部一句话：这页是什么、你在这能做什么 */
  intro: string;
  /** 从哪里点进来（主入口） */
  where: PageWhere;
  /** 入口的具体位置，给“全部页面”表和 404 页看 */
  path: string;
}

export const PAGES: PageInfo[] = [
  // ---- 步骤条（①–⑥）
  { hash: "#/script-create", name: "① 剧本", where: "步骤条", path: "顶部步骤条 ① 剧本", intro: "这部剧每一集的剧本写到哪了；你在这可以看剧本、点“用这版”或“修改”，也可以新建剧本。" },
  { hash: "#/assets", name: "② 资产", where: "步骤条", path: "顶部步骤条 ② 资产", intro: "人物、造型、单品、场景、声音都在这；你在这可以挑候选（用这张 / 修改）、上传参考照片。" },
  { hash: "#epNN", name: "③ 分镜（画布）", where: "步骤条", path: "顶部步骤条 ③ 分镜", intro: "一集一镜一行：首尾帧、提示词、剧本、人物、运镜、声音；你在这可以逐镜看图、点“用这张”或“修改”。" },
  { hash: "#/frames", name: "④ 出图", where: "步骤条", path: "顶部步骤条 ④ 出图", intro: "全部集每一镜的首帧和尾帧；系统自动出图和检查，你在这只需要看新图、点“用这张”或“修改”。" },
  { hash: "#/videos", name: "⑤ 视频", where: "步骤条", path: "顶部步骤条 ⑤ 视频", intro: "全部集每一镜的视频进度；系统自动出视频，你在这可以看片、点“用这条”或“修改”。" },
  { hash: "#/cut", name: "⑥ 成片（剪辑器 · 整集预览）", where: "步骤条", path: "顶部步骤条 ⑥ 成片", intro: "每集的整集预览和剪辑器；你在这可以连播整集、调镜头顺序和时长、导出成片。" },
  // ---- 待办 / 总览
  { hash: "#/queue", name: "待办", where: "待办", path: "顶部右侧“待办”", intro: "需要你动手的事都在这里：每条一句话，点“批准 / 用这张”或“修改”就行，点完系统自己往下走。" },
  { hash: "#/overview", name: "全剧总览", where: "总览", path: "左上角 momoso 标识 / 剧名", intro: "整部剧每一集走到哪一步、系统在做什么、卡在哪、谁在处理；点任何一格看详情或去那一页。" },
  // ---- 设置（日常用得到的二级入口）
  { hash: "#/settings", name: "项目设置", where: "设置", path: "顶部“设置 ▾” › 项目设置", intro: "风格、写实强度、配乐处理等项目级设置：看现在的值，能改的直接改（可撤销）；页底是全部页面的入口。" },
  { hash: "#/sound", name: "声音", where: "设置", path: "② 资产页左栏“声音 · 音色”，或“设置 ▾” › 声音", intro: "人物音色、旁白、每镜台词逐句试听和整集配乐；你在这可以试听、换音色。" },
  { hash: "#/image-edit", name: "图像编辑器", where: "设置", path: "② 资产 / ④ 出图 里的“修改”，或“设置 ▾” › 图像编辑器", intro: "选一镜或一张资产图：看参考、出几张候选、左右对比，写一句话修改。" },
  { hash: "#/script-chat", name: "写作对话", where: "设置", path: "“设置 ▾” › 写作对话（① 剧本页里也有）", intro: "直接和写作模型对话写剧本：新对话、继续下一集、按检查结果返修。" },
  // ---- 设置 › 高级（工程页）
  { hash: "#/models", name: "模型与 API", where: "设置 › 高级", path: "“设置 ▾” › 高级 › 模型与 API", intro: "写作模型、出图和视频机器的配置与连通测试（一般不用动）。" },
  { hash: "#/script-ab", name: "剧本 A/B 对比", where: "设置 › 高级", path: "“设置 ▾” › 高级 › 剧本 A/B 对比", intro: "两份剧本逐镜并排比较首帧、尾帧、视频和提示词，选 A 或选 B。" },
  { hash: "#/audit", name: "操作记录", where: "设置 › 高级", path: "“设置 ▾” › 高级 › 操作记录", intro: "你和系统做过的每个选择、导入、定稿：谁、什么时候、对哪个。只看，不用操作。" },
  { hash: "#/trash", name: "回收站", where: "设置 › 高级", path: "“设置 ▾” › 高级 › 回收站", intro: "删掉的东西都在这里，点“恢复”就能找回。" },
  { hash: "#/v1-library", name: "第一版视频库（只读）", where: "设置 › 高级", path: "“设置 ▾” › 高级 › 第一版视频库 / 剧名下拉 › 历史剧本", intro: "第一版冻结后的视频，只能看，不会进入现在这一版。" },
  { hash: "#/assets-v1", name: "资产中心（旧地址）", where: "设置 › 高级", path: "“设置 ▾” › 高级 › 资产中心（旧地址）", intro: "旧收藏地址，打开的就是 ② 资产中心，内容一样。" },
  // ---- 已下线、自动跳转的旧地址
  { hash: "#/inbox", name: "旧待办地址", where: "旧地址自动跳转", path: "自动跳到“待办”", intro: "旧地址，自动跳到待办。" },
  { hash: "#/projects", name: "旧项目列表地址", where: "旧地址自动跳转", path: "自动跳到 ① 剧本", intro: "旧地址，自动跳到 ① 剧本。" },
];

export const pageInfo = (page: V3Page | null): PageInfo | undefined => PAGES.find((p) => (page ? p.hash === page : p.hash === "#epNN"));

/** 设置 ▾ 菜单 / 设置页索引的分组顺序 */
export const WHERE_ORDER: PageWhere[] = ["步骤条", "待办", "总览", "设置", "设置 › 高级", "旧地址自动跳转"];

/** 某个页面的真实地址（画布 = 当前集） */
export const hrefOf = (p: PageInfo, ep = 1) => (p.hash === "#epNN" ? `#ep${String(ep).padStart(2, "0")}` : p.hash);
