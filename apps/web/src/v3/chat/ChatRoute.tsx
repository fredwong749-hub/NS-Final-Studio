// 回退补回（regress_r1 #14）：写作对话框（新对话 / 继续下一集 / 按校验返修）——归档前的 chat/ChatApp 原样恢复到 v3 外壳里。
// 后端 /api/script-chat（services/api/ns_api/script_chat.py）一直在。
import { useHash } from "../../projects/route";
import ChatApp from "./ChatApp";

export default function ChatRoute() {
  const hash = useHash();
  return <ChatApp hash={hash} />;
}
