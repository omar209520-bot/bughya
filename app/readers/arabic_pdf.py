"""إعادةُ بناء السطر العربيّ من مواضع حروفه في ملفّ بي دي إف (من أداة تفريغ «تهذيب أصول الفقه» بعد تعميمها).

علّتان شائعتان في ملفّات بي دي إف العربيّة، ولا سيّما المصنوعةُ من وورد:
  ١) الحروفُ المركّبة (لا، لأ، لإ، في، لله، لم، جم…) تُكتب خريطتُها معكوسة، فيُستخرج «ثلاثة» «ثالثة»، و«في» «يف»،
     و«الله» «هللا»، و«الإسلام» «اإلسالم»، و«المتون» «املتون».
  ٢) الحركاتُ رموزٌ مستقلّة بينها وبين حروفها رموزُ مسافة، فتتقطّع الكلمة: «مُحَمَّد» ← «مُ حَ مَّ د».
والعلاج:
  - الحروفُ تُرتَّب بمواضعها من اليمين إلى اليسار، والمسافاتُ من الفراغ بين الحروف لا من رموز المسافة؛
  - كلُّ حركةٍ تُلحق بالحرف الذي يقع فيه وسطُها؛
  - الحرفُ المركّب (حروفُه الأولى بلا عرضٍ عند طرفه) يُقسم عرضُه على حروفه، ويُجرَّب ترتيبُها كما هو ومعكوسًا؛
  - الأرقامُ واللاتينيّة تبقى من اليسار إلى اليمين.
ثمّ يُختار للصفحة أحسنُ الصيغ الثلاث (نصُّ المكتبة كما هو، والمبنيُّ، والمبنيُّ بعكس المركّبات) بعدد ما فيها من الكلمات العربيّة الشائعة؛
فالملفُّ السليمُ يبقى على حاله، والمعيبُ يُصلَح.
"""
import re
import unicodedata

import arabic

LTR = {"L", "EN", "AN"}
GAP_EM, GAP_MIN = 0.05, 0.6       # فراغٌ أوسعُ من هذا بين حرفين فهو مسافةُ كلمة (بوحدة حجم الخطّ)؛
                                  # قيس على أربعة ملفّات: ٠٫٠٤–٠٫٠٦ أكثرُ كلماتٍ شائعة من ٠٫٠٨٥ و٠٫١٢
SEP = {"CS", "ES", "ET"}


def _mark(c: str) -> bool:
    return unicodedata.category(c) == "Mn"


def _is_ar(c: str) -> bool:
    return "؀" <= c <= "ۿ" or "ݐ" <= c <= "ݿ" or "ﭐ" <= c <= "﻿"


