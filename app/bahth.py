#!/usr/bin/env python3
"""البحثُ في مخزن النصّ: كلُّ موضعٍ بكتابه وجزئه وصفحته وطبقته (متنٌ أو حاشية)، ومقتطفٌ من نصّه كما قُرئ.

  bahth.py "الصلاة الوسطى"               عبارةٌ متّصلة، ومعها سوابقُ أوّل كلمة (والصلاة، بالصلاة، للصلاة…)
  bahth.py --words "النية الصلاة"        كلماتٌ في صفحةٍ واحدة بأيّ ترتيب (ومع سوابقها)
  bahth.py --any "الغسل الوضوء"          أيُّ كلمةٍ منها
  bahth.py --near "النية الصلاة" --dist 8   كلمتان بينهما ٨ كلماتٍ فأقلّ (بلا سوابق)
  bahth.py --query 'صلا* AND NOT الجمعه'  صيغةُ البحث النصّيّ للمتمرّس: AND وOR وNOT وNEAR، والنجمةُ بادئة

  خيارات:
    --exact               بلا سوابق
    --rasm                بحثٌ متسامحٌ بالرسم المجرّد: يجد الكلمة وإن أخطأت القراءةُ الآليّة في نقاطها
    --layer body|foot     المتنُ وحده أو الحاشيةُ وحدها (الأصل: كلاهما)
    --book 3,5            في كتبٍ بعينها (أرقامُها من maktaba.py books)
    --facet               عددُ المواضع في كلّ كتاب (لقائمة الكتب) بدل المواضع نفسها
    --limit 30 --offset 0 (الأصل ٣٠، و٠ = الكلّ) · --order book|rank (الأصل: بترتيب الكتب والصفحات)
    --context 110         طولُ المقتطف من كلّ جانب · --json

كلُّ بحثٍ يبدأ بسطر «التغطية»: كم كتابًا قُرئ من مكتبتك وكم لم يُقرأ بعد؛ فما لم يُقرأ لم يُبحث فيه.
"""
import argparse
import json
import pathlib
import re
import sys
import unicodedata

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import arabic  # noqa: E402
import common  # noqa: E402
import store  # noqa: E402
from common import ar, count_word, setup_io, units  # noqa: E402

HL = ("【", "】")


# ───────────────────────── صيغةُ البحث ─────────────────────────

def query_tokens(text: str) -> list:
    """كلماتُ السؤال مطبَّعةً، ومعها علامةُ البادئة: [(الكلمة، بادئة؟)]."""
    out = []
    for raw in text.split():
        star = raw.endswith("*")
        for w in arabic.normalize(raw.rstrip("*")).split():
            out.append((w, False))
        if star and out:
            out[-1] = (out[-1][0], True)
    return out


def _q(w: str, star: bool = False) -> str:
    return '"%s"%s' % (w.replace('"', ""), "*" if star else "")


def _forms(w: str, exact: bool, rasm: bool) -> list:
    forms = sorted({w} if exact else arabic.variants(w))
    return sorted({arabic.rasm(f) for f in forms}) if rasm else forms


def build(mode: str, toks: list, exact: bool, rasm: bool, dist: int = 10) -> tuple:
    """(تعبيرُ البحث النصّيّ، وتسلسلاتُ الكلمات للتظليل: قائمةُ [(كلمة، بادئة)])."""
    if not toks:
        common.die("لا كلمةَ في السؤال.")
    conv = (lambda w: arabic.rasm(w)) if rasm else (lambda w: w)
    if mode == "phrase":
        first, rest = toks[0], [(conv(w), s) for w, s in toks[1:]]
        seqs = [[(f, first[1] if not rest else False)] + rest for f in _forms(first[0], exact, rasm)]
        parts = []
        for seq in seqs:
            words = " ".join(w for w, _ in seq)
            parts.append(_q(words, seq[-1][1]))
        return " OR ".join(parts), seqs
    if mode in ("words", "any"):
        groups, seqs = [], []
        for w, star in toks:
            forms = [conv(w)] if star else _forms(w, exact, rasm)
            groups.append("(" + " OR ".join(_q(f, star) for f in forms) + ")")
            seqs += [[(f, star)] for f in forms]
        return (" AND " if mode == "words" else " OR ").join(groups), seqs
    if mode == "near":
        words = [conv(w) for w, _ in toks]
        return "NEAR(%s, %d)" % (" ".join(_q(w) for w in words), dist), [[(w, False)] for w in words]
    common.die("طريقةُ بحثٍ غير معروفة: " + mode)


