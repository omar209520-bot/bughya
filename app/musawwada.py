"""المسوّدة: صفحةٌ متّصلة يكتب فيها الباحث كلامَه، وبين كلامه نقولٌ من كتبه بعزوها، ثمّ يُخرجها وورد أو PDF.

تُحفظ المسوّداتُ في مجلّد البيانات (drafts.json). وكلُّ نقلٍ يُقابَل بصفحته (بوّابة النقل) عند إضافته وعند تعديله،
فيظهر حكمُه في الصفحة وفي ملفّ وورد. ولا يُكتب في ملفّ وورد شيءٌ غير ما في المسوّدة.

المسوّدة: name · items (النقول بعزوها) · body (الصفحة: فقرات)
  الفقرة   {"t": "p" (نصّ) أو "h" (عنوان), "c": [نصٌّ من كلام الباحث, {"q": رقمُ النقل}, …]}
  quote    نقلٌ من كتاب: text · b · n · cite · vol · printed · unit · layer (متن|حاشية) · method (text|ocr)
           · imgok (قابله الباحثُ بالصورة) · verdict · vnote
  aya      آية: text · ref (السورة: الآية)
والنقلُ في الصفحة قطعةٌ واحدة لا يُكتب داخلها، فلا يختلط كلامُ الباحث بالنقل.
"""
import pathlib
import re
import subprocess
import tempfile
import uuid
import zipfile
from xml.sax.saxutils import escape

import common
from common import ar

FILE = common.DATA / "drafts.json"
KINDS = ("quote", "aya")
TEXT_MAX = 20000
FIELDS = {"text": str, "cite": str, "unit": str, "layer": str, "method": str, "verdict": str,
          "vnote": str, "ref": str, "printed": str, "vol": str, "b": int, "n": int, "imgok": bool}
MISMATCH = "غيرُ مطابق"


PARAS_MAX = 20000


def migrate(d: dict) -> dict:
    """مسوّدةٌ من الصيغة الأولى (بنودٌ متتابعة) تصير صفحة: العنوانُ فقرةُ عنوان، والنقلُ فقرة، والتعليقُ فقراتٌ بعده."""
    if isinstance(d.get("body"), list):
        return d
    body, items = [], []
    for it in d.get("items") or []:
        if it.get("kind") == "heading":
            body.append({"t": "h", "c": [it.get("text", "")]})
            continue
        items.append({k: v for k, v in it.items() if k != "note"})
        body.append({"t": "p", "c": [{"q": it.get("id")}]})
        body += [{"t": "p", "c": [ln.strip()]} for ln in (it.get("note") or "").splitlines() if ln.strip()]
    return {"id": d.get("id"), "name": d.get("name"), "items": items, "body": body}


def used(d: dict) -> set:
    return {r["q"] for p in d.get("body") or [] for r in p.get("c") or [] if isinstance(r, dict)}


def load() -> dict:
    d = common.read_json(FILE, None) or {}
    drafts = d.get("drafts") if isinstance(d.get("drafts"), list) else []
    drafts = [migrate(x) for x in drafts if isinstance(x, dict)]
    for x in drafts:                      # نقلٌ حُذف من الصفحة يُحذف من المسوّدة عند فتحها التالي
        u = used(x)
        x["items"] = [i for i in x.get("items") or [] if i.get("id") in u]
    if not drafts:
        drafts = [{"id": uuid.uuid4().hex[:8], "name": "مسوّدتي", "items": [], "body": []}]
    cur = d.get("current") if any(x.get("id") == d.get("current") for x in drafts) else drafts[0]["id"]
    return {"drafts": drafts, "current": cur}


def _clean_body(body, ids: set) -> list:
    out = []
    for p in (body if isinstance(body, list) else [])[:PARAS_MAX]:
        if not isinstance(p, dict):
            continue
        c = []
        for r in p.get("c") or []:
            if isinstance(r, str):
                c.append(r[:TEXT_MAX])
            elif isinstance(r, dict) and r.get("q") in ids:
                c.append({"q": r["q"]})
        out.append({"t": "h" if p.get("t") == "h" else "p", "c": c})
    return out


