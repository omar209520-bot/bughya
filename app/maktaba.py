#!/usr/bin/env python3
"""مكتبتُك: قراءةُ الكتب وبناءُ مخزن النصّ، وبطاقاتُ الكتب، ومجلّداتُها.

  maktaba.py status                 حالُ المكتبة: ما قُرئ، وما يُقرأ الآن، وما لم يُقرأ ولماذا
  maktaba.py update [--detach]      يقرأ ما جدّ أو تغيّر من الكتب ويُخرج ما حُذف (--detach: في الخلفيّة ويعود فورًا)
  maktaba.py stop                   يوقف القراءةَ الجارية بعد الصفحة التي هي فيها (وتُستأنف بـupdate)
  maktaba.py books [--json]         قائمةُ الكتب بأرقامها
  maktaba.py book <رقم> [--json]    بطاقةُ كتاب: ملفُّه ووحدتُه وعناوينُه وحالُ نصّه
  maktaba.py set <رقم> [--title ع] [--author م] [--death س] [--fann ف] [--volume ج] [--notes ن]
                                    يسجّل بياناتِ الكتاب بعد أن يعتمدها المستخدم (من صفحة العنوان لا من الذاكرة)
  maktaba.py sources                مجلّداتُ الكتب · sources add <مجلّد> · sources remove <مجلّد>
  maktaba.py forget <رقم>           يُخرج كتابًا من المخزن ولا يمسّ ملفَّه
  maktaba.py rebuild-search         يعيد بناء جدول البحث من النصوص المحفوظة

القراءة: الكتبُ التي فيها نصٌّ أوّلًا (أسرع)، ثمّ المصوَّرة بالقراءة الآليّة. وتُحفظ كلُّ صفحةٍ حين تُقرأ،
فإن انقطعت القراءة استُؤنفت من حيث وقفت. والبحثُ يعمل على ما قُرئ منها في أثناء ذلك.
"""
import argparse
import hashlib
import json
import os
import pathlib
import re
import subprocess
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import common  # noqa: E402
from common import ar, count_word, setup_io  # noqa: E402
import store  # noqa: E402
from readers import KINDS, UNSUPPORTED_HINT, ReaderError, open_book  # noqa: E402

LOCK = common.STORE_DIR / ".update.lock"
STOP = common.STORE_DIR / ".stop"
FIRST = common.STORE_DIR / ".first"  # أرقامُ كتبٍ تُقدَّم في دور القراءة (maktaba.py first)
EXCLUDE = common.STORE_DIR / ".exclude"  # ملفّاتٌ أُخرجت بـforget فلا تُضاف ثانيةً (سطرٌ لكلّ مسار)
LOG = common.STORE_DIR / "log.txt"
OURS = {"$RECYCLE.BIN", "System Volume Information", ".venv", "node_modules"}
IGNORED_NAMES = {"ضع كتبك هنا.txt"}
ORDINALS = {"الأول": 1, "الاول": 1, "الثاني": 2, "الثالث": 3, "الرابع": 4, "الخامس": 5, "السادس": 6,
            "السابع": 7, "الثامن": 8, "التاسع": 9, "العاشر": 10, "الحادي عشر": 11, "الثاني عشر": 12,
            "الثالث عشر": 13, "الرابع عشر": 14, "الخامس عشر": 15, "السادس عشر": 16, "السابع عشر": 17,
            "الثامن عشر": 18, "التاسع عشر": 19, "العشرون": 20, "العشرين": 20}
BTYPES = {"modern_print": "طبعة حديثة", "old_print": "طبعة قديمة", "lithograph": "طبعة حجرية", "manuscript": "مخطوط"}
STATE_AR = {"done": "قُرئ", "reading": "يُقرأ", "pending": "ينتظر", "error": "تعذّر", "unsupported": "لا يُقرأ",
            "missing": "مفقود", "empty": "بلا نصّ"}


def log(msg: str) -> None:
    common.STORE_DIR.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(common.now() + " " + msg + "\n")


# ───────────────────────── المجلّدات والأسماء ─────────────────────────

def parse_volume(stem: str):
    """(عنوانُ السلسلة، رقمُ المجلّد) من اسم الملفّ: «الجزء الأول»، «ج٢»، «مجلد 3»، «Vol 4» — أو None (من سَبْر الوارث)."""
    tr = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
    alts = "|".join(sorted(ORDINALS, key=len, reverse=True))
    pats = [
        (rf"(?:الجزء|جزء|المجلد|مجلد)\s+({alts})", lambda g: ORDINALS[g]),
        (r"(?:الجزء|الجزئ|جزء|المجلد|مجلد)\s*[-ـ:]?\s*([0-9٠-٩]+)", lambda g: int(g.translate(tr))),
        (r"(?i)\b(?:volumes?|vol|parts?|pt|v)\.?\s*[-_]?\s*([0-9]+)", lambda g: int(g)),
        (r"(?:^|[\s\-_ـ])ج\s*[-ـ]?\s*([0-9٠-٩]+)", lambda g: int(g.translate(tr))),
    ]
    for pat, conv in pats:
        m = re.search(pat, stem)
        if m:
            try:
                vol = conv(m.group(1))
            except (KeyError, ValueError):
                continue
            rest = (stem[:m.start()] + " " + stem[m.end():])
            rest = re.sub(r"\s+", " ", rest).strip(" -_ـ:،.()[]")
            return rest, vol
    return None


