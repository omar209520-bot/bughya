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


# ───────────────────── آياتٌ مكتوبةٌ بخطّ المصحف (QCF) في ملفّات وورد ─────────────────────
# رموزُ خطوط مجمّع الملك فهد كلماتٌ مرسومةٌ لا حروفَ لها في الملفّ، فتُقرأ صورتُها آليًّا (pdf.py)، ثمّ تُطابَق هنا
# بآيات القرآن. والموضعُ موضعُ آيةٍ يقينًا (هو بخطّ المصحف)، فالمطابقةُ أرحب من find: محاذاةُ كلمات القراءة بكلمات الآيات
# كلمةً كلمة مع احتمال أخطاء القراءة واختلافِ الرسم العثمانيّ عن الإملائيّ («الكتب» و«الكتاب»، «الصلوة» و«الصلاة»).
# فإن صحّت المحاذاةُ أُخذت كلماتُ الآيات من النصّ المشكول، وإلّا بقي ما قرأته الآلة كما هو. لا يُخمَّن شيء.
MUSHAF_SIM, MUSHAF_COVER, MUSHAF_MIN = 0.72, 0.7, 4
_DIGITS_AR = str.maketrans("0123456789", "٠١٢٣٤٥٦٧٨٩")
_pairs, _flat = {}, []


def _flat_load() -> None:
    if _flat:
        return
    _load()
    for i, v in enumerate(_verses):
        voc = v["text"].split()
        if len(voc) != len(v["w"]):
            voc = v["w"]
        for k, x in enumerate(v["w"]):
            _flat.append((i, k, arabic.rasm(x), voc[k]))
    for n in range(len(_flat) - 1):
        _pairs.setdefault((_flat[n][2], _flat[n + 1][2]), []).append(n)


def _sim(a: str, b: str) -> float:
    if a == b:
        return 1.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def _align(r: list, near=None):
    """أحسنُ محاذاةٍ موضعيّةٍ لكلمات القراءة (برسمها) بموضعٍ من القرآن ← [(رقم الكلمة في r، موضعها في _flat، التشابه)] أو None.
    near: (من، إلى) في _flat: يُبحث فيه وحده، وهو تتمّةُ مقطعٍ طوبق قبله أو بدايتُه، فتكفي فيه كلمتان."""
    if near:
        wins, need = [(max(0, near[0]), min(len(_flat), near[1]))], 2
    else:
        hits = collections.Counter()
        for p in range(len(r) - 1):
            for n in _pairs.get((r[p], r[p + 1]), ()):
                hits[n - p] += 1                    # موضعُ أوّل كلمةٍ لو بدأت القراءةُ من هنا
        wins = [(max(0, st - 6), min(len(_flat), st + len(r) + 12)) for st, _c in hits.most_common(8)]
        need = MUSHAF_MIN
    best = None
    for lo, hi in wins:
        win = _flat[lo:hi]
        # محاذاةٌ موضعيّة (سميث–وترمان): مطابقةٌ بتشابه الرسم، وفجوةٌ بغرامة
        rows, cols = len(r) + 1, len(win) + 1
        S = [[0.0] * cols for _ in range(rows)]
        B = [[0] * cols for _ in range(rows)]
        top = (0.0, 0, 0)
        for i in range(1, rows):
            for j in range(1, cols):
                s = _sim(r[i - 1], win[j - 1][2])
                opts = (0.0, S[i - 1][j - 1] + (2 * s - 1 if s >= 0.5 else -1.0), S[i - 1][j] - 0.6, S[i][j - 1] - 0.6)
                k = max(range(4), key=lambda q: opts[q])
                S[i][j], B[i][j] = opts[k], k
                if S[i][j] > top[0]:
                    top = (S[i][j], i, j)
        i, j, pairs = top[1], top[2], []
        while i > 0 and j > 0 and B[i][j]:
            if B[i][j] == 1:
                pairs.append((i - 1, lo + j - 1, _sim(r[i - 1], win[j - 1][2])))
                i, j = i - 1, j - 1
            elif B[i][j] == 2:
                i -= 1
            else:
                j -= 1
        pairs.reverse()
        # المحاذاةُ قد تمتدّ من آيةٍ إلى أوّل التي تليها في المصحف بكلماتٍ ضعيفة الشبه (وليست في الصفحة): فتُقصّ من طرفيها
        # كلُّ آيةٍ لا يشهد لها كلمتان قويّتا الشبه (أو كلمتُها إن كانت كلمةً واحدة: «الم»)، وما قُصّ يُطابَق وحده بعد ذلك
        while pairs:
            for side in (0, -1):
                v = _flat[pairs[side][1]][0]
                part = [p for p in pairs if _flat[p[1]][0] == v]
                if len(part) < len(pairs) and sum(1 for p in part if p[2] >= 0.7) < min(2, len(_verses[v]["w"])):
                    pairs = [p for p in pairs if _flat[p[1]][0] != v]
                    break
            else:
                break
        if not pairs or sum(1 for p in pairs if p[2] >= 0.5) < need or sum(p[2] for p in pairs) / len(pairs) < MUSHAF_SIM:
            continue
        if best is None or top[0] > best[0]:
            best = (top[0], pairs)
    if best is None:
        return None
    pairs = best[1]
    # طرفا المدى: كلمةٌ أو كلمتان أخطأتهما القراءةُ عند الطرف تقطعان المحاذاة («رز"» لـ«رزقناهم»). فإن وافقت آخرُ كلمةٍ
    # مقروءةٍ بعد المدى كلمةً من بقيّة الآية نفسِها، وما بينهما قليل، امتدّ المدى إليها. ومثلُه في أوّله.
    i_end, j_end = pairs[-1][0], pairs[-1][1]
    rest = len(r) - 1 - i_end
    if 0 < rest <= 3:
        for e in range(j_end + rest, min(len(_flat), j_end + rest + 3)):
            if _flat[e][0] != _flat[j_end][0]:
                break
            if _sim(r[-1], _flat[e][2]) >= 0.7:
                pairs.append((len(r) - 1, e, _sim(r[-1], _flat[e][2])))
                break
    i_st, j_st = pairs[0][0], pairs[0][1]
    if 0 < i_st <= 3:
        for e in range(j_st - i_st, max(-1, j_st - i_st - 3), -1):
            if e < 0 or _flat[e][0] != _flat[j_st][0]:
                break
            if _sim(r[0], _flat[e][2]) >= 0.7:
                pairs.insert(0, (0, e, _sim(r[0], _flat[e][2])))
                break
    return pairs


