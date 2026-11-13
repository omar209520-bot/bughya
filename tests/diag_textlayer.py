#!/usr/bin/env python3
"""تشخيصُ النصّ المضمَّن في ملفّ بي دي إف: لماذا عدّه البرنامج معيبًا فقرأ صفحاتِه آليًّا؟

    .venv\\Scripts\\python.exe tests\\diag_textlayer.py "مسار\\الملف.pdf"
    .venv\\Scripts\\python.exe tests\\diag_textlayer.py "مسار\\الملف.pdf" --pages 10,200     صفحاتٌ بعينها (الأصل: أربعٌ متباعدة)

يكتب الناتج في tests/results/diag-اسم الملف.txt (بترميز UTF-8؛ افتحه بالمفكّرة). وفيه لكلّ صفحة:
  - خطوطُها، وعددُ حروفها، وما فيها من حروفٍ بلا مقابل (U+FFFD) أو من المنطقة الخاصّة أو من صور العرض؛
  - الصيغةُ التي اختارها القارئ لبناء السطر، وأوّلُ أسطر النصّ المضمَّن كما يستخرجه البرنامج؛
  - أوّلُ أسطر القراءة الآليّة للصورة نفسها (في ويندوز)، ونسبةُ توافق النصّين؛
  - كلماتُ النصّ المضمَّن التي لم تقرأها الآلة، وبجانب كلٍّ أقربُ كلمةٍ قرأتها: من مقابلتهما يظهر نوعُ العيب.
تنبيه: في الناتج مقاطعُ من نصّ الملفّ، فلا تُرسله إن كان النصّ خاصًّا.
"""
import argparse
import collections
import difflib
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent / "app"))


def main() -> int:
    ap = argparse.ArgumentParser(description="تشخيصُ النصّ المضمَّن في ملفّ بي دي إف")
    ap.add_argument("pdf")
    ap.add_argument("--pages", help="أرقامُ صفحاتٍ بينها فاصلة (تبدأ من 1)")
    ap.add_argument("--lines", type=int, default=8, help="عددُ الأسطر المعروضة من كلّ نصّ (8)")
    a = ap.parse_args()
    import arabic
    import pymupdf as fitz
    from readers import pdf as rpdf
    from readers.arabic_pdf import best_lines, sample_bias
    from readers.ocr import engine
    path = pathlib.Path(a.pdf)
    doc = fitz.open(str(path))
    eng = engine()
    out = []
    P = out.append
    md = doc.metadata or {}
    P("الملفّ: %s" % path.name)
    P("الصفحات: %d · المنتِج: %s · الصانع: %s" % (doc.page_count, md.get("producer"), md.get("creator")))
    P("القراءةُ الآليّة: %s" % (eng.name if eng.ok else "لا تعمل هنا (%s)" % eng.reason))
    bias = sample_bias(doc, fitz, doc.page_count)
    P("ميلُ الكتاب إلى صيغ بناء السطر (كما هو، مبنيّ، مبنيّ بعكس المركّبات): %s" % (bias,))
    if a.pages:
        idx = [int(x) - 1 for x in a.pages.split(",") if x.strip()]
    else:
        idx = sorted({min(doc.page_count - 1, int(doc.page_count * f)) for f in (0.2, 0.4, 0.6, 0.8)})
    scores = []
    for i in idx:
        page = doc[i]
        P("\n" + "═" * 70)
        P("الصفحة %d" % (i + 1))
        for f in page.get_fonts(full=True):
            P("  خطّ: %s · النوع %s · الترميز %s" % (f[3], f[2], f[5]))
        kinds = collections.Counter()
        odd = collections.Counter()
        for b in page.get_text("rawdict").get("blocks", []):
            for l in b.get("lines", []):
                for s in l.get("spans", []):
                    for c in s.get("chars", []):
                        ch = c["c"]
                        o = ord(ch[0]) if ch else 0
                        k = ("بلا مقابل (FFFD)" if o == 0xFFFD else "منطقةٌ خاصّة" if 0xE000 <= o <= 0xF8FF
                             else "صورةُ عرض" if 0xFB50 <= o <= 0xFEFF else "عربيّ" if 0x600 <= o <= 0x6FF
                             else "مسافة" if ch.isspace() else "غيره")
                        kinds[k] += 1
                        if k in ("بلا مقابل (FFFD)", "منطقةٌ خاصّة", "صورةُ عرض"):
                            odd["U+%04X %s" % (o, s.get("font", ""))] += 1
        P("  الحروف: " + " · ".join("%s %d" % kv for kv in kinds.most_common()))
        if odd:
            P("  الغريبُ منها: " + " · ".join("%s ×%d" % kv for kv in odd.most_common(15)))
        t0 = time.time()
        lines, variant = best_lines(page, fitz, bias)
        P("  صيغةُ بناء السطر المختارة: %s (%.2f ث)" % (variant, time.time() - t0))
        P("  ── النصّ المضمَّن كما يستخرجه البرنامج:")
        for l in lines[:a.lines]:
            P("     " + l["t"])
        P("  ── النصّ المضمَّن كما تعطيه المكتبة بلا بناء:")
        for l in page.get_text("text").splitlines()[:a.lines]:
            P("     " + l)
        mine = [w for w in arabic.normalize(" ".join(l["t"] for l in lines)).split() if len(w) > 1]
        if not eng.ok:
            continue
        W, H = page.rect.width or 1, page.rect.height or 1
        side = min(rpdf.OCR_LONG_SIDE, getattr(eng, "max_side", None) or rpdf.OCR_LONG_SIDE)
        z = max(1.0, min(6.0, side / max(W, H)))
        t0 = time.time()
        pix = page.get_pixmap(matrix=fitz.Matrix(z, z), colorspace=fitz.csGRAY, alpha=False)
        t1 = time.time()
        png = pix.tobytes("png")
        t2 = time.time()
        got = eng.recognize(png)
        t3 = time.time()
        P("  ── القراءةُ الآليّة (صورة %d×%d: رسمٌ %.2f ث، ضغطٌ %.2f ث، قراءةٌ %.2f ث):"
          % (pix.width, pix.height, t1 - t0, t2 - t1, t3 - t2))
        for g in got[:a.lines]:
            P("     " + g["text"])
        theirs = sorted({w for g in got for w in arabic.normalize(g["text"]).split() if len(w) > 1})
        tset = set(theirs)
        miss = [w for w in mine if w not in tset]
        sc = 1 - len(miss) / len(mine) if mine else None
        if sc is not None:
            scores.append(sc)
            P("  التوافق: %d من %d كلمة (%.0f٪) — دون %.0f٪ يُعدّ النصّ معيبًا"
              % (len(mine) - len(miss), len(mine), 100 * sc, 100 * rpdf.TEXT_LAYER_MIN))
        P("  ── كلماتٌ في النصّ المضمَّن لم تقرأها الآلة ← أقربُ ما قرأته:")
        seen = set()
        for w in miss:
            if w in seen or len(seen) >= 60:
                continue
            seen.add(w)
            near = difflib.get_close_matches(w, theirs, n=1, cutoff=0.5)
            P("     %s ← %s" % (w, near[0] if near else "—"))
    if scores:
        P("\nمتوسّطُ التوافق: %.0f٪" % (100 * sum(scores) / len(scores)))
    res = ROOT / "results"
    res.mkdir(exist_ok=True)
    f = res / ("diag-%s.txt" % path.stem)
    f.write_text("\n".join(out), encoding="utf-8")
    print("Saved: %s" % f)
    return 0


if __name__ == "__main__":
    sys.exit(main())