def clean_stem(stem: str) -> str:
    return re.sub(r"\s+", " ", stem.replace("_", " ")).strip(" -_.")


def meaningless(name: str) -> bool:
    """اسمُ ملفٍّ لا يدلّ على كتاب («mqf01_2»، «02_51105»): لا حرفَ عربيًّا فيه، أو أرقامٌ ورموزٌ غالبة."""
    letters = [c for c in name if c.isalpha()]
    return not any("؀" <= c <= "ۿ" for c in letters) or len(letters) < 3


def fingerprint(p: pathlib.Path) -> str:
    h = hashlib.sha1()
    size = p.stat().st_size
    h.update(str(size).encode())
    with p.open("rb") as f:
        for off in (0, max(0, size // 2 - 32768), max(0, size - 65536)):
            f.seek(off)
            h.update(f.read(65536))
    return h.hexdigest()


def excluded() -> set:
    try:
        return set(EXCLUDE.read_text(encoding="utf-8").splitlines()) - {""}
    except OSError:
        return set()


def scan_files() -> list:
    out = []
    skip = excluded()
    for src in common.sources():
        if not src.exists():
            continue
        if src.is_file():  # كتابٌ واحدٌ أُضيف بعينه (sources add "ملف")
            if str(src) not in skip and (src.suffix.lower() in KINDS or src.suffix.lower() in UNSUPPORTED_HINT):
                out.append((src, src))
            continue
        for dirpath, dirnames, filenames in os.walk(src):
            d = pathlib.Path(dirpath)
            dirnames[:] = sorted(x for x in dirnames if not x.startswith(".") and x not in OURS)
            for fn in sorted(filenames):
                if fn.startswith((".", "~$")) or fn in IGNORED_NAMES:
                    continue
                p = d / fn
                if str(p) in skip:
                    continue
                ext = p.suffix.lower()
                if ext in KINDS or ext in UNSUPPORTED_HINT:
                    out.append((src, p))
    return out


# ───────────────────────── الفحص: ما جدّ وما تغيّر وما حُذف ─────────────────────────

def sync(con) -> dict:
    stats = {"new": 0, "changed": 0, "moved": 0, "missing": 0}
    files = scan_files()
    seen = {str(p) for _, p in files}
    # ما غاب عن موضعه يُعلَّم مفقودًا أوّلًا، ليُعرف إن ظهر في موضعٍ آخر (نُقل أو أُعيدت تسميتُه) فيُنقل إليه بنصّه
    for row in con.execute("SELECT id, path FROM books WHERE state != 'missing'").fetchall():
        if row["path"] not in seen:
            con.execute("UPDATE books SET state='missing', updated=? WHERE id=?", (common.now(), row["id"]))
            stats["missing"] += 1
    for src, p in files:
        key = str(p)
        try:
            st = p.stat()
        except OSError:
            continue
        row = con.execute("SELECT * FROM books WHERE path = ?", (key,)).fetchone()
        if row is None:
            try:
                fp = fingerprint(p)
            except OSError as e:
                log("تعذّرت قراءة %s: %s" % (p, e))
                continue
            moved = con.execute("SELECT * FROM books WHERE fingerprint = ? AND state = 'missing'", (fp,)).fetchone()
            if moved:
                back = "done" if moved["done_pages"] and moved["done_pages"] >= (moved["pages"] or 0) else "pending"
                title = moved["title"]
                if moved["title_source"] == "filename":        # أُعيدت تسميتُه: العنوانُ يتبع الاسمَ الجديد
                    vol = parse_volume(p.stem)
                    title = clean_stem(vol[0]) if vol and vol[0] else clean_stem(p.stem)
                con.execute("UPDATE books SET path=?, source=?, size=?, mtime=?, state=?, title=?, updated=? WHERE id=?",
                            (key, str(src), st.st_size, st.st_mtime, back, title, common.now(), moved["id"]))
                stats["moved"] += 1
                stats["missing"] -= 1 if stats["missing"] else 0
                continue
            add_book(con, src, p, st, fp)
            stats["new"] += 1
        elif row["size"] != st.st_size or abs((row["mtime"] or 0) - st.st_mtime) > 1:
            fp = fingerprint(p)
            if fp != row["fingerprint"]:
                store.delete_book_pages(con, row["id"])
                con.execute("UPDATE books SET size=?, mtime=?, fingerprint=?, pages=0, done_pages=0, ocr_pages=0, "
                            "weak_pages=0, printed_pages=0, state='pending', error=NULL, updated=? WHERE id=?",
                            (st.st_size, st.st_mtime, fp, common.now(), row["id"]))
                stats["changed"] += 1
            else:
                con.execute("UPDATE books SET size=?, mtime=? WHERE id=?", (st.st_size, st.st_mtime, row["id"]))
        elif row["state"] == "missing":
            con.execute("UPDATE books SET state=? WHERE id=?",
                        ("done" if row["done_pages"] and row["done_pages"] >= (row["pages"] or 0) else "pending",
                         row["id"]))
    con.commit()
    return stats


def add_book(con, src, p: pathlib.Path, st, fp: str) -> None:
    ext = p.suffix.lower()
    kind = KINDS.get(ext)
    stem = p.stem
    vol = parse_volume(stem)
    title = clean_stem(vol[0]) if vol and vol[0] else clean_stem(stem)
    state, error, scanned = "pending", None, 0
    if kind is None:
        state, error = "unsupported", UNSUPPORTED_HINT.get(ext, "صيغةٌ لا تُقرأ هنا")
    elif kind == "image":
        scanned = 1
    con.execute("INSERT INTO books(path, source, kind, size, mtime, fingerprint, title, title_source, series, volume, "
                "state, error, scanned_guess, added, updated) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (str(p), str(src), kind or ext.lstrip("."), st.st_size, st.st_mtime, fp, title, "filename",
                 clean_stem(vol[0]) if vol else None, vol[1] if vol else None, state, error, scanned,
                 common.now(), common.now()))


# ───────────────────────── القراءة ─────────────────────────

def fix_printed(con, book_id: int) -> int:
    """الرقمُ المطبوع: يُعتمد ما وافق الإزاحةَ الغالبة بين رقم الملفّ ورقم الطبعة، ويُصحَّح ما قُرئت زخرفتُه أرقامًا زائدة
    («١٧٠٠» لـ١٧٠، كما في أداة الإضافة)، ويُسقط ما خالفها (سنةٌ في ذيل الصفحة ونحوُها) فيُعزى إلى صفحة الملفّ وحدها."""
    rows = con.execute("SELECT id, n, printed FROM pages WHERE book_id = ? AND printed IS NOT NULL", (book_id,)).fetchall()
    vals = [(r["id"], r["n"], int(r["printed"])) for r in rows if str(r["printed"]).isdigit()]
    if len(vals) >= 5:
        offs = {}
        for _, n, pr in vals:
            offs[pr - n] = offs.get(pr - n, 0) + 1
        d, c = max(offs.items(), key=lambda kv: kv[1])
        if c / len(vals) >= 0.6:
            for pid, n, pr in vals:
                want = n + d
                if pr != want:
                    fixed = want if (want > 0 and str(pr).startswith(str(want))) else None
                    con.execute("UPDATE pages SET printed = ? WHERE id = ?", (None if fixed is None else str(fixed), pid))
    return con.execute("SELECT COUNT(*) FROM pages WHERE book_id = ? AND printed IS NOT NULL", (book_id,)).fetchone()[0]


def progress(**kw) -> None:
    pr = common.read_json(common.PROGRESS, {}) or {}
    pr.update(kw)
    pr["updated"] = common.now()
    if kw.get("state") == "running":
        pr.pop("error", None)
    try:   # تقريرُ التقدّم لا يوقف القراءة إن تعذّرت كتابتُه مرّة
        common.write_json(common.PROGRESS, pr)
    except OSError as e:
        log("تعذّرت كتابةُ حال التقدّم: %r" % e)


def counts(con) -> dict:
    c = {r[0]: r[1] for r in con.execute("SELECT state, COUNT(*) FROM books GROUP BY state")}
    total = sum(v for k, v in c.items() if k not in ("missing",))
    return {"books_total": total, "books_done": c.get("done", 0) + c.get("empty", 0),
            "pending": c.get("pending", 0) + c.get("reading", 0)}


def read_book(con, b, ocr, defer: bool = False):
    """يقرأ كتابًا ويحفظ صفحاتِه. ومع defer: إن تبيّن عند فتحه أنّ نصّه المضمَّن معيبٌ فستُقرأ صفحاتُه كلُّها
    قراءةً آليّة (وهي بطيئة)، أُجّل إلى آخر الطابور وأُعيد «defer» ليُقرأ النصّيُّ السليمُ أوّلًا."""
    path = pathlib.Path(b["path"])
    try:
        book = open_book(path, ocr)
    except ReaderError as e:
        con.execute("UPDATE books SET state='error', error=?, updated=? WHERE id=?", (str(e), common.now(), b["id"]))
        con.commit()
        log("✗ %s: %s" % (path.name, e))
        return
    except Exception as e:  # خطأٌ غير متوقَّع في ملفٍّ واحد لا يوقف المكتبة
        con.execute("UPDATE books SET state='error', error=?, updated=? WHERE id=?",
                    ("خطأٌ غير متوقَّع: %s" % e, common.now(), b["id"]))
        con.commit()
        log("✗ %s: %r" % (path.name, e))
        return
    if defer and b["state"] != "reading" and getattr(book, "force_ocr", False):
        con.execute("UPDATE books SET scanned_guess=1, updated=? WHERE id=?", (common.now(), b["id"]))
        con.commit()
        book.close()
        log("↩ %s: نصُّ الملفّ معيبٌ فتُقرأ صفحاتُه آليًّا، وأُخّر إلى آخر الطابور." % path.name)
        return "defer"
    try:
        fresh = b["state"] != "reading"
        if fresh:
            store.delete_book_pages(con, b["id"])
        title, source = b["title"], b["title_source"]
        if source == "filename" and book.title and (book.kind == "epub" or meaningless(path.stem)):
            title, source = book.title, "metadata"
        hints = {k: v for k, v in (getattr(book, "hints", {}) or {}).items() if v}
        con.execute("UPDATE books SET kind=?, unit=?, approx=?, pages=?, title=?, title_source=?, "
                    "author=COALESCE(NULLIF(author, ''), ?), hints=?, scanned_guess=?, state='reading', error=NULL, "
                    "updated=? WHERE id=?", (book.kind, book.unit, int(book.approx), book.total, title, source,
                                             book.author or None, json.dumps(hints, ensure_ascii=False) if hints else None,
                                             int(bool(book.scanned_guess)), common.now(), b["id"]))
        if fresh:
            con.executemany("INSERT INTO toc(book_id, n, level, title) VALUES (?, ?, ?, ?)",
                            [(b["id"], n, lvl, t) for lvl, t, n in book.toc])
            con.execute("UPDATE books SET done_pages=0, ocr_pages=0, weak_pages=0 WHERE id=?", (b["id"],))
        con.commit()
        done = 0 if fresh else (b["done_pages"] or 0)
        ocr_n = 0 if fresh else (b["ocr_pages"] or 0)
        weak_n = 0 if fresh else (b["weak_pages"] or 0)
        last_commit = last_prog = time.time()
        progress(current_id=b["id"], current_title=title, current_page=done, current_pages=book.total)
        for pg in book.pages(done + 1):
            store.add_page(con, b["id"], pg["n"], pg["printed"], pg["method"], pg["conf"], pg["head"], pg["body"],
                           pg["foot"], pg["boxes"], pg.get("vol"), pg.get("catch"))
            done = pg["n"]
            ocr_n += pg["method"] == "ocr"
            weak_n += bool(pg["weak"])
            t = time.time()
            if t - last_commit > 3 or pg["method"] == "ocr":
                con.execute("UPDATE books SET done_pages=?, ocr_pages=?, weak_pages=? WHERE id=?",
                            (done, ocr_n, weak_n, b["id"]))
                con.commit()
                last_commit = t
            if t - last_prog > 1:
                progress(current_page=done, current_method="قراءةٌ آليّة" if pg["method"] == "ocr" else "نصُّ الملفّ")
                last_prog = t
            if STOP.exists():
                break
        printed_n = fix_printed(con, b["id"]) if book.unit == "صفحة" else 0
        finished = done >= book.total
        has_text = con.execute("SELECT 1 FROM pages WHERE book_id=? AND (length(body) > 0 OR length(foot) > 0) LIMIT 1",
                               (b["id"],)).fetchone()
        state = ("done" if has_text else "empty") if finished else "reading"
        err = None
        if state == "empty":
            err = "لم يُستخرج منه نصّ" + ("" if ocr is None or ocr.ok else ": صفحاتُه مصوَّرة والقراءةُ الآليّة غير متاحة (%s)"
                                          % ocr.reason)
        # اقتراحُ نوع الكتاب: ما قُرئ من نصّ ملفّه طبعةٌ حديثة؛ والمصوَّرُ لا يُعرف عمرُه آليًّا، فيختاره المستخدم
        auto = "modern_print" if done and ocr_n < done / 2 else None
        con.execute("UPDATE books SET done_pages=?, ocr_pages=?, weak_pages=?, printed_pages=?, state=?, error=?, "
                    "btype_auto=?, updated=? WHERE id=?", (done, ocr_n, weak_n, printed_n, state, err, auto, common.now(),
                                                            b["id"]))
        con.commit()
        log("✓ %s: %d/%d (آليّة %d، ضعيفة %d)" % (path.name, done, book.total, ocr_n, weak_n))
    finally:
        book.close()


def classify_pending(con, budget: float = 20.0) -> int:
    """قبل القراءة: أيُّ الكتب التي لم تُقرأ بعدُ مصوَّر؟ عيّنةٌ من خمس صفحاتٍ من كلّ بي دي إف: أفيها نصٌّ مضمَّن؟
    بهذا يُقرأ النصّيُّ أوّلًا فيبحث المستخدمُ فيه في ثوانٍ، ويتأخّر المصوَّرُ إلى آخر الطابور لبطء قراءته الآليّة.
    ولولا هذا لرُتّبت الكتبُ في أوّل قراءةٍ بحجم ملفّاتها وحدَها، إذ لا يُعرف المصوَّرُ إلّا بعد فتحه.
    الفحصُ بميزانيّة وقتٍ (ثوانٍ) لئلّا تتأخّر القراءةُ في المكتبات الكبيرة؛ وما لم يُفحص يبقى على ترتيب الحجم.
    ولا يُغني عن الفحص الدقيق في read_book، فهو يصحّحه حين يُفتح الكتاب."""
    rows = con.execute("SELECT id, path FROM books WHERE state = 'pending' AND kind = 'pdf' "
                       "AND scanned_guess = 0 ORDER BY size").fetchall()
    if not rows:
        return 0
    try:
        import pymupdf as fitz
        from readers.pdf import MIN_LETTERS
    except ImportError as e:
        log("تعذّر فحصُ الكتب قبل القراءة: %r" % e)
        return 0
    t0, n = time.monotonic(), 0
    for r in rows:
        if time.monotonic() - t0 > budget or STOP.exists():
            break
        try:
            with fitz.open(r["path"]) as doc:
                total = doc.page_count
                if not total:
                    continue
                idx = sorted({min(total - 1, int(total * f)) for f in (0.1, 0.3, 0.5, 0.7, 0.9)})
                letters = sum(sum(1 for c in doc[i].get_text("text") if c.isalpha()) for i in idx)
            scanned = letters / len(idx) < MIN_LETTERS
        except Exception:      # ملفٌّ معطوبٌ أو مقفل: يُترك لقارئه، فهو يسجّل سببَ تعذّره
            continue
        if scanned:
            con.execute("UPDATE books SET scanned_guess=1 WHERE id=?", (r["id"],))
            n += 1
    if n:
        con.commit()
        log("فحصُ ما قبل القراءة: %d كتابًا مصوَّرًا يُؤخَّر إلى آخر الطابور." % n)
    return n


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if common.IS_WIN:
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True,
                             creationflags=0x08000000).stdout
        return str(pid) in out
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def running():
    try:
        pid, _t, token = LOCK.read_text().split()
        return (int(pid), token) if pid_alive(int(pid)) else None
    except (OSError, ValueError):
        return None


