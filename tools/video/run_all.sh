#!/usr/bin/env bash
# يصنع الفيديو التعريفيّ من البداية: المكتبةُ التجريبيّة، ثمّ التسجيل، ثمّ الجمع.
# الاستعمال: run_all.sh <بايثون_فيه_pymupdf> <مجلّد_الخطوط> <مجلّد_العمل> <الناتج.mp4> <مجلّد_نصوص> [مجلّد_نصوص ...]
set -euo pipefail
PY=$1; FONTS=$2; WORK=$3; OUT=$4; shift 4
HERE=$(cd "$(dirname "$0")" && pwd); APP=$HERE/../../app; PORT=8779
"$PY" "$HERE/prepare.py" "$FONTS" "$WORK" "$@"
"$PY" "$HERE/make_chapter.py" "$WORK/فصل تجريبي.docx"
(cd "$APP" && BUGHYA_HOME="$WORK/home" exec "$PY" "$HERE/serve.py" $PORT) & SRV=$!
trap 'kill $SRV 2>/dev/null' EXIT
sleep 1.5
rm -rf "$WORK/frames"
node "$HERE/record.js" "$WORK/frames" "$WORK/فصل تجريبي.docx" $PORT
"$PY" "$HERE/build_video.py" "$WORK/frames" "$OUT"
