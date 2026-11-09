"""قارئُ بي دي إف والصور: نصُّ الملفّ أوّلًا، ثمّ القراءةُ الآليّة لما لا نصَّ فيه (من «سَبْر الوارث»).

لكلّ صفحة:
  ١) يُستخرج نصُّها المضمَّن بأسطره وأحجام خطّه.
  ٢) إن قلّ (أقلّ من ٢٥ حرفًا: صفحةٌ مصوَّرة) أو فسد (خريطةُ حروفٍ مكسورة في الملفّ) قُرئت صورتُها آليًّا.
  ٣) إن ظهرت الكلماتُ معكوسة (ملفٌّ حفظ العربيّة بترتيب رسمها) قُلبت الأسطر.
  ٤) تُقسم الصفحة: رأسٌ ومتنٌ وحاشيةٌ ورقمٌ مطبوع (layout.py).
والصورُ (png وjpg وtif…) تُفتح كتابًا صفحاتُه مصوَّرةٌ كلُّها.
"""
import arabic
from readers import ReaderError, make_page
from readers import layout, notes
from readers.arabic_pdf import best_lines, sample_bias

try:
    import pymupdf as fitz          # الاسمُ الجديد للمكتبة
except ImportError:  # pragma: no cover
    try:
        import fitz                 # اسمُها في النسخ الأقدم
    except ImportError:
        fitz = None

TOOL_MARKERS = ("microsoft word", "acdsee", "proprint", "acrobat", "scanner", "untitled", "print job",
                ".pdf", ".doc", ".tif", "adobe", "pdf-xchange", "abbyy", "nitro")
OCR_LONG_SIDE = 3000       # طولُ الصورة المقروءة آليًّا بالنقاط الضوئيّة (سَبْر الوارث قاس ١٨٠٠ فرفعها لدقّة الطباعة القديمة)
TEXT_LAYER_MIN = 0.88     # دون هذا التوافقِ مع القراءة الآليّة يُعدّ نصُّ الملفّ معيبًا
MIN_LETTERS = 25           # أقلُّ من هذا في نصّ الملفّ: الصفحةُ مصوَّرة


def usable_meta(raw) -> str:
    """بياناتُ الملفّ تكذب كثيرًا («ACDSee ProPrint Job»، ترميزٌ مكسور): لا تُقبل إلّا عربيّةً صالحة."""
    v = (raw or "").strip()
    if not (4 <= len(v) <= 300) or v.startswith("<") or any(m in v.lower() for m in TOOL_MARKERS):
        return ""
    q = arabic.quality(v)
    return arabic.clean_raw(v) if q["letters"] >= 3 and q["arabic"] >= 0.4 else ""


