"""Yhteiset asetukset ja apufunktiot Näsijärven aineistoputkelle.

Kaikki koordinaatit ovat oletuksena EPSG:3067 (ETRS-TM35FIN), ellei toisin mainita.
"""
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

JUURI = Path(__file__).resolve().parent
TYO = JUURI / "tyo"
RAAKA = TYO / "raaka"
ULOS = JUURI / "ulos"

PAITULI = "https://mirrors.nic.funet.fi/index/geodata/"
VAYLA_WFS = "https://avoinapi.vaylapilvi.fi/vaylatiedot/ows"
TRAFICOM_WFS = "https://julkinen.traficom.fi/inspirepalvelu/rajoitettu/wfs"
KAYTTAJA = "reittikartta-aineisto/1.0 (avoimen datan tietoputki; yhteys: reittikartta-aineisto GitHub-repo)"

# Laaja hakulaatikko, josta Näsijärven vesialue etsitään. Lopullinen rajaus tehdään vesialueesta.
HAKUBBOX = (295000, 6810000, 350000, 6890000)
# Alueen ulkoraja: tämän sisään jäävä osa vesialueesta ja sen 3 km maapuskurista otetaan mukaan.
AOI_RAJAUS = (298000, 6812000, 347500, 6880000)
LIITOSETAISYYS_M = 300     # enintään näin kaukana pääaltaasta olevat vesialueet liitetään mukaan (kanavat)
# Määrittelyn alkuperäinen arvio rajauslaatikosta. Käytetään vertailuna raportissa.
MAARITTELY_BBOX = (300000, 6815000, 345000, 6880000)
# Piste Mustalahden edustalla, josta Näsijärven vesialue tunnistetaan (EPSG:4326 lon, lat).
SIEMENPISTE_WGS84 = (23.7500, 61.5000)
RANTAPUSKURI_M = 3000      # maapuskuri rannasta
RANTAVYOHYKE_M = 500       # 2 m korkeusmallin vyöhyke rannan molemmin puolin
VESIPUSKURI_YHDISTYS_M = 0.5

# Maaston korkeustiilet
TERRAIN_TILE_PX = 256
TERRAIN_MINZ = 8
TERRAIN_MAXZ = 14
PUUSTO_MINZ = 10
PUUSTO_MAXZ = 14
VEKTORI_MINZ = 8
VEKTORI_MAXZ = 16

# Lähdemerkinnät sanatarkasti (luettu ehtotiedostoista, ks. lataa.py ja aineisto.json)
LISENSSI_CC_BY = "https://creativecommons.org/licenses/by/4.0/"


def nyt_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def loki(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def aja(cmd, **kw):
    """Aja ulkoinen komento ja nosta virhe, jos se epäonnistuu."""
    loki("$", " ".join(str(c) for c in cmd)[:300])
    kw.setdefault("check", True)
    return subprocess.run([str(c) for c in cmd], **kw)


def hae(url, kohde, yrityksia=5, kerro=True):
    """Lataa tiedosto. Ohittaa lataamisen, jos kohde on jo olemassa samankokoisena.

    Palauttaa (tavuja, sekunteja, ladattiinko).
    """
    kohde = Path(kohde)
    kohde.parent.mkdir(parents=True, exist_ok=True)
    pyynto = urllib.request.Request(url, headers={"User-Agent": KAYTTAJA})
    viimeinen = None
    for yritys in range(yrityksia):
        try:
            alku = time.time()
            with urllib.request.urlopen(pyynto, timeout=120) as r:
                pituus = r.headers.get("Content-Length")
                if kohde.exists() and pituus and kohde.stat().st_size == int(pituus):
                    return kohde.stat().st_size, 0.0, False
                tmp = kohde.with_suffix(kohde.suffix + ".osa")
                n = 0
                with open(tmp, "wb") as f:
                    while True:
                        osa = r.read(1 << 20)
                        if not osa:
                            break
                        f.write(osa)
                        n += len(osa)
                if pituus and n != int(pituus):
                    raise IOError("Tiedosto katkesi: %d / %s tavua" % (n, pituus))
                os.replace(tmp, kohde)
                dt = time.time() - alku
                if kerro:
                    loki("haettu %s (%.1f Mt, %.1f s)" % (url.split("/")[-1][:60], n / 1e6, dt))
                return n, dt, True
        except Exception as e:  # noqa: BLE001
            viimeinen = e
            time.sleep(2 + 3 * yritys)
    raise RuntimeError("Lataus epäonnistui: %s (%s)" % (url, viimeinen))


def hae_teksti(url, yrityksia=5):
    pyynto = urllib.request.Request(url, headers={"User-Agent": KAYTTAJA})
    viimeinen = None
    for yritys in range(yrityksia):
        try:
            with urllib.request.urlopen(pyynto, timeout=180) as r:
                return r.read()
        except Exception as e:  # noqa: BLE001
            viimeinen = e
            time.sleep(2 + 3 * yritys)
    raise RuntimeError("Haku epäonnistui: %s (%s)" % (url, viimeinen))


def lue_json(polku, oletus=None):
    try:
        with open(polku, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return oletus


def kirjoita_json(polku, data, kompakti=False):
    """kompakti=True kirjoittaa ilman sisennyksiä ja välilyöntejä (selaimen ladattavat hakemistot)."""
    Path(polku).parent.mkdir(parents=True, exist_ok=True)
    with open(polku, "w", encoding="utf-8") as f:
        if kompakti:
            json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
        else:
            json.dump(data, f, ensure_ascii=False, indent=1)


def tuore(polku):
    """Onko tiedosto olemassa ja ei-tyhjä."""
    p = Path(polku)
    return p.exists() and p.stat().st_size > 0


def kansio_koko(polku):
    kok = 0
    for p in Path(polku).rglob("*"):
        if p.is_file():
            kok += p.stat().st_size
    return kok


def siivoa(polku):
    shutil.rmtree(polku, ignore_errors=True)
