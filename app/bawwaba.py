#!/usr/bin/env python3
"""بوّابةُ النقل: لا يُسلَّم نقلٌ حتّى يُقابَل بصفحته المعزوّة في مخزن النصّ.

  bawwaba.py check 9 22 "النصّ المنقول" [--layer متن|حاشية]
  bawwaba.py audit مخرجات/ملف.json|.xlsx|.md      يقابل كلَّ نقلٍ في الملفّ، ويخرج برمزٍ غير الصفر إن فشل شيء

الأحكام (من الأقوى):
  مطابقٌ حرفيًّا          النقلُ مقطعٌ متّصلٌ من الصفحة كما هو (بعد توحيد المسافات)
  مطابقٌ بلا تشكيل        يطابق إذا حُذفت الحركات: فالحركاتُ في النقل تخالف المستخرَج — تُصحَّح من الصفحة
  مطابقٌ بعد التطبيع      يطابق إذا وُحّدت الهمزاتُ والياءات والتاء المربوطة: رسمٌ مخالف — يُصحَّح من الصفحة
  يمتدّ إلى الصفحة التالية  النقلُ مقطعٌ يبدأ في الصفحة ويتمّ في التي تليها: يُقسم نقلين بعزوين
  غيرُ مطابق              لا يوجد في الصفحة: يُرفض (ويُعرض أقربُ ما في الصفحة إليه)

وفي الماك وويندوز سواء: النقلُ من صفحةٍ مقروءةٍ آليًّا يُنبَّه عليه، فيُقابَل بصورتها (sura.py) قبل التسليم.
وصيغةُ العزو في التقارير التي تقرؤها البوّابة: «النصّ» (رقم الكتاب ٩ · صفحة الملف ٢٢) — أو «القطعة» لما لا صفحاتِ له.
"""
import argparse
import difflib
import json
import pathlib
import re
import sys
import unicodedata

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import arabic  # noqa: E402
import common  # noqa: E402
import store  # noqa: E402
from common import ar, count_word, setup_io  # noqa: E402

VERDICTS = ["مطابقٌ حرفيًّا", "مطابقٌ بلا تشكيل", "مطابقٌ بعد التطبيع", "يمتدّ إلى الصفحة التالية", "غيرُ مطابق",
            "مطابقٌ للصورة"]
# «مطابقٌ للصورة»: قوبل النقلُ بصورة صفحته (image_checked في ملفّ الاستخراج)، وخالف المخزنَ في أخطاء الاستخراج وحدها
# (القراءة الآليّة، أو بي دي إف وورد)؛ فلا يُقبل إلّا إذا قارب المخزنَ جدًّا، ويُذكر أقربُ ما في المخزن ليُرى موضعُ الخلاف.
IMAGE_MIN_SIM = 0.85
_DIG = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")


def _ws(s: str) -> str:
    s = s.replace("⏎", " ").replace(bahth_hl(0), "").replace(bahth_hl(1), "")
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", s)).strip()


def bahth_hl(i: int) -> str:
    return "【】"[i]


def _nodiac(s: str) -> str:
    return re.sub(r"[ؐ-ًؚ-ٰٟۖ-ۭـ]", "", _ws(s))


def _norm_words(s: str) -> list:
    return arabic.normalize(s).split()


def _contains(words: list, sub: list) -> bool:
    k = len(sub)
    return k > 0 and any(words[i:i + k] == sub for i in range(len(words) - k + 1))


def closest(text: str, quote: str) -> tuple:
    """أقربُ مقطعٍ في الصفحة إلى النقل: (النسبة، المقطع)."""
    tw, qw = text.split(), quote.split()
    if not tw or not qw:
        return 0.0, ""
    k = len(qw)
    best, where = 0.0, 0
    for i in range(0, max(1, len(tw) - k + 1)):
        r = difflib.SequenceMatcher(None, " ".join(arabic.normalize(w) for w in tw[i:i + k]),
                                    " ".join(arabic.normalize(w) for w in qw)).ratio()
        if r > best:
            best, where = r, i
    return round(best, 2), " ".join(tw[where:where + k])


