#!/usr/bin/env python3
"""Pieni paikallinen palvelin ulos-hakemistolle, tukee HTTP Range -pyyntöjä (PMTiles tarvitsee niitä).

Ajo:  python3 palvele.py [portti]   ->  http://localhost:8000/testi.html
"""
import os
import re
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

JUURI = Path(__file__).resolve().parent / "ulos"


class Kasittelija(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(JUURI), **kw)

    def log_message(self, *a):
        pass

    def end_headers(self):
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Access-Control-Allow-Origin", "*")
        super().end_headers()

    def do_GET(self):
        r = self.headers.get("Range")
        polku = self.translate_path(self.path.split("?")[0])
        if not r or not os.path.isfile(polku):
            return super().do_GET()
        m = re.match(r"bytes=(\d*)-(\d*)$", r)
        koko = os.path.getsize(polku)
        if not m:
            return super().do_GET()
        a, b = m.groups()
        if a == "":
            alku, loppu = max(0, koko - int(b)), koko - 1
        else:
            alku, loppu = int(a), int(b) if b else koko - 1
        loppu = min(loppu, koko - 1)
        if alku > loppu:
            self.send_response(416)
            self.send_header("Content-Range", "bytes */%d" % koko)
            self.end_headers()
            return
        self.send_response(206)
        self.send_header("Content-Type", self.guess_type(polku))
        self.send_header("Content-Range", "bytes %d-%d/%d" % (alku, loppu, koko))
        self.send_header("Content-Length", str(loppu - alku + 1))
        self.end_headers()
        with open(polku, "rb") as f:
            f.seek(alku)
            n = loppu - alku + 1
            while n > 0:
                osa = f.read(min(1 << 20, n))
                if not osa:
                    break
                try:
                    self.wfile.write(osa)
                except (BrokenPipeError, ConnectionResetError):
                    return
                n -= len(osa)


if __name__ == "__main__":
    portti = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    ThreadingHTTPServer(("127.0.0.1", portti), Kasittelija).serve_forever()
