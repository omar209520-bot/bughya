#!/usr/bin/env python3
"""«بُغية»: صفحةُ بحثٍ في المتصفّح يبحث بها المستخدم في كتبه بنفسه، بلا إنترنت.

  wajiha.py               يشغّل الخادمَ على جهازه (127.0.0.1:8777) ويفتح الصفحة؛ فإن كان يعمل فتحها فقط
  wajiha.py --no-open     بلا فتح المتصفّح (للفحص)

لا تبحث الصفحةُ بنفسها: كلُّ طلبٍ يُمرَّر إلى أدوات المحرّك (bahth · nass · sura · mustalah · maktaba · tadqiq)
بمخرجها --json، فالنتائجُ هي نتائجُها بحروفها. وبياناتُ المستخدم كلُّها في مجلّدٍ خاصّ به (common.DATA).
ويُغلق الخادمُ نفسه إذا أُغلقت الصفحة كلُّها بضع دقائق.
"""
import argparse
import json
import os
import pathlib
import re
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import bahth  # noqa: E402
import common  # noqa: E402
import tkinter_dialog  # noqa: E402

HOST, PORT = "127.0.0.1", int(os.environ.get("BUGHYA_PORT") or 8777)   # والمنفذُ يُغيَّر للتجربة
GROUPS = common.GROUPS
IDLE = 300            # ثوانٍ بلا صفحةٍ مفتوحة ثمّ يُغلق الخادم
_last_ping = [time.time()]
_lock = threading.Lock()
NOWIN = 0x08000000 if common.IS_WIN else 0   # CREATE_NO_WINDOW: لا تظهر نافذةُ طرفيّةٍ مع كلّ بحث


def run(tool: str, *args, timeout: int = 180) -> tuple:
    """تشغيلُ أداةٍ من أدوات المحرّك: (المخرج، رمز الخروج)."""
    env = dict(__import__("os").environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    p = subprocess.run(common.tool_cmd(tool, *args), capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=timeout, env=env, cwd=str(common.APP),
                       creationflags=NOWIN)
    return p.stdout, p.returncode


def run_json(tool: str, *args):
    out, code = run(tool, *args)
    try:
        return json.loads(out)
    except ValueError:
        msg = out.strip().splitlines()[-1].lstrip("✗ ").strip() if out.strip() else "تعذّر تشغيلُ الأداة."
        return {"error": msg}


# ───────────────────────── البحث ─────────────────────────

def search_args(q: dict) -> list:
    """خياراتُ bahth.py من طلب الصفحة. والمجموعةُ (ألفاظٌ عدّة) تُجمع صيغةً واحدة: كلُّ لفظٍ بسوابقه، بينها OR."""
    mode = q.get("mode", "phrase")
    text = q.get("q", "").strip()
    rasm, exact = q.get("rasm") == "1", q.get("exact") == "1"
    if mode == "group":
        terms = [t.strip() for t in text.split("\n") if t.strip()]
        parts = []
        for t in terms:
            toks = bahth.query_tokens(t)
            if toks:
                parts.append(bahth.build("phrase", toks, exact, rasm)[0])
        args = ["--query", " OR ".join(parts) or '""']
    elif mode == "phrase":
        args = [text]
    else:
        args = ["--" + mode, text]
    if mode == "near":
        args += ["--dist", q.get("dist", "10")]
    if exact and mode in ("phrase", "words", "any"):
        args.append("--exact")
    if rasm:
        args.append("--rasm")
    if q.get("layer") in ("body", "foot"):
        args += ["--layer", q["layer"]]
    if q.get("fann"):
        args += ["--fann", q["fann"]]
    return args


def api_search(q: dict) -> dict:
    if not q.get("q", "").strip():
        return {"error": "اكتب ما تبحث عنه."}
    base = search_args(q)
    res_args = base + ["--json", "--limit", q.get("limit", "30"), "--offset", q.get("offset", "0"),
                       "--order", q.get("order", "rank")]
    if q.get("facet") == "only":       # قائمةُ الكتب للبحث كلّه (بلا حصر): طلبٌ مستقلّ، فلا تنتظرها النتائج
        f = run_json("bahth.py", *(base + ["--json", "--facet"]))
        return f if "error" in f else {"facet": f["books"]}
    if q.get("books"):
        res_args += ["--book", q["books"]]
    return run_json("bahth.py", *res_args)


def api_image(q: dict) -> dict:
    args = [q["b"], q["n"]]
    if q.get("mark"):
        args += ["--mark", q["mark"], "--full"]
    out, code = run("sura.py", *args)
    last = out.strip().splitlines()[-1] if out.strip() else ""
    if code != 0 or ": " not in last:
        return {"error": last.lstrip("✗ ").strip() or "لا صورةَ لهذه الصفحة."}
    path = pathlib.Path(last.rsplit(": ", 1)[1].strip())
    return {"url": "/img/" + urllib.parse.quote(path.name) + "?t=%d" % time.time()}


def api_ayat(q: dict):
    """الآياتُ في الصفحة، في متنها وحاشيتها كلٌّ على حدة، ولا يتغيّر نصُّ الكتاب."""
    import ayat
    import store
    con = store.connect(readonly=True)
    try:
        p = store.page(con, int(q["b"]), int(q["n"]))
    finally:
        con.close()
    if p is None:
        return []
    out = []
    for layer, text in (("متن", p["body"]), ("حاشية", p["foot"])):
        for x in ayat.find(text):
            x["layer"] = layer
            out.append(x)
    return out


def _align(text: str, ws: list, doubt: bool) -> list:
    """كلماتُ النصّ المعروض (أسطرًا) وموضعُ كلٍّ في الصورة من كلمات القراءة الآليّة، وهل هي مشكوكٌ فيها."""
    import difflib
    import arabic
    import lexicon
    lines = [l.split() for l in (text or "").split("\n")]
    flat = [t for l in lines for t in l]
    norm = lambda t: arabic.normalize(t) or t
    boxes = [None] * len(flat)
    sm = difflib.SequenceMatcher(None, [norm(t) for t in flat], [norm(w[0]) for w in ws], autojunk=False)
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal" or (op == "replace" and i2 - i1 == j2 - j1):
            for k in range(i2 - i1):
                boxes[i1 + k] = ws[j1 + k][1:]
    # 1 لا يعرفها القاموس، 2 يعرفها وهي غريبةٌ بين جارتيها ولها بديلٌ في النقط يناسبهما (lexicon.marks)
    mk = lexicon.marks(flat) if doubt else [0] * len(flat)
    out, k = [], 0
    for l in lines:
        row = []
        for t in l:
            row.append({"t": t, "b": boxes[k], "d": bool(mk[k]), "c": mk[k] == 2})
            k += 1
        out.append(row)
    return out


def api_words(q: dict):
    """الصفحةُ المقروءة آليًّا كلماتٍ بمواضعها في الصورة، مع تعليم ما لا يعرفه القاموس."""
    import lexicon
    import store
    con = store.connect(readonly=True)
    try:
        p = store.page(con, int(q["b"]), int(q["n"]))
        boxes = store.boxes_of(p) if p is not None else []
    finally:
        con.close()
    if p is None or p["method"] != "ocr":
        return {"words": False}
    if not any(bx.get("ws") for bx in boxes):     # قُرئ بإصدارٍ قبل حفظ مواضع الكلمات
        return {"words": False, "old": True}
    doubt = lexicon.ready()
    res = {"words": True, "lexicon": doubt}
    for key, lay in (("body", "b"), ("foot", "f")):
        ws = [w for bx in boxes if bx.get("l") == lay for w in (bx.get("ws") or [])]
        res[key] = _align(p[key], ws, doubt)
    return res


def api_groups_get(q: dict):
    return common.read_json(GROUPS, []) or []


def api_groups_set(body: dict):
    groups = body.get("groups")
    if not isinstance(groups, list):
        return {"error": "صيغةٌ غير صحيحة."}
    clean = []
    for g in groups:
        name = str(g.get("name", "")).strip()
        terms = [str(t).strip() for t in g.get("terms", []) if str(t).strip()]
        if name and terms:
            clean.append({"name": name, "terms": terms})
    with _lock:
        common.write_json(GROUPS, clean)
    return clean


def api_coverage(q: dict):
    import store
    con = store.connect(readonly=True)
    try:
        return bahth.coverage(con)
    finally:
        con.close()


def api_books(q: dict):
    rows = run_json("maktaba.py", "books", "--json")
    if isinstance(rows, dict):
        return rows
    import store
    keep = ("id", "title", "author", "death", "fann", "series", "volume", "unit", "state", "kind", "pages", "done_pages",
            "ocr_pages", "hints", "btype", "btype_auto")
    return [dict({k: r.get(k) for k in keep}, unclear=store.unclear_title(r),
                 cover=pathlib.Path(r.get("path") or "").suffix.lower() in (".pdf", ".epub", ".png", ".jpg", ".jpeg",
                                                                            ".tif", ".tiff", ".bmp", ".webp"))
            for r in rows]


def api_book_set(body: dict) -> dict:
    """تسجيلُ عنوان الكتاب ومؤلّفه ووفاته كما يكتبها المستخدم (من صفحة عنوانه)."""
    try:
        b = int(body.get("b"))
    except (TypeError, ValueError):
        return {"error": "رقمُ الكتاب غير صحيح."}
    args = []
    for key in ("title", "author", "death"):
        v = str(body.get(key) or "").strip()
        if v:
            args += ["--" + key, v]
    if not args:
        return {"error": "اكتب العنوانَ على الأقلّ."}
    out, code = run("maktaba.py", "set", b, *args)
    return {"ok": code == 0, "text": out.strip()} if code == 0 else {"error": out.strip().lstrip("✗ ") or "تعذّر الحفظ."}


# ───────────────────────── أصنافُ الكتب ─────────────────────────
# صنفٌ واحدٌ لكلّ كتاب، يختاره الباحث بنفسه (لا اقتراحَ من البرنامج)، ويُحفظ في خانة «الفنّ».
# والقائمةُ يزيد عليها المستخدم، وتُحفظ في categories.json.

CATS_FILE = common.DATA / "categories.json"
DEFAULT_CATS = ["العقيدة", "الفِرق والردود", "الكلام والمنطق", "التفسير وعلوم القرآن", "الحديث وعلومه",
                "شروح الحديث", "الفقه", "أصول الفقه والقواعد", "السيرة والتاريخ والتراجم", "اللغة والأدب",
                "الرقائق والآداب", "رسائل وبحوث جامعيّة", "كتاباتي", "أخرى"]


def cats() -> list:
    c = common.read_json(CATS_FILE, None)
    return c if isinstance(c, list) and c else list(DEFAULT_CATS)


def api_cats_get(q: dict):
    return cats()


def api_cats_set(body: dict):
    clean = []
    for c in body.get("cats", []):
        c = str(c).strip()
        if c and c not in clean and len(c) <= 40:
            clean.append(c)
    if not clean:
        return {"error": "القائمةُ فارغة."}
    with _lock:
        common.write_json(CATS_FILE, clean)
    return clean


def api_book_cat(body: dict) -> dict:
    """صنفُ الكتاب (أو حذفُه بقيمةٍ فارغة)."""
    try:
        b = int(body.get("b"))
    except (TypeError, ValueError):
        return {"error": "رقمُ الكتاب غير صحيح."}
    c = str(body.get("fann") or "").strip()
    if c and c not in cats():
        return {"error": "صنفٌ غير موجود في القائمة."}
    out, code = run("maktaba.py", "set", b, "--fann", c)
    return {"ok": True} if code == 0 else {"error": out.strip().lstrip("✗ ") or "تعذّر الحفظ."}


# ───────────────────────── أغلفةُ الكتب ─────────────────────────
# صورةٌ صغيرة من أوّل صفحةٍ ليست بيضاء (أو من الصفحة التي اختارها المستخدم)، تُصنع مرّةً وتُحفظ.
# الملفُّ الأصليّ لا يُكتب فيه شيء.

COVERS = common.DATA / "covers"
COVER_CHOICE = COVERS / "choice.json"
_cover_lock = threading.Lock()


def cover_png(bid: int):
    import store
    con = store.connect(readonly=True)
    try:
        b = store.book(con, bid)
    finally:
        con.close()
    if b is None or b["state"] == "missing":
        return None
    path = pathlib.Path(b["path"])
    if path.suffix.lower() not in (".pdf", ".epub", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"):
        return None
    if not path.is_file():
        return None
    chosen = (common.read_json(COVER_CHOICE, {}) or {}).get(str(bid))
    st = path.stat()
    f = COVERS / ("%d_%s_%d.png" % (bid, chosen or "a", int(st.st_mtime)))
    if f.is_file():
        return f.read_bytes()
    try:
        import pymupdf as fitz
    except ImportError:
        import fitz
    with _cover_lock:
        COVERS.mkdir(parents=True, exist_ok=True)
        for old in COVERS.glob("%d_*.png" % bid):
            old.unlink(missing_ok=True)
        doc = fitz.open(path)
        try:
            if not len(doc):
                return None
            if chosen and 1 <= int(chosen) <= len(doc):
                k = int(chosen) - 1
            else:
                k = 0
                for i in range(min(len(doc), 4)):          # أوّلُ صفحةٍ ليست بيضاء
                    sm = doc[i].get_pixmap(matrix=fitz.Matrix(0.05, 0.05), colorspace=fitz.csGRAY)
                    if sum(1 for v in sm.samples if v < 200) / max(1, len(sm.samples)) > 0.01:
                        k = i
                        break
            pg = doc[k]
            z = 360 / max(1, pg.rect.width)               # عرضٌ ثابتٌ صغير
            pg.get_pixmap(matrix=fitz.Matrix(z, z)).save(f)
        finally:
            doc.close()
    return f.read_bytes()


def api_uninstall(body: dict) -> dict:
    """إزالةُ البرنامج: يُشغَّل مُزيلُ التنصيب ثمّ يُغلق البرنامجُ نفسه، ليقدر المزيلُ على حذف ملفّاته.
    والكتبُ المقروءة والإعدادات (في مجلّد البيانات) لا يمسّها المزيل."""
    if not getattr(sys, "frozen", False):
        return {"error": "الإزالةُ متاحةٌ في البرنامج المنصَّب وحده."}
    unins = sorted(pathlib.Path(sys.executable).parent.glob("unins*.exe"))
    if not unins:
        return {"error": "لم أجد مُزيلَ التنصيب في مجلّد البرنامج. أزِله من إعدادات ويندوز ← التطبيقات."}
    subprocess.Popen([str(unins[-1])], close_fds=True)
    threading.Timer(1.5, lambda: os._exit(0)).start()
    return {"ok": True}


def api_cover_set(body: dict) -> dict:
    """اجعل هذه الصفحة غلافَ الكتاب (أو «تلقائيّ» بلا صفحة)."""
    try:
        b = int(body.get("b"))
        n = int(body["n"]) if body.get("n") else None
    except (TypeError, ValueError):
        return {"error": "رقمٌ غير صحيح."}
    with _cover_lock:
        ch = common.read_json(COVER_CHOICE, {}) or {}
        if n:
            ch[str(b)] = n
        else:
            ch.pop(str(b), None)
        COVERS.mkdir(parents=True, exist_ok=True)
        common.write_json(COVER_CHOICE, ch)
        for old in COVERS.glob("%d_*.png" % b):
            old.unlink(missing_ok=True)
    return {"ok": True}


# ───────────────────────── الكتب والقراءة والتدقيق ─────────────────────────

_book_ext = []
_ocr_cache = [0.0, None]
_run_cache = [0.0, False]
JOBS = {}


def book_exts() -> set:
    if not _book_ext:
        from readers import KINDS
        _book_ext.append(set(KINDS))
    return _book_ext[0]


def safe_rel(rel: str) -> pathlib.Path:
    parts = []
    for x in rel.replace("\\", "/").split("/"):
        x = re.sub(r'[<>:"|?*\x00-\x1f]', "_", x).strip().strip(".")
        if x:
            parts.append(x[:150])
    if not parts:
        raise ValueError("اسمُ الملفّ فارغ")
    return pathlib.Path(*parts)


def save_upload(handler, base: pathlib.Path, rel: str, allowed) -> dict:
    n = int(handler.headers.get("Content-Length") or 0)
    p = safe_rel(rel)
    if p.suffix.lower() not in allowed:
        left = n
        while left > 0:                       # يُستهلك الجسمُ ولا يُحفظ
            left -= len(handler.rfile.read(min(1 << 20, left)) or b"0")
        return {"skipped": True}
    dest = base / p
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    left = n
    with tmp.open("wb") as f:
        while left > 0:
            chunk = handler.rfile.read(min(1 << 20, left))
            if not chunk:
                break
            f.write(chunk)
            left -= len(chunk)
    tmp.replace(dest)
    return {"ok": True, "size": n}


def api_btype(body: dict) -> dict:
    t = str(body.get("t", ""))
    if t not in ("modern_print", "old_print", "lithograph", "manuscript", "auto"):
        return {"error": "نوعٌ غير معروف."}
    out, code = run("maktaba.py", "set", int(body["b"]), "--btype", t)
    return {"ok": code == 0, "text": out.strip()}


def api_progress(q: dict) -> dict:
    import maktaba
    import store
    pr = common.read_json(common.PROGRESS, {}) or {}
    if time.time() - _run_cache[0] > 2:
        _run_cache[0], _run_cache[1] = time.time(), maktaba.running() is not None
    live = _run_cache[1]
    con = store.connect(readonly=True)
    try:
        c = maktaba.counts(con)
        scanned = con.execute("SELECT COUNT(*) FROM books WHERE state != 'missing' AND ocr_pages = 0 AND "
                              "(state = 'empty' OR (scanned_guess = 1 AND weak_pages > 0))").fetchone()[0]
        errors = [{"title": r["title"], "error": r["error"], "state": r["state"]} for r in con.execute(
            "SELECT title, error, state FROM books WHERE state IN ('error', 'unsupported') ORDER BY id LIMIT 30")]
        pages = con.execute("SELECT COUNT(*) FROM pages").fetchone()[0]
    finally:
        con.close()
    return {"books_total": c["books_total"], "books_done": c["books_done"], "pending": c["pending"], "pages": pages,
            "running": live, "scanned_unread": scanned, "errors": errors,
            "sources": [str(x) for x in common.sources() if str(x) != str(common.BOOKS)],
            "current_title": pr.get("current_title") if live else None,
            "current_page": pr.get("current_page") if live else None,
            "current_pages": pr.get("current_pages") if live else None,
            "current_method": pr.get("current_method") if live else None,
            "error": pr.get("error")}


def api_ocr(q: dict) -> dict:
    if _ocr_cache[1] is None or q.get("fresh") == "1" or time.time() - _ocr_cache[0] > 60:
        _ocr_cache[1] = run_json("maktaba.py", "ocr", "--json")
        _ocr_cache[0] = time.time()
    return _ocr_cache[1]


def api_pick_folder(body: dict) -> dict:
    path = tkinter_dialog.pick_folder()
    if not path:
        return {"cancelled": True}
    out, code = run("maktaba.py", "sources", "add", path)
    if code != 0:
        return {"error": out.strip().splitlines()[-1].lstrip("✗ ").strip() if out.strip() else "تعذّرت إضافةُ المجلّد."}
    return {"ok": True, "path": path}


def api_update(body: dict) -> dict:
    return {"text": run("maktaba.py", "update", "--detach")[0].strip()}


def api_reread_scanned(body: dict) -> dict:
    ocr = api_ocr({"fresh": "1"})
    if not ocr.get("ok"):
        return {"error": "القراءةُ الآليّة ما زالت غير متاحة: " + (ocr.get("reason") or "")}
    out, code = run("maktaba.py", "reread", "--scanned")
    if code != 0:
        return {"error": out.strip().splitlines()[-1].lstrip("✗ ").strip() if out.strip() else "تعذّر."}
    run("maktaba.py", "update", "--detach")
    return {"text": out.strip()}


def api_reread_book(body: dict) -> dict:
    """أعد قراءةَ كتابٍ واحدٍ من أوّله (قُرئ بإصدارٍ أقدم)، ثمّ ابدأ القراءة في الخلفيّة."""
    out, code = run("maktaba.py", "reread", str(int(body.get("b"))))
    if code != 0:
        return {"error": out.strip().splitlines()[-1].lstrip("✗ ").strip() if out.strip() else "تعذّر."}
    run("maktaba.py", "update", "--detach")
    return {"text": out.strip()}


def api_stop(body: dict) -> dict:
    return {"text": run("maktaba.py", "stop")[0].strip()}


def _vnum(v: str) -> tuple:
    return tuple(int(x) for x in re.findall(r"\d+", v or "")[:3]) or (0,)


def api_update_check(q: dict) -> dict:
    """آخرُ إصدارٍ منشورٍ في صفحة الإصدارات، وهل هو أحدثُ من هذا. لا يُنزَّل شيءٌ ولا يُنصَّب."""
    req = urllib.request.Request(common.RELEASES_API, headers={
        "User-Agent": "Bughya/" + common.VERSION, "Accept": "application/vnd.github+json"})
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            rel = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return {"ok": False, "reason": "لم يُنشر إصدارٌ بعد."}
        return {"ok": False, "reason": "تعذّر السؤالُ عن التحديث (%s)." % e.code}
    except Exception:
        return {"ok": False, "reason": "تعذّر الاتّصال بالإنترنت."}
    latest = (rel.get("tag_name") or "").lstrip("vV")
    exe = [a.get("browser_download_url") for a in rel.get("assets") or [] if (a.get("name") or "").lower().endswith(".exe")]
    url = exe[0] if exe else rel.get("html_url")
    return {"ok": True, "current": common.VERSION, "latest": latest, "newer": _vnum(latest) > _vnum(common.VERSION),
            "url": url if (url or "").startswith("https://github.com/") else None}


def api_open_update(body: dict) -> dict:
    """يفتح رابطَ التحديث في المتصفّح، ولا يقبل إلّا روابط github.com (من صفحة الإصدارات)."""
    url = str(body.get("url") or "")
    if not url.startswith("https://github.com/omar209520-bot/bughya/"):
        return {"error": "رابطٌ غيرُ مقبول."}
    webbrowser.open(url)
    return {"ok": True}


def api_open_settings(body: dict) -> dict:
    try:
        os.startfile("ms-settings:regionlanguage")
        return {"ok": True}
    except Exception as e:
        return {"error": "تعذّر فتحُ الإعدادات: %s" % e}


def api_tadqiq_start(body: dict) -> dict:
    name = safe_rel(str(body.get("file", ""))).name
    src = common.INBOX / name
    if not src.is_file() or src.suffix.lower() != ".docx":
        return {"error": "لم أجد ملفّ وورد (docx) بهذا الاسم."}
    jid = uuid.uuid4().hex[:10]
    jf = common.INBOX / (".job-%s.json" % jid)
    common.write_json(jf, {"state": "running", "done": 0, "total": 0})
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    subprocess.Popen(common.tool_cmd("tadqiq", src, "--job", jf), cwd=str(common.APP), env=env,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=NOWIN)
    JOBS[jid] = jf
    return {"id": jid}


def api_tadqiq_job(q: dict) -> dict:
    jf = JOBS.get(q.get("id", ""))
    if jf is None:
        return {"error": "لا عملَ بهذا الرقم."}
    st = common.read_json(jf, {}) or {}
    if st.get("state") == "done":
        st["result"] = common.read_json(pathlib.Path(st["json"]), {}) or {}
    return st


def api_tadqiq_xlsx(q: dict) -> dict:
    jf = JOBS.get(q.get("id", ""))
    st = common.read_json(jf, {}) if jf else None
    if not st or st.get("state") != "done":
        return {"error": "لم يكتمل التدقيقُ بعد."}
    out, code = run("tadqiq.py", "x.docx", "--xlsx-from", st["json"])
    path = pathlib.Path(out.strip().splitlines()[-1]) if out.strip() else None
    if code != 0 or path is None or not path.is_file():
        return {"error": "تعذّر إنشاءُ ملفّ إكسل."}
    downloads = pathlib.Path.home() / "Downloads"
    downloads.mkdir(exist_ok=True)
    dest = downloads / path.name
    n = 1
    while dest.exists():
        n += 1
        dest = downloads / ("%s (%d)%s" % (path.stem, n, path.suffix))
    dest.write_bytes(path.read_bytes())
    try:
        os.startfile(str(dest))
    except OSError:
        pass
    return {"name": dest.name, "path": str(dest)}


def api_excl_get(q: dict):
    import store
    import tadqiq
    con = store.connect(readonly=True)
    try:
        own = tadqiq.excluded(con)
        rows = con.execute("SELECT id, title, series, volume FROM books WHERE state != 'missing' "
                           "ORDER BY COALESCE(series, title), volume, id").fetchall()
        return [{"id": r["id"], "title": (r["series"] or r["title"] or "") + (" ج%d" % r["volume"] if r["volume"] else ""),
                 "own": r["id"] in own} for r in rows]
    finally:
        con.close()


def api_excl_set(body: dict):
    import store
    ids = {int(x) for x in body.get("ids", [])}
    con = store.connect(readonly=True)
    try:
        titles = {r["id"]: r["title"] for r in con.execute("SELECT id, title FROM books")}
    finally:
        con.close()
    with _lock:
        common.write_json(common.EXCLUSIONS, {
            "شرح": "كتاباتُك أنت في المكتبة (بحوثُك وفصولُك ومسوّداتُها): لا يعدّها المدقّق مصدرًا.",
            "books": {str(i): titles.get(i, "") for i in sorted(ids) if i in titles}})
    return {"ok": True, "n": len(ids)}


# ───────────────────────── المسوّدة ─────────────────────────

def api_drafts_get(q: dict):
    import musawwada
    return musawwada.load()


def api_drafts_set(body: dict):
    import musawwada
    with _lock:
        return musawwada.save(body)


def api_draft_check(body: dict):
    import musawwada
    it = body.get("item") or {}
    if not it.get("b") or not it.get("n") or not str(it.get("text") or "").strip():
        return {"error": "نقلٌ بلا كتابٍ أو صفحةٍ أو نصّ."}
    return musawwada.check(it)


def _draft(body: dict):
    import musawwada
    d = next((x for x in musawwada.load()["drafts"] if x["id"] == body.get("id")), None)
    if d is None or not (d.get("items") or any(p.get("c") for p in d.get("body") or [])):
        return None
    return d


def api_draft_docx(body: dict) -> dict:
    import musawwada
    d = _draft(body)
    if d is None:
        return {"error": "المسوّدةُ فارغة."}
    path = musawwada.out_path(d["name"], ".docx")
    path.write_bytes(musawwada.docx_bytes(d))
    try:
        os.startfile(str(path))
    except (OSError, AttributeError):
        pass
    return {"name": path.name, "path": str(path)}


def api_draft_pdf(body: dict) -> dict:
    """PDF من صفحة طباعة المسوّدة (تبنيها الصفحة نفسُها) بمتصفّح إدج في الخفاء، بلا وورد؛
    والحواشي في آخرها. وإن لم يوجد إدج طبعت الصفحةُ بنافذة الطباعة."""
    import musawwada
    d = _draft(body)
    if d is None:
        return {"error": "المسوّدةُ فارغة."}
    html = str(body.get("html") or "")
    if not html.startswith("<!doctype html>") or len(html) > 20_000_000:
        return {"error": "صفحةُ الطباعة غيرُ صالحة."}
    pdf = musawwada.out_path(d["name"], ".pdf")
    if not musawwada.html_pdf(html, pdf):
        return {"fallback": True}
    try:
        os.startfile(str(pdf))
    except (OSError, AttributeError):
        pass
    return {"name": pdf.name, "path": str(pdf)}


GET = {
    "/api/ayat": api_ayat,
    "/api/words": api_words,
    "/api/progress": api_progress,
    "/api/ocr": api_ocr,
    "/api/tadqiq/job": api_tadqiq_job,
    "/api/tadqiq/xlsx": api_tadqiq_xlsx,
    "/api/exclusions": api_excl_get,
    "/api/search": api_search,
    "/api/page": lambda q: run_json("nass.py", q["b"], q["n"], "--json"),
    "/api/toc": lambda q: run_json("nass.py", q["b"], "--toc", "--json"),
    "/api/image": api_image,
    "/api/jiwar": lambda q: run_json("mustalah.py", "jiwar", q["q"], "--top", q.get("top", "25"), "--json"),
    "/api/measure": lambda q: run_json("mustalah.py", "measure", *[t for t in q["q"].split("\n") if t.strip()], "--json"),
    "/api/status": lambda q: {"text": run("maktaba.py", "status")[0].strip()},
    "/api/books": api_books,
    "/api/update-check": api_update_check,
    "/api/coverage": api_coverage,
    "/api/groups": api_groups_get,
    "/api/cats": api_cats_get,
    "/api/drafts": api_drafts_get,
}
POST = {
    "/api/update": api_update,
    "/api/groups": api_groups_set,
    "/api/pick-folder": api_pick_folder,
    "/api/btype": api_btype,
    "/api/book-set": api_book_set,
    "/api/book-cat": api_book_cat,
    "/api/cats": api_cats_set,
    "/api/cover-set": api_cover_set,
    "/api/uninstall": api_uninstall,
    "/api/reread-scanned": api_reread_scanned,
    "/api/reread-book": api_reread_book,
    "/api/stop": api_stop,
    "/api/open-settings": api_open_settings,
    "/api/open-update": api_open_update,
    "/api/tadqiq/start": api_tadqiq_start,
    "/api/exclusions": api_excl_set,
    "/api/drafts": api_drafts_set,
    "/api/draft/check": api_draft_check,
    "/api/draft/docx": api_draft_docx,
    "/api/draft/pdf": api_draft_pdf,
}


# ───────────────────────── الخادم ─────────────────────────

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code: int, data: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _json(self, obj, code: int = 200) -> None:
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def _local(self) -> bool:
        """لا تُقبل الطلباتُ إلّا من الصفحة نفسها: يُرفض ما جاء من موقعٍ آخر في المتصفّح."""
        host = self.headers.get("Host", "")
        origin = self.headers.get("Origin")
        ok_hosts = ("%s:%d" % (HOST, PORT), "localhost:%d" % PORT)
        return host in ok_hosts and (origin is None or origin in ("http://" + h for h in ok_hosts))

    def do_GET(self):
        if not self._local():
            return self._send(403, b"", "text/plain")
        u = urllib.parse.urlsplit(self.path)
        q = {k: v[-1] for k, v in urllib.parse.parse_qs(u.query).items()}
        _last_ping[0] = time.time()
        if u.path in ("/", "/index.html"):
            ver = common.ar(common.VERSION).replace(".", "٫")
            return self._send(200, PAGE.replace("__VER__", ver).encode("utf-8"), "text/html; charset=utf-8")
        if u.path.startswith("/font/"):     # خطُّ الرقعة لاسم البرنامج (رخصة SIL OFL، معه في data/fonts)
            f = common.APP_DATA / "fonts" / pathlib.Path(u.path).name
            if f.suffix == ".ttf" and f.is_file():
                return self._send(200, f.read_bytes(), "font/ttf")
        if u.path == "/icon.png":
            return self._send(200, (common.APP_DATA / "bughya.png").read_bytes(), "image/png")
        if u.path == "/api/ping":
            return self._json({"ok": True})
        if u.path.startswith("/img/"):
            name = pathlib.Path(urllib.parse.unquote(u.path[5:])).name
            f = common.IMAGES / name
            if f.suffix.lower() == ".png" and f.is_file():
                return self._send(200, f.read_bytes(), "image/png")
            return self._send(404, b"", "text/plain")
        if u.path.startswith("/cover/"):      # غلافُ الكتاب من صفحته
            try:
                data = cover_png(int(pathlib.Path(u.path).stem))
            except Exception:
                data = None
            if data:
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "max-age=3600")
                self.end_headers()
                self.wfile.write(data)
                return
            return self._send(404, b"", "text/plain")
        if u.path.startswith("/dl/"):
            name = pathlib.Path(urllib.parse.unquote(u.path[4:])).name
            f = common.OUTPUTS / name
            if f.suffix.lower() == ".xlsx" and f.is_file():
                data = f.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
                self.send_header("Content-Disposition", "attachment; filename*=UTF-8''" + urllib.parse.quote(name))
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
            return self._send(404, b"", "text/plain")
        fn = GET.get(u.path)
        if fn is None:
            return self._send(404, b"", "text/plain")
        try:
            self._json(fn(q))
        except Exception as e:  # يُعرض للمستخدم في الصفحة بدل أن يسكت الخادم
            self._json({"error": "خطأ: %s" % e})

    def do_PUT(self):
        if not self._local():
            return self._send(403, b"", "text/plain")
        u = urllib.parse.urlsplit(self.path)
        q = {k: v[-1] for k, v in urllib.parse.parse_qs(u.query).items()}
        _last_ping[0] = time.time()
        try:
            if u.path == "/api/upload":
                self._json(save_upload(self, common.BOOKS, q.get("rel", ""), book_exts()))
            elif u.path == "/api/tadqiq/upload":
                self._json(save_upload(self, common.INBOX, pathlib.Path(q.get("rel", "")).name, {".docx"}))
            else:
                self._send(404, b"", "text/plain")
        except Exception as e:
            self._json({"error": "خطأ: %s" % e})

    def do_POST(self):
        if not self._local():
            return self._send(403, b"", "text/plain")
        fn = POST.get(urllib.parse.urlsplit(self.path).path)
        if fn is None:
            return self._send(404, b"", "text/plain")
        n = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(n) or b"{}")
            self._json(fn(body))
        except Exception as e:
            self._json({"error": "خطأ: %s" % e})


