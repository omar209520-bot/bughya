#!/usr/bin/env python3
"""قياسُ جودة تعليم الكلمات المشكوك فيها في الصفحات المقروءة آليًّا، بالطريقتين: القاموس وحده، والقاموس مع السياق.

    .venv\\Scripts\\python.exe app\\maktaba.py lexicon             أوّلًا: يعيد بناء القاموس ومعه فهرسُ الأزواج (مرّةً واحدة)
    .venv\\Scripts\\python.exe tests\\measure_marks.py             يقيس على صفحات المرجع tests/gold ويطبع
    .venv\\Scripts\\python.exe tests\\measure_marks.py --save اسم   ويحفظ النتيجة في tests/results/marks-اسم.json
    .venv\\Scripts\\python.exe tests\\measure_marks.py --sim        محاكاةٌ على نصّ القرآن، بلا صفحاتٍ ولا قراءةٍ آليّة (تعمل على أيّ جهاز)

القياس على صفحات المرجع (يحتاج ويندوز للقراءة الآليّة، وقاموسَ مكتبتك مبنيًّا):
  تُقرأ كلُّ صفحةٍ بقارئ «بُغية» نفسه، وتُعلَّم كلماتُ متنها وحاشيتها كما تعلّمها الواجهة (lexicon.marks)، ثمّ تُقابَل
  بنصّها الصحيح NN.txt كلمةً كلمة. والكلمةُ «خاطئة» إن خالفت مقابلتَها بعد التطبيع (الهمزاتُ والتاء المربوطة والحركات
  لا تُحسب: القاموس لا يراها). وصفحاتُ نصّ الملفّ تُترك: الواجهة لا تعلّم فيها شيئًا.

ما يُطبع، لكلّ طريقة:
  معلَّم     عددُ الكلمات التي وُضعت عليها علامة
  منه خطأ    كم من المعلَّم خاطئٌ حقًّا
  الدقّة      منه خطأ ÷ معلَّم  (العلاماتُ الصادقة؛ وهي المعيار الأوّل: العلامةُ الكاذبة تُفسد الميزة)
  الكشف      منه خطأ ÷ كلّ الكلمات الخاطئة في الصفحات
والطرق:
  القاموس وحده          الطريقةُ القديمة: تُعلَّم الكلمةُ التي لا يعرفها القاموس
  + السياق              الجديدة: وتُعلَّم المعروفةُ الغريبةُ بين جارتيها إن ناسبهما بديلٌ في النقط تكرّر زوجُه (PAIR_MIN = 2)
  + السياق المتساهل     للمقارنة فقط: يكفي أن يرد زوجُ البديل مرّةً واحدة (ليس في البرنامج)
ثمّ تُسرد علاماتُ السياق واحدةً واحدة (✓ خاطئةٌ حقًّا، ✗ صحيحةٌ عُلّمت)، ليُحكم عليها بالنظر.
"""
import argparse
import collections
import difflib
import json
import os
import pathlib
import random
import re
import sys
import tempfile
import time

ROOT = pathlib.Path(__file__).resolve().parent
GOLD = ROOT / "gold"
RESULTS = ROOT / "results"
METHODS = ("القاموس وحده", "+ السياق", "+ السياق المتساهل")
WORD = re.compile("[ء-ي]+")


def key(token: str) -> str:
    """الكلمةُ كما يراها القاموس: مطبَّعةٌ بحروفها العربيّة وحدها."""
    import arabic
    return "".join(WORD.findall(arabic.normalize(token)))


def mark(tokens: list) -> list:
    """لكلّ كلمة: (القاموس وحده، مع السياق، مع السياق المتساهل)."""
    import lexicon
    new, loose = lexicon.marks(tokens), lexicon.marks(tokens, pair_min=1)
    return [(m == 1, m > 0, l > 0) for m, l in zip(new, loose)]


def score(hyp: list, flags: list, gold: list) -> dict:
    """يقابل كلماتِ القراءة (hyp، ولكلٍّ علاماتُه flags) بالنصّ الصحيح (gold)، ويعدّ لكلّ طريقةٍ ما عُلّم وما صدق.

    الكلماتُ التي لا حرفَ عربيًّا فيها (أرقامٌ وعلامات) لا تدخل العدّ. والخاطئةُ ما لم يطابق مقابلتَه: مبدَلةٌ أو زائدة.
    وما سقط من القراءة (في الصحيح وليس فيها) لا يُعلَّم أصلًا، فيُعدّ وحده.
    """
    hk = [(key(t), t, f) for t, f in zip(hyp, flags)]
    hk = [x for x in hk if x[0]]
    gk = [(key(t), t) for t in gold]
    gk = [x for x in gk if x[0]]
    wrong, right = [True] * len(hk), [None] * len(hk)
    missed = 0
    sm = difflib.SequenceMatcher(None, [x[0] for x in hk], [x[0] for x in gk], autojunk=False)
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            for i in range(i1, i2):
                wrong[i] = False
        elif op == "replace" and i2 - i1 == j2 - j1:
            for k in range(i2 - i1):
                right[i1 + k] = gk[j1 + k][1]
        if op in ("delete", "replace", "insert"):
            missed += max(0, (j2 - j1) - (i2 - i1))
    res = {"words": len(hk), "wrong": sum(wrong), "missed": missed, "marked": [0, 0, 0], "hit": [0, 0, 0], "context": [],
           "wrong_flags": wrong}
    for (k, t, f), w, r in zip(hk, wrong, right):
        for m in range(3):
            if f[m]:
                res["marked"][m] += 1
                res["hit"][m] += w
        if f[1] and not f[0]:           # علامةُ سياق: معروفةٌ في القاموس وعُلّمت
            res["context"].append({"word": t, "wrong": w, "right": r})
    return res