def _clean_item(it: dict) -> dict:
    kind = it.get("kind")
    if kind not in KINDS:
        return None
    out = {"id": str(it.get("id") or uuid.uuid4().hex[:8])[:16], "kind": kind}
    for k, t in FIELDS.items():
        v = it.get(k)
        if v is None or v == "":
            continue
        try:
            out[k] = (str(v)[:TEXT_MAX] if t is str else t(v))
        except (TypeError, ValueError):
            continue
    return out if out.get("text") else None


def save(body: dict) -> dict:
    drafts = []
    for d in body.get("drafts") or []:
        if not isinstance(d, dict):
            continue
        items = [x for x in (_clean_item(i) for i in d.get("items") or [] if isinstance(i, dict)) if x]
        name = str(d.get("name") or "").strip()[:120] or "مسوّدة"
        paras = _clean_body(d.get("body"), {x["id"] for x in items})
        drafts.append({"id": str(d.get("id") or uuid.uuid4().hex[:8])[:16], "name": name, "items": items, "body": paras})
    if not drafts:
        return {"error": "لا مسوّدةَ تُحفظ."}
    cur = body.get("current")
    data = {"drafts": drafts, "current": cur if any(x["id"] == cur for x in drafts) else drafts[0]["id"]}
    common.write_json(FILE, data)
    return data


def check(item: dict) -> dict:
    """يقابل النقلَ بصفحته: حكمُ بوّابة النقل وملاحظتُها."""
    import bawwaba
    import store
    con = store.connect(readonly=True)
    try:
        r = bawwaba.verify(con, int(item["b"]), int(item["n"]), str(item.get("text") or ""),
                           image_checked=bool(item.get("imgok")))
    finally:
        con.close()
    return {"verdict": r.get("verdict", ""), "vnote": r.get("note", ""), "closest": r.get("closest", "")}


# ───────────────────────── العزو ─────────────────────────

def title_of(it: dict) -> str:
    m = re.match(r"\s*«([^»]*)»", it.get("cite") or "")
    return m.group(1) if m else (it.get("cite") or "")


def footnote(it: dict) -> str:
    """العزوُ في الحاشية: «العنوان» (٢/ ٢٨) — أو (ص٢٨) — أو (صفحة الملف ٢٢) إن لم يُقرأ رقمُ الصفحة المطبوع."""
    t = "«%s»" % title_of(it)
    vol, printed, n, unit = it.get("vol"), it.get("printed"), it.get("n"), it.get("unit") or "صفحة"
    if unit == "صفحة" and printed:
        loc = "(%s/ %s)" % (ar(vol), ar(printed)) if vol else "(ص%s)" % ar(printed)
    elif unit == "صفحة":
        loc = "(%sصفحة الملف %s)" % ("ج%s، " % ar(vol) if vol else "", ar(n))
    else:
        loc = "(%s %s)" % (unit, ar(n))
    s = t + " " + loc
    if it.get("layer") == "حاشية":
        s += "، في الحاشية"
    return s + "."


def flags(it: dict) -> list:
    """تنبيهاتُ النقل التي تُكتب بجانبه حتّى يُعالجها الباحث."""
    out = []
    if it.get("kind") == "quote":
        if it.get("verdict") == MISMATCH:
            out.append(("لا يطابق نصَّ الصفحة", "red"))
        if it.get("method") == "ocr" and not it.get("imgok"):
            out.append(("لم يُقابَل بالصورة", "yellow"))
    return out


