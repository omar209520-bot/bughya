"""يبني مكتبةً تجريبيّة صغيرة للفيديو التعريفيّ: ملفّ PDF نصّيّ لكلّ كتاب.

النصوص منقولةٌ كما هي من «المكتبة الشاملة» (shamela.ws). كلُّ ملفٍّ نصّيّ:
  #title: / #author: / #shamela: (رقمُ الكتاب في الشاملة)
  ثمّ صفحاتٌ يبدأ كلٌّ منها بسطر «=== <رقم صفحة الشاملة> | <رقم الصفحة المطبوع>».
الاستعمال: python build_library.py <مجلّد_الخطوط> <مجلّد_الناتج> <مجلّد_نصوص> [مجلّد_نصوص ...]
"""
import html
import json
import subprocess
import pathlib
import sys

import pymupdf as fitz

FONTS = pathlib.Path(sys.argv[1])
OUT = pathlib.Path(sys.argv[2])
OUT.mkdir(parents=True, exist_ok=True)


# رقمُ الصفحة في ذيلها بالأرقام الغربيّة: هكذا يقرؤه البرنامج صحيحًا من ملفّات Chromium
WEST = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")


def parse(p):
    meta, pages = {}, []
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.startswith("=== "):
            sid, printed = [x.strip() for x in line[4:].split("|")]
            pages.append({"sid": sid, "printed": printed, "lines": []})
        elif line.startswith("#") and not pages:
            k, v = line[1:].split(":", 1)
            meta[k.strip()] = v.strip()
        elif line.strip() and pages:
            pages[-1]["lines"].append(line)
    return meta, pages


CSS = """
@font-face {font-family: amiri; src: url('file://FONTS/Amiri-Regular.ttf');}
@font-face {font-family: amiri; src: url('file://FONTS/Amiri-Bold.ttf'); font-weight: bold;}
@page {size: 148mm 210mm; margin: 0;}
html, body {margin: 0; padding: 0; background: #fff;}
body {font-family: amiri; color: #1a1a1a; direction: rtl;}
.pg {width: 148mm; height: 210mm; box-sizing: border-box; padding: 11mm 14mm 10mm; position: relative;
     page-break-after: always; overflow: hidden;}
.hd {text-align: center; font-size: 10.5pt; border-bottom: .6pt solid #9e7a29; padding-bottom: 2mm; margin-bottom: 4mm;}
.bd p {text-align: justify; margin: 0 0 2.2mm; line-height: 1.75; font-size: 12.5pt;}
.ft {position: absolute; bottom: 7mm; left: 0; right: 0; text-align: center; font-size: 11pt;}
.tp {border: 1.6pt solid #9e7a29; outline: .5pt solid #9e7a29; outline-offset: -2.5mm; margin: 8mm; height: calc(210mm - 16mm);
     box-sizing: border-box; display: flex; flex-direction: column; justify-content: center; align-items: center; text-align: center; padding: 10mm;}
.tp h1 {font-size: 26pt; line-height: 1.5; margin: 0 0 12mm;}
.tp .by {font-size: 15pt; margin: 0;} .tp .au {font-size: 20pt; margin: 2mm 0 0;}
.tp .nt {position: absolute; bottom: 20mm; left: 0; right: 0; font-size: 10pt;}
"""


def book_html(meta, pages):
    e = html.escape
    h = [f'<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8"><title>{e(meta["title"])}</title>',
         f'<style>{CSS.replace("FONTS", str(FONTS.resolve()))}</style></head><body>',
         f'<div class="pg"><div class="tp"><h1>{e(meta["title"])}</h1><p class="by">تأليف</p><p class="au">{e(meta["author"])}</p>'
         + (f'<p class="by" style="margin-top:8mm">الجزء {e(meta["volume"])}</p>' if meta.get("volume") else "")
         + f'<p class="nt">مقتطفاتٌ منقولة من المكتبة الشاملة (رقم الكتاب {e(meta["shamela"])})<br>لعرض برنامج «بُغية»</p></div></div>']
    for p in pages:
        h.append(f'<div class="pg"><div class="hd">{e(meta["title"])}</div><div class="bd">'
                 + "".join(f"<p>{e(l)}</p>" for l in p["lines"])
                 + f'</div><div class="ft">{e(p["printed"].translate(WEST))}</div></div>')
    h.append("</body></html>")
    return "".join(h)


def set_meta(path, meta):
    d = fitz.open(path)
    d.set_metadata({"title": meta["title"], "author": meta["author"]})
    d.save(path + ".tmp", garbage=3, deflate=True)
    d.close()
    pathlib.Path(path + ".tmp").replace(path)


books = []
for d in sys.argv[3:]:
    for src in sorted(pathlib.Path(d).glob("*.txt")):
        meta, pages = parse(src)
        (OUT / f"{src.stem}.html").write_text(book_html(meta, pages), encoding="utf-8")
        books.append({"file": f"{src.stem}.pdf", **meta, "pages": len(pages)})
(OUT / "books.json").write_text(json.dumps(books, ensure_ascii=False, indent=1), encoding="utf-8")
# الطباعة إلى PDF بمتصفّح Chromium (نصٌّ عربيٌّ قابلٌ للاستخراج)
subprocess.run(["node", str(pathlib.Path(__file__).with_name("print_pdf.js")), str(OUT)], check=True)
for b in books:
    (OUT / b["file"].replace(".pdf", ".html")).unlink()
    set_meta(str(OUT / b["file"]), b)
    print(b["file"], b["pages"], "صفحة")
