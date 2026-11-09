"""العربيّة في محرّك البحث: التطبيع، والرسمُ المجرّد، والسوابق، وكشفُ النصّ المقلوب، وجودةُ النصّ.

التطبيعُ على طريقة برنامج الشاملة: تُحذف الحركاتُ والتطويل، وتوحَّد صورُ الألف والياء والتاء المربوطة والهمزات،
و«ابن» تُكتب «بن»، والأرقامُ المشرقيّة تُكتب لاتينيّة. ويُطبَّق على النصّ عند الحفظ وعلى السؤال عند البحث فيتطابقان.
وتغييرُ شيءٍ هنا يلزمه رفعُ NORM_VERSION، فيُعاد بناءُ جدول البحث من النصوص المحفوظة (maktaba.py rebuild-search).

الرسمُ المجرّد (من «سَبْر الوارث»): الحروفُ على هيكلها غير المنقوط، فتتطابق كلمتان لم تختلفا إلّا في النقاط.
وذاك خطأُ القراءة الآليّة الأشيع («قهرس» ← «فهرس»). وهو طبقةُ بحثٍ متسامحة، لا الأصل.
"""
import re
import unicodedata

NORM_VERSION = "3"

# ما يُحذف: الحركات وعلاماتُ الضبط القرآنيّ والتطويل، وصورُ الحركات المنفصلة، ومحارفُ الاتّجاه الخفيّة
_DROP = [*range(0x0610, 0x061B), *range(0x064B, 0x0660), 0x0670, 0x0640, *range(0x06D6, 0x06EE),
         *range(0xFE70, 0xFE80), 0x200B, 0x200C, 0x200D, 0x200E, 0x200F, 0x061C,
         *range(0x202A, 0x202F), *range(0x2066, 0x206A), 0xFEFF, 0x00AD]

_UNIFY = {
    "أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا", "ٲ": "ا", "ٳ": "ا", "ٵ": "ا",
    "ى": "ي", "ی": "ي", "ئ": "ي", "ې": "ي", "ۍ": "ي",
    "ة": "ه", "ۀ": "ه", "ە": "ه", "ھ": "ه", "ہ": "ه",
    "ؤ": "و", "ٶ": "و",
    "ک": "ك", "ڪ": "ك",
}
_TABLE = {c: None for c in _DROP}
_TABLE.update({ord(k): v for k, v in _UNIFY.items()})
_TABLE.update({0x0660 + i: str(i) for i in range(10)})
_TABLE.update({0x06F0 + i: str(i) for i in range(10)})

# الصورُ العرضيّة للحروف (ﺷ ﻻ ﷲ…) تُردّ إلى حروفها. أمّا صورُ الحركات (FE70–FE7F) فلها خريطتُها في clean_raw.
_PRES = re.compile("[ﭐ-﷿ﺀ-ﻼ]")
_LIG = {"ﷲ": "الله", "ﷺ": "صلى الله عليه وسلم", "ﷻ": "جل جلاله", "﷽": "بسم الله الرحمن الرحيم"}
_SEP = re.compile(r"[\W_]+")
_IBN = re.compile(r"(?<!\S)ابن(?!\S)")

_RASM = {}
for _group in ("بتثني", "جحخ", "دذ", "رز", "سش", "صض", "طظ", "عغ", "فق"):
    for _c in _group:
        _RASM[ord(_c)] = _group[0]


def _pres(m: re.Match) -> str:
    ch = m.group()
    return _LIG.get(ch) or unicodedata.normalize("NFKC", ch)


def normalize(text: str) -> str:
    """النصُّ مطبَّعًا: كلماتٌ بينها مسافةٌ واحدة."""
    if not text:
        return ""
    if _PRES.search(text):
        text = _PRES.sub(_pres, text)
    text = _SEP.sub(" ", text.translate(_TABLE).lower())
    return _IBN.sub("بن", text).strip()


def normalize_map(raw: str):
    """(النصّ المطبَّع، ولكلّ حرفٍ فيه موضعُه في الأصل) — لقصّ المقتطفات من النصّ الأصليّ ومطابقة النقول.
    يطابق normalize في كلماته، لكنّه يُبقي كلَّ فاصلٍ مسافةً ليحفظ المواضع."""
    out, idx = [], []
    for i, ch in enumerate(raw):
        e = _LIG.get(ch) or (unicodedata.normalize("NFKC", ch) if _PRES.match(ch) else ch)
        for c in e.translate(_TABLE).lower():
            if not c.isalnum():
                c = " "
            out.append(c)
            idx.append(i)
    norm = "".join(out)
    # «ابن» ← «بن»: تُسقط ألفُ الكلمة المفردة
    drop = {m.start() for m in _IBN.finditer(norm)}
    if drop:
        norm = "".join(c for j, c in enumerate(norm) if j not in drop)
        idx = [x for j, x in enumerate(idx) if j not in drop]
    return norm, idx


_TOKEN = re.compile(r"[^\W_]+")


def tokens(norm: str):
    """كلماتُ نصٍّ مطبَّع مع مواضعها: [(الكلمة، البداية، النهاية)]."""
    return [(m.group(), m.start(), m.end()) for m in _TOKEN.finditer(norm)]


def rasm(norm: str) -> str:
    """الرسمُ المجرّد لنصٍّ مطبَّع."""
    return norm.translate(_RASM)


# ───────────────────────── النصُّ الأصليّ للعرض والحفظ ─────────────────────────

_MARK_PRES = {0xFE70: "ً", 0xFE71: "ً", 0xFE72: "ٌ", 0xFE74: "ٍ", 0xFE76: "َ",
              0xFE77: "َ", 0xFE78: "ُ", 0xFE79: "ُ", 0xFE7A: "ِ", 0xFE7B: "ِ",
              0xFE7C: "ّ", 0xFE7D: "ّ", 0xFE7E: "ْ", 0xFE7F: "ْ"}
