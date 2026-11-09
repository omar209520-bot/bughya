#!/usr/bin/env python3
"""قراءةُ النصّ: صفحةٌ كاملة، أو مدى صفحات، أو نوافذُ حول مواضع عبارةٍ في كتاب، أو عناوينُ الكتاب.

  nass.py 9 22                  الصفحةُ (أو القطعة) ٢٢ من الكتاب ٩: رأسُها ومتنُها وحاشيتُها، وعزوُها
  nass.py 9 22-25               مدى صفحات (عشرون فأقلّ)
  nass.py 9 --around "العبارة" [--window 600] [--rasm] [--exact]
                                نافذةٌ حول كلّ موضعٍ للعبارة في الكتاب، تتّسع إلى الصفحة المجاورة إن اتّصل الكلامُ بها:
                                هي «القراءةُ الكاملة» للمواضع كلّها بلا عيّنة، دون قراءة الصفحات كاملةً مع جاراتها
  nass.py 9 --toc               عناوينُ الكتاب بصفحاتها
  --layer body|foot · --json

الرقمُ الثاني رقمُ الصفحة في الملفّ (أو القطعة) كما في نتائج البحث، لا الرقمُ المطبوع.
"""
import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import arabic  # noqa: E402
import bahth  # noqa: E402
import common  # noqa: E402
import store  # noqa: E402
from common import ar, count_word, setup_io  # noqa: E402

METHOD = {"ocr": "قراءةٌ آليّة (قابِلها بصورة الصفحة قبل النقل)", "none": "لا نصَّ فيها", "error": "تعذّرت قراءتُها"}


def show_page(b, p, layer: str) -> str:
    out = ["══ %s · رقم الكتاب %s · %s %s%s" % (store.cite(b, p), ar(b["id"]),
                                               "صفحة الملف" if b["unit"] == "صفحة" else b["unit"], ar(p["n"]),
                                               (" · " + METHOD[p["method"]]) if p["method"] in METHOD else "")]
    if p["head"] and layer == "all":
        out.append("[الرأس] " + p["head"])
    if layer in ("all", "body"):
        out.append("[المتن]\n" + (p["body"] or "—"))
    if layer in ("all", "foot") and (p["foot"] or layer == "foot"):
        out.append("[الحاشية]\n" + (p["foot"] or "—"))
    return "\n".join(out)


def page_dict(b, p) -> dict:
    return {"book_id": b["id"], "title": b["title"], "n": p["n"], "printed": p["printed"], "vol": p["vol"] or b["volume"],
            "unit": b["unit"], "method": p["method"], "conf": p["conf"], "cite": store.cite(b, p),
            "head": p["head"], "body": p["body"], "foot": p["foot"],
            "catch": p["catch"] if "catch" in p.keys() else None}


def around(con, b, phrase: str, window: int, rasm: bool, exact: bool, layer: str) -> list:
    """نوافذُ حول كلّ موضع: النصُّ من ‹window› قبل الموضع إلى ‹window› بعده، ويُكمَل من الصفحة السابقة أو اللاحقة
    إن وقع الموضعُ قريبًا من حدّ صفحته."""
    expr, seqs = bahth.build("phrase", bahth.query_tokens(phrase), exact, rasm)
    layers = {"body": (0,), "foot": (1,), "all": (0, 1)}[layer]
    hits = bahth.search(con, expr, seqs, rasm, layers, {b["id"]}, "book", include_missing=True)
    out = []
    for h in hits:
        n, lay = h["row"]["n"], h["layer"]
        p = store.page(con, b["id"], n)
        raw = (p["foot"] if lay else p["body"]) or ""
        for s, e in bahth.find_spans(raw, seqs, rasm) or [(0, 0)]:
            a, z = s - window, e + window
            before = after = ""
            if a < 0 and lay == 0:          # يتّصل بآخر الصفحة السابقة (المتنُ بالمتن)
                prev = store.page(con, b["id"], n - 1)
                if prev and prev["body"]:
                    before = prev["body"][max(0, len(prev["body"]) + a):] + "\n‖ [%s] ‖\n" % store.cite(b, p)
            if z > len(raw) and lay == 0:
                nxt = store.page(con, b["id"], n + 1)
                if nxt and nxt["body"]:
                    after = "\n‖ [%s] ‖\n" % store.cite(b, nxt) + nxt["body"][:z - len(raw)]
            text = before + raw[max(0, a):s] + bahth.HL[0] + raw[s:e] + bahth.HL[1] + raw[e:min(len(raw), z)] + after
            out.append({"cite": store.cite(b, p), "n": n, "layer": store.LAYER_NAME[lay], "method": p["method"],
                        "text": text})
    return out