def cmd_update(args) -> int:
    r = running()
    if r and not (args.child and r[1] == args.child):
        print("القراءةُ جاريةٌ في الخلفيّة. اطلب «حال المكتبة» لترى أين بلغت.")
        return 0
    common.STORE_DIR.mkdir(parents=True, exist_ok=True)
    if args.detach:
        token = "%d-%d" % (os.getpid(), time.time() * 1000)
        cmd = common.tool_cmd("maktaba", "update", "--child", token)
        kw = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL,
              "cwd": str(common.APP)}
        if common.IS_WIN:
            kw["creationflags"] = 0x00000008 | 0x00000200 | 0x08000000
        else:
            kw["start_new_session"] = True
        pid = subprocess.Popen(cmd, **kw).pid
        LOCK.write_text(f"{pid} {time.time()} {token}")
        print("بدأت قراءةُ الكتب في الخلفيّة.")
        return 0
    LOCK.write_text(f"{os.getpid()} {time.time()} {args.child or 'fg-%d' % os.getpid()}")
    try:
        STOP.unlink()
    except OSError:
        pass
    from readers.ocr import engine
    ocr = engine()
    con = store.connect()
    try:
        if store.norm_outdated(con):
            store.rebuild_fts(con)
        stats = sync(con)
        progress(state="running", pid=os.getpid(), started=common.now(), ocr_ok=ocr.ok, ocr_reason=ocr.reason,
                 **counts(con))
        queue = ("SELECT * FROM books WHERE state IN ('pending', 'reading') "
                 "ORDER BY state = 'reading' DESC, scanned_guess, size")
        classify_pending(con)
        todo = con.execute(queue).fetchall()
        first = first_ids()
        todo.sort(key=lambda b: first.index(b["id"]) if b["id"] in first else len(first))
        late = []        # ما تبيّن عند فتحه أنّه يُقرأ آليًّا كلُّه: يُقرأ بعد الكتب النصّيّة
        for b in todo:
            if STOP.exists():
                break
            if store.book(con, b["id"]) is None:  # أُخرج أثناء القراءة
                continue
            if read_book(con, b, ocr, defer=True) == "defer":
                late.append(b["id"])
                continue
            progress(**counts(con))
        for bid in late:
            if STOP.exists():
                break
            b = store.book(con, bid)
            if b is None:
                continue
            read_book(con, b, ocr)
            progress(**counts(con))
        try:                      # قاموسُ الكلمات المعروفة من الكتب النصّيّة السليمة (لتعليم المشكوك فيه)
            import lexicon
            lexicon.build(con)
        except Exception as e:
            log("تعذّر بناءُ القاموس: %r" % e)
        c = counts(con)
        progress(state="stopped" if STOP.exists() else "done", current_title=None, current_page=None,
                 current_pages=None, **c)
        print("✓ قُرئ %s من %s. %s" % (ar(c["books_done"]), count_word(c["books_total"], "كتابٍ واحد", "كتابين",
                                                                         "كتب", "كتابًا"),
                                        "(جديد %s، تغيّر %s، نُقل %s، حُذف %s)" % tuple(
                                            ar(stats[k]) for k in ("new", "changed", "moved", "missing"))))
        return 0
    except Exception as e:
        progress(state="error", error=str(e))
        log("✗ خطأٌ في القراءة: %r" % e)
        raise
    finally:
        con.close()
        for f in (LOCK, STOP):
            try:
                f.unlink()
            except OSError:
                pass


