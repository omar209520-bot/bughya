"""قارئُ ملفّات المكاتب: وورد (docx)، وأوبن أوفيس (odt)، والنصّ المنسَّق (rtf)، ووورد القديم (doc، في الماك وحده).

الصفحات: وورد يحفظ في الملفّ مواضعَ صفحاته كما رسمها آخرَ مرّة، وأوبن أوفيس مثلُه؛ فإن وُجدت فالوحدةُ «صفحة»
(تقريبيّة: قد يرسمها جهازٌ آخر بغير ذلك)، وإلّا فالوحدةُ «قطعة». والحواشي تُحفظ حاشيةً لصفحتها، ومكانُها في المتن رقمُها.
"""
import pathlib
import re
import subprocess
import sys
import zipfile
import xml.etree.ElementTree as ET

import arabic
from readers import ListBook, ReaderError, chunk, make_page

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
MC = "{http://schemas.openxmlformats.org/markup-compatibility/2006}"
DC = "{http://purl.org/dc/elements/1.1/}"
T = "{urn:oasis:names:tc:opendocument:xmlns:text:1.0}"
OFFICE = "{urn:oasis:names:tc:opendocument:xmlns:office:1.0}"


def _meta_ok(v: str) -> str:
    v = (v or "").strip()
    if not (3 <= len(v) <= 300):
        return ""
    q = arabic.quality(v)
    return arabic.clean_raw(v) if q["letters"] >= 3 and q["arabic"] >= 0.4 else ""


class _Pager:
    """يجمع الفقرات صفحاتٍ، ويبدأ صفحةً عند كلّ فاصل صفحة (ولا يصنع صفحةً فارغةً من فاصلين متتاليين)."""

    def __init__(self):
        self.pages = [{"body": [], "foot": []}]
        self.buf = []
        self.breaks = 0

    def text(self, s: str) -> None:
        self.buf.append(s)

    def end_para(self) -> None:
        t = "".join(self.buf).strip()
        self.buf = []
        if t:
            self.pages[-1]["body"].append(t)

    def page_break(self) -> None:
        part = "".join(self.buf).strip()
        self.buf = []
        if part:
            self.pages[-1]["body"].append(part)
        if self.pages[-1]["body"] or self.pages[-1]["foot"]:
            self.pages.append({"body": [], "foot": []})
            self.breaks += 1

    def foot(self, s: str) -> None:
        self.pages[-1]["foot"].append(s)

    def done(self):
        self.end_para()
        for p in self.pages:
            p["body"] = [arabic.clean_raw(x) for x in p["body"]]
            p["foot"] = [arabic.clean_raw(x) for x in p["foot"]]
        return [p for p in self.pages if p["body"] or p["foot"]]


def _book(kind: str, pager: _Pager, heads_by_page: dict, title: str, author: str,
          paras_flat: list, heads_flat: dict) -> ListBook:
    pages = pager.done()
    if pager.breaks >= 1 and len(pages) >= 2:
        out = [make_page(i + 1, "\n".join(p["body"]), "\n".join(p["foot"]), method=kind) for i, p in enumerate(pages)]
        toc = [(lvl, t, pg) for pg, items in sorted(heads_by_page.items()) for lvl, t in items]
        return ListBook(kind, "صفحة", out, title, author, toc, approx=True)
    # بلا مواضع صفحات: قطع، وكلُّ حاشيةٍ مع القطعة التي فيها رقمُها (بالترتيب، فلا تذهب أرقامٌ مكرّرةٌ إلى أوّل قطعة)
    chunks, toc = chunk(paras_flat, heads_flat)
    out = [make_page(i + 1, c, method=kind) for i, c in enumerate(chunks)]
    pos = 0
    for f in (f for p in pages for f in p["foot"]):
        m = re.match(r"\((\d+)\)", f)
        k = None
        if m and out:
            mark = "(%s)" % m.group(1)
            k = next((j for j in range(pos, len(out)) if mark in out[j]["body"]), None)
        if k is None:
            k = min(pos, len(out) - 1) if out else None
        if k is not None:
            out[k]["foot"] = (out[k]["foot"] + "\n" + f).strip()
            pos = k
    return ListBook(kind, "قطعة", out, title, author, toc)