_OPS = {"AND", "OR", "NOT", "NEAR"}


def raw_query(text: str, rasm: bool) -> tuple:
    """صيغةُ المتمرّس: تُطبَّع كلماتُها وتبقى أدواتُها."""
    out, seqs = [], []
    for tok in re.findall(r'"[^"]*"\*?|\(|\)|,|\S+', text):
        if tok in _OPS or tok in ("(", ")", ","):
            out.append(tok)
            continue
        if tok.isdigit() and out and out[-1] == ",":
            out.append(tok)
            continue
        star = tok.endswith("*")
        body = tok.rstrip("*").strip('"')
        words = arabic.normalize(body).split()
        if rasm:
            words = [arabic.rasm(w) for w in words]
        if not words:
            continue
        out.append(_q(" ".join(words), star))
        seqs.append([(w, False) for w in words[:-1]] + [(words[-1], star)])
    return " ".join(out), seqs


# ───────────────────────── المواضعُ في النصّ ─────────────────────────

def find_spans(raw: str, seqs: list, rasm: bool) -> list:
    """مواضعُ التسلسلات في النصّ الأصليّ: [(بداية، نهاية)] بحروف النصّ كما قُرئ."""
    norm, idx = arabic.normalize_map(raw)
    toks = arabic.tokens(norm)
    words = [arabic.rasm(t[0]) if rasm else t[0] for t in toks]
    spans = []
    for seq in seqs:
        k = len(seq)
        for i in range(len(words) - k + 1):
            ok = True
            for j, (w, star) in enumerate(seq):
                have = words[i + j]
                if not (have.startswith(w) if star else have == w):
                    ok = False
                    break
            if ok:
                s, e = toks[i][1], toks[i + k - 1][2] - 1
                a = idx[s]
                j = a - 1                     # ألفُ «ابن» التي أسقطها التطبيع تدخل في التظليل
                while j >= 0 and unicodedata.category(raw[j]) == "Mn":
                    j -= 1
                if toks[i][0] == "بن" and j >= 0 and raw[j] in "اأإآٱ" and (j == 0 or not raw[j - 1].isalpha()):
                    a = j
                spans.append((a, idx[e] + 1))
    spans.sort()
    merged = []
    for s, e in spans:
        if merged and s <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))
    return merged


def snippets(raw: str, spans: list, ctx: int, most: int = 3) -> list:
    """نوافذُ حول المواضع. والنافذةُ التي تتداخل مع سابقتها تُدمج فيها (فلا يتكرّر النصُّ نفسه في نافذتين)،
    ما لم يطل المدموجُ جدًّا؛ فإن طال بدأت النافذةُ التالية من حيث انتهت السابقة."""
    wins = []
    for s, e in spans:
        if wins and e <= wins[-1][1]:
            continue                          # الموضعُ داخل النافذة السابقة: يُظلَّل فيها
        a, b = max(0, s - ctx), min(len(raw), e + ctx)
        while a > 0 and not raw[a - 1].isspace() and s - a < ctx + 25:
            a -= 1
        while b < len(raw) and not raw[b].isspace() and b - e < ctx + 25:
            b += 1
        if wins and a < wins[-1][1]:
            if b - wins[-1][0] <= 5 * ctx:
                wins[-1][1] = b
                continue
            a = wins[-1][1]
            while a < s and raw[a].isspace():
                a += 1
        if len(wins) >= most:
            break
        wins.append([a, b])
    out = []
    for a, b in wins:
        # ما وقع من مواضع داخل النافذة يُظلَّل معها
        inner = [(x, y) for x, y in spans if x >= a and y <= b]
        text, pos = "", a
        for x, y in inner:
            text += raw[pos:x] + HL[0] + raw[x:y] + HL[1]
            pos = y
        text += raw[pos:b]
        out.append(("… " if a > 0 else "") + text.replace("\n", " ⏎ ").strip() + (" …" if b < len(raw) else ""))
    return out


