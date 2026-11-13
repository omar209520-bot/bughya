#!/usr/bin/env python3
"""الفحصُ الذاتيّ لبُغية: هل يقرأ المحرّكُ الكتبَ ويبحث فيها ويقابل النقولَ ويدقّق إحالاتِ فصلٍ على هذا الجهاز؟

يعمل في مجلّد بياناتٍ مؤقّت (لا يمسّ مكتبةَ المستخدم)، ويصنع ملفّاتِ تجربةٍ صغيرة (نصٌّ بترميزين، ووورد بحاشية،
وصفحةُ ويب، وبي دي إف)، ويطبع سطرًا لكلّ فحص. والقراءةُ الآليّة فحصٌ ثانويّ: غيابُها لا يُفشل الفحص
(الكتبُ التي فيها نصٌّ تُقرأ بدونها). وملفّاتُ التجربة تُحذف بعد الفحص.

    .venv\\Scripts\\python.exe selftest.py
"""
import os
import pathlib
import shutil
import sys
import tempfile
import zipfile

TMP = pathlib.Path(tempfile.mkdtemp(prefix="bughya-selftest-"))
os.environ["BUGHYA_HOME"] = str(TMP / "home")      # قبل استيراد common
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent / "app"))

SENT = "قال المؤلف في باب الطهارة إن الماء طهور لا ينجسه شيء"
FOOT = "هذه حاشية التجربة"
W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


def make_docx(path: pathlib.Path, paras, notes=None) -> None:
    body = "".join('<w:p><w:r><w:t>%s</w:t></w:r>%s</w:p>' % (t, '<w:r><w:footnoteReference w:id="%s"/></w:r>' % r if r else "")
                   for t, r in paras)
    foot = "".join('<w:footnote w:id="%s"><w:p><w:r><w:t>%s</w:t></w:r></w:p></w:footnote>' % (k, v)
                   for k, v in (notes or {}).items())
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        z.writestr("word/document.xml", '<?xml version="1.0" encoding="UTF-8"?><w:document %s><w:body>%s</w:body></w:document>' % (W, body))
        z.writestr("word/footnotes.xml", '<?xml version="1.0" encoding="UTF-8"?><w:footnotes %s>%s</w:footnotes>' % (W, foot))