# ───────────────────────── وورد (docx) ─────────────────────────

def _docx_notes(z: zipfile.ZipFile, part: str, tag: str) -> dict:
    notes = {}
    if part not in z.namelist():
        return notes
    root = ET.fromstring(z.read(part))
    for n in root.iter(W + tag):
        if n.get(W + "type") in ("separator", "continuationSeparator", "continuationNotice"):
            continue
        paras = ["".join((t.text or "") for t in p.iter(W + "t")).strip() for p in n.iter(W + "p")]
        notes[n.get(W + "id")] = " ".join(x for x in paras if x)
    return notes


def _docx_styles(z: zipfile.ZipFile) -> dict:
    levels = {}
    if "word/styles.xml" not in z.namelist():
        return levels
    root = ET.fromstring(z.read("word/styles.xml"))
    for s in root.iter(W + "style"):
        sid = s.get(W + "styleId")
        lvl = s.find(W + "pPr/" + W + "outlineLvl")
        name = s.find(W + "name")
        name = (name.get(W + "val") if name is not None else "") or ""
        if lvl is not None and (lvl.get(W + "val") or "").isdigit() and int(lvl.get(W + "val")) < 9:
            levels[sid] = int(lvl.get(W + "val")) + 1
        else:
            m = re.match(r"(?i)heading\s*(\d)", name) or re.match(r"(?i)heading(\d)", sid or "")
            if m:
                levels[sid] = int(m.group(1))
    return levels


def _docx(path: pathlib.Path) -> ListBook:
    try:
        z = zipfile.ZipFile(path)
        root = ET.fromstring(z.read("word/document.xml"))
    except (zipfile.BadZipFile, KeyError, ET.ParseError) as e:
        raise ReaderError("ملفُّ وورد تالفٌ أو غيرُ مفهوم: %s" % e)
    foots = _docx_notes(z, "word/footnotes.xml", "footnote")
    ends = _docx_notes(z, "word/endnotes.xml", "endnote")
    styles = _docx_styles(z)
    restart = root.find(".//" + W + "footnotePr/" + W + "numRestart")
    per_page = restart is not None and restart.get(W + "val") == "eachPage"
    skip = set()
    for fb in root.iter(MC + "Fallback"):          # النسخةُ البديلة لمربّعات النصّ تكرّر نصَّها
        skip.update(id(p) for p in fb.iter(W + "p"))
    pager = _Pager()
    heads_by_page, heads_flat, paras_flat = {}, {}, []
    counter = [0]

    def new_page():
        pager.page_break()
        if per_page:
            counter[0] = 0

    def walk(el, parts):
        for ch in el:
            tag = ch.tag
            if tag in (W + "p", W + "drawing", W + "pict", W + "del", W + "rPr", W + "pPr", W + "instrText",
                       MC + "Fallback"):
                continue
            if tag == W + "t":
                pager.text(ch.text or "")
                parts.append(ch.text or "")
            elif tag == W + "tab":
                pager.text(" ")
                parts.append(" ")
            elif tag in (W + "br", W + "cr"):
                if ch.get(W + "type") == "page":
                    new_page()
                else:
                    pager.text("\n")
                    parts.append("\n")
            elif tag == W + "lastRenderedPageBreak":
                new_page()
            elif tag in (W + "footnoteReference", W + "endnoteReference"):
                counter[0] += 1
                mark = "(%d)" % counter[0]
                pager.text(mark)
                parts.append(mark)
                note = (foots if tag == W + "footnoteReference" else ends).get(ch.get(W + "id"), "")
                pager.foot("%s %s" % (mark, note))
            else:
                walk(ch, parts)

    body = root.find(W + "body")
    for p in (body.iter(W + "p") if body is not None else []):
        if id(p) in skip:
            continue
        parts = []
        walk(p, parts)
        text = arabic.clean_raw("".join(parts))
        style = p.find(W + "pPr/" + W + "pStyle")
        lvl = styles.get(style.get(W + "val")) if style is not None else None
        own = p.find(W + "pPr/" + W + "outlineLvl")
        if own is not None and (own.get(W + "val") or "").isdigit() and int(own.get(W + "val")) < 9:
            lvl = int(own.get(W + "val")) + 1
        if lvl and text:
            heads_by_page.setdefault(len(pager.pages), []).append((lvl, text))
            heads_flat[len(paras_flat)] = (lvl, text)
        if text:
            paras_flat.append(text)
        pager.end_para()
    title = author = ""
    if "docProps/core.xml" in z.namelist():
        core = ET.fromstring(z.read("docProps/core.xml"))
        t, a = core.find(DC + "title"), core.find(DC + "creator")
        title = _meta_ok(t.text if t is not None else "")
        author = _meta_ok(a.text if a is not None else "")
    book = _book("docx", pager, heads_by_page, title, "", paras_flat, heads_flat)
    book.hints = {"title": title, "author": author}     # كاتبُ ملفّ وورد في بياناته ناسخُه غالبًا: تلميحٌ لا مؤلّف
    return book