# ───────────────────────── العرض ─────────────────────────

def cmd_status(args) -> int:
    try:
        con = store.connect(readonly=True)
    except FileNotFoundError:
        n = len(scan_files())
        print("لم تُقرأ الكتبُ بعد. في المجلّدات %s. اطلب «حدّث المكتبة» ليبدأ." %
              count_word(n, "ملفٌّ واحد", "ملفّان", "ملفّات", "ملفًّا"))
        return 0
    c = {r[0]: r[1] for r in con.execute("SELECT state, COUNT(*) FROM books GROUP BY state")}
    tot = con.execute("SELECT COUNT(*), SUM(method='ocr'), SUM(method='none') FROM pages").fetchone()
    weak = con.execute("SELECT COALESCE(SUM(weak_pages), 0) FROM books WHERE state != 'missing'").fetchone()[0]
    pr = common.read_json(common.PROGRESS, {}) or {}
    live = running()
    books_n = sum(v for k, v in c.items() if k != "missing")
    print("مكتبتُك: %s في %s." % (count_word(books_n, "كتابٌ واحد", "كتابان", "كتب", "كتابًا"),
                                  count_word(len(common.sources()), "مجلّدٍ واحد", "مجلّدين", "مجلّدات", "مجلّدًا")))
    parts = ["%s %s" % (STATE_AR[k], ar(c[k])) for k in ("done", "reading", "pending", "error", "unsupported",
                                                           "empty", "missing") if c.get(k)]
    print("  " + " · ".join(parts))
    print("  الصفحاتُ والقطع المقروءة: %s (منها بالقراءة الآليّة %s، وضعيفةُ النصّ %s)"
          % (ar(tot[0] or 0), ar(tot[1] or 0), ar(weak or 0)))
    if live and pr.get("current_title"):
        print("  يُقرأ الآن: «%s» %s من %s%s" % (pr["current_title"], ar(pr.get("current_page") or 0),
                                                  ar(pr.get("current_pages") or 0),
                                                  (" · " + pr["current_method"]) if pr.get("current_method") else ""))
    elif c.get("pending") or c.get("reading"):
        print("  القراءةُ متوقّفة، وبقي ما لم يُقرأ: اطلب «حدّث المكتبة».")
    if "ocr_ok" in pr:
        print("  القراءةُ الآليّة: " + ("متاحة" if pr["ocr_ok"] else "غير متاحة — " + (pr.get("ocr_reason") or "")))
    for r in con.execute("SELECT id, path, state, error FROM books WHERE state IN ('error', 'unsupported', 'empty') "
                         "ORDER BY id").fetchall():
        print("  ✗ [%s] %s — %s" % (ar(r["id"]), pathlib.Path(r["path"]).name, r["error"] or STATE_AR[r["state"]]))
    return 0


