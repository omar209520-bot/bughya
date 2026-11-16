#!/usr/bin/env python3
r"""قياسٌ لحكم القراءة (نصُّ الملفّ أم القراءةُ الآليّة) صفحةً صفحة، على كتب مكتبة المستخدم (قراءةٌ فقط، لا يكتب فيها).

    .venv\Scripts\python.exe tests\measure_page_decision.py --save اسم

لكلّ كتابٍ بي دي إف نصّيٍّ أو معيبٍ نصُّه، ثماني صفحاتٍ متباعدة (منها الأربعُ التي يقيس عليها البرنامج). لكلّ صفحة:
  - أهي صفحةٌ مصوَّرة: صورةٌ تغطّي أكثرَ الصفحة، ونصُّها خفيٌّ (طبقةُ قراءةٍ آليّةٍ قديمة) أو غيرُ عربيّ؛
  - أيقرؤها البرنامج آليًّا وحدها الآن (حروفٌ قليلة أو نصٌّ فاسد)؛
  - توافقُ نصّها مع القراءة الآليّة لصورتها: بالكلمة (كما يقيس البرنامج)، وبالرسم المجرّد (يغفر خطأ النقاط في القراءة الآليّة).
ثمّ لكلّ كتاب: حكمُ البرنامج الآن، وحكمُه لو قيس على صفحاته النصّيّة وحدها.
لا يُكتب اسمُ كتابٍ ولا نصُّه: رقمُه في المكتبة والأرقامُ وحدها.
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
import pymupdf as fitz  # noqa: E402
import arabic  # noqa: E402
from readers import glyphmap, pdf as rpdf  # noqa: E402
from readers.arabic_pdf import best_lines, sample_bias  # noqa: E402
from readers.ocr import engine  # noqa: E402

PROGRAM = (0.2, 0.4, 0.6, 0.8)
MORE = (0.1, 0.3, 0.5, 0.7)


def books():
    db = pathlib.Path(os.environ.get("BUGHYA_HOME") or pathlib.Path(os.environ["LOCALAPPDATA"]) / "Bughya") / "store" / "store.db"
    con = sqlite3.connect("file:%s?mode=ro" % db.as_posix(), uri=True)
    con.row_factory = sqlite3.Row
    out = []
    for r in con.execute("SELECT id, path, kind, state, pages, ocr_pages, hints FROM books WHERE kind = 'pdf' AND state = 'done'"):
        if not os.path.exists(r["path"]):
            continue
        bad = bool(r["hints"] and "معيب" in r["hints"])
        textual = (r["ocr_pages"] or 0) < (r["pages"] or 0) / 2
        if bad or textual:
            out.append((r["id"], r["path"], "معيب" if bad else "نصّي"))
    return out


def image_page(page) -> dict:
    """صورةٌ تغطّي أكثرَ الصفحة؟ وكم من حروف نصّها خفيّ (طبقةُ قراءةٍ آليّة)، وكم منها عربيّ؟"""
    area = abs(page.rect) or 1
    cover = 0.0
    try:
        for im in page.get_image_info():
            r = fitz.Rect(im["bbox"]) & page.rect
            cover = max(cover, abs(r) / area)
    except Exception:
        pass
    chars = hidden = arab = 0
    try:
        for sp in page.get_texttrace():
            for u, g, o, b in sp["chars"]:
                c = chr(u) if u > 0 else ""
                if not c.strip():
                    continue
                chars += 1
                hidden += sp.get("type") == 3 or sp.get("opacity", 1) == 0
                arab += "؀" <= c <= "ۿ" or "ﭐ" <= c <= "﻿"
    except Exception:
        pass
    return {"cover": round(cover, 2), "hidden": round(hidden / chars, 2) if chars else 0.0,
            "arabic": round(arab / chars, 2) if chars else 0.0, "chars": chars}


def main() -> int:
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")
        except Exception:
            pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--save")
    a = ap.parse_args()
    eng = engine()
    rows = []
    print("الكتاب | النوع | الصفحات | البرنامج الآن | على النصّيّة وحدها (كلمة · رسم) | صفحاتٌ مصوَّرةٌ في العيّنة")
    for bid, path, kind in books():
        doc = fitz.open(path)
        glyphmap.repair(doc)
        n = doc.page_count
        bias = sample_bias(doc, fitz, n)
        pages = []
        for f in PROGRAM + MORE:
            i = min(n - 1, int(n * f))
            if any(p["i"] == i for p in pages):
                continue
            page = doc[i]
            lines, _ = best_lines(page, fitz, list(bias))
            raw = "\n".join(l["t"] for l in lines)
            q = arabic.quality(raw)
            per_page_ocr = q["letters"] < rpdf.MIN_LETTERS or arabic.is_garbage(q)
            info = image_page(page)
            mine = [w for w in arabic.normalize(raw).split() if len(w) > 1]
            row = {"i": i, "program": f in PROGRAM, "per_page_ocr": per_page_ocr, "words": len(mine), **info}
            if len(mine) >= 30:
                try:
                    W, H = page.rect.width or 1, page.rect.height or 1
                    side = min(rpdf.OCR_LONG_SIDE, getattr(eng, "max_side", None) or rpdf.OCR_LONG_SIDE)
                    z = max(1.0, min(6.0, side / max(W, H)))
                    pix = page.get_pixmap(matrix=fitz.Matrix(z, z), colorspace=fitz.csGRAY, alpha=False)
                    theirs = [w for g in eng.recognize(pix.tobytes("png")) for w in arabic.normalize(g["text"]).split() if len(w) > 1]
                    tw, tr = set(theirs), {arabic.rasm(w) for w in theirs}
                    row["agree"] = round(sum(w in tw for w in mine) / len(mine), 3)
                    row["agree_rasm"] = round(sum(arabic.rasm(w) in tr for w in mine) / len(mine), 3)
                except Exception as e:
                    row["error"] = repr(e)
            pages.append(row)
        doc.close()
        prog = [p["agree"] for p in pages if p["program"] and "agree" in p]
        now = round(sum(prog) / len(prog), 3) if prog else None
        textp = [p for p in pages if "agree" in p and not p["per_page_ocr"] and not (p["cover"] > 0.8 and (p["hidden"] > 0.5 or p["arabic"] < 0.5))]
        tw = round(sum(p["agree"] for p in textp) / len(textp), 3) if textp else None
        tr = round(sum(p["agree_rasm"] for p in textp) / len(textp), 3) if textp else None
        imgs = sum(1 for p in pages if p["cover"] > 0.8 and (p["hidden"] > 0.5 or p["arabic"] < 0.5))
        rows.append({"id": bid, "kind": kind, "pages": n, "now": now, "text_only": tw, "text_only_rasm": tr,
                     "image_pages_in_sample": imgs, "sample": pages})
        print("%s | %s | %d | %s | %s · %s | %d من %d" % (bid, kind, n, now, tw, tr, imgs, len(pages)), flush=True)
    if a.save:
        (ROOT / "results" / (a.save + ".json")).write_text(json.dumps({"date": time.strftime("%Y-%m-%d %H:%M"), "books": rows},
                                                                      ensure_ascii=False, indent=1), encoding="utf-8")
        print("حُفظ: tests/results/%s.json" % a.save)
    return 0


if __name__ == "__main__":
    sys.exit(main())
