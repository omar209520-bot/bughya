#!/usr/bin/env python3
"""مدقّقُ إحالات الرسالة: يقرأ فصلًا (وورد)، ويستخرج كلَّ نقلٍ بحاشيته، ويبحث عن نصّه في مكتبتك كلّها، ويحكم عليه.

  tadqiq.py "الفصل.docx"                  التقريرُ في الطرفيّة، وملفّاه في «مخرجات»: جيسون وإكسل
  tadqiq.py "الفصل.docx" --no-xlsx        بلا إكسل

ما يُعدّ نقلًا:
  • نصٌّ بين « » أو " " تليه حاشيةٌ مباشرة، أو بلا حاشية (فيُبحث عنه ويُنبَّه أنّه بلا إحالة)
  • أبياتٌ: أسطرٌ قصيرةٌ متتالية تنتهي بحاشية (نظمٌ منقول)
  • وما سوى ذلك ممّا عليه حاشية فحكايةٌ بالمعنى: يُذكر كتابُه هل هو في المكتبة، ولا يُدقَّق نصُّه

الأحكام:
  مطابق                  النصُّ في الكتاب المذكور، والصفحةُ المطبوعة توافق الحاشية
  مطابق، والصفحة تخالف    النصُّ في الكتاب المذكور، والصفحةُ المطبوعة غيرُ التي في الحاشية
  مطابق، والصفحة لم تُقرأ  النصُّ في الكتاب، ولم يُقرأ رقمُ صفحته المطبوع فلا تُقارن الصفحة
  قريبٌ بفروق             الأقربُ في الكتاب يشابهه ولا يطابقه: فروقٌ في النقل، أو أخطاءُ القراءة الآليّة (تُحسم بالصورة)
  في كتابٍ آخر           لم يوجد في الكتاب المذكور، ووُجد في غيره
  الكتاب ليس في المكتبة   لم يُعرف كتابُ الحاشية في مكتبتك (وقد يوجد النصُّ في غيره فيُذكر)
  لم يوجد               لم يوجد في كتبك المقروءة

لا يكتب في ملفّ الرسالة شيئًا: يقرؤه فقط.
"""
import argparse
import difflib
import html
import json
import pathlib
import re
import sys
import zipfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import arabic  # noqa: E402
import bahth  # noqa: E402
import bawwaba  # noqa: E402
import common  # noqa: E402
import store  # noqa: E402
from common import ar, setup_io  # noqa: E402

DIG = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
REF = "%s"            # علامةُ موضع الحاشية في النصّ المستخرج
REF_RE = re.compile("(\\d+)")
EXCL = common.EXCLUSIONS   # كتاباتُ الباحث نفسه في المكتبة: لا تُعدّ مصدرًا للنقل
OWN_TITLE = re.compile(r"^(?:المبحث|الفصل|المطلب|التمهيد|المقدمة|الخاتمة|بسم الله الرحمن الرحيم$|المستند\s*\d*$)")
QUOTE_RE = re.compile(r"«([^«»]{8,}?)»|\"([^\"]{8,}?)\"|“([^“”]{8,}?)”")


# ───────────────────────── قراءةُ ملفّ وورد ─────────────────────────

def _runs(xml: str) -> str:
    out = []
    for m in re.finditer(r'<w:t(?: [^>]*)?>(.*?)</w:t>|<w:footnoteReference [^>]*w:id="(\d+)"[^>]*/>|<w:tab/>|<w:br/>',
                         xml, re.S):
        if m.group(1) is not None:
            out.append(html.unescape(m.group(1)))
        elif m.group(2):
            out.append(REF % m.group(2))
        else:
            out.append(" ")
    return "".join(out)


def read_docx(path: pathlib.Path) -> tuple:
    """(فقرات المتن، الحواشي {رقم: نصّ})."""
    z = zipfile.ZipFile(path)
    doc = z.read("word/document.xml").decode("utf-8")
    paras = [_runs(p) for p in re.findall(r"<w:p[ >].*?</w:p>", doc, re.S)]
    notes = {}
    if "word/footnotes.xml" in z.namelist():
        fx = z.read("word/footnotes.xml").decode("utf-8")
        for m in re.finditer(r'<w:footnote [^>]*w:id="(-?\d+)"[^>]*>(.*?)</w:footnote>', fx, re.S):
            t = re.sub(r"^\s*\(\s*\)\s*", "", _runs(m.group(2))).strip()
            if int(m.group(1)) > 0:
                notes[m.group(1)] = t
    return [p.strip() for p in paras], notes


