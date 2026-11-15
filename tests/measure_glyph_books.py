#!/usr/bin/env python3
r"""قياسُ طريق «حرف الرمز من الخطّ المضمَّن» على كتبٍ كاملة من مكتبة المستخدم (قراءةٌ فقط، لا يكتب في المكتبة).

    .venv\Scripts\python.exe tests\measure_glyph_books.py --save اسم            الكتبُ المعيبُ نصُّها، ثمّ السليمة
    .venv\Scripts\python.exe tests\measure_glyph_books.py --only bad|sound       قسمٌ واحد
    .venv\Scripts\python.exe tests\measure_glyph_books.py --extra "مجلّد"         مجلّدُ كتبٍ آخر تُضاف ملفّاتُه النصّيّة إلى فحص السليمة

١) الكتبُ التي عدّها البرنامجُ «نصُّها معيب» (في hints ملاحظةُ القراءة الآليّة): لكلّ كتابٍ عيّنةٌ من ثماني صفحات، منها الأربعُ
   التي يقيس عليها البرنامج (_text_layer_score). تُقرأ صورةُ كلّ صفحةٍ آليًّا مرّةً واحدة، ثمّ يُحسب توافقُ نصّ الملفّ معها:
   كما هو، وبجدول الخطّ المضمَّن وحده، وبه مع الخطّ المثبَّت. والحدُّ 0.88: ما عبره قرأه البرنامج من نصّه.
٢) الكتبُ النصّيّة السليمة: هل يمسّ الشرطُ خطًّا فيها؟ يجب ألّا يمسّ. وإن مسّ قيس توافقُها قبل وبعد.
التوافقُ مقياسٌ تقريبيّ: القراءةُ الآليّة نفسُها تخطئ، ولا يكشف نصًّا ساقطًا. يصلح للحدّ لا لإثبات الدقّة.
لا يُكتب اسمُ كتابٍ ولا نصُّه: رقمُ الكتاب في المكتبة والأرقامُ وأسماءُ الخطوط وحدها.
"""
import argparse
import json
import os
import pathlib
import sqlite3
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent / "app"))
sys.path.insert(0, str(ROOT))
import pymupdf as fitz  # noqa: E402
import arabic  # noqa: E402
import trial_glyph_shape as T  # noqa: E402
from readers import pdf as rpdf  # noqa: E402
from readers.arabic_pdf import best_lines, sample_bias  # noqa: E402
from readers.ocr import engine  # noqa: E402

PROGRAM = (0.2, 0.4, 0.6, 0.8)                  # صفحاتُ _text_layer_score
MORE = (0.1, 0.3, 0.5, 0.7)
MODES = ("كما هو", "المضمَّن", "كلاهما")


def library():
    db = pathlib.Path(os.environ.get("BUGHYA_HOME") or pathlib.Path(os.environ["LOCALAPPDATA"]) / "Bughya") / "store" / "store.db"
    con = sqlite3.connect("file:%s?mode=ro" % db.as_posix(), uri=True)
    con.row_factory = sqlite3.Row
    rows = [r for r in con.execute("SELECT id, path, kind, state, pages, ocr_pages, hints FROM books") if r["kind"] == "pdf"
            and os.path.exists(r["path"])]
    bad = [r for r in rows if r["hints"] and "معيب" in r["hints"]]
    sound = [r for r in rows if r not in bad and r["state"] == "done" and (r["ocr_pages"] or 0) < (r["pages"] or 0) / 2]
    return bad, sound


def ocr_words(page, eng):
    W, H = page.rect.width or 1, page.rect.height or 1
    side = min(rpdf.OCR_LONG_SIDE, getattr(eng, "max_side", None) or rpdf.OCR_LONG_SIDE)
    z = max(1.0, min(6.0, side / max(W, H)))
    pix = page.get_pixmap(matrix=fitz.Matrix(z, z), colorspace=fitz.csGRAY, alpha=False)
    return {w for g in eng.recognize(pix.tobytes("png")) for w in arabic.normalize(g["text"]).split() if len(w) > 1}


def opened(path, mode):
    """الملفُّ مفتوحًا وخريطتُه مُصلَحةٌ بالطريق mode (في الذاكرة)، وإحصاءُ خطوطه."""
    doc = fitz.open(str(path))
    del T.STATS[:]
    if mode != "كما هو":
        T.make_repair(mode)(doc)
    return doc, [dict(s) for s in T.STATS]


