"""إصلاحُ خريطة الحروف (ToUnicode) المعيبة في ملفّات بي دي إف المحفوظة من وورد.

العلّة: وورد يكتب في الملفّ لكلّ رمزٍ من رموز الخطّ الحرفَ الذي يقابله، ويخطئ في بعضها: رمزُ «ب» المنفردة يُسجَّل «ط»
فتُستخرج «أقطاب» «أقطاط»، ورمزُ «ف» المتطرّفة يُسجَّل مسافةً فتُستخرج «الكشف» «الكش». والصورةُ سليمة، والخطأُ في
الخريطة وحدها؛ فكان البرنامج يجد النصَّ المضمَّن معيبًا فيقرأ الكتابَ كلَّه من صوره آليًّا، وهو أبطأ وأقلّ دقّة.

العلاج: رموزُ الخطّ العربيّ مرتّبةٌ في الخطّ بترتيب يونيكود: الحروفُ المنفردة على ترتيب الحروف (ء آ أ … ي)، وصورُها
المتّصلة على ترتيب صور العرض (ﺎ ﺐ ﺑ ﺒ …). فأكثرُ الخريطة يقع على خطٍّ مستقيم: رقمُ الرمز + إزاحةٌ ثابتة = رقمُ الحرف.
فما شذّ عن الخطّ وجاراه القريبان عليه، يُردّ إليه. ولا يُمسّ رمزٌ ليس بين جارين يشهدان للإزاحة نفسها، ولا ما لا
يقع على حرفٍ عربيّ.

والخطُّ السليم قد ينقطع ترتيبُه (رموزٌ دخيلة في وسطه، أو حروفٌ ساقطة منه): فهو ترتيبان سليمان لا ترتيبٌ واحدٌ معيب.
وقع ذلك في خطوطٍ حقيقيّة (SimplifiedArabic وadwa-assalaf وAAAGoldenLotus)، وكانت الصيغةُ الأولى تبدّل فيها حروفًا
سليمة (ث←خ، ط←ظ، ي←ج). فالقاعدةُ في fixes: عند الشكّ لا يُصلَح شيء. وما تتركه بلا إصلاح يبقى على حاله قبل هذا
الملفّ: نصٌّ معيبٌ يُقرأ آليًّا.

التعديلُ في الذاكرة وحدها: الملفُّ على القرص لا يُكتب. وبعده يُقابَل النصُّ بالصورة كما كان (pdf._text_layer_score)،
فإن بقي معيبًا قُرئ آليًّا كما كان.
"""
import re
import unicodedata

MIN_SUPPORT = 8        # إزاحةٌ يشهد لها هذا العددُ من الرموز فأكثر تُعدّ ترتيبًا للخطّ
WINDOW = 4             # أبعدُ جارٍ شاهدٍ عن الرمز المُصلَح
CHAIN = 4              # سلسلةٌ متّصلةٌ من الشهود بهذا الطول فأكثر لا تكون عَرَضًا (العَرَضيّةُ ثلاثةٌ على الأكثر)
EXCL = 3               # شهودٌ للإزاحة المجاورة ليسوا من شهود الأقوى بهذا العدد فأكثر: ترتيبٌ ثانٍ لا ظلّ
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


def _chains(ws: set, present: list) -> dict:
    """لكلّ شاهد: طولُ سلسلته، وهي الشهودُ المتوالون في الخريطة بلا رمزٍ بينهم يخالف، ولا فجوةٍ أوسعَ من WINDOW."""
    out, run, last = {}, [], None
    for g in present:
        if g in ws and (not run or g - last <= WINDOW):
            run.append(g)
        else:
            for x in run:
                out[x] = len(run)
            run = [g] if g in ws else []
        last = g
    for x in run:
        out[x] = len(run)
    return out


