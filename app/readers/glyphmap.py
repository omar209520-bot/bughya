"""إصلاحُ خريطة الحروف (ToUnicode) المعيبة في ملفّات بي دي إف المحفوظة من وورد، من الخطّ المضمَّن في الملفّ نفسه.

العلّة: وورد يكتب في الملفّ لكلّ رمزٍ من رموز الخطّ الحرفَ الذي يقابله، ويخطئ في خطوطٍ بعينها (Traditional Arabic وأخواتُه):
حروفٌ مرسومةٌ تُسجَّل مسافةً («الكشف» ← «الكش»)، وحرفٌ يُسجَّل غيرَه، والتطويلُ يُسجَّل «ة». والصورةُ سليمة، والخطأ في
الخريطة وحدها؛ فكان البرنامج يجد النصَّ معيبًا فيقرأ الكتابَ كلَّه من صوره آليًّا، وهو أبطأ وأقلّ دقّة.

العلاج: وورد يضمّن الخطَّ بأرقام رموزه الأصليّة ويترك فيه جدولَ حروفه (cmap)، وهو جدولُ صانع الخطّ: لكلّ حرفٍ رمزُه. فيُقرأ
الجدولُ مقلوبًا (لكلّ رمزٍ حرفُه)، وتُردّ صورُ العرض والمركّباتُ إلى حروفها بترتيب القراءة (ﻓﻲ ← في)، وتُكتب في خريطة الملفّ.

متى يُمسّ الملفّ؟ إن ثبت العيبُ يقينًا: في خطٍّ منه (بكلّ نسخه في الملفّ) GATE حرفًا فأكثر مرسومةً سُجّلت مسافة. عندئذٍ تُصلَح
خطوطُ الملفّ كلُّها، فكلُّها من الصانع نفسه. والملفُّ الذي لم يثبت فيه ذلك لا يُمسّ: جدولُ الخطّ قد يخالف استعمالَ وورد للرمز
(هاءٌ مبتدأة، لفظُ الجلالة)، فلا يُبدَّل به ما هو صحيح.

ولا يُبدَّل إلّا ما عُرف حرفًا عربيًّا: الأقواسُ والأرقامُ وعلاماتُ الترقيم تبقى كما سجّلها وورد (القوسُ يُعكس في السطر العربيّ،
فرسمُه لا يدلّ على حرفه).

التعديلُ في الذاكرة وحدها: الملفُّ على القرص لا يُكتب. وبعده يُقابَل النصُّ بالصورة كما كان (pdf._text_layer_score)، فإن
بقي معيبًا قُرئ آليًّا كما كان. ما قيس وما لم يُقَس في «اقرأني».
بالمكتبة القياسيّة وحدها: جداولُ الخطّ اللازمة (cmap و loca) تُقرأ هنا.
"""
import re
import struct
import unicodedata

GATE = 3               # أقلُّ عددٍ من الحروف المرسومة المسجَّلة مسافةً (في الخطّ بكلّ نسخه) يثبت به عيبُ الملفّ
_HEX = "[0-9A-Fa-f]"
_ARABIC = re.compile("[؀-ۿ]")


# ───────────────────── خريطةُ الملفّ: قراءتُها وكتابتُها ─────────────────────

def _u16(h: str) -> str:
    return bytes.fromhex(h).decode("utf-16-be", "replace")


def parse(cmap: str) -> dict:
    """خريطةُ الملفّ: {رقم الرمز: النصّ المقابل}."""
    m = {}
    for kind, blk in re.findall(r"begin(bfchar|bfrange)(.*?)endbf", cmap, re.S):
        if kind == "bfchar":
            for a, b in re.findall(r"<(%s+)>\s*<(%s*)>" % (_HEX, _HEX), blk):
                m[int(a, 16)] = _u16(b)
            continue
        for a, b, rest in re.findall(r"<(%s+)>\s*<(%s+)>\s*(\[[^\]]*\]|<%s*>)" % (_HEX, _HEX, _HEX), blk):
            a, b = int(a, 16), int(b, 16)
            if b - a > 0xFFFF:
                continue
            if rest.startswith("["):
                for i, x in enumerate(re.findall(r"<(%s*)>" % _HEX, rest)):
                    m[a + i] = _u16(x)
            else:
                s = _u16(rest[1:-1])
                if s:
                    for i in range(b - a + 1):
                        m[a + i] = s[:-1] + chr(min(0x10FFFF, ord(s[-1]) + i))
    return m