def book_json(con, b) -> dict:
    d = {k: b[k] for k in b.keys()}
    d["toc"] = [dict(r) for r in con.execute("SELECT n, level, title FROM toc WHERE book_id = ? ORDER BY rowid",
                                             (b["id"],))]
    return d


def cmd_books(args) -> int:
    con = store.connect(readonly=True)
    rows = con.execute("SELECT * FROM books ORDER BY COALESCE(series, title), volume, id").fetchall()
    if args.json:
        print(json.dumps([{k: r[k] for k in r.keys()} for r in rows], ensure_ascii=False, indent=1))
        return 0
    for r in rows:
        vol = (" ج" + ar(r["volume"])) if r["volume"] else ""
        how = ""
        if r["done_pages"]:
            share = (r["ocr_pages"] or 0) / r["done_pages"]
            how = "قراءة آليّة" if share > 0.9 else ("مختلط" if share > 0.05 else "نصّ الملف")
        auth = (" — " + r["author"]) if r["author"] else ""
        print("[%s] %s%s%s · %s %s · %s%s" % (ar(r["id"]), store.title_of(r), vol, auth, ar(r["pages"] or 0),
                                              r["unit"] or "", STATE_AR.get(r["state"], r["state"]),
                                              (" · " + how) if how else ""))
    return 0


