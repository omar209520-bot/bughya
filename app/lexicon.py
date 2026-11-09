"""قاموسُ الكلمات المعروفة: يُبنى من الكتب التي قُرئ نصُّ ملفّها سليمًا في مكتبة المستخدم، ومعه ألفاظُ القرآن.
فائدتُه أن يُعلِّم في الصفحات المقروءة آليًّا الكلماتِ التي لا يعرفها، لتُراجَع بالصورة. ولا يُصحّح شيئًا.

قيس على صفحات المرجع بقاموسٍ من ٢٤ كتابًا: عَلَّم ٤١٪ من الكلمات الخاطئة، وكان ثلثُ ما علَّمه صحيحًا. فالكلمةُ غير
المعلَّمة قد تكون خاطئة أيضًا (كلمةٌ صحيحةٌ في غير موضعها)، ويُقال ذلك للمستخدم.
"""
import json
import re

import arabic
import common

PATH = common.DATA / "lexicon.json"
MIN_WORDS = 3000            # كلماتٌ مختلفة من كتب المستخدم النصّيّة؛ أقلُّ منها لا يُعلَّم شيء (بـ٣٧٦٧: صحّ ٧ من ١٦ معلَّمة في صفحة 06)
PREFIX = "وفبكل"
OCR_BOOKS = 3               # كلمةُ القراءة الآليّة تدخل القاموس إن وردت في هذا العدد من الكتب المختلفة
_ARABIC = re.compile("[ء-ي]")
_cache = [None, 0.0, 0]


def build(con) -> int:
    """يبني القاموس من صفحات نصّ الملفّ في الكتب التي لم يُعلَّم نصُّ ملفّها معيبًا، ويعيد عددَ كلماته."""
    from collections import Counter
    words = Counter()
    rows = con.execute("SELECT p.body, p.foot FROM pages p JOIN books b ON b.id = p.book_id "
                       "WHERE p.method = 'text' AND b.state != 'missing' AND (b.hints IS NULL OR b.hints NOT LIKE '%note%')")
    for body, foot in rows:
        for t in (body, foot):
            if t:
                words.update(w for w in arabic.normalize(t).split() if len(w) > 1 and _ARABIC.search(w))
    # وكلماتُ القراءة الآليّة التي تكرّرت في ثلاثة كتبٍ مختلفة فأكثر: خطأُ القراءة لا يتكرّر في كتبٍ مختلفة غالبًا.
    # (قيس على صفحات المرجع المقروءة آليًّا: قلّت العلاماتُ على الكلمات الصحيحة من ١٢١ إلى ٣٩،
    #  وبقي معلَّمًا ١٠٦ من ١٤٩ كلمةً خاطئةً كانت معلَّمة.)
    titles = {i: re.sub(r"[\d\s().\-_]+$", "", t or "") or str(i) for i, t in con.execute("SELECT id, title FROM books")}
    seen = {}
    for bid, body, foot in con.execute("SELECT p.book_id, p.body, p.foot FROM pages p JOIN books b ON b.id = p.book_id "
                                       "WHERE p.method = 'ocr' AND b.state != 'missing'"):
        for t in (body, foot):
            for w in arabic.normalize(t or "").split():
                if len(w) > 1 and _ARABIC.search(w) and w not in words:
                    seen.setdefault(w, set()).add(titles.get(bid, bid))
    words.update({w: 1 for w, b in seen.items() if len(b) >= OCR_BOOKS})
    lib = len(words)            # كلماتُ كتب المستخدم وحدها: بها يُحكم أنّ القاموس صالح (ألفاظُ القرآن وحدها تُعلّم نصفَ الكلمات)
    import ayat
    ayat._load()
    for v in ayat._verses:
        words.update(v["w"])
    common.write_json(PATH, {"words": dict(words), "lib": lib})
    _cache[0] = None
    return len(words)


def _load():
    try:
        mtime = PATH.stat().st_mtime
    except OSError:
        return None
    if _cache[0] is None or _cache[1] != mtime:
        data = common.read_json(PATH, {}) or {}
        _cache[0], _cache[1] = data.get("words", {}), mtime
        _cache[2] = data.get("lib", 0)
    return _cache[0]


def ready() -> bool:
    """صالحٌ إن كان في كتب المستخدم النصّيّة MIN_WORDS كلمةً مختلفة على الأقلّ (القاموسُ القديم بلا هذا العدد يُعاد بناؤه بالتحديث)."""
    w = _load()
    return bool(w) and len(_cache) > 2 and _cache[2] >= MIN_WORDS


def known(word: str) -> bool:
    """أمعروفةٌ هذه الكلمة؟ تُجرَّب بسوابقها (و، ف، ب، ك، ل) وبلا «ال». وما ليس فيه حرفٌ عربيّ (رقمٌ أو علامة) يُعدّ معروفًا."""
    w = re.sub("[^ء-ي]", "", arabic.normalize(word))
    if len(w) < 2:
        return True
    lex = _load() or {}
    for k in (0, 1, 2):
        if k and not all(c in PREFIX for c in w[:k]):
            break
        stem = w[k:]
        if stem in lex or (stem.startswith("ال") and len(stem) > 3 and stem[2:] in lex) or ("ال" + stem) in lex:
            return True
    return False