def spread_gutter(page):
    """صورةٌ فيها صفحتان متجاورتان (عرضُها أكبرُ من طولها): موضعُ الفاصل بينهما نسبيًّا (٠–١)، أو None.
    الفاصلُ أعرضُ شريطٍ رأسيٍّ خالٍ من الحبر (أو ظلُّ الكعب الأسود) قربَ الوسط، بين ربع العرض وثلاثة أرباعه.
    قيس على كتابين مصوَّرين صفحتين في صورة (٨٠ صفحة): يقع الفاصلُ بين الصفحتين، أو في الصفحة البيضاء إن كانت إحداهما فارغة."""
    W, H = page.rect.width, page.rect.height
    if W < H * 1.15:
        return None
    z = 400 / W
    pix = page.get_pixmap(matrix=fitz.Matrix(z, z), colorspace=fitz.csGRAY, alpha=False)
    w, h, s, st = pix.width, pix.height, pix.samples, pix.stride
    y0, y1 = int(h * 0.12), int(h * 0.88)
    col = [sum(1 for y in range(y0, y1) if s[y * st + x] < 140) / max(1, y1 - y0) for x in range(w)]
    ink = sorted(c for c in col[int(w * .1):int(w * .9)] if c > 0.005)
    med = ink[len(ink) // 2] if ink else 0
    empty = [c <= max(0.004, med * 0.08) or c > 0.85 for c in col]
    runs, x, end = [], int(w * .25), int(w * .75)
    while x < end:
        if empty[x]:
            a = x
            while x < end and empty[x]:
                x += 1
            runs.append((x - a, (a + x) / 2 / w))
        x += 1
    if not runs:
        return None
    width, center = max(runs, key=lambda r: r[0] - abs(r[1] - .5) * w * 0.3)
    return center if width >= w * 0.02 else None


class PdfBook:
    def __init__(self, path, kind: str, ocr=None):
        if fitz is None:
            raise ReaderError("مكتبةُ قراءة بي دي إف غير منصّبة: أعد التنصيب.")
        try:
            self.doc = fitz.open(str(path))
        except Exception as e:
            raise ReaderError("تعذّر فتحُ الملفّ: %s" % e)
        if self.doc.needs_pass:
            raise ReaderError("الملفُّ محميٌّ بكلمة سرّ.")
        self.kind, self.ocr = kind, ocr
        self.unit, self.approx = "صفحة", False
        self.total = self.doc.page_count
        md = self.doc.metadata or {}
        self.title = usable_meta(md.get("title")) if kind == "pdf" else ""
        self.author = ""                   # مؤلّفُ الملفّ في بياناته كثيرًا ما يكون ناسخَه: تلميحٌ لا مؤلّف
        self.hints = {k: usable_meta(md.get(k)) for k in ("title", "author", "subject")} if kind == "pdf" else {}
        self.toc = []
        if kind == "pdf":
            try:
                for lvl, t, pg in self.doc.get_toc(simple=True):
                    t = arabic.clean_raw(t or "")
                    if t and 1 <= pg <= self.total:
                        self.toc.append((lvl, t, pg))
            except Exception:
                self.toc = []
        self.scanned_guess = kind == "image" or self._guess_scanned()
        self.bias = [0, 0, 0] if self.scanned_guess else sample_bias(self.doc, fitz, self.total)
        self.force_ocr = False
        if kind == "pdf" and not self.scanned_guess and ocr is not None and ocr.ok:
            score = self._text_layer_score()
            if score is not None and score < TEXT_LAYER_MIN:
                # نصُّ الملف المضمَّن معيب (حروفٌ ناقصة أو مقطَّعة، كما في ملفّاتٍ حُفظت من وورد): تُقرأ صورةُ كلّ صفحة بدله
                self.force_ocr, self.scanned_guess = True, True
                self.hints["note"] = "نصُّ الملفّ المضمَّن معيب (توافقُه مع الصورة %d٪) فقُرئت صفحاتُه آليًّا" % round(score * 100)

    def _text_layer_score(self):
        """يقابل نصَّ الملفّ المضمَّن بالقراءة الآليّة لصورة أربع صفحاتٍ من الكتاب: نسبةُ كلمات النصّ المضمَّن الموجودة في
        ما قرأته الآلةُ من الصورة. السليمُ ٠٫٩٢ فأكثر في ما قيس، والمعيبُ دون ٠٫٨٥. ويعيد None إن لم تتّسع العيّنة."""
        if self.total < 1:
            return None
        sc = []
        for f in (0.2, 0.4, 0.6, 0.8):
            i = min(self.total - 1, int(self.total * f))
            try:
                page = self.doc[i]
                lines, _ = best_lines(page, fitz, self.bias)
                mine = [w for w in arabic.normalize(" ".join(l["t"] for l in lines)).split() if len(w) > 1]
                if len(mine) < 30:
                    continue
                W, H = page.rect.width or 1, page.rect.height or 1
                side = min(OCR_LONG_SIDE, getattr(self.ocr, "max_side", None) or OCR_LONG_SIDE)
                z = max(1.0, min(6.0, side / max(W, H)))
                pix = page.get_pixmap(matrix=fitz.Matrix(z, z), colorspace=fitz.csGRAY, alpha=False)
                theirs = {w for g in self.ocr.recognize(pix.tobytes("png"))
                          for w in arabic.normalize(g["text"]).split() if len(w) > 1}
                sc.append(sum(1 for w in mine if w in theirs) / len(mine))
            except Exception:
                continue
        return sum(sc) / len(sc) if sc else None

    def _guess_scanned(self) -> bool:
        """عيّنةٌ من خمس صفحاتٍ متباعدة: أفيها نصٌّ مضمَّن؟ (لترتيب القراءة: النصّيُّ أوّلًا لأنّه أسرع)."""
        if not self.total:
            return False
        idx = sorted({min(self.total - 1, int(self.total * f)) for f in (0.1, 0.3, 0.5, 0.7, 0.9)})
        letters = 0
        for i in idx:
            try:
                letters += sum(1 for c in self.doc[i].get_text("text") if c.isalpha())
            except Exception:
                pass
        return letters / len(idx) < MIN_LETTERS

    def close(self) -> None:
        try:
            self.doc.close()
        except Exception:
            pass

    def pages(self, start: int = 1):
        for i in range(max(0, start - 1), self.total):
            yield self.read(i)

    # ───────────────────── الصفحة ─────────────────────

    def read(self, i: int) -> dict:
        n = i + 1
        try:
            page = self.doc[i]
        except Exception as e:
            return make_page(n, method="error", weak=True, body="", head="تعذّرت قراءةُ الصفحة: %s" % e)
        lines, self.last_variant = ([], None) if self.kind == "image" else best_lines(page, fitz, self.bias)
        raw = "\n".join(l["t"] for l in lines)
        q = arabic.quality(raw)
        needs_ocr = self.kind == "image" or q["letters"] < MIN_LETTERS or arabic.is_garbage(q) or self.force_ocr
        # تعذّر بناءُ السطر في كتابٍ تغلب فيه الصيغةُ المبنيّة: فنصُّه كما هو معيبٌ (مركّباتٌ معكوسة)، والقراءةُ الآليّة أصدق
        if self.last_variant == "تعذّر البناء" and max(self.bias[1], self.bias[2]) > self.bias[0]:
            needs_ocr = True
        if needs_ocr:
            if self.ocr is not None and self.ocr.ok:
                return self._ocr(page, n)
            # بلا قراءةٍ آليّة: يُحفظ ما وُجد، وتُعلَّم الصفحة ضعيفة إن كان فيها شيءٌ لم يُقرأ
            has_image = bool(page.get_images(full=False)) if self.kind != "image" else True
            if not lines:
                return make_page(n, method="none", weak=has_image)
        if self.last_variant in ("كما هو", "تعذّر البناء") and arabic.looks_reversed(arabic.normalize(raw)):
            for l in lines:
                l["t"] = arabic.unreverse_line(l["t"])
        rec = layout.split_page(lines, ocr=False)
        for k in ("head", "body", "foot"):
            rec[k] = fix_allah(rec[k])
        return make_page(n, rec["body"], rec["foot"], rec["head"], rec["printed"], "text", None, rec["boxes"],
                         weak=arabic.is_garbage(q), catch=rec.get("catch"))

    def _ocr(self, page, n: int) -> dict:
        """الصفحةُ المصوَّرة صفحتين في صورةٍ واحدة تُقرأ كلُّ صفحةٍ منها وحدها، اليمنى ثمّ اليسرى،
        فلا تختلط أسطرُهما؛ ويبقى رقمُ صفحة الملفّ واحدًا، ومواضعُ الكلمات على الصورة كلّها."""
        g = spread_gutter(page)
        if g is None:
            return self._ocr_one(page, n)
        R = page.rect
        parts = [self._ocr_one(page, n, fitz.Rect(R.x0 + R.width * g, R.y0, R.x1, R.y1)),    # اليمنى أوّلًا
                 self._ocr_one(page, n, fitz.Rect(R.x0, R.y0, R.x0 + R.width * g, R.y1))]
        if any(p["head"].startswith("تعذّرت القراءةُ الآليّة") for p in parts):
            return self._ocr_one(page, n)
        full = [p for p in parts if p["body"].strip() or p["foot"].strip()] or parts[:1]
        join = lambda k, sep: sep.join(p[k] for p in full if p[k].strip())
        confs = [p["conf"] for p in full if p["conf"] is not None]
        return make_page(n, join("body", "\n"), join("foot", "\n"), join("head", " · "),
                         next((p["printed"] for p in full if p["printed"]), None), "ocr",
                         round(sum(confs) / len(confs), 3) if confs else None,
                         [b for p in full for b in (p["boxes"] or [])], any(p["weak"] for p in full),
                         catch=full[-1].get("catch"))

    def _ocr_one(self, page, n: int, clip=None) -> dict:
        R = page.rect
        C = clip or R
        W = C.width or 1
        side = min(OCR_LONG_SIDE, getattr(self.ocr, "max_side", None) or OCR_LONG_SIDE)
        # الدقّةُ دقّةُ الصورة كلّها وإن قُرئ نصفُها: قيس التكبيرُ على عشر صفحاتٍ فلم يُحسّن، وغيّر مواضعَ الخطأ
        z = max(1.0, min(6.0, side / max(R.width or 1, R.height or 1)))
        try:
            pix = page.get_pixmap(matrix=fitz.Matrix(z, z), colorspace=fitz.csGRAY, alpha=False, clip=clip)
            got = self.ocr.recognize(pix.tobytes("png"))
        except Exception as e:
            return make_page(n, method="ocr", weak=True, head="تعذّرت القراءةُ الآليّة: %s" % e)
        if clip is not None:          # مواضعُ ما قُرئ في نصف الصورة ← مواضعُه في الصورة كلّها
            ox, sx = (C.x0 - R.x0) / (R.width or 1), W / (R.width or 1)
            for g in got:
                g["x"], g["w"] = ox + g["x"] * sx, g["w"] * sx
                for w in g.get("words") or []:
                    w["x"], w["w"] = ox + w["x"] * sx, w["w"] * sx
        lines = [{"t": arabic.clean_raw(g["text"]), "x": g["x"], "y": g["y"], "w": g["w"], "h": g["h"],
                  "size": g["h"], "conf": g.get("conf"), "words": g.get("words")} for g in got if g.get("text", "").strip()]
        if not lines:
            return make_page(n, method="ocr", conf=0.0, weak=False)
        if self.kind == "pdf":
            notes.merge(lines, notes.markers(page))      # أرقامُ الحواشي من نصّ الملفّ، لا من القراءة
            lines = [l for l in lines if l["t"].strip()]
        raw = "\n".join(l["t"] for l in lines)
        if arabic.looks_reversed(arabic.normalize(raw)):
            for l in lines:
                l["t"] = arabic.unreverse_line(l["t"])
                l.pop("words", None)       # تغيّر النصّ عن الكلمات المقروءة: لا مواضعَ للكلمات
        elif getattr(self.ocr, "word_order_check", False) and looks_word_reversed(arabic.normalize(raw)):
            for l in lines:
                l["t"] = " ".join(reversed(l["t"].split()))
                if l.get("words"):
                    l["words"] = list(reversed(l["words"]))
        try:
            rules = layout.find_rules(pix.samples, pix.width, pix.height, pix.stride)
        except Exception:
            rules = []
        rec = layout.split_page(lines, ocr=True, rules=rules)
        confs = [l["conf"] for l in lines if l.get("conf") is not None]
        conf = round(sum(confs) / len(confs), 3) if confs else None
        q = arabic.quality(rec["body"] + "\n" + rec["foot"])
        # ثقةُ أداة الماك في العربيّة بين ٠٫٣ و٠٫٥ والنصُّ صالح (قيس على كتابين مصوَّرين)؛ فالضعيفُ ما دون ٠٫٢٥ أو ما فسد
        weak = (conf is not None and conf < 0.25) or arabic.is_garbage(q)
        return make_page(n, rec["body"], rec["foot"], rec["head"], rec["printed"], "ocr", conf, rec["boxes"], weak,
                         catch=rec.get("catch"))

    def render(self, n: int, zoom: float = 2.0):
        """صورةُ الصفحة (لأداة الصور)."""
        page = self.doc[n - 1]
        return page, page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)


