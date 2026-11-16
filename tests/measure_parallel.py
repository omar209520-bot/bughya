#!/usr/bin/env python3
r"""قياسُ القراءة الآليّة بعدّة عمليّات (readers/parallel.py) على كتابٍ مصوَّر كامل: الوقتُ، ومطابقةُ النصّ صفحةً صفحة.

    .venv\Scripts\python.exe tests\measure_parallel.py "مسار\كتاب مصوَّر.pdf"                  الكتابُ كلُّه
    .venv\Scripts\python.exe tests\measure_parallel.py "…pdf" --pages 60 --save اسم             أوّلُ ستّين صفحة، وتُحفظ الأرقام

يقرأ الكتابَ بقارئ «بُغية» (book.pages) مرّةً بعمليّةٍ واحدة (BUGHYA_OCR_WORKERS=1، وهو ما كان قبل هذه الميزة) ومرّةً بالعدد
التلقائيّ، ويقابل كلَّ صفحةٍ بأختها: الرقمُ والطريقةُ والرأسُ والمتنُ والحاشيةُ والرقمُ المطبوع. لا يكتب نصَّ الكتاب في أيّ ملفّ.
"""
import argparse
import hashlib
import json
import os
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent / "app"))


def run(pdf, limit, n_workers):
    from readers import open_book, parallel
    from readers.ocr import engine
    if n_workers:
        os.environ[parallel.ENV] = str(n_workers)
    else:
        os.environ.pop(parallel.ENV, None)
    book = open_book(pathlib.Path(pdf), engine())
    out, t0 = [], time.perf_counter()
    try:
        used = min(parallel.workers(), max(1, book.total // 2)) if book.scanned_guess else 1
        for pg in book.pages(1):
            key = json.dumps([pg[k] for k in ("n", "method", "head", "body", "foot", "printed", "weak")], ensure_ascii=False)
            out.append((pg["n"], pg["method"], hashlib.sha1(key.encode("utf-8")).hexdigest()))
            if limit and len(out) >= limit:
                break
    finally:
        book.close()
    return out, time.perf_counter() - t0, used


def main() -> int:
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")
        except Exception:
            pass
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("--pages", type=int, default=0, help="أوّلُ كذا صفحة (الأصل: الكتابُ كلُّه)")
    ap.add_argument("--save")
    a = ap.parse_args()
    many, t_many, used = run(a.pdf, a.pages, 0)
    print("بعدّة عمليّات (%d): %d صفحة في %.1f ث · %.2f ث للصفحة" % (used, len(many), t_many, t_many / max(1, len(many))), flush=True)
    one, t_one, _ = run(a.pdf, a.pages, 1)
    print("بعمليّةٍ واحدة: %d صفحة في %.1f ث · %.2f ث للصفحة" % (len(one), t_one, t_one / max(1, len(one))))
    order = [r[0] for r in many] == list(range(1, len(many) + 1))
    diff = sum(1 for x, y in zip(one, many) if x != y) + abs(len(one) - len(many))
    ocr_n = sum(1 for r in one if r[1] == "ocr")
    print("النسبة: %.0f%% من وقت الواحدة · الترتيب %s · صفحاتٌ اختلفت: %d · المقروءُ آليًّا: %d" % (
        100 * t_many / t_one, "سليم" if order else "مختلّ", diff, ocr_n))
    if a.save:
        res = ROOT / "results"
        res.mkdir(exist_ok=True)
        (res / (a.save + ".json")).write_text(json.dumps({
            "date": time.strftime("%Y-%m-%d %H:%M"), "pages": len(one), "ocr_pages": ocr_n, "workers": used,
            "logical_cpus": os.cpu_count(), "seconds_one": round(t_one, 1), "seconds_many": round(t_many, 1),
            "ratio": round(t_many / t_one, 3), "order_ok": order, "pages_changed": diff}, ensure_ascii=False, indent=1),
            encoding="utf-8")
        print("حُفظ: tests/results/%s.json" % a.save)
    return 0 if order and not diff else 1


if __name__ == "__main__":
    sys.exit(main())
