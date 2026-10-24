#!/usr/bin/env python3
"""Ottaa testi.html:stä kuvakaappaukset hakemistoon shots/ (Playwright + Chromium).

Ajo:  python3 kuvakaappaukset.py
Käynnistää palvele.py:n väliaikaisesti, joten ulos/-hakemiston pitää olla rakennettu.
"""
import json
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

JUURI = Path(__file__).resolve().parent
PORTTI = 8137
KUVAT = [
    ("mustalahti", "lat=61.5052&lon=23.7525&z=16", "Mustalahti, Tampere"),
    ("siilinkari", "lat=61.5185&lon=23.7568&z=15", "Siilinkari"),
    ("muroleen_kanava", "lat=61.8553&lon=23.9068&z=16", "Muroleen kanava"),
    ("tampere_keskusta_z15", "lat=61.4978&lon=23.7610&z=15", "Tampereen keskusta, zoom 15"),
    ("osoite_laiturikatu_8", "lat=61.5053&lon=23.7463&z=18", "Laiturikatu 8, Mustalahti"),
    ("puusto_muroleen_suunta", "lat=61.83&lon=23.89&z=13&paalle=puusto", "Puustotaso"),
]


def main():
    (JUURI / "shots").mkdir(exist_ok=True)
    palvelin = subprocess.Popen([sys.executable, str(JUURI / "palvele.py"), str(PORTTI)])
    time.sleep(1.5)
    try:
        with sync_playwright() as p:
            selain = p.chromium.launch()
            sivu = selain.new_page(viewport={"width": 1100, "height": 760}, device_scale_factor=1)
            virheet = []
            sivu.on("console", lambda m: virheet.append(m.text) if m.type == "error" else None)
            sivu.on("pageerror", lambda e: virheet.append(str(e)))
            for nimi, kysely, _ in KUVAT:
                sivu.goto("http://127.0.0.1:%d/testi.html?%s" % (PORTTI, kysely))
                sivu.wait_for_function("window.__testi && window.__testi.valmis()", timeout=60000)
                sivu.wait_for_timeout(1500)
                sivu.screenshot(path=str(JUURI / "shots" / (nimi + ".png")))
                print("kuva", nimi)
            # Yksi puhelinnäkymä: 390 x 844 px, zoom 14, Tampereen keskusta
            puh = selain.new_page(viewport={"width": 390, "height": 844}, device_scale_factor=2)
            siirretty = []
            puh.on("response", lambda r: siirretty.append(r))
            puh.goto("http://127.0.0.1:%d/testi.html?lat=61.4990&lon=23.7600&z=14" % PORTTI)
            puh.wait_for_function("window.__testi && window.__testi.valmis()", timeout=60000)
            puh.wait_for_timeout(1500)
            puh.screenshot(path=str(JUURI / "shots" / "puhelin_390x844_z14.png"))
            print("kuva puhelin_390x844_z14")
            yht = {}
            for r in siirretty:
                try:
                    n = len(r.body())
                except Exception:  # noqa: BLE001
                    continue
                nimi = r.url.split("/")[-1].split("?")[0]
                yht[nimi] = yht.get(nimi, 0) + n
            yht["_yhteensa"] = sum(yht.values())
            (JUURI / "shots" / "puhelin_siirto_tavua.json").write_text(json.dumps(yht, indent=1))
            print("puhelinnäkymän siirto tavuina:", yht)
            print("konsolivirheet:", virheet[:10])
            selain.close()
    finally:
        palvelin.terminate()


if __name__ == "__main__":
    main()
