#!/usr/bin/env python3
"""تركيبُ موصل Claude (mawsil.py) على جهاز مستخدمٍ آخر لبُغية، بلا أوامر.

يشغّله «ركب-موصل-Claude.bat» بعد أن يجهّز بيئةَ المجلّد (.venv) ومكتبةَ mcp، ويُسحب إليه ملفُّ إعدادات Claude
(claude_desktop_config.json، يُفتح موضعُه من Claude: الإعدادات ← المطوّر ← تعديل الإعدادات):
  ١. يجرّب الموصلَ على مكتبة بُغية في هذا الجهاز (بحثٌ قصير).
  ٢. يحفظ نسخةً من ملفّ الإعدادات، ثمّ يضيف إليه «bughya» وحده، ولا يمسّ ما فيه غيره.
ويعرض النتيجةَ في نافذةِ رسالةٍ عربيّة (فالطرفيّةُ لا تُحسن عرضَ العربيّة).
"""
import json
import os
import pathlib
import shutil
import sys
import time

APP = pathlib.Path(__file__).resolve().parent
TITLE = "موصل بُغية لـClaude"


def say(text: str, error: bool = False) -> None:
    if os.environ.get("BUGHYA_TARKIB_PRINT"):           # للتجربة: تُطبع الرسالةُ بدل النافذة
        sys.stdout.reconfigure(encoding="utf-8")
        print(("✗ " if error else "") + text)
        return
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, text, TITLE, 0x10 if error else 0x40)
    except Exception:
        print(text)


def main() -> int:
    sys.path.insert(0, str(APP))
    import mawsil

    # ١. تجربةُ الموصل على مكتبة هذا الجهاز
    try:
        res = mawsil.search_library("الله", limit=1)
        cov = res.get("coverage") or {}
    except Exception as e:
        say("الموصل لم يستطع أن يقرأ مكتبة بُغية في هذا الجهاز:\n\n%s\n\n"
            "افتح برنامج بُغية، وأضف كتبك، وانتظر حتّى تُقرأ، ثمّ أعد المحاولة." % e, error=True)
        return 1
    if not cov.get("done"):
        say("مكتبة بُغية في هذا الجهاز لم يُقرأ منها كتابٌ بعد.\n\n"
            "افتح برنامج بُغية، وأضف كتبك، وانتظر حتّى تُقرأ، ثمّ أعد المحاولة.", error=True)
        return 1

    # ٢. ملفُّ إعدادات Claude المسحوب إلى ملفّ التركيب
    if len(sys.argv) < 2:
        say("جُهّز الموصل، وجرّبتُه على مكتبتك فعمل (%d كتابًا مقروءًا).\n\n"
            "بقيت خطوةٌ واحدة: افتح Claude، ثمّ الإعدادات ← المطوّر (Developer) ← تعديل الإعدادات (Edit Config)، "
            "فيظهر ملفّ claude_desktop_config.json. اسحبه بالفأرة وأفلته فوق ملفّ «ركب-موصل-Claude»." % cov["done"])
        return 0
    cfg = pathlib.Path(sys.argv[1])
    if cfg.name.lower() != "claude_desktop_config.json" or not cfg.is_file():
        say("هذا ليس ملفّ إعدادات Claude.\n\nاسحب الملفّ الذي اسمه claude_desktop_config.json "
            "(يظهر من Claude: الإعدادات ← المطوّر ← تعديل الإعدادات).", error=True)
        return 1
    try:
        text = cfg.read_text(encoding="utf-8-sig").strip()
        data = json.loads(text) if text else {}
    except ValueError:
        say("ملفّ إعدادات Claude فيه خطأٌ في صيغته، فلم أعدّله.\n\n%s" % cfg, error=True)
        return 1
    if not isinstance(data, dict) or not isinstance(data.get("mcpServers", {}), dict):
        say("ملفّ إعدادات Claude على غير الصيغة المعروفة، فلم أعدّله.", error=True)
        return 1
    backup = cfg.with_name(cfg.name + ".قبل-بغية-%s" % time.strftime("%Y%m%d-%H%M%S"))
    shutil.copy2(cfg, backup)
    data.setdefault("mcpServers", {})["bughya"] = {
        "command": str(pathlib.Path(sys.executable)),
        "args": [str(APP / "mawsil.py")],
        "env": {"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"},
    }
    cfg.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    say("تمّ. أُضيف الموصل «bughya» إلى إعدادات Claude.\n\n"
        "الآن أغلق Claude إغلاقًا تامًّا (من أيقونته قرب الساعة: Quit)، ثمّ افتحه.\n\n"
        "وحُفظت نسخةٌ من الإعدادات قبل التعديل:\n%s" % backup.name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