# ───────────────────────── أوبن أوفيس (odt) ─────────────────────────

def _odt(path: pathlib.Path) -> ListBook:
    try:
        z = zipfile.ZipFile(path)
        root = ET.fromstring(z.read("content.xml"))
    except (zipfile.BadZipFile, KeyError, ET.ParseError) as e:
        raise ReaderError("ملفُّ أوبن أوفيس تالفٌ أو غيرُ مفهوم: %s" % e)
    pager = _Pager()
    heads_by_page, heads_flat, paras_flat = {}, {}, []

    def inline(el, parts):
        if el.text:
            parts.append(el.text)
        for ch in el:
            tag = ch.tag
            if tag == T + "s":
                parts.append(" " * int(ch.get(T + "c", "1") or 1))
            elif tag == T + "tab":
                parts.append(" ")
            elif tag == T + "line-break":
                parts.append("\n")
            elif tag == T + "soft-page-break":
                parts.append("\x0c")
            elif tag == T + "note":
                cit = ch.find(T + "note-citation")
                mark = "(%s)" % ((cit.text or "").strip() if cit is not None else "*")
                parts.append(mark)
                nb = ch.find(T + "note-body")
                note = " ".join("".join(p.itertext()).strip() for p in (nb.iter(T + "p") if nb is not None else []))
                pager.foot("%s %s" % (mark, note.strip()))
            else:
                inline(ch, parts)
            if ch.tail:
                parts.append(ch.tail)

    def para(el):
        parts = []
        inline(el, parts)
        raw = "".join(parts)
        for k, seg in enumerate(raw.split("\x0c")):
            if k > 0:
                pager.page_break()
            pager.text(seg)
        text = arabic.clean_raw(raw.replace("\x0c", " "))
        if el.tag == T + "h" and text:
            lvl = int(el.get(T + "outline-level", "1") or 1)
            heads_by_page.setdefault(len(pager.pages), []).append((lvl, text))
            heads_flat[len(paras_flat)] = (lvl, text)
        if text:
            paras_flat.append(text)
        pager.end_para()

    def block(el):
        for ch in el:
            if ch.tag in (T + "p", T + "h"):
                para(ch)
            elif ch.tag == T + "soft-page-break":
                pager.page_break()
            elif ch.tag in (T + "tracked-changes", T + "sequence-decls"):
                continue
            else:
                block(ch)

    body = root.find(".//" + OFFICE + "text")
    if body is not None:
        block(body)
    return _book("odt", pager, heads_by_page, "", "", paras_flat, heads_flat)


# ───────────────────────── النصّ المنسَّق (rtf) ─────────────────────────