# ───────────────────────── التغطية ─────────────────────────

def coverage(con) -> dict:
    c = {r[0]: r[1] for r in con.execute("SELECT state, COUNT(*) FROM books GROUP BY state")}
    ocr = con.execute("SELECT COUNT(*) FROM pages WHERE method='ocr'").fetchone()[0]
    pages = con.execute("SELECT COUNT(*) FROM pages").fetchone()[0]
    total = sum(v for k, v in c.items() if k != "missing")
    return {"books": total, "done": c.get("done", 0), "reading": c.get("reading", 0), "pending": c.get("pending", 0),
            "failed": c.get("error", 0) + c.get("unsupported", 0) + c.get("empty", 0), "missing": c.get("missing", 0),
            "pages": pages, "ocr_pages": ocr}


def coverage_line(cv: dict) -> str:
    s = "التغطية: بُحث في %s قُرئت كاملةً من %s" % (count_word(cv["done"], "كتابٍ واحد", "كتابين", "كتب", "كتابًا"),
                                                  count_word(cv["books"], "كتابٍ واحد", "كتابين", "كتب", "كتابًا"))
    if cv["reading"] or cv["pending"]:
        s += "، وفيما قُرئ من %s لم تكتمل قراءتُها (%s تنتظر)" % (count_word(cv["reading"], "كتابٍ واحد", "كتابين", "كتب", "كتابًا"),
                                                                ar(cv["pending"]))
    if cv["failed"]:
        s += " · لم يُقرأ منها %s (maktaba.py status)" % ar(cv["failed"])
    if cv["ocr_pages"]:
        s += " · منها %s صفحةً بالقراءة الآليّة (جرّب --rasm لما أخطأت نقاطُه)" % ar(cv["ocr_pages"])
    return s


# ───────────────────────── البحث ─────────────────────────

def search(con, expr: str, seqs: list, rasm: bool, layers=(0, 1), books=None, order: str = "book",
           include_missing: bool = False, fann: str = None) -> list:
    rows = store.match(con, expr, "rasm" if rasm else "norm")
    rows = [r for r in rows if r[1] in layers]
    if not rows:
        return []
    score = {(pid, layer): sc for pid, layer, sc in rows}
    ids = sorted({pid for pid, _, _ in rows})
    info = {}
    for k in range(0, len(ids), 500):
        part = ids[k:k + 500]
        q = ("SELECT p.id, p.book_id, p.n, p.printed, p.vol, p.method, p.conf, b.title, b.volume, b.unit, b.state, "
             "b.series, b.fann FROM pages p JOIN books b ON b.id = p.book_id WHERE p.id IN (%s)" % ",".join("?" * len(part)))
        for r in con.execute(q, part):
            info[r["id"]] = r
    hits = []
    for (pid, layer), sc in score.items():
        r = info.get(pid)
        if r is None or (books and r["book_id"] not in books):
            continue
        if fann and (r["fann"] or "") != fann:          # الحصرُ في صنفٍ من أصناف الكتب
            continue
        if r["state"] == "missing" and not include_missing:
            continue
        hits.append({"page_id": pid, "layer": layer, "score": sc, "row": r})
    if order == "rank":
        hits.sort(key=lambda h: h["score"])
    else:
        hits.sort(key=lambda h: ((h["row"]["series"] or h["row"]["title"] or ""), h["row"]["volume"] or 0,
                                 h["row"]["book_id"], h["row"]["n"], h["layer"]))
    return hits


