"""known_hosts 补登记（W21 NETFIX-BULK 11-03，运维 FONG-QUICK：不关指纹校验；REMOTE HOST IDENTIFICATION HAS CHANGED 就停）。

只许用 `ssh-keyscan -t <type> <host>` 的输出，且指纹必须与登记的一致才写；不一致 → 返回 P0、不写一个字节。
    python tools/netfix/hostkey.py --host 47.243.63.181 --type ed25519 --expect SHA256:IrIRIa+ucfx1CxhkWG4lEsDI58vb1EZ03/rOR7uPHtY [--dry]
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
KNOWN = ROOT / "config/netfix/known_hosts"


def fingerprint(key_b64: str) -> str:
    """OpenSSH 的 SHA256 指纹（= ssh-keygen -lf）：sha256(公钥 blob) 的 base64、去掉尾部 '='"""
    return "SHA256:" + base64.b64encode(hashlib.sha256(base64.b64decode(key_b64)).digest()).decode().rstrip("=")


def parse_scan(text: str, host: str, ktype: str) -> list[tuple[str, str]]:
    """keyscan 输出里 host 的 ktype 行 → [(整行, 指纹)]"""
    want = ktype if ktype.startswith(("ssh-", "ecdsa-")) else f"ssh-{ktype}"
    out = []
    for ln in (text or "").splitlines():
        p = ln.split()
        if len(p) >= 3 and not ln.startswith("#") and p[0] == host and p[1] == want:
            try:
                out.append((" ".join(p[:3]), fingerprint(p[2])))
            except ValueError:
                continue
    return out


def verify_and_add(host: str, ktype: str, expect: str, scan_text: str, known: Path = KNOWN, dry: bool = False) -> dict:
    """→ {ok, action: added|already_present|refused, why, fingerprints}；refused 时 level=P0，known_hosts 不动"""
    got = parse_scan(scan_text, host, ktype)
    fps = [fp for _, fp in got]
    if not got:
        return {"ok": False, "action": "refused", "level": "P0", "why": f"keyscan 没拿到 {host} 的 {ktype} 公钥", "fingerprints": fps}
    if any(fp != expect for fp in fps):
        return {"ok": False, "action": "refused", "level": "P0",
                "why": f"指纹不一致：keyscan {fps} ≠ 登记 {expect}，不写 known_hosts，找运维核对", "fingerprints": fps}
    line = got[0][0]
    cur = known.read_text(encoding="utf-8") if known.exists() else ""
    if line in [" ".join(x.split()[:3]) for x in cur.splitlines()]:
        return {"ok": True, "action": "already_present", "why": "同一公钥已在 known_hosts", "fingerprints": fps}
    if not dry:
        with open(known, "a", encoding="utf-8", newline="\n") as f:
            f.write(("" if not cur or cur.endswith("\n") else "\n") + line + "\n")
    return {"ok": True, "action": "added" if not dry else "would_add", "why": "指纹与登记一致", "fingerprints": fps}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", required=True)
    ap.add_argument("--type", default="ed25519")
    ap.add_argument("--expect", required=True)
    ap.add_argument("--known", default=str(KNOWN))
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args(argv)
    r = subprocess.run(["ssh-keyscan", "-T", "30", "-t", a.type, a.host], capture_output=True, text=True, timeout=60)
    res = verify_and_add(a.host, a.type, a.expect, r.stdout, Path(a.known), a.dry)
    res["keyscan"] = r.stdout.strip()
    print(json.dumps(res, ensure_ascii=False, indent=1))
    return 0 if res["ok"] else 2


if __name__ == "__main__":
    sys.exit(main())
