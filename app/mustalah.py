#!/usr/bin/env python3
"""كشفُ المصطلح في مكتبتك: أداةُ مهارة «كشف-المصطلح» — تقيس الألفاظ على كتبك ولا تقرّر شيئًا من الذاكرة.

  mustalah.py measure "لفظ" "لفظ" …      لكلّ لفظ: كم صفحةً وكم كتابًا وكم موضعًا (مع السوابق)،
                                         وكم يزيد البحثُ المتسامح بالرسم المجرّد فيما قُرئ آليًّا
  mustalah.py jiwar "لفظ" [--top 20]      جيرانُ اللفظ: أكثرُ ما يسبقه ويليه من الكلمات في كتبك، فيظهر المصطلحُ المركّب
                                         (المناط ← تحقيق المناط · تنقيح المناط · تخريج المناط)
  mustalah.py siyaq "لفظ" [--limit 12]    سياقاتٌ موزّعةٌ على الكتب (واحدٌ من كلّ كتابٍ أوّلًا) للتمييز بين المعاني
  mustalah.py kutub "لفظ" ["لفظ" …]       قائمةُ الكتب للألفاظ مجتمعة: الكتاب · المؤلّف ووفاته إن سُجّلت · الفنّ · عددُ المواضع
                                         — وهي المرحلةُ الثانية من البروتوكول: تُعرض على المستخدم قبل أيّ قراءة
  خيارات: --exact (بلا سوابق) · --layer body|foot · --json

المرشَّحاتُ (الألفاظ التي تُقاس) قد تخطر لك من معرفتك، لكنّ ما يُكتب للمستخدم هو القياسُ وحده بشواهده.
"""
import argparse
import collections
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import arabic  # noqa: E402
import bahth  # noqa: E402
import common  # noqa: E402
import store  # noqa: E402
from common import ar, count_word, setup_io, units  # noqa: E402

LAYERS = {"body": (0,), "foot": (1,), "all": (0, 1)}


def hits_for(con, term: str, exact: bool, layers, rasm: bool = False):
    expr, seqs = bahth.build("phrase", bahth.query_tokens(term), exact, rasm)
    return bahth.search(con, expr, seqs, rasm, layers), seqs


def occ(con, hits, seqs, rasm=False, cap=4000) -> int:
    if len(hits) > cap:
        return -1
    return sum(max(1, len(bahth.find_spans(bahth.text_of(con, h["page_id"], h["layer"]), seqs, rasm))) for h in hits)


def cmd_measure(con, a) -> int:
    rows = []
    ocr_any = con.execute("SELECT 1 FROM pages WHERE method='ocr' LIMIT 1").fetchone() is not None
    for t in a.terms:
        hits, seqs = hits_for(con, t, a.exact, LAYERS[a.layer])
        r = {"term": t, "pages": len(hits), "books": len({h["row"]["book_id"] for h in hits}),
             "occurrences": occ(con, hits, seqs)}
        if ocr_any:
            rh, _ = hits_for(con, t, a.exact, LAYERS[a.layer], rasm=True)
            r["rasm_extra"] = max(0, len(rh) - len(hits))
        rows.append(r)
    rows.sort(key=lambda r: -r["pages"])
    if a.json:
        print(json.dumps({"coverage": bahth.coverage(con), "terms": rows}, ensure_ascii=False, indent=1))
        return 0
    print(bahth.coverage_line(bahth.coverage(con)))
    print("القياس%s:\n" % (" (بلا سوابق)" if a.exact else " (مع السوابق)"))
    for r in rows:
        o = "" if r["occurrences"] < 0 else "، %s" % count_word(r["occurrences"], "موضعٌ واحد", "موضعان", "مواضع", "موضعًا")
        extra = (" · والرسمُ المجرّد يزيد %s" % ar(r["rasm_extra"])) if r.get("rasm_extra") else ""
        if r["pages"]:
            print("  «%s»: %s في %s%s%s" % (r["term"], count_word(r["pages"], "صفحةٌ واحدة", "صفحتان", "صفحات", "صفحةً"),
                                           count_word(r["books"], "كتابٍ واحد", "كتابين", "كتب", "كتابًا"), o, extra))
        else:
            print("  «%s»: لم أجده في كتبك المقروءة%s" % (r["term"], extra))
    return 0


