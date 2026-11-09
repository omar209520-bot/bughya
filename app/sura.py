#!/usr/bin/env python3
"""صورةُ الصفحة: ليقابل الباحثُ النقلَ بالصفحة نفسها قبل تقديمه، ويراها المستخدم مظلَّلًا فيها الموضع.

  sura.py 3 40                          صورةُ صفحة الملف ٤٠ من الكتاب ٣ كاملة
  sura.py 3 40 --mark "العبارة"         تُظلَّل أسطرُها، وتُقصّ الصورة عليها (أقلُّ حجمًا لقراءة كلود)
  sura.py 3 40 --mark "…" --full        تظليلٌ بلا قصّ · --zoom 2 (الدقّة) · --open (يفتحها للمستخدم)

للكتب ذات الصفحات المصوَّرة أو المطبوعة (بي دي إف والصور)؛ وتُحفظ الصورةُ في «مخرجات/صور-الصفحات».
الملفُّ الأصليّ لا يُكتب فيه شيء: التظليلُ في نسخةٍ في الذاكرة.
**النقلُ من صفحةٍ مقروءةٍ آليًّا لا يُقدَّم قبل أن تُقابَل صورتُها.**
"""
import argparse
import pathlib
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import arabic  # noqa: E402
import common  # noqa: E402
import store  # noqa: E402
from common import ar, setup_io  # noqa: E402

try:
    import pymupdf as fitz
except ImportError:  # pragma: no cover
    import fitz


def marked_boxes(boxes: list, phrase: str) -> list:
    """أسطرُ الصفحة التي فيها العبارة (أو بعضُ كلماتها إن امتدّت على سطرين)."""
    want = arabic.normalize(phrase).split()
    if not want:
        return []
    hits = []
    for k, bx in enumerate(boxes):
        line = arabic.normalize(bx["t"]).split()
        joined = " ".join(line)
        if " ".join(want) in joined:
            hits.append(k)
    if hits:
        return [boxes[k] for k in hits]
    # العبارةُ على سطرين: أسطرٌ متتاليةٌ فيها أوّلُ العبارة وآخرُها
    head, tail = " ".join(want[:max(1, len(want) // 2)]), " ".join(want[len(want) // 2:])
    for k in range(len(boxes) - 1):
        a = " ".join(arabic.normalize(boxes[k]["t"]).split())
        b = " ".join(arabic.normalize(boxes[k + 1]["t"]).split())
        if head in a and tail in b:
            return [boxes[k], boxes[k + 1]]
    return []


def main() -> int:
    setup_io()
    ap = argparse.ArgumentParser(prog="sura.py", description="صورةُ الصفحة مظلَّلًا فيها الموضع")
    ap.add_argument("book", type=int)
    ap.add_argument("page", type=int)
    ap.add_argument("--mark")
    ap.add_argument("--full", action="store_true")
    ap.add_argument("--zoom", type=float, default=2.0)
    ap.add_argument("--open", action="store_true")
    a = ap.parse_args()
    try:
        con = store.connect(readonly=True)
    except FileNotFoundError as e:
        common.die(str(e))
    b = store.book(con, a.book)
    if b is None:
        common.die("لا كتابَ بالرقم %s" % a.book)
    if b["kind"] not in ("pdf", "image"):
        common.die("صورةُ الصفحة للكتب المصوَّرة والمطبوعة (بي دي إف والصور)؛ «%s» ملفُّ %s بلا صفحاتٍ مرسومة."
                   % (store.title_of(b), b["kind"]))
    path = pathlib.Path(b["path"])
    if not path.exists():
        common.die("ملفُّ الكتاب غير موجود في موضعه: %s" % path)
    doc = fitz.open(str(path))
    if not 1 <= a.page <= doc.page_count:
        common.die("لا صفحةَ بهذا الرقم (في الملفّ %s)." % ar(doc.page_count))
    page = doc[a.page - 1]
    R = page.rect
    clip = None
    found = []
    if a.mark:
        p = store.page(con, b["id"], a.page)
        found = marked_boxes(store.boxes_of(p), a.mark) if p is not None else []
        if found:
            shape = page.new_shape()
            for bx in found:
                r = fitz.Rect(R.x0 + bx["x"] * R.width, R.y0 + bx["y"] * R.height,
                              R.x0 + (bx["x"] + bx["w"]) * R.width, R.y0 + (bx["y"] + bx["h"]) * R.height)
                shape.draw_rect(r + (-2, -2, 2, 2))
            shape.finish(color=None, fill=(1, 0.82, 0.1), fill_opacity=0.35)
            shape.commit()
            if not a.full:
                y0 = min(bx["y"] for bx in found) * R.height + R.y0
                y1 = max(bx["y"] + bx["h"] for bx in found) * R.height + R.y0
                clip = fitz.Rect(R.x0, max(R.y0, y0 - 0.12 * R.height), R.x1, min(R.y1, y1 + 0.12 * R.height))
    pix = page.get_pixmap(matrix=fitz.Matrix(a.zoom, a.zoom), clip=clip, alpha=False)
    common.IMAGES.mkdir(parents=True, exist_ok=True)
    out = common.IMAGES / ("%d-%d%s.png" % (b["id"], a.page, "-موضع" if clip is not None else ""))
    pix.save(str(out))
    print("صورةُ %s: %s" % (store.cite(b, store.page(con, b["id"], a.page) or {"n": a.page, "printed": None, "vol": None}),
                           out))
    if a.mark and not found:
        print("لم أجد العبارةَ في أسطر الصفحة المحفوظة؛ فالصورةُ كاملةٌ بلا تظليل.")
    if a.open:
        if common.IS_MAC:
            subprocess.run(["open", str(out)])
        elif common.IS_WIN:
            import os
            os.startfile(str(out))  # noqa: S606
    return 0


if __name__ == "__main__":
    sys.exit(main())