def rebuild(chars: list, size: float, reverse_groups: bool) -> str:
    """chars: [(الحرف، x0، x1)] بترتيب ورودها ← نصُّ السطر بترتيب القراءة."""
    base = [c for c in chars if c[0].strip() and not _mark(c[0])]
    marks = [c for c in chars if _mark(c[0])]
    if not base:
        return ""
    order = sorted(range(len(base)), key=lambda i: (-round(base[i][2], 1), i))
    seq = [[base[i][0], base[i][1], base[i][2], []] for i in order]
    # الحرفُ المركّب: حروفُه الأولى بلا عرضٍ عند طرفه الأيمن، وآخرُها بعرضه كلِّه
    k = 0
    while k < len(seq):
        j = k
        while j < len(seq) and seq[j][2] - seq[j][1] <= 0.3 and abs(seq[j][2] - seq[k][2]) < 0.15:
            j += 1
        if j > k and j < len(seq) and abs(seq[j][2] - seq[k][2]) < 0.15 and seq[j][2] - seq[j][1] > 0.3:
            group = seq[k:j + 1]
            if reverse_groups:
                group = group[::-1]
            x1, w = seq[j][2], (seq[j][2] - seq[j][1]) / (j - k + 1)
            for n, g in enumerate(group):
                g[1], g[2] = x1 - (n + 1) * w, x1 - n * w
            seq[k:j + 1] = group
            k = j + 1
        else:
            k += 1
    for m in marks:     # الحركةُ لحرفها الذي يقع فيه وسطُها، وإلّا تُترك (حركةٌ ناقصةٌ خيرٌ من حركةٍ على غير حرفها)
        x = (m[1] + m[2]) / 2
        cand = [n for n, b in enumerate(seq) if b[2] - b[1] > 0.3 and b[1] - 0.5 <= x <= b[2] + 0.5]
        if cand:
            best = max(cand, key=lambda n: min(x - seq[n][1], seq[n][2] - x))
            seq[best][3].append(m[0])
    for n, b in enumerate(seq):     # حركةُ التطويل لحرفها الذي قبله
        if b[0] == "ـ" and b[3]:
            j = n - 1
            while j >= 0 and seq[j][0] == "ـ":
                j -= 1
            if j >= 0:
                seq[j][3].extend(b[3])
            b[3] = []
    gap = max(GAP_MIN, GAP_EM * size)
    out = []
    for n, b in enumerate(seq):
        if n:
            g = seq[n - 1][1] - b[2]
            if b[0] != "ـ":        # التطويلُ يلاصق ما بعده؛ وبعده مسافةٌ حقيقيّةٌ إن اتّسعت («هـ وتوفي»)
                if g > max(10.0, 0.7 * size) and _is_ar(seq[n - 1][0]) and _is_ar(b[0]):
                    out.append("  ")        # بين شطرَي البيت
                elif g > gap:
                    out.append(" ")
        if b[0] == "ـ":
            continue
        out.append(b[0] + "".join(sorted(b[3], key=lambda c: (c != "ّ", c))))

    def bid(t: str) -> str:
        return unicodedata.bidirectional(t[0]) if t and not t.isspace() else "WS"

    res, i = [], 0
    while i < len(out):     # كلُّ مقطعٍ من الأرقام واللاتينيّة يعود إلى ترتيبه من اليسار إلى اليمين
        if bid(out[i]) in LTR:
            j = i
            while j + 1 < len(out) and (bid(out[j + 1]) in LTR or (
                    bid(out[j + 1]) in SEP | {"WS"} and j + 2 < len(out) and bid(out[j + 2]) in LTR
                    and not out[j + 1].isspace())):
                j += 1
            res.extend(reversed(out[i:j + 1]))
            i = j + 1
        else:
            res.append(out[i])
            i += 1
    s = unicodedata.normalize("NFC", "".join(res))
    return re.sub(r"[ ]{3,}", "  ", s).strip()