def scores(path, eng):
    """{الطريق: {رقم الصفحة: التوافق}} على عيّنة الصفحات، وإحصاءُ الخطوط، وما بقي من رموزٍ بلا حرف."""
    doc = fitz.open(str(path))
    total = doc.page_count
    idx = {f: min(total - 1, int(total * f)) for f in PROGRAM + MORE}
    pages = sorted(set(idx.values()))
    theirs = {}
    for i in pages:
        try:
            theirs[i] = ocr_words(doc[i], eng)
        except Exception:
            pass
    doc.close()
    out, fonts, unknown = {}, [], None
    for mode in MODES:
        doc, st = opened(path, mode)
        bias = sample_bias(doc, fitz, total)
        res = {}
        for i in pages:
            if i not in theirs:
                continue
            lines, _ = best_lines(doc[i], fitz, bias)
            mine = [w for w in arabic.normalize(" ".join(l["t"] for l in lines)).split() if len(w) > 1]
            if len(mine) >= 30:
                res[i] = sum(1 for w in mine if w in theirs[i]) / len(mine)
        out[mode] = res
        if mode == "كلاهما":
            fonts = st
            chars = bad = 0             # حروفُ العيّنة، وما بقي منها بلا مقابلٍ في الخريطة (U+FFFD)
            for i in pages:
                for sp in doc[i].get_texttrace():
                    for u, g, o, b in sp["chars"]:
                        chars += 1
                        bad += u == 0xFFFD
            unknown = {"chars": chars, "no_letter": bad}
        doc.close()
    prog = sorted({idx[f] for f in PROGRAM})
    summ = {}
    for mode in MODES:
        p4 = [out[mode][i] for i in prog if i in out[mode]]
        p8 = list(out[mode].values())
        summ[mode] = {"program": round(sum(p4) / len(p4), 3) if p4 else None, "all": round(sum(p8) / len(p8), 3) if p8 else None,
                      "pages": len(p8)}
    return summ, fonts, unknown


def font_row(s):
    return {k: v for k, v in s.items() if not k.startswith("_") and k != "mode"}


def main() -> int:
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")
        except Exception:
            pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", choices=("bad", "sound"))
    ap.add_argument("--extra", action="append", default=[])
    ap.add_argument("--save")
    a = ap.parse_args()
    eng = engine()
    bad, sound = library()
    res = {"date": time.strftime("%Y-%m-%d %H:%M"), "threshold": rpdf.TEXT_LAYER_MIN, "bad": [], "sound": []}
    if a.only != "sound":
        print("الكتاب | الصفحات | التوافق كما هو | بالمضمَّن | بكليهما | يعبر %.2f؟ | الخطوطُ التي مُسّت (المثبَّت؟)" % rpdf.TEXT_LAYER_MIN)
        for r in bad:
            t0 = time.time()
            try:
                summ, fonts, unknown = scores(r["path"], eng)
            except Exception as e:
                print("%d | تعذّر: %r" % (r["id"], e))
                res["bad"].append({"id": r["id"], "error": repr(e)})
                continue
            touched = [f for f in fonts if f.get("changed")]
            names = "، ".join("%s (%s)" % (f["font"], "مثبَّتٌ مطابق" if f.get("outlines_drawn") and f.get("outlines_same") == f.get("outlines_drawn")
                                           else "مثبَّتٌ يخالف" if f.get("installed") else "غير مثبَّت") for f in touched) or "لم يُمسّ خطّ"
            g = lambda m: "—" if summ[m]["program"] is None else "%.2f" % summ[m]["program"]
            def cross(m):
                return summ[m]["program"] is not None and summ[m]["program"] >= rpdf.TEXT_LAYER_MIN
            print("%d | %d | %s | %s | %s | %s | %s" % (r["id"], r["pages"], g("كما هو"), g("المضمَّن"), g("كلاهما"),
                                                       "نعم" if cross("كلاهما") else "لا", names), flush=True)
            res["bad"].append({"id": r["id"], "pages": r["pages"], "scores": summ, "crosses_embedded": cross("المضمَّن"),
                               "crosses_both": cross("كلاهما"), "fonts": [font_row(f) for f in fonts], "sample": unknown,
                               "seconds": round(time.time() - t0, 1)})
    if a.only != "bad":
        files = [(r["id"], r["path"]) for r in sound]
        for d in a.extra:
            for p in sorted(pathlib.Path(d).rglob("*.pdf")):
                files.append(("+", str(p)))
        print("\nالكتبُ النصّيّة السليمة: %d ملفًّا" % len(files))
        hit = 0
        for bid, path in files:
            try:
                doc = fitz.open(path)
                n = doc.page_count
                letters = sum(sum(1 for c in doc[i].get_text("text") if c.isalpha()) for i in sorted({min(n - 1, int(n * f)) for f in PROGRAM}))
                doc.close()
                if bid == "+" and letters < 4 * rpdf.MIN_LETTERS:
                    continue                                    # مصوَّر: ليس من هذا الفحص
                doc, st = opened(path, "كلاهما")
                doc.close()
            except Exception as e:
                res["sound"].append({"id": bid, "error": repr(e)})
                continue
            touched = [font_row(f) for f in st if f.get("changed")]
            row = {"id": bid, "pages": n, "fonts": len(st), "touched": touched}
            if touched:
                hit += 1
                try:
                    summ, _, _ = scores(path, eng)
                    row["scores"] = summ
                except Exception as e:
                    row["scores_error"] = repr(e)
                print("  مُسّ كتابٌ سليم (%s، %d صفحة): %s | التوافق قبل %s وبعد %s" % (
                    bid, n, "، ".join("%s: %d حرفًا مسافة" % (f["font"], f.get("letters_as_space", 0)) for f in touched),
                    row.get("scores", {}).get("كما هو", {}).get("all"), row.get("scores", {}).get("كلاهما", {}).get("all")), flush=True)
            res["sound"].append(row)
        print("فُحص %d ملفًّا نصّيًّا سليمًا، ومُسّ منها %d." % (len(res["sound"]), hit))
    if a.save:
        (ROOT / "results" / (a.save + ".json")).write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
        print("حُفظ: tests/results/%s.json" % a.save)
    return 0


if __name__ == "__main__":
    sys.exit(main())