def verify(con, book_id: int, n: int, quote: str, layer: str = None, image_checked: bool = False) -> dict:
    b = store.book(con, book_id)
    if b is None:
        return {"verdict": VERDICTS[4], "note": "لا كتابَ بالرقم %s" % book_id}
    p = store.page(con, book_id, n)
    if p is None:
        return {"verdict": VERDICTS[4], "note": "لا صفحةَ %s في «%s»" % (n, store.title_of(b))}
    q = _ws(quote)
    layers = [("متن", p["body"] or ""), ("حاشية", p["foot"] or "")]
    res = {"cite": store.cite(b, p), "method": p["method"], "layer_found": None}
    for lvl, test in enumerate((lambda t: q in _ws(t), lambda t: _nodiac(q) in _nodiac(t),
                                lambda t: _contains(_norm_words(t), _norm_words(q)))):
        for name, text in layers:
            if text and test(text):
                res.update(verdict=VERDICTS[lvl], layer_found=name)
                break
        if res["layer_found"]:
            break
    if not res["layer_found"]:
        nxt = store.page(con, book_id, n + 1)
        if nxt is not None and _contains(_norm_words((p["body"] or "") + " " + (nxt["body"] or "")), _norm_words(q)):
            res.update(verdict=VERDICTS[3], layer_found="متن")
        else:
            (ratio, near), lname = max(((closest(t, q), name) for name, t in layers if t), default=((0.0, ""), None))
            res.update(verdict=VERDICTS[4], closest=near, similarity=ratio)
            # وفي بي دي إف المصنوع من وورد قد يفسد المستخرَجُ نفسُه (حروفٌ ساقطةٌ وحركاتٌ زائدة)، فالصورةُ تحسم كذلك
            if image_checked and ratio >= IMAGE_MIN_SIM and len(q.split()) >= 3:
                res.update(verdict=VERDICTS[5], layer_found=lname)
    notes = []
    if res["verdict"] == VERDICTS[5]:
        notes.append("قوبل بصورة الصفحة، والمقروءُ آليًّا يخالفه (تشابه %s): «%s»" % (ar(res["similarity"]),
                                                                                  res["closest"][:160]))
    if layer and res["layer_found"] and layer != res["layer_found"]:
        notes.append("عُزي إلى %s وهو في %s" % (layer, res["layer_found"]))
    if res["layer_found"] == "حاشية":
        notes.append("من الحاشية")
    if p["method"] == "ocr" and res["verdict"] not in (VERDICTS[4], VERDICTS[5]):
        notes.append("صفحةٌ مقروءةٌ آليًّا: قابِله بصورتها (sura.py %d %d --mark …)" % (book_id, n))
    res["note"] = "؛ ".join(notes)
    return res


# ───────────────────────── قراءةُ الملفّات ─────────────────────────

CITE_MD = re.compile(r"«([^«»]{3,}?)»[^«»\n]{0,40}?رقم الكتاب\s*([0-9٠-٩]+)\s*[·،,\-]\s*"
                     r"(?:صفحة الملف|الصفحة|القطعة|قطعة)\s*([0-9٠-٩]+)")