def page_variants(page, fitz) -> list:
    """ثلاثُ صيغٍ لأسطر الصفحة: [نصُّ المكتبة، المبنيّ، المبنيّ بعكس المركّبات] — كلُّ سطرٍ {t, x, y, w, h, size}."""
    W, H = page.rect.width or 1, page.rect.height or 1
    flags = fitz.TEXT_PRESERVE_WHITESPACE | fitz.TEXT_MEDIABOX_CLIP
    try:
        d = page.get_text("rawdict", flags=flags)
    except Exception:
        # عطبٌ في المكتبة (1.28.2): فكُّها لبعض الحروف المركّبة يُخرج رقمَ حرفٍ لا يصحّ فتسقط الصفحةُ كلُّها.
        # فتُطلب المركّباتُ كما هي، وclean_raw يفكّها. (لوحظ في صفحتَي المرجع 03 و05: كان نصُّهما يُؤخذ بلا بناء.)
        d = page.get_text("rawdict", flags=flags | fitz.TEXT_PRESERVE_LIGATURES)
    native, built, flipped = [], [], []
    for b in d.get("blocks", []):
        if b.get("type") != 0:
            continue
        for ln in b.get("lines", []):
            chars, sizes, text = [], [], []
            for s in ln.get("spans", []):
                if s.get("size", 0) < 4:            # نصٌّ خفيٌّ بحجمٍ ضئيل لا يُرى في الصفحة
                    continue
                for c in s.get("chars", []):
                    text.append(c["c"])
                    chars.append((c["c"], c["bbox"][0], c["bbox"][2]))
                    if c["c"].strip():
                        sizes.append(s["size"])
            t = "".join(text)
            if not t.strip():
                continue
            x0, y0, x1, y1 = ln["bbox"]
            size = sorted(sizes)[len(sizes) // 2] if sizes else 10.0
            geo = {"x": x0 / W, "y": y0 / H, "w": (x1 - x0) / W, "h": max(1e-4, (y1 - y0) / H), "size": size,
                   "pw": W, "sp": t != t.strip()}     # عرضُ الصفحة، وهل في طرف القطعة مسافةٌ في الملف (لضمّ القطع)
            native.append(dict(geo, t=arabic.clean_raw(t)))
            horizontal = abs(ln.get("dir", (1, 0))[1]) < 0.1
            if horizontal and any(_is_ar(c[0]) for c in chars):
                built.append(dict(geo, t=arabic.clean_raw(rebuild(chars, size, False))))
                flipped.append(dict(geo, t=arabic.clean_raw(rebuild(chars, size, True))))
            else:
                built.append(dict(geo, t=arabic.clean_raw(t)))
                flipped.append(dict(geo, t=arabic.clean_raw(t)))
    return [native, built, flipped]


def native_lines(page, fitz) -> list:
    """نصُّ المكتبة كما هو بأسطره (احتياطٌ إن تعذّرت قراءةُ الحروف بمواضعها)."""
    W, H = page.rect.width or 1, page.rect.height or 1
    out = []
    try:
        d = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE | fitz.TEXT_MEDIABOX_CLIP)
    except Exception:
        return out
    for b in d.get("blocks", []):
        if b.get("type") != 0:
            continue
        for ln in b.get("lines", []):
            spans = [x for x in ln.get("spans", []) if x.get("text") and x.get("size", 0) >= 4]
            t = "".join(x["text"] for x in spans)
            if not t.strip():
                continue
            x0, y0, x1, y1 = ln["bbox"]
            out.append({"t": arabic.clean_raw(t), "x": x0 / W, "y": y0 / H, "w": (x1 - x0) / W,
                        "h": max(1e-4, (y1 - y0) / H), "size": max(x["size"] for x in spans)})
    return out


def score(lines: list) -> int:
    words = arabic.normalize(" ".join(l["t"] for l in lines)).split()
    return sum(1 for w in words if w in arabic.COMMON)


NAMES = ["كما هو", "مبنيّ", "مبنيّ بعكس المركّبات"]


def sample_bias(doc, fitz, total: int) -> list:
    """مجموعُ درجات الصيغ الثلاث في عيّنةٍ من ثماني صفحاتٍ متباعدة: يرجّح بها الكتابُ صيغتَه عند التساوي."""
    bias = [0, 0, 0]
    for f in (0.05, 0.15, 0.3, 0.45, 0.6, 0.75, 0.85, 0.95):
        i = min(total - 1, int(total * f))
        try:
            for k, v in enumerate(page_variants(doc[i], fitz)):
                bias[k] += score(v)
        except Exception:
            continue
    return bias


def best_lines(page, fitz, bias=None):
    """أحسنُ الصيغ الثلاث للصفحة بعدد الكلمات الشائعة؛ وعند التساوي صيغةُ الكتاب الغالبة (bias)، ثمّ نصُّ المكتبة كما هو.
    ← (الأسطر، اسمُ الصيغة)."""
    try:
        variants = page_variants(page, fitz)
    except Exception:           # عطبٌ في مكتبة القراءة مع رمزٍ غريب في الصفحة: نصُّها كما هو، والقارئُ يقرّر
        return native_lines(page, fitz), "تعذّر البناء"
    bias = bias or [0, 0, 0]
    scores = [score(v) for v in variants]
    best = max(range(3), key=lambda i: (scores[i], bias[i], -i))
    for k in range(3):
        bias[k] += scores[k]
    return variants[best], NAMES[best]
