"""حواراتُ اختيار المجلّد والملفّ: تعمل في عمليّةٍ مستقلّة لأنّ نافذة Tk تريد خيطَها الرئيسيَّ.

    Bughya --pick-folder [العنوان]            مجلّد
    Bughya --pick-save <الاسم المقترح>        موضعُ حفظ النسخة الاحتياطيّة (zip)
    Bughya --pick-open                        ملفُّ نسخةٍ احتياطيّة لاسترجاعه (zip)
"""
import os
import subprocess

import common

ZIP = [("نسخة بُغية الاحتياطيّة", "*.zip")]


def ask(kind: str = "folder", arg: str = "") -> None:
    """تُستدعى في العمليّة الفرعيّة: تطبع ما اختاره المستخدم (أو لا شيء إن ألغى)."""
    common.setup_io()        # المسارُ قد يكون عربيًّا، ولا يُطبع سليمًا بترميز النظام
    import tkinter as t
    import tkinter.filedialog as f
    r = t.Tk()
    r.withdraw()
    r.attributes("-topmost", True)
    if kind == "save":
        out = f.asksaveasfilename(title="أين تحفظ النسخة الاحتياطيّة؟", parent=r, initialfile=arg or "نسخة.zip",
                                  defaultextension=".zip", filetypes=ZIP)
    elif kind == "open":
        out = f.askopenfilename(title="اختر ملفَّ النسخة الاحتياطيّة", parent=r, filetypes=ZIP)
    else:
        out = f.askdirectory(title=arg or "اختر مجلّد كتبك", parent=r)
    print(out or "")


def _run(*args) -> str:
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    out = subprocess.run(common.self_cmd(*args), capture_output=True, text=True, encoding="utf-8",
                         errors="replace", timeout=900, env=env, cwd=str(common.APP),
                         creationflags=0x08000000 if os.name == "nt" else 0).stdout
    path = out.strip().splitlines()[-1].strip() if out.strip() else ""
    return path.replace("/", os.sep) if path else ""


def pick_folder(title: str = "") -> str:
    return _run("--pick-folder", *([title] if title else []))


def pick_save(name: str) -> str:
    return _run("--pick-save", name)


def pick_open() -> str:
    return _run("--pick-open")
