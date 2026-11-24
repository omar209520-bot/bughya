#!/usr/bin/env python3
"""موصلُ بُغية: يتيح لـClaude Desktop أن يبحث في مكتبة الباحث على جهازه، ويقرأ صفحاتها، ويقابل النقولَ بها.

يعمل على جهاز الباحث وحده (بروتوكول MCP عبر stdio)، ويقرأ مخزنَ النصّ للقراءة فقط: لا يكتب في المكتبة شيئًا،
ولا يتّصل بالإنترنت. وكلُّ أداةٍ فيه تستدعي أداةَ بُغية المقابلة (bahth وnass وbawwaba وmaktaba) بـ--json في
عمليّةٍ مستقلّة؛ فالنتائجُ هي نتائجُ البرنامج نفسُها، وطباعةُ الأدوات لا تختلط بقناة البروتوكول.

ليس جزءًا من البرنامج المنشور (لا يُذكر في build_exe.bat)، ويحتاج مكتبةَ mcp في بيئة التشغيل من الكود:
    .venv\\Scripts\\python.exe -m pip install mcp

وتسجيلُه في Claude Desktop (الإعدادات ← المطوّر ← تعديل الإعدادات، أي ملفّ claude_desktop_config.json):
    {"mcpServers": {"bughya": {"command": "C:\\\\…\\\\bughya\\\\.venv\\\\Scripts\\\\python.exe",
                               "args": ["C:\\\\…\\\\bughya\\\\app\\\\mawsil.py"]}}}

وتجربتُه بلا Claude: python app/mawsil.py --try "العبارة"
"""
import functools
import json
import os
import pathlib
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

APP = pathlib.Path(__file__).resolve().parent
TIMEOUT = 120
PORT = int(os.environ.get("BUGHYA_PORT") or 8777)         # منفذُ صفحة بُغية (wajiha.py)

# ما يُرسَل من بيانات الكتاب: لا مسارُ الملفّ ولا مجلّدُه ولا بصمتُه، فهي من جهاز الباحث لا من الكتاب
BOOK_FIELDS = ("id", "title", "author", "death", "fann", "series", "volume", "unit", "pages", "done_pages",
               "ocr_pages", "state")

INSTRUCTIONS = """\
بُغية مكتبةُ الباحث الخاصّة على جهازه: كتبٌ قرأها برنامجُ «بُغية» (بي دي إف نصّيٌّ ومصوَّر، ووورد، ونصوص).
- ابحث بـsearch_library، ثمّ اقرأ السياقَ بـread_page أو read_around قبل أن تنقل؛ فالمقتطفُ في نتائج البحث قصير.
- رقمُ الصفحة في الأدوات رقمُها في الملفّ (أو القطعة)، لا الرقمُ المطبوع. والعزوُ الذي تكتبه للباحث هو حقلُ cite.
- الصفحةُ التي method فيها ocr قُرئت آليًّا من صورتها، فقد تخطئ في النقاط والحروف: نبّه الباحثَ أن يقابل النقلَ بصورة الصفحة
  في البرنامج. وإن لم تجد كلمةً في كتبٍ مصوَّرة فأعد البحثَ بـrasm=true (يتسامح مع خطأ النقاط).
- كلُّ بحثٍ يبيّن التغطية: ما لم يُقرأ من الكتب لم يُبحث فيه؛ فلا تقل «ليس في كتبك» وفي المكتبة ما لم يُقرأ.
- قبل أن تسلّم نقلًا معزوًّا إلى صفحة قابِله بها بـverify_quote، وانقل النصَّ كما في الصفحة.
- ما في الحاشية (layer: حاشية) كلامُ المحقّق أو الشارح غالبًا، لا كلامُ المؤلّف.
- لتُري الباحثَ صورةَ صفحةٍ (ولا سيّما المقروءةُ آليًّا قبل أن يعتمد نقلًا منها) افتحها له في بُغية بـopen_in_bughya، ومعها النقلُ
  ليُظلَّل في الصورة؛ فيقابله بعينه.
"""


class ToolError(Exception):
    pass