# ───────────────────────── الحاشية: الكتابُ والصفحة ─────────────────────────

SAME = re.compile(r"^(?:انظر:?\s*)?(?:المصدر|المرجع)\s+(?:نفسه|السابق)|^نفسه")


def parse_note(text: str, prev: dict) -> dict:
    """الكتابُ الأوّل في الحاشية وصفحاتُه، و«المصدر نفسه/السابق» يُردّ إلى ما قبله."""
    t = text.strip().rstrip(".").strip()
    see = t.startswith("انظر")
    first = re.split(r"[،,]\s*(?:و\s*)?(?:انظر:?)?\s*(?=\S)|\s+وانظر:?\s*", t)[0]
    m = re.match(r"(?:انظر:?\s*)?(.*?)\s*\(([^()]*)\)\s*$", first)
    title, loc = (m.group(1), m.group(2)) if m else (re.sub(r"^انظر:?\s*", "", first), "")
    if SAME.match(t):
        title = prev.get("title", "")
        if not loc:
            loc = prev.get("loc", "")
    vol, pages = None, []
    l2 = loc.translate(DIG).replace("–", "-").replace("—", "-")
    mv = re.match(r"\s*(\d+)\s*/\s*(.*)", l2)
    if mv:
        vol, l2 = int(mv.group(1)), mv.group(2)
    for a, b in re.findall(r"(\d+)\s*(?:-\s*(\d+))?", re.sub(r"^\s*ص\s*", "", l2)):
        a = int(a)
        b = int(b) if b else a
        if b < a:                     # ٢٩–٣٠ تُكتب أحيانًا ٢٩-٣٠، و١٥٣-٥٥ تعني ١٥٣-١٥٥
            b = int(str(a)[:len(str(a)) - len(str(b))] + str(b))
        pages.append((a, b))
    return {"text": text, "title": title.strip(), "loc": loc, "vol": vol, "pages": pages, "see": see,
            "others": t[len(first):].strip(" ،,")}


def excluded(con) -> dict:
    """كتاباتُ الباحث في المكتبة {رقم: عنوان}. تُحفظ في «استثناءات-التدقيق.json» فيعدّلها؛ وأوّلَ مرّةٍ تُقترح
    من العناوين التي على هيئة أقسام الرسالة (المبحث، الفصل…)."""
    data = common.read_json(EXCL)
    if data is None:
        data = {"شرح": "كتاباتُك أنت في المكتبة (بحوثُك وفصولُك ومسوّداتُها): لا يعدّها المدقّق مصدرًا.",
                "books": {str(b["id"]): b["title"] for b in con.execute("SELECT id, title FROM books")
                          if OWN_TITLE.match((b["title"] or "").strip())}}
        common.write_json(EXCL, data)
    return {int(k): v for k, v in data.get("books", {}).items()}


def find_books(con, title: str) -> list:
    """كتبُ المكتبة التي يوافق عنوانُها عنوانَ الحاشية: [(رقم، العنوان، الدرجة)] الأقربُ أوّلًا."""
    if not title:
        return []
    nt = " ".join(arabic.normalize(re.sub(r"[+_]", " ", title)).split())
    words = [w for w in nt.split() if len(w) > 2 and w not in ("في", "شرح", "علي", "من", "عن")]
    out = []
    own = excluded(con)
    for b in con.execute("SELECT id, title, series, path FROM books WHERE state != 'missing'"):
        if b["id"] in own:
            continue
        hay = " ".join(arabic.normalize(re.sub(r"[+_]", " ", " ".join(x or "" for x in
                                                                     (b["title"], b["series"], pathlib.Path(b["path"]).stem)))).split())
        if nt and nt in hay:
            score = 1.0 - (0.15 if hay.startswith("شرح") and not nt.startswith("شرح") else 0) \
                - min(0.3, (len(hay) - len(nt)) / 400)
        elif len(words) >= 2:
            got = sum(w in hay.split() for w in words)
            score = got / len(words) * 0.7 if got >= 2 else 0
        else:
            score = 0
        if score >= 0.5:
            out.append((b["id"], store.title_of(store.book(con, b["id"])), round(score, 2)))
    return sorted(out, key=lambda x: -x[2])


# ───────────────────────── استخراجُ النقول ─────────────────────────