def cmd_book(args) -> int:
    con = store.connect(readonly=True)
    b = store.book(con, args.id)
    if b is None:
        common.die("لا كتابَ بالرقم %s" % args.id)
    d = book_json(con, b)
    if args.json:
        print(json.dumps(d, ensure_ascii=False, indent=1))
        return 0
    print("الكتاب [%s]: %s%s" % (ar(b["id"]), store.title_of(b), (" ج" + ar(b["volume"])) if b["volume"] else ""))
    print("  الملفّ: %s" % b["path"])
    src = {"filename": "من اسم الملفّ", "metadata": "من بيانات الملفّ", "user": "سجّله المستخدم"}.get(b["title_source"], "")
    print("  مصدرُ العنوان: %s" % src)
    for k, lab in (("author", "المؤلّف"), ("death", "الوفاة"), ("fann", "الفنّ"), ("notes", "ملاحظات")):
        if b[k]:
            print("  %s: %s" % (lab, b[k]))
    if b["hints"]:
        h = json.loads(b["hints"])
        lab = {"title": "العنوان", "author": "المؤلّف", "subject": "الموضوع"}
        print("  بياناتُ الملفّ (تلميحٌ لا يُعتمد: كاتبُها قد يكون ناسخَ الملفّ): "
              + " · ".join("%s «%s»" % (lab.get(k, k), v) for k, v in h.items()))
    print("  الوحدة: %s · العدد: %s · المقروء: %s%s" % (b["unit"], ar(b["pages"] or 0), ar(b["done_pages"] or 0),
                                                       " (ترقيمٌ تقريبيّ كما رسمه برنامجُه آخرَ مرّة)" if b["approx"] else ""))
    if b["unit"] == "صفحة" and b["done_pages"]:
        print("  بالقراءة الآليّة: %s · ضعيفةُ النصّ: %s · قُرئ رقمُها المطبوع: %s"
              % (ar(b["ocr_pages"] or 0), ar(b["weak_pages"] or 0), ar(b["printed_pages"] or 0)))
    print("  الحال: %s%s" % (STATE_AR.get(b["state"], b["state"]), (" — " + b["error"]) if b["error"] else ""))
    if d["toc"]:
        print("  العناوين (%s):" % ar(len(d["toc"])))
        for t in d["toc"][:60]:
            print("    %s%s … %s %s" % ("  " * (max(1, t["level"] or 1) - 1), t["title"], b["unit"], ar(t["n"])))
        if len(d["toc"]) > 60:
            print("    … وغيرُها (--json للكلّ)")
    return 0


