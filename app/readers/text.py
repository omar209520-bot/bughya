"""قارئُ النصوص: الملفّاتُ النصّيّة (txt وmd)، وصفحاتُ الويب (html)، والكتبُ الإلكترونيّة (epub).

الملفُّ النصّيّ: يُكشف ترميزُه (يونيكود، أو عربيّة ويندوز القديمة 1256 وهي شائعةٌ في الملفّات العربيّة القديمة).
فإن كان فيه علامةُ فصل الصفحات (\\f، يكتبها برنامجُ تحويل بي دي إف إلى نصّ) فالوحدةُ «صفحة»، وإلّا «قطعة».

الكتابُ الإلكترونيّ: إن كان مصدَّرًا من المكتبة الشاملة (في ذيل كلّ صفحةٍ «الجزء: ٢ ¦ الصفحة: ٥٣٧») قُرئ صفحاتٍ بجزئها
ورقمها المطبوع، وحواشيه حاشية، وعناوينُه من فهرسه؛ وإلّا فقطعٌ من نحو ٣٥٠ كلمة.
"""
import pathlib
import posixpath
import re
import zipfile
import xml.etree.ElementTree as ET
from html.parser import HTMLParser

import arabic
from readers import ListBook, ReaderError, chunk, make_page


def decode(data: bytes) -> str:
    if data.startswith(b"\xef\xbb\xbf"):
        return data[3:].decode("utf-8", "replace")
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16", "replace")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        pass
    head = data[:4000]
    if head.count(b"\x00") > len(head) // 4:
        for enc in ("utf-16-le", "utf-16-be"):
            try:
                return data.decode(enc)
            except UnicodeDecodeError:
                continue
    return data.decode("cp1256", "replace")


def _txt(path: pathlib.Path) -> ListBook:
    text = decode(path.read_bytes()).replace("\r\n", "\n").replace("\r", "\n")
    parts = text.split("\f")
    if len([p for p in parts if p.strip()]) >= 2:
        pages = [make_page(i + 1, arabic.clean_raw(p), method="txt") for i, p in enumerate(parts)]
        return ListBook("txt", "صفحة", pages, approx=True)
    blocks = re.split(r"\n\s*\n", text) if re.search(r"\n\s*\n", text) else text.split("\n")
    chunks, toc = chunk([arabic.clean_raw(b.replace("\n", " ")) for b in blocks])
    return ListBook("txt", "قطعة", [make_page(i + 1, c, method="txt") for i, c in enumerate(chunks)], toc=toc)


# ───────────────────────── صفحاتُ الويب ─────────────────────────

_BLOCK = {"p", "div", "br", "li", "tr", "blockquote", "pre", "section", "article", "h1", "h2", "h3", "h4", "h5",
          "h6", "dt", "dd", "table", "hr", "figcaption", "header", "footer", "td", "th"}
_SKIP = {"script", "style", "noscript", "svg", "template"}
_BLOCK_CLASSES = {"title", "info-item", "center", "footnote", "footnote-hr"}
_FOOTER = re.compile(r"^(?:الجزء\s*:\s*([0-9٠-٩]+)\s*¦\s*)?الصفحة\s*:\s*([0-9٠-٩]+)$")
_DIG = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")