# لفظُ الجلالة في ملفّات وورد: يُرسم بحرفٍ مركّب يُحفظ في نصّ الملفّ «للا» بلا هاء، فيُقرأ «اللَ».
# و«الل» ليست كلمةً عربيّة، فلا تأتي إلّا من هذا: تُردّ الهاء (وما قبلها من حرف عطفٍ أو جرّ أو قسَمٍ يبقى)
_ALLAH = __import__("re").compile(r"(?<![ء-ي])([وفبت]{0,2}الل)([ً-ْ]*)(?![ء-يً-ْ])")


def fix_allah(t: str) -> str:
    return _ALLAH.sub(lambda m: m.group(1) + m.group(2) + "ه", t) if t else t


_BIGRAMS = [("صلي", "الله"), ("رضي", "الله"), ("رسول", "الله"), ("بسم", "الله"), ("الله", "عليه"),
            ("عليه", "وسلم"), ("قال", "رسول"), ("الله", "تعالي")]


def looks_word_reversed(norm_text: str) -> bool:
    """كلماتُ السطر سليمةٌ وترتيبُها معكوس (قد تفعله بعضُ محرّكات القراءة الآليّة): أزواجٌ شائعةٌ تظهر مقلوبة."""
    w = norm_text.split()
    pairs = list(zip(w, w[1:]))
    fwd = sum(1 for p in pairs if p in _BIGRAMS)
    rev = sum(1 for a, b in pairs if (b, a) in _BIGRAMS)
    return rev >= 2 and rev > 2 * fwd