def is_verse(p: str) -> bool:
    s = REF_RE.sub("", p).strip()
    return 0 < len(s) <= 70 and not s.endswith((".", ":", "؟")) and len(s.split()) <= 12


def extract(paras: list, notes: dict) -> list:
    items, prev = [], {}
    used_refs = set()
    for pi, p in enumerate(paras):
        if not p:
            continue
        # ١) النقولُ بين علامات التنصيص
        for m in QUOTE_RE.finditer(p):
            q = next(g for g in m.groups() if g)
            after = p[m.end():m.end() + 12]
            r = re.match(r"\s*[\(\)]*\s*(\d+)", after)
            ref = r.group(1) if r else None
            if len(q.split()) < (3 if ref else 6):   # «أول واجب على المكلف» بلا حاشية: مصطلحٌ أو عنوان، لا نقل
                continue
            items.append({"kind": "نصّ", "para": pi, "quote": REF_RE.sub("", q).strip(), "ref": ref})
            if ref:
                used_refs.add(ref)
        # ٢) الأبيات، و٣) الحكايةُ بالمعنى
        for r in REF_RE.finditer(p):
            ref = r.group(1)
            if ref in used_refs:
                continue
            used_refs.add(ref)
            if is_verse(p):
                lines, j = [p], pi - 1
                while j >= 0 and (not paras[j] or (is_verse(paras[j]) and not REF_RE.search(paras[j]))):
                    if paras[j]:
                        lines.insert(0, paras[j])
                    j -= 1
                q = " ".join(REF_RE.sub("", x).strip(" ()") for x in lines)
                items.append({"kind": "أبيات", "para": pi, "quote": q, "lines": [REF_RE.sub("", x).strip(" ()") for x in lines],
                              "ref": ref})
            else:
                ctx = REF_RE.sub("", p[max(0, r.start() - 90):r.start()]).strip(" ()")
                items.append({"kind": "حكاية", "para": pi, "quote": ctx, "ref": ref})
    items.sort(key=lambda it: (it["para"], int(it["ref"]) if it["ref"] else 10 ** 6))
    for it in items:
        if it["ref"]:
            it["note"] = parse_note(notes.get(it["ref"], ""), prev)
            if it["note"]["title"]:
                prev = it["note"]
    return items


# ───────────────────────── البحثُ عن النصّ ─────────────────────────

def chunks(quote: str, k: int = 3, most: int = 14) -> list:
    words = [w for w in arabic.normalize(quote).split() if not w.isdigit()]
    if len(words) <= k:
        return [" ".join(words)] if words else []
    starts = list(range(0, len(words) - k + 1, 2))
    if len(starts) > most:
        step = len(starts) / most
        starts = [starts[int(i * step)] for i in range(most)]
    return [" ".join(words[i:i + k]) for i in starts]


def locate(con, quote: str) -> list:
    """الصفحاتُ التي يقع فيها أكثرُ مقاطع النقل: [(رقم الكتاب، الصفحة، نسبةُ المقاطع)]."""
    cs = chunks(quote)
    if not cs:
        return []
    score = {}
    for rasm in (False, True):
        for c in cs:
            toks = bahth.query_tokens(c)
            if not toks:
                continue
            expr, seqs = bahth.build("phrase", toks, True, rasm)
            for h in bahth.search(con, expr, seqs, rasm, (0, 1), None, "book"):
                key = (h["row"]["book_id"], h["row"]["n"])
                score.setdefault(key, [set(), set()])[int(rasm)].add(c)
        best = max((len(v[0]) for v in score.values()), default=0)
        if best >= max(2, len(cs) * 0.5):
            break                         # البحثُ الدقيق كافٍ؛ والرسمُ المجرّد لما أفسدت القراءةُ الآليّة نقاطَه
    res = [(b, n, len(v[0] | v[1]) / len(cs)) for (b, n), v in score.items()]
    res = [r for r in res if r[2] >= 0.3 or (len(cs) <= 2 and r[2] > 0)]
    return sorted(res, key=lambda r: -r[2])[:8]


def similarity(con, b: int, n: int, quote: str) -> tuple:
    """أقربُ مقطعٍ في الصفحة (ومعها التالية) إلى النقل: (النسبة، المقطع، الطبقة)."""
    p = store.page(con, b, n)
    nxt = store.page(con, b, n + 1)
    best = (0.0, "", None)
    for name, text in (("متن", p["body"] or ""), ("حاشية", p["foot"] or ""),
                       ("متن", (p["body"] or "") + " " + ((nxt["body"] or "") if nxt else ""))):
        if text:
            r, near = bawwaba.closest(text, quote)
            if r > best[0]:
                best = (r, near, name)
    return best