def total(rows: list) -> dict:
    t = {"words": 0, "wrong": 0, "missed": 0, "marked": [0, 0, 0], "hit": [0, 0, 0]}
    for r in rows:
        for k in ("words", "wrong", "missed"):
            t[k] += r[k]
        for m in range(3):
            t["marked"][m] += r["marked"][m]
            t["hit"][m] += r["hit"][m]
    return t


def pct(a: int, b: int) -> str:
    return "%.0f%%" % (100 * a / b) if b else "—"


def table(t: dict) -> None:
    print("الطريقة | معلَّم | منه خطأ | الدقّة | الكشف")
    for m, name in enumerate(METHODS):
        print("%s | %d | %d | %s | %s" % (name, t["marked"][m], t["hit"][m], pct(t["hit"][m], t["marked"][m]),
                                          pct(t["hit"][m], t["wrong"])))
    for m in (1, 2):
        dm, dh = t["marked"][m] - t["marked"][0], t["hit"][m] - t["hit"][0]
        print("ما زاده «%s» على القاموس وحده: %d علامة، منها %d على خطأ و%d على صحيح (كاذبة)" % (METHODS[m][2:], dm, dh, dm - dh))


def gold_pages() -> int:
    sys.path.insert(0, str(ROOT.parent / "app"))
    import lexicon
    if not (GOLD / "pages.json").exists():
        print("لا صفحاتِ مرجعٍ في tests/gold (ليست في المستودع لحقوق كتبها). ضع صفحاتك فيه كما في tests/gold/README.md، "
              "أو جرّب المحاكاة: tests\\measure_marks.py --sim")
        return 2
    if not lexicon.ready():
        print("قاموسُ مكتبتك غير مبنيٍّ أو صغير (أقلّ من %d كلمة من كتبك النصّيّة)، فلا يُعلَّم شيءٌ في الواجهة. "
              "ابنِه: .venv\\Scripts\\python.exe app\\maktaba.py lexicon" % lexicon.MIN_WORDS)
        return 2
    if lexicon._pairs() is None:
        print("القاموس مبنيٌّ بإصدارٍ قبل السياق (لا ملفَّ %s)، فالطريقتان الآن سواء. "
              "أعِد بناءه ثمّ أعِد القياس: .venv\\Scripts\\python.exe app\\maktaba.py lexicon" % lexicon.PAIRS.name)
        return 2
    from readers import open_book
    from readers.ocr import engine
    eng = engine()
    if not eng.ok:
        print("القراءةُ الآليّة لا تعمل على هذا الجهاز (%s)، والقياس على صفحات المرجع يحتاجها (ويندوز). "
              "المحاكاة تعمل هنا: tests/measure_marks.py --sim" % eng.reason)
        return 2
    meta = json.loads((GOLD / "pages.json").read_text(encoding="utf-8"))
    rows, skipped = [], []
    print("الصفحة | كلمات | خاطئة | القاموس وحده: معلَّم (منه خطأ) | + السياق: معلَّم (منه خطأ)")
    for m in meta:
        gid = m["id"]
        ref = GOLD / (gid + ".txt")
        if not ref.exists():
            continue
        book = open_book(GOLD / (gid + ".pdf"), eng)
        try:
            pg = next(book.pages(1))
        finally:
            book.close()
        if pg["method"] != "ocr":
            skipped.append(gid)
            continue
        hyp, flags = [], []
        for part in (pg["body"], pg["foot"]):         # المتنُ والحاشية كلٌّ وحده، كما في الواجهة
            ws = (part or "").split()
            hyp += ws
            flags += mark(ws)
        r = score(hyp, flags, ref.read_text(encoding="utf-8").split())
        r["id"] = gid
        rows.append(r)
        print("%s | %d | %d | %d (%d) | %d (%d)" % (gid, r["words"], r["wrong"], r["marked"][0], r["hit"][0],
                                                    r["marked"][1], r["hit"][1]))
    if skipped:
        print("تُركت (نصُّ ملفٍّ لا قراءةٌ آليّة، فلا تُعلَّم): " + " ".join(skipped))
    if not rows:
        print("لا صفحةَ مقروءةً آليًّا في المرجع.")
        return 2
    t = total(rows)
    print("\nالمجموع: %d صفحة، %d كلمة، منها %d خاطئة (%s)، وسقط من القراءة %d كلمة لا تُعلَّم أصلًا."
          % (len(rows), t["words"], t["wrong"], pct(t["wrong"], t["words"]), t["missed"]))
    table(t)
    print("\nعلاماتُ السياق (كلماتٌ يعرفها القاموس وعُلّمت):")
    n = 0
    for r in rows:
        for c in r["context"]:
            n += 1
            print("  %s  صفحة %s: «%s»%s" % ("✓" if c["wrong"] else "✗", r["id"], c["word"],
                                             (" والصحيح «%s»" % c["right"]) if c["right"] else
                                             (" (زائدةٌ أو في موضعٍ مضطرب)" if c["wrong"] else " وهي صحيحة")))
    if not n:
        print("  لا شيء.")
    return rows, t


