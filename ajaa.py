#!/usr/bin/python3
"""Koko putki yhdellä komennolla: lataa -> rakenna -> tarkista. Kirjoittaa ajoajat tiedostoon ulos/ajoaika.json.

Ajo:  python3 ajaa.py                koko ajo
      python3 ajaa.py --puhdas       poistaa ensin tyo/ ja ulos/ (puhdas ajo, kuten GitHub Actionsissa)
      python3 ajaa.py --ei-lataa     ohittaa latausvaiheen (käyttää olemassa olevaa tyo/-hakemistoa)
"""
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

JUURI = Path(__file__).resolve().parent


def vaihe(nimi, komento):
    print("\n=== %s ===" % nimi, flush=True)
    alku = time.time()
    r = subprocess.run([sys.executable] + komento, cwd=JUURI)
    dt = time.time() - alku
    print("=== %s: %.0f s, paluukoodi %d ===" % (nimi, dt, r.returncode), flush=True)
    return r.returncode, dt


def main(argv):
    alku = time.time()
    if "--puhdas" in argv:
        for h in ("tyo", "ulos"):
            shutil.rmtree(JUURI / h, ignore_errors=True)
    ajat = {}
    if "--ei-lataa" not in argv:
        rc, ajat["lataa_s"] = vaihe("lataa", ["lataa.py"])
        if rc:
            print("Lataus epäonnistui, keskeytetään.")
            return rc
    rc, ajat["rakenna_s"] = vaihe("rakenna", ["rakenna.py"])
    if rc:
        return rc
    rc, ajat["tarkista_s"] = vaihe("tarkista", ["tarkista.py"])
    ajat["yhteensa_s"] = round(time.time() - alku, 1)
    ajat["tyo_hakemisto_mt"] = round(sum(p.stat().st_size for p in (JUURI / "tyo").rglob("*") if p.is_file()) / 1e6)
    ajat["ulos_hakemisto_mt"] = round(sum(p.stat().st_size for p in (JUURI / "ulos").rglob("*") if p.is_file()) / 1e6, 1)
    (JUURI / "ulos" / "ajoaika.json").write_text(json.dumps(ajat, indent=1), encoding="utf-8")
    print(json.dumps(ajat, indent=1))
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
