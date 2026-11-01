"""Extract owner (human) messages + AskUserQuestion Q/A from Claude Code transcripts.
Usage: python -I -X utf8 extract_owner_messages.py OUT.md transcript1.jsonl [transcript2.jsonl ...]
"""
import json, re, sys

SECRET = re.compile(r"(sk[_-][A-Za-z0-9]{12,}|ak_[A-Za-z0-9]{12,}|hf_[A-Za-z0-9]{12,}|ghp_[A-Za-z0-9]{12,})")

def clean(t):
    t = re.sub(r"<system-reminder>.*?</system-reminder>", "", t, flags=re.S)
    t = SECRET.sub("[REDACTED-KEY]", t)
    if t.lstrip().startswith(("<bash-input>", "<bash-stdout>", "<bash-stderr>")):
        return ""
    return t.strip()

def text_of(content):
    if isinstance(content, str):
        return content
    out = []
    for c in content or []:
        if isinstance(c, dict):
            if c.get("type") == "text":
                out.append(c.get("text", ""))
            elif c.get("type") == "image":
                out.append("[image]")
    return "\n".join(out)

def extract(path, relevant_only=False):
    items = []
    seen = set()
    pending_q = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                d = json.loads(line)
            except Exception:
                continue
            ts = d.get("timestamp", "")
            typ = d.get("type")
            if d.get("isSidechain"):
                continue
            if typ == "user":
                msg = d.get("message", {})
                content = msg.get("content")
                origin = (d.get("origin") or {}).get("kind")
                if origin == "human":
                    t = clean(text_of(content))
                    if t and t not in seen:
                        seen.add(t)
                        items.append((ts, "OWNER", t))
                elif isinstance(content, list):
                    for c in content:
                        if c.get("type") == "tool_result" and c.get("tool_use_id") in pending_q:
                            q = pending_q.pop(c["tool_use_id"])
                            ans = c.get("content")
                            if isinstance(ans, list):
                                ans = text_of(ans)
                            items.append((ts, "ASK", q + "\n\n**回答:** " + clean(str(ans))))
                        elif c.get("type") == "tool_result" and str(c.get("tool_use_id","")).startswith("__never"):
                            pass
                # older format without origin: human typed str w/o meta
                elif origin is None and isinstance(content, str) and not d.get("isMeta") and not content.startswith(("<task-notification", "Another Claude session", "[Cross-session", "<command-", "Caveat:", "<local-command")):
                    if d.get("promptSource") in (None, "typed") and d.get("userType") == "external" and "toolUseResult" not in d:
                        t = clean(content)
                        if t and t not in seen and not t.startswith("This session is being continued"):
                            seen.add(t)
                            items.append((ts, "OWNER?", t))
            elif typ == "attachment":
                a = d.get("attachment", {})
                if a.get("type") == "queued_command" and (a.get("origin") or {}).get("kind") == "human":
                    p = a.get("prompt")
                    t = clean(text_of(p) if not isinstance(p, str) else p)
                    if t and t not in seen:
                        seen.add(t)
                        items.append((a.get("timestamp", ts), "OWNER(mid-turn)", t))
            elif typ == "assistant":
                for c in d.get("message", {}).get("content", []) or []:
                    if isinstance(c, dict) and c.get("type") == "tool_use" and c.get("name") == "AskUserQuestion":
                        qs = c.get("input", {}).get("questions", [])
                        lines = []
                        for q in qs:
                            lines.append("**问:** " + q.get("question", ""))
                            for o in q.get("options", []):
                                lines.append("  - " + o.get("label", "") + (" — " + o.get("description", "") if o.get("description") else ""))
                        pending_q[c.get("id")] = "\n".join(lines)
    return items

def main():
    out = sys.argv[1]
    files = sys.argv[2:]
    with open(out, "w", encoding="utf-8") as w:
        w.write("# 项目方原话提取（自动生成，tools/qa/extract_owner_messages.py）\n\n")
        for p in files:
            items = extract(p)
            if not items:
                continue
            w.write(f"\n\n## 会话 {p.split('/')[-1].split(chr(92))[-1]}（{len(items)} 条）\n")
            for ts, kind, t in items:
                w.write(f"\n### {ts} [{kind}]\n\n{t}\n")
            print(p, len(items))

if __name__ == "__main__":
    main()