def items_from(path: pathlib.Path) -> list:
    suf = path.suffix.lower()
    if suf == ".json":
        d = json.loads(path.read_text(encoding="utf-8"))
        items = d.get("items", d) if isinstance(d, dict) else d
        return [{"book": int(str(x["book"]).translate(_DIG)), "page": int(str(x["page"]).translate(_DIG)),
                 "quote": x["quote"], "layer": x.get("layer"), "image_checked": bool(x.get("image_checked"))}
                for x in items]
    if suf == ".xlsx":
        import openpyxl
        ws = openpyxl.load_workbook(path, read_only=True).worksheets[0]
        rows = list(ws.iter_rows(values_only=True))
        for h, row in enumerate(rows[:10]):
            names = [str(c or "").strip() for c in row]
            if "رقم الكتاب" in names and any(x in names for x in ("النص", "النصّ", "النقل")):
                ib = names.index("رقم الكتاب")
                ip = next(names.index(x) for x in ("صفحة الملف", "القطعة", "الصفحة") if x in names)
                iq = next(names.index(x) for x in ("النصّ", "النص", "النقل") if x in names)
                il = names.index("الطبقة") if "الطبقة" in names else None
                return [{"book": int(str(r[ib]).translate(_DIG)), "page": int(str(r[ip]).translate(_DIG)),
                         "quote": str(r[iq]), "layer": r[il] if il is not None else None}
                        for r in rows[h + 1:] if r[ib] and r[ip] and r[iq]]
        common.die("لم أجد في الورقة الأولى أعمدةَ «رقم الكتاب» و«صفحة الملف» و«النصّ».")
    text = path.read_text(encoding="utf-8")
    return [{"book": int(m.group(2).translate(_DIG)), "page": int(m.group(3).translate(_DIG)), "quote": m.group(1),
             "layer": None} for m in CITE_MD.finditer(text)]


def main() -> int:
    setup_io()
    ap = argparse.ArgumentParser(prog="bawwaba.py", description="بوّابةُ النقل")
    sub = ap.add_subparsers(dest="cmd")
    c = sub.add_parser("check")
    c.add_argument("book", type=int)
    c.add_argument("page", type=int)
    c.add_argument("quote")
    c.add_argument("--layer", choices=["متن", "حاشية"])
    c.add_argument("--json", action="store_true")
    au = sub.add_parser("audit")
    au.add_argument("file")
    au.add_argument("--json", action="store_true")
    a = ap.parse_args()
    try:
        con = store.connect(readonly=True)
    except FileNotFoundError as e:
        common.die(str(e))
    if a.cmd == "check":
        r = verify(con, a.book, a.page, a.quote, a.layer)
        if a.json:
            print(json.dumps(r, ensure_ascii=False, indent=1))
        else:
            print("%s — %s%s" % (r["verdict"], r.get("cite", ""), (" · " + r["note"]) if r.get("note") else ""))
            if r["verdict"] == VERDICTS[4] and r.get("closest"):
                print("  أقربُ ما في الصفحة (تشابه %s): %s" % (ar(r["similarity"]), r["closest"]))
        return 0 if r["verdict"] != VERDICTS[4] else 1
    if a.cmd == "audit":
        path = pathlib.Path(a.file)
        items = items_from(path)
        if not items:
            common.die("لم أجد نقولًا معزوّةً في الملفّ (الصيغة: «النصّ» (رقم الكتاب ٩ · صفحة الملف ٢٢)).")
        out, tally = [], {v: 0 for v in VERDICTS}
        for i, it in enumerate(items, 1):
            r = verify(con, it["book"], it["page"], it["quote"], it.get("layer"), it.get("image_checked", False))
            tally[r["verdict"]] += 1
            out.append(dict(it, index=i, **r))
        if a.json:
            print(json.dumps({"tally": tally, "items": out}, ensure_ascii=False, indent=1))
        else:
            print("بوّابةُ النقل: %s في %s" % (count_word(len(items), "نقلٌ واحد", "نقلان", "نقول", "نقلًا"), path.name))
            print("  " + " · ".join("%s %s" % (k, ar(v)) for k, v in tally.items() if v))
            for r in out:
                if r["verdict"] != VERDICTS[0] or r.get("note"):
                    print("  [%s] %s — %s%s\n       «%s»" % (ar(r["index"]), r["verdict"], r.get("cite", ""),
                                                           (" · " + r["note"]) if r.get("note") else "",
                                                           r["quote"][:120]))
                    if r.get("closest"):
                        print("       أقربُ ما في الصفحة: %s" % r["closest"][:160])
        return 0 if tally[VERDICTS[4]] == 0 else 1
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
