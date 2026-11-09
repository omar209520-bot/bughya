"""الرسمُ القديم في البحث: «الصلوة» تُوجد بالبحث عن «الصلاة»، ونصُّ الكتاب كما رُسم.

الجدول في data/old_orthography.tsv يزيد عليه المستخدم. ويُضاف الرسم المعاصر إلى صفّ البحث وحده (مثل لفظ الآيات
في ayat.py)، فكلُّ تغييرٍ في الجدول يغيّر بصمته، والبصمةُ جزءٌ من arabic.NORM_VERSION فيُعاد بناءُ جدول البحث.
"""
import hashlib
import pathlib

import arabic

TABLE = pathlib.Path(__file__).resolve().parent / "data" / "old_orthography.tsv"
PREFIX = "وفبكل"
_map = None


def _load() -> dict:
    global _map
    if _map is None:
        _map = {}
        try:
            for line in TABLE.read_text(encoding="utf-8-sig").splitlines():
                if not line.strip() or line.startswith("#") or "\t" not in line:
                    continue
                old, new = (arabic.normalize(x) for x in line.split("\t", 1))
                if old and new and old != new:      # ما يستوي بعد التطبيع لا يحتاج إضافة
                    _map[old] = new
        except OSError:
            pass
    return _map


def fingerprint() -> str:
    try:
        return hashlib.sha1(TABLE.read_bytes()).hexdigest()[:8]
    except OSError:
        return "none"


def search_extra(text: str) -> str:
    """إن كان في النصّ رسمٌ قديم: النصُّ كلُّه مطبَّعًا بالرسم المعاصر (لصفّ البحث وحده، فتصحّ العبارات المتتالية)."""
    m = _load()
    if not m or not text:
        return ""
    out, changed = [], False
    for w in arabic.normalize(text).split():
        new = m.get(w)
        if new is None:
            for k in (1, 2):                                   # والصلوة، بالصلوة، وبالصلوة
                if len(w) > k + 2 and all(ch in PREFIX for ch in w[:k]) and w[k:] in m:
                    new = w[:k] + m[w[k:]]
                    break
        changed |= new is not None
        out.append(new or w)
    return " ".join(out) if changed else ""