def via_ayat(raw: str, seqs: list, rasm: bool):
    """إن لم يوجد اللفظ في نصّ الصفحة نفسه: أهو في لفظ آيةٍ عرفها المطابق فيها (أخطأت القراءةُ في نصّها)؟"""
    import ayat
    for x in ayat.find(raw):
        if x["sure_words"] and find_spans(x["ref"], seqs, rasm):
            return x
    return None


def text_of(con, pid: int, layer: int) -> str:
    r = con.execute("SELECT body, foot FROM pages WHERE id = ?", (pid,)).fetchone()
    return (r["foot"] if layer else r["body"]) or ""


def facet(con, hits: list, seqs: list, rasm: bool) -> list:
    per = {}
    count_occ = len(hits) <= 20000
    for h in hits:
        r = h["row"]
        d = per.setdefault(r["book_id"], {"book_id": r["book_id"], "title": r["title"], "volume": r["volume"],
                                          "pages": 0, "occurrences": 0, "ocr": 0})
        d["pages"] += 1
        d["ocr"] += r["method"] == "ocr"
        if count_occ:
            d["occurrences"] += max(1, len(find_spans(text_of(con, h["page_id"], h["layer"]), seqs, rasm)))
    out = sorted(per.values(), key=lambda d: (-d["pages"], d["title"] or ""))
    for d in out:
        b = store.book(con, d["book_id"])
        d.update(author=b["author"], death=b["death"], fann=b["fann"], unit=b["unit"], unclear=store.unclear_title(b))
    return out


