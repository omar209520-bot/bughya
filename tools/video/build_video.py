"""يجمع إطاراتِ record.js فيديو MP4: ‏1920×1080، ‏30 إطارًا في الثانية، H.264، وصوتُ نقرةٍ قصيرة عند كلّ نقرة (AAC).
لا موسيقى ولا صوتَ غيرَ النقرات. صوتُ النقرة مصنوعٌ هنا حسابيًّا (لا ملفَّ صوتٍ من مصدرٍ خارجيّ).
الاستعمال: python build_video.py <مجلّد_الإطارات> <الناتج.mp4>
"""
import json
import math
import pathlib
import random
import struct
import subprocess
import sys
import wave

FR = pathlib.Path(sys.argv[1])
OUT = pathlib.Path(sys.argv[2])
tl = json.loads((FR / "timeline.json").read_text())
frames = tl["frames"]
start = frames[0]["t"]
end = max(tl["t1"], frames[-1]["t"] + 1.0)
dur = end - start

# ── الصورة: كلُّ إطارٍ يبقى حتّى الإطار التالي (ملفُّ concat بمدد)، ثمّ تثبيتُ ٣٠ إطارًا في الثانية
lst = FR / "frames.txt"
with lst.open("w") as f:
    for a, b in zip(frames, frames[1:] + [{"name": frames[-1]["name"], "t": end}]):
        f.write(f"file '{a['name']}'\nduration {max(b['t'] - a['t'], 0.001):.4f}\n")
    f.write(f"file '{frames[-1]['name']}'\n")

# ── الصوت: نقرةٌ قصيرة (نحو ٤٠ مللي ثانية) عند كلّ نقرة، والباقي صمت
SR = 48000
n = int(dur * SR) + SR
buf = [0.0] * n
rnd = random.Random(7)
click = []
for i in range(int(0.045 * SR)):
    t = i / SR
    v = (0.55 * math.sin(2 * math.pi * 3100 * t) * math.exp(-t * 160)
         + 0.35 * math.sin(2 * math.pi * 1250 * t) * math.exp(-t * 110)
         + 0.30 * (rnd.random() * 2 - 1) * math.exp(-t * 420))
    click.append(v)
for c in tl["clicks"]:
    k = int((c - start) * SR)
    for i, v in enumerate(click):
        if 0 <= k + i < n:
            buf[k + i] += v * 0.8
wav = FR / "clicks.wav"
with wave.open(str(wav), "wb") as w:
    w.setnchannels(1)
    w.setsampwidth(2)
    w.setframerate(SR)
    w.writeframes(b"".join(struct.pack("<h", int(max(-1, min(1, x)) * 32000)) for x in buf))

subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                "-f", "concat", "-safe", "0", "-i", str(lst), "-i", str(wav),
                "-vf", "scale=1920:1080:flags=lanczos,fps=30,format=yuv420p",
                "-c:v", "libx264", "-preset", "slow", "-crf", "20", "-tune", "stillimage", "-r", "30",
                "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2",
                "-t", f"{dur:.3f}", "-movflags", "+faststart", str(OUT)], check=True)
print(f"{OUT} · {dur:.1f} ث · {len(tl['clicks'])} نقرة · {len(frames)} إطارًا ملتقطًا")