def simulate(seed: int, tail: bool, rate: float = 0.10) -> tuple:
    """محاكاة: القاموس والفهرس من ٩٠٪ من آيات القرآن، وخطأُ نقطٍ في ١٠٪ من كلمات الباقي. تمرّ بكود البرنامج نفسه (ملفٌّ وبلوم)."""
    home = tempfile.mkdtemp(prefix="bughya-marks-")
    os.environ["BUGHYA_HOME"] = home                  # قبل استيراد common: لا يمسّ قاموسَ المستخدم
    sys.path.insert(0, str(ROOT.parent / "app"))
    import ayat
    import common
    import lexicon
    ayat._load()
    verses = [v["w"] for v in ayat._verses]
    rnd = random.Random(seed)
    cut = len(verses) // 10
    if tail:
        test = set(range(len(verses) - cut, len(verses)))
    else:
        test = set(rnd.sample(range(len(verses)), cut))
    words = collections.Counter()
    index = lexicon._Index(sum(len(w) + 1 for i, v in enumerate(verses) if i not in test for w in v))
    for i, v in enumerate(verses):
        if i not in test:
            words.update(v)
            index.chain(v)
    index.write()
    common.write_json(lexicon.PATH, {"words": dict(words), "lib": len(words)})
    rows, agree = [], True
    for i in sorted(test):
        v = verses[i]
        hyp, bad = list(v), [False] * len(v)
        for j, w in enumerate(v):
            if rnd.random() < rate:
                alts = [w[:p] + d + w[p + 1:] for p, c in enumerate(w) for d in lexicon._DOT.get(c, "") if d != c]
                if alts:
                    hyp[j], bad[j] = rnd.choice(alts), True
        r = score(hyp, mark(hyp), v)
        agree = agree and r["wrong_flags"] == bad      # المقابلةُ يجب أن تجد الأخطاءَ المُدخلة بعينها
        rows.append(r)
    import shutil
    shutil.rmtree(home, ignore_errors=True)
    return rows, total(rows), agree, len(words), lexicon.PAIRS


def main() -> int:
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")
        except Exception:
            pass
    ap = argparse.ArgumentParser(description="قياسُ تعليم الكلمات المشكوك فيها: القاموس وحده، والقاموس مع السياق")
    ap.add_argument("--save", metavar="اسم", help="يحفظ النتيجة في tests/results/marks-اسم.json")
    ap.add_argument("--sim", action="store_true", help="محاكاةٌ على نصّ القرآن بدل صفحات المرجع")
    ap.add_argument("--seed", type=int, default=0, help="بذرةُ المحاكاة (0)")
    ap.add_argument("--tail", action="store_true", help="في المحاكاة: الاختبارُ آخرُ عُشر المصحف (أسلوبٌ يخالف الباقي) لا آياتٌ متفرّقة")
    a = ap.parse_args()
    if a.sim:
        rows, t, agree, nwords, _ = simulate(a.seed, a.tail)
        print("محاكاة (لا قياسٌ حقيقيّ): قاموسٌ من %d كلمة من ٩٠٪ من الآيات، واختبارٌ على %s: %d كلمة، أُدخل خطأُ نقطٍ في %d منها."
              % (nwords, "آخر عُشر المصحف" if a.tail else "عُشر الآيات متفرّقةً", t["words"], t["wrong"]))
        table(t)
        print("فحصُ المقابلة: الأخطاءُ التي وجدتها المقابلةُ هي المُدخلة بعينها — %s" % ("نعم" if agree else "لا (عيبٌ في القياس)"))
        if not agree:
            return 1
    else:
        got = gold_pages()
        if isinstance(got, int):
            return got
        rows, t = got
    if a.save:
        RESULTS.mkdir(exist_ok=True)
        out = RESULTS / ("marks-%s.json" % a.save)
        pages = [{k: v for k, v in r.items() if k != "wrong_flags" and (k != "context" or not a.sim)} for r in rows]
        out.write_text(json.dumps({"date": time.strftime("%Y-%m-%d %H:%M"), "methods": METHODS, "sim": a.sim,
                                   "total": t, "pages": [] if a.sim else pages}, ensure_ascii=False, indent=1), encoding="utf-8")
        print("حُفظ: tests/results/%s" % out.name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
