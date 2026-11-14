#!/usr/bin/env python3
"""تجربةُ جدوى (ليست ميزة): معرفةُ حرف كلّ رمزٍ في خطّ بي دي إف المحفوظ من وورد من الخطّ نفسه لا من خريطته (ToUnicode).

    .venv\\Scripts\\python.exe tests\\trial_glyph_shape.py                    يقيس صفحات المرجع 01 02 03 04 05 10
    .venv\\Scripts\\python.exe tests\\trial_glyph_shape.py --pages 01          صفحاتٌ بعينها
    .venv\\Scripts\\python.exe tests\\trial_glyph_shape.py --save اسم          ويحفظ الأرقام في tests/results/اسم.json
    .venv\\Scripts\\python.exe tests\\trial_glyph_shape.py --panel مجلّد       ويكتب لوحةَ مقابلةٍ بالعين (فيها قصاصاتٌ من الصفحة: لا تُرفع)

ما وُجد: وورد يضمّن الخطَّ في الملفّ بأرقام رموزه الأصليّة ورسومها كما هي، ويترك فيه جدولَ حروفه (cmap). فحرفُ الرمز يُعرف من
ثلاثة مصادر، تُقاس هنا كلٌّ وحدها:
  «المضمَّن»: جدولُ الحروف (cmap) في الخطّ المضمَّن في الملفّ نفسه. لا يحتاج شيئًا من الجهاز.
  «المثبَّت»: الخطُّ المثبَّت في ويندوز باسمه، بعد التحقّق أنّ رسمَ كلّ رمزٍ في الملفّ يطابق رسمَ الرمز ذي الرقم نفسه فيه بايتًا ببايت:
             جدولُ حروفه (cmap) ثمّ جدولُ الإبدال (GSUB) لما لا حرفَ له في الجدول (مركّباتٌ وصورٌ سياقيّة).
  «كلاهما»: المضمَّن أوّلًا، وما لم يعرفه فمن المثبَّت.
والمعروفُ يُكتب في خريطة الملفّ في الذاكرة (كما يفعل readers/tounicode.py)، ثمّ يُقرأ نصُّ الصفحة بقارئ «بُغية» نفسه ويُقاس بطريقة
tests/measure.py. ولا يُبدَّل إلّا ما عُرف حرفًا عربيًّا: الأقواسُ والأرقامُ وعلاماتُ الترقيم تبقى كما سجّلها وورد (القوسُ يُعكس في
السطر العربيّ، فرسمُه لا يدلّ على حرفه).

يحتاج fontTools و jiwer (للتجربة والقياس وحدهما، لا يدخلان في البرنامج). ولا يغيّر شيئًا في app.
"""
import argparse
import io
import json
import os
import pathlib
import re
import sys
import time
import unicodedata

ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent / "app"))
sys.path.insert(0, str(ROOT))
import jiwer  # noqa: E402
import pymupdf as fitz  # noqa: E402
from fontTools.ttLib import TTFont  # noqa: E402
from measure import GOLD, RESULTS, clean  # noqa: E402
from readers import tounicode  # noqa: E402

ORIG_REPAIR = tounicode.repair
ARABIC = re.compile("[\u0600-\u06ff]")


# ───────────────────── حرفُ الرمز من جداول الخطّ ─────────────────────

def _text(cp: int) -> str:
    """نصُّ رقم يونيكود بعد ردّ صور العرض والمركّبات إلى حروفها بترتيب القراءة (ﻓﻲ ← في)."""
    if 0xFDF0 <= cp <= 0xFDFD and cp != 0xFDF2:           # ﷺ وأخواتها كلمةٌ برمزٍ واحد: تبقى كما هي
        return chr(cp)
    s = unicodedata.normalize("NFKC", chr(cp))
    if len(s) > 1 and any(unicodedata.combining(c) for c in s):
        s = s.replace(" ", "").replace("\u0640", "")       # صورةُ الحركة المنفردة «مسافة+حركة» والمتوسّطة «تطويل+حركة»
    return s


