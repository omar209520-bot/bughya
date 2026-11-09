"""يشغّل واجهة «بُغية» على لينكس للتسجيل (دون نافذة ويندوز). الاستعمال: BUGHYA_HOME=... python serve.py [المنفذ]"""
import pathlib
import sys
from http.server import ThreadingHTTPServer

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "app"))
import wajiha  # noqa: E402

wajiha.PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8777
ThreadingHTTPServer(("127.0.0.1", wajiha.PORT), wajiha.Handler).serve_forever()