def _matches(r: list, off: int = 0, before=None, after=None) -> list:
    """كلُّ مواضع القرآن في كلمات القراءة: أحسنُها أوّلًا، ثمّ ما قبله وما بعده كلٌّ وحده (الصفحةُ قد تجمع آياتٍ من سورٍ شتّى).
    وما بعد مقطعٍ مطابَقٍ يُجرَّب أوّلًا تتمّةً له في المصحف (after: موضعُ آخر كلمةٍ فيه)، وما قبله بدايةً له (before)."""
    if not r:
        return []
    pairs = None
    if after is not None:
        pairs = _align(r, (after + 1, after + len(r) + 6))
        if pairs and (pairs[0][0] > 1 or pairs[0][1] - after - 1 > 2):
            pairs = None                            # ليست تتمّةً متّصلة: تبدأ من أوّل الكلمات، وبعد آخر المطابَق مباشرة
    if not pairs and before is not None:
        pairs = _align(r, (before - len(r) - 6, before))
        if pairs and (pairs[-1][0] < len(r) - 2 or before - 1 - pairs[-1][1] > 2):
            pairs = None
    if not pairs and len(r) >= MUSHAF_MIN:
        pairs = _align(r)
    if not pairs:
        return []
    a, b = pairs[0][0], pairs[-1][0]
    return (_matches(r[:a], off, before=pairs[0][1]) + [[(i + off, j, s) for i, j, s in pairs]]
            + _matches(r[b + 1:], off + b + 1, after=pairs[-1][1]))


def _junk(t: str) -> bool:
    """حرفٌ واحدٌ وحده بجوار آيةٍ مطابَقة: ليس كلمةً من القرآن (الحروفُ المقطّعة تدخل في المطابقة)، بل قوسُ الآية مقروءًا حرفًا."""
    n = arabic.normalize(t).replace(" ", "")
    return len(n) == 1 and "ء" <= n <= "ي"


def mushaf(words: list):
    """words: كلماتُ القراءة الآليّة لمواضع خطّ المصحف في الصفحة بترتيب القراءة.
    ← (كلماتُ الناتج، {رقمُ الكلمة في words: موضعُ أوّل ما يقابلها في الناتج}) — أو None إن لم يُطابَق شيء.
    ما طوبق أُخذ لفظُه من النصّ المشكول وبين كلّ آيتين منه رقمُ الأولى، وما لم يُطابَق بقي كما قرأته الآلة."""
    _flat_load()
    toks = [(k, arabic.normalize(t)) for k, t in enumerate(words)]
    toks = [(k, t) for k, t in toks if t and not t.isdigit() and re.search("[ء-ي]", t)]
    found = _matches([arabic.rasm(t.replace(" ", "")) for _, t in toks])
    if not found:
        return None
    out, where, k = [], {}, 0
    for pairs in found:
        first_raw, last_raw = toks[pairs[0][0]][0], toks[pairs[-1][0]][0]
        while k < first_raw:
            where[k] = len(out)
            if not (k == first_raw - 1 and _junk(words[k])):    # قوسُ الآية «﴿» يُقرأ حرفًا ملاصقًا لأوّلها
                out.append(words[k])
            k += 1
        c, d, pos = pairs[0][1], pairs[-1][1], {}
        for n in range(c, d + 1):
            pos[n] = len(out)
            out.append(_flat[n][3])
            i, w = _flat[n][0], _flat[n][1]
            if w == len(_verses[i]["w"]) - 1 and n < d:    # رقمُ الآية بين آيتين في المقطع؛ وبعد آخره لا يُكتب
                out.append(str(_verses[i]["aya"]).translate(_DIGITS_AR))  # (المقتبَسُ يُختم غالبًا بلا رقم، كما في الصفحة 03)
        for ti, n, _ in pairs:
            where.setdefault(toks[ti][0], pos[n])
        while k <= last_raw:                        # ما لم يُحاذَ: إلى أقرب كلمةٍ محاذاةٍ قبله
            where.setdefault(k, where.get(k - 1, pos[c]))
            k += 1
        # رقمُ الآية الذي قرأته الآلةُ بعد المدى زائدٌ إذ كُتب الرقمُ من النصّ، وقوسُ الآية «﴾» يُقرأ حرفًا
        while k < len(words) and (arabic.normalize(words[k]).isdigit() or _junk(words[k])):
            where[k] = len(out)
            k += 1
    while k < len(words):
        where[k] = len(out)
        out.append(words[k])
        k += 1
    return out, where