def word_diff(quote: str, near: str) -> str:
    a, b = arabic.normalize(quote).split(), arabic.normalize(near).split()
    out = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b).get_opcodes():
        if op == "replace":
            out.append("«%s» ← في الكتاب «%s»" % (" ".join(a[i1:i2]), " ".join(b[j1:j2])))
        elif op == "delete":
            out.append("«%s» ليس في الكتاب" % " ".join(a[i1:i2]))
        elif op == "insert":
            out.append("في الكتاب زيادة «%s»" % " ".join(b[j1:j2]))
    return " · ".join(out[:6])


def page_ok(p, note: dict):
    """هل توافق صفحةُ الملف المطبوعةُ صفحاتِ الحاشية؟ True/False، أو None إن لم يُقرأ الرقمُ المطبوع."""
    if not note or not note.get("pages"):
        return None
    try:
        pr = int(str(p["printed"]).translate(DIG))
    except (TypeError, ValueError):
        # لم يُقرأ المطبوع: فإن وافقت صفحةُ الملف الحاشيةَ (كثيرٌ من الملفّات صفحاتُها صفحاتُ المطبوع) قيل ذلك
        return "file" if any(a <= p["n"] <= b for a, b in note["pages"]) else None
    return any(a - 1 <= pr <= b + 1 for a, b in note["pages"])   # ±١: النقلُ قد يبدأ في آخر الصفحة السابقة


def segments(quote: str) -> list:
    """أجزاءُ النقل بين علامات الحذف (... أو …): كلُّ جزءٍ يُقابَل وحده."""
    segs = [x.strip(" ،,.") for x in re.split(r"\.{2,}|…", quote)]
    segs = [x for x in segs if len(x.split()) >= 3]
    return segs or [quote]


def unreadable(con, book_id: int) -> bool:
    """نصُّ الكتاب في المخزن لا يُقرأ (رموزٌ مكان الحروف، أو صفحاتٌ فارغة في أكثره)."""
    rows = con.execute("SELECT body FROM pages WHERE book_id = ? ORDER BY n LIMIT 80", (book_id,)).fetchall()
    if not rows:
        return True
    bad = sum(1 for r in rows if not (r["body"] or "").strip() or arabic.is_garbage(arabic.quality(r["body"] or "")))
    return bad / len(rows) > 0.4


VPAGE = {True: "مطابق", "file": "مطابق، والصفحة توافق صفحة الملف", False: "مطابق، والصفحة تخالف",
         None: "مطابق، والصفحة لم تُقرأ"}
ELSEWHERE = 0.8       # ما وُجد في غير كتاب الحاشية لا يُذكر إلّا إن قارب النقلَ جدًّا: فالتشابهُ الضعيف عباراتٌ متداولة


def empty_pages(con, book_id: int) -> list:
    return [r["n"] for r in con.execute("SELECT n FROM pages WHERE book_id = ? AND TRIM(COALESCE(body, '')) = '' "
                                        "ORDER BY n LIMIT 6", (book_id,))]


def not_found(con, it, note, books, book_ids, pick) -> dict:
    if books and all(unreadable(con, b) for b in book_ids):
        it["verdict"] = "الكتاب في المكتبة، ونصُّه غيرُ مقروء"
    else:
        it["verdict"] = "لم يوجد" if (books or not note) else "الكتاب ليس في المكتبة"
        gaps = [(b, empty_pages(con, b)) for b in book_ids[:1]]
        if gaps and gaps[0][1]:
            it["gaps"] = "في كتاب الحاشية صفحاتٌ لم يُقرأ نصُّها (صفحة الملف %s)؛ فقد يكون النقلُ فيها" %                          "، ".join(ar(n) for n in gaps[0][1])
    if pick and pick["sim"] >= 0.45:
        it["nearest"] = pick
    return it