def _rank(cp: int):
    return (0 if 0x600 <= cp <= 0x6FF else 1 if 0xFE70 <= cp <= 0xFEFF else 2 if 0xFB50 <= cp <= 0xFDFF else 3, cp)


def cmap_map(font) -> dict:
    """{رقم الرمز: نصّه} من جدول الحروف في الخطّ."""
    if "cmap" not in font:
        return {}
    best = font.getBestCmap() or {}
    gid = {n: i for i, n in enumerate(font.getGlyphOrder())}
    rev = {}
    for cp, name in best.items():
        if name in gid and cp >= 0x20 and not 0xE000 <= cp <= 0xF8FF:
            rev.setdefault(gid[name], []).append(cp)
    return {g: _text(min(cps, key=_rank)) for g, cps in rev.items()}


def gsub_map(font, known: dict) -> dict:
    """ما لا حرفَ له في جدول الحروف: يُعرف من جدول الإبدال. بديلُ الرمز له نصُّه، والمركّبُ له نصوصُ أجزائه بالترتيب."""
    if "GSUB" not in font:
        return {}
    gid = {n: i for i, n in enumerate(font.getGlyphOrder())}
    single, liga = [], []
    for lk in font["GSUB"].table.LookupList.Lookup:
        for st in lk.SubTable:
            if lk.LookupType == 7:
                st = st.ExtSubTable
            if hasattr(st, "mapping") and st.LookupType == 1:
                single += [(gid[b], gid[a]) for a, b in st.mapping.items()]
            elif hasattr(st, "ligatures"):
                for first, ligs in st.ligatures.items():
                    liga += [(gid[l.LigGlyph], [gid[first]] + [gid[c] for c in l.Component]) for l in ligs]
    out, have = {}, dict(known)
    changed = True
    while changed:                  # المركّبُ مقدَّمٌ على البديل: رمزُ «لله» بديلٌ سياقيٌّ لرمز «الله»، وأجزاؤه ل ل ه
        changed = False
        for g, parts in liga:
            if g not in have and all(p in have for p in parts):
                have[g] = out[g] = "".join(have[p] for p in parts)
                changed = True
        if changed:
            continue
        for g, src in single:
            if g not in have and src in have:
                have[g] = out[g] = have[src]
                changed = True
    return out


# ───────────────────── الخطُّ المثبَّت ─────────────────────

def _key(name: str) -> str:
    return re.sub(r"[\s,\-_]+", "", name or "").lower()


_INSTALLED = None


def installed_index() -> dict:
    """{اسم الخطّ مبسَّطًا: (المسار، رقمه في الملفّ)} لكلّ خطٍّ مثبَّت في ويندوز."""
    global _INSTALLED
    if _INSTALLED is not None:
        return _INSTALLED
    _INSTALLED = {}
    loose = {}                      # اسمُ العائلة وحده يشترك فيه العاديُّ والأسود: لا يُؤخذ به إلّا إن لم يوجد الاسمُ التامّ
    dirs = [pathlib.Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts",
            pathlib.Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "Windows" / "Fonts"]
    for d in dirs:
        if not d.is_dir():
            continue
        for p in sorted(d.iterdir()):
            if p.suffix.lower() not in (".ttf", ".ttc", ".otf"):
                continue
            for i in range(8 if p.suffix.lower() == ".ttc" else 1):
                try:
                    f = TTFont(str(p), lazy=True, fontNumber=i)
                    nm = f["name"]
                    fam, sub = nm.getDebugName(1) or "", nm.getDebugName(2) or ""
                    names = {nm.getDebugName(6), nm.getDebugName(4), fam + sub, fam + "," + sub}
                    if sub.lower() in ("regular", "normal", ""):
                        names.add(fam)
                    for n in names:
                        if n:
                            _INSTALLED.setdefault(_key(n), (str(p), i))
                    loose.setdefault(_key(fam), (str(p), i))
                    f.close()
                except Exception:
                    break
    for k, v in loose.items():
        _INSTALLED.setdefault(k, v)
    return _INSTALLED


