"""قاموسُ الكلمات المعروفة: يُبنى من الكتب التي قُرئ نصُّ ملفّها سليمًا في مكتبة المستخدم، ومعه ألفاظُ القرآن.
فائدتُه أن يُعلِّم في الصفحات المقروءة آليًّا الكلماتِ التي لا يعرفها، لتُراجَع بالصورة. ولا يُصحّح شيئًا.

قيس على صفحات المرجع بقاموسٍ من ٢٤ كتابًا: عَلَّم ٤١٪ من الكلمات الخاطئة، وكان ثلثُ ما علَّمه صحيحًا. فالكلمةُ غير
المعلَّمة قد تكون خاطئة أيضًا (كلمةٌ صحيحةٌ في غير موضعها)، ويُقال ذلك للمستخدم.

والسياق (فهرسُ الأزواج المتجاورة، lexicon.pairs): أكثرُ خطأ القراءة الآليّة في النقط، فيُنتج كلمةً أخرى صحيحة («قال» ← «فال»)
يعرفها القاموس فلا تُعلَّم. فتُعلَّم الكلمةُ المعروفة أيضًا إن اجتمع فيها ثلاثة:
    ١. لم يَرِد زوجُها مع جارتها السابقة ولا اللاحقة في كتب المستخدم؛
    ٢. ولها بديلٌ بإبدال حرفٍ واحدٍ بآخرَ من مجموعة نقطه (DOTS) يعرفه القاموس، وليس أندرَ منها فيه؛
    ٣. وورد زوجُ البديل مع إحدى الجارتين PAIR_MIN مرّةً فأكثر.
والفهرسُ مرشّحا بلوم (ما ورد، وما تكرّر) لا قائمةُ الأزواج: مكتبةٌ من عشرات الكتب فيها ملايين الأزواج.
قيس بالمحاكاة على نصّ القرآن وحده (tests/measure_marks.py --sim)، ولم يُقَس بعدُ على قراءةٍ آليّةٍ حقيقيّة.
"""
import collections
import hashlib
import re
import struct
import zlib

import arabic
import common

PATH = common.DATA / "lexicon.json"
MIN_WORDS = 3000            # كلماتٌ مختلفة من كتب المستخدم النصّيّة؛ أقلُّ منها لا يُعلَّم شيء (بـ٣٧٦٧: صحّ ٧ من ١٦ معلَّمة في صفحة 06)
PREFIX = "وفبكل"
OCR_BOOKS = 3               # كلمةُ القراءة الآليّة تدخل القاموس إن وردت في هذا العدد من الكتب المختلفة
PAIRS = common.DATA / "lexicon.pairs"
PAIR_MIN = 2                # زوجُ البديل مع الجارة يُعتدّ به إن ورد مرّتين فأكثر (بمرّةٍ واحدة تضاعفت العلاماتُ الكاذبة في المحاكاة). والفهرسُ لا يعدّ فوق اثنتين
DOTS = ("بتثني", "جحخ", "دذ", "رز", "سش", "صض", "طظ", "عغ", "فق")      # «ى ي» و«ه ة» يوحّدهما التطبيع فلا يُفرَّق بينهما
_DOT = {c: g for g in DOTS for c in g}
_ARABIC = re.compile("[ء-ي]")
_WORD = re.compile("[ء-ي]+")
_MAGIC = b"BUGHP1"
_K = 4                      # مواضعُ الزوج في المرشّح
_FILL = (0.30, 0.10)        # أقصى امتلاءٍ للمرشّحَين بعد الطيّ: خطأُ الأوّل ≈ ٠٫٨٪ (يُنقص العلامات)، والثاني ≈ ٠٫٠١٪ (يزيدها)
_cache = [None, 0.0, 0]
_pcache = [None, None]


