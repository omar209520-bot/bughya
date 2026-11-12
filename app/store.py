"""مخزنُ النصّ: قاعدةٌ واحدة فيها كتبُ المستخدم وصفحاتُها بنصّها كما قُرئ، وجدولُ بحثٍ نصّيٍّ مطبَّع.

الجداول:
    books   الكتاب: ملفُّه، وعنوانُه ومؤلّفُه ووفاتُه وفنُّه (إن سُجّلت)، ومجلّدُه في السلسلة، وحالُ قراءته
    pages   الصفحة (أو القطعة): رقمُها في الملفّ، ورقمُها المطبوع إن عُرف، وطريقةُ قراءتها (نصُّ الملفّ أو القراءة الآليّة)،
            والرأسُ والمتنُ والحاشيةُ كلٌّ في حقل، ومواضعُ أسطرها مضغوطةً (لتظليل الموضع في صورة الصفحة)
    toc     عناوينُ الكتاب (من فهرسه المدمج في الملفّ، أو عناوين وورد)
    fts     جدولُ البحث: لكلّ صفحةٍ صفّان، المتنُ والحاشية، وفي كلٍّ النصُّ مطبَّعًا ورسمُه المجرّد.
            رقمُ الصفّ = رقمُ الصفحة × ٢ + (٠ للمتن، ١ للحاشية). ولا يحفظ نصًّا: النصُّ في pages وحدها.
"""
import json
import sqlite3
import zlib

