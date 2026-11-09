"""فصلٌ تجريبيّ قصير (وورد بحواشٍ) لعرض «مدقّق الإحالات». الكلامُ الذي حول النقول مكتوبٌ للتجربة،
والنقولُ منقولةٌ بلفظها من الكتب التجريبيّة؛ وفيه نقلٌ صفحتُه مخالفة ونقلٌ مختلَق عمدًا ليظهر حكمُهما.
الاستعمال: python make_chapter.py <المسار.docx>"""
import sys
import zipfile
from xml.sax.saxutils import escape

W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
PARAS = [
    ("الفصل الأول: معنى التوحيد عند أهل العلم (فصلٌ تجريبيّ)", None),
    ("قرّر الشيخ محمد بن عبد الوهاب أصلَ المسألة فقال: «التوحيد هو إفراد الله سبحانه بالعبادة»", "1"),
    ("وبيّن ابن تيمية حقيقة الإسلام بقوله: «فالإسلام يتضمن الاستسلام لله وحده»", "2"),
    ("وعرّفه الشيخ صالح الفوزان شرعًا بأنه: «إفراد الله سبحانه وتعالى بالعبادة، وترك عبادة ما سواه»", "3"),
    ("ونُسب إليه أنه قال: «التوحيد معرفةٌ مجرّدة لا يلزم منها عمل»", "4"),
]
NOTES = {
    "1": "كشف الشبهات (ص ٣).",
    "2": "التدمرية (ص ١٦٩).",
    "3": "التعليقات المختصرة على متن العقيدة الطحاوية (ص ٣٠).",
    "4": "التدمرية (ص ١٧٠).",
}
rtl = '<w:pPr><w:bidi/></w:pPr>'
body = "".join('<w:p>%s<w:r><w:rPr><w:rtl/></w:rPr><w:t xml:space="preserve">%s</w:t></w:r>%s</w:p>'
               % (rtl, escape(t), '<w:r><w:footnoteReference w:id="%s"/></w:r>' % r if r else "") for t, r in PARAS)
foot = "".join('<w:footnote w:id="%s"><w:p>%s<w:r><w:rPr><w:rtl/></w:rPr><w:t>%s</w:t></w:r></w:p></w:footnote>'
               % (k, rtl, escape(v)) for k, v in NOTES.items())
with zipfile.ZipFile(sys.argv[1], "w") as z:
    z.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
    z.writestr("word/document.xml", '<?xml version="1.0" encoding="UTF-8"?><w:document %s><w:body>%s</w:body></w:document>' % (W, body))
    z.writestr("word/footnotes.xml", '<?xml version="1.0" encoding="UTF-8"?><w:footnotes %s>%s</w:footnotes>' % (W, foot))
