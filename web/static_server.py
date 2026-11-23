"""Yayın klasörünü (web/dist) Cloudflare'deki gibi _headers başlıklarıyla sunar.

    python web/static_server.py [port]

Yalnız yerel deneme ve uçtan uca test içindir (e2e_test.py --pyodide). Yayında
Cloudflare aynı _headers dosyasını kendisi uygular.
"""
from __future__ import annotations

import fnmatch
import http.server
import os
import sys

DIST = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dist")


def kurallar() -> list[tuple[str, list[tuple[str, str]]]]:
    sonuc: list[tuple[str, list[tuple[str, str]]]] = []
    yol = os.path.join(DIST, "_headers")
    if not os.path.exists(yol):
        return sonuc
    for satir in open(yol, encoding="utf-8"):
        if not satir.strip() or satir.lstrip().startswith("#"):
            continue
        if not satir[0].isspace():
            sonuc.append((satir.strip(), []))
        elif sonuc and ":" in satir:
            ad, deger = satir.strip().split(":", 1)
            sonuc[-1][1].append((ad.strip(), deger.strip()))
    return sonuc


class Isleyici(http.server.SimpleHTTPRequestHandler):
    extensions_map = {**http.server.SimpleHTTPRequestHandler.extensions_map,
                      ".wasm": "application/wasm", ".mjs": "text/javascript", ".js": "text/javascript"}

    def __init__(self, *a, **k):
        super().__init__(*a, directory=DIST, **k)

    def end_headers(self):
        yol = self.path.split("?", 1)[0]
        for desen, basliklar in KURALLAR:
            if fnmatch.fnmatchcase(yol, desen):
                for ad, deger in basliklar:
                    self.send_header(ad, deger)
        super().end_headers()

    def log_message(self, *a):
        pass


KURALLAR = kurallar()

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    print(f"http://127.0.0.1:{port}/")
    class Sunucu(http.server.ThreadingHTTPServer):
        def handle_error(self, request, client_address):  # tarayıcının yarıda kestiği bağlantılar
            pass
    Sunucu(("127.0.0.1", port), Isleyici).serve_forever()