def run(tool: str, *args, ok_codes=(0,)) -> object:
    """يشغّل أداةَ بُغية بـ--json ويعيد ناتجها. والخطأُ رسالةٌ عربيّة تصل إلى Claude كما هي."""
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)          # لا تومض نافذةُ طرفيّة في ويندوز
    try:
        p = subprocess.run([sys.executable, str(APP / (tool + ".py")), *map(str, args), "--json"],
                           capture_output=True, env=env, timeout=TIMEOUT, creationflags=flags, cwd=str(APP))
    except subprocess.TimeoutExpired:
        raise ToolError("طال البحثُ أكثرَ من %d ثانية؛ ضيّقه بكتبٍ أو بعبارةٍ أطول." % TIMEOUT)
    out = p.stdout.decode("utf-8", "replace").strip()
    if p.returncode in ok_codes and out:
        try:
            return json.loads(out)
        except ValueError:
            pass
    # الأدواتُ تكتب خطأها في المخرج نفسه («✗ …» من common.die)، وما انهار منها يكتبه في مخرج الأخطاء
    lines = [x for x in (out + "\n" + p.stderr.decode("utf-8", "replace")).splitlines() if x.strip()]
    msg = next((x for x in reversed(lines) if x.startswith("✗")), lines[-1] if lines else "")
    raise ToolError(msg.lstrip("✗ ").strip() or "تعذّر تشغيلُ %s (الرمز %d)" % (tool, p.returncode))


def _ids(books) -> list:
    if not books:
        return []
    return ["--book", ",".join(str(int(b)) for b in books)]


# ───────────────────────── الأدوات ─────────────────────────

def search_library(text: str, mode: str = "phrase", exact: bool = False, rasm: bool = False, layer: str = "all",
                   books: list = None, fann: str = None, per_book: bool = False, limit: int = 20,
                   offset: int = 0) -> dict:
    mode = mode if mode in ("phrase", "words", "any", "near", "query") else "phrase"
    args = [text] if mode == "phrase" else ["--" + mode, text]
    args += ["--exact"] * bool(exact) + ["--rasm"] * bool(rasm)
    args += ["--layer", layer if layer in ("body", "foot", "all") else "all"]
    args += _ids(books) + (["--fann", fann] if fann else [])
    if per_book:
        res = run("bahth", *args, "--facet")
    else:
        res = run("bahth", *args, "--limit", max(1, min(int(limit), 50)), "--offset", max(0, int(offset)))
    res.pop("expr", None)                    # صيغةُ البحث الداخليّة: طويلةٌ ولا تفيد القارئ
    return res


def read_page(book: int, page: int, to_page: int = None, layer: str = "all") -> object:
    span = str(int(page)) if not to_page or int(to_page) <= int(page) else "%d-%d" % (int(page), min(int(to_page), int(page) + 4))
    return run("nass", int(book), span, "--layer", layer if layer in ("body", "foot", "all") else "all")


def read_around(book: int, text: str, window: int = 600, rasm: bool = False, exact: bool = False) -> object:
    return run("nass", int(book), "--around", text, "--window", max(100, min(int(window), 2000)),
               *(["--rasm"] if rasm else []), *(["--exact"] if exact else []))


def book_toc(book: int) -> dict:
    toc = run("nass", int(book), "--toc")
    return {"toc": toc} if toc else {"toc": [], "note": "لا عناوينَ مسجّلةً لهذا الكتاب؛ ابحث فيه بـsearch_library وbooks."}


def list_books(query: str = None) -> dict:
    rows = [{k: r.get(k) for k in BOOK_FIELDS} for r in run("maktaba", "books")
            if r.get("state") not in ("duplicate",)]
    if query:
        q = query.strip()
        rows = [r for r in rows if any(q in (r.get(k) or "") for k in ("title", "author", "fann", "series"))]
    return {"count": len(rows), "books": rows}


def verify_quote(book: int, page: int, quote: str, layer: str = None) -> dict:
    args = ["check", int(book), int(page), quote]
    if layer in ("متن", "حاشية"):
        args += ["--layer", layer]
    return run("bawwaba", *args, ok_codes=(0, 1))        # الرمز ١: «غيرُ مطابق»، وهو حكمٌ لا خطأ


