"""«بُغية»: يشغّل الخادمَ المحلّي ويفتح الصفحة في المتصفّح. (يُفتح بنقرتين، أو من run.bat)

ويُستدعى بوسائط لأدواته الفرعيّة (فيعمل بعد التغليف ملفًّا واحدًا بلا بايثون منفصل):
    Bughya --tool <أداة> ...      تشغيلُ أداةٍ من المحرّك (maktaba · bahth · nass · sura · mustalah · tadqiq)
    Bughya --pick-folder          حوارُ اختيار مجلّد
"""
import multiprocessing
import pathlib
import sys

if not getattr(sys, "frozen", False):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent / "app"))


def main() -> int:
    multiprocessing.freeze_support()
    import os
    os.environ["PYINSTALLER_SUPPRESS_SPLASH_SCREEN"] = "1"     # شاشةُ البداية للنافذة وحدها، لا لأدواتها الفرعيّة
    if not (len(sys.argv) == 1):            # أداةٌ أو حوارٌ أو تشغيلٌ في المتصفّح: لا شاشة بداية
        try:
            import pyi_splash
            pyi_splash.close()
        except Exception:
            pass
    if len(sys.argv) > 2 and sys.argv[1] == "--tool":
        import importlib
        name = sys.argv[2]
        sys.argv = [name + ".py"] + sys.argv[3:]
        return importlib.import_module(name).main() or 0
    if len(sys.argv) > 1 and sys.argv[1] == "--pick-folder":
        import tkinter_dialog
        tkinter_dialog.ask()
        return 0
    import wajiha
    if len(sys.argv) > 1:      # --no-open أو --browser: في المتصفّح (للفحص)
        sys.argv = [a for a in sys.argv if a != "--browser"]
        return wajiha.main()
    return wajiha.run_app()


if __name__ == "__main__":
    sys.exit(main())