def write(m: dict) -> bytes:
    rows = ["<%04X> <%s>" % (g, s.encode("utf-16-be").hex().upper()) for g, s in sorted(m.items()) if s]
    parts = ["/CIDInit /ProcSet findresource begin", "12 dict begin", "begincmap",
             "/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def",
             "/CMapName /Adobe-Identity-UCS def", "/CMapType 2 def",
             "1 begincodespacerange", "<0000> <FFFF>", "endcodespacerange"]
    for i in range(0, len(rows), 100):
        parts += ["%d beginbfchar" % len(rows[i:i + 100]), *rows[i:i + 100], "endbfchar"]
    parts += ["endcmap", "CMapName currentdict /CMap defineresource pop", "end", "end"]
    return "\n".join(parts).encode("ascii")


# ───────────────────── جداولُ الخطّ المضمَّن ─────────────────────

def _tables(buf: bytes) -> dict:
    """{اسم الجدول: (موضعه، طوله)} في خطّ TrueType."""
    if len(buf) < 12 or buf[:4] not in (b"\x00\x01\x00\x00", b"true", b"OTTO"):
        return {}
    out = {}
    for i in range(struct.unpack(">H", buf[4:6])[0]):
        rec = buf[12 + 16 * i: 28 + 16 * i]
        if len(rec) < 16:
            break
        tag, _sum, off, ln = struct.unpack(">4sLLL", rec)
        out[tag.decode("latin-1")] = (off, ln)
    return out


def _cmap(buf: bytes, tabs: dict) -> dict:
    """{رقم يونيكود: رقم الرمز} من أحسن جداول الحروف في الخطّ (الصيغتان 12 و4)."""
    if "cmap" not in tabs:
        return {}
    base = tabs["cmap"][0]
    n = struct.unpack(">H", buf[base + 2: base + 4])[0]
    subs = {}
    for i in range(n):
        pid, eid, off = struct.unpack(">HHL", buf[base + 4 + 8 * i: base + 12 + 8 * i])
        subs[(pid, eid)] = base + off
    for key in ((3, 10), (0, 6), (0, 4), (3, 1), (0, 3), (0, 2), (0, 1), (0, 0)):
        if key not in subs:
            continue
        o = subs[key]
        fmt = struct.unpack(">H", buf[o: o + 2])[0]
        out = {}
        if fmt == 12:
            ng = struct.unpack(">L", buf[o + 12: o + 16])[0]
            for i in range(min(ng, 100000)):
                a, b, g = struct.unpack(">LLL", buf[o + 16 + 12 * i: o + 28 + 12 * i])
                if b - a > 0x20000:
                    continue
                for cp in range(a, b + 1):
                    out[cp] = g + cp - a
        elif fmt == 4:
            seg = struct.unpack(">H", buf[o + 6: o + 8])[0] // 2
            p = o + 14
            end = struct.unpack(">%dH" % seg, buf[p: p + 2 * seg])
            p += 2 * seg + 2
            start = struct.unpack(">%dH" % seg, buf[p: p + 2 * seg])
            p += 2 * seg
            delta = struct.unpack(">%dh" % seg, buf[p: p + 2 * seg])
            p += 2 * seg
            rng = struct.unpack(">%dH" % seg, buf[p: p + 2 * seg])
            for i in range(seg):
                if start[i] == 0xFFFF:
                    continue
                for cp in range(start[i], end[i] + 1):
                    if rng[i] == 0:
                        g = (cp + delta[i]) & 0xFFFF
                    else:
                        q = p + 2 * i + rng[i] + 2 * (cp - start[i])
                        if q + 2 > len(buf):
                            continue
                        g = struct.unpack(">H", buf[q: q + 2])[0]
                        if g:
                            g = (g + delta[i]) & 0xFFFF
                    if g:
                        out[cp] = g
        else:
            continue
        if out:
            return out
    return {}