def check_verse(con, it, note, books, book_ids, own) -> dict:
    """الأبيات: يُبحث عن كلّ شطرٍ وحده، وتُختار الصفحةُ التي فيها أكثرُها؛ فالقراءةُ الآليّة تخلط ترتيبَ الأشطر وتُدخل
    أرقامَ الأبيات بينها، فلا تصلح مقابلةُ الأبيات نصًّا واحدًا."""
    lines = [ln for ln in it["lines"] if len(arabic.normalize(ln).split()) >= 2] or it["lines"]
    votes = {}
    for ln in lines:
        for b, n, frac in locate(con, ln):
            votes.setdefault((b, n), 0)
            votes[(b, n)] += frac
    mine = sorted({"«%s» صفحة الملف %s" % (own[b], ar(n)) for (b, n) in votes if b in own})
    if mine:
        it["own"] = mine
    cands = []
    for (b, n), v in sorted(votes.items(), key=lambda kv: -kv[1])[:8]:
        if b in own:
            continue
        sims = [similarity(con, b, n, ln) for ln in lines]
        cands.append({"book": b, "page": n, "votes": v, "line_sims": [x[0] for x in sims],
                      "near": " / ".join(x[1] for x in sims), "layer": sims[0][2],
                      "sim": round(sum(x[0] for x in sims) / len(sims), 2),
                      "lines_found": sum(1 for x in sims if x[0] >= 0.9)})
    in_cited = sorted((c for c in cands if c["book"] in book_ids and c["sim"] >= 0.6), key=lambda c: -c["sim"])
    pick = (in_cited or sorted(cands, key=lambda c: -c["sim"]) or [None])[0]
    if pick is None or pick["sim"] < (0.6 if pick["book"] in book_ids else ELSEWHERE):
        return not_found(con, it, note, books, book_ids, pick)
    b, n = pick["book"], pick["page"]
    bk, p = store.book(con, b), store.page(con, b, n)
    pick.update(cite=store.cite(bk, p), method=p["method"], printed=p["printed"])
    it["found"] = pick
    it["lines"] = lines
    exact = pick["lines_found"] == len(lines)
    if not exact:
        it["diff"] = " | ".join("الشطر «%s» (تشابه %s)" % (ln, ar(round(sm, 2)))
                                for ln, sm in zip(lines, pick["line_sims"]) if sm < 0.9)
    if b not in book_ids:
        it["verdict"] = "في كتابٍ آخر" if books else "الكتاب ليس في المكتبة، والنصّ في غيره"
    elif not exact:
        it["verdict"] = "قريبٌ بفروق"
    else:
        ok = page_ok(p, note)
        it["verdict"] = VPAGE[ok]
    if p["method"] == "ocr":
        it["ocr"] = True
    return it


def check(con, it: dict) -> dict:
    note = it.get("note") or {}
    books = find_books(con, note.get("title", "")) if note else []
    it["books"] = [{"id": b, "title": t, "score": s} for b, t, s in books[:3]]
    book_ids = [b["id"] for b in it["books"]]
    if it["kind"] == "حكاية":
        if not note.get("title"):
            it["verdict"] = "حاشيةٌ فارغة" if note else "بلا حاشية"
        else:
            it["verdict"] = "حكايةٌ بالمعنى: الكتاب في المكتبة" if books else "حكايةٌ بالمعنى: الكتاب ليس في المكتبة"
        return it
    own = excluded(con)
    if it["kind"] == "أبيات":
        return check_verse(con, it, note, books, book_ids, own)
    segs = segments(it["quote"])
    main = max(segs, key=len)
    cands, mine = [], []
    for b, n, frac in locate(con, main):
        if b in own:                      # ورد في كتاباتك أنت: يُذكر ولا يُعدّ مصدرًا
            mine.append("«%s» صفحة الملف %s" % (own[b], ar(n)))
            continue
        sims = [similarity(con, b, n, sg) for sg in segs]
        r = min(x[0] for x in sims)
        cands.append({"book": b, "page": n, "frac": round(frac, 2), "sim": r, "segs": sims,
                      "near": " … ".join(x[1] for x in sims), "layer": sims[segs.index(main)][2]})
    if mine:
        it["own"] = mine
    in_cited = sorted((c for c in cands if c["book"] in book_ids and c["sim"] >= 0.6), key=lambda c: -c["sim"])
    pick = (in_cited or sorted(cands, key=lambda c: -c["sim"]) or [None])[0]
    if pick is None or pick["sim"] < (0.6 if pick["book"] in book_ids else ELSEWHERE):
        return not_found(con, it, note, books, book_ids, pick)
    b, n = pick["book"], pick["page"]
    bk, p = store.book(con, b), store.page(con, b, n)
    gates = [bawwaba.verify(con, b, n, sg)["verdict"] for sg in segs] if it["kind"] == "نصّ" else []
    exact = (gates and all(g in bawwaba.VERDICTS[:4] for g in gates)) or pick["sim"] >= 0.97
    pick.update(cite=store.cite(bk, p), method=p["method"], printed=p["printed"], gate=" · ".join(gates))
    pick.pop("segs", None)
    it["found"] = pick
    if not exact:
        it["diff"] = " | ".join(d for d in (word_diff(sg, x[1]) for sg, x in
                                             zip(segs, [similarity(con, b, n, sg) for sg in segs])) if d)
    if not note:
        it["verdict"] = "وُجد، والنقل بلا حاشية" if exact else "قريبٌ بفروق، والنقل بلا حاشية"
    elif b not in book_ids:
        it["verdict"] = "في كتابٍ آخر" if books else "الكتاب ليس في المكتبة، والنصّ في غيره"
    elif not exact:
        it["verdict"] = "قريبٌ بفروق"
    else:
        ok = page_ok(p, note)
        it["verdict"] = VPAGE[ok]
    if p["method"] == "ocr":
        it["ocr"] = True
    return it