def already_running() -> bool:
    try:
        with urllib.request.urlopen("http://%s:%d/api/ping" % (HOST, PORT), timeout=2) as r:
            return r.status == 200
    except Exception:
        return False


def watchdog(srv) -> None:
    while True:
        time.sleep(30)
        if time.time() - _last_ping[0] > IDLE:
            srv.shutdown()
            return


def start_server():
    """يشغّل الخادم في خيطٍ مستقلّ ويعيده."""
    import store
    store.connect().close()          # يُنشأ المخزنُ فارغًا أوّلَ مرّة، فتعمل الصفحةُ قبل أن يُضاف كتاب
    srv = ThreadingHTTPServer((HOST, PORT), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    common.resume_reading(first_delay=5)
    return srv


def close_splash(*_):
    """شاشةُ البداية (في البرنامج المبنيّ وحده) تُغلق حين تظهر النافذة."""
    try:
        import pyi_splash
        pyi_splash.close()
    except Exception:
        pass


def run_app() -> int:
    """البرنامجُ في نافذته الخاصّة: إغلاقُها يُغلق البرنامج. وقراءةُ الكتب الجارية عمليّةٌ مستقلّة فتُكمل.
    فإن تعذّرت النافذة (مكوّن العرض في ويندوز غير موجود) فُتحت الصفحة في المتصفّح."""
    url = "http://%s:%d/" % (HOST, PORT)
    srv = None if already_running() else start_server()
    try:
        import webview
        webview.settings["ALLOW_DOWNLOADS"] = True
        win = webview.create_window("بُغية", url, width=1280, height=840, min_size=(820, 560), text_select=True)
        win.events.shown += close_splash
        webview.start(gui="edgechromium", private_mode=False, storage_path=str(common.DATA / "window"))
        if srv:
            srv.shutdown()
        return 0
    except Exception as e:
        try:
            common.DATA.mkdir(parents=True, exist_ok=True)
            with (common.DATA / "window-error.txt").open("a", encoding="utf-8") as f:
                f.write(common.now() + " " + repr(e) + "\n")
        except OSError:
            pass
    close_splash()
    webbrowser.open(url)
    if srv:
        threading.Thread(target=watchdog, args=(srv,), daemon=True).start()
        threading.Event().wait()
    return 0


def main() -> int:
    common.setup_io()
    ap = argparse.ArgumentParser(prog="wajiha.py", description="«بُغية»")
    ap.add_argument("--no-open", action="store_true")
    a = ap.parse_args()
    url = "http://%s:%d/" % (HOST, PORT)
    if already_running():
        if not a.no_open:
            webbrowser.open(url)
        return 0
    import store
    store.connect().close()          # يُنشأ المخزنُ فارغًا أوّلَ مرّة، فتعمل الصفحةُ قبل أن يُضاف كتاب
    srv = ThreadingHTTPServer((HOST, PORT), Handler)
    threading.Thread(target=watchdog, args=(srv,), daemon=True).start()
    common.resume_reading(first_delay=5)
    if not a.no_open:
        threading.Timer(0.5, webbrowser.open, (url,)).start()
    print("«بُغية» تعمل على " + url)
    srv.serve_forever()
    return 0


# ───────────────────────── الصفحة ─────────────────────────

PAGE = r"""<!doctype html>
<html lang="ar" dir="rtl"><head><script>try{var t=localStorage.getItem("bughya-theme");if(t=="light"||t=="dark")document.documentElement.dataset.theme=t}catch(e){}</script><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>بُغية</title>
<style>
/* الأخضر والذهبي المألوفان في البرامج الإسلامية، وحمرة العناوين في المخطوط للعزو */
:root{--bg:#f7f3e6;--card:#fffdf6;--ink:#1f2a24;--mute:#5a665d;--line:#ddd6bf;--acc:#0b5240;--acc2:#e9f0e6;--rail:#0b3d2e;--railink:#f1e9cf;--gold:#c9a13f;--mark:#f1dc9a;--rub:#7a1f1f;--foot:#5c4a8a;--ocr:#855414;--err:#a8201a;
--text:"Traditional Arabic","Arabic Typesetting","Amiri",serif;--ui:"Segoe UI",Tahoma,sans-serif}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#12201a;--card:#1a2b23;--ink:#e8e6da;--mute:#a9b3a6;--line:#33453a;--acc:#9fd3b8;--acc2:#1f332a;--rail:#0a2c21;--mark:#6d5716;--rub:#eb9186;--foot:#c2b1ec;--ocr:#e3b071;--err:#f2b8b5}}
:root[data-theme="dark"]{--bg:#12201a;--card:#1a2b23;--ink:#e8e6da;--mute:#a9b3a6;--line:#33453a;--acc:#9fd3b8;--acc2:#1f332a;--rail:#0a2c21;--mark:#6d5716;--rub:#eb9186;--foot:#c2b1ec;--ocr:#e3b071;--err:#f2b8b5}
*{box-sizing:border-box}
html{background:var(--bg)}
body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.7 var(--ui);display:grid;grid-template-columns:186px minmax(0,1fr);min-height:calc(100vh / var(--z,1))}
body>*{grid-column:2}
body>script{display:none}
button,input,select,textarea{font:inherit;color:inherit}
:focus-visible{outline:2px solid var(--gold);outline-offset:2px}
header{grid-column:1;grid-row:1/span 40;background:var(--rail);color:var(--railink);padding:22px 0 14px;display:flex;flex-direction:column;position:sticky;top:0;height:calc(100vh / var(--z,1));overflow:auto}
@font-face{font-family:BRuqaa;src:url(/font/ArefRuqaa-Bold.ttf) format('truetype');font-display:swap}
header .brand{display:flex;align-items:center;gap:8px;margin:0 18px 2px}header .lg{width:56px;height:48px;flex:none}
header h1{font:700 50px/1.1 BRuqaa,var(--text);margin:0;color:#e3c069}
header .tagl{font:16px var(--text);color:#c9d6c6;margin:0 22px 18px}
.ptl{font:700 28px/1.3 var(--text);margin:0 0 14px;color:var(--ink)}.ptl::after{content:'';display:block;width:48px;height:2px;background:var(--gold);margin-top:6px}
header nav{display:flex;flex-direction:column}
header nav button{background:none;border:0;color:var(--railink);text-align:right;padding:9px 22px;font-size:15px;cursor:pointer;border-inline-start:3px solid transparent}
header nav button:hover{background:#ffffff14}
header nav button.on{background:var(--bg);color:var(--ink);border-inline-start-color:var(--gold);font-weight:600}
header .cov{font-size:13px;line-height:1.6;padding:14px 22px 8px;margin-top:auto;color:#c4d0e2}
header .zm{display:flex;gap:6px;padding:0 22px}
header .zm button{background:none;color:var(--railink);border:1px solid #ffffff55;border-radius:3px;padding:0 10px;font-size:15px;cursor:pointer}
.panel{display:none;min-width:0}.panel.on{display:block}
.bar{padding:26px 34px 14px}
.row{display:flex;gap:10px;flex-wrap:wrap}
.bar input[type=text]{flex:1;min-width:220px;font:26px/1.5 var(--text);padding:8px 16px;border:1px solid var(--line);border-bottom:2px solid var(--acc);border-radius:3px;background:var(--card)}
.btn{background:var(--acc);color:#fff;border:0;border-radius:3px;padding:6px 22px;cursor:pointer;font-weight:600}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]) .btn{color:#10192a}}
:root[data-theme="dark"] .btn{color:#10192a}
.btn2{border:1px solid var(--line);color:var(--acc);background:var(--card);border-radius:3px;padding:2px 11px;font-size:14px;cursor:pointer}
.btn2:hover{border-color:var(--acc)}
.btn2:disabled{opacity:.4;cursor:default}
details.more{margin-top:8px;font-size:14px;color:var(--mute)}
details.more summary{cursor:pointer;width:max-content}
.opts{display:flex;gap:16px;flex-wrap:wrap;margin-top:8px;align-items:center}
.opts select,.opts input[type=number]{font-size:14px;background:var(--card);border:1px solid var(--line);border-radius:3px}
.help{font-size:14px;color:var(--mute);margin-top:4px}
main{display:grid;grid-template-columns:minmax(0,1fr) 260px;gap:34px;padding:10px 34px 34px}
main>*{min-width:0}
main>aside{order:2}
aside{align-self:start;max-height:88vh;overflow:auto;position:sticky;top:10px;padding-inline-start:18px;border-inline-start:1px solid var(--line)}
aside h3{font-size:14px;font-weight:600;margin:0 0 6px}
.bk{display:flex;gap:6px;font-size:14px;line-height:1.5;padding:5px 0;cursor:pointer}
.bk .t{flex:1}.bk .c{color:var(--acc);font-weight:600}
.summary{color:var(--mute);font-size:14px;margin-bottom:12px}
.card{background:var(--card);border:1px solid var(--line);border-inline-start:4px solid var(--gold);border-radius:6px;padding:12px 18px 14px;margin-bottom:12px}
.cite{font:700 21px/1.5 var(--text);color:var(--acc)}
.bid{color:var(--mute);font:400 13px var(--ui);margin-inline-start:8px}
.nw{white-space:nowrap}
.ct{cursor:pointer}.ct:hover{text-decoration:underline;text-underline-offset:5px}
.chips{display:flex;flex-wrap:wrap;gap:6px;margin:-8px 0 20px}
.chip{border:1px solid var(--line);border-radius:16px;padding:2px 12px;cursor:pointer;color:var(--ink);background:none;font:14px var(--ui)}
.chip.on{background:var(--gold);color:#1b1b12;border-color:var(--gold)}.chip i{font-style:normal;opacity:.7;margin-inline-start:5px}
.vol select.cat{margin-top:6px;width:100%;font-size:12px;padding:1px 4px;border:1px solid var(--line);border-radius:3px;background:var(--card);color:var(--ink)}
.vol select.cat.none{color:var(--mute);border-style:dashed}
.vol .newcat{display:flex;gap:4px;margin-top:6px}.vol .newcat input{flex:1;min-width:0;font-size:13px;padding:1px 6px;border:1px solid var(--line);border-radius:3px;background:var(--bg);color:var(--ink)}
.cover.img,.cover.img.ocr,.cover.img.wait{padding:0;background:#f4f1ea;border-inline-start:9px solid #1f7a55}.cover.img.ocr{border-inline-start-color:#a8691f}.cover.img.wait{border-inline-start-color:#7d8794}
.vol .vt{margin-top:7px;font:700 17px/1.4 var(--text);overflow-wrap:anywhere}
.cover.img img{width:100%;height:100%;object-fit:cover;object-position:top;display:block}
.fname{opacity:.55;font-weight:400}.nt{font:400 13px var(--ui);color:var(--ocr);white-space:nowrap}.nt .lnk{color:var(--ocr)}
.tag{display:inline-block;font-size:12px;border:1px solid var(--line);border-radius:3px;padding:0 7px;margin:2px 0 0 6px;color:var(--mute)}
.tag.foot{color:var(--foot);border-color:var(--foot)}.tag.ocr{color:var(--ocr);border-color:var(--ocr)}
.sn{margin:6px 0 10px;overflow-wrap:anywhere;font:22px/1.85 var(--text);max-width:44em}
mark{background:var(--mark);color:inherit;padding:0 2px;border-radius:2px}
.nl{display:block;height:0}
.acts{display:flex;gap:8px;flex-wrap:wrap;align-items:center}
.err{color:var(--err)}.muted{color:var(--mute)}
.wait{color:var(--mute);padding:34px 0;font-size:15px}
#pv{display:none;position:fixed;inset:0;background:#0b1422cc;padding:14px;overflow:auto;z-index:5;grid-column:auto}
#pv .box{background:var(--card);border-radius:4px;max-width:1500px;margin:auto;padding:10px 20px 20px}
#pv .top{display:flex;gap:8px;align-items:center;flex-wrap:wrap;border-bottom:1px solid var(--line);padding:6px 0 10px;position:sticky;top:-14px;background:var(--card);z-index:1}
#pv .top b{font:700 21px/1.4 var(--text);color:var(--rub);flex:1 1 100%;min-width:0}
#pv .two{display:grid;grid-template-columns:var(--cols,minmax(0,1fr));gap:18px;margin-top:12px;justify-content:center}
#pvtoc{font-size:13px;line-height:1.5;position:sticky;top:48px;align-self:start;max-height:calc(100vh / var(--z,1) - 60px);overflow:auto;padding-inline-end:10px;border-inline-end:1px solid var(--line)}
#pvtoc h3{font-size:13px;margin:0 0 6px;color:var(--acc)}
#pvtoc div{padding:3px 6px;cursor:pointer;border-radius:2px}#pvtoc div:hover{background:var(--acc2)}#pvtoc div.cur{background:var(--mark)}
#pv .txt{font:23px/2 var(--text);white-space:pre-wrap;overflow-wrap:anywhere}
#pv .foot{border-top:1px solid var(--line);margin-top:12px;padding-top:8px;font:19px/1.8 var(--text);color:var(--foot);white-space:pre-wrap}
#pv .foot b{font:600 13px var(--ui)}
#pv .head{font-size:14px;color:var(--mute)}
#pv img{width:100%;border:1px solid var(--line);display:block}
#pv .imgwrap{position:relative}
#pv .wbox{position:absolute;pointer-events:none;border-radius:2px}
#pv .wbox.dqb{border:1.5px solid #d9822b;background:#f5b04a22}
#pv .wbox.curb{border:2.5px solid #c0392b;background:#f1dc9a66}
#pv .wd{cursor:pointer;border-radius:2px}#pv .wd:hover{background:var(--acc2)}
#pv .wd.dq{text-decoration:underline wavy #d9822b;text-underline-offset:6px}
#pv .wd.on{background:var(--mark)}
#pvimgw{position:sticky;top:48px;align-self:start;max-height:calc(100vh / var(--z,1) - 60px);overflow:auto}
#pvayat h3{font:600 15px var(--ui);margin:18px 0 2px;padding-top:12px;border-top:1px solid var(--line)}
.ayb{padding:9px 0;border-bottom:1px solid var(--line)}
.ay{margin:4px 0}.aytxt{font:22px/1.9 var(--text)}.ay b{font-size:13px;color:var(--rub);white-space:nowrap}
.note{font-size:13px;color:var(--ocr);margin-top:6px}
.wrap{padding:26px 34px 34px;max-width:1240px}
.box2{background:var(--card);border:1px solid var(--line);border-radius:3px;padding:12px 18px;margin-bottom:16px}
.cols{display:grid;grid-template-columns:1fr 1fr;gap:16px}
table{border-collapse:collapse;width:100%;font-size:15px}
td,th{border-bottom:1px solid var(--line);padding:6px 8px;text-align:right;vertical-align:top}
th{color:var(--mute);font-weight:400;font-size:13px}
td.n{color:var(--acc);font-weight:600;white-space:nowrap}
.lnk{color:var(--acc);cursor:pointer;text-decoration:underline dotted}
pre{white-space:pre-wrap;font:inherit;margin:0}
.banner{padding:12px 34px;background:#fbf0cd;color:#4f3d05;border-bottom:1px solid #e3cd86;font-size:15px}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]) .banner{background:#3a3217;color:#f1dc9a;border-color:#6b5b22}}
:root[data-theme="dark"] .banner{background:#3a3217;color:#f1dc9a;border-color:#6b5b22}
.banner ol{margin:4px 0;padding-inline-start:22px}
.prog{height:8px;background:var(--line);overflow:hidden;margin:6px 0}.prog>i{display:block;height:100%;background:var(--gold);width:0}
#wlc{background:none;border:0;padding:0}
#wlc h2{font:700 42px/1.3 var(--text);margin:0}
#dz{border:1px solid var(--acc);outline:1px solid var(--acc);outline-offset:-7px;border-radius:2px;padding:48px 24px;text-align:center;background:var(--acc2);font:700 34px/1.4 var(--text);margin:16px 0}
#dz.over{background:var(--mark)}
#dz small{display:block;font:400 15px/1.7 var(--ui);color:var(--mute);margin-top:6px}
#dz .acts{font:16px var(--ui)}
.v{display:inline-block;border-radius:3px;padding:0 8px;font-size:14px;white-space:nowrap}
.v-ok{background:#c9ecd0;color:#123f1b}.v-warn{background:#f8e7a4;color:#4f3d05}.v-alt{background:#f9dcc9;color:#6c2d00}.v-bad{background:#f3c0ae;color:#6c1800}.v-gray{background:#e3e6ea;color:#333}
header .ver{display:flex;align-items:center;justify-content:space-between;gap:6px;padding:10px 22px 0;font-size:12px;color:#c9d6c9}
header .ver button{width:24px;height:24px;border-radius:50%;border:1.5px solid var(--gold);background:none;color:#fff;font:italic 700 14px Georgia,serif;cursor:pointer;padding:0}
#about{display:none;position:fixed;inset:0;background:#0a1a14cc;z-index:6;align-items:center;justify-content:center;padding:16px;grid-column:auto}
#about.on{display:flex}
#ren{display:none;position:fixed;inset:0;background:#0a1a14cc;z-index:7;align-items:center;justify-content:center;padding:16px;grid-column:auto}
#ren.on{display:flex}
#ren .abox{background:var(--card);border:1px solid var(--gold);border-radius:3px;padding:18px 22px;width:100%;max-width:520px}
#ren .fl{display:block;font-size:14px;color:var(--mute);margin-top:8px}
#ren .fl input{display:block;width:100%;box-sizing:border-box;margin-top:3px;font:19px var(--text);padding:5px 10px;border:1px solid var(--line);border-radius:3px;background:var(--bg);color:var(--ink)}
#about .abox{background:var(--card);border:1px solid var(--gold);border-radius:3px;padding:20px 24px;width:100%;max-width:440px}
#about .ahd{display:flex;align-items:center;gap:12px;margin-bottom:10px}
#about .t1{font:700 32px/1.2 var(--text)}#about .t2{font:700 24px/1.5 var(--text)}
#about .asec{padding:10px 0;border-top:1px solid var(--line);font-size:14px}
#cmenu{position:fixed;z-index:20;display:none;background:var(--card);border:1px solid var(--gold);border-radius:4px;box-shadow:0 4px 14px #0003;padding:4px 0;min-width:170px;grid-column:auto}
#cmenu button{display:block;width:100%;text-align:right;background:none;border:0;color:var(--ink);padding:7px 16px;font:15px var(--ui);cursor:pointer}
#cmenu button:hover{background:var(--acc2)}
#toast{position:fixed;bottom:18px;left:50%;transform:translateX(-50%);background:#0b3d2e;color:#fff;padding:5px 20px;border-radius:3px;display:none;z-index:9;font-size:15px;grid-column:auto}
/* رفّ الكتب: الغلافُ أخضر لما قُرئ من نصّ ملفّه، وبنّيّ لما قُرئ آليًّا فيقابَل بالصورة، ورماديّ لما لم يُقرأ */
.shelf{display:grid;grid-template-columns:repeat(auto-fill,176px);gap:26px 22px}
.vol{min-width:0}
.cover{height:224px;background:#0b3d2e;color:#f4efe0;padding:9px;position:relative;border-inline-start:9px solid #0003;border-radius:1px 3px 3px 1px;cursor:pointer;display:block;width:100%;border-block:0;border-inline-end:0;text-align:center;font:inherit}
.cover.ocr{background:#6b4418}.cover.wait{background:#7d8794}.cover.bad{background:#7a2b26}
.cover>span{display:flex;flex-direction:column;align-items:center;justify-content:center;gap:6px;height:100%;border:1px solid #c9a13fb0;outline:1px solid #c9a13f60;outline-offset:-5px;padding:12px 9px;overflow:hidden}
.cover b{font:700 23px/1.4 var(--text);display:-webkit-box;-webkit-line-clamp:5;-webkit-box-orient:vertical;overflow:hidden;overflow-wrap:anywhere}
.cover i{font:400 16px/1.3 var(--text);opacity:.85}
.vol .meta{font-size:13px;color:var(--mute);margin-top:7px;line-height:1.5;overflow-wrap:anywhere}
.vol .acts{margin-top:7px;font-size:13px;gap:10px}
.vol .prog{margin:5px 0 0}
.vol select.bt{margin-top:6px;width:100%;font-size:12px;padding:1px 4px;border:1px solid var(--line);border-radius:3px;background:var(--card)}
.oldnote{font-size:13px;color:var(--ocr);border:1px solid var(--ocr);border-radius:3px;padding:6px 10px;margin:8px 0}
.catch{font-size:13px;color:var(--mute);margin-top:10px;padding-top:6px;border-top:1px dashed var(--line)}
.dtop{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:12px}
.dtop select{font-size:15px;padding:3px 8px;border:1px solid var(--line);border-radius:3px;background:var(--card);max-width:320px}
.dmw{position:relative}.dmenu{display:none;position:absolute;top:100%;inset-inline-start:0;z-index:6;background:var(--card);border:1px solid var(--gold);border-radius:4px;padding:4px 0;min-width:150px;box-shadow:0 4px 14px #0003}
.dmenu.on{display:block}.dmenu button{display:block;width:100%;text-align:right;background:none;border:0;color:var(--ink);padding:6px 14px;font:15px var(--ui);cursor:pointer}.dmenu button:hover{background:var(--acc2)}
.dinl{display:flex;gap:8px;align-items:center;margin-bottom:12px}.dinl input{flex:1;max-width:420px;font:19px var(--text);padding:3px 10px;border:1px solid var(--line);border-radius:3px;background:var(--card)}
:root{--qt:#efe4c4;--qty:#fae3b8;--qtyl:#ba7517;--qtr:#f9d6d3;--qtrl:#a32d2d;--qta:#d8efe4}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--qt:#3a3420;--qty:#4a3a12;--qtyl:#e3b071;--qtr:#4d2220;--qtrl:#f2b8b5;--qta:#173a2e}}
:root[data-theme="dark"]{--qt:#3a3420;--qty:#4a3a12;--qtyl:#e3b071;--qtr:#4d2220;--qtrl:#f2b8b5;--qta:#173a2e}
.dpaper{background:var(--card);border:1px solid var(--line);border-radius:4px;padding:26px 38px 18px;max-width:56em;position:relative}
#ded{font:22px/2 var(--text);min-height:46vh;outline:none;white-space:pre-wrap;overflow-wrap:anywhere;text-align:justify}
#ded p{margin:0 0 6px}#ded h2{font:700 25px/1.6 var(--text);color:var(--acc);margin:14px 0 6px}
#dhint{position:absolute;top:30px;inset-inline:38px;font:19px/1.8 var(--text);pointer-events:none}
.qt{background:var(--qt);border-radius:3px;padding:0 3px;cursor:pointer;-webkit-box-decoration-break:clone;box-decoration-break:clone}
.qt.st-y{background:var(--qty);box-shadow:inset 0 -2px 0 var(--qtyl)}.qt.st-r{background:var(--qtr);box-shadow:inset 0 -2px 0 var(--qtrl)}.qt.aya{background:var(--qta)}
.qt.sel{outline:2px solid var(--gold)}
.qt sup{font:600 12px var(--ui);color:var(--acc);margin-inline-start:2px}
#dfn{border-top:1px solid var(--line);margin-top:18px;padding-top:6px;font:17px/1.7 var(--text);color:var(--mute)}#dfn:empty{display:none}
#dfn div{cursor:pointer}#dfn div:hover{color:var(--acc)}
.dleg{display:flex;gap:14px;flex-wrap:wrap;font-size:13px;color:var(--mute);margin-top:8px}.dleg i{display:inline-block;width:18px;height:12px;border-radius:2px;vertical-align:-1px;margin-inline-end:4px}
#dqt{display:none;position:fixed;z-index:8;background:var(--card);border:1px solid var(--gold);border-radius:4px;box-shadow:0 4px 14px #0003;padding:8px 12px;max-width:480px;font-size:14px;grid-column:auto}
#dqt .c{font:700 17px/1.5 var(--text);color:var(--acc)}#dqt .v{margin:2px 0 6px}#dqt .acts{margin-top:6px}
#dqe{display:none;position:fixed;inset:0;background:#0a1a14cc;z-index:7;align-items:center;justify-content:center;padding:16px;grid-column:auto}#dqe.on{display:flex}
#dqe .abox{background:var(--card);border:1px solid var(--gold);border-radius:3px;padding:18px 22px;width:100%;max-width:640px}
#dqe textarea{width:100%;box-sizing:border-box;font:21px/1.8 var(--text);margin:8px 0;padding:6px 10px;border:1px solid var(--line);border-radius:3px;background:var(--bg);color:var(--ink)}
#nvd i{font-style:normal;font-size:12px;background:var(--gold);color:#1b1b12;border-radius:9px;padding:0 6px;margin-inline-start:6px}
@media(max-width:860px){body{display:block}
 header{position:static;height:auto;padding:12px 0 6px}header h1{font-size:40px;margin:0 16px 8px}
 header nav{flex-direction:row;flex-wrap:wrap}header nav button{padding:4px 12px;border-inline-start:0;border-bottom:3px solid transparent}header nav button.on{border-bottom-color:var(--gold)}
 header .cov{padding:6px 16px}header .zm{padding:0 16px}
 .bar,.wrap{padding-inline:16px}main{grid-template-columns:1fr;padding-inline:16px}main>aside{order:0;position:static;max-height:34vh;border:0;padding:0}
 #pv .two{--cols:minmax(0,1fr)!important;grid-template-columns:minmax(0,1fr)}#pvtoc{display:none!important}.cols{grid-template-columns:1fr}.banner{padding-inline:16px}.shelf{grid-template-columns:repeat(auto-fill,140px)}.cover{height:190px}}
</style></head><body>
<header><div class="brand"><svg class="lg" viewBox="10 22 108 90" aria-hidden="true"><path d="M16 40 Q40 30 64 40 L64 102 Q40 92 16 102Z" fill="#f3ead3"/><path d="M112 40 Q88 30 64 40 L64 102 Q88 92 112 102Z" fill="#e8dcbc"/><path d="M24 54 Q40 49 56 54M24 64 Q40 59 56 64M24 74 Q40 69 56 74M24 84 Q40 79 56 84" stroke="#c9b98f" stroke-width="2.5" fill="none"/><circle cx="84" cy="68" r="22" fill="#fbf5e6" stroke="#d6a943" stroke-width="6"/><path d="M100 84 L112 96" stroke="#d6a943" stroke-width="9" stroke-linecap="round"/></svg><h1>بُغية</h1></div><div class="tagl">باحثٌ في مكتبتك</div>
<nav><button data-p="search" class="on">البحث</button><button data-p="books">كتبي</button><button data-p="welcome">أضف كتبًا</button><button data-p="draft" id="nvd">المسودة<i id="dcount" style="display:none"></i></button><button data-p="audit">مدقّق الإحالات</button><button data-p="jiwar">ألفاظٌ مجاورة</button><button data-p="groups">مجموعات الألفاظ</button><button data-p="status">حال المكتبة</button></nav>
<span class="cov" id="cov"></span><span class="zm"><button type="button" id="zdn" title="تصغير الخطّ">أ−</button><button type="button" id="zup" title="تكبير الخطّ">أ+</button><button type="button" id="thm" title="المظهر: تلقائيّ (كويندوز) ← نهاريّ ← ليليّ">تلقائي</button></span><script>(function(){var k="bughya-zoom",z=1.1;try{var v=parseFloat(localStorage.getItem(k));if(v)z=v}catch(e){}function set(v){z=Math.min(2.2,Math.max(0.8,Math.round(v*100)/100));document.documentElement.style.zoom=z;document.documentElement.style.setProperty('--z',z);try{localStorage.setItem(k,z)}catch(e){}}set(z);document.getElementById("zup").onclick=function(){set(z+0.1)};document.getElementById("zdn").onclick=function(){set(z-0.1)}})()</script><div class="ver"><span>الإصدار __VER__</span><button type="button" id="abt" aria-label="عن البرنامج" title="عن البرنامج">i</button></div></header>
<div id="about" role="dialog" aria-modal="true" aria-label="عن البرنامج"><div class="abox">
<div class="ahd"><img src="/icon.png" alt="" width="52" height="52"><div><div class="t1">بُغية</div><div class="muted">الإصدار __VER__</div></div></div>
<div class="asec"><span class="muted">تطوير</span><br><span class="t2" dir="ltr">Omar Elmnfi</span></div>
<div class="asec">«بُغية» قارئٌ لكتبك على جهازك: تبحث فيها وتنقل منها بعزوٍ كامل، وتتحقّق من إحالات ما تكتبه.</div>
<div class="asec"><button class="btn2" id="updchk">تحقّق من وجود تحديث</button> <span id="updres" class="muted"></span></div>
<div class="asec"><button class="btn2" id="unins">إزالة البرنامج من جهازك</button>
<div id="uninsq" style="display:none;margin-top:8px">تُزال «بُغية» من جهازك، وتبقى كتبُك المقروءة وإعداداتُك محفوظةً إن نصّبتها ثانية.<br>
<button class="btn" id="uninsy">نعم، أزِلها</button> <button class="btn2" id="uninsn">إلغاء</button></div></div>
<div class="asec muted">الأصل: مبنيٌّ على «هديّة وَتَد» من «وَتَد الوقفيّة للمساندة الأكاديميّة والتعليم».<br>خطُّ الاسم: الرقعة (Aref Ruqaa) برخصة SIL OFL.</div>
<div style="text-align:left;margin-top:8px"><button class="btn" id="abtx">إغلاق</button></div></div></div>
<div class="banner" id="updbar" style="display:none"></div>
<div class="banner" id="ocrbar" style="display:none"></div>
<div class="banner" id="progbar" style="display:none;background:var(--acc2);color:var(--ink);border-color:var(--line)"></div>

<!-- ═════ أضف كتبًا ═════ -->
<section class="panel" id="p-welcome"><div class="wrap">
<div class="box2" id="wlc"><h2 style="margin:0">أهلًا بك في «بُغية»</h2>
<div class="help" style="font-size:16px">«بُغية» قارئٌ لكتبك على جهازك: تبحث فيها وتنقل منها بعزوٍ كامل، وتتحقّق من إحالات ما تكتبه. لا إنترنتَ ولا حسابَ؛ وكتبُك لا تغادر جهازك.</div></div>
<div id="dz">اسحب كتبَك أو مجلّدَ كتبك إلى هنا<small>بي دي إف (نصّيٌّ أو مصوَّر) · وورد · نصوص · صفحات ويب · كتب إلكترونيّة (epub) · صور</small>
<div class="acts" style="justify-content:center;margin-top:14px"><button class="btn" id="pickdir">اختر مجلّدًا من جهازك</button><button class="btn2" id="pickfiles">أو اختر ملفّات</button></div>
<input type="file" id="fileinp" multiple style="display:none"></div>
<div class="box2"><b>ما الفرق؟</b><div class="help">«اختر مجلّدًا» تقرأ بُغية الكتبَ من مكانها دون نسخ. والسحبُ يحفظ نسخةً من الكتب في مجلّد بيانات بُغية.</div><div id="upinfo" class="muted"></div><div id="srclist" class="muted"></div></div>
</div></section>

<!-- ═════ مدقّق الإحالات ═════ -->
<section class="panel" id="p-audit"><div class="wrap">
<div class="box2"><b>مدقّقُ الإحالات</b><div class="help">اسحب ملفًّا ممّا كتبتَ، بحثًا أو فصلًا أو مقالًا (ملفَّ وورد .docx) فيستخرج كلَّ نقلٍ بحاشيته، ويبحث عنه في كتبك المقروءة، ويحكم عليه. لا يكتب في ملفّك شيئًا.</div></div>
<div id="adz" style="border:3px dashed var(--acc);border-radius:16px;padding:26px;text-align:center;background:var(--acc2);font-size:19px;margin-bottom:12px">اسحب ملفَّ وورد هنا<small style="display:block;font-size:14px;color:var(--mute)">أو <span class="lnk" id="apick">اختره من جهازك</span></small><input type="file" id="ainp" accept=".docx" style="display:none"></div>
<div id="aprog"></div><div id="ares"></div>
<div class="box2"><b>كتاباتي (لا تُعدّ مصدرًا)</b><div class="help">إن كانت في مكتبتك كتاباتُك أنت (بحوثُك أو فصولُك) فعلّمها هنا، حتى لا يجد المدقّقُ نقلًا في كلامك أنت فيحسبه موجودًا في مصدره.</div>
<div class="acts"><button class="btn2" id="exopen">عدّل القائمة</button></div><div id="exbox" style="display:none"><input type="text" id="exf" placeholder="صفِّ بالعنوان…" style="width:100%;padding:4px 10px;border:1px solid var(--line);border-radius:6px;background:var(--bg);margin:6px 0"><div id="exlist" style="max-height:300px;overflow:auto"></div><div class="acts"><button class="btn" id="exsave">احفظ</button></div></div></div>
</div></section>

<!-- ═════ البحث ═════ -->
<section class="panel on" id="p-search">
<div class="bar"><form id="sf" class="row"><input type="text" id="q" placeholder="ابحث في كتبك" autofocus><button class="btn">ابحث</button></form>
<details class="more"><summary>خيارات البحث</summary><div class="opts">
<label>نوع البحث <select id="mode"><option value="phrase">عبارةٌ متتالية</option><option value="words">كلماتٌ مجتمعة في الصفحة</option><option value="any">أيُّ كلمةٍ منها</option><option value="near">كلمتان متقاربتان</option><option value="query">صيغةُ المتمرّس</option></select></label>
<label id="distw" style="display:none">بينهما <input type="number" id="dist" value="10" min="1" max="60" style="width:52px"> كلمة فأقلّ</label>
<label>في صنف <select id="fann"><option value="">كلّ الأصناف</option></select></label>
<label>في <select id="layer"><option value="all">المتن والحاشية</option><option value="body">المتن وحده</option><option value="foot">الحاشية وحدها</option></select></label>
<label title="لا يبحث عن: والصلاة، بالصلاة، للصلاة…"><input type="checkbox" id="exact"> بلا سوابق</label>
<label title="يجد الكلمة وإن أخطأت القراءةُ الآليّة في نقاطها"><input type="checkbox" id="rasm"> تسامحٌ مع أخطاء النقاط</label>
<label>الترتيب <select id="order"><option value="rank">الأقرب صلة</option><option value="book">بالكتاب والصفحة</option></select></label>
</div>
<div class="help" id="mhelp"></div></details></div>
<main><aside id="facet"><h3>الكتب</h3><div class="muted" style="font-size:14px">تظهر هنا الكتبُ التي ورد فيها ما تبحث عنه، فتحصر البحثَ فيما تختار منها.</div></aside>
<section id="results"><div class="wait">اكتب ما تبحث عنه ثمّ «ابحث».<br><span style="font-size:14px">البحثُ بالكلمة وسوابقها (و، ف، ب، ك، ل، ال) لا بالجذر؛ والنجمةُ في صيغة المتمرّس بادئة: <b>صلا*</b></span></div></section></main>
</section>

<!-- ═════ المسوّدة ═════ -->
<section class="panel" id="p-draft"><div class="wrap">
<div class="dtop"><select id="dsel" aria-label="المسودة"></select><span class="dmw"><button class="btn2" id="dmore" aria-label="خيارات المسودة" title="مسودة جديدة · أعد التسمية · احذف">⋯</button><div id="dmenu" class="dmenu"><button type="button" id="dnew">مسودة جديدة</button><button type="button" id="dren">أعد التسمية</button><button type="button" id="ddel">احذف المسودة</button></div></span>
<button class="btn2" id="dfh" title="اجعل الفقرة التي فيها المؤشّر عنوانًا">عنوان</button><button class="btn2" id="dfp" title="اجعلها نصًّا عاديًّا">نصّ</button>
<span style="flex:1"></span><button class="btn" id="ddocx">وورد</button><button class="btn2" id="dpdf">PDF</button><button class="btn2" id="dprint">طباعة</button></div>
<div class="dinl" id="dnamebox" style="display:none"><input type="text" id="dnamei" placeholder="اسمُ المسودة، مثل: المبحث الأول"><button class="btn" id="dnameok">احفظ</button><button class="btn2" id="dnamex">إلغاء</button></div>
<div class="banner" id="ddelq" style="display:none;margin-bottom:12px"></div>
<div class="banner" id="dundo" style="display:none;margin-bottom:12px"></div>
<div class="dpaper"><div id="dhint" class="muted" style="display:none">اكتب هنا كلامك كما تكتب في وورد. ولتضع نقلًا: اجعل المؤشّر حيث تريده، ثمّ اضغط «+ أضف إلى المسودة» تحت نتيجةٍ في البحث، أو بعد تحديد نصٍّ في عارض الصفحة؛ فيدخل النقلُ في موضع المؤشّر، وعزوُه في الحواشي.</div>
<div id="ded" contenteditable="true" spellcheck="false" role="textbox" aria-multiline="true" aria-label="نصّ المسودة"></div>
<div id="dfn"></div></div>
<div class="dleg"><span><i style="background:var(--qt)"></i>نقلٌ مطابقٌ لصفحته</span><span><i style="background:var(--qty);box-shadow:inset 0 -2px 0 var(--qtyl)"></i>لم يُقابَل بالصورة</span><span><i style="background:var(--qtr);box-shadow:inset 0 -2px 0 var(--qtrl)"></i>لا يطابق نصَّ الصفحة</span><span><i style="background:var(--qta)"></i>آية</span><span>· اضغط النقلَ لترى عزوه وتعدّله أو تحذفه</span></div>
</div></section>
<div id="dqt" role="dialog" aria-label="النقل"></div>
<div id="dqe" role="dialog" aria-modal="true" aria-label="تعديل النقل"><div class="abox"><b style="font:700 21px var(--text)">تعديلُ النقل</b>
<div class="help">قصِّر النقلَ أو صحّحه من صورة الصفحة؛ ثمّ يُقابَل بالصفحة من جديد ويظهر حكمُه.</div>
<textarea id="dqet" rows="7"></textarea><div class="acts"><button class="btn" id="dqeok">احفظ</button><button class="btn2" id="dqex">إلغاء</button></div></div></div>
<iframe id="dpf" title="طباعة المسودة" style="position:absolute;width:0;height:0;border:0;left:-9999px"></iframe>

<!-- ═════ ألفاظٌ مجاورة ═════ -->
<section class="panel" id="p-jiwar"><div class="wrap">
<div class="box2"><form id="jf" class="row"><input type="text" id="jq" placeholder="لفظٌ تعرفه، مثل: خبر الآحاد" style="flex:1;font-size:19px;padding:6px 12px;border:1px solid var(--line);border-radius:8px;background:var(--bg)"><button class="btn">ابحث</button></form>
<div class="help">تعرض أكثرَ الكلمات التي تسبق اللفظَ وتليه في كتبك، فيظهر المصطلحُ المركّب والعباراتُ التي يُعبَّر بها عن المسألة. اضغط عبارةً لتبحث بها، أو «+» لتضيفها إلى مجموعة.</div></div>
<div id="jres"></div></div></section>

<!-- ═════ مجموعاتي ═════ -->
<section class="panel" id="p-groups"><div class="wrap">
<div class="box2"><b>مجموعاتُ الألفاظ</b><div class="help">اجمع الألفاظ التي يُعبَّر بها عن مسألةٍ واحدة (مثل: خبر الآحاد · خبر الواحد · أخبار الآحاد)، ثمّ ابحث بها كلّها دفعةً واحدة، كلُّ لفظٍ مع سوابقه. وتُحفظ على جهازك في ملفّ «مجموعات-الألفاظ.json».</div></div>
<div class="box2"><div class="row"><input type="text" id="gname" placeholder="اسمُ المجموعة" style="flex:1;padding:4px 10px;border:1px solid var(--line);border-radius:6px;background:var(--bg)"></div>
<textarea id="gterms" rows="4" placeholder="لفظٌ في كلّ سطر" style="width:100%;margin-top:6px;padding:4px 10px;border:1px solid var(--line);border-radius:6px;background:var(--bg)"></textarea>
<div class="acts"><button class="btn" id="gsave">احفظ المجموعة</button><button class="btn2" id="gmeasure">كم مرّةً ورد كلُّ لفظ؟</button><button class="btn2" id="gclear">مجموعةٌ جديدة</button></div>
<div id="gm"></div></div>
<div id="glist"></div></div></section>

<!-- ═════ الكتب ═════ -->
<section class="panel" id="p-books"><div class="wrap">
<div class="row" style="margin-bottom:20px;align-items:center"><input type="text" id="bf" placeholder="صفِّ بالعنوان أو المؤلّف" style="flex:1;max-width:420px;padding:5px 12px;border:1px solid var(--line);border-radius:3px;background:var(--card)"><span class="muted" id="bcount"></span></div>
<div class="chips" id="bchips"></div>
<div class="shelf" id="btab"></div></div></section>

<!-- ═════ حالُ المكتبة ═════ -->
<section class="panel" id="p-status"><div class="wrap">
<div class="box2"><pre id="stext">…</pre></div>
<div class="box2"><button class="btn" id="upd">حدّث المكتبة</button> <button class="btn2" id="stopb">أوقف القراءة</button>
<div class="help">يقرأ ما جدّ من الكتب في مجلّداتك، ويُكمل ما لم تكتمل قراءتُه، في الخلفيّة. والبحثُ يعمل فيما قُرئ ريثما تكتمل. والكتبُ المصوَّرة تأخذ وقتًا.</div>
<pre id="utext" class="muted"></pre></div></div></section>

<!-- ═════ عارضُ الصفحة ═════ -->
<div id="pv"><div class="box"><div class="top"><b id="pvcite"></b>
<span id="pvmeth" class="tag"></span>
<button class="btn2" id="pvprev">‹ السابقة</button><input type="number" id="pvgo" min="1" style="width:70px;font-size:15px;padding:0 6px;border:1px solid var(--line);border-radius:6px;background:var(--bg)" title="رقمُ الصفحة ثمّ Enter"><span class="muted" id="pvtot"></span><button class="btn2" id="pvnext">التالية ›</button>
<button class="btn2" id="pvimg">صورةُ الصفحة</button><button class="btn2" id="pvcopy">انسخ المحدَّد مع عزوه</button><button class="btn2" id="pvadd">+ أضف المحدَّد إلى المسودة</button><button class="btn2" id="pvsearch">ابحث في هذا الكتاب</button>
<button class="btn2" id="pvflow" title="العرضُ وحده يتغيّر، لا نصُّ الكتاب"></button><button class="btn2" id="pvcover">اجعلها غلاف الكتاب</button><button class="btn2" id="pvren">بيانات الكتاب</button><button class="btn2" id="pvclose">إغلاق ✕</button></div>
<div class="two one" id="pvtwo"><aside id="pvtoc" style="display:none"></aside><div><div class="head" id="pvhead"></div><div class="note" id="pvnote"></div><div class="txt" id="pvbody"></div><div class="foot" id="pvfoot"></div><div id="pvayat"></div></div>
<div id="pvimgw" style="display:none"></div></div></div></div>
<div id="ren" role="dialog" aria-modal="true" aria-label="بيانات الكتاب"><div class="abox">
<b style="font:700 22px var(--text)">بياناتُ الكتاب</b> <span class="muted" id="renid"></span>
<div class="help">اكتبها من صفحة عنوان الكتاب. وتظهر في النتائج والعزو بدل اسم الملفّ، ولا يتغيّر الملفّ نفسه.</div>
<div class="acts" style="margin:4px 0 8px"><button class="btn2" id="renimg">افتح الكتاب لترى صفحة عنوانه</button></div>
<label class="fl">العنوان<input type="text" id="rent"></label>
<label class="fl">المؤلّف <span class="muted">(اختياريّ)</span><input type="text" id="rena"></label>
<label class="fl">سنةُ الوفاة <span class="muted">(اختياريّ)</span><input type="text" id="rend" placeholder="مثل: ٧٢٨ هـ"></label>
<div class="acts" style="justify-content:flex-start;margin-top:10px"><button class="btn" id="rensave">احفظ</button><button class="btn2" id="renx">إلغاء</button></div></div></div>
<div id="toast"></div><div id="cmenu" role="menu"></div>

<script>
const $=s=>document.querySelector(s), AR=n=>String(n).replace(/\d/g,d=>'٠١٢٣٤٥٦٧٨٩'[d]);
const esc=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
function toast(t){const e=$('#toast');e.textContent=t;e.style.display='block';clearTimeout(e._t);e._t=setTimeout(()=>e.style.display='none',1600)}
async function api(path,params,post){
  const url=path+(params?'?'+new URLSearchParams(params):'');
  const r=await fetch(url,post?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(post)}:{});
  return r.json();
}
async function copy(t){try{await navigator.clipboard.writeText(t)}catch(e){const a=document.createElement('textarea');a.value=t;document.body.appendChild(a);a.select();document.execCommand('copy');a.remove()}toast('نُسخ ✓')}
setInterval(()=>fetch('/api/ping').catch(()=>{}),20000);

// ── التبويبات
document.querySelectorAll('header nav button').forEach(b=>b.onclick=()=>show(b.dataset.p));
function show(p){
  document.querySelectorAll('header nav button').forEach(x=>x.classList.toggle('on',x.dataset.p==p));
  document.querySelectorAll('.panel').forEach(x=>x.classList.toggle('on',x.id=='p-'+p));
  if(p=='books')loadBooks(); if(p=='status')loadStatus(); if(p=='groups')loadGroups(); if(p=='welcome')loadSources(); if(p=='draft')loadDrafts();
}

// ── البحث
const HELP={phrase:'العبارةُ كما تكتبها، كلماتُها متتالية، ومع سوابق أوّل كلمة (والصلاة، بالصلاة…).',
 words:'كلُّ الكلمات في صفحةٍ واحدة بأيّ ترتيب، ومع سوابقها.',any:'أيُّ كلمةٍ منها، ومع سوابقها.',
 near:'كلمتان (أو أكثر) بينهما عددُ الكلمات الذي تحدّده فأقلّ، بلا سوابق.',
 query:'للمتمرّس: AND و OR و NOT و NEAR، والنجمةُ بادئة (صلا*)، والعبارةُ بين علامتي تنصيص. مثل: "خبر الواحد" AND العقيده',
 group:'مجموعةُ ألفاظ: كلُّ لفظٍ مع سوابقه، وأيُّها ورد.'};
const S={q:'',mode:'phrase',books:new Set(),offset:0,facet:[],total:0,params:null,results:[]};
$('#mode').onchange=()=>{$('#distw').style.display=$('#mode').value=='near'?'':'none';$('#mhelp').textContent=HELP[$('#mode').value]};
$('#mhelp').textContent=HELP.phrase;
$('#sf').onsubmit=e=>{e.preventDefault();S.books.clear();newSearch($('#q').value,$('#mode').value)};
['layer','exact','rasm','order','fann'].forEach(id=>$('#'+id).onchange=()=>{if(S.q)newSearch(S.q,S.mode,true)});
function newSearch(q,mode,keepBooks){
  q=q.trim(); if(!q)return; S.q=q;S.mode=mode;S.offset=0;S.results=[]; if(!keepBooks)S.books.clear();
  S.params={q,mode,dist:$('#dist').value,layer:$('#layer').value,exact:$('#exact').checked?1:0,rasm:$('#rasm').checked?1:0,order:$('#order').value,fann:$('#fann').value};
  run(true);
}
let GEN=0;
async function run(withFacet){
  const res=$('#results'),g=++GEN;
  if(S.offset==0)res.innerHTML='<div class="wait">يبحث…</div>';
  if(withFacet)loadFacet(g);   // قائمةُ الكتب تُحصى وحدها، والنتائجُ لا تنتظرها
  const p=Object.assign({},S.params,{offset:S.offset,limit:30,books:[...S.books].join(',')});
  const r=await api('/api/search',p);
  if(g!=GEN)return;            // بحثٌ أحدثُ منه بدأ
  if(r.error){res.innerHTML='<div class="wait err">'+esc(r.error)+'</div>';return}
  if(r.coverage)setCov(r.coverage);
  S.total=r.pages;S.bookN=r.books;S.results=S.results.concat(r.results);
  drawResults();
}
let FGEN=0;
async function loadFacet(g){
  const fg=++FGEN;
  $('#facet').innerHTML='<h3>الكتب</h3><div class="muted" style="font-size:14px">تُحصى الكتبُ التي ورد فيها…</div>';
  const r=await api('/api/search',Object.assign({},S.params,{facet:'only'}));
  if(fg!=FGEN)return;
  if(r.error){$('#facet').innerHTML='<h3>الكتب</h3><div class="muted err" style="font-size:14px">'+esc(r.error)+'</div>';return}
  S.facet=r.facet||[];drawFacet();
}
function drawFacet(){
  const f=$('#facet');
  if(!S.facet.length){f.innerHTML='<h3>الكتب</h3><div class="muted">—</div>';return}
  f.innerHTML='<h3>الكتب التي ورد فيها ('+AR(S.facet.length)+')</h3><div class="acts" style="margin-bottom:4px"><button class="btn2" id="fall">كلُّها</button></div>'+
   S.facet.map(b=>'<label class="bk"><input type="checkbox" data-b="'+b.book_id+'" '+(S.books.has(b.book_id)?'checked':'')+'> <span class="t">'+
   (b.unclear?'<span class="fname">'+esc(b.title)+'</span>':esc(b.title))+(b.volume?' ج'+AR(b.volume):'')+
   (b.unclear?'<br>'+noTitle(b.book_id):'')+
   (b.author?'<br><span class="muted" style="font-size:12px">'+esc(b.author)+(b.death?' (ت '+esc(b.death)+')':'')+'</span>':'')+
   '</span><span class="c" title="مواضع">'+AR(b.occurrences||b.pages)+'</span></label>').join('');
  f.querySelectorAll('input[data-b]').forEach(c=>c.onchange=()=>{const id=+c.dataset.b;c.checked?S.books.add(id):S.books.delete(id);S.offset=0;S.results=[];run(false)});
  $('#fall').onclick=()=>{S.books.clear();drawFacet();S.offset=0;S.results=[];run(false)};
}
function snipHTML(s){return esc(s).replace(/【/g,'<mark>').replace(/】/g,'</mark>').replace(/ ⏎ /g,'<span class="nl"> ⏎ </span>')}
function plain(s){return s.replace(/[【】]/g,'').replace(/ ⏎ /g,' ').replace(/^… | …$/g,'')}
function citeFull(x){return x.cite+' · رقم الكتاب '+AR(x.book_id)}
// العنوانُ يلتفّ إن طال، وما بعده (الجزء والصفحة) لا ينكسر بين سطرين
// كتابٌ اسمُه اسمُ ملفٍّ لا يدلّ عليه: يظهر الاسمُ باهتًا، وبعده ما يُفعل
function noTitle(id){return '<span class="nt">بلا عنوان — <span class="lnk" data-ren="'+id+'">اكتب عنوانه</span></span>'}
function citeHTML(c,unclear){const m=String(c||'').match(/^(«[^»]*»)\s*(.*)$/);
  return m?(unclear?'<span class="fname">'+esc(m[1])+'</span>':esc(m[1]))+(m[2]?' <span class="nw">'+esc(m[2]).replace(/ \(/g,'</span> <span class="nw">(')+'</span>':''):esc(c)}
function drawResults(){
  const res=$('#results');
  if(!S.results.length){res.innerHTML='<div class="wait">لم أجده في كتبك المقروءة'+covNote()+'.<br><span style="font-size:14px">جرّب «تسامحٌ مع أخطاء النقاط»، أو صيغةً أخرى للكلمة، أو «ألفاظٌ مجاورة».</span></div>';return}
  const lim=(S.books.size?' (في الكتب المختارة)':'')+(S.params&&S.params.fann?' (في صنف «'+esc(S.params.fann)+'»)':'');
  let h='<div class="summary">وُجد في '+AR(S.total)+' صفحة من '+AR(S.bookN)+' كتابًا'+lim+' · المعروض '+AR(S.results.length)+covNote()+'</div>';
  S.results.forEach((x,i)=>{
    h+='<div class="card"><div class="cite"><span class="ct" data-open="'+i+'" title="افتح الصفحة">'+citeHTML(x.cite,x.unclear)+'</span> <span class="bid nw">رقم الكتاب '+AR(x.book_id)+'</span>'+
      (x.unclear?' '+noTitle(x.book_id):'')+'</div>'+
      '<span class="tag '+(x.layer=='حاشية'?'foot':'')+'">'+esc(x.layer)+''+'</span>'+
      (x.method=='ocr'?'<span class="tag ocr">قراءةٌ آليّة · قابِل بالصورة قبل النقل</span>':'')+
      (x.via_ayat?'<span class="tag">لم يُقرأ لفظها سليمًا في الكتاب، وعُرفت بمطابقة الآية: '+esc(x.via_ayat.join('، '))+'</span>':'')+
      x.snippets.map(s=>'<p class="sn">'+snipHTML(s)+'</p>').join('')+
      '<div class="acts"><button class="btn2" data-open="'+i+'">افتح الصفحة'+(x.method=='ocr'?' والصورة':'')+'</button><button class="btn2" data-copy="'+i+'">انسخ المقطع مع عزوه</button><button class="btn2" data-dadd="'+i+'">+ أضف إلى المسودة</button></div></div>';
  });
  if(S.results.length<S.total)h+='<div style="text-align:center"><button class="btn" id="more">المزيد ('+AR(S.total-S.results.length)+' باقية)</button></div>';
  res.innerHTML=h;
  res.querySelectorAll('[data-open]').forEach(b=>b.onclick=()=>{const x=S.results[+b.dataset.open];openPage(x.book_id,x.n,x.method=='ocr')});
  res.querySelectorAll('[data-copy]').forEach(b=>b.onclick=()=>{const x=S.results[+b.dataset.copy];
    copy('«'+plain(x.snippets[0])+'» — '+citeFull(x)+(x.method=='ocr'?' (قراءةٌ آليّة لم تُقابَل بالصورة)':''))});
  res.querySelectorAll('[data-dadd]').forEach(b=>b.onclick=()=>{const x=S.results[+b.dataset.dadd];
    addToDraft({kind:'quote',text:plain(x.snippets[0]).replace(/\s+/g,' ').trim(),b:x.book_id,n:x.n,cite:x.cite,vol:x.vol,printed:x.printed,unit:x.unit,layer:x.layer,method:x.method})});
  if($('#more'))$('#more').onclick=()=>{S.offset=S.results.length;run(false)};
}
let COV=null;
function setCov(c){COV=c;$('#cov').textContent='قُرئ '+AR(c.done)+' من '+AR(c.books)+' كتابًا · '+AR(c.pages)+' صفحة'+(c.pending||c.reading?' · '+AR(c.pending+c.reading)+' لم تكتمل':'')}
function covNote(){return COV&&(COV.pending||COV.reading)?' — والبحثُ فيما قُرئ: '+AR(COV.done)+' كتابًا من '+AR(COV.books)+'، وما لم يُقرأ لم يُبحث فيه':''}

// ── عارضُ الصفحة
const PV={b:0,n:0,data:null};
async function openPage(b,n,img){
  PV.b=b;PV.n=n;$('#pv').style.display='block';$('#pvbody').textContent='…';$('#pvfoot').textContent='';$('#pvhead').textContent='';$('#pvnote').textContent='';
  $('#pvimgw').style.display='none';$('#pvtwo').classList.add('one');
  const r=await api('/api/page',{b,n});
  if(r.error||!r.length){$('#pvbody').innerHTML='<span class="err">'+esc(r.error||'لا صفحة بهذا الرقم.')+'</span>';PV.data=null;return}
  const p=r[0];PV.data=p;
  $('#pvcite').innerHTML=citeHTML(p.cite)+' <span class="nw">· رقم الكتاب '+AR(p.book_id)+'</span>';
  const m=$('#pvmeth');m.textContent=p.method=='ocr'?'قراءةٌ آليّة':'نصُّ الملفّ';m.className='tag'+(p.method=='ocr'?' ocr':'');
  $('#pvgo').value=p.n;
  if(!BOOKS||BOOKS.error)try{BOOKS=await api('/api/books')}catch(e){}
  const bk=Array.isArray(BOOKS)&&BOOKS.find(x=>x.id==p.book_id);PV.total=bk?bk.pages:0;
  $('#pvtot').textContent=PV.total?'من '+AR(PV.total):'';
  $('#pvgo').max=PV.total||'';
  $('#pvhead').textContent=p.head||'';
  $('#pvbody').innerHTML=hl(flowText(p.body||'—'));
  $('#pvfoot').innerHTML=p.foot?'<b>الحاشية:</b>\n'+hl(flowText(p.foot)):'';
  $('#pvnote').textContent=p.method=='ocr'?'قُرئت هذه الصفحة قراءةً آليّة، وفيها أخطاء؛ فالصورةُ تحسم قبل أيّ نقل.':'';
  if(!BOOKS||BOOKS.error)try{BOOKS=await api('/api/books')}catch(e){}
  const bb=Array.isArray(BOOKS)&&BOOKS.find(x=>x.id==p.book_id);
  if(bb&&OLD.includes(bb.btype)&&p.method=='ocr')$('#pvnote').innerHTML='<div class="oldnote">هذا الكتاب '+BT[bb.btype]+'، والقراءة الآلية فيه ضعيفة جدًّا: اعتمد على صورة الصفحة، ولا تنقل من النص المستخرج.</div>';
  drawCatch(p);
  if(p.method=='ocr')drawWords(p);
  $('#pvimg').disabled=p.unit!='صفحة';$('#pvcover').disabled=p.unit!='صفحة';
  await loadPvToc(p);pvGrid();
  if(img)showImg();
  drawAyat(p);
}
function pvGrid(){
  const toc=PV.toc&&PV.toc.length,img=$('#pvimgw').style.display!='none';
  $('#pvtoc').style.display=toc?'block':'none';
  $('#pvtwo').style.setProperty('--cols',(toc?'170px ':'')+(img?'minmax(0,1fr) minmax(0,1fr)':'minmax(0,46em)'));
}
async function loadPvToc(p){
  if(PV.tocb!=p.book_id){PV.tocb=p.book_id;const r=await api('/api/toc',{b:p.book_id});PV.toc=Array.isArray(r)?r:[];
    $('#pvtoc').innerHTML='<h3>الفهرس</h3>'+PV.toc.map(t=>'<div data-tn="'+t.n+'" style="padding-inline-start:'+(6+(Math.max(1,t.level||1)-1)*10)+'px">'+esc(t.title)+'</div>').join('');
    $('#pvtoc').querySelectorAll('[data-tn]').forEach(d=>d.onclick=()=>openPage(PV.b,+d.dataset.tn,$('#pvimgw').style.display=='block'))}
  let cur=null;$('#pvtoc').querySelectorAll('[data-tn]').forEach(d=>{d.classList.remove('cur');if(+d.dataset.tn<=p.n)cur=d});
  if(cur){cur.classList.add('cur');cur.scrollIntoView({block:'nearest'})}
}
let PVW=null;
async function drawWords(p){
  PVW=null;const r=await api('/api/words',{b:p.book_id,n:p.n});
  if(PV.n!=p.n||PV.b!=p.book_id)return;
  if(!r.words){if(r.old){const n=document.createElement('div');n.className='note';n.textContent='قُرئ هذا الكتاب بإصدارٍ أقدم من «بُغية»، فلا تظهر فيه مواضعُ الكلمات في الصورة ولا تعليمُ المشكوك فيها. أعد قراءتَه لتظهر.';const bt=document.createElement('button');bt.className='btn2';bt.textContent='أعد قراءة هذا الكتاب';bt.onclick=async()=>{const x=await api('/api/reread-book',null,{b:p.book_id});toast(x.error||'بدأت إعادةُ القراءة');pollProgress()};n.appendChild(document.createTextNode(' '));n.appendChild(bt);$('#pvnote').appendChild(n);}return;}
  PVW=r;let doubts=0;
  const render=lines=>{const sp=lineSeps(lines.map(l=>l.map(w=>w.t).join(' ')));
    return lines.map((l,i)=>l.map(w=>{if(w.d)doubts++;
    return '<span class="wd'+(w.d?' dq" title="'+(w.c?'في قاموس كتبك، لكنّها لم ترد فيها بجوار ما حولها، وورد مكانَها ما يخالفها في النقط؛ فقد تكون خطأً في القراءة الآلية: قابلها بالصورة':'ليست في قاموس كتبك، فقد تكون خطأً في القراءة الآلية: قابلها بالصورة'):'')+'"'+(w.b?' data-b="'+w.b.join(',')+'"':'')+'>'+esc(w.t)+'</span>'}).join(' ')+(i<lines.length-1?sp[i]:'')).join('')};
  $('#pvbody').innerHTML=render(r.body||[]);
  if(r.foot&&r.foot.length&&p.foot)$('#pvfoot').innerHTML='<b>الحاشية:</b>\n'+render(r.foot);
  document.querySelectorAll('#pv .wd[data-b]').forEach(s=>s.onclick=()=>showWord(s));
  const n=document.createElement('div');n.className='note';
  n.textContent=!r.lexicon?'اضغط أي كلمة لترى موضعها في الصورة. (تعليم الكلمات المشكوك فيها يحتاج كتبًا نصيّة أكثر في مكتبتك.)'
    :doubts?('اضغط أي كلمة لترى موضعها في الصورة. و'+AR(doubts)+' كلمةً تحتها خطٌّ متموّجٌ برتقاليّ، وتُؤطَّر في الصورة: ليست في قاموس كتبك، أو هي فيه لكنّها غريبةٌ بين جارتيها؛ فقد تكون خطأً في القراءة الآلية، فقابلها بالصورة قبل نقلها. وما لا خطَّ تحته قد يكون خاطئًا أيضًا.')
    :'اضغط أي كلمة لترى موضعها في الصورة. ولم تُعلَّم كلمةٌ في هذه الصفحة: كلُّها في قاموس كتبك وليس فيها ما يُستغرب موضعُه، وهذا لا يعني أنّها كلَّها صواب.';
  $('#pvnote').appendChild(n);
  drawImgBoxes();
}
async function showWord(s){
  document.querySelectorAll('#pv .wd.on').forEach(x=>x.classList.remove('on'));s.classList.add('on');
  if($('#pvimgw').style.display!='block'||!$('#pvimgw img'))await showImg();
  drawImgBoxes(s.dataset.b);
}
function drawImgBoxes(cur){
  const wrap=$('#pvimgw .imgwrap');if(!wrap)return;
  wrap.querySelectorAll('.wbox').forEach(x=>x.remove());
  const add=(b,cls)=>{const [x,y,w,h]=b.split(',').map(Number);const d=document.createElement('div');d.className='wbox '+cls;
    d.style.left=(x*100-0.4)+'%';d.style.top=(y*100-0.4)+'%';d.style.width=(w*100+0.8)+'%';d.style.height=(h*100+0.8)+'%';wrap.appendChild(d);return d};
  document.querySelectorAll('#pv .wd.dq[data-b]').forEach(s=>add(s.dataset.b,'dqb'));
  if(cur){const d=add(cur,'curb');d.scrollIntoView({block:'center',behavior:'smooth'})}
}
async function drawCatch(p){
  const old=$('#pvcatch');if(old)old.remove();
  if(!p.catch)return;
  const d=document.createElement('div');d.id='pvcatch';d.className='catch';d.textContent='التعقيبة: '+p.catch;$('#pvfoot').after(d);
  const r=await api('/api/page',{b:p.book_id,n:p.n+1});
  if(PV.n!=p.n||!Array.isArray(r)||!r.length)return;
  const strip=t=>(t||'').replace(/[\u064B-\u0652\u0670\u0640]/g,'').replace(/[أإآٱ]/g,'ا').replace(/ى/g,'ي').replace(/ة/g,'ه').trim();
  const first=strip((r[0].body||'').split(/\s+/).slice(0,2).join(' ')),c=strip(p.catch);
  d.textContent+=first.startsWith(c.split(' ')[0])?' — توافق أول الصفحة التالية':' — لا توافق أول الصفحة التالية («'+(r[0].body||'').split(/\s+/).slice(0,2).join(' ')+'»): قد يكون ترتيب الصفحات مختلًّا، أو أخطأت القراءة';
}
async function drawAyat(p){
  const w=$('#pvayat');w.innerHTML='';
  const r=await api('/api/ayat',{b:p.book_id,n:p.n});
  if(PV.n!=p.n||PV.b!=p.book_id||r.error||!r.length)return;
  const line=x=>x.verses.map(v=>'<div class="ay"><span class="aytxt">﴿'+esc(v.text)+'﴾</span> <b>'+esc(v.sura)+' '+AR(v.aya)+'</b></div>').join('')+(x.more?'<div class="muted">وغيرها '+AR(x.more)+'</div>':'');
  w.innerHTML='<h3>الآيات والعبارات القرآنية في هذه الصفحة</h3><div class="help">نص الكتاب أعلاه لم يتغيّر. قابل الآية بالمصحف قبل النقل.</div>'+
   r.map((x,i)=>'<div class="ayb"><span class="tag">'+(x.kind!='آية'?'عبارة قرآنية محتملة':x.cited?'آية مطابقة':'اقتباسٌ قرآنيّ في كلام المؤلّف')+'</span>'+(x.layer=='حاشية'?'<span class="tag foot">في الحاشية</span>':'')+
    ' <button class="btn2" data-ay="'+i+'">انسخ</button> <button class="btn2" data-aya="'+i+'">+ المسودة</button>'+line(x)+'<div class="muted" style="font-size:13px">في الكتاب: '+esc(x.words)+'</div></div>').join('');
  w.querySelectorAll('[data-ay]').forEach(b=>b.onclick=()=>{const x=r[+b.dataset.ay],v=x.verses[0];copy('﴿'+v.text+'﴾ ['+v.sura+': '+v.aya+']')});
  w.querySelectorAll('[data-aya]').forEach(b=>b.onclick=()=>{const v=r[+b.dataset.aya].verses[0];addToDraft({kind:'aya',text:v.text,ref:v.sura+': '+AR(v.aya)})});
}
function hlTerms(){ // كلماتُ البحث للتظليل في الصفحة (تقريبيّ: بلا تشكيل)
  if(!S.q||S.mode=='query'||S.mode=='group')return [];
  return S.mode=='phrase'?[S.q]:S.q.split(/\s+/);
}
function hl(t){
  let h=esc(t);
  for(const w of hlTerms()){
    const re=new RegExp(w.replace(/[.*+?^${}()|[\]\\]/g,'').split('').map(c=>{
      const g={'ا':'[اأإآٱ]','ي':'[يى]','ه':'[هة]','ة':'[هة]','أ':'[اأإآٱ]','إ':'[اأإآٱ]','آ':'[اأإآٱ]','ى':'[يى]'}[c]||c;
      return c==' '?'\\s+[\\u064B-\\u0652\\u0670\\u0640]*':g+'[\\u064B-\\u0652\\u0670\\u0640]*'}).join(''),'g');
    h=h.replace(re,m=>'<mark>'+m+'</mark>');
  }
  return h;
}
async function showImg(){
  const w=$('#pvimgw');w.style.display='block';$('#pvtwo').classList.remove('one');pvGrid();w.innerHTML='<div class="wait">تُجهَّز الصورة…</div>';
  const mark=S.mode=='phrase'&&S.q?S.q:'';
  let r=await api('/api/image',{b:PV.b,n:PV.n,mark});
  if(r.error&&mark)r=await api('/api/image',{b:PV.b,n:PV.n,mark:''});
  w.innerHTML=r.error?'<div class="wait err">'+esc(r.error)+'</div>':'<div class="imgwrap"><img src="'+r.url+'" alt="صورة الصفحة"></div>';
  const im=w.querySelector('img');if(im)await new Promise(res=>{if(im.complete)res();else{im.onload=res;im.onerror=res}});
  drawImgBoxes((document.querySelector('#pv .wd.on')||{}).dataset?.b);
}
$('#pvimg').onclick=showImg;
$('#pvclose').onclick=()=>$('#pv').style.display='none';
document.addEventListener('keydown',e=>{if(e.key=='Escape')$('#pv').style.display='none'});
$('#pvprev').onclick=()=>PV.n>1&&openPage(PV.b,PV.n-1,$('#pvimgw').style.display=='block');
$('#pvnext').onclick=()=>(!PV.total||PV.n<PV.total)&&openPage(PV.b,PV.n+1,$('#pvimgw').style.display=='block');
const goPage=()=>{const n=parseInt($('#pvgo').value);if(n>=1&&(!PV.total||n<=PV.total))openPage(PV.b,n,$('#pvimgw').style.display=='block');else toast('رقمٌ غير صحيح')};
$('#pvgo').addEventListener('keydown',e=>{if(e.key=='Enter'){e.preventDefault();goPage()}e.stopPropagation()});
document.addEventListener('keydown',e=>{if($('#pv').style.display!='block'||e.target.tagName=='INPUT')return;
  if(e.key=='ArrowLeft')$('#pvnext').click();else if(e.key=='ArrowRight')$('#pvprev').click()});
// قائمةُ الزرّ الأيمن (نافذةُ البرنامج لا تُظهر قائمةَ المتصفّح): نسخ، ونسخٌ مع العزو في القارئ، ولصق، وتحديدُ الكلّ
(function(){
  const m=$('#cmenu');let sel='',fld=null;
  const hide=()=>{m.style.display='none'};
  const item=(t,f)=>{const b=document.createElement('button');b.type='button';b.textContent=t;
    b.onmousedown=e=>e.preventDefault();b.onclick=()=>{hide();f()};m.appendChild(b)};
  document.addEventListener('contextmenu',e=>{
    sel=String(getSelection()).trim();fld=e.target.closest('input,textarea');
    if(fld&&fld.selectionEnd>fld.selectionStart)sel=fld.value.slice(fld.selectionStart,fld.selectionEnd);
    m.innerHTML='';
    if(sel)item('نسخ',()=>copy(sel));
    if(sel&&!fld&&$('#pv').style.display=='block'&&$('#pv').contains(getSelection().anchorNode)){item('انسخ مع العزو',()=>$('#pvcopy').click());item('أضف إلى المسودة',()=>$('#pvadd').click())}
    if(fld&&!fld.readOnly){
      if(sel)item('قصّ',()=>{copy(sel);fld.setRangeText('','select');fld.dispatchEvent(new Event('input'))});
      item('لصق',async()=>{try{const t=await navigator.clipboard.readText();fld.focus();fld.setRangeText(t,fld.selectionStart,fld.selectionEnd,'end');fld.dispatchEvent(new Event('input'))}catch(x){toast('للّصق: اضغط Ctrl+V')}});
    }
    item('تحديد الكلّ',()=>{if(fld){fld.focus();fld.select()}else{const r=document.createRange();r.selectNodeContents(e.target.closest('.panel,#pv')||document.body);getSelection().removeAllRanges();getSelection().addRange(r)}});
    e.preventDefault();m.style.display='block';
    const w=m.offsetWidth,h=m.offsetHeight;
    m.style.left=Math.max(4,Math.min(e.clientX-w,innerWidth-w-4))+'px';m.style.top=Math.max(4,Math.min(e.clientY,innerHeight-h-4))+'px';
  });
  ['click','scroll','blur','resize'].forEach(t=>addEventListener(t,hide,true));
  document.addEventListener('keydown',e=>{if(e.key=='Escape')hide()});
})();
(function(){   // زرُّ المظهر: تلقائيّ ← نهاريّ ← ليليّ، ويُحفظ الاختيار
  const b=$('#thm'),names={auto:'تلقائي',light:'نهاري',dark:'ليلي'},next={auto:'light',light:'dark',dark:'auto'};
  let t='auto';try{t=localStorage.getItem('bughya-theme')||'auto'}catch(e){}
  const set=v=>{t=v;if(v=='auto')delete document.documentElement.dataset.theme;else document.documentElement.dataset.theme=v;
    b.textContent=names[v];try{localStorage.setItem('bughya-theme',v)}catch(e){}};
  set(names[t]?t:'auto');b.onclick=()=>set(next[t]);
})();
$('#pvcopy').onclick=()=>{
  const p=PV.data;if(!p)return;const sel=String(getSelection()).trim();
  if(!sel){toast('حدّد النصَّ المراد نقلُه أوّلًا');return}
  const foot=p.foot&&$('#pvfoot').contains(getSelection().anchorNode);
  copy('«'+sel+'» — '+p.cite+' · رقم الكتاب '+AR(p.book_id)+(foot?' · الحاشية':'')+(p.method=='ocr'?' (قراءةٌ آليّة لم تُقابَل بالصورة)':''));
};
$('#pvadd').onclick=()=>{
  const p=PV.data;if(!p)return;const sel=String(getSelection()).replace(/\s+/g,' ').trim();
  if(!sel){toast('حدّد النصَّ المراد نقلُه أوّلًا');return}
  const foot=p.foot&&$('#pvfoot').contains(getSelection().anchorNode);
  addToDraft({kind:'quote',text:sel,b:p.book_id,n:p.n,cite:p.cite,vol:p.vol,printed:p.printed,unit:p.unit,layer:foot?'حاشية':'متن',method:p.method});
};
$('#pvsearch').onclick=()=>{$('#pv').style.display='none';show('search');S.books=new Set([PV.b]);$('#q').focus();
  if(S.q){S.offset=0;S.results=[];run(false);drawFacet()}else toast('اكتب ما تبحث عنه؛ وسيُحصر في هذا الكتاب')};

// ── المسوّدة: صفحةٌ متّصلة يكتب فيها الباحث، والنقولُ فيها قطعٌ مقفلة بعزوها (تُقابَل بصفحاتها)، وحواشيها تُرقَّم وحدها
let DR=null,DRT=null,DRANGE=null,DCLIP=null,DQ=null,DUNDO=null;
const ED=$('#ded'),uid=()=>Math.random().toString(36).slice(2,10);
try{document.execCommand('defaultParagraphSeparator',false,'p')}catch(e){}
async function loadDrafts(){if(!DR){try{const r=await api('/api/drafts');if(!r.error){DR=r;dRender()}}catch(e){}}return DR}
function curDraft(){return DR&&DR.drafts.find(d=>d.id==DR.current)}
function itemOf(id){const d=curDraft();return d&&d.items.find(x=>x.id==id)}
function saveDrafts(now){clearTimeout(DRT);
  const go=async()=>{const d=curDraft();if(d&&ED.dataset.d==d.id)d.body=dSer();const r=await api('/api/drafts',null,DR);if(r.error)toast(r.error)};
  if(now)return go();DRT=setTimeout(go,600)}
async function checkItem(it){
  const r=await api('/api/draft/check',null,{item:it});
  if(r.error){it.verdict='';it.vnote=r.error;return}
  it.verdict=r.verdict;
  it.vnote=r.verdict=='غيرُ مطابق'?(r.closest?'أقربُ ما في الصفحة: «'+r.closest+'»':''):(r.vnote||'').replace(/ ?\(sura\.py[^)]*\)/,'');
}
function stClass(it){if(it.kind=='aya')return 'aya';if(it.verdict=='غيرُ مطابق')return 'st-r';
  if((it.method=='ocr'&&!it.imgok)||(it.verdict||'').startsWith('يمتدّ'))return 'st-y';return 'st-ok'}
function qHTML(it){return '<span class="qt '+stClass(it)+'" contenteditable="false" data-id="'+esc(it.id)+'">'+
  (it.kind=='aya'?'﴿'+esc(it.text)+'﴾ ['+esc(it.ref||'')+']':'«'+esc(it.text)+'»<sup></sup>')+'</span>'}
function fnText(it){const t=(String(it.cite||'').match(/^«[^»]*»/)||[it.cite||''])[0],u=it.unit||'صفحة';let loc;
  if(u=='صفحة'&&it.printed)loc=it.vol?'('+AR(it.vol)+'/ '+AR(it.printed)+')':'(ص'+AR(it.printed)+')';
  else if(u=='صفحة')loc='('+(it.vol?'ج'+AR(it.vol)+'، ':'')+'صفحة الملف '+AR(it.n)+')';else loc='('+u+' '+AR(it.n)+')';
  return t+' '+loc+(it.layer=='حاشية'?'، في الحاشية':'')+'.'}
// الصفحة ← فقرات: [{t:'p'|'h', c:[نصّ, {q:رقم النقل}…]}]
function dSer(root){root=root||ED;
  const out=[];
  const push=(t,c)=>{const m=[];c.forEach(r=>{if(typeof r=='string'){r=r.replace(/[​﻿]/g,'').replace(/ /g,' ');
    if(typeof m[m.length-1]=='string')m[m.length-1]+=r;else m.push(r)}else m.push(r)});out.push({t,c:m.filter(r=>r!=='')})};
  const walk=(node,acc)=>{for(const ch of node.childNodes){
    if(ch.nodeType==3)acc.cur.push(ch.textContent);
    else if(ch.nodeType==1){
      if(ch.classList.contains('qt')&&ch.dataset.id)acc.cur.push({q:ch.dataset.id});
      else if(ch.tagName=='BR'){acc.lines.push(acc.cur);acc.cur=[]}
      else if(/^(P|DIV|H[1-6]|LI|BLOCKQUOTE)$/.test(ch.tagName)){acc.lines.push(acc.cur);acc.cur=[];walk(ch,acc);acc.lines.push(acc.cur);acc.cur=[]}
      else walk(ch,acc)}}};
  let inl=null;   // نصٌّ أو نقلٌ في أعلى الصفحة خارج الفقرات: يُجمع فقرةً واحدة
  const flush=()=>{if(inl){const s=inl.lines.concat([inl.cur]).filter(x=>x.length);(s.length?s:[[]]).forEach(x=>push('p',x));inl=null}};
  for(const el of root.childNodes){
    const block=el.nodeType==1&&/^(P|DIV|H[1-6]|LI|BLOCKQUOTE|UL|OL)$/.test(el.tagName);
    if(!block){if(el.nodeType==3&&!el.textContent.trim()&&!inl)continue;inl=inl||{lines:[],cur:[]};
      if(el.nodeType==3)inl.cur.push(el.textContent);else if(el.nodeType==1){if(el.classList.contains('qt'))inl.cur.push({q:el.dataset.id});else if(el.tagName=='BR'){inl.lines.push(inl.cur);inl.cur=[]}else walk(el,inl)}
      continue}
    flush();
    const t=/^H[1-6]$/.test(el.tagName)?'h':'p',acc={lines:[],cur:[]};walk(el,acc);acc.lines.push(acc.cur);
    let segs=acc.lines.filter(s=>s.length);if(!segs.length)segs=[[]];segs.forEach(s=>push(t,s));
  }
  flush();return out}
function dRender(){
  const d=curDraft();if(!d)return;ED.dataset.d=d.id;
  ED.innerHTML=(d.body||[]).map(p=>{const tag=p.t=='h'?'h2':'p';
    const inner=(p.c||[]).map(r=>typeof r=='string'?esc(r):(itemOf(r.q)?qHTML(itemOf(r.q))+'':'')).join('');
    return '<'+tag+'>'+(inner||'<br>')+'</'+tag+'>'}).join('')||'<p><br></p>';
  DRANGE=null;dSel();dNum()}
function dSel(){$('#dsel').innerHTML=DR.drafts.map(d=>'<option value="'+esc(d.id)+'"'+(d.id==DR.current?' selected':'')+'>'+esc(d.name)+'</option>').join('')}
function dNum(){
  let n=0;const notes=[];
  ED.querySelectorAll('.qt').forEach(s=>{const it=itemOf(s.dataset.id);if(!it||it.kind=='aya')return;n++;
    const sp=s.querySelector('sup');if(sp)sp.textContent='('+AR(n)+')';notes.push([s.dataset.id,fnText(it)])});
  $('#dfn').innerHTML=notes.map((x,i)=>'<div data-fq="'+esc(x[0])+'">('+AR(i+1)+') '+esc(x[1])+'</div>').join('');
  $('#dfn').querySelectorAll('[data-fq]').forEach(x=>x.onclick=()=>{const s=ED.querySelector('.qt[data-id="'+x.dataset.fq+'"]');if(s){s.scrollIntoView({block:'center',behavior:'smooth'});qtOpen(s)}});
  const c=$('#dcount');c.textContent=AR(n);c.style.display=n?'':'none';
  $('#dhint').style.display=(!ED.textContent.trim()&&!ED.querySelector('.qt'))?'block':'none';
}
// موضعُ المؤشّر في الصفحة يُحفظ، فيدخل النقلُ فيه وإن كنتَ في البحث
document.addEventListener('selectionchange',()=>{const s=getSelection();if(s.rangeCount&&ED.contains(s.anchorNode)&&ED.contains(s.focusNode))DRANGE=s.getRangeAt(0).cloneRange()});
function dInsert(it){
  const tmp=document.createElement('span');tmp.innerHTML=qHTML(it);const node=tmp.firstChild,sp=document.createTextNode(' ');
  let r=DRANGE&&ED.contains(DRANGE.startContainer)?DRANGE:null;
  if(r){const q=(r.startContainer.nodeType==1?r.startContainer:r.startContainer.parentNode).closest('.qt');
    if(q){r=document.createRange();r.setStartAfter(q)}
    r.collapse(false);
    if(r.startContainer==ED){const p=document.createElement('p');ED.insertBefore(p,ED.childNodes[r.startOffset]||null);r=document.createRange();r.setStart(p,0)}
    const sc=r.startContainer,so=r.startOffset,glued=sc.nodeType==3&&so>0&&!/\s/.test(sc.textContent[so-1]);
    r.insertNode(sp);r.insertNode(node);if(glued)r.insertNode(document.createTextNode(' '));
    const nr=document.createRange();nr.setStartAfter(sp);nr.collapse(true);DRANGE=nr;dNum();return 'في موضع المؤشّر'}
  const last=ED.lastElementChild;
  if(last&&last.tagName=='P'&&!last.textContent.trim()&&!last.querySelector('.qt')){last.innerHTML='';last.append(node,sp)}
  else{const p=document.createElement('p');p.append(node,sp);ED.appendChild(p)}
  const nr=document.createRange();nr.setStartAfter(sp);nr.collapse(true);DRANGE=nr;dNum();return 'في آخر المسودة'}
async function addToDraft(it){
  await loadDrafts();if(!DR){toast('تعذّر فتحُ المسودة');return}
  it.id=uid();
  if(it.kind=='quote'){if(it.vol!=null)it.vol=String(it.vol);if(it.printed!=null)it.printed=String(it.printed);await checkItem(it)}
  const d=curDraft();if(ED.dataset.d!=d.id)dRender();
  d.items.push(it);const where=dInsert(it);await saveDrafts(true);
  toast('أُضيف '+where+' في «'+d.name+'»'+(it.verdict=='غيرُ مطابق'?' — ولا يطابق الصفحة':''));
}
ED.addEventListener('input',()=>{dNum();saveDrafts()});
ED.addEventListener('drop',e=>e.preventDefault());ED.addEventListener('dragstart',e=>e.preventDefault());
// النسخُ داخل المسودة يحفظ النقولَ بعزوها، فيُنقل النقلُ بالقصّ واللصق؛ وما جاء من خارجها يُلصق نصًّا مجرّدًا
function runsHTML(c){return c.map(r=>typeof r=='string'?esc(r):(itemOf(r.q)?qHTML(itemOf(r.q)):'')).join('')}
function clipOf(s){const box=document.createElement('div');box.appendChild(s.getRangeAt(0).cloneContents());
  return {text:String(s),html:dSer(box).map(p=>runsHTML(p.c)).join('<br>')}}
ED.addEventListener('copy',()=>{const s=getSelection();if(s.rangeCount)DCLIP=clipOf(s)});
ED.addEventListener('cut',e=>{const s=getSelection();if(!s.rangeCount)return;DCLIP=clipOf(s);
  e.preventDefault();e.clipboardData.setData('text/plain',DCLIP.text);document.execCommand('delete');dNum();saveDrafts()});
ED.addEventListener('paste',e=>{e.preventDefault();const t=e.clipboardData.getData('text/plain');
  if(DCLIP&&t==DCLIP.text)document.execCommand('insertHTML',false,DCLIP.html);else document.execCommand('insertText',false,t);dNum()});
// النقرُ على نقل: عزوُه وحكمُه وأفعالُه
function qtClose(){$('#dqt').style.display='none';ED.querySelectorAll('.qt.sel').forEach(x=>x.classList.remove('sel'));DQ=null}
function qtOpen(s){
  const it=itemOf(s.dataset.id);if(!it)return;qtClose();DQ=s;s.classList.add('sel');const b=$('#dqt');
  let v='';
  if(it.kind=='aya')v='<div class="v">آية: ['+esc(it.ref||'')+']</div>';
  else{v='<div class="c">'+citeHTML(it.cite)+' <span class="bid nw">رقم الكتاب '+AR(it.b)+'</span></div><div class="v">'+
    (it.layer=='حاشية'?'<span class="tag foot">الحاشية</span>':'')+(it.method=='ocr'?'<span class="tag ocr">قراءةٌ آليّة</span>':'')+
    (it.verdict=='غيرُ مطابق'?'<span class="tag bad">لا يطابق نصَّ الصفحة</span>':it.verdict?'<span class="tag ok">'+esc(it.verdict)+'</span>':'')+
    (it.method=='ocr'&&!it.imgok?'<span class="tag warn">لم يُقابَل بالصورة</span>':'')+'</div>'+
    (it.vnote?'<div class="muted" style="font-size:13px">'+esc(it.vnote)+'</div>':'')+
    (it.method=='ocr'?'<label style="display:block;cursor:pointer;margin-top:4px"><input type="checkbox" id="dqimg"'+(it.imgok?' checked':'')+'> قابلتُه بصورة الصفحة، وصحّحتُه منها</label>':'')}
  b.innerHTML=v+'<div class="acts">'+(it.kind=='quote'?'<button class="btn2" id="dqopen">افتح الصفحة'+(it.method=='ocr'?' والصورة':'')+'</button><button class="btn2" id="dqedit">عدّل النصّ</button>':'')+
    '<button class="btn2" id="dqdel">احذفه</button><button class="btn2" id="dqx">إغلاق</button></div>';
  b.style.display='block';const R=s.getBoundingClientRect(),z=parseFloat(getComputedStyle(document.documentElement).zoom)||1;
  const w=b.offsetWidth,h=b.offsetHeight,W=innerWidth/z,H=innerHeight/z;
  let top=R.bottom/z+6;if(top+h>H-8)top=Math.max(8,R.top/z-h-6);
  b.style.top=top+'px';b.style.left=Math.max(8,Math.min(R.right/z-w,W-w-8))+'px';
  $('#dqx').onclick=qtClose;
  if($('#dqopen'))$('#dqopen').onclick=()=>{qtClose();openPage(it.b,it.n,it.method=='ocr')};
  if($('#dqedit'))$('#dqedit').onclick=()=>{$('#dqet').value=it.text;$('#dqe').classList.add('on');$('#dqet').focus()};
  if($('#dqimg'))$('#dqimg').onchange=async e=>{it.imgok=e.target.checked;await checkItem(it);dRefresh(it);saveDrafts();qtOpen(ED.querySelector('.qt[data-id="'+it.id+'"]'))};
  $('#dqdel').onclick=()=>{const nx=s.nextSibling;DUNDO={node:s,parent:s.parentNode,next:nx};
    if(nx&&nx.nodeType==3&&nx.textContent.startsWith(' '))nx.textContent=nx.textContent.slice(1);
    s.remove();qtClose();dNum();saveDrafts();
    const u=$('#dundo');u.innerHTML='حُذف النقل. <button class="btn2" id="dundob">تراجع</button>';u.style.display='block';
    $('#dundob').onclick=()=>{if(DUNDO&&ED.contains(DUNDO.parent)){DUNDO.parent.insertBefore(DUNDO.node,DUNDO.next&&DUNDO.next.parentNode==DUNDO.parent?DUNDO.next:null);DUNDO.node.after(document.createTextNode(' '));dNum();saveDrafts()}u.style.display='none'}};
}
function dRefresh(it){const s=ED.querySelector('.qt[data-id="'+it.id+'"]');if(s){const t=document.createElement('span');t.innerHTML=qHTML(it);s.replaceWith(t.firstChild)}dNum()}
ED.addEventListener('click',e=>{const s=e.target.closest('.qt');if(s){e.preventDefault();qtOpen(s)}else qtClose()});
document.addEventListener('mousedown',e=>{if($('#dqt').style.display=='block'&&!$('#dqt').contains(e.target)&&!e.target.closest('.qt'))qtClose();
  if(!e.target.closest('.dmw'))$('#dmenu').classList.remove('on')},true);
document.addEventListener('keydown',e=>{if(e.key=='Escape'){qtClose();$('#dqe').classList.remove('on')}});
$('#dqex').onclick=()=>$('#dqe').classList.remove('on');
$('#dqeok').onclick=async()=>{const s=DQ,it=s&&itemOf(s.dataset.id);const t=$('#dqet').value.replace(/\s+/g,' ').trim();
  if(!it){$('#dqe').classList.remove('on');return}if(!t){toast('النقلُ فارغ');return}
  it.text=t;$('#dqeok').disabled=true;await checkItem(it);$('#dqeok').disabled=false;$('#dqe').classList.remove('on');
  dRefresh(it);saveDrafts();qtClose();toast(it.verdict=='غيرُ مطابق'?'حُفظ، ولا يطابق نصَّ الصفحة':'حُفظ: '+it.verdict)};
// العنوان والنصّ
const keepSel=b=>b.addEventListener('mousedown',e=>e.preventDefault());
[$('#dfh'),$('#dfp')].forEach(keepSel);
$('#dfh').onclick=()=>{if(!ED.contains(getSelection().anchorNode)){toast('ضع المؤشّر في الفقرة أوّلًا');return}document.execCommand('formatBlock',false,'h2');dNum();saveDrafts()};
$('#dfp').onclick=()=>{if(!ED.contains(getSelection().anchorNode)){toast('ضع المؤشّر في الفقرة أوّلًا');return}document.execCommand('formatBlock',false,'p');dNum();saveDrafts()};
// المسوّدات
$('#dmore').onclick=()=>$('#dmenu').classList.toggle('on');
$('#dsel').onchange=async()=>{await saveDrafts(true);DR.current=$('#dsel').value;dRender();saveDrafts(true)};
let DNAME=null;
const nameBox=(mode,val)=>{$('#dmenu').classList.remove('on');DNAME=mode;$('#dnamei').value=val||'';$('#dnamebox').style.display='flex';$('#dnamei').focus()};
$('#dnew').onclick=()=>nameBox('new','');
$('#dren').onclick=()=>nameBox('ren',curDraft().name);
$('#dnamex').onclick=()=>{$('#dnamebox').style.display='none'};
$('#dnamei').addEventListener('keydown',e=>{if(e.key=='Enter')$('#dnameok').click();if(e.key=='Escape')$('#dnamex').click()});
$('#dnameok').onclick=async()=>{const v=$('#dnamei').value.trim();if(!v){toast('اكتب اسمًا');return}
  if(DNAME=='new'){await saveDrafts(true);const d={id:uid(),name:v,items:[],body:[]};DR.drafts.push(d);DR.current=d.id;dRender()}else{curDraft().name=v;dSel()}
  $('#dnamebox').style.display='none';saveDrafts(true)};
$('#ddel').onclick=()=>{$('#dmenu').classList.remove('on');const d=curDraft(),q=$('#ddelq');
  q.innerHTML='تُحذف المسودة «'+esc(d.name)+'» بكلامك ونقولها، ولا تُستعاد. <button class="btn" id="ddely">نعم، احذفها</button> <button class="btn2" id="ddeln">إلغاء</button>';q.style.display='block';
  $('#ddeln').onclick=()=>q.style.display='none';
  $('#ddely').onclick=()=>{DR.drafts=DR.drafts.filter(x=>x.id!=d.id);if(!DR.drafts.length)DR.drafts.push({id:uid(),name:'مسوّدتي',items:[],body:[]});
    DR.current=DR.drafts[0].id;ED.dataset.d='';q.style.display='none';dRender();saveDrafts(true)}};
// الإخراج: وورد (والحواشي في أسفل الصفحات)، وPDF والطباعة (والحواشي في آخرها)
function dWarn(){const ids=[...ED.querySelectorAll('.qt')].map(s=>itemOf(s.dataset.id)).filter(Boolean);
  const bad=ids.filter(x=>x.verdict=='غيرُ مطابق').length,ocr=ids.filter(x=>x.method=='ocr'&&!x.imgok).length;
  return (bad?AR(bad)+' نقلًا لا يطابق صفحته':'')+(bad&&ocr?'، و':'')+(ocr?AR(ocr)+' نقلًا لم يُقابَل بالصورة':'')}
const dEmpty=()=>!ED.textContent.trim()&&!ED.querySelector('.qt');
async function dExport(kind){await saveDrafts(true);const d=curDraft();if(dEmpty()){toast('المسودة فارغة');return}
  toast(kind=='pdf'?'يُجهَّز PDF…':'يُجهَّز ملفُّ وورد…');
  const r=await api('/api/draft/'+kind,null,kind=='pdf'?{id:d.id,html:dHTML(d)}:{id:d.id});
  if(r.error){toast(r.error);return}
  if(r.fallback){toast('تعذّر صنعُ PDF مباشرة؛ فاختر في نافذة الطباعة «Microsoft Print to PDF»');setTimeout(dPrint,1500);return}
  const w=dWarn();toast('حُفظ في التنزيلات: '+r.name+(w?' — وفيه '+w+'، معلَّمٌ في الملفّ':''))}
$('#ddocx').onclick=()=>dExport('docx');
$('#dpdf').onclick=()=>dExport('pdf');
function dHTML(d){
  const body=dSer();while(body.length&&!body[body.length-1].c.some(r=>typeof r!='string'||r.trim()))body.pop();
  let n=0;const notes=[];
  const h='<h1>'+esc(d.name)+'</h1>'+body.map(p=>{const tag=p.t=='h'?'h2':'p';
    return '<'+tag+'>'+(p.c.map(r=>{if(typeof r=='string')return esc(r);const it=itemOf(r.q);if(!it)return '';
      if(it.kind=='aya')return '﴿'+esc(it.text)+'﴾ ['+esc(it.ref||'')+']';
      n++;notes.push(fnText(it));
      return '«'+esc(it.text)+'»<sup>('+AR(n)+')</sup>'+(it.verdict=='غيرُ مطابق'?' <span class="fr">[لا يطابق نصَّ الصفحة]</span>':'')+(it.method=='ocr'&&!it.imgok?' <span class="fy">[لم يُقابَل بالصورة]</span>':'')}).join('')||'&nbsp;')+'</'+tag+'>'}).join('')+
    (notes.length?'<div class="fns">'+notes.map((t,i)=>'<div>('+AR(i+1)+') '+esc(t)+'</div>').join('')+'</div>':'');
  return '<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8"><title>'+esc(d.name)+'</title><style>@page{size:A4;margin:2.2cm}*{-webkit-print-color-adjust:exact;print-color-adjust:exact}body{font:17pt/1.8 "Traditional Arabic","Arabic Typesetting",serif;color:#000;text-align:justify;white-space:pre-wrap}h1{text-align:center;font-size:22pt;white-space:normal}h2{font-size:18pt;color:#0b5240;margin:14pt 0 4pt}p{margin:0 0 6pt}sup{font-size:10pt}.fr{background:#a8201a;color:#fff;font-size:12pt;padding:0 4px}.fy{background:#ffe680;font-size:12pt;padding:0 4px}.fns{border-top:1px solid #777;margin-top:24pt;padding-top:8pt;font-size:13pt;line-height:1.6;white-space:normal}</style></head><body>'+h+'</body></html>'}
function dPrint(){const d=curDraft();if(dEmpty()){toast('المسودة فارغة');return}
  const doc=dHTML(d),f=$('#dpf');f.onload=()=>{f.onload=null;try{f.contentWindow.focus();f.contentWindow.print()}catch(e){toast('تعذّرت الطباعة: '+e)}};f.srcdoc=doc}
$('#dprint').onclick=dPrint;
loadDrafts();

// ── ألفاظٌ مجاورة
$('#jf').onsubmit=async e=>{e.preventDefault();const q=$('#jq').value.trim();if(!q)return;
  const w=$('#jres');w.innerHTML='<div class="wait">يحسب…</div>';
  const r=await api('/api/jiwar',{q});
  if(r.error){w.innerHTML='<div class="wait err">'+esc(r.error)+'</div>';return}
  if(!r.pages){w.innerHTML='<div class="wait">لم أجد «'+esc(q)+'» في كتبك المقروءة.</div>';return}
  const tab=(arr,before)=>'<table><thead><tr><th>العبارة</th><th>مرّات</th><th>كتب</th><th></th></tr></thead><tbody>'+arr.map(x=>{
    const ph=before?x.words+' '+q:q+' '+x.words;
    return '<tr><td><span class="lnk" data-s="'+esc(ph)+'">'+(before?'<b>'+esc(x.words)+'</b> '+esc(q):esc(q)+' <b>'+esc(x.words)+'</b>')+'</span></td><td class="n">'+AR(x.count)+'</td><td>'+AR(x.books)+'</td><td><button class="btn2" data-g="'+esc(ph)+'" title="أضف إلى مجموعة">+</button></td></tr>'}).join('')+'</tbody></table>';
  w.innerHTML='<div class="summary">«'+esc(q)+'» في '+AR(r.pages)+' صفحة. والكلماتُ هنا مطبَّعة (بلا همزات ولا تاء مربوطة).</div><div class="cols"><div class="box2"><b>ما يسبقه</b>'+tab(r.before||[],true)+'</div><div class="box2"><b>ما يليه</b>'+tab(r.after||[],false)+'</div></div>';
  w.querySelectorAll('[data-s]').forEach(a=>a.onclick=()=>{show('search');$('#q').value=a.dataset.s;$('#mode').value='phrase';$('#mode').onchange();newSearch(a.dataset.s,'phrase')});
  w.querySelectorAll('[data-g]').forEach(a=>a.onclick=()=>{show('groups');const t=$('#gterms');t.value=(t.value.trim()?t.value.trim()+'\n':'')+a.dataset.g;if(!$('#gname').value)$('#gname').value=q;toast('أُضيف؛ احفظ المجموعة')});
};

// ── مجموعاتي
let GROUPS=[];
async function loadGroups(){GROUPS=await api('/api/groups');drawGroups()}
function drawGroups(){
  const w=$('#glist');
  if(!GROUPS.length){w.innerHTML='<div class="muted">لا مجموعاتٍ بعد.</div>';return}
  w.innerHTML=GROUPS.map((g,i)=>'<div class="box2"><b>'+esc(g.name)+'</b> <span class="muted">('+AR(g.terms.length)+' ألفاظ)</span><div>'+g.terms.map(esc).join(' · ')+'</div>'+
    '<div class="acts"><button class="btn" data-run="'+i+'">ابحث بها</button><button class="btn2" data-edit="'+i+'">عدّل</button><button class="btn2" data-del="'+i+'">احذف</button></div></div>').join('');
  w.querySelectorAll('[data-run]').forEach(b=>b.onclick=()=>{const g=GROUPS[+b.dataset.run];show('search');$('#q').value='مجموعة: '+g.name;$('#mhelp').textContent=HELP.group+' ('+g.terms.join(' · ')+')';newSearch(g.terms.join('\n'),'group')});
  w.querySelectorAll('[data-edit]').forEach(b=>b.onclick=()=>{const g=GROUPS[+b.dataset.edit];$('#gname').value=g.name;$('#gterms').value=g.terms.join('\n');scrollTo(0,0)});
  w.querySelectorAll('[data-del]').forEach(b=>b.onclick=async()=>{const g=GROUPS[+b.dataset.del];if(!confirm('أحذف مجموعة «'+g.name+'»؟'))return;
    GROUPS.splice(+b.dataset.del,1);GROUPS=await api('/api/groups',null,{groups:GROUPS});drawGroups()});
}
$('#gsave').onclick=async()=>{const name=$('#gname').value.trim(),terms=$('#gterms').value.split('\n').map(s=>s.trim()).filter(Boolean);
  if(!name||!terms.length){toast('اكتب اسمًا ولفظًا واحدًا على الأقلّ');return}
  GROUPS=GROUPS.filter(g=>g.name!=name);GROUPS.push({name,terms});
  const r=await api('/api/groups',null,{groups:GROUPS});if(r.error){toast(r.error);return}GROUPS=r;drawGroups();toast('حُفظت ✓')};
$('#gclear').onclick=()=>{$('#gname').value='';$('#gterms').value='';$('#gm').innerHTML=''};
$('#gmeasure').onclick=async()=>{const t=$('#gterms').value.trim();if(!t)return;$('#gm').innerHTML='<div class="wait">يقيس…</div>';
  const r=await api('/api/measure',{q:t});
  if(r.error){$('#gm').innerHTML='<div class="err">'+esc(r.error)+'</div>';return}
  const rows=r.terms||r.results||r;
  $('#gm').innerHTML='<table><thead><tr><th>اللفظ</th><th>صفحات</th><th>كتب</th><th>مواضع</th><th>زيادةُ التسامح بالنقاط</th></tr></thead><tbody>'+
   (Array.isArray(rows)?rows:[]).map(x=>'<tr><td>'+esc(x.term)+'</td><td class="n">'+AR(x.pages)+'</td><td>'+AR(x.books)+'</td><td>'+(x.occurrences>=0?AR(x.occurrences):'كثيرة')+'</td><td>'+(x.rasm_extra?'+'+AR(x.rasm_extra):'—')+'</td></tr>').join('')+'</tbody></table>';
};

// ── الكتب
let BOOKS=null;
const STATE={done:'قُرئ',reading:'يُقرأ',pending:'ينتظر',error:'تعذّر',unsupported:'لا يُقرأ',empty:'لا نصّ',missing:'مفقود',duplicate:'مكرَّر'};
async function loadBooks(){$('#btab').innerHTML='<div class="wait">تُحمَّل الكتب…</div>';BOOKS=await api('/api/books');
  if(BOOKS.error){$('#btab').innerHTML='<div class="err">'+esc(BOOKS.error)+'</div>';BOOKS=null;return}drawBooks()}
function how(b){
  let h='';
  if(b.done_pages){const sh=(b.ocr_pages||0)/b.done_pages;
    h=sh>0.9?'<span class="tag ocr">قراءة آلية</span>':sh>0.05?'<span class="tag ocr">قراءة مختلطة</span>':'<span class="tag">نص الملف</span>'}
  try{const x=b.hints&&JSON.parse(b.hints);           // المكرَّرُ والمشابهُ يظهران وإن لم تُقرأ صفحة
    if(x)for(const k of ['dup','similar','note'])if(x[k])h+='<div style="font-size:12px;margin-top:3px">'+esc(x[k])+'</div>'}catch(e){}
  return h}
const BT={modern_print:'طبعة حديثة',old_print:'طبعة قديمة',lithograph:'طبعة حجرية',manuscript:'مخطوط'};
const OLD=['old_print','lithograph','manuscript'];
function btOptions(b){const cur=b.btype||'auto';
  return '<option value="auto"'+(cur=='auto'?' selected':'')+'>'+(b.btype_auto?'تلقائي: '+BT[b.btype_auto]:'النوع: لم يُحدَّد')+'</option>'+
   Object.entries(BT).map(([k,v])=>'<option value="'+k+'"'+(cur==k?' selected':'')+'>'+v+'</option>').join('')}
function coverKind(b){if(['error','unsupported','empty','missing','duplicate'].includes(b.state))return 'bad';if(!b.done_pages)return 'wait';return (b.ocr_pages||0)/b.done_pages>0.05?'ocr':''}
function bookTitle(b){return (b.series||b.title||'')+(b.volume?' ج'+AR(b.volume):'')}
// الأصناف: صنفٌ واحدٌ لكلّ كتاب، والقائمةُ في categories.json
let CATS=[],BCAT='',COVV={};
async function loadCats(){try{const r=await api('/api/cats');if(Array.isArray(r))CATS=r}catch(e){}
  const s=$('#fann'),v=s.value;s.innerHTML='<option value="">كلّ الأصناف</option>'+CATS.map(c=>'<option>'+esc(c)+'</option>').join('');s.value=v}
loadCats();
function catSelect(b){
  return '<select class="cat'+(b.fann?'':' none')+'" data-cat="'+b.id+'" title="صنفُ الكتاب"><option value="">— اختر صنفه —</option>'+
    CATS.map(c=>'<option'+(c==b.fann?' selected':'')+'>'+esc(c)+'</option>').join('')+
    (b.fann&&!CATS.includes(b.fann)?'<option selected>'+esc(b.fann)+'</option>':'')+'<option value="+">＋ صنفٌ جديد…</option></select>'}
function drawChips(){
  const cnt={};BOOKS.forEach(b=>{const c=b.fann||'';cnt[c]=(cnt[c]||0)+1});
  const list=[['','الكلّ',BOOKS.length],...CATS.filter(c=>cnt[c]).map(c=>[c,c,cnt[c]]),...(cnt['']&&cnt['']<BOOKS.length?[['-','غير مصنّف',cnt['']]]:[])];
  if(BCAT&&!list.some(x=>x[0]==BCAT))BCAT='';
  $('#bchips').innerHTML=list.length>1?list.map(([k,l,n])=>'<button class="chip'+(k==BCAT?' on':'')+'" data-chip="'+esc(k)+'">'+esc(l)+'<i>'+AR(n)+'</i></button>').join(''):'';
  document.querySelectorAll('[data-chip]').forEach(b=>b.onclick=()=>{BCAT=b.dataset.chip;drawBooks()});
}
async function setCat(id,c){
  const r=await api('/api/book-cat',null,{b:id,fann:c});if(r.error){toast(r.error);return false}
  const b=BOOKS.find(x=>x.id==id);b.fann=c||null;toast(c?'صُنّف في «'+c+'»':'أُزيل صنفه');drawBooks();return true}
function coverFail(im){const btn=im.closest('.cover');btn.classList.remove('img');btn.innerHTML='<span><b>'+esc(btn.dataset.t)+'</b></span>'}
function drawBooks(){
  drawChips();
  const f=$('#bf').value.trim();const list=BOOKS.filter(b=>(!f||bookTitle(b).includes(f)||(b.author||'').includes(f))&&
    (!BCAT||(BCAT=='-'?!b.fann:b.fann==BCAT)));
  $('#bcount').textContent=AR(list.length)+' من '+AR(BOOKS.length);
  if(!BOOKS.length){$('#btab').innerHTML='<div class="wait">لا كتب بعد. <span class="lnk" id="goadd">أضف كتبك</span> لتبدأ.</div>';$('#goadd').onclick=()=>show('welcome');return}
  $('#btab').innerHTML=list.map(b=>{const part=b.pages&&b.pages!=b.done_pages,img=b.cover&&b.done_pages&&!['error','unsupported','missing','duplicate'].includes(b.state);
    const name=b.unclear?'<span class="fname">'+esc(bookTitle(b))+'</span>':esc(bookTitle(b));
    return '<div class="vol"><button class="cover '+coverKind(b)+(img?' img':'')+'" title="افتح الكتاب: صورة الصفحة بجانب النص المستخرج" data-rd="'+b.id+'" data-t="'+esc(bookTitle(b))+'">'+
    (img?'<img src="/cover/'+b.id+'.png?v='+(COVV[b.id]||0)+'" alt="" loading="lazy" onerror="coverFail(this)">':
      '<span><b>'+esc(bookTitle(b))+'</b>'+(b.author?'<i>'+esc(b.author)+(b.death?' (ت '+esc(b.death)+')':'')+'</i>':'')+'</span>')+'</button>'+
    (img?'<div class="vt">'+name+(b.author?'<div class="muted" style="font-size:13px">'+esc(b.author)+(b.death?' (ت '+esc(b.death)+')':'')+'</div>':'')+'</div>':'')+
    (part?'<div class="prog"><i style="width:'+Math.round(100*(b.done_pages||0)/b.pages)+'%"></i></div>':'')+
    '<div class="meta">'+AR(b.done_pages||0)+(part?' من '+AR(b.pages):'')+' '+(b.unit=='قطعة'?'قطعة':'صفحة')+' ، '+(STATE[b.state]||esc(b.state))+'<br>'+how(b)+'</div>'+
    catSelect(b)+
    '<select class="bt" data-bt="'+b.id+'" title="نوع الكتاب">'+btOptions(b)+'</select>'+
    '<div class="acts"><span class="lnk" data-sb="'+b.id+'">ابحث فيه</span>'+
    (b.unclear?'':'<span class="lnk" data-ren="'+b.id+'">بياناته</span>')+'</div>'+(b.unclear?'<div class="meta">'+noTitle(b.id)+'</div>':'')+'</div>'}).join('');
  document.querySelectorAll('[data-cat]').forEach(s=>s.onchange=async()=>{const id=+s.dataset.cat;
    if(s.value!='+'){setCat(id,s.value);return}
    const w=document.createElement('div');w.className='newcat';w.innerHTML='<input type="text" placeholder="اسمُ الصنف"><button class="btn2">أضف</button>';
    s.after(w);s.style.display='none';const inp=w.querySelector('input');inp.focus();
    const add=async()=>{const c=inp.value.trim();if(!c){drawBooks();return}
      if(!CATS.includes(c)){const r=await api('/api/cats',null,{cats:[...CATS,c]});if(r.error){toast(r.error);return}CATS=r;loadCats()}
      setCat(id,c)};
    w.querySelector('button').onclick=add;inp.onkeydown=e=>{if(e.key=='Enter')add();if(e.key=='Escape')drawBooks()}});
  document.querySelectorAll('[data-bt]').forEach(s=>s.onchange=async()=>{const r=await api('/api/btype',null,{b:+s.dataset.bt,t:s.value});
    if(r.error||!r.ok){toast(r.error||'تعذّر الحفظ');return}const bk=BOOKS.find(x=>x.id==+s.dataset.bt);bk.btype=s.value=='auto'?null:s.value;toast('حُفظ نوع الكتاب')});
  document.querySelectorAll('[data-sb]').forEach(a=>a.onclick=()=>{S.books=new Set([+a.dataset.sb]);show('search');$('#q').focus();toast('اكتب ما تبحث عنه؛ وسيُحصر في هذا الكتاب');if(S.q){S.offset=0;S.results=[];run(false)}});
  document.querySelectorAll('[data-rd]').forEach(a=>a.onclick=()=>{const b=BOOKS.find(x=>x.id==+a.dataset.rd);openPage(b.id,1,b.unit=='صفحة')});
}
$('#bf').oninput=()=>BOOKS&&drawBooks();

// ── بياناتُ الكتاب (عنوانُه ومؤلّفه ووفاته)
let RENB=0;
async function openRen(id){
  if(!Array.isArray(BOOKS))try{BOOKS=await api('/api/books')}catch(e){}
  const b=Array.isArray(BOOKS)&&BOOKS.find(x=>x.id==id)||{id};RENB=id;
  $('#renid').textContent='رقم الكتاب '+AR(id)+(b.title?' · اسمه الآن: '+b.title:'');
  $('#rent').value=b.unclear?'':(b.title||'');$('#rena').value=b.author||'';$('#rend').value=b.death||'';
  $('#ren').classList.add('on');$('#rent').focus();
}
$('#renx').onclick=()=>$('#ren').classList.remove('on');
$('#ren').onclick=e=>{if(e.target.id=='ren')$('#ren').classList.remove('on')};
$('#renimg').onclick=async()=>{$('#ren').classList.remove('on');
  if(!Array.isArray(BOOKS))try{BOOKS=await api('/api/books')}catch(e){}
  const b=Array.isArray(BOOKS)&&BOOKS.find(x=>x.id==RENB);openPage(RENB,1,!b||b.unit=='صفحة');
  toast('إذا عرفتَ العنوان فاضغط «بيانات الكتاب» في أعلى العارض')};
$('#rensave').onclick=async()=>{
  const r=await api('/api/book-set',null,{b:RENB,title:$('#rent').value,author:$('#rena').value,death:$('#rend').value});
  if(r.error){toast(r.error);return}
  $('#ren').classList.remove('on');toast('حُفظت بياناتُ الكتاب ✓');
  BOOKS=await api('/api/books');
  if($('#p-books').classList.contains('on'))drawBooks();
  if($('#pv').style.display=='block'&&PV.b==RENB)openPage(PV.b,PV.n,$('#pvimgw').style.display=='block');
  if(S.q){S.offset=0;S.results=[];run(true)}
};
$('#pvren').onclick=()=>openRen(PV.b);
$('#pvcover').onclick=async()=>{const r=await api('/api/cover-set',null,{b:PV.b,n:PV.n});
  if(r.error){toast(r.error);return}COVV[PV.b]=Date.now();toast('صارت هذه الصفحةُ غلافَ الكتاب ✓');
  if(Array.isArray(BOOKS)&&$('#p-books').classList.contains('on'))drawBooks()};

// ── عرضُ النصّ أسطرًا متّصلة: يُوصل السطرُ بما بعده ما لم ينتهِ به الكلام (للعرض وحده؛ نصُّ الكتاب لا يتغيّر)
let FLOW=true;try{FLOW=localStorage.getItem('bughya-flow')!='0'}catch(e){}
function flowLabel(){$('#pvflow').textContent=FLOW?'أسطرُ الصفحة كما في الكتاب':'نصٌّ متّصل'}
flowLabel();
$('#pvflow').onclick=()=>{FLOW=!FLOW;try{localStorage.setItem('bughya-flow',FLOW?'1':'0')}catch(e){}flowLabel();
  if(PV.b)openPage(PV.b,PV.n,$('#pvimgw').style.display=='block')};
// الفاصلُ بعد كلّ سطر: سطرٌ جديد أو مسافة
function lineSeps(lines){
  const len=lines.map(l=>l.trim().length),nz=len.filter(n=>n>0).sort((a,b)=>a-b),med=nz.length?nz[nz.length>>1]:0;
  return lines.map((l,i)=>{
    if(!FLOW||i==lines.length-1)return '\n';
    const t=l.trim(),nx=(lines[i+1]||'').trim();
    if(!t||!nx)return '\n';
    if(/[.:؛؟!…][»"”'’)\]]*\s*(\([٠-٩0-9]+\))?$/.test(t))return '\n';      // انتهى الكلام
    if(med&&t.length<0.6*med)return '\n';                                     // سطرٌ قصير: آخرُ الفقرة
    if(/^(\(?[٠-٩0-9]+[)\-.]|[-–•*]|\[)/.test(nx))return '\n';                // التالي يبدأ حاشيةً أو بندًا
    return ' ';
  });
}
function flowText(t){const ls=String(t||'').split('\n'),sp=lineSeps(ls);return ls.map((l,i)=>l+(i<ls.length-1?sp[i]:'')).join('')}
document.addEventListener('click',e=>{const t=e.target.closest('[data-ren]');if(!t)return;e.preventDefault();e.stopPropagation();openRen(+t.dataset.ren)},true);

// ── حالُ المكتبة
async function loadStatus(){const r=await api('/api/progress');if(r.error){$('#stext').textContent=r.error;return}
  $('#stext').textContent='مكتبتُك: '+AR(r.books_total)+' كتابًا، قُرئ منها '+AR(r.books_done)+' ('+AR(r.pages)+' صفحة وقطعة)'+(r.running?'\nتُقرأ الآن في الخلفيّة…':(r.pending?'\nبقي ما لم يُقرأ: اضغط «حدّث المكتبة».':''))+
   (r.errors.length?'\n\nكتبٌ لم تُقرأ:\n'+r.errors.map(e=>'• '+e.title+' — '+(e.error||'')).join('\n'):'')}
$('#upd').onclick=async()=>{$('#upd').disabled=true;$('#utext').textContent='…';const r=await api('/api/update',null,{});$('#utext').textContent=r.text||r.error||'بدأت القراءة في الخلفيّة.';$('#upd').disabled=false;pollProgress();setTimeout(loadStatus,3000)};
$('#stopb').onclick=async()=>{const r=await api('/api/stop',null,{});toast(r.text||r.error||'ستتوقّف القراءة')};
api('/api/coverage').then(c=>{if(!c.error)setCov(c)});

// ── التقدّم وإرشادُ القراءة الضوئيّة وأوّلُ تشغيل
let PG=null,firstShown=false;
async function pollProgress(){
  let r;try{r=await api('/api/progress')}catch(e){return}
  if(r.error&&r.books_total===undefined)return;
  PG=r;const bar=$('#progbar');
  if(r.running){const pct=r.current_pages?Math.min(100,Math.round(100*(r.current_page||0)/r.current_pages)):0;
    bar.style.display='block';
    bar.innerHTML='<b>تُقرأ كتبُك الآن</b> — قُرئ '+AR(r.books_done)+' من '+AR(r.books_total)+' كتابًا'+(r.current_title?'<br>الكتابُ الجاري: «'+esc(r.current_title)+'» — '+AR(r.current_page||0)+' من '+AR(r.current_pages||0)+(r.current_method?' ('+esc(r.current_method)+')':''):'')+
     '<div class="prog"><i style="width:'+pct+'%"></i></div><span style="font-size:14px">يمكنك البحثُ فيما قُرئ ريثما تكتمل القراءة.</span>';
    api('/api/coverage').then(c=>{if(!c.error)setCov(c)});
  }else bar.style.display='none';
  if(!firstShown){firstShown=true;if(!r.books_total&&!r.running&&!r.sources.length)show('welcome')}
  drawOcr(r);
  setTimeout(pollProgress,r.running?2000:8000);
}
async function drawOcr(r){
  const bar=$('#ocrbar');
  if(!r.scanned_unread){bar.style.display='none';return}
  const o=await api('/api/ocr');
  if(o.ok){bar.style.display='block';
    bar.innerHTML='في مكتبتك كتبٌ مصوَّرة لم يُقرأ نصُّها بعد (عددها '+AR(r.scanned_unread)+')، والقراءةُ الضوئيّة العربيّةُ متاحةٌ الآن. <button class="btn2" id="rrs">اقرأها الآن</button>';
    $('#rrs').onclick=async()=>{const x=await api('/api/reread-scanned',null,{});toast(x.error||'بدأت القراءة');pollProgress()};return}
  bar.style.display='block';
  bar.innerHTML='<b>بعضُ كتبك صفحاتُها صورٌ (عددها '+AR(r.scanned_unread)+')، ولا يستطيع جهازُك قراءةَ الحروف العربيّة من الصور بعدُ.</b> لتفعيل ذلك مرّةً واحدة:'+
   '<ol><li>اضغط «افتح إعدادات اللغة» أدناه (أو: الإعدادات ← الوقت واللغة ← اللغة).</li><li>اختر «إضافة لغة» ثمّ «العربيّة»، واتركْ خيار «التعرّف الضوئي على الحروف» (OCR) مُعلَّمًا.</li><li>انتظر حتى يكتمل التنزيل (يحتاج اتّصالًا بالإنترنت هذه المرّة وحدها)، ثمّ ارجع إلى هنا واضغط «تحقّقت».</li></ol>'+
   '<button class="btn2" id="oset">افتح إعدادات اللغة</button> <button class="btn2" id="ochk">تحقّقتُ، أعد المحاولة</button> <span style="font-size:14px">الكتبُ التي فيها نصٌّ تُقرأ وتُبحث دون ذلك.</span>';
  $('#oset').onclick=()=>api('/api/open-settings',null,{});
  $('#ochk').onclick=async()=>{const x=await api('/api/reread-scanned',null,{});if(x.error)toast('ما زالت غير متاحة؛ تأكّد من اكتمال التنزيل ثمّ أعد المحاولة');else{toast('بدأت قراءةُ الكتب المصوَّرة');pollProgress()}};
}

// ── أضف كتبًا
const EXTS='pdf xps oxps cbz png jpg jpeg tif tiff bmp gif webp docx odt rtf doc txt text md htm html xhtml epub'.split(' ');
const okExt=n=>EXTS.includes(n.split('.').pop().toLowerCase());
async function collect(dt){
  const out=[];const ents=[...dt.items].map(i=>i.webkitGetAsEntry&&i.webkitGetAsEntry()).filter(Boolean);
  if(!ents.length)return [...dt.files].map(f=>({file:f,rel:f.name}));
  async function walk(e,path){
    if(e.isFile){await new Promise(r=>e.file(f=>{out.push({file:f,rel:path+f.name});r()},r))}
    else{const rd=e.createReader();let all=[];for(;;){const b=await new Promise(r=>rd.readEntries(r,()=>r([])));if(!b.length)break;all=all.concat(b)}
      for(const c of all)await walk(c,path+e.name+'/')}}
  for(const e of ents)await walk(e,'');
  return out;
}
async function uploadAll(list){
  list=list.filter(x=>okExt(x.rel));const info=$('#upinfo');
  if(!list.length){info.textContent='لم أجد فيما سحبتَه كتبًا بصيغةٍ مدعومة.';return}
  let done=0,bytes=0;
  for(const x of list){
    info.textContent='يُنسخ '+AR(done+1)+' من '+AR(list.length)+': '+x.rel;
    try{const r=await fetch('/api/upload?rel='+encodeURIComponent(x.rel),{method:'PUT',body:x.file});const j=await r.json();if(j.error){info.textContent='تعذّر: '+j.error;return}}catch(e){info.textContent='انقطع النسخ: '+e;return}
    done++;
  }
  info.textContent='نُسخ '+AR(done)+' كتابًا. بدأت القراءة…';
  await api('/api/update',null,{});firstShown=true;pollProgress();show('search');toast('بدأت القراءة؛ ابحث فيما قُرئ');
}
const dz=$('#dz');
['dragenter','dragover'].forEach(ev=>dz.addEventListener(ev,e=>{e.preventDefault();dz.classList.add('over')}));
['dragleave','drop'].forEach(ev=>dz.addEventListener(ev,e=>{e.preventDefault();dz.classList.remove('over')}));
dz.addEventListener('drop',async e=>{$('#upinfo').textContent='يُفحص ما سحبتَه…';uploadAll(await collect(e.dataTransfer))});
['dragover','drop'].forEach(ev=>document.addEventListener(ev,e=>{if(!e.target.closest||!e.target.closest('#dz,#adz'))e.preventDefault()}));
$('#pickfiles').onclick=()=>$('#fileinp').click();
$('#fileinp').onchange=e=>uploadAll([...e.target.files].map(f=>({file:f,rel:f.name})));
$('#pickdir').onclick=async()=>{$('#pickdir').disabled=true;$('#upinfo').textContent='اختر المجلّد من النافذة التي ظهرت…';
  const r=await api('/api/pick-folder',null,{});$('#pickdir').disabled=false;
  if(r.cancelled){$('#upinfo').textContent='';return}if(r.error){$('#upinfo').textContent=r.error;return}
  $('#upinfo').textContent='أُضيف المجلّد. بدأت القراءة…';await api('/api/update',null,{});firstShown=true;pollProgress();show('search');toast('بدأت القراءة؛ ابحث فيما قُرئ')};
async function loadSources(){const r=await api('/api/progress');$('#srclist').innerHTML=r.sources&&r.sources.length?'<b>المجلّداتُ المضافة:</b><br>'+r.sources.map(esc).join('<br>'):''}

// ── مدقّق الإحالات
function vclass(v){v=v||'';if(v.startsWith('مطابق، والصفحة تخالف'))return 'v-warn';if(v.startsWith('مطابق'))return 'v-ok';if(v.startsWith('قريب'))return 'v-warn';
  if(v.startsWith('في كتاب')||v.startsWith('الكتاب ليس'))return 'v-alt';if(v.startsWith('لم يوجد'))return 'v-bad';if(v.startsWith('وُجد'))return 'v-ok';return 'v-gray'}
let AJOB=null,ARES=null;
const adz=$('#adz');
['dragenter','dragover'].forEach(ev=>adz.addEventListener(ev,e=>{e.preventDefault();adz.style.background='var(--mark)'}));
['dragleave','drop'].forEach(ev=>adz.addEventListener(ev,e=>{e.preventDefault();adz.style.background=''}));
adz.addEventListener('drop',e=>{const f=[...e.dataTransfer.files].find(x=>x.name.toLowerCase().endsWith('.docx'));f?auditFile(f):toast('اسحب ملفَّ وورد بامتداد docx')});
$('#apick').onclick=()=>$('#ainp').click();$('#ainp').onchange=e=>e.target.files[0]&&auditFile(e.target.files[0]);
async function auditFile(f){
  if(!PG||!PG.books_total){toast('أضف كتبًا أوّلًا ثمّ دقّق');return}
  $('#ares').innerHTML='';$('#aprog').innerHTML='<div class="wait">يُرفع الملفّ…</div>';
  const u=await (await fetch('/api/tadqiq/upload?rel='+encodeURIComponent(f.name),{method:'PUT',body:f})).json();
  if(u.error||u.skipped){$('#aprog').innerHTML='<div class="err">تعذّر رفعُ الملفّ.</div>';return}
  const s=await api('/api/tadqiq/start',null,{file:f.name});if(s.error){$('#aprog').innerHTML='<div class="err">'+esc(s.error)+'</div>';return}
  AJOB=s.id;pollAudit();
}
async function pollAudit(){
  const r=await api('/api/tadqiq/job',{id:AJOB});
  if(r.error){$('#aprog').innerHTML='<div class="err">'+esc(r.error)+'</div>';return}
  if(r.state=='error'){$('#aprog').innerHTML='<div class="err">'+esc(r.error)+'</div>';return}
  if(r.state=='running'){const p=r.total?Math.round(100*r.done/r.total):0;
    $('#aprog').innerHTML='<div class="box2">يُدقَّق… '+(r.total?AR(r.done)+' من '+AR(r.total)+' نقلًا':'يُستخرج النصّ')+'<div class="prog"><i style="width:'+p+'%"></i></div></div>';
    setTimeout(pollAudit,1200);return}
  $('#aprog').innerHTML='';ARES=r.result;drawAudit();
}
function drawAudit(filter){
  const R=ARES,items=R.items||[];const counts={};items.forEach(i=>counts[i.verdict]=(counts[i.verdict]||0)+1);
  const chips=Object.entries(counts).map(([k,v])=>'<span class="v '+vclass(k)+'" style="cursor:pointer;margin:2px" data-vf="'+esc(k)+'">'+esc(k)+' '+AR(v)+'</span>').join('');
  const rows=items.map((it,i)=>({it,i})).filter(x=>!filter||x.it.verdict==filter);
  $('#ares').innerHTML='<div class="box2"><b>«'+esc(R.name||'')+'»</b> — '+AR(items.length)+' إحالة<div class="help">'+esc(R.coverage||'')+'</div><div>'+chips+(filter?' <span class="lnk" id="vall">الكلّ</span>':'')+'</div>'+
   '<div class="acts" style="margin-top:6px"><button class="btn" id="axl">صدّر إلى إكسل</button></div></div>'+
   '<div class="box2" style="overflow:auto"><table><thead><tr><th>م</th><th>الحكم</th><th>النقل</th><th>الحاشية</th><th>موضعه في مكتبتك</th><th></th></tr></thead><tbody>'+
   rows.map(({it,i})=>{const f=it.found||{},n=it.nearest||{};const bk=f.book||n.book,pg=f.page||n.page;
     return '<tr><td class="n">'+AR(i+1)+'</td><td><span class="v '+vclass(it.verdict)+'">'+esc(it.verdict)+'</span>'+(it.ocr?'<br><span class="tag ocr">قراءةٌ آليّة</span>':'')+'</td><td>'+esc((it.quote||'').slice(0,220))+((it.quote||'').length>220?' …':'')+(it.diff?'<br><span class="muted" style="font-size:13px">الفروق: '+esc(it.diff)+'</span>':'')+'</td>'+
      '<td>'+esc(it.note&&it.note.text||'')+'</td><td>'+(f.cite?esc(f.cite):(n.near?'<span class="muted">أقربُ ما وُجد: '+esc(String(n.near).slice(0,90))+'</span>':'—'))+'</td>'+
      '<td>'+(bk?'<button class="btn2" data-op="'+bk+','+pg+','+i+'">افتح الصفحة وصورتها</button>':'')+'</td></tr>'}).join('')+'</tbody></table></div>';
  document.querySelectorAll('[data-vf]').forEach(a=>a.onclick=()=>drawAudit(a.dataset.vf));if($('#vall'))$('#vall').onclick=()=>drawAudit();
  document.querySelectorAll('[data-op]').forEach(b=>b.onclick=()=>{const [bk,pg,i]=b.dataset.op.split(',');S.q=(items[+i].quote||'').slice(0,80);S.mode='phrase';openPage(+bk,+pg,true)});
  $('#axl').onclick=async()=>{const x=await api('/api/tadqiq/xlsx',{id:AJOB});if(x.error){toast(x.error);return}toast('حُفظ في التنزيلات: '+x.name)};
}
$('#exopen').onclick=async()=>{const b=$('#exbox');if(b.style.display=='block'){b.style.display='none';return}b.style.display='block';EX=await api('/api/exclusions');drawEx()};
let EX=[];
function drawEx(){const f=$('#exf').value.trim();$('#exlist').innerHTML=EX.filter(b=>!f||b.title.includes(f)).map(b=>'<label class="bk"><input type="checkbox" data-eb="'+b.id+'" '+(b.own?'checked':'')+'> <span class="t">'+esc(b.title)+'</span></label>').join('')||'<div class="muted">لا كتبَ.</div>';
  $('#exlist').querySelectorAll('input').forEach(c=>c.onchange=()=>{EX.find(x=>x.id==c.dataset.eb).own=c.checked})}
$('#exf').oninput=drawEx;
$('#exsave').onclick=async()=>{const r=await api('/api/exclusions',null,{ids:EX.filter(x=>x.own).map(x=>x.id)});toast(r.error||'حُفظت ✓')};
async function updCheck(manual){
  const r=await api('/api/update-check',{});
  const res=$('#updres');
  if(!r.ok){if(manual)res.textContent=r.reason||'تعذّر.';return}
  if(!r.newer){if(manual)res.textContent='لديك آخرُ إصدار ('+AR(r.current).replace(/\./g,'٫')+').';return}
  const msg='إصدارٌ جديد من «بُغية» متاح ('+AR(r.latest).replace(/\./g,'٫')+').';
  if(manual)res.textContent=msg;
  const b=$('#updbar');b.style.display='block';
  b.innerHTML=esc(msg)+' نزّل ملفَّ التنصيب ثمّ شغّله، فيُنصَّب فوق هذا، وتبقى كتبُك ومكتبتُك كما هي. '+(r.url?'<button class="btn2" id="updget">نزّله</button> ':'')+'<button class="btn2" id="updno">لاحقًا</button>';
  if(r.url)$('#updget').onclick=()=>api('/api/open-update',null,{url:r.url});
  $('#updno').onclick=()=>{b.style.display='none'};
}
$('#updchk').onclick=()=>{$('#updres').textContent='…';updCheck(true)};
try{const k='bughya-updchk',t=+localStorage.getItem(k)||0;if(Date.now()-t>864e5){localStorage.setItem(k,Date.now());setTimeout(()=>updCheck(false),4000)}}catch(e){}
const ab=$('#about');$('#abt').onclick=()=>{ab.classList.add('on');$('#abtx').focus()};$('#abtx').onclick=()=>ab.classList.remove('on');
$('#unins').onclick=()=>{$('#uninsq').style.display='block';$('#unins').style.display='none'};
$('#uninsn').onclick=()=>{$('#uninsq').style.display='none';$('#unins').style.display=''};
$('#uninsy').onclick=async()=>{const r=await api('/api/uninstall',null,{});
  if(r.error){toast(r.error);return}$('#uninsq').textContent='يُفتح مُزيلُ التنصيب، وتُغلق «بُغية» الآن…'};
ab.onclick=e=>{if(e.target==ab)ab.classList.remove('on')};document.addEventListener('keydown',e=>{if(e.key=='Escape')ab.classList.remove('on')});
pollProgress();
</script><script>document.querySelectorAll('header nav button').forEach(b=>{const s=document.getElementById('p-'+b.dataset.p);if(!s||b.dataset.p=='welcome')return;const h=document.createElement('h2');h.className='ptl';h.textContent=b.textContent;(s.querySelector('.wrap')||s.querySelector('.bar')||s).prepend(h)});</script>
</body></html>"""


if __name__ == "__main__":
    sys.exit(main())
