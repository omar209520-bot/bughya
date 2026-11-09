"""القراءةُ الآليّة للصفحات المصوَّرة، بأداة النظام نفسه بلا تنزيل محرّكٍ ولا مفتاح:
    الماك     أداةُ قراءة الحروف في نظام الماك (عبر حزمة PyObjC)، بإعدادات «سَبْر الوارث» المقيسة:
              الدقيقةُ لا السريعة (السريعةُ تُخرج صفرًا من العربيّة)، وبلا تصحيحٍ لغويّ (يحفظ الأعلام)، ولا تُسقط الأسطرَ الصغيرة.
    ويندوز   محرّكُ القراءة في ويندوز (عبر حزم winrt)، ويلزمه أن تكون العربيّةُ مضافةً بميزة القراءة الضوئيّة.
             **لم يُختبر على جهاز ويندوز.**

engine() يعيد كائنًا فيه ok وreason وname، وrecognize(png) ← [{text, conf, x, y, w, h}] بمواضع نسبيّةٍ من أعلى اليسار.
"""
import sys

_ENGINE = None


class _None:
    ok, name, word_order_check, max_side = False, "لا شيء", False, None

    def __init__(self, reason: str):
        self.reason = reason

    def recognize(self, png: bytes):
        raise RuntimeError(self.reason)


class _Mac:
    name, word_order_check, max_side = "أداةُ قراءة الحروف في نظام الماك", False, None

    def __init__(self):
        self.ok, self.reason = False, ""
        try:
            import objc  # noqa: F401
            import Vision
            from Foundation import NSData  # noqa: F401
        except ImportError:
            self.reason = "حزمةُ القراءة الآليّة غير منصّبة (أعد التنصيب)."
            return
        try:
            req = Vision.VNRecognizeTextRequest.alloc().init()
            req.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
            langs, _err = req.supportedRecognitionLanguagesAndReturnError_(None)
            langs = [str(x) for x in (langs or [])]
        except Exception as e:
            self.reason = "تعذّر تشغيلُ أداة القراءة في النظام: %s" % e
            return
        self.langs = [x for x in ("ar-SA", "ar") if x in langs]
        if not self.langs:
            self.reason = ("نظامُ الماك في هذا الجهاز لا يقرأ العربيّة آليًّا (يلزمه إصدارٌ أحدث من النظام). "
                           "الكتبُ التي فيها نصٌّ تُقرأ، والمصوَّرةُ لا.")
            return
        self.langs += [x for x in ("en-US",) if x in langs]
        self.ok = True

    def recognize(self, png: bytes):
        import objc
        import Vision
        from Foundation import NSData
        with objc.autorelease_pool():
            data = NSData.dataWithBytes_length_(png, len(png))
            handler = Vision.VNImageRequestHandler.alloc().initWithData_options_(data, None)   # قاموسٌ فارغ يُرفض هنا
            req = Vision.VNRecognizeTextRequest.alloc().init()
            req.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
            req.setRecognitionLanguages_(self.langs)
            req.setUsesLanguageCorrection_(False)
            req.setMinimumTextHeight_(0.0)
            ok, err = handler.performRequests_error_([req], None)
            if not ok:
                raise RuntimeError(str(err))
            out = []
            for obs in req.results() or []:
                cands = obs.topCandidates_(1)
                if not cands:
                    continue
                c = cands[0]
                bb = obs.boundingBox()
                x, y, w, h = bb.origin.x, bb.origin.y, bb.size.width, bb.size.height
                out.append({"text": str(c.string()), "conf": float(c.confidence()),
                            "x": float(x), "y": float(1.0 - y - h), "w": float(w), "h": float(h)})
            return out