def cmd_jiwar(con, a) -> int:
    hits, seqs = hits_for(con, a.terms[0], a.exact, LAYERS[a.layer])
    k = len(seqs[0]) if seqs else 1
    forms = {s[0][0] for s in seqs}
    left, right, books_of = collections.Counter(), collections.Counter(), collections.defaultdict(set)
    for h in hits:
        words = arabic.normalize(bahth.text_of(con, h["page_id"], h["layer"])).split()
        rest = [w for w, _ in seqs[0][1:]]
        for i in range(len(words) - k + 1):
            if words[i] in forms and words[i + 1:i + k] == rest:
                for n in (1, 2):
                    if i + k + n <= len(words):
                        g = tuple(words[i + k:i + k + n])
                        if not all(w in arabic.COMMON for w in g):
                            right[g] += 1
                            books_of[("r",) + g].add(h["row"]["book_id"])
                    if i - n >= 0:
                        g = tuple(words[i - n:i])
                        if not all(w in arabic.COMMON for w in g):
                            left[g] += 1
                            books_of[("l",) + g].add(h["row"]["book_id"])
    term = arabic.normalize(a.terms[0])
    if a.json:
        print(json.dumps({"term": a.terms[0], "pages": len(hits),
                          "after": [{"words": " ".join(g), "count": c, "books": len(books_of[("r",) + g])}
                                    for g, c in right.most_common(a.top)],
                          "before": [{"words": " ".join(g), "count": c, "books": len(books_of[("l",) + g])}
                                     for g, c in left.most_common(a.top)]}, ensure_ascii=False, indent=1))
        return 0
    print("جيرانُ «%s» في %s (الكلماتُ مطبَّعة: بلا حركاتٍ وبألفٍ وياءٍ موحّدتين):\n"
          % (a.terms[0], count_word(len(hits), "صفحةٍ واحدة", "صفحتين", "صفحات", "صفحةً")))
    print("  ما يليه:")
    for g, c in right.most_common(a.top):
        print("    %s %s — %s في %s" % (term, " ".join(g), ar(c), count_word(len(books_of[("r",) + g]), "كتابٍ واحد",
                                                                                "كتابين", "كتب", "كتابًا")))
    print("  ما يسبقه:")
    for g, c in left.most_common(a.top):
        print("    %s %s — %s في %s" % (" ".join(g), term, ar(c), count_word(len(books_of[("l",) + g]), "كتابٍ واحد",
                                                                                "كتابين", "كتب", "كتابًا")))
    return 0


def cmd_siyaq(con, a) -> int:
    hits, seqs = hits_for(con, a.terms[0], a.exact, LAYERS[a.layer])
    by_book = collections.OrderedDict()
    for h in hits:
        by_book.setdefault(h["row"]["book_id"], []).append(h)
    picked, rnd = [], 0
    while len(picked) < a.limit and any(len(v) > rnd for v in by_book.values()):
        for v in by_book.values():
            if len(v) > rnd and len(picked) < a.limit:
                picked.append(v[rnd])
        rnd += 1
    out = []
    for h in picked:
        raw = bahth.text_of(con, h["page_id"], h["layer"])
        b, p = store.book(con, h["row"]["book_id"]), store.page(con, h["row"]["book_id"], h["row"]["n"])
        out.append({"cite": store.cite(b, p), "book_id": b["id"], "n": p["n"], "layer": store.LAYER_NAME[h["layer"]],
                    "method": p["method"], "snippet": (bahth.snippets(raw, bahth.find_spans(raw, seqs, False), 140, 1)
                                                       or [raw[:280]])[0]})
    if a.json:
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return 0
    print("سياقاتُ «%s» (%s من %s، موزّعةٌ على الكتب):\n" % (a.terms[0], ar(len(out)),
                                                          count_word(len(hits), "صفحةٍ واحدة", "صفحتين", "صفحات", "صفحةً")))
    for i, x in enumerate(out, 1):
        print("[%s] %s · %s%s\n    %s\n" % (ar(i), x["cite"], x["layer"], " · قراءةٌ آليّة" if x["method"] == "ocr" else "",
                                           x["snippet"]))
    return 0