def one_line(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").replace("⏎", " ")).strip()


# ───────────────────────── وورد ─────────────────────────

FONT = "Traditional Arabic"


def _run(text: str, rpr: str = "") -> str:
    return '<w:r><w:rPr>%s<w:rtl/></w:rPr><w:t xml:space="preserve">%s</w:t></w:r>' % (rpr, escape(text))


def _para(runs: str, style: str = "", jc: str = "both") -> str:
    ps = '<w:pStyle w:val="%s"/>' % style if style else ""
    return '<w:p><w:pPr>%s<w:bidi/><w:jc w:val="%s"/></w:pPr>%s</w:p>' % (ps, jc, runs)


def _flag_runs(it: dict) -> str:
    out = ""
    for text, color in flags(it):
        rpr = '<w:color w:val="A8201A"/><w:sz w:val="24"/><w:szCs w:val="24"/><w:highlight w:val="%s"/>' % color
        if color == "red":
            rpr = '<w:color w:val="FFFFFF"/><w:sz w:val="24"/><w:szCs w:val="24"/><w:highlight w:val="red"/>'
        out += _run(" ") + _run("[%s]" % text, rpr)
    return out


def docx_bytes(draft: dict) -> bytes:
    d = migrate(draft)
    items = {x["id"]: x for x in d.get("items") or []}
    paras = list(d.get("body") or [])
    while paras and not any((r.strip() if isinstance(r, str) else True) for r in paras[-1]["c"]):
        paras.pop()                       # الفقراتُ الفارغة في آخر الصفحة لا تُكتب
    body, notes = [], []
    body.append(_para(_run(d.get("name") or "مسوّدة"), "Title", "center"))
    for p in paras:
        runs = ""
        for r in p["c"]:
            if isinstance(r, str):
                runs += _run(r)
                continue
            it = items.get(r["q"])
            if it is None:
                continue
            if it.get("kind") == "aya":
                runs += _run("﴿%s﴾ [%s]" % (one_line(it["text"]), it.get("ref", "")))
            else:
                notes.append(footnote(it))
                runs += (_run("«%s»" % one_line(it["text"])) +
                         '<w:r><w:rPr><w:rStyle w:val="FootnoteReference"/><w:rtl/></w:rPr><w:footnoteReference w:id="%d"/></w:r>'
                         % len(notes) + _flag_runs(it))
        body.append(_para(runs, "Heading1", "right") if p["t"] == "h" else _para(runs))
    sect = ('<w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1440" w:right="1440" w:bottom="1440" '
            'w:left="1440" w:header="708" w:footer="708" w:gutter="0"/><w:bidi/></w:sectPr>')
    W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" ' \
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
    doc = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document %s><w:body>%s%s</w:body></w:document>'
           % (W, "".join(body), sect))
    fn = ['<w:footnote w:type="separator" w:id="-1"><w:p><w:pPr><w:bidi/></w:pPr><w:r><w:separator/></w:r></w:p></w:footnote>',
          '<w:footnote w:type="continuationSeparator" w:id="0"><w:p><w:pPr><w:bidi/></w:pPr><w:r><w:continuationSeparator/></w:r></w:p></w:footnote>']
    for i, t in enumerate(notes, 1):
        fn.append('<w:footnote w:id="%d"><w:p><w:pPr><w:pStyle w:val="FootnoteText"/><w:bidi/><w:jc w:val="both"/></w:pPr>'
                  '<w:r><w:rPr><w:rStyle w:val="FootnoteReference"/><w:rtl/></w:rPr><w:footnoteRef/></w:r>%s</w:p></w:footnote>'
                  % (i, _run(" " + t)))
    foot = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:footnotes %s>%s</w:footnotes>' % (W, "".join(fn))
    fonts = '<w:rFonts w:ascii="{0}" w:hAnsi="{0}" w:cs="{0}" w:eastAsia="{0}"/>'.format(FONT)
    styles = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:styles %s>'
              '<w:docDefaults><w:rPrDefault><w:rPr>%s<w:sz w:val="32"/><w:szCs w:val="32"/>'
              '<w:lang w:val="ar-SA" w:bidi="ar-SA"/></w:rPr></w:rPrDefault>'
              '<w:pPrDefault><w:pPr><w:bidi/><w:spacing w:after="120" w:line="276" w:lineRule="auto"/></w:pPr></w:pPrDefault></w:docDefaults>'
              '<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:qFormat/></w:style>'
              '<w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/>'
              '<w:pPr><w:spacing w:after="240"/></w:pPr><w:rPr><w:b/><w:bCs/><w:sz w:val="44"/><w:szCs w:val="44"/></w:rPr></w:style>'
              '<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/>'
              '<w:pPr><w:keepNext/><w:spacing w:before="240" w:after="120"/><w:outlineLvl w:val="0"/></w:pPr>'
              '<w:rPr><w:b/><w:bCs/><w:color w:val="0B5240"/><w:sz w:val="36"/><w:szCs w:val="36"/></w:rPr></w:style>'
              '<w:style w:type="paragraph" w:styleId="FootnoteText"><w:name w:val="footnote text"/><w:basedOn w:val="Normal"/>'
              '<w:pPr><w:spacing w:after="0" w:line="240" w:lineRule="auto"/></w:pPr><w:rPr><w:sz w:val="26"/><w:szCs w:val="26"/></w:rPr></w:style>'
              '<w:style w:type="character" w:styleId="FootnoteReference"><w:name w:val="footnote reference"/>'
              '<w:rPr><w:vertAlign w:val="superscript"/></w:rPr></w:style></w:styles>') % (W, fonts)
    settings = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:settings %s>'
                '<w:footnotePr><w:footnote w:id="-1"/><w:footnote w:id="0"/></w:footnotePr></w:settings>') % W
    ct = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
          '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
          '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
          '<Default Extension="xml" ContentType="application/xml"/>'
          '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
          '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
          '<Override PartName="/word/settings.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.settings+xml"/>'
          '<Override PartName="/word/footnotes.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.footnotes+xml"/>'
          '</Types>')
    R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="%s/officeDocument" Target="word/document.xml"/></Relationships>') % R
    drels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
             '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
             '<Relationship Id="rId1" Type="{0}/styles" Target="styles.xml"/>'
             '<Relationship Id="rId2" Type="{0}/settings" Target="settings.xml"/>'
             '<Relationship Id="rId3" Type="{0}/footnotes" Target="footnotes.xml"/></Relationships>').format(R)
    import io
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", ct)
        z.writestr("_rels/.rels", rels)
        z.writestr("word/document.xml", doc)
        z.writestr("word/styles.xml", styles)
        z.writestr("word/settings.xml", settings)
        z.writestr("word/footnotes.xml", foot)
        z.writestr("word/_rels/document.xml.rels", drels)
    return buf.getvalue()


