"""مطابقةُ الآيات: يبحث في نصّ الصفحة عمّا يقارب آيات القرآن، ولا يغيّر نصّ الكتاب.

النصّ المرجعيّ في data/ (إملائيّ بلا تشكيل للمطابقة، ومشكول للعرض).
المطابقةُ بالرسم المجرّد لتتحمّل أخطاء النقاط في القراءة الآليّة، ثمّ يُشترط تشابهُ النصّين.
    آية     ٧ كلمات فأكثر، أو آيةٌ كاملة من ٤ كلمات فأكثر
    عبارة   ٥ أو ٦ كلمات: قد تتكرّر في القرآن وفي كلام الناس، فلا يُجزم فيها برقم آية
"""
import collections
import difflib
import pathlib
import re

import arabic

DATA = pathlib.Path(__file__).resolve().parent / "data"
N, MIN_PHRASE, MIN_AYA, MIN_FULL, MIN_SIM = 3, 5, 7, 4, 0.80
LINE = re.compile(r"\s*\{(.*)\}\s*\[(.+):(\d+)\]")
_verses, _index = [], {}


def _load() -> None:
    if _verses:
        return
    plain = (DATA / "QURANNODIC.txt").read_bytes().decode("cp1256").splitlines()
    voc = (DATA / "QURANTXT.txt").read_bytes().decode("cp1256").splitlines()
    index = collections.defaultdict(list)
    for a, b in zip(plain, voc):
        m, v = LINE.match(a), LINE.match(b)
        if not m or not v:
            continue
        w = arabic.normalize(m.group(1)).split()
        r = [arabic.rasm(x) for x in w]
        i = len(_verses)
        _verses.append({"sura": m.group(2), "aya": int(m.group(3)), "text": v.group(1).strip(), "w": w})
        for k in range(len(r) - N + 1):
            index[tuple(r[k:k + N])].append((i, k))
    _index.update(index)


def _spans(w: list, r: list) -> list:
    hits = collections.defaultdict(list)
    for p in range(len(r) - N + 1):
        for i, k in _index.get(tuple(r[p:p + N]), ()):
            hits[i].append((p, k))
    out = []
    for i, hs in hits.items():
        hs.sort()
        runs, run = [], [hs[0]]
        for h in hs[1:]:
            dp, dk = h[0] - run[-1][0], h[1] - run[-1][1]
            if 0 < dp <= N + 3 and 0 < dk <= N + 3 and abs(dp - dk) <= 2:
                run.append(h)
            else:
                runs.append(run)
                run = [h]
        runs.append(run)
        vw = _verses[i]["w"]
        for run in runs:
            a, b = run[0], run[-1]
            n = b[1] - a[1] + N
            full = n >= len(vw)
            if n < MIN_PHRASE and not (full and n >= MIN_FULL):
                continue
            mine, ref = " ".join(w[a[0]:b[0] + N]), " ".join(vw[a[1]:b[1] + N])
            if difflib.SequenceMatcher(None, mine, ref).ratio() >= MIN_SIM:
                out.append({"st": a[0], "en": b[0] + N, "i": i, "n": n, "full": full, "mine": mine, "ref": ref})
    return out


def search_extra(text: str) -> str:
    """لفظُ الآيات الصحيح لما أخطأت القراءةُ فيه من الصفحة، يُضاف إلى صفّ البحث وحده فيجدها الباحث؛ ولا يدخل نصَّ الكتاب.
    ما يُكتب هنا جزءٌ من صفّ البحث: فكلُّ تغييرٍ في المطابقة أو في data/ يلزمه رفعُ arabic.NORM_VERSION."""
    return " ".join(x["ref"] for x in find(text) if x["sure_words"] and x["ref"] != x["words"])


_BRACKETS = "﴿﴾{}"
_CITE_WORDS = ("تعالي", "تعالى", "سبحانه", "وجل", "قوله", "لقوله", "كقوله", "وقوله", "التنزيل", "الايه", "الآية", "قال", "يقول")


_NUM = __import__("re").compile(r"^[(\[]*[0-9٠-٩]{1,3}[)\]]*[.،]?$")


def _cited(raw: list, a: int, b: int, n: int) -> bool:
    """أمستشهَدٌ بها آيةً، لا مقتبَسةٌ في كلام المؤلّف؟ بين أقواس الآيات (أو ما تقرؤه القراءةُ الآليّة «{» أو «((»)،
    أو قبلها بثلاث كلماتٍ «قال تعالى» و«قوله» ونحوُهما، أو بعدها رقمُ الآية أو اسمُ السورة أو رقمُ حاشية، أو طالت
    (عشرُ كلماتٍ فأكثر: لا تُقتبس آيةٌ بهذا الطول في كلام المؤلّف إلّا نادرًا)."""
    if n >= 10:
        return True
    after = raw[b + 1:b + 4]
    if any(_NUM.match(t) or "سورة" in t or t.startswith("[") for t in after):
        return True
    near = " ".join(raw[max(0, a - 1):b + 2])
    if any(c in near for c in _BRACKETS) or "((" in near or "))" in near:
        return True
    if a < len(raw) and raw[a][:1] in "(«" and b < len(raw) and raw[b][-1:] in ")»":
        return True
    before = [arabic.normalize(t) for t in raw[max(0, a - 3):a]]
    return any(x in before or ("ال" + x) in before for x in (arabic.normalize(c) for c in _CITE_WORDS))


def find(text: str) -> list:
    """[{kind: آية|عبارة، words: ما في الكتاب، verses: [{sura, aya, text}]}] مرتَّبةً بموضعها في الصفحة."""
    _load()
    raw = (text or "").split()
    w, at = [], []                  # الكلماتُ مطبَّعةً، وموضعُ كلٍّ منها في النصّ الأصليّ (لمعرفة ما حولها)
    for k, t in enumerate(raw):
        for x in arabic.normalize(t).split():
            w.append(x); at.append(k)
    spans = _spans(w, [arabic.rasm(x) for x in w])
    spans.sort(key=lambda s: (-s["n"], s["st"]))
    groups = []
    for s in spans:
        for g in groups:
            if s["st"] >= g["st"] and s["en"] <= g["en"]:   # داخل مقطعٍ أطول، أو مساوٍ له فهي الآية مكرَّرة
                if s["n"] == g["n"] and s["st"] == g["st"]:
                    g["ids"].append(s["i"])
                break
        else:
            groups.append({"st": s["st"], "en": s["en"], "n": s["n"], "full": s["full"], "mine": s["mine"], "ref": s["ref"], "ids": [s["i"]]})
    groups.sort(key=lambda g: g["st"])
    out = []
    for g in groups:
        sure = (g["n"] >= MIN_AYA or (g["full"] and g["n"] >= MIN_FULL)) and len(g["ids"]) == 1
        out.append({"kind": "آية" if sure else "عبارة", "words": g["mine"], "ref": g["ref"],
                    "cited": _cited(raw, at[g["st"]], at[min(g["en"], len(at)) - 1], g["n"]),
                    "sure_words": g["n"] >= MIN_AYA or (g["full"] and g["n"] >= MIN_FULL),
                    "verses": [{k: _verses[i][k] for k in ("sura", "aya", "text")} for i in g["ids"][:6]],
                    "more": max(0, len(g["ids"]) - 6)})
    return out