def cmd_kutub(con, a) -> int:
    per, total_pages = {}, set()
    for t in a.terms:
        hits, seqs = hits_for(con, t, a.exact, LAYERS[a.layer])
        for d in bahth.facet(con, hits, seqs, False):
            e = per.setdefault(d["book_id"], dict(d, pages=0, occurrences=0, ocr=0, terms={}))
            e["pages"] += d["pages"]
            e["occurrences"] += d["occurrences"]
            e["ocr"] += d["ocr"]
            e["terms"][t] = d["pages"]
        total_pages |= {h["page_id"] for h in hits}
    rows = sorted(per.values(), key=lambda d: (-d["occurrences"], -d["pages"]))
    cv = bahth.coverage(con)
    if a.json:
        print(json.dumps({"coverage": cv, "terms": a.terms, "books": rows}, ensure_ascii=False, indent=1))
        return 0
    print("قائمةُ الكتب لـ: %s" % " · ".join("«%s»" % t for t in a.terms))
    print(bahth.coverage_line(cv))
    print("في %s:\n" % count_word(len(rows), "كتابٍ واحد", "كتابين", "كتب", "كتابًا"))
    print("  رقم · الكتاب · المؤلّف والوفاة · الفنّ · المواضع")
    for d in rows:
        who = " ".join(x for x in (d["author"] or "", ("ت " + d["death"]) if d["death"] else "") if x) or "غيرُ مسجَّل"
        fann = d["fann"] or "غيرُ مسجَّل"
        per_term = "، ".join("%s %s" % (t, ar(n)) for t, n in d["terms"].items()) if len(a.terms) > 1 else ""
        print("  [%s] %s%s · %s · %s · %s في %s%s%s" % (
            ar(d["book_id"]), d["title"], (" ج" + ar(d["volume"])) if d["volume"] else "", who, fann,
            count_word(d["occurrences"], "موضعٌ واحد", "موضعان", "مواضع", "موضعًا"), units(d["pages"], d["unit"]),
            (" (%s)" % per_term) if per_term else "", (" · منها %s بالقراءة الآليّة" % ar(d["ocr"])) if d["ocr"] else ""))
    print("\nبياناتُ المؤلّف والوفاة والفنّ لا تُكتب إلّا من صفحة عنوان الكتاب بعد اعتماد المستخدم (maktaba.py set).")
    return 0


def main() -> int:
    setup_io()
    ap = argparse.ArgumentParser(prog="mustalah.py", description="كشفُ المصطلح في مكتبتك")
    ap.add_argument("cmd", choices=["measure", "jiwar", "siyaq", "kutub"])
    ap.add_argument("terms", nargs="+")
    ap.add_argument("--exact", action="store_true")
    ap.add_argument("--layer", choices=["body", "foot", "all"], default="all")
    ap.add_argument("--top", type=int, default=20)
    ap.add_argument("--limit", type=int, default=12)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    try:
        con = store.connect(readonly=True)
    except FileNotFoundError as e:
        common.die(str(e))
    return {"measure": cmd_measure, "jiwar": cmd_jiwar, "siyaq": cmd_siyaq, "kutub": cmd_kutub}[a.cmd](con, a)


if __name__ == "__main__":
    sys.exit(main())