# ───────────────────────── العرض ─────────────────────────

def show(items: list, cov: dict, src: str) -> None:
    print("تدقيقُ إحالات: «%s»" % src)
    print(bahth.coverage_line(cov))
    counts = {}
    for it in items:
        counts[it["verdict"]] = counts.get(it["verdict"], 0) + 1
    print("الخلاصة: " + " · ".join("%s %s" % (k, ar(v)) for k, v in counts.items()) + "\n")
    for i, it in enumerate(items, 1):
        q = it["quote"] if len(it["quote"]) < 160 else it["quote"][:150] + " …"
        print("[%s] %s · %s%s" % (ar(i), it["kind"], it["verdict"], (" · حاشية %s" % ar(it["ref"])) if it["ref"] else " · بلا حاشية"))
        print("    النقل: «%s»" % q)
        if it.get("note"):
            print("    الحاشية: %s" % it["note"]["text"])
        if it.get("books"):
            print("    كتابُ الحاشية في المكتبة: " + " | ".join("[%s] %s" % (ar(b["id"]), b["title"]) for b in it["books"]))
        f = it.get("found")
        if f:
            extra = (" · %s من %s أشطر" % (ar(f["lines_found"]), ar(len(it["lines"])))) if "lines_found" in f else ""
            print("    وُجد: %s · رقم الكتاب %s · %s · تشابه %s%s%s" % (
                f["cite"], ar(f["book"]), f["layer"] or "", ar(f["sim"]), extra,
                " · قراءةٌ آليّة: يُقابَل بالصورة" if f["method"] == "ocr" else ""))
        if it.get("diff"):
            print("    الفروق: " + it["diff"])
        if it.get("gaps"):
            print("    تنبيه: " + it["gaps"])
        if it.get("own"):
            print("    وورد أيضًا في كتاباتك (لا يُعدّ مصدرًا): " + " | ".join(it["own"][:3]))
        if it.get("nearest"):
            nb = store.book(CON, it["nearest"]["book"])
            print("    أقربُ ما وُجد (تشابه %s): «%s» — %s صفحة الملف %s" % (
                ar(it["nearest"]["sim"]), it["nearest"]["near"][:120], store.title_of(nb), ar(it["nearest"]["page"])))
        print()


