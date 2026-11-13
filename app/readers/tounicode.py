"""إصلاحُ خريطة الحروف (ToUnicode) المعيبة في ملفّات بي دي إف المحفوظة من وورد.

العلّة: وورد يكتب في الملفّ لكلّ رمزٍ من رموز الخطّ الحرفَ الذي يقابله، ويخطئ في بعضها: رمزُ «ب» المنفردة يُسجَّل «ط»
فتُستخرج «أقطاب» «أقطاط»، ورمزُ «ف» المتطرّفة يُسجَّل مسافةً فتُستخرج «الكشف» «الكش». والصورةُ سليمة، والخطأُ في
الخريطة وحدها؛ فكان البرنامج يجد النصَّ المضمَّن معيبًا فيقرأ الكتابَ كلَّه من صوره آليًّا، وهو أبطأ وأقلّ دقّة.

العلاج: رموزُ الخطّ العربيّ مرتّبةٌ في الخطّ بترتيب يونيكود: الحروفُ المنفردة على ترتيب الحروف (ء آ أ … ي)، وصورُها
المتّصلة على ترتيب صور العرض (ﺎ ﺐ ﺑ ﺒ …). فأكثرُ الخريطة يقع على خطٍّ مستقيم: رقمُ الرمز + إزاحةٌ ثابتة = رقمُ الحرف.
فما شذّ عن الخطّ وجاراه القريبان عليه، يُردّ إليه. ولا يُمسّ رمزٌ ليس بين جارين يشهدان للإزاحة نفسها، ولا ما لا
يقع على حرفٍ عربيّ.

التعديلُ في الذاكرة وحدها: الملفُّ على القرص لا يُكتب. وبعده يُقابَل النصُّ بالصورة كما كان (pdf._text_layer_score)،
فإن بقي معيبًا قُرئ آليًّا كما كان.
"""
import re
import unicodedata

MIN_SUPPORT = 8        # إزاحةٌ يشهد لها هذا العددُ من الرموز فأكثر تُعدّ ترتيبًا للخطّ
WINDOW = 4             # أبعدُ جارٍ شاهدٍ عن الرمز المُصلَح
_HEX = "[0-9A-Fa-f]"

# لكلّ حرفٍ عربيّ: أرقامُ صور عرضه (المنفردة والمتطرّفة والمبتدأة والمتوسّطة)
_FORMS = {}
for _cp in range(0xFE80, 0xFEFD):
    _d = unicodedata.normalize("NFKC", chr(_cp))
    if _d != chr(_cp):              # ومنها المركّبات «لا لأ لإ لآ»: تشهد للترتيب ولا يُصلَح إليها
        _FORMS.setdefault(_d, []).append(_cp)


def _letter(cp: int):
    """الحرفُ الذي يقابله هذا الرقم إن كان حرفًا عربيًّا أو صورةَ عرضٍ لحرفٍ واحد، وإلّا None."""
    if 0x0621 <= cp <= 0x063A or 0x0640 <= cp <= 0x064A:
        return chr(cp)
    if 0xFE80 <= cp <= 0xFEFC:
        d = unicodedata.normalize("NFKC", chr(cp))
        return d if len(d) == 1 else None
    return None


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


def fixes(m: dict) -> dict:
    """ما يُصلَح من الخريطة: {رقم الرمز: الحرف الصحيح}."""
    codes = {}                      # لكلّ رمز: الأرقامُ التي يصحّ أن يقع عليها بحسب حرفه المسجَّل
    for g, s in m.items():
        if len(s) == 1 and _letter(ord(s)) == s:
            codes[g] = {ord(s), *_FORMS.get(s, ())}
        elif s in _FORMS:
            codes[g] = set(_FORMS[s])
    support = {}
    for g, cs in codes.items():
        for c in cs:
            support.setdefault(c - g, set()).add(g)
    out, settled, taken = {}, set(), []
    # الأقوى شهادةً أوّلًا. والإزاحةُ المجاورة للصحيحة (±١…٣) يشهد لها بعضُ رموز الحرف الواحد عَرَضًا،
    # فلا تُقبل إزاحةٌ إلّا بشهودٍ لم تستوفهم إزاحةٌ أقوى، ولا يُمسّ رمزٌ شهد لإزاحةٍ مقبولة.
    for k, gs in sorted(support.items(), key=lambda kv: -len(kv[1])):
        own = gs - settled
        if len(own) < MIN_SUPPORT or any(abs(k - t) <= 3 for t in taken):
            continue
        taken.append(k)
        ok = set(own)               # الشهود، ويُزاد عليهم ما أُصلح: فالمُصلَح يشهد لجاره
        settled |= own
        lo, hi = min(own), max(own)
        changed = True
        while changed:
            changed = False
            for g in range(lo - 1, hi + 2):
                if g in settled or g in out or g not in m:
                    continue
                want = _letter(g + k)
                if want is None or m[g] == want:
                    continue
                left = [x for x in range(g - WINDOW, g) if x in ok]
                right = [x for x in range(g + 1, g + WINDOW + 1) if x in ok]
                # بين شاهدين، أو ملاصقٌ لثلاثة شهودٍ متقاربين من جهةٍ واحدة (طرفُ الترتيب)
                if (left and right) or (g - 1 in ok and len(left) >= 3) or (g + 1 in ok and len(right) >= 3):
                    out[g] = want
                    ok.add(g)
                    changed = True
    return out


def _write(m: dict) -> bytes:
    rows = ["<%04X> <%s>" % (g, s.encode("utf-16-be").hex().upper()) for g, s in sorted(m.items()) if s]
    parts = ["/CIDInit /ProcSet findresource begin", "12 dict begin", "begincmap",
             "/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def",
             "/CMapName /Adobe-Identity-UCS def", "/CMapType 2 def",
             "1 begincodespacerange", "<0000> <FFFF>", "endcodespacerange"]
    for i in range(0, len(rows), 100):
        parts += ["%d beginbfchar" % len(rows[i:i + 100]), *rows[i:i + 100], "endbfchar"]
    parts += ["endcmap", "CMapName currentdict /CMap defineresource pop", "end", "end"]
    return "\n".join(parts).encode("ascii")


def repair(doc) -> int:
    """يُصلح خرائطَ الخطوط العربيّة المعيبة في الملفّ المفتوح (في الذاكرة)، ويعيد عددَ الرموز المُصلَحة."""
    total, done = 0, set()
    try:
        n = doc.xref_length()
    except Exception:
        return 0
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
            m = parse(doc.xref_stream(tx).decode("latin-1"))
            fx = fixes(m)
            if not fx:
                continue
            m.update(fx)
            doc.update_stream(tx, _write(m))
            total += len(fx)
        except Exception:
            continue
    return total