class _Win:
    name, word_order_check = "محرّكُ القراءة في ويندوز", True

    def __init__(self):
        self.ok, self.reason = False, ""
        try:
            from winrt.windows.media.ocr import OcrEngine
        except ImportError:
            self.reason = "حزمةُ القراءة الآليّة في ويندوز غير منصّبة (أعد التنصيب)."
            return
        try:
            tags = [str(l.language_tag) for l in OcrEngine.available_recognizer_languages]
        except Exception as e:
            self.reason = "تعذّر تشغيلُ محرّك القراءة في ويندوز: %s" % e
            return
        arabic = [t for t in tags if t.lower().startswith("ar")]
        if not arabic:
            self.reason = ("لغةُ القراءة الآليّة العربيّة غير مضافة في ويندوز. أضفها من: الإعدادات ← الوقت واللغة ← اللغة والمنطقة "
                           "← إضافة لغة ← العربيّة (مع ميزة «التعرّف الضوئي على الحروف»)، ثمّ اطلب «حدّث المكتبة». "
                           "الكتبُ التي فيها نصٌّ تُقرأ، والمصوَّرةُ لا.")
            return
        self.tag = arabic[0]
        try:        # أكبرُ طولٍ للصورة يقبله المحرّك؛ وما زاد عليه يُرفض، فتُصغَّر الصورةُ إليه
            self.max_side = int(OcrEngine.max_image_dimension) or None
        except Exception:
            self.max_side = 2600
        self.ok = True

    def recognize(self, png: bytes):
        import asyncio
        return asyncio.run(self._recognize(png))

    async def _recognize(self, png: bytes):
        from winrt.windows.globalization import Language
        from winrt.windows.graphics.imaging import BitmapDecoder
        from winrt.windows.media.ocr import OcrEngine
        from winrt.windows.storage.streams import DataWriter, InMemoryRandomAccessStream
        stream = InMemoryRandomAccessStream()
        writer = DataWriter(stream)
        writer.write_bytes(bytes(png))
        await writer.store_async()
        await writer.flush_async()
        writer.detach_stream()
        stream.seek(0)
        decoder = await BitmapDecoder.create_async(stream)
        bmp = await decoder.get_software_bitmap_async()
        W, H = float(bmp.pixel_width) or 1.0, float(bmp.pixel_height) or 1.0
        engine = OcrEngine.try_create_from_language(Language(self.tag))
        if engine is None:
            raise RuntimeError("تعذّر تشغيلُ محرّك القراءة العربيّة")
        res = await engine.recognize_async(bmp)
        out = []
        for line in res.lines:
            words = list(line.words)
            rects = [w.bounding_rect for w in words]
            if not rects:
                continue
            # المحرّكُ يرتّب كلماتِ السطر العربيّ من اليسار (قيس على جهاز ويندوز)، فتُرتَّب بمواضعها من اليمين
            text = str(line.text)
            if any("؀" <= ch <= "ۿ" for ch in text):
                text = " ".join(str(w.text) for w in sorted(words, key=lambda w: -(w.bounding_rect.x
                                                                                 + w.bounding_rect.width)))
            x0 = min(r.x for r in rects)
            y0 = min(r.y for r in rects)
            x1 = max(r.x + r.width for r in rects)
            y1 = max(r.y + r.height for r in rects)
            ws = [{"t": str(w.text), "x": w.bounding_rect.x / W, "y": w.bounding_rect.y / H,
                   "w": w.bounding_rect.width / W, "h": w.bounding_rect.height / H}
                  for w in sorted(words, key=lambda w: -(w.bounding_rect.x + w.bounding_rect.width))]
            out.append({"text": text, "conf": None, "words": ws,
                        "x": x0 / W, "y": y0 / H, "w": (x1 - x0) / W, "h": (y1 - y0) / H})
        return out


def engine():
    global _ENGINE
    if _ENGINE is None:
        if sys.platform == "darwin":
            _ENGINE = _Mac()
        elif sys.platform == "win32":
            _ENGINE = _Win()
        else:
            _ENGINE = _None("القراءةُ الآليّة متاحةٌ في الماك وويندوز وحدهما.")
        if not _ENGINE.ok and not isinstance(_ENGINE, _None):
            reason = _ENGINE.reason
            _ENGINE = _None(reason)
    return _ENGINE