class _Bloom:
    """مرشّحُ بلوم حجمُه قوّةُ اثنين، فيُطوى نصفين (يُضمّ نصفُه إلى نصفه) ما دام قليلَ الامتلاء، ولا يتغيّر جوابُه إلّا بزيادة خطئه."""

    def __init__(self, log2: int, data=None):
        self.log2, self.mask = log2, (1 << log2) - 1
        self.b = data if data is not None else bytearray(1 << (log2 - 3))

    def _pos(self, a: str, b: str):
        d = hashlib.blake2b((a + " " + b).encode("utf-8"), digest_size=8).digest()
        h, step = int.from_bytes(d[:4], "little"), int.from_bytes(d[4:], "little") | 1
        return [(h + i * step) & self.mask for i in range(_K)]

    def has(self, a: str, b: str) -> bool:
        bits = self.b
        return all(bits[p >> 3] & (1 << (p & 7)) for p in self._pos(a, b))

    def add(self, a: str, b: str) -> None:
        bits = self.b
        for p in self._pos(a, b):
            bits[p >> 3] |= 1 << (p & 7)

    def fold(self, fill: float) -> None:
        while self.log2 > 10:
            n = len(self.b) // 2
            lo, hi = int.from_bytes(self.b[:n], "little"), int.from_bytes(self.b[n:], "little")
            both = lo | hi
            if (both.bit_count() if hasattr(both, "bit_count") else bin(both).count("1")) > fill * n * 8:
                break
            self.b = bytearray(both.to_bytes(n, "little"))
            self.log2 -= 1
            self.mask = (1 << self.log2) - 1


class _Index:
    """يبني فهرسَ الأزواج: تُعطى له سلاسلُ الكلمات المطبَّعة (chain) ثمّ يُكتب (write). ذاكرتُه محدودة مهما كبرت المكتبة."""

    def __init__(self, chars: int):
        log2 = min(29, max(16, (chars * 4 + 1_000_000).bit_length()))     # ≈ ١٦ خانةً لكلّ كلمة، وأقصاه ٦٤ م.ب لكلّ مرشّحٍ أثناء البناء
        self.seen, self.twice = _Bloom(log2), _Bloom(log2)
        self.batch = collections.Counter()

    def chain(self, ws: list) -> None:
        ok = _WORD.fullmatch
        bad = {w for w in set(ws) if not ok(w)}      # الرقمُ والحرفُ اللاتينيّ يقطعان الجوار
        pairs = zip(ws, ws[1:])
        self.batch.update(pairs if not bad else [x for x in pairs if x[0] not in bad and x[1] not in bad])
        if len(self.batch) > 300_000:
            self.flush()

    def flush(self) -> None:
        s, t, pos = self.seen.b, self.twice.b, self.seen._pos        # المرشّحان بحجمٍ واحدٍ هنا، فمواضعُ الزوج فيهما واحدة
        for (a, b), c in self.batch.items():
            ps = pos(a, b)
            if c >= 2 or all(s[p >> 3] & (1 << (p & 7)) for p in ps):      # تكرّر في هذه الدفعة، أو ورد قبلها
                for p in ps:
                    t[p >> 3] |= 1 << (p & 7)
            for p in ps:
                s[p >> 3] |= 1 << (p & 7)
        self.batch.clear()

    def write(self) -> None:
        self.flush()
        self.seen.fold(_FILL[0])
        self.twice.fold(_FILL[1])
        PAIRS.parent.mkdir(parents=True, exist_ok=True)
        tmp = PAIRS.with_suffix(".pairs.tmp")
        tmp.write_bytes(_MAGIC + struct.pack("<BBB", _K, self.seen.log2, self.twice.log2)
                        + zlib.compress(bytes(self.seen.b) + bytes(self.twice.b), 6))
        for i in range(20):         # كما في common.write_json: ويندوز يرفض الاستبدال ما دام قارئٌ فاتحًا الملفّ
            try:
                tmp.replace(PAIRS)
                break
            except PermissionError:
                if i == 19:
                    raise
                import time
                time.sleep(0.1 * (i + 1))
        _pcache[0] = None


