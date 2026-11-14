#!/usr/bin/env python3
"""تجربةُ قياس (ليست ميزة): القراءةُ الآليّة لكتابٍ مصوَّر بعدّة معالجاتٍ معًا، كم توفّر من الوقت؟ وهل يبقى النصُّ كما هو؟

    .venv\\Scripts\\python.exe tests\\trial_parallel_ocr.py "مسار\\كتاب مصوَّر.pdf"
    .venv\\Scripts\\python.exe tests\\trial_parallel_ocr.py "…pdf" --start 100 --pages 40 --workers 1,2,3,4,6,8 --save اسم

يقرأ الصفحاتِ نفسَها بقارئ «بُغية» نفسه (PdfBook.read: تصويرُ الصفحة ثمّ محرّكُ النظام ثمّ قسمةُ الصفحة) مرّةً في عمليّةٍ واحدة
كما يفعل البرنامج الآن، ثمّ بعددٍ من العمليّات كلٌّ منها تفتح الكتابَ وتقرأ نصيبَها. ويقارن نصَّ كلّ صفحةٍ بما خرج من العمليّة
الواحدة. ووقتُ تشغيل العمليّات يُذكر وحده، فهو يُدفع مرّةً للكتاب لا لكلّ صفحة.
لا يغيّر شيئًا في app، ولا يكتب نصَّ الكتاب في أيّ ملفّ: الأرقامُ وحدها.
"""
import argparse
import hashlib
import json
import multiprocessing as mp
import os
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent / "app"))
RESULTS = ROOT / "results"
_BOOK = None


def _open(path: str):
    global _BOOK
    from readers import open_book
    from readers.ocr import engine
    _BOOK = open_book(pathlib.Path(path), engine())


def _ready(_):
    return os.getpid()


def _read(i: int):
    pg = _BOOK.read(i)
    text = "\n".join(x for x in (pg["head"], pg["body"], pg["foot"]) if x)
    return i, pg["method"], hashlib.sha1(text.encode("utf-8")).hexdigest(), len(text.split())


def _split(i: int):
    """وقتُ الصفحة مقسومًا: التصويرُ، ثمّ المحرّك (في العمليّة الواحدة)."""
    import pymupdf as fitz
    from readers import pdf as rpdf
    page = _BOOK.doc[i]
    side = min(rpdf.OCR_LONG_SIDE, getattr(_BOOK.ocr, "max_side", None) or rpdf.OCR_LONG_SIDE)
    z = max(1.0, min(6.0, side / max(page.rect.width or 1, page.rect.height or 1)))
    t0 = time.perf_counter()
    png = page.get_pixmap(matrix=fitz.Matrix(z, z), colorspace=fitz.csGRAY, alpha=False).tobytes("png")
    t1 = time.perf_counter()
    _BOOK.ocr.recognize(png)
    return t1 - t0, time.perf_counter() - t1


def main() -> int:
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")
        except Exception:
            pass
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("--start", type=int, default=100, help="أوّلُ صفحةٍ (تبدأ من 1)")
    ap.add_argument("--pages", type=int, default=40)
    ap.add_argument("--workers", default="1,2,3,4,6,8")
    ap.add_argument("--save")
    a = ap.parse_args()
    _open(a.pdf)
    total = _BOOK.total
    idx = list(range(a.start - 1, min(total, a.start - 1 + a.pages)))
    print("الكتاب: %d صفحة · العيّنة: %d صفحة من %d · أنويةُ الجهاز المنطقيّة: %d" % (total, len(idx), a.start, os.cpu_count()))
    _read(idx[0])                                   # تسخين: أوّلُ نداءٍ للمحرّك أبطأ
    parts = [_split(i) for i in idx[:6]]
    render, recog = sum(p[0] for p in parts) / len(parts), sum(p[1] for p in parts) / len(parts)
    print("الصفحةُ الواحدة: التصوير %.2f ث · المحرّك %.2f ث" % (render, recog))
    t0 = time.perf_counter()
    base = [_read(i) for i in idx]
    t_one = time.perf_counter() - t0
    words = sum(r[3] for r in base)
    methods = sorted({r[1] for r in base})
    print("عمليّةٌ واحدة (البرنامج الآن): %.1f ث · %.2f ث للصفحة · %d كلمة · الطريقة: %s" % (t_one, t_one / len(idx), words, methods))
    ref = {r[0]: r[2] for r in base}
    rows = [{"workers": 0, "label": "الآن", "seconds": round(t_one, 2), "per_page": round(t_one / len(idx), 3)}]
    print("العمليّات | الوقت | للصفحة | النسبة إلى الواحدة | تشغيلُ العمليّات | صفحاتٌ تغيّر نصُّها")
    for k in [int(x) for x in a.workers.split(",")]:
        t0 = time.perf_counter()
        with mp.Pool(k, initializer=_open, initargs=(a.pdf,)) as pool:
            pool.map(_ready, range(k * 4), chunksize=1)          # حتّى تفتح كلُّ عمليّةٍ الكتاب
            t_up = time.perf_counter() - t0
            t1 = time.perf_counter()
            got = pool.map(_read, idx, chunksize=1)
            t = time.perf_counter() - t1
        diff = sum(1 for r in got if ref[r[0]] != r[2])
        rows.append({"workers": k, "seconds": round(t, 2), "per_page": round(t / len(idx), 3), "ratio": round(t / t_one, 3),
                     "startup": round(t_up, 2), "pages_changed": diff})
        print("%d | %.1f ث | %.2f ث | %.0f%% | %.1f ث | %d" % (k, t, t / len(idx), 100 * t / t_one, t_up, diff))
    if a.save:
        RESULTS.mkdir(exist_ok=True)
        (RESULTS / (a.save + ".json")).write_text(json.dumps({
            "date": time.strftime("%Y-%m-%d %H:%M"), "book_pages": total, "sample_pages": len(idx), "words": words,
            "logical_cpus": os.cpu_count(), "render_s": round(render, 3), "recognize_s": round(recog, 3), "runs": rows},
            ensure_ascii=False, indent=1), encoding="utf-8")
        print("حُفظ: tests/results/%s.json" % a.save)
    return 0


if __name__ == "__main__":
    sys.exit(main())