def cmd_set(args) -> int:
    con = store.connect()
    b = store.book(con, args.id)
    if b is None:
        common.die("لا كتابَ بالرقم %s" % args.id)
    fields = {k: getattr(args, k) for k in ("title", "author", "death", "fann", "notes", "volume", "btype")
              if getattr(args, k) is not None}
    if fields.get("btype") == "auto":
        fields["btype"] = None
    if not fields:
        common.die("لم يُذكر شيءٌ يُسجَّل.")
    if "title" in fields:
        fields["title_source"] = "user"
    con.execute("UPDATE books SET %s, updated=? WHERE id=?" % ", ".join(f"{k}=?" for k in fields),
                (*fields.values(), common.now(), args.id))
    con.commit()
    labels = {"title": "العنوان", "author": "المؤلّف", "death": "الوفاة", "fann": "الفنّ", "notes": "ملاحظات",
              "volume": "الجزء", "btype": "نوع الكتاب"}
    print("✓ سُجّل للكتاب [%s]: %s" % (ar(args.id), " · ".join("%s: %s" % (labels[k], v) for k, v in fields.items()
                                                              if k in labels)))
    return 0


def cmd_sources(args) -> int:
    cfg = common.load_config()
    extra = [s for s in cfg.get("sources", []) if pathlib.Path(s).expanduser() != common.BOOKS]
    if args.action == "add":
        p = pathlib.Path(args.path.strip().strip('"')).expanduser().resolve()
        if not (p.is_dir() or p.is_file()):
            common.die("لم أجد المجلّد ولا الملفّ: %s" % p)
        if str(p) not in extra:
            extra.append(str(p))
        cfg["sources"] = extra
        common.save_config(cfg)
        print("✓ أُضيف %s: %s — اطلب «حدّث المكتبة» لتُقرأ." % ("الكتاب" if p.is_file() else "المجلّد", p))
    elif args.action == "remove":
        p = str(pathlib.Path(args.path).expanduser().resolve())
        cfg["sources"] = [s for s in extra if str(pathlib.Path(s).expanduser().resolve()) != p]
        common.save_config(cfg)
        print("✓ أُخرج المجلّد من المكتبة (تبقى نصوصُه في المخزن حتّى «حدّث المكتبة»، ثمّ تُعلَّم مفقودة).")
    for s in common.sources():
        print(("• %s" % s) + ("" if s.exists() else "  (غير موجود)"))
    return 0


def cmd_forget(args) -> int:
    con = store.connect()
    b = store.book(con, args.id)
    if b is None:
        common.die("لا كتابَ بالرقم %s" % args.id)
    store.delete_book_pages(con, args.id)
    con.execute("DELETE FROM books WHERE id = ?", (args.id,))
    con.commit()
    with EXCLUDE.open("a", encoding="utf-8") as f:
        f.write(b["path"] + "\n")
    print("✓ أُخرج من المخزن: %s (الملفُّ باقٍ في مكانه، ولن يُقرأ ثانيةً)" % store.title_of(b))
    return 0


def first_ids() -> list:
    try:
        return [int(x) for x in FIRST.read_text().split()]
    except (OSError, ValueError):
        return []