def fixes(m: dict) -> dict:
    """ما يُصلَح من الخريطة: {رقم الرمز: الحرف الصحيح}.

    الإزاحةُ المجاورة للصحيحة (±١…٣) يشهد لها بعضُ صور الحرف الواحد عَرَضًا، وشهودُها كلُّهم من شهود الصحيحة: فهي
    ظلٌّ لها يُطرح. وإن كان للمجاورة شهودٌ ليسوا للأقوى (EXCL فأكثر) فهما ترتيبان حقيقيّان متنازعان: خطٌّ في وسطه
    رموزٌ دخيلة، ما قبلها ترتيبٌ سليم وما بعدها ترتيبٌ سليم، لا ترتيبٌ واحدٌ معيبٌ ذيلُه. فيُقسم الشهودُ بينهما
    بالسلاسل المتّصلة: كلُّ رمزٍ للترتيب الذي سلسلتُه فيه أطول، ولا يُصلِح المتنازعُ شيئًا إلّا بسلسلةٍ طولُها CHAIN.
    ولا يُصلَح:
      - رمزٌ يشهد لترتيبٍ آخر (حرفُه المسجَّل صحيحٌ هناك)؛
      - ولا رمزٌ يصير بالإصلاح حرفًا له رمزُه في الخطّ، أو استوفت جاراتُه صورَه (الحرفُ لا يتكرّر في الترتيب:
        فهذا دخيلٌ عند ملتقى ترتيبين)؛
      - ولا رمزٌ ليس بين شاهدين للترتيب نفسه، إلّا عند طرف الترتيب إن لم يكن حرفُه المسجَّل على نسق جاره.
    وعند الشكّ لا يُصلَح شيء: القراءةُ الآليّة كما كانت خيرٌ من نصٍّ مبدَّل الحروف."""
    codes, reg = {}, {}             # لكلّ رمز: الأرقامُ التي يصحّ أن يقع عليها بحسب حرفه المسجَّل، وحرفُه
    for g, s in m.items():
        if len(s) == 1 and _letter(ord(s)):
            reg[g] = _letter(ord(s))
            codes[g] = {ord(reg[g]), *_FORMS.get(reg[g], ())} if 0x0600 <= ord(s) <= 0x06FF else {ord(s)}
        elif s in _FORMS:
            codes[g] = set(_FORMS[s])
    support = {}
    for g, cs in codes.items():
        for c in cs:
            support.setdefault(c - g, set()).add(g)
    # حرفٌ عربيٌّ من غير الثمانية والعشرين (ی ک گ… وصورُها) مسجَّلٌ على وجهه: لا يُمسّ
    alien = {g for g, s in m.items() if len(s) == 1 and g not in reg and unicodedata.category(s) == "Lo"
             and ("\u0600" <= s <= "\u06ff" or "\u0750" <= s <= "\u077f" or "\ufb50" <= s <= "\ufdff"
                  or "\ufe70" <= s <= "\ufeff")}
    cand, tied, shadows = [], set(), []     # الأقوى شهادةً أوّلًا، وتُطرح ظلالُه
    for k, gs in sorted(support.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        if len(gs) < MIN_SUPPORT:
            break
        over = [t for t in cand if abs(k - t) <= 3 and len(gs - support[t]) < EXCL]
        if not over:
            cand.append(k)
        else:
            shadows.append(k)
        tied.update(t for t in over if len(support[t]) == len(gs))     # ظلٌّ بقوّة أصله: لا يُدرى أيُّهما الترتيب
    cand = [k for k in cand if k not in tied]
    rivals = {k for k in cand if any(t != k and abs(k - t) <= 3 for t in cand)}
    # المسافةُ المسجَّلة علامةُ وورد لما جهله، فلا تشهد ولا تقطع سلسلة؛ ويقطعها ما سُجّل له نصٌّ يخالف
    present = sorted(g for g, s in m.items() if s.strip())
    chain = {k: _chains(support[k], present) for k in cand}
    owner, held = {}, set()         # كلُّ شاهدٍ لترتيبٍ واحد؛ وما تساوى فيه ترتيبان لا يُمسّ ولا يشهد
    held |= alien
    for t in tied:
        held |= support[t]
    for k in shadows:               # ما وافق الظلَّ مع جارٍ له ولم يوافق ترتيبًا: لعلّه ترتيبٌ قصيرٌ سليم، فلا يُمسّ
        ch = _chains(support[k], present)
        held |= {g for g in support[k] if ch[g] >= 2 and not any(g in support[t] for t in cand)}
    for g in codes:
        best = sorted(((chain[k][g], len(support[k]), k) for k in cand if g in support[k]), reverse=True)
        if not best:
            continue
        even = len(best) > 1 and best[0][0] == best[1][0] and (
            best[0][1] == best[1][1] or abs(best[0][2] - best[1][2]) <= 3)      # بين متنازعَين: السلسلةُ وحدها تحكم
        if even or (best[0][2] in rivals and best[0][0] < 2):
            held.add(g)             # ومنه الشاهدُ المنفرد في ترتيبٍ متنازع: قد يكون عَرَضًا
        else:
            owner[g] = best[0][2]
    lines = {}
    for g, k in owner.items():
        lines.setdefault(k, set()).add(g)
    for k in list(lines):           # ما بقي للترتيب بعد القسمة: أيكفي؟
        if len(lines[k]) < MIN_SUPPORT or (k in rivals and max(_chains(lines[k], present).values()) < CHAIN):
            held |= lines.pop(k)
    taken = {g + k for k, gs in lines.items() for g in gs}      # حروفُ الخطّ التي عُرفت رموزُها
    out, guess = {}, set()          # guess: حرفٌ مسجَّلٌ بُدّل عند طرف ترتيب، فلا يُبنى عليه طرفٌ آخر
    for k, own in sorted(lines.items(), key=lambda kv: -len(kv[1])):
        ok = set(own)               # الشهود، ويُزاد عليهم ما أُصلح: فالمُصلَح يشهد لجاره
        lo, hi = min(own), max(own)
        changed = True
        while changed:
            changed = False
            for g in range(lo - 1, hi + 2):
                if g not in m or g in owner or g in held or g in out:
                    continue
                want = _letter(g + k)
                if want is None or g + k in taken:
                    continue
                if reg.get(g) == want:
                    continue
                # للحرف في الترتيب صورُه لا أكثر (وفي ترتيب الحروف المنفردة رمزٌ واحد): فإن استوفتها جاراتُه فهو دخيل
                room = len(_FORMS.get(want, ())) if g + k >= 0xFE80 else 1
                if sum(1 for x in range(g - 2 * WINDOW + 1, g + 2 * WINDOW)
                       if x != g and out.get(x, reg.get(x)) == want) >= room:
                    continue
                left = [x for x in range(g - WINDOW, g) if x in ok]
                right = [x for x in range(g + 1, g + WINDOW + 1) if x in ok]
                if not (left and right):
                    # طرفُ الترتيب: ملاصقٌ لثلاثة شهودٍ متقاربين من جهةٍ واحدة
                    if g - 1 in ok and len(left) >= 3:
                        near, up = g - 1, True
                    elif g + 1 in ok and len(right) >= 3:
                        near, up = g + 1, False
                    else:
                        continue
                    # وحرفُه المسجَّل إن جاء على نسق جاره (هو أو ما يليه بقليل) فلعلّه أوّلُ ترتيبٍ آخر؛
                    # ولا يُبنى تبديلُ حرفٍ على تبديل حرفٍ قبله، كيلا يسري التبديلُ في ترتيبٍ قصيرٍ سليم
                    a, b = reg.get(g), _letter(near + k)
                    if not a and m[g].strip():      # مسجَّلٌ له نصٌّ ليس حرفًا (مركّبٌ، أو علامة، أو غيرُ عربيّ):
                        continue                    # لا يُملأ عند الطرف، فلعلّه رمزٌ دخيلٌ بعد آخر الترتيب
                    if a and (near in guess or (b and 0 <= (ord(a) - ord(b)) * (1 if up else -1) <= 3)):
                        continue
                    # أو الحرفُ نفسُه مسجَّلٌ لرمزٍ قريبٍ وراءه (ترتيبٌ قصيرٌ قبل رموزٍ دخيلة)
                    wide = range(g - WINDOW, g + 3 * WINDOW + 1) if up else range(g - 3 * WINDOW, g + WINDOW + 1)
                    if sum(1 for x in wide if x != g and out.get(x, reg.get(x)) == want) >= room:
                        continue
                    if a:
                        guess.add(g)
                out[g] = want
                ok.add(g)
                taken.add(g + k)
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