# ───────────────────────── الملفّات ─────────────────────────

def out_path(name: str, ext: str) -> pathlib.Path:
    """ملفٌّ جديد في مجلّد التنزيلات، لا يكتب فوق ملفٍّ موجود."""
    folder = pathlib.Path.home() / "Downloads"
    folder.mkdir(exist_ok=True)
    stem = "مسودة - " + (re.sub(r'[\\/:*?"<>|\r\n\t]+', " ", name).strip() or "مسودة")[:80]
    p, i = folder / (stem + ext), 1
    while p.exists():
        i += 1
        p = folder / ("%s (%d)%s" % (stem, i, ext))
    return p


def edge():
    """متصفّح إدج المنصَّب مع ويندوز، أو None."""
    import os
    for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles"), os.environ.get("LOCALAPPDATA")):
        if base:
            f = pathlib.Path(base) / "Microsoft" / "Edge" / "Application" / "msedge.exe"
            if f.is_file():
                return f
    return None


def html_pdf(html: str, pdf: pathlib.Path) -> bool:
    """يصنع PDF من صفحة الطباعة بمتصفّح إدج في الخفاء، بملفّ تعريفٍ مؤقّتٍ مستقلّ يُحذف بعده:
    لا يُفتح وورد ولا تُحمَّل إضافاتُه، ولا يُمسّ متصفّحُ المستخدم ولا إعداداتُه. وإن لم يوجد إدج عاد بـ False."""
    import shutil
    exe = edge()
    if exe is None:
        return False
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="bughya-pdf-"))
    try:
        page = tmp / "draft.html"
        page.write_text(html, encoding="utf-8")
        out = tmp / "draft.pdf"
        subprocess.run([str(exe), "--headless", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
                        "--disable-extensions", "--user-data-dir=" + str(tmp / "profile"), "--no-pdf-header-footer",
                        "--print-to-pdf=" + str(out), page.as_uri()],
                       capture_output=True, timeout=120, creationflags=0x08000000 if common.IS_WIN else 0)
        if not (out.is_file() and out.stat().st_size > 0):
            return False
        shutil.copyfile(out, pdf)
        return True
    except (OSError, subprocess.SubprocessError):
        return False
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