_CHARSET_CP = {0: "cp1252", 161: "cp1253", 162: "cp1254", 177: "cp1255", 178: "cp1256", 186: "cp1257",
               204: "cp1251", 222: "cp874", 238: "cp1250", 128: "cp932", 134: "gbk", 136: "big5", 129: "cp949"}
_SKIP_DEST = {"colortbl", "stylesheet", "info", "pict", "object", "header", "footer", "headerl", "headerr",
              "headerf", "footerl", "footerr", "footerf", "themedata", "colorschememapping", "datastore",
              "latentstyles", "listtable", "listoverridetable", "rsidtbl", "generator", "xmlnstbl", "mmathPr",
              "fldinst", "filetbl", "revtbl", "pgdsctbl", "private", "nonshppict", "shp", "blipuid"}
_RTF_TOKEN = re.compile(r"\\([a-zA-Z]+)(-?\d+)? ?|\\'([0-9a-fA-F]{2})|\\(.)|([{}])|([^\\{}\r\n]+)|[\r\n]+", re.S)
_SPECIAL = {"par": "\n", "line": "\n", "sect": "\n", "row": "\n", "cell": " ", "tab": " ", "emdash": "—",
            "endash": "–", "lquote": "‘", "rquote": "’", "ldblquote": "“", "rdblquote": "”", "bullet": "•"}


def rtf_pages(data: bytes) -> list:
    """نصُّ ملفّ rtf صفحاتٍ (بفواصل الصفحات الصريحة فيه، إن وُجدت). يقرأ \\uN و\\'hh بخريطة حروف الخطّ."""
    s = data.decode("latin-1")
    m = re.search(r"\\ansicpg(\d+)", s[:4000])
    ansi = "cp" + m.group(1) if m else "cp1252"
    fonts, pages, out = {}, [], []
    st = {"skip": False, "uc": 1, "cp": ansi, "fonttbl": False, "font": None}
    stack, pend, ucskip = [], bytearray(), 0

    def flush_bytes():
        if pend:
            try:
                out.append(bytes(pend).decode(st["cp"], "replace"))
            except LookupError:
                out.append(bytes(pend).decode(ansi, "replace"))
            pend.clear()

    for mt in _RTF_TOKEN.finditer(s):
        word, arg, hexb, sym, brace, text = mt.groups()
        if brace:
            flush_bytes()
            ucskip = 0
            if brace == "{":
                stack.append(dict(st))
            elif stack:
                st = stack.pop()
            continue
        if ucskip:                         # بعد \uN يُتخطّى بديلُه القديم (حرفٌ أو \'hh)
            if text:
                k = min(ucskip, len(text))
                ucskip -= k
                text = text[k:]
                if not text:
                    continue
            elif hexb or sym:
                ucskip -= 1
                continue
            elif word:
                ucskip = 0
        if word:
            if st["fonttbl"]:
                if word == "f" and arg is not None:
                    st["font"] = int(arg)
                elif word == "fcharset" and arg is not None and st["font"] is not None:
                    fonts[st["font"]] = _CHARSET_CP.get(int(arg), ansi)
                continue
            if word == "fonttbl":
                st["fonttbl"] = True
                continue
            if word in _SKIP_DEST:
                st["skip"] = True
                continue
            if st["skip"]:
                continue
            if word == "u" and arg is not None:
                flush_bytes()
                v = int(arg)
                out.append(chr(v + 65536 if v < 0 else v))
                ucskip = st["uc"]
            elif word == "uc" and arg is not None:
                st["uc"] = int(arg)
            elif word == "f" and arg is not None:
                flush_bytes()
                st["cp"] = fonts.get(int(arg), ansi)
            elif word == "page":
                flush_bytes()
                pages.append("".join(out))
                out = []
            elif word in _SPECIAL:
                flush_bytes()
                out.append(_SPECIAL[word])
            continue
        if st["skip"] or st["fonttbl"]:
            continue
        if hexb:
            pend.append(int(hexb, 16))
            continue
        flush_bytes()
        if sym:
            if sym == "*":
                st["skip"] = True
            elif sym in "\\{}":
                out.append(sym)
            elif sym == "~":
                out.append(" ")
            elif sym == "_":
                out.append("-")
            elif sym in "\r\n":
                out.append("\n")
            continue
        if text:
            out.append(text)
    flush_bytes()
    pages.append("".join(out))
    return [p for p in pages if p.strip()] or [""]


