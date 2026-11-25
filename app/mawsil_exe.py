"""مدخلُ «موصل بُغية» المبنيّ برنامجًا مستقلًّا (إضافةُ Claude بصيغة mcpb)، يبنيه build_mawsil.bat.

    BughyaClaude.exe                 الموصل (MCP عبر stdio)، ويشغّله Claude
    BughyaClaude.exe --tool <أداة>   أداةٌ من أدوات بُغية (bahth · nass · bawwaba · maktaba · sura)، يشغّلها الموصلُ نفسُه
    BughyaClaude.exe --try "عبارة"   تجربةٌ بلا Claude

لا يمسّ برنامجَ بُغية المنصَّب: يقرأ مكتبتَه (%LOCALAPPDATA%\\Bughya) للقراءة وحدها.
"""
import sys

READ_ONLY_TOOLS = ("bahth", "nass", "bawwaba", "maktaba", "sura")


def main() -> int:
    for s in (sys.stdout, sys.stderr):              # العربيّةُ في المخرج أيًّا كان ترميزُ الطرفيّة
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    if len(sys.argv) > 2 and sys.argv[1] == "--tool":
        name = sys.argv[2]
        if name not in READ_ONLY_TOOLS:
            print("✗ أداةٌ غيرُ مسموحة في الموصل: %s" % name)
            return 2
        if name == "maktaba" and sys.argv[3:4] != ["books"]:        # من المكتبة قائمةُ الكتب وحدها، لا قراءةٌ ولا تعديل
            print("✗ الموصلُ لا يعدّل المكتبة.")
            return 2
        import importlib
        sys.argv = [name + ".py"] + sys.argv[3:]
        return importlib.import_module(name).main() or 0
    import mawsil
    return mawsil.main()


if __name__ == "__main__":
    sys.exit(main())