def main() -> int:
    setup_io()
    ap = argparse.ArgumentParser(prog="maktaba.py", description="مكتبتُك: قراءةُ الكتب وبطاقاتُها")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("status")
    u = sub.add_parser("update")
    u.add_argument("--detach", action="store_true")
    u.add_argument("--child")
    sub.add_parser("stop")
    rr = sub.add_parser("reread", help="أعد قراءةَ كتبٍ من أوّلها (بأرقامها، أو --ocr: كلُّ ما قُرئ آليًّا)")
    rr.add_argument("ids", type=int, nargs="*")
    rr.add_argument("--ocr", action="store_true")
    rr.add_argument("--scanned", action="store_true",
                    help="الكتبُ المصوَّرة التي لم تُقرأ آليًّا (بعد إضافة القراءة الضوئيّة العربيّة)")
    oc = sub.add_parser("ocr", help="هل القراءةُ الآليّة للصور متاحة؟")
    oc.add_argument("--json", action="store_true")
    fi = sub.add_parser("first", help="قدّم كتبًا في دور القراءة (بلا أرقامٍ: الغِ التقديم)")
    fi.add_argument("ids", type=int, nargs="*")
    b = sub.add_parser("books")
    b.add_argument("--json", action="store_true")
    k = sub.add_parser("book")
    k.add_argument("id", type=int)
    k.add_argument("--json", action="store_true")
    s = sub.add_parser("set")
    s.add_argument("id", type=int)
    for f in ("title", "author", "death", "fann", "notes"):
        s.add_argument("--" + f)
    s.add_argument("--volume", type=int)
    s.add_argument("--btype", choices=list(BTYPES) + ["auto"], help="نوعُ الكتاب (auto: الاقتراحُ الآليّ)")
    so = sub.add_parser("sources")
    so.add_argument("action", nargs="?", choices=["add", "remove"])
    so.add_argument("path", nargs="?")
    fg = sub.add_parser("forget")
    fg.add_argument("id", type=int)
    sub.add_parser("rebuild-search")
    sub.add_parser("lexicon", help="يعيد بناءَ قاموس الكلمات المعروفة")
    args = ap.parse_args()
    if args.cmd == "update":
        return cmd_update(args)
    if args.cmd == "ocr":
        from readers.ocr import engine
        e = engine()
        d = {"ok": bool(e.ok), "reason": getattr(e, "reason", ""), "name": e.name}
        print(json.dumps(d, ensure_ascii=False) if args.json else ("متاحة: " + e.name if e.ok else "غير متاحة: " + e.reason))
        return 0
    if args.cmd == "stop":
        common.STORE_DIR.mkdir(parents=True, exist_ok=True)
        STOP.write_text("stop")
        print("ستتوقّف القراءةُ بعد الصفحة الجارية. وتُستأنف بـ«حدّث المكتبة».")
        return 0
    if args.cmd == "reread":
        if running():
            common.die("القراءةُ جارية: أوقفها أوّلًا (maktaba.py stop).")
        con = store.connect()
        ids = set(args.ids)
        if args.ocr:
            ids |= {r[0] for r in con.execute("SELECT id FROM books WHERE ocr_pages > 0")}
        if args.scanned:
            ids |= {r[0] for r in con.execute("SELECT id FROM books WHERE state != 'missing' AND ocr_pages = 0 AND "
                                              "(state = 'empty' OR (scanned_guess = 1 AND weak_pages > 0))")}
        # «pending» تجعل القراءةَ تبدأ من أوّل الكتاب وتمحو صفحاتِه القديمة (read_book)
        n = con.execute("UPDATE books SET state='pending' WHERE state IN ('done', 'reading', 'empty', 'error') "
                        "AND id IN (%s)" % ",".join("?" * len(ids)), tuple(ids)).rowcount if ids else 0
        con.commit()
        print("✓ ستُعاد قراءةُ %s عند «حدّث المكتبة»." % count_word(n, "كتابٍ واحد", "كتابين", "كتب", "كتابًا"))
        return 0
    if args.cmd == "first":
        common.STORE_DIR.mkdir(parents=True, exist_ok=True)
        FIRST.write_text(" ".join(str(i) for i in args.ids))
        print(("✓ تُقدَّم في دور القراءة: %s. " % "، ".join(ar(i) for i in args.ids) if args.ids
               else "✓ أُلغي التقديم. ") + "ويسري من القراءة التالية (إن كانت قراءةٌ جارية فأوقفها ثمّ استأنفها).")
        return 0
    if args.cmd == "books":
        return cmd_books(args)
    if args.cmd == "book":
        return cmd_book(args)
    if args.cmd == "set":
        return cmd_set(args)
    if args.cmd == "sources":
        if args.action and not args.path:
            common.die("اذكر المجلّد.")
        return cmd_sources(args)
    if args.cmd == "forget":
        return cmd_forget(args)
    if args.cmd == "lexicon":
        import lexicon
        print("✓ القاموس: %s كلمة" % ar(lexicon.build(store.connect())))
        return 0
    if args.cmd == "rebuild-search":
        con = store.connect()
        print("✓ أُعيد بناءُ جدول البحث: %s" % count_word(store.rebuild_fts(con), "صفحةٌ واحدة", "صفحتان",
                                                          "صفحات", "صفحةً"))
        return 0
    return cmd_status(args)


if __name__ == "__main__":
    sys.exit(main())
