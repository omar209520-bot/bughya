"""المشترك بين أدوات «بُغية»: المواضع، والإعداد، والطباعة بالعربيّة.

الكودُ في مجلّد البرنامج (APP)، وبياناتُ كلّ مستخدمٍ في مجلّدٍ خاصّ به (DATA):
    %LOCALAPPDATA%/Bughya/   (ويُغيَّر بالمتغيّر BUGHYA_HOME للتجربة)
        store/      مخزنُ النصّ (store.db) وحالُ القراءة (progress.json)
        books/      الكتبُ التي سحبها المستخدم إلى النافذة (نسخةٌ منها)
        inbox/      ملفّاتُ وورد المسحوبةُ للتدقيق
        outputs/    ما يُصدَّر، وصورُ الصفحات في outputs/images
        config.json · groups.json · exclusions.json
"""
import json
import os
import pathlib
import sys
import time

FROZEN = bool(getattr(sys, "frozen", False))
APP_DATA = pathlib.Path(__file__).resolve().parent / "data"
APP = pathlib.Path(sys.executable).resolve().parent if FROZEN else pathlib.Path(__file__).resolve().parent


def self_cmd(*args) -> list:
    """أمرُ تشغيل البرنامج نفسه بوسائط (لأدواته الفرعيّة): بعد التغليف هو ملفُّ التشغيل، وقبله بايثون وBughya.pyw."""
    if FROZEN:
        return [sys.executable, *map(str, args)]
    return [sys.executable.replace("pythonw.exe", "python.exe"), str(APP.parent / "Bughya.pyw"), *map(str, args)]


def tool_cmd(tool: str, *args) -> list:
    """أمرُ تشغيل أداةٍ من أدوات المحرّك (maktaba.py ← maktaba)."""
    return self_cmd("--tool", tool.removesuffix(".py"), *args)
TOOLS = APP
NAME = "Bughya"
VERSION = "0.9.3"
# صفحةُ الإصدارات: يسأل منها زرُّ التحديث عن آخر إصدارٍ منشور (ولا يُرسل شيئًا عن المستخدم ولا كتبه)
RELEASES_API = "https://api.github.com/repos/omar209520-bot/bughya/releases/latest"
DATA = pathlib.Path(os.environ.get("BUGHYA_HOME") or
                    (pathlib.Path(os.environ.get("LOCALAPPDATA") or pathlib.Path.home() / "AppData" / "Local") / NAME))
BOOKS = DATA / "books"
STORE_DIR = DATA / "store"
STORE_DB = STORE_DIR / "store.db"
PROGRESS = STORE_DIR / "progress.json"
OUTPUTS = DATA / "outputs"
IMAGES = OUTPUTS / "images"
INBOX = DATA / "inbox"
CONFIG = DATA / "config.json"
GROUPS = DATA / "groups.json"
EXCLUSIONS = DATA / "exclusions.json"
IS_WIN = os.name == "nt"
IS_MAC = sys.platform == "darwin"

AR_DIGITS = str.maketrans("0123456789", "٠١٢٣٤٥٦٧٨٩")


def setup_io() -> None:
    """الطباعةُ بالعربيّة في كلّ طرفيّة: ويندوز يطبع بترميز النظام ما لم يُؤمَر بغيره."""
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def ar(n) -> str:
    """الأرقامُ بالأرقام العربيّة المشرقيّة: ١٢٣."""
    return str(n).translate(AR_DIGITS)


def count_word(n: int, one: str, two: str, few: str, many: str) -> str:
    """تمييزُ العدد: «كتابٌ واحد» · «كتابان» · «٣ كتب» · «١١ كتابًا»."""
    if n == 1:
        return one
    if n == 2:
        return two
    if 3 <= n % 100 <= 10:
        return f"{ar(n)} {few}"
    return f"{ar(n)} {many}"


def units(n: int, unit: str) -> str:
    """عددُ الوحدات بتمييزه: «صفحتان» · «٣ صفحات» · «١٢ قطعةً»."""
    if unit == "قطعة":
        return count_word(n, "قطعةٌ واحدة", "قطعتان", "قطع", "قطعةً")
    return count_word(n, "صفحةٌ واحدة", "صفحتان", "صفحات", "صفحةً")


def load_config() -> dict:
    try:
        cfg = json.loads(CONFIG.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        cfg = {}
    cfg.setdefault("sources", [])
    return cfg


def save_config(cfg: dict) -> None:
    write_json(CONFIG, cfg)


def sources() -> list:
    """مجلّداتُ الكتب: مجلّدُ ما سحبه المستخدم دائمًا، وما أضافه من مجلّداتٍ."""
    out, seen = [], set()
    for s in [str(BOOKS)] + load_config().get("sources", []):
        p = pathlib.Path(s).expanduser()
        key = os.path.normcase(str(p.resolve())) if p.exists() else os.path.normcase(str(p))
        if key not in seen:
            seen.add(key)
            out.append(p)
    return out


def write_json(path: pathlib.Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    for i in range(20):   # في ويندوز يُرفض الاستبدالُ ما دام قارئٌ آخرُ فاتحًا الملفّ (أداةُ الحال أو صفحةُ التعريف): أعِد المحاولة
        try:
            tmp.replace(path)
            return
        except PermissionError:
            if i == 19:
                raise
            import time
            time.sleep(0.1 * (i + 1))


def read_json(path: pathlib.Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return default


def now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def die(msg: str, code: int = 2) -> None:
    print("✗ " + msg)
    sys.exit(code)


def resume_reading(first_delay: int = 20, every: int = 1800) -> None:
    """يستأنف قراءةَ الكتب وحده في الخلفيّة: مرّةً بعد ‹first_delay› ثانية (فيُقرأ ما جدّ)، ثمّ كلّ ‹every› ثانية ما دام
    في الكتب ما لم يُقرأ (بعد إيقاف الجهاز أو نومه). يستعمله الجسرُ وصفحةُ البحث؛ و«update» نفسه لا يبدأ قراءةً ثانية إن كانت جارية."""
    import subprocess
    import threading

    def start():
        try:
            subprocess.run(tool_cmd("maktaba", "update", "--detach"), cwd=str(APP), capture_output=True, timeout=120, stdin=subprocess.DEVNULL,
                           creationflags=0x08000000 if IS_WIN else 0)
        except Exception:
            pass

    def loop():
        time.sleep(first_delay)
        start()
        while True:
            time.sleep(every)
            pr = read_json(PROGRESS, {}) or {}
            if pr.get("pending"):
                start()

    threading.Thread(target=loop, daemon=True).start()
