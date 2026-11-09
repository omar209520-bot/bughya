"""تقسيمُ الصفحة: الرأسُ والمتنُ والحاشيةُ ورقمُ الصفحة المطبوع، من أسطرها بمواضعها وأحجامها.

يعمل على أسطر نصّ الملفّ (بحجم خطّها) وعلى أسطر القراءة الآليّة (بارتفاعها)، والمواضعُ نسبيّةٌ (٠–١، أعلى يسار).
قواعدُه من أداة إضافة الكتب (tahyia.py) بعد تعميمها، وهي قواعدُ للكتب المطبوعة الشائعة لا لكلّ كتاب:
  - الرأس: سطرٌ في أعلى الصفحة قبل المتن (اسمُ الكتاب أو الباب يتكرّر في كلّ صفحة).
  - رقمُ الصفحة: سطرٌ أرقامٌ وحدها في أعلاها أو أسفلها.
  - الحاشية: من أوّل سطرٍ يبدأ برقم حاشيةٍ بخطٍّ أصغر من المتن إلى آخر الصفحة؛
    فإن لم يوجد رقم، فالكتلةُ الصغيرةُ الخطّ في أسفل الصفحة.
وما أخطأت فيه يظهر للمستخدم: المتنُ والحاشيةُ يُعرضان منفصلين، وصورةُ الصفحة تحسم.
"""
import re

_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
_ONLY_NUM = re.compile(r"^[\s\-–—_ـ.()\[\]{}<>|/\\*•·0-9٠-٩۰-۹]+$")
_FOOT_MARK = re.compile(r"^\s*[(\[{<]?\s*[0-9٠-٩]{1,3}\s*[)\]}>]?\s*[-–—.:)]?\s+\S|^\s*\*+\s*\S")
# أرقامُ الحواشي كما تقرؤها القراءةُ الآليّة («<٦-» و«)٣(»)؛ من tahyia.py
_JUNK = r"\(\)<>\-\+&@'\\$%!\^;,\*~\?/#_\|\[\]{}\"=:"
_OCR_MARK = re.compile(rf"[{_JUNK}]*([٠-٩]{{1,3}})[{_JUNK}]+|[{_JUNK}]+([٠-٩]{{1,3}})(?=[\s\u0600-\u06FF]|$)")
_OCR_FOOT = re.compile(rf"^[{_JUNK}\s]{{0,4}}([٠-٩]{{1,3}})(?:[{_JUNK}\s]{{0,3}}([٠-٩]{{1,3}}))?[{_JUNK}]{{1,4}}\s")
_PAREN_NUM = re.compile(r"^\W{0,2}[()][0-9٠-٩]{1,3}[()]")     # «(١)» أو «)١(» كما تقرؤها القراءةُ الآليّة
_LEAD_NUM = re.compile(r"^\W{0,3}[0-9٠-٩؟]{1,3}\s*[-–—.:،)]")
_OCR_QUOTE = re.compile(r"\(([^()«»\n]{1,60})»")
_OCR_OPEN = re.compile(r"(^|[\s(\[])[!#&/?.'\"]+(?=[\u0621-\u064A][^«»\n]{0,80}»)")


def _num(t: str):
    d = re.sub(r"\D", "", t.translate(_DIGITS))
    return int(d) if d and len(d) <= 5 else None


_DARK = bytes(1 if v < 110 else 0 for v in range(256))


