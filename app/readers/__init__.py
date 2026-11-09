"""قرّاءُ الكتب: كلُّ صيغةٍ تُقرأ صفحاتٍ (أو قطعًا) بنصّها، ولكلّ صفحةٍ رأسٌ ومتنٌ وحاشية.

الواجهة:
    book = open_book(path, ocr)      ← كائنٌ فيه kind وunit («صفحة» أو «قطعة») وapprox وtotal وtitle وauthor وtoc
    for page in book.pages(start):   ← قاموسٌ لكلّ صفحة (انظر make_page)
    book.close()

الوحدة:
    «صفحة»   بي دي إف والصور: صفحةُ الملفّ نفسُها، ومعها رقمُها المطبوع إن قُرئ.
             ووورد إن حفظ فيه وورد مواضعَ صفحاته (approx=1: كما رسمها وورد آخرَ مرّة).
    «قطعة»   ما لا صفحاتِ له (النصوص، وصفحات الويب، والكتب الإلكترونيّة، ووورد بلا مواضع صفحات):
             نحو ٣٥٠ كلمة، لا تقطع فقرة.
"""
import pathlib

KINDS = {
    ".pdf": "pdf", ".xps": "pdf", ".oxps": "pdf", ".cbz": "pdf",
    ".png": "image", ".jpg": "image", ".jpeg": "image", ".tif": "image", ".tiff": "image",
    ".bmp": "image", ".gif": "image", ".webp": "image",
    ".docx": "docx", ".odt": "odt", ".rtf": "rtf", ".doc": "doc",
    ".txt": "txt", ".text": "txt", ".md": "txt",
    ".htm": "html", ".html": "html", ".xhtml": "html",
    ".epub": "epub",
}
UNSUPPORTED_HINT = {
    ".djvu": "صيغةُ دجافو لا تُقرأ هنا: حوّله إلى بي دي إف ثمّ ضعه في المجلّد.",
    ".djv": "صيغةُ دجافو لا تُقرأ هنا: حوّله إلى بي دي إف ثمّ ضعه في المجلّد.",
    ".mobi": "صيغةُ موبي لا تُقرأ هنا: حوّلها إلى إيبب أو بي دي إف.",
    ".azw3": "صيغةُ كندل لا تُقرأ هنا: حوّلها إلى إيبب أو بي دي إف.",
    ".pages": "ملفّاتُ «بيجز» لا تُقرأ هنا: صدّره من «بيجز» بصيغة وورد أو بي دي إف.",
    ".bok": "ملفّاتُ الشاملة القديمة لا تُقرأ هنا.",
}


class ReaderError(Exception):
    """تعذّرت قراءةُ الملفّ؛ ورسالتُه بالعربيّة تُعرض للمستخدم."""


def kind_of(path: pathlib.Path):
    return KINDS.get(path.suffix.lower())


def make_page(n: int, body: str = "", foot: str = "", head: str = "", printed=None, method: str = "text",
              conf=None, boxes=None, weak: bool = False, vol=None, catch=None) -> dict:
    return {"n": n, "body": body or "", "foot": foot or "", "head": head or "", "printed": printed,
            "method": method, "conf": conf, "boxes": boxes, "weak": weak, "vol": vol, "catch": catch}


class ListBook:
    """كتابٌ قُرئ كلُّه دفعةً واحدة (وورد والنصوص والكتب الإلكترونيّة)؛ صفحاتُه قائمةٌ جاهزة."""
    scanned_guess = False

    def __init__(self, kind: str, unit: str, pages: list, title: str = "", author: str = "", toc=None,
                 approx: bool = False):
        self.kind, self.unit, self.approx = kind, unit, approx
        self._pages = pages
        self.total = len(pages)
        self.title, self.author, self.toc = title or "", author or "", toc or []
        self.hints = {}

    def pages(self, start: int = 1):
        yield from self._pages[max(0, start - 1):]

    def close(self) -> None:
        pass


TARGET_WORDS = 350


def chunk(paras: list, heads: dict = None):
    """فقراتٌ ← قطعٌ من نحو ٣٥٠ كلمة لا تقطع فقرة (إلّا فقرةً أطولَ من ٧٠٠ كلمة فتُقسم على كلماتها).
    heads: {رقم الفقرة: (المستوى، العنوان)} ← يُعاد معها toc بأرقام القطع."""
    heads = heads or {}
    chunks, cur, words, toc = [], [], 0, []

    def flush():
        nonlocal cur, words
        if cur:
            chunks.append("\n".join(cur))
            cur, words = [], 0

    for i, p in enumerate(paras):
        p = p.strip()
        if not p:
            continue
        w = p.split()
        if i in heads and words >= TARGET_WORDS // 3:
            flush()                      # العنوانُ يبدأ قطعةً جديدة ما لم تكن القطعةُ الجاريةُ قصيرة
        if i in heads:
            toc.append((heads[i][0], heads[i][1], len(chunks) + 1))
        if len(w) > 2 * TARGET_WORDS:
            flush()
            for k in range(0, len(w), TARGET_WORDS):
                chunks.append(" ".join(w[k:k + TARGET_WORDS]))
            continue
        if cur and words + len(w) > TARGET_WORDS * 1.3:
            flush()
        cur.append(p)
        words += len(w)
        if words >= TARGET_WORDS:
            flush()
    flush()
    return chunks, toc


def open_book(path, ocr=None):
    path = pathlib.Path(path)
    kind = kind_of(path)
    if kind in ("pdf", "image"):
        from readers.pdf import PdfBook
        return PdfBook(path, kind, ocr)
    if kind in ("docx", "odt", "rtf", "doc"):
        from readers.office import open_office
        return open_office(path, kind)
    if kind in ("txt", "html", "epub"):
        from readers.text import open_text
        return open_text(path, kind)
    raise ReaderError(UNSUPPORTED_HINT.get(path.suffix.lower(), "صيغةٌ لا تُقرأ هنا: " + path.suffix))