def main() -> int:
    setup_io()
    ap = argparse.ArgumentParser(prog="bahth.py", description="البحثُ في مخزن النصّ")
    ap.add_argument("phrase", nargs="?")
    ap.add_argument("--words")
    ap.add_argument("--any")
    ap.add_argument("--near")
    ap.add_argument("--dist", type=int, default=10)
    ap.add_argument("--query")
    ap.add_argument("--exact", action="store_true")
    ap.add_argument("--rasm", action="store_true")
    ap.add_argument("--layer", choices=["body", "foot", "all"], default="all")
    ap.add_argument("--book")
    ap.add_argument("--facet", action="store_true")
    ap.add_argument("--fann", help="الحصرُ في كتب صنفٍ واحد (مثل: العقيدة)")
    ap.add_argument("--limit", type=int, default=30)
    ap.add_argument("--offset", type=int, default=0)
    ap.add_argument("--order", choices=["book", "rank"], default="book")
    ap.add_argument("--context", type=int, default=110)
    ap.add_argument("--include-missing", action="store_true")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    if a.query:
        mode, (expr, seqs) = "query", raw_query(a.query, a.rasm)
    else:
        mode, text = next(((m, v) for m, v in (("words", a.words), ("any", a.any), ("near", a.near),
                                                ("phrase", a.phrase)) if v), (None, None))
        if not mode:
            ap.print_help()
            return 2
        expr, seqs = build(mode, query_tokens(text), a.exact, a.rasm, a.dist)
    try:
        con = store.connect(readonly=True)
    except FileNotFoundError as e:
        common.die(str(e))
    layers = {"body": (0,), "foot": (1,), "all": (0, 1)}[a.layer]
    books = {int(x) for x in a.book.split(",")} if a.book else None
    cv = coverage(con)
    try:
        hits = search(con, expr, seqs, a.rasm, layers, books, a.order, a.include_missing, a.fann)
    except Exception as e:
        common.die("صيغةُ البحث غيرُ مفهومة: %s" % e)
    label = {"phrase": "عبارة", "words": "كلماتٌ في صفحة", "any": "أيُّ كلمة", "near": "كلماتٌ متقاربة",
             "query": "صيغةُ متمرّس"}[mode]
    opts = [label] + (["بلا سوابق"] if a.exact else ([] if mode in ("near", "query") else ["مع السوابق"]))
    opts += (["بالرسم المجرّد"] if a.rasm else []) + ({"body": ["في المتن"], "foot": ["في الحاشية"]}.get(a.layer, []))
    books_n = len({h["row"]["book_id"] for h in hits})
    if a.facet:
        fc = facet(con, hits, seqs, a.rasm)
        if a.json:
            print(json.dumps({"coverage": cv, "expr": expr, "pages": len(hits), "books": fc}, ensure_ascii=False,
                             indent=1))
            return 0
        print("البحث: «%s» (%s)" % (a.query or a.words or a.any or a.near or a.phrase, "، ".join(opts)))
        print(coverage_line(cv))
        print("النتيجة: %s في %s\n" % (count_word(len(hits), "صفحةٌ واحدة", "صفحتان", "صفحات", "صفحةً"),
                                        count_word(books_n, "كتابٍ واحد", "كتابين", "كتب", "كتابًا")))
        for d in fc:
            meta = " · ".join(x for x in (d["author"], ("ت " + d["death"]) if d["death"] else "", d["fann"]) if x)
            print("[%s] %s%s%s — %s، %s%s" % (
                ar(d["book_id"]), d["title"], (" ج" + ar(d["volume"])) if d["volume"] else "",
                (" (" + meta + ")") if meta else "",
                units(d["pages"], d["unit"]),
                count_word(d["occurrences"], "موضعٌ واحد", "موضعان", "مواضع", "موضعًا") if d["occurrences"] else "",
                (" · منها %s بالقراءة الآليّة" % ar(d["ocr"])) if d["ocr"] else ""))
        return 0
    shown = hits[a.offset:] if a.limit == 0 else hits[a.offset:a.offset + a.limit]
    results = []
    for h in shown:
        r = h["row"]
        raw = text_of(con, h["page_id"], h["layer"])
        spans = find_spans(raw, seqs, a.rasm)
        snips = snippets(raw, spans, a.context) if spans else [raw[:2 * a.context].replace("\n", " ⏎ ") + " …"]
        via = via_ayat(raw, seqs, a.rasm) if not spans else None
        if via:
            snips = ["في الكتاب: «%s»" % via["words"]]
        b = store.book(con, r["book_id"])
        p = store.page(con, r["book_id"], r["n"])
        results.append({"book_id": r["book_id"], "title": r["title"], "n": r["n"], "printed": r["printed"],
                        "vol": r["vol"] or r["volume"], "unit": r["unit"], "layer": store.LAYER_NAME[h["layer"]],
                        "method": r["method"], "conf": r["conf"], "cite": store.cite(b, p),
                        "unclear": store.unclear_title(b),
                        "occurrences": len(spans), "snippets": snips,
                        "via_ayat": ["%s %s" % (v["sura"], ar(v["aya"])) for v in via["verses"]] if via else None})
    if a.json:
        print(json.dumps({"coverage": cv, "expr": expr, "pages": len(hits), "books": books_n, "offset": a.offset,
                          "results": results}, ensure_ascii=False, indent=1))
        return 0
    print("البحث: «%s» (%s)" % (a.query or a.words or a.any or a.near or a.phrase, "، ".join(opts)))
    print(coverage_line(cv))
    if not hits:
        print("\nلم أجده في كتبك المقروءة.")
        return 0
    print("النتيجة: %s في %s%s\n" % (
        count_word(len(hits), "صفحةٌ واحدة", "صفحتان", "صفحات", "صفحةً"),
        count_word(books_n, "كتابٍ واحد", "كتابين", "كتب", "كتابًا"),
        (" — المعروض %s إلى %s (--offset %d للتالي)" % (ar(a.offset + 1), ar(a.offset + len(shown)), a.offset + len(shown))
         if len(hits) > a.offset + len(shown) else "")))
    for i, x in enumerate(results, a.offset + 1):
        how = "نصُّ الملفّ" if x["method"] not in ("ocr",) else "قراءةٌ آليّة — قابِلها بصورة الصفحة: sura.py %d %d" % (x["book_id"], x["n"])
        print("[%s] %s · %s · %s" % (ar(i), x["cite"], x["layer"], how))
        for s in x["snippets"]:
            print("    " + s)
        print("    ← nass.py %d %d" % (x["book_id"], x["n"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