import arabic
import ayat
import orth
from common import STORE_DB, STORE_DIR

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS books(
  id INTEGER PRIMARY KEY,
  path TEXT UNIQUE NOT NULL,
  source TEXT,
  kind TEXT,
  size INTEGER, mtime REAL, fingerprint TEXT,
  title TEXT, title_source TEXT, author TEXT, death TEXT, fann TEXT, notes TEXT, hints TEXT,
  series TEXT, volume INTEGER,
  unit TEXT DEFAULT 'صفحة', approx INTEGER DEFAULT 0,
  pages INTEGER DEFAULT 0, done_pages INTEGER DEFAULT 0,
  ocr_pages INTEGER DEFAULT 0, weak_pages INTEGER DEFAULT 0, printed_pages INTEGER DEFAULT 0,
  scanned_guess INTEGER DEFAULT 0,
  state TEXT DEFAULT 'pending', error TEXT,
  added TEXT, updated TEXT
);
CREATE TABLE IF NOT EXISTS pages(
  id INTEGER PRIMARY KEY,
  book_id INTEGER NOT NULL,
  n INTEGER NOT NULL,
  printed TEXT, vol INTEGER, method TEXT, conf REAL,
  head TEXT, body TEXT, foot TEXT,
  boxes BLOB,
  UNIQUE(book_id, n)
);
CREATE INDEX IF NOT EXISTS pages_book ON pages(book_id, n);
CREATE TABLE IF NOT EXISTS toc(book_id INTEGER, n INTEGER, level INTEGER, title TEXT);
CREATE INDEX IF NOT EXISTS toc_book ON toc(book_id, n);
"""
FTS = "CREATE VIRTUAL TABLE IF NOT EXISTS fts USING fts5(norm, rasm, content='', tokenize='unicode61 remove_diacritics 0')"
LAYERS = {"body": 0, "foot": 1}
LAYER_NAME = {0: "متن", 1: "حاشية"}


def connect(readonly: bool = False) -> sqlite3.Connection:
    if readonly:
        if not STORE_DB.exists():
            raise FileNotFoundError("لا مخزنَ نصٍّ بعد: لم تُقرأ الكتب. شغّل maktaba.py update")
        con = sqlite3.connect(f"file:{STORE_DB}?mode=ro", uri=True, timeout=30)
    else:
        STORE_DIR.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(str(STORE_DB), timeout=30)
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA synchronous=NORMAL")
        con.executescript(SCHEMA)
        con.execute(FTS)
        _migrate(con)
        if meta(con, "norm_version") is None:
            set_meta(con, "norm_version", norm_version())
        con.commit()
    con.row_factory = sqlite3.Row
    return con


def _migrate(con) -> None:
    """أعمدةٌ أُضيفت بعد إنشاء المخزن تُضاف إليه، فلا يلزم إعادةُ قراءة الكتب."""
    want = {"books": [("hints", "TEXT"), ("approx", "INTEGER DEFAULT 0"), ("scanned_guess", "INTEGER DEFAULT 0"),
                      ("btype", "TEXT"), ("btype_auto", "TEXT"),
                      ("dup_of", "INTEGER")],
            "pages": [("vol", "INTEGER"), ("catch", "TEXT")]}
    for table, cols in want.items():
        have = {r[1] for r in con.execute("PRAGMA table_info(%s)" % table)}
        for name, typ in cols:
            if name not in have:
                con.execute("ALTER TABLE %s ADD COLUMN %s %s" % (table, name, typ))


def meta(con, key: str):
    r = con.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return r[0] if r else None


def set_meta(con, key: str, value) -> None:
    con.execute("INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)", (key, str(value)))


def norm_version() -> str:
    """نسخةُ التطبيع وبصمةُ جدول الرسم القديم: تغيُّرُ أيٍّ منهما يُعيد بناءَ جدول البحث."""
    return "%s-%s" % (arabic.NORM_VERSION, orth.fingerprint())


def norm_outdated(con) -> bool:
    return meta(con, "norm_version") != norm_version()


# ───────────────────────── الكتابة ─────────────────────────

def _fts_rows(page_id: int, body: str, foot: str):
    for layer, text in ((0, body), (1, foot)):
        if text and text.strip():
            nm = arabic.normalize(text)
            if nm:
                nm = (nm + " " + ayat.search_extra(text) + " " + orth.search_extra(text)).strip()
                yield page_id * 2 + layer, nm, arabic.rasm(nm)


def add_page(con, book_id: int, n: int, printed, method: str, conf, head: str, body: str, foot: str,
             boxes=None, vol=None, catch=None) -> int:
    old = con.execute("SELECT id, body, foot FROM pages WHERE book_id = ? AND n = ?", (book_id, n)).fetchone()
    if old:
        _fts_delete(con, old["id"], old["body"], old["foot"])
        con.execute("DELETE FROM pages WHERE id = ?", (old["id"],))
    blob = zlib.compress(json.dumps(boxes, ensure_ascii=False).encode("utf-8")) if boxes else None
    cur = con.execute("INSERT INTO pages(book_id, n, printed, vol, method, conf, head, body, foot, boxes, catch) "
                      "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                      (book_id, n, None if printed is None else str(printed), vol, method, conf, head, body, foot,
                       blob, catch or None))
    pid = cur.lastrowid
    con.executemany("INSERT INTO fts(rowid, norm, rasm) VALUES (?, ?, ?)", list(_fts_rows(pid, body, foot)))
    return pid


def _fts_delete(con, page_id: int, body: str, foot: str) -> None:
    con.executemany("INSERT INTO fts(fts, rowid, norm, rasm) VALUES ('delete', ?, ?, ?)",
                    list(_fts_rows(page_id, body, foot)))


def delete_book_pages(con, book_id: int) -> None:
    for r in con.execute("SELECT id, body, foot FROM pages WHERE book_id = ?", (book_id,)).fetchall():
        _fts_delete(con, r["id"], r["body"], r["foot"])
    con.execute("DELETE FROM pages WHERE book_id = ?", (book_id,))
    con.execute("DELETE FROM toc WHERE book_id = ?", (book_id,))


def rebuild_fts(con) -> int:
    """يعيد بناء جدول البحث كلِّه من النصوص المحفوظة (بعد تغيّر طريقة التطبيع)."""
    con.execute("DROP TABLE IF EXISTS fts")
    con.execute(FTS)
    n = 0
    for r in con.execute("SELECT id, body, foot FROM pages").fetchall():
        con.executemany("INSERT INTO fts(rowid, norm, rasm) VALUES (?, ?, ?)", list(_fts_rows(r[0], r[1], r[2])))
        n += 1
    set_meta(con, "norm_version", norm_version())
    con.commit()
    return n


# ───────────────────────── القراءة ─────────────────────────

def boxes_of(row) -> list:
    b = row["boxes"] if row is not None else None
    return json.loads(zlib.decompress(b).decode("utf-8")) if b else []


def book(con, book_id: int):
    return con.execute("SELECT * FROM books WHERE id = ?", (book_id,)).fetchone()


def page(con, book_id: int, n: int):
    return con.execute("SELECT * FROM pages WHERE book_id = ? AND n = ?", (book_id, n)).fetchone()


def match(con, expr: str, column: str = "norm"):
    """صفوفُ جدول البحث المطابقة: [(رقم الصفحة، الطبقة، درجة الترتيب)]؛ الدرجةُ الأصغر أقرب."""
    q = "{%s} : (%s)" % (column, expr)
    return [(r[0] // 2, r[0] % 2, r[1]) for r in
            con.execute("SELECT rowid, bm25(fts) FROM fts WHERE fts MATCH ?", (q,))]


def title_of(b) -> str:
    return (b["title"] or "").strip() or "بلا عنوان"


def unclear_title(b) -> bool:
    """عنوانٌ أُخذ من اسم ملفٍّ لا يدلّ على كتاب («mtian05»، «01»)، ولم يسمِّه المستخدم بعد."""
    if b["title_source"] == "user":
        return False
    letters = [c for c in (b["title"] or "") if c.isalpha()]
    return not any("؀" <= c <= "ۿ" for c in letters) or len(letters) < 3


def cite(b, p) -> str:
    """العزوُ بالعربيّة: «العنوان» ج٢ ص٤٥ (صفحة الملف ٥١) — أو «العنوان» قطعة ١٢."""
    from common import ar
    s = "«%s»" % title_of(b)
    vol = p["vol"] if "vol" in p.keys() and p["vol"] else b["volume"]
    if vol:
        s += " ج" + ar(vol)
    if b["unit"] == "صفحة":
        if p["printed"]:
            s += " ص%s (صفحة الملف %s)" % (ar(p["printed"]), ar(p["n"]))
        else:
            s += " صفحة الملف %s" % ar(p["n"])
    else:
        s += " %s %s" % (b["unit"], ar(p["n"]))
    return s
