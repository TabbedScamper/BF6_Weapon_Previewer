"""Local dev server: serves the site plus /models/ mapped onto the GLB
staging drive (default A:\\bf6weapons\\models, override with BF6WPN_MODELS).

Usage: python serve.py [port]
"""
import os
import sys
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler

SITE = os.path.dirname(os.path.abspath(__file__))
MODELS = os.environ.get("BF6WPN_MODELS", r"A:\bf6weapons\models")
SKINS = os.environ.get("BF6WPN_SKINS", r"A:\bf6weapons\skins")


class H(SimpleHTTPRequestHandler):
    def translate_path(self, path):
        p = path.split("?", 1)[0].split("#", 1)[0]
        for prefix, root in (("/models/", MODELS), ("/skins/", SKINS),
                             ("/refs/", r"A:\bf6weapons\refs")):
            if p.startswith(prefix):
                rel = os.path.normpath(p[len(prefix):]).lstrip("\\/")
                full = os.path.join(root, rel)
                if os.path.commonpath([os.path.abspath(full), root]) == root:
                    return full
                return root
        return super().translate_path(path)

    def end_headers(self):
        if self.path.startswith(("/models/", "/skins/")):
            # no-cache while we iterate on conversions — a long max-age here
            # serves stale/deleted models across rebuilds
            self.send_header("Cache-Control", "no-cache")
        else:
            self.send_header("Cache-Control", "no-cache")
        super().end_headers()


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8087
    os.chdir(SITE)
    print("serving %s  (+ /models/ -> %s)  on http://localhost:%d" % (SITE, MODELS, port))
    ThreadingHTTPServer(("127.0.0.1", port), H).serve_forever()