def _pairs():
    """(مرشّح ما ورد، مرشّح ما تكرّر)، أو None إن لم يُبنَ الفهرس بعد (قاموسٌ قديم): فيبقى التعليمُ بالقاموس وحده."""
    try:
        mtime = PAIRS.stat().st_mtime
    except OSError:
        return None
    if _pcache[0] is None or _pcache[1] != mtime:
        try:
            raw = PAIRS.read_bytes()
            if raw[:6] != _MAGIC:
                raise ValueError("صيغةٌ غير معروفة")
            k, l1, l2 = struct.unpack("<BBB", raw[6:9])
            data = zlib.decompress(raw[9:])
            n1 = 1 << (l1 - 3)
            if k != _K or len(data) != n1 + (1 << (l2 - 3)):
                raise ValueError("حجمٌ لا يطابق")
            _pcache[0] = (_Bloom(l1, data[:n1]), _Bloom(l2, data[n1:]))
        except Exception:
            _pcache[0] = False      # ملفٌّ تالف: كأنْ لا فهرس، حتى يُعاد البناء
        _pcache[1] = mtime
    return _pcache[0] or None


def build(con) -> int:
    """يبني القاموس من صفحات نصّ الملفّ في الكتب التي لم يُعلَّم نصُّ ملفّها معيبًا، ويعيد عددَ كلماته."""
    from collections import Counter
    words = Counter()
    where = ("FROM pages p JOIN books b ON b.id = p.book_id "
             "WHERE p.method = 'text' AND b.state != 'missing' AND (b.hints IS NULL OR b.hints NOT LIKE '%note%')")
    # فهرسُ الأزواج من الصفحات نفسها. حجمُ المرشّحَين يُقدَّر من طول النصّ (الأزواجُ المختلفة لا تزيد على الكلمات)، ثمّ يُطوَيان.
    chars = con.execute("SELECT SUM(LENGTH(p.body) + LENGTH(COALESCE(p.foot, ''))) " + where).fetchone()[0] or 0
    index = _Index(chars)
    chain = index.chain
    for body, foot in con.execute("SELECT p.body, p.foot " + where):
        for t in (body, foot):
            if t:
                ws = arabic.normalize(t).split()
                words.update(w for w in ws if len(w) > 1 and _ARABIC.search(w))
                chain(ws)
    # وكلماتُ القراءة الآليّة التي تكرّرت في ثلاثة كتبٍ مختلفة فأكثر: خطأُ القراءة لا يتكرّر في كتبٍ مختلفة غالبًا.
    # (قيس على صفحات المرجع المقروءة آليًّا: قلّت العلاماتُ على الكلمات الصحيحة من ١٢١ إلى ٣٩،
    #  وبقي معلَّمًا ١٠٦ من ١٤٩ كلمةً خاطئةً كانت معلَّمة.)
    titles = {i: re.sub(r"[\d\s().\-_]+$", "", t or "") or str(i) for i, t in con.execute("SELECT id, title FROM books")}
    ocr_seen = {}
    for bid, body, foot in con.execute("SELECT p.book_id, p.body, p.foot FROM pages p JOIN books b ON b.id = p.book_id "
                                       "WHERE p.method = 'ocr' AND b.state != 'missing'"):
        for t in (body, foot):
            for w in arabic.normalize(t or "").split():
                if len(w) > 1 and _ARABIC.search(w) and w not in words:
                    ocr_seen.setdefault(w, set()).add(titles.get(bid, bid))
    words.update({w: 1 for w, b in ocr_seen.items() if len(b) >= OCR_BOOKS})
    lib = len(words)            # كلماتُ كتب المستخدم وحدها: بها يُحكم أنّ القاموس صالح (ألفاظُ القرآن وحدها تُعلّم نصفَ الكلمات)
    import ayat
    ayat._load()
    for v in ayat._verses:
        words.update(v["w"])
        chain(v["w"])
    index.write()
    common.write_json(PATH, {"words": dict(words), "lib": lib})
    _cache[0] = None
    return len(words)


def _load():
    try:
        mtime = PATH.stat().st_mtime
    except OSError:
        return None
    if _cache[0] is None or _cache[1] != mtime:
        data = common.read_json(PATH, {}) or {}
        _cache[0], _cache[1] = data.get("words", {}), mtime
        _cache[2] = data.get("lib", 0)
    return _cache[0]