_INVISIBLE = {c: None for c in (0x200B, 0x200E, 0x200F, 0x061C, *range(0x202A, 0x202F),
                                *range(0x2066, 0x206A), 0xFEFF, 0x00AD)}
_INVISIBLE.update(_MARK_PRES)
_INVISIBLE[0x00A0] = " "


def clean_raw(text: str) -> str:
    """النصُّ كما يُحفظ ويُعرض: الصورُ العرضيّة حروفًا، بلا محارف خفيّة، والحركاتُ باقية."""
    if not text:
        return ""
    if _PRES.search(text):
        text = _PRES.sub(_pres, text)
    text = text.translate(_INVISIBLE)
    text = re.sub(r"[ \t]+", " ", text)
    return "\n".join(l.strip() for l in text.splitlines()).strip()


# ───────────────────────── السوابق ─────────────────────────

def variants(tok: str) -> set:
    """صورُ الكلمة بسوابقها: الواو والفاء، والباء والكاف واللام، و«لل» مع التعريف.
    «الصلاة» ← والصلاة، فالصلاة، بالصلاة، كالصلاة، للصلاة، وللصلاة… · «صلاة» ← وصلاة، بصلاة، لصلاة…"""
    out = {c + p + tok for c in ("", "و", "ف") for p in ("", "ب", "ك", "ل")}
    # «ال» قد تكون أداةَ التعريف (الصلاة ← للصلاة) أو أوّلَ الكلمة (ألفاظ ← لألفاظ)، فالصورتان كلتاهما
    if len(tok) >= 4 and tok.startswith("ال"):
        stem = tok[2:]
        out |= {c + ("ل" + stem if stem.startswith("ل") else "لل" + stem) for c in ("", "و", "ف")}
    return out


# ───────────────────────── النصُّ المقلوب ─────────────────────────
# بعضُ ملفّات بي دي إف تحفظ العربيّة بترتيب رسمها من اليسار، فتُستخرج كلماتُها معكوسة.

_FWD = {"من", "في", "علي", "الله", "التي", "الذي", "هذا", "كان", "قال", "الي", "عن"}
_REV = {w[::-1] for w in _FWD}
_LTR_RUN = re.compile(r"[0-9A-Za-z٠-٩][0-9A-Za-z٠-٩.,:/\-]*")
_MIRROR = str.maketrans("()[]{}<>«»", ")(][}{><»«")
_MARKS_FIRST = re.compile("([ً-ٰٟ]+)([^ً-ٰٟ])")


def looks_reversed(norm_text: str) -> bool:
    words = norm_text.split()
    fwd = sum(1 for w in words if w in _FWD)
    rev = sum(1 for w in words if w in _REV)
    return rev >= 3 and rev > 2 * fwd


def unreverse_line(line: str) -> str:
    """يعكس سطرًا محفوظًا بترتيب رسمه: تُقلب الحروف، وتُعاد الأرقامُ واللاتينيّة إلى اتّجاهها،
    وتُعكس الأقواس، وتُردّ كلُّ حركةٍ بعد حرفها."""
    s = line[::-1]
    s = _LTR_RUN.sub(lambda m: m.group()[::-1], s)
    s = s.translate(_MIRROR)
    return _MARKS_FIRST.sub(r"\2\1", s)


# ───────────────────────── جودةُ النصّ ─────────────────────────

COMMON = set("""من في علي الي عن ان ما لا الله قال هذا ذلك التي الذي كان هو هي او ثم قد لم لن لو اذا كل بعض بين عند
حتي مع غير هذه تلك الا انه ولا وقد فان وان وهو وهي فيه عليه اليه منه عنه به له بن ابو ابي يا ايضا اي كما مثل عليهم
فيها منها بها لها ذكر رضي رحمه صلي وسلم تعالي سبحانه وفي ومن وعلي فلا فقد اما لان كانت يكون قوله اذ""".split())


def quality(text: str) -> dict:
    """مقاييسُ جودة نصّ صفحة: كم حرفًا، وكم نسبةُ العربيّ، وكم نسبةُ رموز الاستعمال الخاصّ، وكم نسبةُ الكلمات الشائعة."""
    letters = [c for c in text if c.isalpha()]
    n = len(letters)
    arab = sum(1 for c in letters if "؀" <= c <= "ۿ" or "ﭐ" <= c <= "﻿")
    pua = sum(1 for c in text if 0xE000 <= ord(c) <= 0xF8FF)
    # خريطةُ خطٍّ مكسورة تُخرج «�» أو حروفًا عبريّة مكان العربيّة (وُجد في ١٤ كتابًا قُرئت رموزًا)
    bad = sum(1 for c in text if c == "�" or "֐" <= c <= "׿")
    words = normalize(text).split()
    common = sum(1 for w in words if w in COMMON)
    return {"letters": n, "arabic": arab / n if n else 0.0, "pua": pua / len(text) if text else 0.0,
            "words": len(words), "common": common / len(words) if words else 0.0,
            "bad": bad / len(text) if text else 0.0}


def is_garbage(q: dict) -> bool:
    """نصٌّ مستخرجٌ لا يُقرأ (خريطةُ حروفٍ مكسورة في الملفّ): رموزٌ خاصّة كثيرة، أو عربيّةٌ بلا كلماتٍ شائعة."""
    if q.get("bad", 0) > 0.05:
        return True
    if q["letters"] < 25:
        return False
    if q["pua"] > 0.05:
        return True
    return q["arabic"] > 0.5 and q["words"] >= 40 and q["common"] < 0.02