def find_rules(samples: bytes, width: int, height: int, stride: int = None) -> list:
    """خطوطُ الفصل الأفقيّة في صورة الصفحة (رماديّة): سطرٌ رفيعٌ متّصلُ الحبر طولُه ١٢٪ من العرض فأكثر،
    وفوقه وتحته بياضٌ في امتداده. ← [(y، x0، x1)] نسبيّةً (٠–١)."""
    stride = stride or width
    need = max(20, int(width * 0.12))
    pat = re.compile(b"{%d,}" % need)
    rows = {}
    for y in range(int(height * 0.3), height - 2):
        row = samples[y * stride:y * stride + width].translate(_DARK)
        m = max(pat.finditer(row), key=lambda r: r.end() - r.start(), default=None)
        if m:
            rows[y] = (m.start(), m.end())
    out, ys = [], sorted(rows)
    thick = max(2, height // 300)
    k = 0
    while k < len(ys):
        j = k
        while j + 1 < len(ys) and ys[j + 1] == ys[j] + 1:
            j += 1
        y0, y1 = ys[k], ys[j]
        x0, x1 = rows[y0]
        if y1 - y0 + 1 <= thick:
            clear = True
            for yy in (y0 - 4, y0 - 7, y1 + 4, y1 + 7):          # بياضٌ فوقه وتحته في امتداده
                if 0 <= yy < height:
                    seg = samples[yy * stride + x0:yy * stride + x1].translate(_DARK)
                    if seg.count(1) > 0.05 * (x1 - x0):
                        clear = False
            # حافّةُ إطارٍ حول كلام (لا فاصل): من طرفيها خطٌّ رأسيٌّ ينزل أو يصعد
            for side in (x0, x1 - 1):
                for rng in (range(y1 + 2, min(height, y1 + 2 + 6 * thick)), range(max(0, y0 - 2 - 6 * thick), y0 - 2)):
                    col = sum(1 for yy in rng if any(samples[yy * stride + xx] < 110 for xx in range(max(0, side - 3), min(width, side + 4))))
                    if rng and col >= 0.8 * len(rng):
                        clear = False
            if clear:
                out.append(((y0 + y1) / 2 / height, x0 / width, x1 / width))
        k = j + 1
    return out


def _foot_block(lines: list, idx: list, k: int) -> bool:
    """في القراءة الآليّة تتفاوت ارتفاعاتُ الأسطر، فقد لا يصغر سطرُ الحاشية الأوّلُ عن حجم الصفحة كلّها.
    فيُقارن ما بعده بما قبله: أسطرُه أصغرُ من أسطر المتن فوقه (وسطُها ٩٠٪ فأقلّ)، وقبله فراغٌ أوسعُ من تباعد الأسطر
    (ربعٌ فأكثر)، أو كانت أصغرَ بوضوح (٨٥٪ فأقلّ)."""
    med = lambda v: sorted(v)[len(v) // 2]
    above = [lines[i] for i in idx[:k]]
    below = [lines[i] for i in idx[k:] if lines[i]["size"] > 0]
    if len(above) < 2 or not below:
        return False
    a, b = med([l["size"] for l in above]), med([l["size"] for l in below])
    if b > 0.9 * a:
        return False
    steps = [above[j]["y"] - above[j - 1]["y"] for j in range(1, len(above))]
    gap = lines[idx[k]]["y"] - above[-1]["y"]
    return gap >= 1.25 * med(steps) or b <= 0.85 * a


def _rule_start(lines: list, idx: list, rules: list):
    """أوّلُ سطرٍ تحت خطّ الفصل، إن كان الخطُّ بين سطرين من المتن في النصف الأسفل، وما تحته ليس بأكبرَ خطًّا ممّا فوقه،
    ولا يزيد على ثلثي أسطر الصفحة."""
    med = lambda v: sorted(v)[len(v) // 2]
    for ry, rx0, rx1 in sorted(rules, key=lambda r: r[0]):
        if ry < 0.4:
            continue
        below = [k for k, i in enumerate(idx) if lines[i]["y"] > ry]
        if not below or below[0] == 0 or len(below) > 2 * len(idx) / 3:
            continue
        k = below[0]
        up, dn = lines[idx[k - 1]], lines[idx[k]]
        # فاصلُ الحاشية بعيدٌ عمّا فوقه وما تحته؛ والخطُّ الملاصقُ لسطرٍ فوقه خطٌّ تحت كلامٍ في المتن
        if ry - (up["y"] + up["h"]) < 0.25 * up["h"] or dn["y"] - ry < 0.3 * dn["h"]:
            continue
        a = med([lines[i]["size"] for i in idx[:k]])
        b = med([lines[i]["size"] for i in idx[k:]])
        if b <= 1.02 * a:
            return k
    return None


def _lead_num(t: str):
    """رقمٌ في أوّل السطر يليه فاصل («٢٦ -»، «12.»)، أو None."""
    if not _LEAD_NUM.match(t):
        return None
    d = re.match(r"\W{0,3}([0-9٠-٩]{1,3})", t.translate(_DIGITS))
    return int(d.group(1)) if d else None


def _arabic_share(t: str) -> float:
    letters = [c for c in t if c.isalpha()]
    return sum(1 for c in letters if "\u0600" <= c <= "\u06FF") / len(letters) if letters else 0.0


def _glued(prev: dict, p: dict, gap: float, text: str) -> bool:
    """قطعتان من كلمةٍ واحدة قسمتهما مكتبةُ القراءة («ال» + «عصر»، «والثقافي» + «ة»، «الثا» + «لث»)، لنصّ الملفّ وحده.
    المواضعُ لا تكفي: في ملفّات وورد قد تتلاصق كلمتان تامّتان بلا مسافةٍ في الملف («مسألة» + «الذكر»). فالشرط مع التلاصق
    أن يكون أحدُ الطرفين قصيرًا لا يقوم كلمةً وحده (حرفًا أو حرفين، أو «ال» وبعدها حرفان على الأكثر)؛ ولا يُضمّ ما بعد
    «ة» أو «ى» (آخرُ الكلمة)، ولا ما يبدأ بـ«ال» بعد كلمةٍ تامّة، ولا كلمةٌ شائعة («في»، «قد»)، ولا «و» وحدها بعد كلمة."""
    if "sp" not in prev or "sp" not in p or prev["sp"] or p["sp"] or not text or not p["t"]:
        return False
    a, b = text[-1], p["t"][0]
    if not ("ء" <= a <= "ي" and "ء" <= b <= "ي") or a in "ةى":
        return False
    if gap * p["pw"] >= 0.15 * max(p.get("size") or 0, prev.get("size") or 0):
        return False
    import arabic
    lw = re.sub("[^ء-ي]", "", arabic.normalize(text.split()[-1]))
    rw = re.sub("[^ء-ي]", "", arabic.normalize(p["t"].split()[0]))
    if not lw or not rw or lw in arabic.COMMON or rw in arabic.COMMON or rw == "و":
        return False
    if rw.startswith("ال") and len(lw) > 1:
        return False
    short = lambda w: len(w) <= 2 or (w.startswith("ال") and len(w) <= 4)
    return short(lw) or short(rw)


def merge_baselines(lines: list) -> list:
    """أجزاءُ السطر الواحد (تفصلها مسافةٌ أو يختلف خطُّها) تُضمّ سطرًا واحدًا، من اليمين إلى اليسار في العربيّة."""
    lines = sorted(lines, key=lambda l: l["y"])
    rows = []
    for l in lines:
        placed = False
        for row in rows[-3:]:
            top, bot = max(row["y"], l["y"]), min(row["y"] + row["h"], l["y"] + l["h"])
            if bot - top >= 0.6 * min(row["h"], l["h"]) > 0:
                row["parts"].append(l)
                row["y"], row["h"] = min(row["y"], l["y"]), max(row["y"] + row["h"], l["y"] + l["h"]) - min(row["y"], l["y"])
                placed = True
                break
        if not placed:
            rows.append({"y": l["y"], "h": l["h"], "parts": [l]})
    out = []
    for row in rows:
        parts = row["parts"]
        rtl = _arabic_share(" ".join(p["t"] for p in parts)) >= 0.5
        parts.sort(key=lambda p: -(p["x"] + p["w"]) if rtl else p["x"])
        text, prev = "", None
        for p in parts:
            if prev is not None:
                gap = (prev["x"] - (p["x"] + p["w"])) if rtl else (p["x"] - (prev["x"] + prev["w"]))
                if _glued(prev, p, gap, text):
                    pass
                else:
                    text += "  " if gap > 0.08 else " "
            text += p["t"]
            prev = p
        x0 = min(p["x"] for p in parts)
        x1 = max(p["x"] + p["w"] for p in parts)
        size = max(p.get("size") or p["h"] for p in parts)
        conf = [p["conf"] for p in parts if p.get("conf") is not None]
        words = [w for p in parts for w in (p.get("words") or [])]
        out.append({"t": text.strip(), "x": x0, "y": row["y"], "w": x1 - x0, "h": row["h"], "size": size,
                    "conf": sum(conf) / len(conf) if conf else None, "words": words or None})
    return out


def _body_size(lines: list) -> float:
    zone = [l for l in lines if 0.08 <= l["y"] <= 0.85] or lines
    pairs = sorted((l["size"], max(1, len(l["t"]))) for l in zone)
    half, acc = sum(w for _, w in pairs) / 2, 0
    for s, w in pairs:
        acc += w
        if acc >= half:
            return s
    return pairs[-1][0] if pairs else 0


def clean_ocr(t: str) -> str:
    def rep(m):
        return "(%s)" % (m.group(1) or m.group(2))
    t = _OCR_MARK.sub(rep, t)
    t = _OCR_QUOTE.sub(r"«\1»", t)
    t = _OCR_OPEN.sub(r"\1«", t)
    t = re.sub(r"«[!#&/?.']+", "«", t)
    return re.sub(r"\s+", " ", t).strip()


def clean_ocr_foot(t: str) -> str:
    m = _OCR_FOOT.match(t)
    if not m:
        return clean_ocr(t)
    a, b = m.group(1), m.group(2)
    return ("(%s-%s)" % (a, b) if b else "(%s)" % a) + " " + clean_ocr(t[m.end():])


_ARABIC = __import__("re").compile("[\u0621-\u064a]")


def split_page(lines: list, ocr: bool = False, rules: list = None) -> dict:
    """lines: [{t, x, y, w, h, size, conf}] ← {head, body, foot, printed, boxes}."""
    lines = [l for l in merge_baselines([l for l in lines if l["t"].strip()]) if l["t"]]
    if not lines:
        return {"head": "", "body": "", "foot": "", "printed": None, "boxes": [], "catch": None}
    size = _body_size(lines)
    layer = ["b"] * len(lines)
    printed = None
    # رقمُ الصفحة: أرقامٌ وحدها في أعلى الصفحة أو أسفلها (والأسفلُ أولى)
    for i in sorted(range(len(lines)), key=lambda i: -lines[i]["y"]):
        l = lines[i]
        if (l["y"] > 0.86 or l["y"] + l["h"] < 0.10) and _ONLY_NUM.match(l["t"]) and _num(l["t"]) is not None:
            layer[i] = "n"
            printed = _num(l["t"]) if _num(l["t"]) >= 1 else None
            break
    # الذيلُ المتكرّر: سطرٌ في أسفل الصفحة بخطٍّ أصغر من المتن، في أحد طرفيه رقمُ الصفحة وفي الآخر اسمُ الكتاب أو المؤلّف
    # («200 كتاب تمهيد الأوائل…»): ليس من الكلام، ورقمُه رقمُ الصفحة المطبوع
    # (في نصّ الملفّ وحده: الحاشيةُ الواحدةُ في أسفل الصفحة المقروءة آليًّا تشبهه، وقد كانت تُحذف)
    if printed is None and not ocr:
        i = max(range(len(lines)), key=lambda i: lines[i]["y"])
        l = lines[i]
        toks = l["t"].split()
        num = _num(toks[0]) if toks and _ONLY_NUM.match(toks[0]) else (
            _num(toks[-1]) if toks and _ONLY_NUM.match(toks[-1]) else None)
        above = max((lines[j]["y"] + lines[j]["h"] for j in range(len(lines)) if j != i), default=0)
        apart = l["y"] - above > 0.15      # بعيدٌ عن آخر الكلام بمسافةٍ ظاهرة
        if (layer[i] == "b" and l["y"] > 0.88 and num is not None and 2 <= len(toks) <= 20
                and apart and _ARABIC.search(l["t"])):
            layer[i] = "n"
            printed = num if num >= 1 else None
    # التعقيبة: كلمةٌ أو كلمتان وحدهما في آخر الصفحة على يسارها، هي أوّلُ كلام الصفحة التالية (الطبعات القديمة والمخطوطات).
    # والسطرُ الأخيرُ القصيرُ من فقرةٍ عربيّة يبدأ من اليمين، فلا يُشتبه بها
    catch = None
    rest = [i for i in range(len(lines)) if layer[i] == "b"]
    if len(rest) >= 3:
        i = max(rest, key=lambda i: lines[i]["y"])
        l = lines[i]
        words = l["t"].split()
        if (l["y"] > 0.8 and 1 <= len(words) <= 2 and l["x"] + l["w"] < 0.45 and l["w"] < 0.25
                and not any(c.isdigit() for c in l["t"]) and _ARABIC.search(l["t"])
                and sum(1 for j in rest if j != i and lines[j]["y"] > l["y"] - l["h"] * 0.5) == 0):
            layer[i] = "c"
            catch = l["t"].strip()
    # الرأس: ما في أعلى الصفحة قبل أوّل سطرٍ من المتن، وليس أكبرَ خطًّا من المتن (العنوانُ الكبير متن)
    for i, l in enumerate(lines):
        if layer[i] == "n":
            continue
        if l["y"] + l["h"] < (0.085 if ocr else 0.09) and l["size"] <= size * 1.08 and i < 3:
            layer[i] = "h"
        else:
            break
    if sum(1 for x in layer if x == "b") < 2:      # لا رأسَ لصفحةٍ لا متنَ بعده (سطرٌ واحد في أعلاها متنُها)
        layer = ["b" if x == "h" else x for x in layer]
    body_idx = [i for i in range(len(lines)) if layer[i] == "b"]
    # الحاشية: أوّلُ سطرٍ يبدأ برقم حاشيةٍ بخطٍّ أصغر، بعد متنٍ، في النصف الأسفل تقريبًا
    small = 0.86 if ocr else 0.9
    start = None
    for k, i in enumerate(body_idx):
        l = lines[i]
        mark = (_OCR_FOOT.match(l["t"]) or _FOOT_MARK.match(l["t"])) if ocr else _FOOT_MARK.match(l["t"])
        # أسطرٌ مرقّمةٌ قبله (أبياتُ منظومة، أو قائمةٌ مرقّمة) ورقمُه يُكمل ترقيمَها (٢٢ ثمّ ٢٦): رقمُ بيتٍ لا رقمُ حاشية.
        # أمّا رقمٌ يبدأ من جديد (١ بعد ٣٠) فحاشية.
        if mark:
            prior = [_lead_num(lines[j]["t"]) for j in body_idx[max(0, k - 6):k]]
            prior = [x for x in prior if x is not None]
            n = _lead_num(l["t"])
            if len(prior) >= 3 and n is not None and any(0 < n - x <= 5 for x in prior[-4:]):
                continue
        if k > 0 and l["y"] > 0.3 and l["size"] <= size * small and mark:
            start = k
            break
        if ocr and _PAREN_NUM.match(l["t"]) and k > 1 and l["y"] > 0.3 and _foot_block(lines, body_idx, k):
            start = k
            break
    rule_start = _rule_start(lines, body_idx, rules or [])
    if rule_start is not None:
        start = rule_start      # خطُّ الفصل في الصورة: ما تحته حاشية (ولو لم يبدأ برقم: تكملةُ حاشية الصفحة السابقة)
    if start is None:   # بلا رقمٍ: الكتلةُ الصغيرةُ الخطّ المتّصلةُ بأسفل الصفحة
        k = len(body_idx)
        while k > 1 and lines[body_idx[k - 1]]["size"] <= size * (small - 0.04) and lines[body_idx[k - 1]]["y"] > 0.45:
            k -= 1
        if k < len(body_idx):
            start = k
    if start is not None:
        for i in body_idx[start:]:
            layer[i] = "f"
    head = [lines[i]["t"] for i in range(len(lines)) if layer[i] == "h"]
    body = [lines[i]["t"] for i in range(len(lines)) if layer[i] == "b"]
    foot = [lines[i]["t"] for i in range(len(lines)) if layer[i] == "f"]
    if ocr:
        body = [clean_ocr(t) for t in body]
        foot_out = []
        for t in foot:   # سطرٌ يبدأ برقمٍ حاشيةٌ جديدة، وما سواه تكملةٌ لما قبله
            if _OCR_FOOT.match(t) or _FOOT_MARK.match(t) or not foot_out:
                foot_out.append(clean_ocr_foot(t))
            else:
                foot_out[-1] += " " + clean_ocr(t)
        foot = foot_out
    boxes = [{"t": l["t"], "x": round(l["x"], 4), "y": round(l["y"], 4), "w": round(l["w"], 4),
              "h": round(l["h"], 4), "l": layer[i]} for i, l in enumerate(lines)]
    for bx, l in zip(boxes, lines):              # مواضعُ الكلمات (في القراءة الآليّة): للنقر على الكلمة في القارئ
        if l.get("words"):
            bx["ws"] = [[w["t"], round(w["x"], 4), round(w["y"], 4), round(w["w"], 4), round(w["h"], 4)] for w in l["words"]]
    return {"head": " ".join(head), "body": "\n".join(body), "foot": "\n".join(foot), "printed": printed,
            "boxes": boxes, "catch": catch}
