#!/usr/bin/env python3
"""قياسُ دقة الاستخراج على صفحات المرجع (tests/gold): نسبةُ الخطأ في الحروف (CER) والكلمات (WER) لكل صفحة وللمجموع.

    .venv\\Scripts\\python.exe tests\\measure.py                 يقيس ويطبع
    .venv\\Scripts\\python.exe tests\\measure.py --save اسم       ويحفظ النتيجة في tests/results/اسم.json
    .venv\\Scripts\\python.exe tests\\measure.py --diff اسم      ويقارن بنتيجةٍ محفوظة

يقرأ كلَّ صفحةٍ بقارئ «بُغية» نفسه (readers.open_book)، فيقيس ما يحفظه البرنامج فعلًا: الرأس والمتن والحاشية.
والمقارنةُ بعد حذف الحركات والتطويل وعلامات الترقيم فقط، فلا تُحسب الهمزة أو الياء أو التاء المربوطة خطأً مغفورًا.
ويحتاج مكتبة jiwer (للقياس وحده، لا تدخل في البرنامج): pip install jiwer
"""
import argparse
import json
import pathlib
import re
import sys
import time
import unicodedata

ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent / "app"))
import jiwer  # noqa: E402

GOLD = ROOT / "gold"
RESULTS = ROOT / "results"
MARKS = re.compile("[ً-ْٰـۖ-ۭ]")
PUNCT = re.compile(r"[«»\"'“”{}\[\]()﴿﴾،؛:.!؟,;*\-ـ]")


def clean(t: str) -> str:
    t = unicodedata.normalize("NFC", t)
    t = MARKS.sub("", t)
    t = PUNCT.sub(" ", t)
    return re.sub(r"\s+", " ", t).strip()


def extract(pdf: pathlib.Path) -> tuple:
    from readers import open_book
    from readers.ocr import engine
    book = open_book(pdf, engine())
    try:
        pg = next(book.pages(1))
        method = pg["method"] + (" (نص الملف معيب)" if getattr(book, "force_ocr", False) else "")
        return "\n".join(x for x in (pg["head"], pg["body"], pg["foot"]) if x), method
    finally:
        book.close()


def main() -> int:
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")
        except Exception:
            pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--save")
    ap.add_argument("--diff")
    a = ap.parse_args()
    meta = {m["id"]: m for m in json.loads((GOLD / "pages.json").read_text(encoding="utf-8"))}
    rows, refs, hyps = [], [], []
    for gid, m in meta.items():
        ref_f = GOLD / (gid + ".txt")
        if not ref_f.exists():
            continue
        ref, (hyp, method) = clean(ref_f.read_text(encoding="utf-8")), extract(GOLD / (gid + ".pdf"))
        hyp = clean(hyp)
        refs.append(ref)
        hyps.append(hyp)
        rows.append({"id": gid, "kind": m["kind"], "category": m.get("category", "modern_print"), "method": method,
                     "cer": round(jiwer.cer(ref, hyp), 4), "wer": round(jiwer.wer(ref, hyp), 4),
                     "words": len(ref.split())})
    total = {"cer": round(jiwer.cer(refs, hyps), 4), "wer": round(jiwer.wer(refs, hyps), 4),
             "words": sum(r["words"] for r in rows)}
    cats = {}
    for r, rf, hp in zip(rows, refs, hyps):                  # كلُّ فئةٍ وحدها، كيلا يخفي المتوسطُ ضعفَ الكتب القديمة
        c = cats.setdefault(r["category"], [[], []])
        c[0].append(rf); c[1].append(hp)
    total["categories"] = {k: {"cer": round(jiwer.cer(v[0], v[1]), 4), "wer": round(jiwer.wer(v[0], v[1]), 4),
                               "pages": len(v[0])} for k, v in cats.items()}
    old = None
    if a.diff:
        old = json.loads((RESULTS / (a.diff + ".json")).read_text(encoding="utf-8"))
        old_rows = {r["id"]: r for r in old["pages"]}
    print("الصفحة | النوع | طريقة القراءة | خطأ الحروف | خطأ الكلمات" + (" | الفرق في الكلمات" if old else ""))
    for r in rows:
        line = "%s | %s | %s | %.1f%% | %.1f%%" % (r["id"], r["kind"], r["method"], 100 * r["cer"], 100 * r["wer"])
        if old and r["id"] in old_rows:
            line += " | %+.1f" % (100 * (r["wer"] - old_rows[r["id"]]["wer"]))
        print(line)
    print("المجموع (%d كلمة) | خطأ الحروف %.1f%% | خطأ الكلمات %.1f%%" % (total["words"], 100 * total["cer"], 100 * total["wer"])
          + (" | كان %.1f%% و%.1f%%" % (100 * old["total"]["cer"], 100 * old["total"]["wer"]) if old else ""))
    names = {"modern_print": "طبعات حديثة", "old_print": "طبعات قديمة", "lithograph": "طبعات حجرية", "manuscript": "مخطوطات"}
    for k, v in total["categories"].items():
        print("  %s (%d صفحات) | خطأ الحروف %.1f%% | خطأ الكلمات %.1f%%" % (names.get(k, k), v["pages"], 100 * v["cer"], 100 * v["wer"]))
    if a.save:
        RESULTS.mkdir(exist_ok=True)
        (RESULTS / (a.save + ".json")).write_text(json.dumps({"date": time.strftime("%Y-%m-%d %H:%M"), "pages": rows,
                                                               "total": total}, ensure_ascii=False, indent=1),
                                                  encoding="utf-8")
        print("حُفظ: tests/results/%s.json" % a.save)
    return 0


if __name__ == "__main__":
    sys.exit(main())
