"""النسخةُ الاحتياطيّة: ملفٌّ مضغوطٌ واحدٌ فيه عملُ الباحث ومخزنُ النصّ، يُسترجَع على هذا الجهاز أو على غيره.

ما يدخل النسخة: كلُّ ما في مجلّد البيانات (DATA)، إلّا ما يعود وحده أو لا قيمةَ له:
    window/ (مكوّنُ النافذة) · outputs/images (صورُ الصفحات المؤقّتة) · الأقفالُ والملفّاتُ المؤقّتة
    والكتبُ المسحوبة (books/) لا تدخل إلّا إن اختارها المستخدم.
قواعدُ البيانات (store.db وغيرها) تُنسخ بأداة النسخ في sqlite نفسها، فتخرج سليمةً ولو كانت القراءةُ جارية.

الاسترجاع:
    ١. يُتحقّق أنّ الملفّ نسخةٌ من «بُغية».
    ٢. تُحفظ البياناتُ الحاليّة في مجلّد «قبل-الاسترجاع» داخل مجلّد البيانات (يُبقى آخرُ اثنين).
    ٣. تُكتب بياناتُ النسخة مكانها.
    ٤. مواضعُ الكتب: إن تغيّر موضعُها (جهازٌ آخر، أو اسمُ مستخدمٍ آخر) دلّ المستخدمُ البرنامجَ على مجلّدها،
       فيتعرّف الفحصُ (maktaba.sync) على كلّ كتابٍ ببصمته ويُلحقه بنصّه المقروء، فلا يُقرأ ثانية.
"""
import json
import os
import pathlib
import shutil
import sqlite3
import tempfile
import time
import zipfile

import common

MANIFEST = "bughya-backup.json"
STATE = common.DATA / "backup.json"          # آخرُ نسخةٍ وتأجيلُ التذكير: لا يدخل النسخة
SAFETY_PREFIX = "قبل-الاسترجاع-"
KEEP_SAFETY = 2
SKIP_DIRS = {"window", "inbox-tmp"}
SKIP_NAMES = {"window-error.txt", ".update.lock", ".stop", STATE.name}
SKIP_SUFFIXES = (".tmp", "-shm", "-wal", "-journal")
DB_SUFFIXES = (".db", ".sqlite")


def _rel(p: pathlib.Path) -> str:
    return p.relative_to(common.DATA).as_posix()


def _skip(rel: str, with_books: bool) -> bool:
    parts = rel.split("/")
    if parts[0] in SKIP_DIRS or parts[0].startswith(SAFETY_PREFIX):
        return True
    if parts[0] == "books" and not with_books:
        return True
    if rel == "outputs/images" or rel.startswith("outputs/images/"):
        return True
    name = parts[-1]
    return name in SKIP_NAMES or name.endswith(SKIP_SUFFIXES)


def files(with_books: bool = False) -> list:
    """ما يدخل النسخة: [(المسار, الاسم النسبيّ)]."""
    out = []
    if not common.DATA.exists():
        return out
    for dirpath, dirnames, filenames in os.walk(common.DATA):
        d = pathlib.Path(dirpath)
        dirnames[:] = sorted(x for x in dirnames if not _skip(_rel(d / x), with_books))
        for fn in sorted(filenames):
            p = d / fn
            rel = _rel(p)
            if not _skip(rel, with_books):
                out.append((p, rel))
    return out


def size_estimate(with_books: bool = False) -> int:
    n = 0
    for p, _ in files(with_books):
        try:
            n += p.stat().st_size
        except OSError:
            pass
    return n


def _db_copy(src: pathlib.Path, dst: pathlib.Path) -> None:
    """نسخةٌ متّسقةٌ من قاعدة sqlite ولو كانت مفتوحةً للكتابة."""
    s = sqlite3.connect(f"file:{src}?mode=ro", uri=True, timeout=60)
    d = sqlite3.connect(str(dst))
    try:
        s.backup(d)
    finally:
        d.close()
        s.close()


def _is_db(p: pathlib.Path) -> bool:
    if not p.name.endswith(DB_SUFFIXES):
        return False
    try:
        with p.open("rb") as f:
            return f.read(16) == b"SQLite format 3\x00"
    except OSError:
        return False


def summary() -> dict:
    """ما في المكتبة الآن: عددُ الكتب المقروءة والمسوّدات (للبيان وللتذكير)."""
    out = {"books": 0, "done": 0, "drafts": 0, "quotes": 0}
    try:
        con = sqlite3.connect(f"file:{common.STORE_DB}?mode=ro", uri=True, timeout=10)
        try:
            out["books"] = con.execute("SELECT COUNT(*) FROM books WHERE state != 'missing'").fetchone()[0]
            out["done"] = con.execute("SELECT COUNT(*) FROM books WHERE done_pages > 0").fetchone()[0]
        finally:
            con.close()
    except sqlite3.Error:
        pass
    try:
        d = json.loads((common.DATA / "drafts.json").read_text(encoding="utf-8"))
        ds = d.get("drafts", []) if isinstance(d, dict) else []
        out["drafts"] = sum(1 for x in ds if x.get("items"))
        out["quotes"] = sum(1 for x in ds for it in x.get("items", []) if it.get("kind") == "quote")
    except (OSError, ValueError, AttributeError):
        pass
    return out