def to_xlsx(items: list, path: pathlib.Path, src: str, cov_line: str) -> None:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    wb = Workbook()
    ws = wb.active
    ws.title = "التدقيق"
    ws.sheet_view.rightToLeft = True
    ws.append(["تدقيقُ إحالات: " + src])
    ws.append([cov_line])
    head = ["م", "النوع", "الحكم", "النقل", "رقم الحاشية", "الحاشية", "كتابُ الحاشية في المكتبة", "موضعُه في المكتبة",
            "رقم الكتاب", "صفحة الملف", "التشابه", "الفروق", "تنبيه"]
    ws.append(head)
    colors = {"مطابق": "C6EFCE", "مطابق، والصفحة لم تُقرأ": "E2EFDA", "مطابق، والصفحة تخالف": "FFEB9C",
              "قريبٌ بفروق": "FFEB9C", "في كتابٍ آخر": "FCE4D6", "لم يوجد": "F8CBAD"}
    for i, it in enumerate(items, 1):
        f = it.get("found") or {}
        warn = []
        if it.get("ocr"):
            warn.append("قراءةٌ آليّة: قابِله بصورة الصفحة")
        if f.get("layer") == "حاشية":
            warn.append("وُجد في الحاشية")
        if it.get("gaps"):
            warn.append(it["gaps"])
        if it.get("own"):
            warn.append("ورد أيضًا في كتاباتك: " + " | ".join(it["own"][:2]))
        if "lines_found" in f:
            warn.append("%d من %d أشطر حرفيًّا" % (f["lines_found"], len(it["lines"])))
        ws.append([i, it["kind"], it["verdict"], it["quote"], it["ref"] or "", (it.get("note") or {}).get("text", ""),
                   " | ".join("[%d] %s" % (b["id"], b["title"]) for b in it.get("books", [])), f.get("cite", ""),
                   f.get("book", ""), f.get("page", ""), f.get("sim", ""), it.get("diff", ""), "؛ ".join(warn)])
        c = colors.get(it["verdict"])
        if c:
            ws.cell(ws.max_row, 3).fill = PatternFill("solid", fgColor=c)
    for row in ws.iter_rows(min_row=3):
        for cell in row:
            cell.alignment = Alignment(wrap_text=True, vertical="top")
    for cell in ws[3]:
        cell.font = Font(bold=True)
    for col, w in zip("ABCDEFGHIJKLM", (4, 8, 18, 60, 8, 30, 30, 34, 8, 8, 8, 40, 26)):
        ws.column_dimensions[col].width = w
    wb.save(path)


CON = None


def run_job(src: pathlib.Path, progress=None) -> dict:
    """يدقّق ملفّ وورد ويكتب جيسون النتيجة في «outputs»؛ progress(done, total) يُستدعى بعد كلّ نقل (لواجهة الصفحة)."""
    global CON
    CON = store.connect(readonly=True)
    paras, notes = read_docx(src)
    todo = extract(paras, notes)
    items = []
    for i, it in enumerate(todo, 1):
        items.append(check(CON, it))
        if progress:
            progress(i, len(todo))
    cov = bahth.coverage(CON)
    res = {"source": str(src), "name": src.name, "coverage": bahth.coverage_line(cov), "items": items}
    out = common.OUTPUTS / ("تدقيق - " + src.stem)
    common.write_json(out.with_suffix(".json"), res)
    res["json"] = str(out.with_suffix(".json"))
    return res


def main() -> int:
    setup_io()
    ap = argparse.ArgumentParser(prog="tadqiq.py", description="مدقّقُ إحالات الرسالة")
    ap.add_argument("docx")
    ap.add_argument("--no-xlsx", action="store_true")
    ap.add_argument("--job", help="ملفّ تقدّمٍ يكتبه المدقّق (للصفحة): النتيجةُ جيسون في «outputs»")
    ap.add_argument("--xlsx-from", help="جيسون نتيجةٍ سابقة: يُصدَّر إلى إكسل ويُطبع مساره")
    a = ap.parse_args()
    if a.xlsx_from:
        d = common.read_json(pathlib.Path(a.xlsx_from), {}) or {}
        out = pathlib.Path(a.xlsx_from).with_suffix(".xlsx")
        to_xlsx(d.get("items", []), out, d.get("name") or pathlib.Path(d.get("source", "")).name, d.get("coverage", ""))
        print(out)
        return 0
    src = pathlib.Path(a.docx)
    if not src.is_file() or src.suffix.lower() != ".docx":
        common.die("أعطني ملفّ وورد (docx) موجودًا.")
    if a.job:
        jp = pathlib.Path(a.job)

        def prog(i, n):
            common.write_json(jp, {"state": "running", "done": i, "total": n})
        try:
            res = run_job(src, prog)
            common.write_json(jp, {"state": "done", "json": res["json"]})
        except Exception as e:
            common.write_json(jp, {"state": "error", "error": "تعذّر التدقيق: %s" % e})
            return 1
        return 0
    res = run_job(src)
    cov = bahth.coverage(CON)
    show(res["items"], cov, src.name)
    if not a.no_xlsx:
        out = pathlib.Path(res["json"]).with_suffix(".xlsx")
        to_xlsx(res["items"], out, src.name, bahth.coverage_line(cov))
        print("الملفّ: " + str(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
