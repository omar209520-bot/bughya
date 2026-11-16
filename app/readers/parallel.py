"""القراءةُ الآليّة لكتابٍ مصوَّر بعدّة عمليّاتٍ معًا (ويندوز).

محرّكُ القراءة في ويندوز يقرأ الصفحةَ في نحو ثانيةٍ ويستعمل نواةً واحدة، والحاسوبُ فيه أربعٌ في العادة. فتُفتح عمليّاتٌ
كلٌّ منها تفتح الكتابَ وتقرأ صفحاتٍ منه (PdfBook.read نفسُها: التصويرُ ثمّ المحرّكُ ثمّ قسمةُ الصفحة)، وتُسلَّم الصفحاتُ
بترتيبها كما كانت. قيس على جهازٍ بأربع أنويةٍ حقيقيّة: الوقتُ ينزل إلى نحو النصف بأربع عمليّات، والنصُّ مطابقٌ صفحةً صفحة.

- العدد: نصفُ الأنوية المنطقيّة، وأقصاه أربع؛ ويُغيَّر بمتغيّر البيئة BUGHYA_OCR_WORKERS (١ يُبطلها).
- العمليّاتُ بأولويّةٍ دون العاديّة، فلا يثقل الجهازُ على صاحبه.
- لا يُطلب من الصفحات إلّا ما يسبق المقروءَ بقليل: فإن أُوقفت القراءةُ لم يَضِع إلّا صفحاتٌ معدودة، وتُستأنف من حيث حُفظ.
- إن تعذّر تشغيلُ العمليّات أو انكسرت في أثناء القراءة، أُكمل الكتابُ في العمليّة الواحدة كما كان.
وفي غير ويندوز عمليّةٌ واحدة: أداةُ الماك لم تُقَس هكذا.
"""
import collections
import os
import sys

ENV = "BUGHYA_OCR_WORKERS"
MAX_AUTO = 4
LOOKAHEAD = 2          # لكلّ عمليّةٍ صفحتان في الطابور على الأكثر
_BOOK = None


def workers() -> int:
    v = os.environ.get(ENV)
    if v:
        try:
            return max(1, min(16, int(v)))
        except ValueError:
            pass
    if sys.platform != "win32":
        return 1
    return max(1, min(MAX_AUTO, (os.cpu_count() or 1) // 2))


def _start(path: str, kind: str, preset: dict) -> None:
    """في كلّ عمليّة: تُفتح نسختُها من الكتاب بما قرّرته العمليّةُ الأمّ (فلا يُعاد فحصُ الكتاب)."""
    global _BOOK
    if sys.platform == "win32":
        try:
            import ctypes
            k = ctypes.windll.kernel32
            k.SetPriorityClass(k.GetCurrentProcess(), 0x00004000)       # دون العاديّة
        except Exception:
            pass
    from readers.ocr import engine
    from readers.pdf import PdfBook
    ocr = engine()
    if not ocr.ok:
        raise RuntimeError(ocr.reason)
    _BOOK = PdfBook(path, kind, ocr, preset=preset)


def _page(i: int) -> dict:
    return _BOOK.read(i)


def pages(book, start: int = 1):
    """صفحاتُ الكتاب من start بترتيبها، مقروءةً بعدّة عمليّات إن أمكن."""
    i, total, n = max(0, start - 1), book.total, workers()
    n = min(n, max(1, (total - i) // 2))            # الكتابُ القصير لا يستحقّ تشغيلَ العمليّات
    ex = None
    if n > 1:
        try:
            from concurrent.futures import ProcessPoolExecutor
            preset = {"scanned_guess": book.scanned_guess, "force_ocr": book.force_ocr, "bias": list(book.bias)}
            ex = ProcessPoolExecutor(n, initializer=_start, initargs=(book.path, book.kind, preset))
        except Exception:
            ex = None
    if ex is not None:
        pending, nxt = collections.deque(), i
        try:
            while i < total:
                while nxt < total and len(pending) < n * LOOKAHEAD:
                    pending.append(ex.submit(_page, nxt))
                    nxt += 1
                try:
                    pg = pending.popleft().result()
                except Exception:               # عمليّةٌ ماتت أو لم تبدأ: يُكمَل في العمليّة الواحدة
                    break
                i += 1
                yield pg
        finally:
            for f in pending:
                f.cancel()
            try:
                ex.shutdown(wait=False, cancel_futures=True)
            except Exception:
                pass
    while i < total:
        pg = book.read(i)
        i += 1
        yield pg
