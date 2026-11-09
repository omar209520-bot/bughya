"""يجهّز مكتبةً تجريبيّة في مجلّد بياناتٍ جديد (BUGHYA_HOME) لتسجيل الفيديو.

الاستعمال: python prepare.py <مجلّد_الخطوط> <مجلّد_العمل> <مجلّد_نصوص> [مجلّد_نصوص ...]
ينشئ <العمل>/books (ملفّات PDF) و<العمل>/home (بيانات البرنامج)، ويقرأ الكتب، ويكتب بطاقاتها.
"""
import json
import os
import pathlib
import shutil
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
APP = HERE.parents[1] / "app"
fonts, work, *texts = sys.argv[1:]
work = pathlib.Path(work)
books, home = work / "books", work / "home"
shutil.rmtree(work, ignore_errors=True)
home.mkdir(parents=True)
subprocess.run([sys.executable, str(HERE / "build_library.py"), fonts, str(books), *texts], check=True)
env = dict(os.environ, BUGHYA_HOME=str(home), PYTHONUTF8="1")
mk = lambda *a: subprocess.run([sys.executable, "maktaba.py", *map(str, a)], cwd=APP, env=env, check=True,
                               capture_output=True, text=True).stdout
mk("sources", "add", books)
print(mk("update").strip())
listed = json.loads(mk("books", "--json"))
meta = {b["title"]: b for b in json.loads((books / "books.json").read_text(encoding="utf-8"))}
for b in listed:
    m = meta[b["title"]]
    args = ["set", b["id"], "--author", m["author"], "--notes", f"منقولٌ من المكتبة الشاملة، رقم الكتاب فيها {m['shamela']}"]
    if m.get("volume"):
        args += ["--volume", m["volume"]]
    mk(*args)
print(mk("books"))