def ready() -> bool:
    """صالحٌ إن كان في كتب المستخدم النصّيّة MIN_WORDS كلمةً مختلفة على الأقلّ (القاموسُ القديم بلا هذا العدد يُعاد بناؤه بالتحديث)."""
    w = _load()
    return bool(w) and len(_cache) > 2 and _cache[2] >= MIN_WORDS


def known(word: str) -> bool:
    """أمعروفةٌ هذه الكلمة؟ تُجرَّب بسوابقها (و، ف، ب، ك، ل) وبلا «ال». وما ليس فيه حرفٌ عربيّ (رقمٌ أو علامة) يُعدّ معروفًا."""
    return _known(re.sub("[^ء-ي]", "", arabic.normalize(word)), _load() or {})


def _known(w: str, lex: dict) -> bool:
    if len(w) < 2:
        return True
    for k in (0, 1, 2):
        if k and not all(c in PREFIX for c in w[:k]):
            break
        stem = w[k:]
        if stem in lex or (stem.startswith("ال") and len(stem) > 3 and stem[2:] in lex) or ("ال" + stem) in lex:
            return True
    return False


def _odd(w: str, prev, nxt, lex: dict, px, pair_min: int = PAIR_MIN) -> bool:
    """كلمةٌ معروفةٌ غريبةٌ في موضعها: لم ترد مع جارتيها، وورد مكانَها بديلٌ يخالفها في النقط. (الجارةُ None: لا جارة.)"""
    if px is None or len(w) < 2 or not (prev or nxt):
        return False
    seen, twice = px
    if (prev and seen.has(prev, w)) or (nxt and seen.has(w, nxt)):
        return False
    alt, freq = (twice if pair_min >= 2 else seen), lex.get(w, 0)
    for i, c in enumerate(w):
        for d in _DOT.get(c, ""):
            if d == c:
                continue
            a = w[:i] + d + w[i + 1:]
            if lex.get(a, 0) >= freq and _known(a, lex) and ((prev and alt.has(prev, a)) or (nxt and alt.has(a, nxt))):
                return True
    return False


def marks(tokens: list, pair_min: int = PAIR_MIN) -> list:
    """لكلّ كلمةٍ من كلمات النصّ المتتابعة: 0 لا تُعلَّم، 1 لا يعرفها القاموس، 2 معروفةٌ غريبةٌ في موضعها (السياق).

    الجارةُ أقربُ كلمةٍ قبلها أو بعدها؛ وعلامةُ الترقيم المنفردة لا تقطع الجوار (كما في بناء الفهرس)، والرقمُ يقطعه.
    وبلا فهرس أزواج (قاموسٌ قديم) لا يكون إلّا 0 و1 كما كان.
    """
    lex, px = _load() or {}, _pairs()
    parts = [arabic.normalize(t).split() for t in tokens]
    out = [0 if _known("".join(_WORD.findall("".join(ps))), lex) else 1 for ps in parts]
    if px is None:
        return out
    full = [i for i, ps in enumerate(parts) if ps]
    for k, i in enumerate(full):
        ps = parts[i]
        if out[i] or len(ps) != 1 or not _WORD.fullmatch(ps[0]):
            continue
        prev = parts[full[k - 1]][-1] if k else None
        nxt = parts[full[k + 1]][0] if k + 1 < len(full) else None
        if _odd(ps[0], prev if prev and _WORD.fullmatch(prev) else None, nxt if nxt and _WORD.fullmatch(nxt) else None,
                lex, px, pair_min):
            out[i] = 2
    return out


def doubt(word: str, prev: str = None, nxt: str = None) -> bool:
    """أمشكوكٌ في الكلمة بين جارتيها؟ لا يعرفها القاموس، أو يعرفها وهي غريبةٌ في موضعها ولها بديلٌ يناسبه."""
    return bool(marks([prev or "0", word, nxt or "0"])[1])
