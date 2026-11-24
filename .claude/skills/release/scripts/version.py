#!/usr/bin/env python3
"""رقمُ إصدار بُغية في مواضعه الثلاثة: يتحقّق من تطابقها، أو يضبطها معًا.

    python .claude/skills/release/scripts/version.py              يطبع الرقمَ في كلّ موضع، ويخرج بخطأ إن اختلفت
    python .claude/skills/release/scripts/version.py --set 0.9.7  يكتب الرقمَ الجديد في المواضع كلّها ثمّ يتحقّق

المواضع (ويفحصها release.yml نفسُه قبل البناء):
  app/common.py          VERSION = "X"
  installer/bughya.iss   #define AppVer "X"
  assets/version.txt     filevers و prodvers (أربعة أرقام) و FileVersion و ProductVersion
"""
import argparse
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[4]
FILES = {
    "common": ROOT / "app" / "common.py",
    "iss": ROOT / "installer" / "bughya.iss",
    "vinfo": ROOT / "assets" / "version.txt",
}
PAT = {
    "common": r'(VERSION\s*=\s*")([^"]+)(")',
    "iss": r'(#define AppVer ")([^"]+)(")',
    "file": r"('FileVersion', ')([^']+)(')",
    "product": r"('ProductVersion', ')([^']+)(')",
    "filevers": r"(filevers=\()([\d, ]+)(\))",
    "prodvers": r"(prodvers=\()([\d, ]+)(\))",
}
WHERE = {"common": "common", "iss": "iss", "file": "vinfo", "product": "vinfo", "filevers": "vinfo", "prodvers": "vinfo"}


def tuple_of(v: str) -> str:
    nums = [int(x) for x in re.findall(r"\d+", v.split("-")[0])][:4]
    return ", ".join(str(n) for n in nums + [0] * (4 - len(nums)))


def read() -> dict:
    out = {}
    for k, p in PAT.items():
        m = re.search(p, FILES[WHERE[k]].read_text(encoding="utf-8"))
        out[k] = m.group(2) if m else None
    return out


def check() -> int:
    v = read()
    base = v["common"]
    bad = []
    for k in ("iss", "file", "product"):
        if v[k] != base:
            bad.append(k)
    for k in ("filevers", "prodvers"):
        if v[k] is None or tuple_of(v[k]) != tuple_of(base or ""):
            bad.append(k)
    for k, val in v.items():
        print("%-9s %-22s %s%s" % (k, FILES[WHERE[k]].relative_to(ROOT).as_posix(), val, "   ✗" if k in bad else ""))
    if bad:
        print("لا يتطابق: " + "، ".join(bad))
        return 1
    print("متطابق: " + base)
    return 0


def set_version(new: str) -> None:
    if not re.fullmatch(r"\d+\.\d+\.\d+", new):
        sys.exit("الرقم بصيغة 0.9.7 (والتجريبيّ يُعرف بالوسم v0.9.7-beta1، لا بالرقم)")
    texts = {f: p.read_bytes().decode("utf-8") for f, p in FILES.items()}   # كما هو: علامةُ BOM ونهاياتُ الأسطر
    for k, p in PAT.items():
        val = tuple_of(new) if k in ("filevers", "prodvers") else new
        texts[WHERE[k]], n = re.subn(p, lambda m: m.group(1) + val + m.group(3), texts[WHERE[k]], count=1)
        if not n:
            sys.exit("لم يوجد %s في %s" % (k, FILES[WHERE[k]]))
    for f, p in FILES.items():
        p.write_bytes(texts[f].encode("utf-8"))


def main() -> int:
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")
        except Exception:
            pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--set")
    a = ap.parse_args()
    if a.set:
        set_version(a.set)
    return check()


if __name__ == "__main__":
    sys.exit(main())
