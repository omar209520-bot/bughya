"""أرقامُ الحواشي المرفوعة في الصفحات المقروءة آليًّا: تُؤخذ من نصّ الملفّ المضمَّن، لا من القراءة.

القراءةُ الآليّة تُخطئ في الأرقام الصغيرة المرفوعة («العكبري⁽²⁾» تُقرأ «العكبري (ا،»)، ونصُّ الملفّ وإن فسدت حروفُه
يحفظ هذه الأرقامَ ومواضعَها. فيُحذف ما قرأته الآلةُ في موضع الرقم، ويُكتب الرقمُ من نصّ الملفّ بعد الكلمة التي تسبقه.
ولا يُخمَّن شيء: ما لا رقمَ له في نصّ الملفّ يبقى كما قُرئ.
"""
import re

NUM = re.compile(r"^\(?\s*([0-9٠-٩]{1,3})\s*\)?$")
GARBAGE = re.compile(r"^[()\"'!“”«»0-9٠-٩اأ،,.\s]{1,6}$")
TAIL = re.compile(r"[()\"'!“”0-9٠-٩]+$")
DIG = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")


def markers(page) -> list:
    """أرقامُ الحواشي المرفوعة في نصّ الملفّ بمواضعها النسبيّة: [{n, x0, y0, x1, y1}]."""
    W, H = page.rect.width or 1, page.rect.height or 1
    spans, base = [], {}
    try:
        for blk in page.get_text("dict").get("blocks", []):
            for ln in blk.get("lines", []):
                sps = [sp for sp in ln.get("spans", []) if sp.get("text", "").strip()]
                low = max((sp["bbox"][3] for sp in sps if any(c.isalpha() for c in sp["text"])), default=None)
                for sp in sps:
                    spans.append(sp)
                    base[id(sp)] = low
    except Exception:
        return []
    sizes = sorted(sp["size"] for sp in spans if any(c.isalpha() for c in sp["text"]))
    if not sizes:
        return []
    body = sizes[len(sizes) // 2]
    small = [sp["bbox"] for sp in spans if sp["size"] < body * 0.8 and any(c.isalpha() for c in sp["text"])]
    out = []
    for sp in spans:
        m = NUM.match(sp["text"].strip())
        if not m:
            continue
        # مرفوعٌ عن سطره: لا رقمَ آيةٍ صغيرَ الخطّ على السطر نفسه («[الروم: 50]»)
        low = base.get(id(sp))
        lifted = low is not None and sp["bbox"][3] < low - 0.2 * body
        raised = bool(sp.get("flags", 0) & 1) or (sp["size"] < body * 0.8 and (lifted or low is None))
        x0, y0, x1, y1 = sp["bbox"]
        # رقمُ آيةٍ أو صفحةٍ بخطٍّ صغير بجانب كلامٍ صغير («[الروم: 50]»): ليس رقمَ حاشية
        near = any(_overlap(y0, y1, b[1], b[3]) > 0.5 * (y1 - y0) and min(abs(x0 - b[2]), abs(b[0] - x1)) < 40
                   for b in small)
        if not raised or near:
            continue
        out.append({"n": m.group(1).translate(DIG), "x0": x0 / W, "y0": y0 / H, "x1": x1 / W, "y1": y1 / H})
    return out


def _overlap(a0, a1, b0, b1) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))


def merge(lines: list, marks: list) -> int:
    """يُدخل الأرقامَ في أسطر القراءة الآليّة (التي فيها words بمواضعها)، ويعيد عددَ ما أُدخل."""
    if not marks:
        return 0
    lines = [l for l in lines if l.get("words")]
    # ١) ما قرأته الآلةُ في موضع الرقم وليس كلمةً: يُحذف
    for l in lines:
        keep = []
        for w in l["words"]:
            hit = any(_overlap(w["x"], w["x"] + w["w"], m["x0"], m["x1"]) > 0.5 * w["w"]
                      and _overlap(w["y"], w["y"] + w["h"], m["y0"], m["y1"]) > 0 for m in marks)
            if hit and GARBAGE.match(w["t"]):
                if w["t"].rstrip().endswith("،"):
                    w = dict(w, t="،")
                    keep.append(w)
                continue
            keep.append(w)
        l["words"] = keep
    added = 0
    for m in marks:
        my = (m["y0"] + m["y1"]) / 2
        best, bo = None, 0.0
        for l in lines:                       # السطرُ الذي فيه الرقم: أكثرُها تداخلًا معه، من الأسطر التي فيها كلام
            if not any(re.search("[؀-ۿ]", w["t"]) for w in l["words"]):
                continue
            o = _overlap(l["y"], l["y"] + l["h"], m["y0"], m["y1"])
            if o > bo:
                best, bo = l, o
        if best is None:
            continue
        # الكلمةُ التي تسبقه في القراءة: أقربُ كلمةٍ عن يمينه
        right = [w for w in best["words"] if w["x"] + w["w"] * 0.5 >= m["x1"] - 0.002]
        if not right:
            continue
        w = min(right, key=lambda w: w["x"])
        if _overlap(w["x"], w["x"] + w["w"], m["x0"], m["x1"]) > 0:
            w["t"] = TAIL.sub("", w["t"]) or w["t"]
        w["t"] += "(%s)" % m["n"]
        added += 1
    for l in lines:
        l["t"] = " ".join(w["t"] for w in l["words"] if w["t"])
    return added
