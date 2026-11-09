"""حوارُ اختيار المجلّد: يعمل في عمليّةٍ مستقلّة لأنّ نافذة Tk تريد خيطَها الرئيسيَّ."""
import os
import subprocess

import common


def ask() -> None:
    """تُستدعى في العمليّة الفرعيّة (Bughya --pick-folder): تطبع المجلّدَ المختار."""
    common.setup_io()        # المسارُ قد يكون عربيًّا، ولا يُطبع سليمًا بترميز النظام
    import tkinter as t
    import tkinter.filedialog as f
    r = t.Tk()
    r.withdraw()
    r.attributes("-topmost", True)
    print(f.askdirectory(title="اختر مجلّد كتبك", parent=r))


def pick_folder() -> str:
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    out = subprocess.run(common.self_cmd("--pick-folder"), capture_output=True, text=True, encoding="utf-8",
                         errors="replace", timeout=900, env=env, cwd=str(common.APP),
                         creationflags=0x08000000 if os.name == "nt" else 0).stdout
    path = out.strip().splitlines()[-1].strip() if out.strip() else ""
    return path.replace("/", os.sep) if path else ""