def make(dest: pathlib.Path, with_books: bool = False, progress=None) -> dict:
    """يصنع النسخة في dest (ملفّ zip). progress(تمّ, الكلّ) إن أُعطيت."""
    dest = pathlib.Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    items = files(with_books)
    total = sum(p.stat().st_size for p, _ in items if p.exists()) or 1
    done = 0
    tmp_zip = dest.with_name(dest.name + ".part")
    with tempfile.TemporaryDirectory() as td:
        with zipfile.ZipFile(tmp_zip, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
            for p, rel in items:
                try:
                    sz = p.stat().st_size
                except OSError:
                    continue
                if _is_db(p):
                    c = pathlib.Path(td) / "copy.db"
                    _db_copy(p, c)
                    z.write(c, rel)
                    c.unlink()
                else:
                    try:
                        z.write(p, rel)
                    except OSError:
                        continue       # ملفٌّ مقفلٌ أو حُذف أثناء النسخ: لا يُفسد النسخةَ كلَّها
                done += sz
                if progress:
                    progress(done, total)
            man = {"app": common.NAME, "version": common.VERSION, "created": common.now(),
                   "data": str(common.DATA), "books_dir": str(common.BOOKS),
                   "sources": common.load_config().get("sources", []),
                   "with_books": bool(with_books), "summary": summary(), "files": len(items)}
            z.writestr(MANIFEST, json.dumps(man, ensure_ascii=False, indent=1))
    tmp_zip.replace(dest)
    st = load_state()
    st.update({"last": common.now(), "last_ts": time.time(), "last_path": str(dest), "snooze_until": 0})
    common.write_json(STATE, st)
    return {"ok": True, "path": str(dest), "size": dest.stat().st_size, "files": len(items)}


def read_manifest(zpath: pathlib.Path) -> dict:
    try:
        with zipfile.ZipFile(zpath) as z:
            man = json.loads(z.read(MANIFEST).decode("utf-8"))
    except (OSError, KeyError, ValueError, zipfile.BadZipFile):
        raise ValueError("هذا الملفّ ليس نسخةً احتياطيّةً من «بُغية».")
    if man.get("app") != common.NAME:
        raise ValueError("هذا الملفّ ليس نسخةً احتياطيّةً من «بُغية».")
    return man


def _safe_member(name: str) -> bool:
    p = pathlib.PurePosixPath(name)
    return not (p.is_absolute() or ".." in p.parts or ":" in name or name.startswith(("/", "\\")))


def _prune_safety() -> None:
    olds = sorted(x for x in common.DATA.iterdir() if x.is_dir() and x.name.startswith(SAFETY_PREFIX))
    for x in olds[:-KEEP_SAFETY]:
        shutil.rmtree(x, ignore_errors=True)


def restore(zpath: pathlib.Path) -> dict:
    """يكتب بياناتِ النسخة في مجلّد البيانات بعد حفظ الحاليّة. القراءةُ يجب أن تكون متوقّفة."""
    zpath = pathlib.Path(zpath)
    man = read_manifest(zpath)
    common.DATA.mkdir(parents=True, exist_ok=True)
    safety = common.DATA / (SAFETY_PREFIX + time.strftime("%Y-%m-%d-%H%M%S"))
    with zipfile.ZipFile(zpath) as z:
        names = [n for n in z.namelist() if n != MANIFEST and not n.endswith("/")]
        bad = [n for n in names if not _safe_member(n)]
        if bad:
            raise ValueError("في النسخة مسارٌ غيرُ سليم، فلم تُسترجَع: " + bad[0])
        # ١. البياناتُ الحاليّة التي ستُكتب فوقها تُحفظ أوّلًا
        for n in names:
            cur = common.DATA / n
            if cur.is_file():
                keep = safety / n
                keep.parent.mkdir(parents=True, exist_ok=True)
                if _is_db(cur):
                    _db_copy(cur, keep)
                else:
                    shutil.copy2(cur, keep)
        # ٢. الكتابة
        with tempfile.TemporaryDirectory() as td:
            for n in names:
                out = common.DATA / n
                out.parent.mkdir(parents=True, exist_ok=True)
                if n.endswith(DB_SUFFIXES) and out.exists() and _is_db(out):
                    # القاعدةُ قد تكون مفتوحةً (الصفحة): تُكتب فوقها بأداة sqlite لا باستبدال الملفّ
                    t = pathlib.Path(td) / "in.db"
                    with z.open(n) as src, t.open("wb") as dst:
                        shutil.copyfileobj(src, dst)
                    s = sqlite3.connect(str(t))
                    d = sqlite3.connect(str(out), timeout=60)
                    try:
                        s.backup(d)
                    finally:
                        d.close()
                        s.close()
                    t.unlink()
                else:
                    tmp = out.with_name(out.name + ".restoring")
                    with z.open(n) as src, tmp.open("wb") as dst:
                        shutil.copyfileobj(src, dst)
                    for i in range(20):
                        try:
                            tmp.replace(out)
                            break
                        except PermissionError:
                            if i == 19:
                                raise
                            time.sleep(0.1 * (i + 1))
    _prune_safety()
    st = load_state()
    st.update({"restored": common.now(), "restored_from": str(zpath), "snooze_until": 0})
    common.write_json(STATE, st)
    return {"ok": True, "manifest": man, "files": len(names), "safety": str(safety) if safety.exists() else ""}


def missing_sources() -> list:
    """مجلّداتُ الكتب المسجّلة التي لا وجودَ لها على هذا الجهاز."""
    return [s for s in common.load_config().get("sources", []) if not pathlib.Path(s).expanduser().exists()]


def relink(new_folder: str = "") -> dict:
    """يُلحق الكتبَ بمواضعها الجديدة: يُضاف المجلّدُ الجديد مصدرًا، وتُزال المصادرُ الغائبة،
    ثمّ يفحص المكتبةَ فيتعرّف على كلّ كتابٍ ببصمته."""
    import maktaba
    import store
    cfg = common.load_config()
    gone = [s for s in cfg.get("sources", []) if not pathlib.Path(s).expanduser().exists()]
    keep = [s for s in cfg.get("sources", []) if s not in gone]
    if new_folder:
        nf = str(pathlib.Path(new_folder).expanduser().resolve())
        if not pathlib.Path(nf).is_dir():
            raise ValueError("المجلّدُ غيرُ موجود: " + new_folder)
        if os.path.normcase(nf) not in {os.path.normcase(str(pathlib.Path(s).resolve())) for s in keep}:
            keep.append(nf)
        # الملفّاتُ المستبعَدة (.exclude) مسجّلةٌ بمواضعها القديمة: تُنقل إلى الموضع الجديد إن كان المصدرُ الغائبُ واحدًا
        if len(gone) == 1:
            _remap_excluded(gone[0], nf)
    cfg["sources"] = keep
    common.save_config(cfg)
    # الكتبُ المسحوبةُ في مجلّد البيانات القديم (books/) تُعرف ببصمتها في مجلّد البيانات الجديد
    con = store.connect()
    try:
        stats = maktaba.sync(con)
        total = con.execute("SELECT COUNT(*) FROM books").fetchone()[0]
        miss = [r[0] for r in con.execute("SELECT COALESCE(title, path) FROM books WHERE state = 'missing' ORDER BY id")]
    finally:
        con.close()
    return {"ok": True, "moved": stats.get("moved", 0), "new": stats.get("new", 0), "total": total,
            "missing": len(miss), "missing_titles": miss[:30], "removed_sources": gone}


def _remap_excluded(old: str, new: str) -> None:
    import maktaba
    try:
        lines = maktaba.EXCLUDE.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    o = os.path.normcase(old.rstrip("\\/"))
    out = []
    for ln in lines:
        if os.path.normcase(ln).startswith(o + os.sep):
            ln = new.rstrip("\\/") + ln[len(o):]
        out.append(ln)
    maktaba.EXCLUDE.write_text("\n".join(out) + ("\n" if out else ""), encoding="utf-8")


# ───────────────────────── التذكير ─────────────────────────

REMIND_DAYS = 30
SNOOZE_DAYS = 14


def load_state() -> dict:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def snooze() -> None:
    st = load_state()
    st["snooze_until"] = time.time() + SNOOZE_DAYS * 86400
    common.write_json(STATE, st)


def state() -> dict:
    """آخرُ نسخة، وهل يُذكَّر المستخدم: لا يُذكَّر إلّا من عنده ما يستحقّ الحفظ."""
    st = load_state()
    s = summary()
    worth = s["done"] > 0 or s["quotes"] > 0
    last_ts = st.get("last_ts") or 0
    days = int((time.time() - last_ts) // 86400) if last_ts else None
    # أوّلُ استعمالٍ بلا نسخة: يُحسب الشهرُ من أوّل مرّة رآه البرنامج (لا يُذكَّر من نصّب أمس)
    if not last_ts:
        first = st.get("first_seen")
        if not first:
            st["first_seen"] = first = time.time()
            try:
                common.write_json(STATE, st)
            except OSError:
                pass
        due = time.time() - first > REMIND_DAYS * 86400
    else:
        due = days >= REMIND_DAYS
    remind = bool(worth and due and time.time() > (st.get("snooze_until") or 0))
    return {"last": st.get("last"), "days": days, "last_path": st.get("last_path"), "remind": remind,
            "summary": s, "size": size_estimate(False), "books_size": _books_size(),
            "missing_sources": missing_sources()}


def _books_size() -> int:
    n = 0
    if common.BOOKS.exists():
        for dirpath, _, fns in os.walk(common.BOOKS):
            for fn in fns:
                try:
                    n += os.path.getsize(os.path.join(dirpath, fn))
                except OSError:
                    pass
    return n


def default_name() -> str:
    return "بغية - نسخة احتياطية %s.zip" % time.strftime("%Y-%m-%d")