def same_outlines(emb, inst) -> tuple:
    """كم رمزًا مرسومًا في المضمَّن يطابق رسمُه رسمَ الرمز ذي الرقم نفسه في المثبَّت بايتًا ببايت: (المطابق، المرسوم)."""
    if "glyf" not in emb or "glyf" not in inst:
        return 0, 0
    eo, io_ = emb.getGlyphOrder(), inst.getGlyphOrder()
    eg, ig = emb["glyf"], inst["glyf"]
    same = drawn = 0
    for i, n in enumerate(eo):
        a = eg[n].compile(eg)
        if not a:
            continue
        drawn += 1
        if i < len(io_) and a == ig[io_[i]].compile(ig):
            same += 1
    return same, drawn


# ───────────────────── إصلاحُ الخريطة في الذاكرة ─────────────────────

STATS = []
GATE = 3               # أقلُّ عددٍ من الحروف المرسومة المسجَّلة مسافةً يُعدّ به الخطُّ معيبَ الخريطة


def make_repair(mode: str):
    """mode: «المضمَّن» أو «المثبَّت» أو «كلاهما»."""
    def repair(doc) -> int:
        total, done = 0, set()
        for xref in range(1, doc.xref_length()):
            try:
                obj = doc.xref_object(xref, compressed=True)
                if "/Type0" not in obj or "/Identity-H" not in obj:
                    continue
                t = re.search(r"/ToUnicode\s+(\d+)\s+0\s+R", obj)
                d = re.search(r"/DescendantFonts\s*\[\s*(\d+)\s+0\s+R", obj) or re.search(r"/DescendantFonts\s+(\d+)\s+0\s+R", obj)
                if not t or not d or int(t.group(1)) in done:
                    continue
                tx = int(t.group(1))
                done.add(tx)
                name = (re.search(r"/BaseFont\s*/([^\s/\[<>]+)", obj) or [None, ""])[1].split("+")[-1]
                name = re.sub(r"#([0-9A-Fa-f]{2})", lambda x: chr(int(x.group(1), 16)), name)
                st = {"font": name, "mode": mode}
                STATS.append(st)
                buf = doc.extract_font(xref)[3]
                if not buf:
                    st["note"] = "الخطّ غير مضمَّن"
                    continue
                emb = TTFont(io.BytesIO(buf))
                shape = {}
                if mode in ("المثبَّت", "كلاهما"):
                    hit = installed_index().get(_key(name))
                    st["installed"] = bool(hit)
                    if hit:
                        inst = TTFont(hit[0], fontNumber=hit[1])
                        st["installed_version"] = inst["name"].getDebugName(5)
                        same, drawn = same_outlines(emb, inst)
                        st["outlines_same"], st["outlines_drawn"] = same, drawn
                        if drawn and same == drawn:             # الرسمُ يشهد أنّ الأرقامَ هي الأرقام
                            cm = cmap_map(inst)
                            gs = gsub_map(inst, cm)
                            st["from_gsub"] = len(gs)
                            shape.update(gs)
                            shape.update(cm)
                if mode in ("المضمَّن", "كلاهما"):
                    cm = cmap_map(emb)
                    st["embedded_cmap"] = len(cm)
                    shape.update(cm)                            # المضمَّنُ في الملفّ مقدَّم
                m = tounicode.parse(doc.xref_stream(tx).decode("latin-1"))
                # شرطُ المسّ: خريطةُ الخطّ معيبةٌ يقينًا، أي فيها رموزٌ مرسومةٌ عُرفت حروفًا وسجّلها وورد مسافة.
                # الخطُّ السليمُ الخريطة لا يُمسّ: جدولُ حروفه قد يخالف استعمالَ وورد للرمز (هـ المبتدأة، ولفظ الجلالة).
                eo, eg = emb.getGlyphOrder(), emb["glyf"] if "glyf" in emb else None
                blank = [g for g, s in m.items() if not s.strip() and g in shape and unicodedata.category(shape[g][0]) == "Lo"
                         and eg is not None and g < len(eo) and eg[eo[g]].numberOfContours != 0]
                st["letters_as_space"] = len(blank)
                if len(blank) < GATE:
                    st["note"] = "خريطتُه سليمة: لم يُمسّ"
                    continue
                fx = {g: s for g, s in shape.items() if ARABIC.search(s) and m.get(g) != s}
                st["known"], st["changed"] = len(shape), len(fx)
                st["_fx"], st["_old"] = fx, {g: m.get(g) for g in fx}
                if fx:
                    m.update(fx)
                    doc.update_stream(tx, tounicode._write(m))
                    total += len(fx)
            except Exception as e:
                STATS.append({"font": "?", "mode": mode, "error": repr(e)})
        return total
    return repair


