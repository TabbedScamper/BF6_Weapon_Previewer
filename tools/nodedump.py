"""Dump runtime node world-positions for a build. Usage like shot.py."""
import json
import sys

from playwright.sync_api import sync_playwright

wid = sys.argv[1]
sets = [a for a in sys.argv[2:] if "=" in a]


def main():
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        pg = b.new_page()
        pg.on("console", lambda m: print("CON[%s] %s" % (m.type, m.text[:220]))
              if m.type in ("error", "warning") else None)
        pg.on("pageerror", lambda e: print("PAGEERR", str(e)[:300]))
        pg.goto("http://localhost:8087/#" + wid.replace("/", "%2F"))
        pg.wait_for_timeout(2500)
        for kv in sets:
            k, v = kv.split("=", 1)
            fn = "setCharm" if k == "charm" else "setBuild"
            pg.evaluate("([k,v])=>window.__app.setBuild(k,v)" if k != "charm"
                        else "(v)=>window.__app.setCharm(v)",
                        [k, v] if k != "charm" else v)
        stable = 0
        for _ in range(400):
            pg.wait_for_timeout(300)
            busy = pg.evaluate("window.__app.busy()")
            n = pg.evaluate("window.__app.loaded()")
            if busy == 0 and n > 0:
                stable += 1
                if stable >= 2:
                    break
            else:
                stable = 0
        info = pg.evaluate("window.__app.nodes()")
        for e in info:
            print("%-8s %-58s vis=%s at %s" % (e["id"], e["node"][-58:], e["vis"], e["at"]))
        b.close()


if __name__ == "__main__":
    main()