def _rtf(path: pathlib.Path) -> ListBook:
    try:
        pages = rtf_pages(path.read_bytes())
    except Exception as e:
        raise ReaderError("تعذّرت قراءةُ ملفّ rtf: %s" % e)
    if len(pages) >= 2:
        out = [make_page(i + 1, arabic.clean_raw(p), method="rtf") for i, p in enumerate(pages)]
        return ListBook("rtf", "صفحة", out, approx=True)
    chunks, toc = chunk([arabic.clean_raw(x) for x in pages[0].split("\n")])
    return ListBook("rtf", "قطعة", [make_page(i + 1, c, method="rtf") for i, c in enumerate(chunks)], toc=toc)


# ───────────────────────── وورد القديم (doc) ─────────────────────────

_WORD_PS = r"""
$ErrorActionPreference = 'Stop'
$w = New-Object -ComObject Word.Application
$w.Visible = $false; $w.DisplayAlerts = 0
try {
  $d = $w.Documents.Open($env:WATAD_SRC, $false, $true, $false)
  $d.Repaginate(); [void]$d.ComputeStatistics(2)
  $d.SaveAs2($env:WATAD_DST, 16)
  $d.Close($false)
} finally { $w.Quit() }
"""


def _doc_via_word(path: pathlib.Path) -> ListBook:
    """ويندوز: يحوّله برنامجُ وورد المنصَّب إلى docx في مخزن النصّ (لا يُمسّ الأصل)، ثمّ يُقرأ كالـdocx."""
    import hashlib
    import os
    import common
    cache = common.STORE_DIR / ".doc-cache"
    cache.mkdir(parents=True, exist_ok=True)
    st = path.stat()
    dst = cache / (hashlib.sha1(("%s|%d|%d" % (path, st.st_size, int(st.st_mtime))).encode("utf-8")).hexdigest() + ".docx")
    if not dst.exists():
        env = dict(os.environ, WATAD_SRC=str(path), WATAD_DST=str(dst))
        p = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", _WORD_PS], env=env,
                           capture_output=True, timeout=300, creationflags=0x08000000)
        if p.returncode != 0 or not dst.exists():
            raise ReaderError("صيغةُ وورد القديمة (doc) تحتاج برنامجَ وورد لتُقرأ في ويندوز، وتعذّر تحويلُها: "
                              + p.stderr.decode("utf-8", "replace")[-200:].strip())
    book = _docx(dst)
    book.kind = "doc"
    return book


def _doc(path: pathlib.Path) -> ListBook:
    if sys.platform == "win32":
        return _doc_via_word(path)
    if sys.platform != "darwin":
        raise ReaderError("صيغةُ وورد القديمة (doc) لا تُقرأ هنا: افتحه في وورد واحفظه بصيغة docx.")
    p = subprocess.run(["/usr/bin/textutil", "-convert", "txt", "-stdout", "-encoding", "UTF-8", str(path)],
                       capture_output=True)
    if p.returncode != 0:
        raise ReaderError("تعذّرت قراءةُ ملفّ doc: " + p.stderr.decode("utf-8", "replace")[-300:])
    chunks, toc = chunk([arabic.clean_raw(x) for x in p.stdout.decode("utf-8", "replace").split("\n")])
    return ListBook("doc", "قطعة", [make_page(i + 1, c, method="doc") for i, c in enumerate(chunks)], toc=toc)


def open_office(path: pathlib.Path, kind: str) -> ListBook:
    return {"docx": _docx, "odt": _odt, "rtf": _rtf, "doc": _doc}[kind](path)
