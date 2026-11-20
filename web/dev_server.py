"""Yalnız geliştirme ve test için yerel sunucu (yayına konmaz).

Aynı sfweb.py köprüsünü normal Python ile çalıştırır; arayüz `?dev=1` ile
açılınca Pyodide yerine bu sunucuya komut gönderir. Böylece arayüz ve köprü,
internetsiz bir ortamda gerçek tarayıcıda uçtan uca test edilebilir.

Kullanım:  python web/dev_server.py [port]   →  http://127.0.0.1:8765/?dev=1
Yalnız 127.0.0.1'i dinler.
"""

from __future__ import annotations

import json
import os
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
os.environ.setdefault("SFWEB_DIR", os.path.join(os.path.dirname(HERE), ".sfweb_dev"))

import sfweb  # noqa: E402

UPLOAD = os.path.join(os.environ["SFWEB_DIR"], "upload")


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=HERE, **kw)

    def log_message(self, *a):  # sessiz
        pass

    def _send(self, body: bytes, ctype="application/json; charset=utf-8", code=200):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        u = urlparse(self.path)
        n = int(self.headers.get("Content-Length") or 0)
        data = self.rfile.read(n)
        if u.path == "/api":
            req = json.loads(data or b"{}")
            out = sfweb.dispatch(req["name"], json.dumps(req.get("args")))
            return self._send(out.encode("utf-8"))
        if u.path == "/put":
            name = os.path.basename(parse_qs(u.query).get("name", ["dosya"])[0])
            os.makedirs(UPLOAD, exist_ok=True)
            path = os.path.join(UPLOAD, name)
            with open(path, "wb") as f:
                f.write(data)
            return self._send(json.dumps({"path": path}).encode())
        self._send(b"{}", code=404)

    def do_GET(self):
        u = urlparse(self.path)
        if u.path == "/get":
            path = os.path.abspath(parse_qs(u.query)["path"][0])
            if not path.startswith(os.path.abspath(os.environ["SFWEB_DIR"])):
                return self._send(b"", code=403)
            with open(path, "rb") as f:
                return self._send(f.read(), "application/octet-stream")
        return super().do_GET()


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"http://127.0.0.1:{port}/?dev=1")
    srv.serve_forever()


if __name__ == "__main__":
    main()