def main() -> int:
    results, core_ok = [], True

    def report(ok: bool, name: str, why: str = "", core: bool = True) -> None:
        nonlocal core_ok
        results.append(ok)
        if core and not ok:
            core_ok = False
        print(("✓ " if ok else ("✗ " if core else "⚠ ")) + name + ("" if ok else " — " + why))

    try:
        import arabic
        ok = (arabic.normalize("الصَّلَاةُ عِمَادُ الدِّينِ") == "الصلاه عماد الدين"
              and "والصلاه" in arabic.variants("الصلاه") and arabic.rasm("فهرس") == arabic.rasm("قهرس"))
        report(ok, "التطبيعُ العربيّ والسوابقُ والرسمُ المجرّد")

        import common
        report(str(common.STORE_DIR).startswith(str(TMP)), "بياناتُ المستخدم في مجلّدها الخاصّ لا في مجلّد البرنامج",
               str(common.STORE_DIR))
        books = TMP / "كتب"
        books.mkdir()
        (books / "نص يونيكود.txt").write_text(SENT + "\n\nفقرةٌ أخرى", encoding="utf-8")
        (books / "نص ويندوز.txt").write_bytes(("باب الصلاة: " + SENT).encode("cp1256"))
        make_docx(books / "ملف وورد.docx", [(SENT, "1"), ("فقرةٌ ثانية للتجربة", None)], {"1": FOOT})
        (books / "صفحة.html").write_text("<html><head><title>تجربة</title></head><body><p>%s</p></body></html>" % SENT,
                                         encoding="utf-8")
        try:
            import pymupdf
            d = pymupdf.open()
            d.new_page().insert_text((72, 300), "Bughya selftest 2026 page one: reading and searching")
            d.save(str(books / "latin.pdf"))
            report(True, "مكتبةُ قراءة بي دي إف")
        except Exception as e:
            report(False, "مكتبةُ قراءة بي دي إف", str(e))
        try:
            import openpyxl  # noqa: F401
            report(True, "مكتبةُ إكسل")
        except Exception as e:
            report(False, "مكتبةُ إكسل", str(e))

        import maktaba
        import store
        common.save_config({"sources": [str(books)]})
        con = store.connect()
        maktaba.sync(con)
        for b in con.execute("SELECT * FROM books WHERE state='pending'").fetchall():
            maktaba.read_book(con, b, None)
        states = {pathlib.Path(r["path"]).name: r["state"] for r in con.execute("SELECT path, state FROM books")}
        report(all(v == "done" for v in states.values()) and len(states) == 5,
               "قراءةُ الصيغ (نصٌّ بترميزين، ووورد، وويب، وبي دي إف)", str(states))

        # تكرارُ الكتاب: الملفُّ نفسُه في موضعٍ آخر نسخةٌ مكرَّرة لا تُقرأ، والعنوانُ نفسُه بملفٍّ آخر تنبيهٌ ظنّيّ
        import json
        import shutil
        nus = books / "نسخ"
        nus.mkdir()
        shutil.copy(books / "ملف وورد.docx", nus / "ملف وورد - نسخة.docx")      # الملفُّ نفسُه
        make_docx(nus / "ملف وورد.docx", [("نصٌّ آخرُ في ملفٍّ عنوانُه كعنوانه", None)])   # العنوانُ نفسُه
        maktaba.sync(con)
        dup = con.execute("SELECT state, hints FROM books WHERE path LIKE '%- نسخة%'").fetchone()
        report(bool(dup) and dup["state"] == "duplicate" and "dup" in json.loads(dup["hints"] or "{}"),
               "النسخةُ المكرَّرة لا تُقرأ ثانيةً", str(dict(dup) if dup else None))
        sim = con.execute("SELECT state, hints FROM books WHERE path LIKE '%نسخ%' AND path NOT LIKE '%- نسخة%'"
                          ).fetchone()
        report(bool(sim) and sim["state"] == "pending" and "similar" in json.loads(sim["hints"] or "{}"),
               "المشابهُ عنوانُه يُنبَّه عليه ولا يُمنع من القراءة", str(dict(sim) if sim else None))

        import bahth
        expr, seqs = bahth.build("phrase", bahth.query_tokens("الماء طهور"), False, False)
        hits = bahth.search(con, expr, seqs, False)
        n = len({h["row"]["book_id"] for h in hits})
        report(n == 4, "البحثُ بعبارة في مخزن النصّ", "وُجدت في %d كتب" % n)
        expr, seqs = bahth.build("phrase", bahth.query_tokens("الصلاة"), False, False)
        report(bool(bahth.search(con, expr, seqs, False)), "البحثُ بالسوابق (الصلاة ← «باب الصلاة»)")
        expr, seqs = bahth.build("phrase", bahth.query_tokens("حاشية التجربة"), False, False)
        report(any(h["layer"] == 1 for h in bahth.search(con, expr, seqs, False)), "الحاشيةُ طبقةٌ منفصلة (وورد)")

        import bawwaba
        bid = con.execute("SELECT id FROM books WHERE path LIKE ?", ("%يونيكود%",)).fetchone()[0]
        v1 = bawwaba.verify(con, bid, 1, "إن الماء طهور لا ينجسه شيء")
        v2 = bawwaba.verify(con, bid, 1, "إن الماء نجس")
        report(v1["verdict"] == bawwaba.VERDICTS[0] and v2["verdict"] == bawwaba.VERDICTS[4], "بوّابةُ النقل",
               "%s / %s" % (v1["verdict"], v2["verdict"]))
        con.close()

        import tadqiq
        chap = TMP / "فصل.docx"
        make_docx(chap, [("قال المؤلف: «إن الماء طهور لا ينجسه شيء»", "1"),
                         ("وقال: «نصٌّ مختلقٌ لا وجود له في أيّ كتابٍ من كتب هذه التجربة أبدًا ولا في غيرها»", "2")],
                  {"1": "نص يونيكود (ص 1).", "2": "نص يونيكود (ص 1)."})
        res = tadqiq.run_job(chap)
        v = [i["verdict"] for i in res["items"]]
        report(len(v) == 2 and v[0].startswith("مطابق") and v[1] == "لم يوجد", "مدقّقُ الإحالات", str(v))
        import ayat
        g = ayat.find("قال تعالى ومن يبتع غير الاسلام دينا فلن يقبل منه وهو في الاخرة من الخاسرين وهذا كلام")
        report(len(g) == 1 and g[0]["kind"] == "آية" and g[0]["verses"][0]["aya"] == 85, "مطابقةُ الآيات مع خطأ في النقاط", str(g)[:120])
        report(not ayat.find("ذهب الطالب إلى المكتبة فقرأ كتابًا نافعًا في أصول الدين ثم رجع"), "لا مطابقةَ في كلامٍ عاديّ")
        con2 = store.connect()
        bk2 = con2.execute("SELECT id FROM books LIMIT 1").fetchone()[0]
        store.add_page(con2, bk2, 900, None, "ocr", None, "", "قال تعالى ومن يبتع غير الاسلام دينا فلن يقبل منه وهو في الاخرة من الخاسرين", "")
        con2.commit()
        expr, seqs = bahth.build("phrase", bahth.query_tokens("ومن يبتغ غير الإسلام دينا"), False, False)
        report(any(h["row"]["n"] == 900 for h in bahth.search(con2, expr, seqs, False)), "البحثُ يجد الآية وإن أخطأت القراءةُ في نقاطها")
        store.delete_book_pages(con2, bk2)
        con2.commit()
        expr, seqs = bahth.build("phrase", bahth.query_tokens("ومن يبتغ غير الإسلام دينا"), False, False)
        report(not bahth.search(con2, expr, seqs, False), "حذفُ الصفحة يُخرج لفظَ الآية من جدول البحث")
        con2.close()
        con3 = store.connect()
        bk3 = con3.execute("SELECT id FROM books LIMIT 1").fetchone()[0]
        store.add_page(con3, bk3, 901, None, "ocr", None, "", "باب في فضل الصلوة على وقتها والزكوة", "")
        con3.commit()
        expr, seqs = bahth.build("phrase", bahth.query_tokens("فضل الصلاة"), False, False)
        report(any(h["row"]["n"] == 901 for h in bahth.search(con3, expr, seqs, False)), "البحثُ بالرسم المعاصر يجد الرسمَ القديم (الصلوة)")
        report(con3.execute("SELECT body FROM pages WHERE n=901").fetchone()[0].count("الصلوة") == 1, "نصُّ الكتاب يبقى برسمه القديم")
        con3.close()
        from readers import layout
        L = lambda t, x, y, w: {"t": t, "x": x, "y": y, "w": w, "h": 0.03, "size": 0.03}
        page = [L("السطر الأول من المتن في هذه الصفحة", 0.1, 0.1, 0.8), L("السطر الثاني من المتن", 0.1, 0.5, 0.8),
                L("وآخر سطر من الكلام هنا", 0.1, 0.8, 0.8), L("قال", 0.12, 0.9, 0.06)]
        rec = layout.split_page(page)
        report(rec["catch"] == "قال" and "قال" not in rec["body"].split(), "التعقيبةُ تُعلَّم ولا تدخل المتن", str(rec["catch"]))
        page[-1] = L("قال", 0.8, 0.9, 0.06)      # كلمةٌ في آخر الصفحة على اليمين: آخرُ فقرة، لا تعقيبة
        report(layout.split_page(page)["catch"] is None, "آخرُ فقرةٍ قصيرٌ على اليمين لا يُعدّ تعقيبة")
        from readers.pdf import fix_allah
        report(fix_allah("اذكروا اللَ ذكرا والل أعلم الليل وال") == "اذكروا اللَه ذكرا والله أعلم الليل وال", "لفظُ الجلالة الناقصُ في ملفّات وورد يُردّ، ولا يمسّ غيرَه")
        x = TMP / "t.xlsx"
        tadqiq.to_xlsx(res["items"], x, "فصل.docx", res["coverage"])
        report(x.is_file() and x.stat().st_size > 1000, "تصديرُ نتيجة التدقيق إلى إكسل")
    except Exception as e:
        import traceback
        traceback.print_exc()
        report(False, "خطّ القراءة والبحث والتدقيق", repr(e))

    try:     # فحصٌ ثانويّ: القراءةُ الآليّة لصورة نصٍّ عربيّ
        import arabic
        from readers.ocr import engine
        eng = engine()
        if not eng.ok:
            report(False, "القراءةُ الآليّة", eng.reason, core=False)
        else:
            import pymupdf
            d = pymupdf.open()
            pg = d.new_page(width=420, height=300)
            pg.insert_htmlbox(pymupdf.Rect(20, 20, 400, 280), "<p dir='rtl' style='font-size:22pt'>بسم الله الرحمن الرحيم</p>")
            png = pg.get_pixmap(matrix=pymupdf.Matrix(3, 3), alpha=False).tobytes("png")
            got = arabic.normalize(" ".join(x["text"] for x in eng.recognize(png)))
            report("الرحمن" in got, "القراءةُ الآليّة (%s)" % eng.name, "قرأت: " + got[:60], core=False)
    except Exception as e:
        report(False, "القراءةُ الآليّة", repr(e), core=False)

    print("النتيجة: %d من %d" % (sum(results), len(results)))
    shutil.rmtree(TMP, ignore_errors=True)
    return 0 if core_ok else 1


if __name__ == "__main__":
    sys.exit(main())