def _bughya(path: str, timeout: float = 3) -> object:
    """طلبٌ إلى صفحة بُغية العاملة على الجهاز. يعيد None إن لم تكن تعمل، و"old" إن كانت أقدمَ من الأداة."""
    try:
        with urllib.request.urlopen("http://127.0.0.1:%d%s" % (PORT, path), timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return "old" if e.code == 404 else None
    except (OSError, ValueError):
        return None


def _start_bughya() -> bool:
    """يفتح برنامجَ بُغية المنصَّب إن لم يكن مفتوحًا، وينتظر صفحته."""
    exe = pathlib.Path(os.environ.get("LOCALAPPDATA") or "") / "Programs" / "Bughya" / "Bughya.exe"
    if not exe.is_file():
        return False
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    subprocess.Popen([str(exe)], cwd=str(exe.parent), creationflags=flags, close_fds=True,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(40):
        time.sleep(1)
        if _bughya("/api/ping", 1) is not None:
            return True
    return False


def open_in_bughya(book: int, page: int, quote: str = None) -> dict:
    book, page = int(book), int(page)
    info = run("nass", book, str(page))                     # يتحقّق من الكتاب والصفحة، ويعطي العزو
    info = info[0] if isinstance(info, list) and info else {}
    cite = info.get("cite")
    if info.get("unit") not in (None, "صفحة"):
        raise ToolError("هذا الكتاب بلا صفحاتٍ مرسومة (%s)؛ فلا صورةَ له. اقرأه بـread_page." % (info.get("unit") or ""))
    if _bughya("/api/ping") is None and not _start_bughya():
        raise ToolError("بُغية ليست مفتوحة، وتعذّر فتحُها؛ فليفتحها الباحثُ ثمّ أعد الطلب.")
    q = urllib.parse.urlencode({"b": book, "n": page, "mark": (quote or "")[:400]})
    res = _bughya("/api/goto?" + q)
    if isinstance(res, dict) and res.get("ok"):
        return {"opened": True, "cite": cite,
                "note": "فُتحت الصفحة في بُغية مع صورتها" + ("، والنقلُ مظلَّلٌ فيها إن وُجد في أسطرها" if quote else "")}
    if res == "old":
        # إصدارٌ من بُغية لا يعرف هذا الطلب: تُفتح صورةُ الصفحة وحدها في عارض الصور
        out = subprocess.run([sys.executable, str(APP / "sura.py"), str(book), str(page), "--full", "--open",
                              *(["--mark", quote] if quote else [])], capture_output=True, cwd=str(APP),
                             env=dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8"),
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), timeout=TIMEOUT)
        if out.returncode == 0:
            return {"opened": True, "cite": cite, "note": "إصدارُ بُغية المنصَّب أقدمُ من هذه الأداة، "
                    "ففُتحت صورةُ الصفحة في عارض الصور بدل البرنامج"}
        raise ToolError("تعذّر فتحُ صورة الصفحة.")
    raise ToolError("لم تُجب بُغية؛ فليتأكّد الباحثُ أنّها مفتوحة.")


# ───────────────────────── الخادم ─────────────────────────

DOCS = {
    search_library: "ابحث في كتب الباحث المقروءة. "
                    "mode: phrase عبارةٌ متّصلة (الأصل، ومعها سوابقُ أوّل كلمة: والصلاة، بالصلاة)، words كلماتٌ في صفحةٍ "
                    "واحدة بأيّ ترتيب، any أيُّ كلمة، near كلماتٌ متقاربة، query صيغةُ المتمرّس (AND وOR وNOT وNEAR والنجمة). "
                    "exact: بلا سوابق. rasm: متسامحٌ مع خطأ النقاط في الكتب المقروءة آليًّا. layer: body المتن، foot الحاشية، all كلاهما. "
                    "books: أرقامُ كتبٍ لحصر البحث فيها (من list_books). fann: صنفُ الكتب (مثل: الفقه). "
                    "per_book: عددُ المواضع في كلّ كتاب بدل المواضع نفسها (لمعرفة أين ورد اللفظ). "
                    "النتيجة: coverage (ما قُرئ من المكتبة)، وpages (عددُ الصفحات)، وresults: لكلٍّ book_id وn (رقمُ صفحة الملفّ) "
                    "وcite (العزو) وlayer وmethod (ocr = قراءةٌ آليّة) وsnippets (المواضعُ بين 【】). limit أقصاه ٥٠، وoffset للتالي.",
    read_page: "اقرأ صفحةً كاملة من كتاب (رأسُها ومتنُها وحاشيتُها وعزوُها)، أو إلى to_page (خمسُ صفحاتٍ فأقلّ). "
               "page رقمُ الصفحة في الملفّ كما في نتائج البحث (n)، لا الرقمُ المطبوع.",
    read_around: "نافذةٌ حول كلّ موضعٍ لعبارةٍ في كتابٍ واحد، تتّسع إلى الصفحة المجاورة إن اتّصل الكلامُ بها: "
                 "لقراءة كلّ ما في الكتاب عن مسألةٍ دون قراءة صفحاته كاملة. window طولُ النافذة بالحروف.",
    book_toc: "عناوينُ الكتاب (فهرسُه) بأرقام صفحاتها في الملفّ: للوصول إلى بابٍ بعينه.",
    list_books: "كتبُ المكتبة: الرقمُ والعنوانُ والمؤلّفُ والوفاةُ والفنُّ والجزءُ وعددُ الصفحات وما قُرئ منها وما قُرئ آليًّا، "
                "والحال (done مقروء، reading يُقرأ، pending ينتظر، missing ملفُّه غائب). "
                "query: كلمةٌ تُطلب في العنوان أو المؤلّف أو الفنّ.",
    verify_quote: "قابِل نقلًا بالصفحة المعزوّ إليها قبل تسليمه. الأحكام: مطابقٌ حرفيًّا، مطابقٌ بلا تشكيل، "
                  "مطابقٌ بعد التطبيع (رسمٌ مخالف: صحّحه من الصفحة)، يمتدّ إلى الصفحة التالية، غيرُ مطابق (ومعه أقربُ ما في الصفحة). "
                  "layer: متن أو حاشية، إن عُزي إلى أحدهما.",
    open_in_bughya: "افتح صفحةً في برنامج بُغية على جهاز الباحث (ويُفتح البرنامجُ إن كان مغلقًا)، مع صورتها ونصّها، "
                    "ليراها بعينه ويقابل بها النقل. quote: النقلُ ليُظلَّل في الصورة. page رقمُ صفحة الملفّ (n). "
                    "لا يصلك منها شيء؛ إنّما تُعرض للباحث.",
}


def server():
    try:
        from mcp.server.mcpserver import MCPServer as Server          # mcp 2
    except ImportError:
        from mcp.server.fastmcp import FastMCP as Server               # mcp 1
    try:
        from mcp.server.mcpserver.exceptions import ToolError as McpError
    except ImportError:
        from mcp.server.fastmcp.exceptions import ToolError as McpError
    from mcp.types import ToolAnnotations
    srv = Server("bughya", instructions=INSTRUCTIONS)
    ro = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)

    def guard(fn):
        # المكتبةُ تخفي عن Claude رسالةَ كلّ خطأٍ إلّا خطأها هي؛ فتُنقل رسالةُ بُغية العربيّة إليه
        @functools.wraps(fn)
        def inner(*a, **k):
            try:
                return fn(*a, **k)
            except ToolError as e:
                raise McpError(str(e)) from None
            except (ValueError, TypeError) as e:
                raise McpError("مدخلٌ غيرُ صالح: %s" % e) from None
        return inner

    for fn, doc in DOCS.items():
        srv.tool(name=fn.__name__, description=doc, annotations=ro)(guard(fn))
    return srv


def main() -> int:
    if len(sys.argv) > 2 and sys.argv[1] == "--try":           # تجربةٌ بلا Claude
        for s in (sys.stdout, sys.stderr):
            s.reconfigure(encoding="utf-8")
        print(json.dumps(search_library(sys.argv[2], limit=5), ensure_ascii=False, indent=1))
        return 0
    server().run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
