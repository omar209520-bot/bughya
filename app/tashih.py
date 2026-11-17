#!/usr/bin/env python3
"""تصحيحاتُ المستخدم لكلمات الصفحات المقروءة آليًّا (أو المُعاد بناءُ نصّها)، وهي منه لا من البرنامج.

نصُّ الكتاب في المخزن لا يُغيَّر أبدًا: يُحفظ التصحيحُ هنا في ملفٍّ مستقلّ (corrections.sqlite في مجلّد البيانات)،
ويُعرض فوق النصّ في القارئ مُعلَّمًا بأنّه منك. والمخزنُ يُبنى من الكتب ويُعاد بناؤه (إعادةُ القراءة تحذف صفحات الكتاب)،
فلا يُحفظ التصحيحُ فيه.

كلُّ تصحيحٍ مفتاحُه: بصمةُ ملفّ الكتاب (لا رقمُه، فيبقى إن نُقل الكتاب أو أُعيدت قراءته)، والصفحة، والطبقة (متن · حاشية)،
وموضعُ الكلمة في الطبقة. ومعه الكلمةُ كما قُرئت: فإن أُعيدت القراءة فتغيّرت الكلمةُ في موضعها لم يُطبَّق عليها،
وطُلبت في موضعٍ قريبٍ بالكلمة نفسها؛ فإن لم توجد عُدّ التصحيحُ «لا يطابق» ولم يُعرض على كلمةٍ أخرى.

  kind = fix   صحّحها المستخدم من الصورة (fixed: ما كتبه)
  kind = ok    قال إنّها صحيحةٌ كما قُرئت، فتُرفع عنها علامةُ الشكّ
"""
import sqlite3
import threading

import common

PATH = common.DATA / "corrections.sqlite"
NEAR = 3              # إن تغيّر موضعُ الكلمة بإعادة القراءة: تُطلب بحروفها في هذا العدد من المواضع قبله وبعده
_lock = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS corrections(
  fp TEXT NOT NULL, book_id INTEGER, n INTEGER NOT NULL, layer TEXT NOT NULL, idx INTEGER NOT NULL,
  orig TEXT NOT NULL, fixed TEXT, kind TEXT NOT NULL, at TEXT,
  PRIMARY KEY(fp, n, layer, idx)
);
"""


def connect() -> sqlite3.Connection:
    common.DATA.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(PATH), timeout=30)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


def key_of(book) -> str:
    """بصمةُ الكتاب، وإلّا مسارُه (كتابٌ قديمٌ بلا بصمة)."""
    return (book["fingerprint"] or "") or ("path:" + (book["path"] or ""))


def page(book, n: int) -> list:
    """تصحيحاتُ صفحةٍ واحدة."""
    if not PATH.exists():
        return []
    with _lock:
        con = connect()
        try:
            return [dict(r) for r in con.execute("SELECT * FROM corrections WHERE fp = ? AND n = ?", (key_of(book), n))]
        finally:
            con.close()


def save(book, n: int, layer: str, idx: int, orig: str, kind: str, fixed: str = None) -> dict:
    if layer not in ("body", "foot") or kind not in ("fix", "ok"):
        raise ValueError("طبقةٌ أو نوعٌ غير معروف")
    orig = str(orig or "").strip()
    fixed = " ".join(str(fixed or "").split()) if kind == "fix" else None
    if not orig:
        raise ValueError("كلمةٌ فارغة")
    if kind == "fix" and (not fixed or len(fixed) > 80):
        raise ValueError("اكتب الكلمةَ الصحيحة")
    if kind == "fix" and fixed == orig:
        kind, fixed = "ok", None          # كتبها كما قُرئت: فهي صحيحة
    with _lock:
        con = connect()
        try:
            con.execute("INSERT OR REPLACE INTO corrections(fp, book_id, n, layer, idx, orig, fixed, kind, at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (key_of(book), book["id"], n, layer, idx, orig, fixed, kind, common.now()))
            con.commit()
        finally:
            con.close()
    return {"ok": True, "kind": kind, "fixed": fixed}


def remove(book, n: int, layer: str, idx: int) -> dict:
    if not PATH.exists():
        return {"ok": True}
    with _lock:
        con = connect()
        try:
            con.execute("DELETE FROM corrections WHERE fp = ? AND n = ? AND layer = ? AND idx = ?",
                        (key_of(book), n, layer, idx))
            con.commit()
        finally:
            con.close()
    return {"ok": True}


def apply(words: list, rows: list, layer: str) -> int:
    """يضع التصحيحاتِ على كلمات طبقةٍ (قائمةُ القواميس التي يعيدها _align مسطّحةً بترتيبها): x للمصحَّح، ok للمُقَرّ،
    وi لموضع الكلمة. ويعيد عددَ التصحيحات التي لم تجد كلمتَها (تغيّر نصُّ الصفحة بعد إعادة القراءة)."""
    for k, w in enumerate(words):
        w["i"] = k
    stale = 0
    for r in rows:
        if r["layer"] != layer:
            continue
        k = r["idx"]
        cands = [k] + [k + s * d for d in range(1, NEAR + 1) for s in (-1, 1)]
        hit = next((j for j in cands if 0 <= j < len(words) and words[j]["t"] == r["orig"]), None)
        if hit is None:
            stale += 1
            continue
        w = words[hit]
        if r["kind"] == "fix":
            w["x"] = r["fixed"]
        else:
            w["ok"] = True
        if hit != k:
            w["i0"] = k          # محفوظٌ بموضعه القديم: يُحدَّث به إن عُدّل أو أُلغي
    return stale
