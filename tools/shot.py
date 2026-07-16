"""Headless screenshot probe for the local previewer.
Usage: shot.py <weaponId> <out.png> [slot=tok ...] [charm=<id>] [gadget]
Drives the page state directly (build/charm globals + apply) then snaps
the canvas after models load.
"""
import sys
import time

from playwright.sync_api import sync_playwright

wid = sys.argv[1]
out = sys.argv[2]
sets = [a for a in sys.argv[3:] if "=" in a]
BASE = "http://localhost:8087/"


def main():
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        pg = b.new_page(viewport={"width": 2400, "height": 1400},
                        device_scale_factor=1)
        pg.goto(BASE + "#" + wid.replace("/", "%2F"))
        pg.wait_for_timeout(2500)
        for kv in sets:
            k, v = kv.split("=", 1)
            if k == "charm":
                pg.evaluate("(v)=>window.__app.setCharm(v)", v)
            elif k == "camo":
                pg.evaluate("(v)=>window.__app.setCamo(v)", v)
            else:
                pg.evaluate("([k,v])=>window.__app.setBuild(k,v)", [k, v])
        # wait for pending loads to settle (no GLB requests in flight)
        stable = 0
        for _ in range(400):
            pg.wait_for_timeout(300)
            busy = pg.evaluate("window.__app ? window.__app.busy() : 1")
            n = pg.evaluate("window.__app ? window.__app.loaded() : 0")
            if busy == 0 and n > 0:
                stable += 1
                if stable >= 2:
                    break
            else:
                stable = 0
        pg.evaluate("window.__app && window.__app.frame()")
        pg.wait_for_timeout(400)
        pg.screenshot(path=out)
        title = pg.evaluate("document.getElementById('np-name')?.textContent||''")
        print("shot:", out, "| nameplate:", title)
        b.close()


if __name__ == "__main__":
    main()