def _drawn(buf: bytes, tabs: dict):
    """دالّةٌ: هل للرمز رسمٌ في الخطّ؟ (من جدول مواضع الرسوم loca). وNone إن لم يكن الخطُّ برسومٍ من هذا النوع."""
    if not all(k in tabs for k in ("loca", "head", "maxp")):
        return None
    long = struct.unpack(">h", buf[tabs["head"][0] + 50: tabs["head"][0] + 52])[0]
    n = struct.unpack(">H", buf[tabs["maxp"][0] + 4: tabs["maxp"][0] + 6])[0]
    off, ln = tabs["loca"]
    size = 4 if long else 2
    cnt = min(n + 1, ln // size)
    loca = struct.unpack(">%d%s" % (cnt, "L" if long else "H"), buf[off: off + cnt * size])
    return lambda g: 0 <= g < cnt - 1 and loca[g + 1] > loca[g]


def _text(cp: int) -> str:
    """نصُّ رقم يونيكود بعد ردّ صور العرض والمركّبات إلى حروفها بترتيب القراءة (ﻓﻲ ← في)."""
    if 0xFDF0 <= cp <= 0xFDFD and cp != 0xFDF2:           # ﷺ وأخواتها كلمةٌ برمزٍ واحد: تبقى كما هي
        return chr(cp)
    s = unicodedata.normalize("NFKC", chr(cp))
    if len(s) > 1 and any(unicodedata.combining(c) for c in s):
        s = s.replace(" ", "").replace("ـ", "")       # صورةُ الحركة المنفردة «مسافة+حركة» والمتوسّطة «تطويل+حركة»
    return s


def _rank(cp: int):
    return (0 if 0x600 <= cp <= 0x6FF else 1 if 0xFE70 <= cp <= 0xFEFF else 2 if 0xFB50 <= cp <= 0xFDFF else 3, cp)


def letters(buf: bytes):
    """من الخطّ المضمَّن: ({رقم الرمز: نصّه}، دالّةُ «أللرمز رسم؟»)."""
    tabs = _tables(buf)
    rev = {}
    for cp, g in _cmap(buf, tabs).items():
        if cp >= 0x20 and not 0xE000 <= cp <= 0xF8FF:
            rev.setdefault(g, []).append(cp)
    return {g: _text(min(cps, key=_rank)) for g, cps in rev.items()}, _drawn(buf, tabs)


# ───────────────────── الإصلاح ─────────────────────

def _key(name: str) -> str:
    return re.sub(r"[\s,\-_]+", "", name or "").lower()


def repair(doc) -> int:
    """يُصلح خرائطَ خطوط الملفّ المفتوح (في الذاكرة) إن ثبت عيبُها، ويعيد عددَ الرموز التي بُدّل نصُّها."""
    try:
        n = doc.xref_length()
    except Exception:
        return 0
    found, done, family = [], set(), {}
    for xref in range(1, n):
        try:
            obj = doc.xref_object(xref, compressed=True)
            if "/Type0" not in obj or "/Identity-H" not in obj:
                continue
            t = re.search(r"/ToUnicode\s+(\d+)\s+0\s+R", obj)
            if not t or int(t.group(1)) in done:
                continue
            tx = int(t.group(1))
            done.add(tx)
            name = (re.search(r"/BaseFont\s*/([^\s/\[<>]+)", obj) or [None, ""])[1].split("+")[-1]
            buf = doc.extract_font(xref)[3]
            if not buf:
                continue
            shape, drawn = letters(buf)
            if not shape or drawn is None:
                continue
            m = parse(doc.xref_stream(tx).decode("latin-1"))
            blank = sum(1 for g, s in m.items() if not s.strip() and g in shape
                        and unicodedata.category(shape[g][0]) == "Lo" and drawn(g))
            k = _key(re.sub(r"#([0-9A-Fa-f]{2})", lambda x: chr(int(x.group(1), 16)), name))
            family[k] = family.get(k, 0) + blank
            found.append((tx, m, shape))
        except Exception:
            continue
    if not any(v >= GATE for v in family.values()):
        return 0
    total = 0
    for tx, m, shape in found:
        try:
            fx = {g: s for g, s in shape.items() if _ARABIC.search(s) and m.get(g) != s}
            if fx:
                m.update(fx)
                doc.update_stream(tx, write(m))
                total += len(fx)
        except Exception:
            continue
    return total