class _Html(HTMLParser):
    """فقراتُ المتن وفقراتُ الحاشية وعناوينُ الصفحة وذيلُها («الجزء: … ¦ الصفحة: …»)."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.paras, self.foot, self.heads = [], [], {}
        self.buf, self.stack = [], []
        self.skip = self.in_foot = 0
        self.head_level, self.title, self.in_title = None, "", False
        self.footer = None

    def _flush(self):
        t = re.sub(r"\s+", " ", "".join(self.buf)).strip()
        self.buf = []
        if not t:
            return
        m = _FOOTER.match(t)
        if m:
            self.footer = (int(m.group(1).translate(_DIG)) if m.group(1) else None, int(m.group(2).translate(_DIG)))
            return
        if self.in_foot:
            self.foot.append(t)
            return
        if self.head_level:
            self.heads[len(self.paras)] = (self.head_level, t)
        self.paras.append(t)

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        cls = set((a.get("class") or "").split())
        foot = ("footnote" in cls) or (tag == "aside" and (a.get("epub:type") or "") in ("footnote", "endnote",
                                                                                       "rearnote"))
        heading = re.fullmatch(r"h[1-6]", tag) or "title" in cls
        block = tag in _BLOCK or bool(cls & _BLOCK_CLASSES) or foot
        if tag in ("br", "hr", "img", "meta", "link", "input"):      # عناصرُ لا تُغلق
            if tag in ("br", "hr"):
                self._flush()
            return
        self.stack.append((tag, foot, heading, block))
        if tag in _SKIP:
            self.skip += 1
            return
        if tag == "title":
            self.in_title = True
            return
        if block:
            self._flush()
        if foot:
            self.in_foot += 1
        if heading:
            self.head_level = int(tag[1]) if tag.startswith("h") and tag[1:].isdigit() else 1

    def handle_endtag(self, tag):
        if tag in ("br", "hr", "img", "meta", "link", "input"):
            return
        while self.stack:                      # يُغلق أقربُ عنصرٍ بهذا الاسم (ويُعفى عن الإغلاق الناقص)
            t, foot, heading, block = self.stack.pop()
            if t in _SKIP:
                self.skip = max(0, self.skip - 1)
            elif t == "title":
                self.in_title = False
            else:
                if block or heading:
                    self._flush()
                if foot:
                    self.in_foot = max(0, self.in_foot - 1)
                if heading:
                    self.head_level = None
            if t == tag:
                break

    def handle_data(self, data):
        if self.in_title:
            self.title += data
        elif not self.skip:
            self.buf.append(data)

    def close(self):
        super().close()
        self._flush()


def parse_html(markup: str) -> dict:
    p = _Html()
    p.feed(markup)
    p.close()
    return {"paras": [arabic.clean_raw(x) for x in p.paras], "foot": [arabic.clean_raw(x) for x in p.foot],
            "heads": p.heads, "title": arabic.clean_raw(p.title), "footer": p.footer}


def _ok(v: str) -> str:
    return v if v and arabic.quality(v)["arabic"] >= 0.4 else ""


def _html(path: pathlib.Path) -> ListBook:
    raw = path.read_bytes()
    m = re.search(rb"charset=[\"']?([A-Za-z0-9_\-]+)", raw[:3000])
    try:
        markup = raw.decode(m.group(1).decode("ascii")) if m else decode(raw)
    except (LookupError, UnicodeDecodeError):
        markup = decode(raw)
    d = parse_html(markup)
    chunks, toc = chunk(d["paras"], d["heads"])
    pages = [make_page(i + 1, c, method="html") for i, c in enumerate(chunks)]
    if pages and d["foot"]:
        pages[-1]["foot"] = "\n".join(d["foot"])
    return ListBook("html", "قطعة", pages, _ok(d["title"]), "", toc)


# ───────────────────────── الكتبُ الإلكترونيّة (epub) ─────────────────────────

def _ncx_toc(z, opf_dir: str, opf) -> list:
    """فهرسُ الكتاب الإلكترونيّ: [(المستوى، العنوان، الملفّ)] من toc.ncx أو من nav.xhtml."""
    out = []
    ncx = next((e.get("href") for e in opf.iter() if e.tag.endswith("}item")
                and e.get("media-type") == "application/x-dtbncx+xml"), None)
    if ncx:
        try:
            root = ET.fromstring(z.read(posixpath.normpath(posixpath.join(opf_dir, ncx))))

            def walk(el, lvl):
                for np in el:
                    if not np.tag.endswith("}navPoint"):
                        continue
                    label = next((t.text for t in np.iter() if t.tag.endswith("}text")), "") or ""
                    src = next((c.get("src") for c in np if c.tag.endswith("}content")), "") or ""
                    ncx_dir = posixpath.dirname(posixpath.join(opf_dir, ncx))
                    out.append((lvl, arabic.clean_raw(label), posixpath.normpath(posixpath.join(ncx_dir, src.split("#")[0]))))
                    walk(np, lvl + 1)

            nav_map = next((e for e in root.iter() if e.tag.endswith("}navMap")), None)
            if nav_map is not None:
                walk(nav_map, 1)
        except (KeyError, ET.ParseError):
            out = []
    return out


def _epub(path: pathlib.Path) -> ListBook:
    try:
        z = zipfile.ZipFile(path)
        cont = ET.fromstring(z.read("META-INF/container.xml"))
        rootfile = next(e for e in cont.iter() if e.tag.endswith("rootfile")).get("full-path")
        opf = ET.fromstring(z.read(rootfile))
    except (zipfile.BadZipFile, KeyError, StopIteration, ET.ParseError) as e:
        raise ReaderError("كتابٌ إلكترونيٌّ تالفٌ أو غيرُ مفهوم: %s" % e)
    base = posixpath.dirname(rootfile)
    manifest = {e.get("id"): (e.get("href"), e.get("media-type", "")) for e in opf.iter() if e.tag.endswith("}item")}
    spine = [e.get("idref") for e in opf.iter() if e.tag.endswith("}itemref")]
    title = author = ""
    for e in opf.iter():
        if e.tag.endswith("}title") and not title:
            title = (e.text or "").strip()
        elif e.tag.endswith("}creator") and not author:
            author = (e.text or "").strip()
    items = []
    for idref in spine:
        href, mt = manifest.get(idref, (None, ""))
        if not href or "html" not in mt:
            continue
        name = posixpath.normpath(posixpath.join(base, href.split("#")[0]))
        try:
            d = parse_html(decode(z.read(name)))
        except KeyError:
            continue
        d["name"] = name
        items.append(d)
    ncx = _ncx_toc(z, base, opf)
    title, author = _ok(arabic.clean_raw(title)), _ok(arabic.clean_raw(author))
    paged = sum(1 for it in items if it["footer"]) >= max(1, len(items) // 2)
    if paged:        # مصدَّرٌ من الشاملة: كلُّ ملفٍّ صفحة، بجزئها ورقمها المطبوع
        pages, where, toc = [], {}, []
        for it in items:
            if not it["paras"] and not it["foot"]:
                continue
            n = len(pages) + 1
            vol, pg = it["footer"] or (None, None)
            pages.append(make_page(n, "\n".join(it["paras"]), "\n".join(it["foot"]), printed=pg, method="epub",
                                   vol=vol))
            where.setdefault(it["name"], n)
            if not ncx:
                toc += [(lvl, t, n) for _, (lvl, t) in sorted(it["heads"].items())]
        if ncx:
            toc = [(lvl, t, where[f]) for lvl, t, f in ncx if f in where]
        return ListBook("epub", "صفحة", pages, title, author, toc)
    paras, heads, feet = [], {}, []
    for it in items:
        for k, v in it["heads"].items():
            heads[len(paras) + k] = v
        paras.extend(it["paras"])
        feet.extend(it["foot"])
    chunks, toc = chunk(paras, heads)
    pages = [make_page(i + 1, c, method="epub") for i, c in enumerate(chunks)]
    for f in feet:             # الحاشيةُ مع القطعة التي فيها رقمُها
        m = re.match(r"\((\d+)\)", f)
        target = next((p for p in pages if m and "(%s)" % m.group(1) in p["body"]), pages[-1] if pages else None)
        if target is not None:
            target["foot"] = (target["foot"] + "\n" + f).strip()
    return ListBook("epub", "قطعة", pages, title, author, toc)


def open_text(path: pathlib.Path, kind: str) -> ListBook:
    return {"txt": _txt, "html": _html, "epub": _epub}[kind](path)