# ───────────────────── القياس ─────────────────────

def read_page(pdf, repair, ocr):
    """نصُّ الصفحة الأولى بقارئ «بُغية»، بعد وضع repair موضعَ إصلاح الخريطة. ocr=None يُلزم نصَّ الملفّ."""
    from readers import open_book
    tounicode.repair = repair
    try:
        book = open_book(pdf, ocr)
        try:
            pg = next(book.pages(1))
            note = (getattr(book, "hints", {}) or {}).get("note", "")
            return "\n".join(x for x in (pg["head"], pg["body"], pg["foot"]) if x), pg["method"], bool(getattr(book, "force_ocr", False)), note
        finally:
            book.close()
    finally:
        tounicode.repair = ORIG_REPAIR


def panel(pdf, out_dir, gid_name, limit=48):
    """لوحةُ المقابلة بالعين: لكلّ رمزٍ بُدّل حرفُه قصاصةٌ من موضعه في الصفحة، وتحتها ما كان مسجَّلًا وما عُرف."""
    doc = fitz.open(str(pdf))
    rep = make_repair("كلاهما")
    before = len(STATS)
    rep(doc)
    fx = {}
    for st in STATS[before:]:
        for g, s in st.get("_fx", {}).items():
            fx[(st["font"], g)] = (st["_old"].get(g), s)
    del STATS[before:]
    page = doc[0]
    seen, cells = set(), []
    for sp in page.get_texttrace():
        for u, g, o, b in sp["chars"]:
            k = (sp["font"], g)
            if k in fx and k not in seen:
                seen.add(k)
                cells.append((k, fitz.Rect(b)))
    cells = cells[:limit]
    cols, cw, ch = 8, 150, 120
    rows = (len(cells) + cols - 1) // cols
    sheet = fitz.open()
    pg = sheet.new_page(width=cols * cw, height=max(1, rows) * ch)
    font = fitz.Font("notos") if False else None
    for i, ((fname, g), r) in enumerate(cells):
        x, y = (i % cols) * cw, (i // cols) * ch
        clip = fitz.Rect(r.x0 - 22, r.y0 - 4, r.x1 + 22, r.y1 + 4) & page.rect
        pix = page.get_pixmap(matrix=fitz.Matrix(4, 4), clip=clip)
        box = fitz.Rect(x + 4, y + 4, x + cw - 4, y + 70)
        pg.insert_image(box, pixmap=pix, keep_proportion=True)
        mid = (r.x0 + r.x1) / 2 - clip.x0
        sx = min(box.width / clip.width, box.height / clip.height)
        px = box.x0 + (box.width - clip.width * sx) / 2 + mid * sx
        pg.draw_line((px, y + 70), (px, y + 76), color=(1, 0, 0), width=1.2)
        old, new = fx[(fname, g)]
        lab = lambda s: " ".join("%s" % unicodedata.name(c, "?").replace("ARABIC ", "").replace("LETTER ", "").lower() for c in (s or "")) or "-"
        pg.insert_textbox(fitz.Rect(x + 2, y + 78, x + cw - 2, y + ch), "g%d %s\nwas: %s\nnow: %s" % (g, "B" if "Bold" in fname else "", lab(old), lab(new)),
                          fontsize=7.5, fontname="helv")
    out = pathlib.Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    f = out / ("panel-%s.png" % gid_name)
    pg.get_pixmap(matrix=fitz.Matrix(1.6, 1.6)).save(str(f))
    return f, len(seen)


def main() -> int:
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")
        except Exception:
            pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--pages", default="01,02,03,04,05,10")
    ap.add_argument("--save")
    ap.add_argument("--panel")
    a = ap.parse_args()
    from readers.ocr import engine
    eng = engine()
    rows = []
    ways = [("الحالي", ORIG_REPAIR), ("المضمَّن", make_repair("المضمَّن")), ("المثبَّت", make_repair("المثبَّت")),
            ("كلاهما", make_repair("كلاهما"))]
    print("الصفحة | البرنامج الآن (طريقته) | نص الملف الحالي | المضمَّن | المثبَّت | كلاهما | حكم البرنامج على نص «كلاهما»")
    for gid in a.pages.split(","):
        pdf, ref = GOLD / (gid + ".pdf"), clean((GOLD / (gid + ".txt")).read_text(encoding="utf-8"))
        row = {"id": gid, "words": len(ref.split())}
        hyp, method, forced, _ = read_page(pdf, ORIG_REPAIR, eng)
        row["now"] = {"method": method + (" (نص الملف معيب)" if forced else ""), "wer": round(jiwer.wer(ref, clean(hyp)), 4),
                      "cer": round(jiwer.cer(ref, clean(hyp)), 4)}
        for label, rep in ways:
            del STATS[:]
            hyp, method, _, _ = read_page(pdf, rep, None)
            row[label] = {"wer": round(jiwer.wer(ref, clean(hyp)), 4), "cer": round(jiwer.cer(ref, clean(hyp)), 4)}
            if label != "الحالي":
                row[label]["fonts"] = [{k: v for k, v in st.items() if not k.startswith("_") and k != "mode"} for st in STATS]
        t0 = time.time()
        _, method, forced, note = read_page(pdf, ways[-1][1], eng)           # أيقبل البرنامجُ النصَّ الجديد أم يعدّه معيبًا؟
        row["accept"] = {"method": method, "forced_ocr": forced, "note": note}
        rows.append(row)
        print("%s | %.1f%% (%s) | %.1f%% | %.1f%% | %.1f%% | %.1f%% | %s" % (
            gid, 100 * row["now"]["wer"], row["now"]["method"], 100 * row["الحالي"]["wer"], 100 * row["المضمَّن"]["wer"],
            100 * row["المثبَّت"]["wer"], 100 * row["كلاهما"]["wer"], "يقرؤه نصًّا" if not forced else "يعدّه معيبًا: " + note))
        print("     خطأ الحروف: الآن %.1f%% | الحالي %.1f%% | المضمَّن %.1f%% | المثبَّت %.1f%% | كلاهما %.1f%%" % tuple(
            100 * row[k]["cer"] for k in ("now", "الحالي", "المضمَّن", "المثبَّت", "كلاهما")))
        for st in row["كلاهما"]["fonts"]:
            print("     ", json.dumps(st, ensure_ascii=False))
        if a.panel:
            f, n = panel(pdf, a.panel, gid)
            print("     لوحة المقابلة: %s (%d رمزًا بُدّل حرفُه في الصفحة)" % (f, n))
    if a.save:
        RESULTS.mkdir(exist_ok=True)
        (RESULTS / (a.save + ".json")).write_text(json.dumps({"date": time.strftime("%Y-%m-%d %H:%M"), "pages": rows},
                                                              ensure_ascii=False, indent=1), encoding="utf-8")
        print("حُفظ: tests/results/%s.json" % a.save)
    return 0


if __name__ == "__main__":
    sys.exit(main())