def main() -> int:
    setup_io()
    ap = argparse.ArgumentParser(prog="nass.py", description="قراءةُ نصّ صفحةٍ أو مداها أو نوافذ حول المواضع")
    ap.add_argument("book", type=int)
    ap.add_argument("page", nargs="?")
    ap.add_argument("--around")
    ap.add_argument("--window", type=int, default=600)
    ap.add_argument("--rasm", action="store_true")
    ap.add_argument("--exact", action="store_true")
    ap.add_argument("--toc", action="store_true")
    ap.add_argument("--layer", choices=["body", "foot", "all"], default="all")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    try:
        con = store.connect(readonly=True)
    except FileNotFoundError as e:
        common.die(str(e))
    b = store.book(con, a.book)
    if b is None:
        common.die("لا كتابَ بالرقم %s (maktaba.py books)" % a.book)
    if a.toc:
        rows = [dict(r) for r in con.execute("SELECT n, level, title FROM toc WHERE book_id = ? ORDER BY rowid", (b["id"],))]
        if a.json:
            print(json.dumps(rows, ensure_ascii=False, indent=1))
        elif not rows:
            print("لا عناوينَ محفوظةٌ لهذا الكتاب (لا فهرسَ مدمجًا في ملفّه).")
        else:
            for r in rows:
                print("%s%s … %s %s" % ("  " * (max(1, r["level"] or 1) - 1), r["title"], b["unit"], ar(r["n"])))
        return 0
    if a.around:
        res = around(con, b, a.around, a.window, a.rasm, a.exact, a.layer)
        if a.json:
            print(json.dumps(res, ensure_ascii=False, indent=1))
            return 0
        if not res:
            print("لم أجد «%s» في «%s»." % (a.around, store.title_of(b)))
            return 0
        print("«%s» في «%s»: %s\n" % (a.around, store.title_of(b),
                                        count_word(len(res), "موضعٌ واحد", "موضعان", "مواضع", "موضعًا")))
        for i, r in enumerate(res, 1):
            print("[%s] %s · %s%s\n%s\n" % (ar(i), r["cite"], r["layer"], (" · " + METHOD["ocr"]) if r["method"] == "ocr" else "",
                                           r["text"]))
        return 0
    if not a.page:
        common.die("اذكر رقمَ الصفحة (أو --around أو --toc).")
    if "-" in a.page:
        lo, hi = (int(x) for x in a.page.split("-", 1))
    else:
        lo = hi = int(a.page)
    if hi < lo or hi - lo > 19:
        common.die("المدى عشرون صفحةً فأقلّ.")
    pages = [store.page(con, b["id"], n) for n in range(lo, hi + 1)]
    pages = [p for p in pages if p is not None]
    if not pages:
        common.die("لا صفحةَ بهذا الرقم في «%s» (فيه %s)." % (store.title_of(b), ar(b["done_pages"] or 0)))
    if a.json:
        print(json.dumps([page_dict(b, p) for p in pages], ensure_ascii=False, indent=1))
        return 0
    print("\n\n".join(show_page(b, p, a.layer) for p in pages))
    return 0


if __name__ == "__main__":
    sys.exit(main())
