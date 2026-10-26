#!/usr/bin/env python3
"""Laserkeilausmoduuli (vaihe 1b): pintamalli, rakennuskorkeudet ja maamerkkien mitat rantavyöhykkeeltä.

Käyttö:
  python3 laser.py                koko tuotanto (kaikki vaiheet, jatkaa siitä mihin jäätiin)
  python3 laser.py --puhdas       poistaa tämän moduulin välitulokset (ei ladattuja laserruutuja) ja ajaa kaiken
  python3 laser.py --puhdas-lataus  poistaa myös ladatut laserruudut ja ajaa kaiken (täysi ajo tyhjästä)
  python3 laser.py <vaihe> ...    vain nimetyt vaiheet (lisäksi vaihe nakopiste hakee siluettikuvan katselupisteen)

Vaiheet järjestyksessä:
  alue         rantavyöhyke (vesialueen reuna 1 km molemmin puolin, rajattuna laatikkoon)
  ruudut       alueen leikkaavat laserruudut Paitulin indeksistä ja hakemistolistauksista
  lataa        laserruutujen lataus (jatkuu keskeytyksestä)
  korkeus      DEM 1 m ruudukkoon (DEM 2 m, puuttuvissa DEM 10 m)
  pisteet      pistepilven luku, kohinasuodatus ja tiivis välitallennus
  pinta        pintamalli 1 m (pinta_1m.tif)
  rakennukset  rakennuskorkeudet (rakennuskorkeudet.json)
  maamerkit    maamerkkien mitat pistepilvestä (maamerkit.json)
  tiilet       Terrain-RGB-tiilet (pinta.pmtiles)
  kuvat        tarkistuskuvat (varjostus, lähikuvat, siluetti vedestä)
  tarkista     hyväksymiskriteerit lukuina (tarkistus_1b.json)
  kuvaus       aineisto_1b.json

Asetukset ovat heti tämän kommentin jälkeen. Moduuli ei muuta rakenna.py- eikä lataa.py-tiedostoja. Vaiheen 1
välitulokset (aoi.gpkg, dem2.vrt, dem10.tif, rajattu.gpkg) luetaan hakemistosta tyo/, tai ympäristömuuttujan
LASER_VAIHE1_TYO osoittamasta hakemistosta.

Ajetaan Pythonilla, jossa on GDAL-sidokset (Ubuntu 24.04:n python3). Jos ne puuttuvat oletustulkista ja
/usr/bin/python3.12 on olemassa, moduuli käynnistää itsensä uudelleen sillä.
"""
import os
import sys

try:
    from osgeo import gdal, ogr, osr  # noqa: F401
except ImportError:  # pragma: no cover
    _vara = "/usr/bin/python3.12"
    if os.path.exists(_vara) and not os.environ.get("LASER_UUDELLEENKAYNNISTYS"):
        os.environ["LASER_UUDELLEENKAYNNISTYS"] = "1"
        os.execv(_vara, [_vara] + sys.argv)
    raise

import hashlib
import io
import json
import math
import re
import shutil
import time
import traceback
from pathlib import Path

import numpy as np
import pyproj
from PIL import Image, ImageDraw
from shapely import wkb as swkb
from shapely.geometry import MultiPoint, box, mapping, shape
from shapely.ops import transform, unary_union
from shapely.prepared import prep

from asetukset import *  # noqa: F401,F403
from mml_asiakas import LASER_PROSESSI, MmlAsiakas, MmlVirhe

gdal.UseExceptions()
ogr.UseExceptions()

# ----------------------------------------------------------------------------------------
# ASETUKSET
# ----------------------------------------------------------------------------------------
# Alueen ulkoraja (EPSG:3067). Rantavyöhyke rajataan tähän laatikkoon. Alueen voi laajentaa kasvattamalla laatikkoa
# (esimerkiksi (314000, 6820000, 347500, 6880000) koko Näsijärven vesialueen ympärille), jolloin laserruudut haetaan
# uudelleen indeksistä ja kaikki vaiheet lasketaan alueelle.
ALUE_LAATIKKO = (322000, 6820000, 334000, 6827000)
VYOHYKE_M = 1000            # rantavyöhykkeen leveys vesialueen reunasta molemmille puolille
RUUDUKKO_M = 100            # laskentaruudukon ulkoraja pyöristetään tähän
RES = 1.0                   # pintamallin ruutukoko metreinä
TAYTTOSADE = 3              # pisteettömien ruutujen täyttö lähimmästä pisteestä, enintään näin monta ruutua
ZOOM_MIN, ZOOM_MAX = 12, 16
PINTA_KVANTTI = 0.5         # Terrain-RGB-kvantisointi metreinä (maasto.pmtiles: 0,5)
PINTA_KOKO_RAJA_MT = 30.0
SIIRTO_Z15_RAJA_MT = 3.0
PIENIN_PISTEMAARA = 5       # rakennus saa korkeuden, kun polygonissa on vähintään näin monta pistettä
KOHINA_TUKI = 3             # korkea piste hyväksytään, kun 12 m x 12 m x 12 m ympäristössä on vähintään näin monta pistettä
KOHINA_RAJA_M = 4.0         # tuki vaaditaan vain pisteiltä, jotka ovat tämän verran DEM:n yläpuolella
EPAVARMA_ALA_M2 = 150.0     # rakennus merkitään epävarmaksi (todennäköisesti keilauksen jälkeen rakennettu), kun ala on vähintään tämä
EPAVARMA_H_M = 3.0          # ja polygonin korkein piste on alle tämän verran maanpinnan yläpuolella
PILVI_RAJA_M = 45.0         # ilmassa leijuvien pilvien (höyry, savu) tunnistus vain tämän DEM:n yläpuolisilta pisteiltä
PILVI_RUUTU_M = 8.0         # tunnistus 8 m x 8 m pystypylväissä
PILVI_VALI_M = 4.0          # saman kerroksen pisteiden enimmäisväli pystysuunnassa
PILVI_MIN_PISTEITA = 8      # kerros on pilvi, kun siinä on vähintään näin monta pistettä
PILVI_PAKSUUS_M = 8.0       # ja kerroksen paksuus on vähintään tämä (kiinteä katto on ohut, höyrypilvi paksu)
# Käsin määritellyt poissulkutilavuudet (E0, N0, E1, N1, korkein sallittu korkeus N2000). Naistenlahden voimalaitoksen
# höyrypilvi näkyy keilauksessa 2008 kiinteän pinnan tavoin 205-231 m:n korkeudella (noin 105-130 m maan yläpuolella) piipun päällä.
# Piipun omat osumat ovat alle 190 m:n korkeudella, joten tilavuuden yläpuoliset pisteet poistetaan.
POISSULKUTILAVUUDET = [
    {"nimi": "Naistenlahden voimalaitoksen höyrypilvi", "laatikko": (328350, 6823650, 328700, 6823950), "z_yli": 192.0},
]
POISTETTAVAT_LUOKAT = (7, 18)  # MML:n luokat 7 (matala roska) ja 18 (korkea roska). Luokkaa 18 ei tässä aineistossa ole
# MML:n uusi laserkeilaus (0,5 p/m2, 2020-) tiedostopalvelun OGC API Processes -rajapinnasta (vaihe 1c). Avain tulee ympäristömuuttujasta
# MML_API_KEY (GitHubin salaisuus), eikä sitä kirjoiteta mihinkään. Ilman avainta tai jos ruutu puuttuu, käytetään Paitulin vuoden 2008 keilausta.
MML_AVAIN_MUUTTUJA = "MML_API_KEY"
MML_OGC_OSOITE = "https://avoin-paikkatieto.maanmittauslaitos.fi/tiedostopalvelu/ogcproc/v1/"
MML_AINEISTO = "Uusin"                      # dataSetInput: "Uusin", "05p_2020-" tai "05p_2008-2019"
MML_POISTETTAVAT_LUOKAT = (7, 15, 16, 18)   # MML:n luokat: 7 matala piste, 15 ilmapiste, 16 yksittäinen piste, 18 korkea kohina
LASER_LISENSSI = "https://creativecommons.org/licenses/by/4.0/"
LASER_PAITULI = PAITULI + "mml/laserkeilaus/2008_latest/"
LASER_INDEKSI = ("2008_latest.shp", "2008_latest.shx", "2008_latest.dbf", "2008_latest.prj", "2008_latest.cpg")

# Tarkistuspisteet ja maamerkkien alkuarviot (EPSG:3067). Alkuarvot löytyvät pistepilvestä korkeimpien rakenteiden
# haulla, ja mitat lasketaan niiden ympäriltä automaattisesti (ks. vaihe maamerkit).
# Toinen näkymä on määrittelyn esimerkkipiste (suoraan pohjoisesta, 2 m vedenpinnasta, 120° kulma). Siitä kuljetin jää kattilarakennuksen
# ja lähirannan puuston taakse, joten pääkuva otetaan Naistenlahden poukamasta, jonka valitsee säteenjäljitys (ks. vaihe nakopiste).
SILUETTI_PISTE = (327740.0, 6823980.0)   # Naistenlahden poukama, vedessä, noin 800 m voimalaitokselta länteen (säteenjäljityshaun tulos)
SILUETTI_SUUNTA_DEG = 172.0
SILUETTI_KULMA_DEG = 160.0
SILUETTI_KORKEUS_M = 2.0                 # silmän korkeus vedenpinnasta
SILUETTI2_PISTE = (328500.0, 6824500.0)  # määrittelyn esimerkkipiste
SILUETTI2_SUUNTA_DEG = 180.0
SILUETTI2_KULMA_DEG = 120.0
TARKISTUS_SIEMEN = 20261024           # satunnaisotosten siemen (toistettavuus)
AVOIN_OTOS_N = 50                     # kriteeri 5: avoimen maan pisteiden määrä
EI_KEILATTU_H_M = 2.0                 # rakennus on 'ei keilattu', jos korkein piste on alle tämän verran maanpinnan yläpuolella
AVOIN_KENNO_M = 5                     # avoimen maan tunnistuksen kennokoko (m): kenno ja sen 8 naapuria ilman muuta kuin maapisteitä
AVOIN_MIN_MAAPISTEITA = 5             # ja keskikennossa vähintään näin monta maapistettä
AVOIN_RAKENNUSPUSKURI_M = 10.0
RAKENNUSOTOS_N = 40                   # kriteeri 4: vertailuotoksen koko (kerrostalot ja pientalot kumpikin)
SILUETTI_KARTTA = (326400.0, 6822950.0, 328800.0, 6824500.0)   # siluettikuvan kartan laatikko (E0, N0, E1, N1), 1 px = 1 m
NAKOPISTE_HAKU = (326500, 6823900, 330500, 6826600, 40)   # E0, N0, E1, N1, hilaväli (m), vedessä olevat pisteet
NAKOPISTE_ETAISYYS_M = (450, 1800)                        # etäisyys kattilarakennuksesta

# ----------------------------------------------------------------------------------------
# Polut
# ----------------------------------------------------------------------------------------
LTYO = TYO / "laser"
LRAAKA = LTYO / "raaka"
LAZ = LRAAKA / "laz"
LAZ_MML = LAZ / "mml"                       # MML:n ruudut (välimuistihakemiston sisällä): <ruutu>.laz ja <ruutu>.json (metatiedot)
LPISTEET = LTYO / "pisteet"
LKUVAT = ULOS / "tarkistuskuvat"
LOKI = LTYO / "loki.json"
PUHDAS_KOHTEET = [LTYO / n for n in ("alue.json", "ruudut.json", "dem1.tif", "pisteet", "pinta_1m.tif", "pinta_osat",
                                     "rakennuskorkeudet.json", "maamerkit.json", "pinta.pmtiles", "tarkistus_1b.json",
                                     "tiilet_tilasto.json", "loki.json", "kuvat_tilasto.json")]

T3067_4326 = pyproj.Transformer.from_crs(3067, 4326, always_xy=True)
T4326_3067 = pyproj.Transformer.from_crs(4326, 3067, always_xy=True)
T3067_3857 = pyproj.Transformer.from_crs(3067, 3857, always_xy=True)
WM = 20037508.342789244


def vaihe1_tyo():
    """Hakemisto, jossa vaiheen 1 välitulokset ovat."""
    ymp = os.environ.get("LASER_VAIHE1_TYO")
    if ymp:
        return Path(ymp)
    return TYO


def v1(nimi):
    return str(vaihe1_tyo() / nimi)


def loki_lue():
    return lue_json(LOKI, {}) or {}


def loki_kirjoita(avain, arvo):
    d = loki_lue()
    d[avain] = arvo
    kirjoita_json(LOKI, d)


# ----------------------------------------------------------------------------------------
# Alue ja ruudukko
# ----------------------------------------------------------------------------------------
def lue_vesi():
    """Näsijärven vesialue (vaiheen 1 aoi.gpkg, kerros vesi) EPSG:3067:ssä."""
    ds = ogr.Open(v1("aoi.gpkg"))
    k = ds.GetLayerByName("vesi")
    g = unary_union([swkb.loads(bytes(f.GetGeometryRef().ExportToWkb())) for f in k])
    return g


def vaihe_alue():
    t = time.time()
    vesi = lue_vesi()
    bb = box(*ALUE_LAATIKKO)
    paikallinen = vesi.intersection(bb.buffer(VYOHYKE_M + 500)).simplify(1.0)
    vyohyke = paikallinen.boundary.buffer(VYOHYKE_M).intersection(bb)
    # Laskentaruudukko: vyöhykkeen ulkoraja pyöristettynä ulospäin
    x0, y0, x1, y1 = vyohyke.bounds
    r = RUUDUKKO_M
    ruudukko = (int(math.floor(x0 / r) * r), int(math.floor(y0 / r) * r),
                int(math.ceil(x1 / r) * r), int(math.ceil(y1 / r) * r))
    ruudukko = (max(ruudukko[0], ALUE_LAATIKKO[0]), max(ruudukko[1], ALUE_LAATIKKO[1]),
                min(ruudukko[2], ALUE_LAATIKKO[2]), min(ruudukko[3], ALUE_LAATIKKO[3]))
    tied = {
        "alue_laatikko": list(ALUE_LAATIKKO), "ruudukko": list(ruudukko), "vyohyke_m": VYOHYKE_M,
        "vyohyke_km2": round(vyohyke.area / 1e6, 2),
        "vesi_laatikossa_km2": round(vesi.intersection(bb).area / 1e6, 2),
        "ruudukko_leveys": int((ruudukko[2] - ruudukko[0]) / RES), "ruudukko_korkeus": int((ruudukko[3] - ruudukko[1]) / RES),
    }
    kirjoita_json(LTYO / "alue.json", dict(tied, vyohyke=mapping(vyohyke), vesi=mapping(paikallinen.intersection(box(*ruudukko).buffer(300)))))
    loki("alue: ruudukko %s, vyöhyke %.1f km², vesialue laatikossa %.1f km² (%.1f s)" % (
        ruudukko, tied["vyohyke_km2"], tied["vesi_laatikossa_km2"], time.time() - t))
    return tied


def alue():
    d = lue_json(LTYO / "alue.json")
    if d is None:
        vaihe_alue()
        d = lue_json(LTYO / "alue.json")
    d["vyohyke_g"] = shape(d["vyohyke"])
    d["vesi_g"] = shape(d["vesi"])
    return d


class Ruudukko:
    """Laskentaruudukko EPSG:3067:ssä. Rivi 0 on pohjoisin. Ruudun (i, j) keskipiste on (e0+(j+0,5)*res, n1-(i+0,5)*res)."""

    def __init__(self, laatikko, res=RES):
        self.e0, self.n0, self.e1, self.n1 = [float(v) for v in laatikko]
        self.res = float(res)
        self.w = int(round((self.e1 - self.e0) / res))
        self.h = int(round((self.n1 - self.n0) / res))

    def geotransform(self):
        return (self.e0, self.res, 0.0, self.n1, 0.0, -self.res)

    def sarake(self, e):
        return np.floor((np.asarray(e) - self.e0) / self.res).astype(np.int64)

    def rivi(self, n):
        return np.floor((self.n1 - np.asarray(n)) / self.res).astype(np.int64)

    def piirra(self, geom):
        """Rasteroi geometria totuusarvotaulukoksi (True = sisällä)."""
        im = Image.new("1", (self.w, self.h), 0)
        d = ImageDraw.Draw(im)
        if geom.is_empty:
            return np.zeros((self.h, self.w), dtype=bool)

        def pix(c):
            return [((x - self.e0) / self.res, (self.n1 - y) / self.res) for x, y in c]
        for poly in getattr(geom, "geoms", [geom]):
            if poly.geom_type != "Polygon":
                continue
            d.polygon(pix(poly.exterior.coords), fill=1)
            for ring in poly.interiors:
                d.polygon(pix(ring.coords), fill=0)
        return np.array(im, dtype=bool)


def ruudukko():
    a = alue()
    return Ruudukko(a["ruudukko"]), a


def kirjoita_tif(polku, taulu, rd, nodata=-9999.0, tyyppi=gdal.GDT_Float32, lzw=True):
    drv = gdal.GetDriverByName("GTiff")
    opts = ["TILED=YES", "BLOCKXSIZE=256", "BLOCKYSIZE=256", "COMPRESS=DEFLATE", "PREDICTOR=3" if tyyppi == gdal.GDT_Float32 else "PREDICTOR=2",
            "BIGTIFF=IF_SAFER"]
    tmp = str(polku) + ".osa"
    ds = drv.Create(tmp, rd.w, rd.h, 1, tyyppi, options=opts)
    ds.SetGeoTransform(rd.geotransform())
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(3067)
    ds.SetProjection(srs.ExportToWkt())
    b = ds.GetRasterBand(1)
    b.SetNoDataValue(nodata)
    b.WriteArray(np.where(np.isfinite(taulu), taulu, nodata).astype(np.float32) if tyyppi == gdal.GDT_Float32 else taulu)
    ds.FlushCache()
    ds = None
    os.replace(tmp, polku)


def lue_tif(polku, nodata_nan=True):
    ds = gdal.Open(str(polku))
    a = ds.GetRasterBand(1).ReadAsArray()
    nd = ds.GetRasterBand(1).GetNoDataValue()
    ds = None
    if nodata_nan and nd is not None and a.dtype.kind == "f":
        a = np.where(a == nd, np.nan, a)
    return a


# ----------------------------------------------------------------------------------------
# Ruudut
# ----------------------------------------------------------------------------------------
def hakemistolista(url):
    """Apache-hakemistolistauksen tiedostot ja alihakemistot."""
    try:
        teksti = hae_teksti(url, yrityksia=3).decode("utf-8", "replace")
    except Exception:  # noqa: BLE001
        return [], []
    nimet = re.findall(r'href="([^"?/][^"?]*)"', teksti)
    hak = [n for n in nimet if n.endswith("/") and not n.startswith("/")]
    tied = [n for n in nimet if not n.endswith("/") and not n.startswith("/")]
    return hak, tied


def vaihe_ruudut():
    t = time.time()
    rd, a = ruudukko()
    for n in LASER_INDEKSI:
        hae(LASER_PAITULI + n, LRAAKA / n, kerro=False)
    ds = ogr.Open(str(LRAAKA / "2008_latest.shp"))
    k = ds.GetLayer(0)
    zon = a["vyohyke_g"]
    b = [float(v) for v in zon.bounds]
    k.SetSpatialFilterRect(b[0], b[1], b[2], b[3])
    zp = prep(zon)
    ruudut = []
    for f in k:
        g = swkb.loads(bytes(f.GetGeometryRef().ExportToWkb()))
        if not zp.intersects(g):
            continue
        osuus = g.intersection(zon).area
        if osuus <= 0:
            continue
        polku = f["path"]                               # mml/laserkeilaus/2008_latest/<vuosi>/<lehti>/<1|2>/<ruutu>.laz
        osat = polku.split("/")
        vuosi, lehti, ala, nimi = osat[3], osat[4], osat[5], osat[6][:-4]
        ruudut.append({"ruutu": nimi, "vuosi": int(vuosi), "lehti": lehti, "alahakemisto": ala, "polku": polku,
                       "laatikko": [float(v) for v in g.bounds], "vyohykkeen_osuus_km2": round(osuus / 1e6, 2)})
    ruudut.sort(key=lambda r: r["ruutu"])
    # Tarkistus hakemistolistauksista: tiedosto on olemassa, ja ruudulle ei ole uudempaa vuotta
    vuosilistat = {}
    for r in ruudut:
        lista_url = LASER_PAITULI + "%d/%s/%s/" % (r["vuosi"], r["lehti"], r["alahakemisto"])
        if lista_url not in vuosilistat:
            vuosilistat[lista_url] = hakemistolista(lista_url)[1]
        r["listauksessa"] = (r["ruutu"] + ".laz") in vuosilistat[lista_url]
    lehdet = sorted({r["lehti"] for r in ruudut})
    uudemmat = []
    for vuosi in range(min(r["vuosi"] for r in ruudut) + 1, datetime_nyt_vuosi() + 1):
        hak, _ = hakemistolista(LASER_PAITULI + "%d/" % vuosi)
        for lehti in lehdet:
            if lehti + "/" in hak:
                uudemmat.append({"vuosi": vuosi, "lehti": lehti})
    yhteensa = {"ruutuja": len(ruudut), "lehdet": lehdet, "vuodet": sorted({r["vuosi"] for r in ruudut}),
                "uudempia_vuosia_samalle_lehdelle": uudemmat, "kaikki_listauksessa": all(r["listauksessa"] for r in ruudut)}
    kirjoita_json(LTYO / "ruudut.json", {"ruudut": ruudut, "yhteenveto": yhteensa})
    loki("ruudut: %d ruutua, lehdet %s, vuodet %s, uudempia vuosia lehdille: %s (%.1f s)" % (
        len(ruudut), lehdet, yhteensa["vuodet"], uudemmat or "ei", time.time() - t))
    return ruudut


def datetime_nyt_vuosi():
    return int(time.strftime("%Y"))


_RUUDUT_VALIMUISTI = {"mtime": None, "data": None}


def ruudut():
    """Ruutulista ruudut.json:sta (välimuistissa tiedoston muutosajan mukaan)."""
    polku = LTYO / "ruudut.json"
    if not polku.exists():
        vaihe_ruudut()
    mt = polku.stat().st_mtime_ns
    if _RUUDUT_VALIMUISTI["mtime"] != mt:
        _RUUDUT_VALIMUISTI["data"] = lue_json(polku)["ruudut"]
        _RUUDUT_VALIMUISTI["mtime"] = mt
    return _RUUDUT_VALIMUISTI["data"]


def lahde_lyhyt(r):
    return "mml" if r.get("lahde") == "mml_tiedostopalvelu" else "2008"


def laz_polku(r):
    """Ruudun käytettävä LAZ-tiedosto (MML:n uusi keilaus tai Paitulin 2008)."""
    return LAZ_MML / (r["ruutu"] + ".laz") if lahde_lyhyt(r) == "mml" else LAZ / (r["ruutu"] + ".laz")


def npz_polku(r):
    return LPISTEET / ("%s_%s.npz" % (r["ruutu"], lahde_lyhyt(r)))


def ruutu_nimella(nimi):
    for r in ruudut():
        if r["ruutu"] == nimi:
            return r
    raise KeyError(nimi)


def keilausvuodet():
    return sorted({r["vuosi"] for r in ruudut() if r.get("vuosi")})


def laser_lahdemerkinta():
    """Lähdemerkintä käytettyjen ruutujen keilausvuosien mukaan (vuosi/vuosi, jos lähteitä on useita)."""
    return "Sisältää Maanmittauslaitoksen laserkeilausaineistoa %s (CC BY 4.0)" % "/".join(str(v) for v in keilausvuodet())


def keilausselite():
    """Lyhyt kuvaus käytetystä keilauksesta: 'MML 2023' tai 'MML 2023, osin Paituli 2008'."""
    rs = ruudut()
    mml = sorted({r["vuosi"] for r in rs if r.get("lahde") == "mml_tiedostopalvelu" and r.get("vuosi")})
    vara = [r for r in rs if r.get("lahde") != "mml_tiedostopalvelu"]
    osat = []
    if mml:
        osat.append("MML:n uusi keilaus %s" % "/".join(str(v) for v in mml))
    if vara:
        osat.append(("ruudut %s: Paitulin keilaus 2008" % ", ".join(r["ruutu"] for r in vara)) if mml else "Paitulin keilaus 2008")
    return ", ".join(osat)


def laz_kelvollinen(polku):
    """Onko LAZ-tiedosto avattavissa ja onko siinä pisteitä (laspy lukee vain otsakkeen)."""
    try:
        import laspy
        with laspy.open(str(polku)) as f:
            return f.header.point_count > 0
    except Exception:  # noqa: BLE001
        return False


def hae_mml_ruudut(lista):
    """Hakee MML:n uuden keilauksen ruudut tiedostopalvelun OGC API Processes -rajapinnasta (yksi työ kaikille ruuduille).

    Palauttaa (ruutu -> tiedot, yhteenveto). Ei nosta virhettä: jos avainta ei ole tai haku epäonnistuu, palautetaan tyhjä tulos
    (tai välimuistissa jo olevat ruudut), ja kutsuja käyttää 2008-aineistoa varalähteenä. Ruudut tallennetaan hakemistoon tyo/laser/raaka/laz/mml/
    (välimuistihakemiston sisällä), ja jokaisen vieressä on <ruutu>.json, jossa on tulosvastauksen metatiedot ja muokkausaika. Tiedosto ladataan
    uudelleen vain, jos se puuttuu, koko poikkeaa tai MML:n lastModified on muuttunut.
    """
    from concurrent.futures import ThreadPoolExecutor
    avain = os.environ.get(MML_AVAIN_MUUTTUJA, "").strip()
    yht = {"avain_asetettu": bool(avain), "aineisto": MML_AINEISTO, "prosessi": LASER_PROSESSI, "pyydetty_ruutuja": len(lista)}
    tulos = {}
    t0 = time.time()

    def lue_valimuisti(nimi):
        p, j = LAZ_MML / (nimi + ".laz"), LAZ_MML / (nimi + ".json")
        if p.exists() and j.exists() and laz_kelvollinen(p):
            d = lue_json(j) or {}
            d["tavua"] = p.stat().st_size
            return d
        return None

    if not avain:
        loki("VAROITUS: %s puuttuu, MML:n uutta keilausta ei haeta. Käytetään välimuistissa olevia MML-ruutuja, muuten vuoden 2008 keilausta (Paituli)." % MML_AVAIN_MUUTTUJA)
        yht["tila"] = "ei avainta"
        for r in lista:
            d = lue_valimuisti(r["ruutu"])
            if d:
                tulos[r["ruutu"]] = d
        yht["valimuistista_ruutuja"] = len(tulos)
        return tulos, yht
    asiakas = MmlAsiakas(avain, loki=loki)
    try:
        ids = asiakas.yhteys()
        if LASER_PROSESSI not in ids:
            raise MmlVirhe("prosessia %s ei ole prosessiluettelossa" % LASER_PROSESSI)
        yht["tunnistus"] = asiakas.tunnistus
        nimet = [r["ruutu"] for r in lista]
        job, vast = asiakas.kaynnista(nimet, aineisto=MML_AINEISTO)
        yht["tyon_tunnus"] = job
        lop = asiakas.odota(job, enint_s=1200, vali_s=4, kerro=lambda j, st, pr, dt: loki("MML-työ %s: %s %s %% (%.0f s)" % (j[:8], st, pr, dt)))
        yht["tyon_tila"] = lop.get("status")
        yht["tyon_viesti"] = lop.get("message") or lop.get("statusMessage")
        if lop.get("status") != "successful":
            raise MmlVirhe("työ päättyi tilaan %s: %s" % (lop.get("status"), asiakas.siivoa_teksti(json.dumps(lop)[:300])))
        tul = asiakas.tulokset(job)
        tied = [t for t in asiakas.tiedostot(tul) if t["nimi"].lower().endswith(".laz")]
        yht["tuloksessa_ruutuja"] = len(tied)
        loki("MML: työ onnistui, tuloksessa %d / %d ruutua (%s)" % (len(tied), len(nimet), yht["tyon_viesti"]))
        pyydetyt = set(nimet)
        tied = [t for t in tied if t["lehti"] in pyydetyt]
        LAZ_MML.mkdir(parents=True, exist_ok=True)

        def kasittele(t):
            nimi = t["lehti"]
            p, j = LAZ_MML / (nimi + ".laz"), LAZ_MML / (nimi + ".json")
            meta = t.get("meta") or {}
            try:
                pituus = int(t["length"]) if t.get("length") else None
            except (TypeError, ValueError):
                pituus = None
            vanha = lue_json(j) if j.exists() else None
            sama = (p.exists() and vanha and vanha.get("lastModified") == meta.get("lastModified") and
                    (pituus is None or p.stat().st_size == pituus) and laz_kelvollinen(p))
            ladattu = 0
            if not sama:
                try:
                    ladattu = asiakas.lataa(t["path"], p)
                except MmlVirhe as e:
                    loki("VAROITUS: ruudun %s lataus epäonnistui (%s), käytetään 2008-aineistoa" % (nimi, str(e)[:200]))
                    return nimi, None
                if not laz_kelvollinen(p):
                    loki("VAROITUS: ladattu ruutu %s ei aukea, käytetään 2008-aineistoa" % nimi)
                    p.unlink(missing_ok=True)
                    return nimi, None
                kirjoita_json(j, {"lastModified": meta.get("lastModified"), "meta": meta, "haettu": nyt_iso(), "url": asiakas.siivoa_teksti(t["path"])})
            else:
                loki("MML-ruutu %s: välimuistissa, ei ladata" % nimi)
            d = lue_json(j) or {}
            d["tavua"] = p.stat().st_size
            d["ladattu_nyt_tavua"] = ladattu
            return nimi, d
        with ThreadPoolExecutor(max_workers=4) as ex:
            for nimi, d in ex.map(kasittele, tied):
                if d:
                    tulos[nimi] = d
        yht["tila"] = "ok"
    except (MmlVirhe, OSError, ValueError, KeyError) as e:
        yht["tila"] = "virhe"
        yht["virhe"] = asiakas.siivoa_teksti(str(e))[:400]
        loki("VAROITUS: MML-haku epäonnistui (%s). Käytetään välimuistin MML-ruutuja ja muuten 2008-aineistoa." % yht["virhe"])
        for r in lista:
            if r["ruutu"] not in tulos:
                d = lue_valimuisti(r["ruutu"])
                if d:
                    tulos[r["ruutu"]] = d
        yht["valimuistista_ruutuja"] = len(tulos)
    yht["pyyntoja"] = asiakas.pyyntoja
    yht["sekuntia"] = round(time.time() - t0, 1)
    yht["ladattu_nyt_tavua"] = int(sum(d.get("ladattu_nyt_tavua", 0) for d in tulos.values()))
    return tulos, yht


def vaihe_lataa():
    t0 = time.time()
    lista = ruudut()
    mml, mml_yht = hae_mml_ruudut(lista)
    tavuja = int(mml_yht.get("ladattu_nyt_tavua", 0))
    ladattu = sum(1 for d in mml.values() if d.get("ladattu_nyt_tavua"))
    rivit = []
    for r in lista:
        d = mml.get(r["ruutu"])
        if d:
            meta = d.get("meta") or {}
            vuosi = None
            for kentta in (meta.get("yearOfScanning"), (meta.get("dateOfScanning") or "")[:4], (meta.get("lastModified") or "")[:4]):
                if kentta and str(kentta).isdigit():
                    vuosi = int(kentta)
                    break
            r.update(lahde="mml_tiedostopalvelu", vuosi=vuosi, koko_tavua=d["tavua"], url=asiakas_osoite(d), mml_meta=meta,
                     metatiedot={"Keilauspaivamaara": meta.get("dateOfScanning"), "Pistetiheys": meta.get("pointDensity"),
                                 "Korkeustarkkuus": meta.get("elevationPrecision"), "Keilain": meta.get("scanner"),
                                 "Projekti(t)": meta.get("project"), "Pistepilvitunnus": meta.get("pointCloudID"),
                                 "Aineistoversio": meta.get("datasetVersion"), "Muokattu": meta.get("lastModified")})
            # Varalähteen vanha 2008-tiedosto ei ole enää tarpeen: se poistetaan, ettei välimuisti kasva turhaan
            for pääte in ("laz", "csv"):
                (LAZ / (r["ruutu"] + "." + pääte)).unlink(missing_ok=True)
        else:
            r.pop("mml_meta", None)
            r["lahde"] = "paituli_2008"
            r["vuosi"] = 2008
            for pääte in ("laz", "csv"):
                url = PAITULI + r["polku"][:-3] + pääte
                kohde = LAZ / (r["ruutu"] + "." + pääte)
                n, dt, uusi = hae(url, kohde, kerro=(pääte == "laz"))
                if uusi:
                    tavuja += n
                    ladattu += 1
                if pääte == "laz":
                    r["koko_tavua"] = n
                    r["url"] = url
                else:
                    r["metatiedot"] = lue_metatiedot(kohde)
        rivit.append(r)
    mml_yht["ruutuja_mml"] = sum(1 for r in rivit if r["lahde"] == "mml_tiedostopalvelu")
    mml_yht["ruutuja_2008_varalla"] = [r["ruutu"] for r in rivit if r["lahde"] != "mml_tiedostopalvelu"]
    mml_yht["vuodet"] = sorted({r["vuosi"] for r in rivit if r["lahde"] == "mml_tiedostopalvelu" and r["vuosi"]})
    d = lue_json(LTYO / "ruudut.json")
    d["ruudut"] = rivit
    d["yhteenveto"]["mml_haku"] = mml_yht
    d["yhteenveto"]["vuodet"] = sorted({r["vuosi"] for r in rivit if r.get("vuosi")})
    kirjoita_json(LTYO / "ruudut.json", d)
    siirto = loki_lue().get("lataus", {"tavua": 0, "sekuntia": 0.0})
    siirto["tavua"] += tavuja
    siirto["sekuntia"] = round(siirto["sekuntia"] + time.time() - t0, 1)
    siirto["tiedostoja_ladattu_nyt"] = ladattu
    loki_kirjoita("lataus", siirto)
    loki_kirjoita("mml_haku", mml_yht)
    loki("lataus: MML-ruutuja %d, 2008-varalla %d (%s), tällä kertaa %d tiedostoa, %.1f Mt, %.0f s" % (
        mml_yht["ruutuja_mml"], len(mml_yht["ruutuja_2008_varalla"]), ", ".join(mml_yht["ruutuja_2008_varalla"]) or "-", ladattu, tavuja / 1e6, time.time() - t0))


def asiakas_osoite(d):
    """MML-ruudun lataus-URL (sivutiedostosta, ilman avainta)."""
    return d.get("url") or "https://avoin-paikkatieto.maanmittauslaitos.fi/tiedostopalvelu/dl/v1/"


def lue_metatiedot(polku):
    try:
        teksti = Path(polku).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}
    m = {}
    for rivi in teksti.splitlines():
        if ";" in rivi:
            a, b = rivi.split(";", 1)
            m[a.strip()] = b.strip()
    return m


# ----------------------------------------------------------------------------------------
# DEM 1 m ruudukkoon
# ----------------------------------------------------------------------------------------
def vaihe_korkeus():
    t = time.time()
    rd, a = ruudukko()
    ulos = LTYO / "dem1.tif"
    if tuore(ulos):
        return

    def varppaa(lahde):
        ds = gdal.Warp("", lahde, format="MEM", dstSRS="EPSG:3067", outputBounds=(rd.e0, rd.n0, rd.e1, rd.n1),
                       width=rd.w, height=rd.h, resampleAlg="bilinear", srcNodata=-9999, dstNodata=-9999,
                       outputType=gdal.GDT_Float32, multithread=True)
        arr = ds.GetRasterBand(1).ReadAsArray()
        ds = None
        return np.where(arr <= -9000, np.nan, arr)
    d2 = varppaa(v1("dem2.vrt"))
    puuttuu = ~np.isfinite(d2)
    if puuttuu.any():
        d10 = varppaa(v1("dem10.tif"))
        d2 = np.where(puuttuu, d10, d2)
    loki("DEM 1 m: ruutuja %d x %d, DEM 2 m:n ulkopuolella %.2f %% (%.0f s)" % (rd.w, rd.h, 100.0 * puuttuu.mean(), time.time() - t))
    kirjoita_tif(ulos, d2.astype(np.float32), rd)
    loki_kirjoita("dem_10m_osuus_pros", round(100.0 * float(puuttuu.mean()), 3))


def dem1():
    vaihe_korkeus()
    rd, _ = ruudukko()
    return lue_tif(LTYO / "dem1.tif"), rd


# ----------------------------------------------------------------------------------------
# Pistepilvi: luku, kohinasuodatus, tiivis välitallennus
# ----------------------------------------------------------------------------------------
def kohinasuodatus(x, y, z, dem_z):
    """Poistaa yksinäiset korkeat pisteet (linnut, kohina). Tuki lasketaan 4 m ruuduissa 3 x 3 x 3 -ympäristöstä."""
    ehdokas = (z - dem_z) > KOHINA_RAJA_M
    if not ehdokas.any():
        return np.ones(len(x), dtype=bool)
    ix = np.floor(x / 4.0).astype(np.int64)
    iy = np.floor(y / 4.0).astype(np.int64)
    iz = np.floor(z / 4.0).astype(np.int64) + 8
    K1, K2 = 2097152 * 1024, 1024
    avain = ix * K1 + iy * K2 + iz
    uniq, lkm = np.unique(avain, return_counts=True)
    e = np.where(ehdokas)[0]
    summa = np.zeros(len(e), dtype=np.int64)
    ak = avain[e]
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            for dz in (-1, 0, 1):
                k = ak + dx * K1 + dy * K2 + dz
                p = np.searchsorted(uniq, k)
                p[p >= len(uniq)] = len(uniq) - 1
                summa += np.where(uniq[p] == k, lkm[p], 0)
    ok = np.ones(len(x), dtype=bool)
    ok[e] = summa >= KOHINA_TUKI
    return ok


def pilvisuodatus(x, y, z, dem_z):
    """Poistaa ilmassa leijuvat paksut pistekerrokset (voimalaitosten höyry- ja savupilvet), jotka näkyvät pistepilvessä
    kiinteän pinnan tavoin. Kiinteä katto on 8 m x 8 m pylväässä ohut kerros, pilvi yli 8 m paksu ja tiheä."""
    ok = np.ones(len(x), dtype=bool)
    cand = np.where((z - dem_z) > PILVI_RAJA_M)[0]
    if len(cand) < PILVI_MIN_PISTEITA:
        return ok
    key = np.floor(x[cand] / PILVI_RUUTU_M).astype(np.int64) * 4194304 + np.floor(y[cand] / PILVI_RUUTU_M).astype(np.int64)
    zc = z[cand]
    jarj = np.lexsort((zc, key))
    ks, zs = key[jarj], zc[jarj]
    uusi = np.concatenate([[True], (ks[1:] != ks[:-1]) | (np.diff(zs) > PILVI_VALI_M)])
    alut = np.where(uusi)[0]
    gid = np.cumsum(uusi) - 1
    n = np.bincount(gid)
    paksuus = np.maximum.reduceat(zs, alut) - np.minimum.reduceat(zs, alut)
    pilvi = (n >= PILVI_MIN_PISTEITA) & (paksuus >= PILVI_PAKSUUS_M)
    poista = pilvi[gid]
    ok[cand[jarj[poista]]] = False
    return ok


def lue_ruutu_raaka(polku):
    import laspy
    las = laspy.read(str(polku))
    return (np.asarray(las.x), np.asarray(las.y), np.asarray(las.z), np.asarray(las.classification).astype(np.uint8),
            np.asarray(las.return_number).astype(np.uint8), np.asarray(las.number_of_returns).astype(np.uint8))


def vaihe_pisteet():
    t0 = time.time()
    rd, a = ruudukko()
    dem, _ = dem1()
    vesi = rd.piirra(a["vesi_g"])
    lista = ruudut()
    LPISTEET.mkdir(parents=True, exist_ok=True)
    reuna = 60.0
    tilasto = loki_lue().get("pisteet", {})
    for r in lista:
        ulos = npz_polku(r)
        if tuore(ulos):
            continue
        t = time.time()
        mml = lahde_lyhyt(r) == "mml"
        poistettavat = MML_POISTETTAVAT_LUOKAT if mml else POISTETTAVAT_LUOKAT
        x, y, z, c, rn, nr = lue_ruutu_raaka(laz_polku(r))
        n0 = len(x)
        ok = ~np.isin(c, poistettavat)
        n_l7 = int((~ok).sum())
        luokat_ennen = {int(k): int(v) for k, v in zip(*np.unique(c, return_counts=True))}
        ok &= (x >= rd.e0 - reuna) & (x < rd.e1 + reuna) & (y >= rd.n0 - reuna) & (y < rd.n1 + reuna)
        n_ulko = int(n0 - n_l7 - ok.sum())
        x, y, z, c, rn, nr = x[ok], y[ok], z[ok], c[ok], rn[ok], nr[ok]
        if len(x) == 0:
            np.savez(ulos, x=np.zeros(0, np.int32), y=np.zeros(0, np.int32), z=np.zeros(0, np.int32), c=np.zeros(0, np.uint8),
                     rn=np.zeros(0, np.uint8), nr=np.zeros(0, np.uint8))
            continue
        # DEM-korkeus pisteen kohdalla (alueen ulkopuolella lähin reunaruutu)
        j = np.clip(rd.sarake(x), 0, rd.w - 1)
        i = np.clip(rd.rivi(y), 0, rd.h - 1)
        dz = dem[i, j]
        dz = np.where(np.isfinite(dz), dz, np.nanmedian(dem))
        hyv = kohinasuodatus(x, y, z, dz)
        n_kohina = int((~hyv).sum())
        x, y, z, c, rn, nr, dz = x[hyv], y[hyv], z[hyv], c[hyv], rn[hyv], nr[hyv], dz[hyv]
        pil = pilvisuodatus(x, y, z, dz)
        if not mml:
            # Käsin rajatut poissulkutilavuudet kuvaavat vuoden 2008 keilauksen höyrypilveä, eivät uutta keilausta
            for tv in POISSULKUTILAVUUDET:
                te0, tn0, te1, tn1 = tv["laatikko"]
                pil &= ~((x >= te0) & (x < te1) & (y >= tn0) & (y < tn1) & (z > tv["z_yli"]))
        n_pilvi = int((~pil).sum())
        x, y, z, c, rn, nr = x[pil], y[pil], z[pil], c[pil], rn[pil], nr[pil]
        # Tiheys ruudun ja laskentaruudukon leikkauksessa (kaikki ruudut ja vain maaruudut)
        tl = r["laatikko"]
        e0, e1 = max(tl[0], rd.e0), min(tl[2], rd.e1)
        n0_, n1_ = max(tl[1], rd.n0), min(tl[3], rd.n1)
        tiheys = {}
        if e1 > e0 and n1_ > n0_:
            inb = (x >= e0) & (x < e1) & (y >= n0_) & (y < n1_)
            jj = np.clip(rd.sarake(x[inb]), 0, rd.w - 1)
            ii = np.clip(rd.rivi(y[inb]), 0, rd.h - 1)
            maalla = ~vesi[ii, jj]
            j0, j1 = int(round(e0 - rd.e0)), int(round(e1 - rd.e0))
            i0, i1 = int(round(rd.n1 - n1_)), int(round(rd.n1 - n0_))
            maa_ala = float((~vesi[i0:i1, j0:j1]).sum()) * rd.res * rd.res
            ala = (e1 - e0) * (n1_ - n0_)
            tiheys = {"ala_km2": round(ala / 1e6, 3), "maa_km2": round(maa_ala / 1e6, 3), "pisteita_alueella": int(inb.sum()),
                      "pisteita_maalla": int(maalla.sum()), "tiheys_p_m2": round(float(inb.sum()) / ala, 3),
                      "tiheys_maalla_p_m2": round(float(maalla.sum()) / maa_ala, 3) if maa_ala > 0 else None}
        np.savez(ulos, x=np.round((x - rd.e0) * 100).astype(np.int32), y=np.round((y - rd.n0) * 100).astype(np.int32),
                 z=np.round(z * 100).astype(np.int32), c=c, rn=rn, nr=nr)
        tilasto[r["ruutu"]] = dict({"lahde": r.get("lahde"), "vuosi": r.get("vuosi"), "luettu": int(n0), "poistettu_luokilla": n_l7,
                                    "poistetut_luokat": list(poistettavat), "luokat_ennen": luokat_ennen, "luokka7": n_l7,
                                    "alueen_ulkopuolella": n_ulko, "kohinaksi": n_kohina, "pilvea": n_pilvi,
                                    "tallennettu": int(len(x)), "sekuntia": round(time.time() - t, 1)}, **tiheys)
        loki("pisteet %s (%s %s): luettu %d, poistettu luokilla %s %d, ulkopuolella %d, kohinaksi %d, pilvi %d, tallennettu %d, tiheys %s (%.1f s)" % (
            r["ruutu"], r.get("lahde"), r.get("vuosi"), n0, list(poistettavat), n_l7, n_ulko, n_kohina, n_pilvi, len(x),
            tiheys.get("tiheys_p_m2"), time.time() - t))
        loki_kirjoita("pisteet", tilasto)
    yht = {"ruutuja": len(tilasto), "luettu": sum(v["luettu"] for v in tilasto.values()), "tallennettu": sum(v["tallennettu"] for v in tilasto.values()),
           "pisteita_alueella": sum(v.get("pisteita_alueella", 0) for v in tilasto.values()), "pisteita_maalla": sum(v.get("pisteita_maalla", 0) for v in tilasto.values()),
           "ala_km2": round(sum(v.get("ala_km2", 0) for v in tilasto.values()), 2), "maa_km2": round(sum(v.get("maa_km2", 0) for v in tilasto.values()), 2)}
    yht["tiheys_p_m2"] = round(yht["pisteita_alueella"] / (yht["ala_km2"] * 1e6), 3) if yht["ala_km2"] else None
    yht["tiheys_maalla_p_m2"] = round(yht["pisteita_maalla"] / (yht["maa_km2"] * 1e6), 3) if yht["maa_km2"] else None
    loki_kirjoita("pisteet_yhteensa", yht)
    loki("pisteet valmis (%.0f s): %s" % (time.time() - t0, yht))


def pisteet_ruudulle(nimi):
    d = np.load(npz_polku(ruutu_nimella(nimi)))
    return d["x"], d["y"], d["z"], d["c"], d["rn"], d["nr"]


def kaikki_pisteet(rd, ehto=None):
    """Generaattori: (x, y, z, luokka) metreinä EPSG:3067 / N2000, ruutu kerrallaan."""
    for r in ruudut():
        x, y, z, c, rn, nr = pisteet_ruudulle(r["ruutu"])
        if len(x) == 0:
            continue
        X = x.astype(np.float64) / 100.0 + rd.e0
        Y = y.astype(np.float64) / 100.0 + rd.n0
        Z = z.astype(np.float64) / 100.0
        if ehto is not None:
            m = ehto(X, Y, Z, c)
            X, Y, Z, c = X[m], Y[m], Z[m], c[m]
        yield r["ruutu"], X, Y, Z, c


# ----------------------------------------------------------------------------------------
# Pintamalli 1 m
# ----------------------------------------------------------------------------------------
def lahin_taytto(arr, kohde, sade):
    """Täyttää kohderuudut (arr on NaN) lähimmästä arvollisesta ruudusta enintään `sade` ruudun päästä.

    Lähimmyys on euklidista etäisyyttä ruutujen keskipisteiden välillä. Lähdearvoina käytetään vain arr:n arvoja.
    """
    out = arr.copy()
    h, w = arr.shape
    P = np.pad(arr, sade, mode="constant", constant_values=np.nan)
    siirrot = sorted(((dy, dx) for dy in range(-sade, sade + 1) for dx in range(-sade, sade + 1)
                      if (dy or dx) and dy * dy + dx * dx <= sade * sade + 0.5), key=lambda d: (d[0] ** 2 + d[1] ** 2, d))
    tyhja = kohde & ~np.isfinite(out)
    for dy, dx in siirrot:
        if not tyhja.any():
            break
        src = P[sade + dy:sade + dy + h, sade + dx:sade + dx + w]
        m = tyhja & np.isfinite(src)
        out[m] = src[m]
        tyhja &= ~m
    return out


def vaihe_pinta():
    t0 = time.time()
    rd, a = ruudukko()
    dem, _ = dem1()
    vesi = rd.piirra(a["vesi_g"])
    vyoh = rd.piirra(a["vyohyke_g"])
    maxz = np.full((rd.h, rd.w), -np.inf, dtype=np.float32)
    vesi_naytteet = []
    tilasto = {"pisteita_ruuduissa": 0}
    for nimi, X, Y, Z, C in kaikki_pisteet(rd):
        j = rd.sarake(X)
        i = rd.rivi(Y)
        m = (j >= 0) & (j < rd.w) & (i >= 0) & (i < rd.h)
        j, i, Z, C = j[m], i[m], Z[m], C[m]
        vm = vesi[i, j]
        w9 = vm & (C == 9)
        if w9.any():
            vesi_naytteet.append(Z[w9][::40].astype(np.float32))
        np.maximum.at(maxz.ravel(), i * rd.w + j, Z.astype(np.float32))
        tilasto["pisteita_ruuduissa"] += int(len(Z))
        loki("pinta: ruutu %s käsitelty" % nimi)
    raaka = np.where(np.isfinite(maxz), maxz, np.nan).astype(np.float32)
    del maxz
    peitto = float(np.isfinite(raaka)[vyoh].mean())
    taso = float(np.median(np.concatenate(vesi_naytteet))) if vesi_naytteet else float(np.nanmedian(dem[vesi]))
    taso_dem = float(np.nanmedian(dem[vesi])) if vesi.any() else float("nan")
    loki("pinta: pistepeitto vyöhykkeellä %.1f %% (1 m ruuduista), järven pinta pisteistä %.2f m, DEM:stä %.2f m" % (100 * peitto, taso, taso_dem))
    # Maa ja vesi täytetään erikseen, jotta maan pisteet eivät ulotu veteen eivätkä päinvastoin
    maa = np.where(~vesi, raaka, np.nan)
    maa = lahin_taytto(maa, ~vesi, TAYTTOSADE)
    maa_puuttui = ~vesi & ~np.isfinite(maa)
    maa = np.where(maa_puuttui, dem, maa)
    maa = np.where(~vesi, np.maximum(maa, dem), maa)       # pintamalli ei voi olla maanpintaa alempana
    v = np.where(vesi, raaka, np.nan)
    v = np.where(np.isfinite(v) & (v < taso + 0.7), np.float32(taso), v)
    v = lahin_taytto(v, vesi, TAYTTOSADE)
    v = np.where(vesi & ~np.isfinite(v), np.float32(taso), v)
    pinta = np.where(vesi, v, maa).astype(np.float32)
    pinta = np.where(vyoh, pinta, np.nan)
    tilasto.update({
        "ruutuja_vyohykkeella": int(vyoh.sum()), "pistepeitto_pros": round(100 * peitto, 1),
        "maa_taytetty_demista_pros": round(100.0 * float((maa_puuttui & vyoh).sum()) / max(1, int((vyoh & ~vesi).sum())), 2),
        "jarven_pinta_pisteista_m": round(taso, 2), "jarven_pinta_demista_m": round(taso_dem, 2),
        "vesiruutuja_vyohykkeella": int((vesi & vyoh).sum()),
        "pinta_min_m": round(float(np.nanmin(pinta)), 2), "pinta_max_m": round(float(np.nanmax(pinta)), 2),
    })
    kirjoita_tif(LTYO / "pinta_1m.tif", pinta, rd)
    kirjoita_json(LTYO / "pinta_tilasto.json", tilasto)
    loki("pinta_1m.tif kirjoitettu: %s (%.0f s)" % (tilasto, time.time() - t0))


# ----------------------------------------------------------------------------------------
# Rakennuskorkeudet
# ----------------------------------------------------------------------------------------
def lue_rakennukset(vyohyke):
    """Maastotietokannan rakennukset (rajattu.gpkg, kerros rakennus) vyöhykkeellä: [(fid, geometria, ominaisuudet)]."""
    ds = ogr.Open(v1("rajattu.gpkg"))
    k = ds.GetLayerByName("rakennus")
    b = [float(v) for v in vyohyke.bounds]
    k.SetSpatialFilterRect(b[0], b[1], b[2], b[3])
    pv = prep(vyohyke)
    tulos = []
    for f in k:
        g = swkb.loads(bytes(f.GetGeometryRef().ExportToWkb()))
        if not pv.intersects(g):
            continue
        tulos.append((int(f.GetFID()), g, {"kaytto": f["kaytto"], "krs": f["krs"] or "", "luokka": int(f["luokka"])}))
    return tulos


def reunan_maanpinta(g, dem, rd):
    """Maanpinnan korkeus (N2000) rakennuksen reunalla: DEM:n mediaani polygonin reunaviivalla 2 m välein."""
    import shapely
    viiva = shapely.segmentize(g.boundary, 2.0)
    pisteet = []
    for osa in getattr(viiva, "geoms", [viiva]):
        pisteet.extend(osa.coords)
    p = np.asarray(pisteet, dtype=np.float64)
    j = np.clip(rd.sarake(p[:, 0]), 0, rd.w - 1)
    i = np.clip(rd.rivi(p[:, 1]), 0, rd.h - 1)
    v = dem[i, j]
    v = v[np.isfinite(v)]
    return float(np.median(v)) if len(v) else float("nan")


def vuosi_pisteelle(e, n):
    """Sen laserruudun keilausvuosi, jonka laatikossa piste on."""
    for r in ruudut():
        l_ = r["laatikko"]
        if l_[0] <= e < l_[2] and l_[1] <= n < l_[3]:
            return r["vuosi"]
    return None


def vaihe_rakennukset():
    t0 = time.time()
    rd, a = ruudukko()
    dem, _ = dem1()
    rak = lue_rakennukset(a["vyohyke_g"])
    loki("rakennukset: %d maastotietokannan rakennusta vyöhykkeellä" % len(rak))
    # Tunnisteraaste: jokaisen rakennuksen ruutuihin kirjoitetaan sen järjestysnumero (1..n)
    kuva = Image.new("I", (rd.w, rd.h), 0)
    d = ImageDraw.Draw(kuva)

    def pix(c):
        return [((x - rd.e0) / rd.res, (rd.n1 - y) / rd.res) for x, y in c]
    for n, (fid, g, p) in enumerate(rak, start=1):
        for poly in getattr(g, "geoms", [g]):
            if poly.geom_type != "Polygon":
                continue
            d.polygon(pix(poly.exterior.coords), fill=n)
            for ring in poly.interiors:
                d.polygon(pix(ring.coords), fill=0)
    tunn = np.array(kuva, dtype=np.int32)
    del kuva, d
    # Pisteet rakennuksiin
    lab_lista, z_lista = [], []
    for nimi, X, Y, Z, C in kaikki_pisteet(rd):
        j = rd.sarake(X)
        i = rd.rivi(Y)
        m = (j >= 0) & (j < rd.w) & (i >= 0) & (i < rd.h)
        j, i, Z = j[m], i[m], Z[m]
        lab = tunn[i, j]
        k = lab > 0
        lab_lista.append(lab[k])
        z_lista.append(Z[k].astype(np.float32))
    lab = np.concatenate(lab_lista)
    zz = np.concatenate(z_lista)
    jarj = np.lexsort((zz, lab))
    lab, zz = lab[jarj], zz[jarj]
    alut = np.searchsorted(lab, np.arange(1, len(rak) + 2))
    tulos = {}
    ei_korkeutta = 0
    for n, (fid, g, p) in enumerate(rak, start=1):
        z_maa = reunan_maanpinta(g, dem, rd)
        pisteita = int(alut[n] - alut[n - 1]) if n < len(alut) else 0
        pisteita = int(alut[n] - alut[n - 1])
        c = g.centroid
        rec = {"e": round(c.x, 1), "n": round(c.y, 1), "kaytto": p["kaytto"], "krs": p["krs"], "ala_m2": round(g.area, 1),
               "z_maa": round(z_maa, 2) if np.isfinite(z_maa) else None, "pisteita": pisteita, "keilausvuosi": vuosi_pisteelle(c.x, c.y)}
        if pisteita >= PIENIN_PISTEMAARA and np.isfinite(z_maa):
            osa = zz[alut[n - 1]:alut[n]].astype(np.float64) - z_maa
            rec["h_max"] = round(float(osa.max()), 2)
            rec["h_p90"] = round(float(np.percentile(osa, 90)), 2)
            rec["h_med"] = round(float(np.median(osa)), 2)
            # Suuri rakennus, jossa ei ole yhtään yli 3 m korkeaa pistettä, on todennäköisesti rakennettu keilauksen jälkeen
            if g.area >= EPAVARMA_ALA_M2 and rec["h_max"] < EPAVARMA_H_M:
                rec["epavarma"] = 1
        else:
            ei_korkeutta += 1
        # Ei keilattu: pisteitä alle 5 tai korkein piste alle 2 m maanpinnan yläpuolella eli rakennusta ei ollut keilaushetkellä (tai se on matala katos)
        if pisteita < PIENIN_PISTEMAARA or not np.isfinite(z_maa) or rec.get("h_max", 0.0) < EI_KEILATTU_H_M:
            rec["ei_keilattu"] = 1
        tulos[str(fid)] = rec
    saa = [r for r in tulos.values() if "h_p90" in r]
    yht = {"rakennuksia_vyohykkeella": len(rak), "korkeus_saatu": len(saa), "korkeus_saatu_pros": round(100.0 * len(saa) / max(1, len(rak)), 1),
           "alle_5_pistetta": ei_korkeutta, "pistetiheys_ruutua_kohden": round(float(len(zz)) / max(1.0, sum(r["ala_m2"] for r in tulos.values())), 3),
           "h_p90_alle_2_5_m": int(sum(1 for r in saa if r["h_p90"] < 2.5)),
           "epavarma_keilauksen_jalkeen_rakennettu": int(sum(1 for r in tulos.values() if r.get("epavarma"))),
           "ei_keilattu": int(sum(1 for r in tulos.values() if r.get("ei_keilattu"))),
           "ei_keilattu_ala_vahintaan_150_m2": int(sum(1 for r in tulos.values() if r.get("ei_keilattu") and r["ala_m2"] >= 150)),
           "keilausvuodet": sorted({r["keilausvuosi"] for r in tulos.values() if r.get("keilausvuosi")}),
           "mediaani_ala_m2": round(float(np.median([r["ala_m2"] for r in tulos.values()])), 1)}
    kirjoita_json(LTYO / "rakennuskorkeudet.json", {
        "avain": "fid = maastotietokannan rakennuskerroksen (tyo/rajattu.gpkg, kerros rakennus) kohteen FID, joka on sama kuin "
                 "kohteen 1-pohjainen järjestysnumero rakenna.py:n tee_rakennus-kierroksella. e ja n ovat polygonin keskipiste (EPSG:3067).",
        "kentat": {"z_maa": "maanpinta N2000, DEM:n mediaani polygonin reunalla (m)",
                   "h_max": "korkein piste polygonissa miinus z_maa (m)", "h_p90": "90. persentiili korkeuksista miinus z_maa (m)",
                   "h_med": "mediaani miinus z_maa (m)", "pisteita": "pisteiden määrä polygonissa (kohinasuodatuksen jälkeen)",
                   "ala_m2": "polygonin pinta-ala", "epavarma": "1 = vähintään 150 m² ja korkein piste alle 3 m: rakennus on todennäköisesti rakennettu keilauksen jälkeen",
                   "ei_keilattu": "1 = pisteitä alle 5 tai h_max alle 2 m: rakennusta ei ollut keilaushetkellä (tai se on matala katos). Älä käytä h_p90:tä korkeutena.",
                   "keilausvuosi": "sen laserruudun keilausvuosi, jonka alueella rakennuksen keskipiste on"},
        "huomio": "Korkeudet ovat laserkeilauksen ajalta (ks. aineisto_1b.json; käytetty keilaus: " + keilausselite() + "). Sen jälkeen rakennetuilla rakennuksilla "
                  "h_p90 kuvaa tonttia tai kasvillisuutta, ei rakennusta.",
        "yhteenveto": yht, "rakennukset": tulos}, kompakti=True)
    kirjoita_json(LTYO / "rakennukset_tilasto.json", yht)
    loki("rakennukset: %s (%.0f s)" % (yht, time.time() - t0))


# ----------------------------------------------------------------------------------------
# Maamerkit
# ----------------------------------------------------------------------------------------
# Maamerkkien alkuarviot (EPSG:3067). Ne on löydetty pistepilven korkeimpien rakenteiden ja katuosoitteiden perusteella,
# ja jokaisen mitat lasketaan alkuarvon ympäriltä pistepilvestä koodilla.
NASINNEULA_ALKU = (326711.0, 6823364.0)
VOIMALAITOS_ALKU = (328515.0, 6823755.0)
VOIMALAITOS_HAKUSADE_M = 160.0
TAMPELLA_KADUT = ("Verstaankatu", "Alaverstaanraitti", "Juhlatalonkatu", "Turpiininkatu", "Valssipadonraitti", "Tampellan esplanadi")
TAMPELLA_ETAISYYS_M = 25.0
TAMPELLA_PIIPPU_ALKU = (327815.0, 6823431.0)
SARKANNIEMI_LAATIKKO = (326350, 6823000, 327150, 6823750)
MUSTALAHTI_LAATIKKO = (326750, 6823100, 327150, 6823550)
MUSTALAHTI_VESIETAISYYS_M = 70.0


def ll(e, n):
    lon, lat = T3067_4326.transform(e, n)
    return [round(lon, 6), round(lat, 6)]


def piste_ominaisuudet(e, n):
    return {"epsg3067": [round(float(e), 1), round(float(n), 1)], "epsg4326": ll(e, n)}


def geom_ominaisuudet(g, tarkkuus=0.1):
    """Polygoni EPSG:3067:ssä ja EPSG:4326:ssa (ulkoreuna)."""
    g = g.simplify(1.0)
    ulko = g.exterior.coords if g.geom_type == "Polygon" else max(g.geoms, key=lambda q: q.area).exterior.coords
    return {"epsg3067": [[round(x, 1), round(y, 1)] for x, y in ulko],
            "epsg4326": [ll(x, y) for x, y in ulko], "ala_m2": round(g.area, 0)}


def pisteet_ikkuna(rd, dem, e0, n0, e1, n1):
    """Kaikki pisteet laatikossa: taulukko sarakkein x, y, z, nz (DEM:n yläpuolella), luokka, return_number, number_of_returns."""
    osat = []
    for r in ruudut():
        x, y, z, c, rn, nr = pisteet_ruudulle(r["ruutu"])
        if len(x) == 0:
            continue
        X = x.astype(np.float64) / 100.0 + rd.e0
        Y = y.astype(np.float64) / 100.0 + rd.n0
        m = (X >= e0) & (X < e1) & (Y >= n0) & (Y < n1)
        if not m.any():
            continue
        X, Y, Z = X[m], Y[m], z[m].astype(np.float64) / 100.0
        j = np.clip(rd.sarake(X), 0, rd.w - 1)
        i = np.clip(rd.rivi(Y), 0, rd.h - 1)
        osat.append(np.c_[X, Y, Z, Z - dem[i, j], c[m], rn[m], nr[m]])
    return np.vstack(osat) if osat else np.zeros((0, 7))


def ymparyskaavio(A, kenno=6.0):
    """Ryhmittelee pisteet (sarakkeet 0 ja 1) yhtenäisiksi klustereiksi kenno-ruudukossa (8-naapuruus). Palauttaa indeksilistat."""
    from collections import defaultdict
    kennot = defaultdict(list)
    ix = np.floor(A[:, 0] / kenno).astype(np.int64)
    iy = np.floor(A[:, 1] / kenno).astype(np.int64)
    for k, (a, b) in enumerate(zip(ix, iy)):
        kennot[(int(a), int(b))].append(k)
    nahty = set()
    tulos = []
    for avain in kennot:
        if avain in nahty:
            continue
        pino = [avain]
        nahty.add(avain)
        jasen = []
        while pino:
            q = pino.pop()
            jasen += kennot[q]
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    nb = (q[0] + dx, q[1] + dy)
                    if nb in kennot and nb not in nahty:
                        nahty.add(nb)
                        pino.append(nb)
        tulos.append(np.array(jasen))
    return tulos


def korkeat_kapeat(rd, dem, nz_raja=40.0, ylaosa_m=10.0, enint_laajuus_m=14.0):
    """Koko vyöhykkeen korkeat kapeat rakenteet (piiput, mastot): klusterit, joissa on pisteitä vähintään nz_raja m maan yläpuolella
    ja joiden ylimmän ylaosa_m m:n pisteet mahtuvat enint_laajuus_m m:n laajuuteen."""
    osat = []
    for r in ruudut():
        x, y, z, c, rn, nr = pisteet_ruudulle(r["ruutu"])
        if len(x) == 0:
            continue
        X = x.astype(np.float64) / 100.0 + rd.e0
        Y = y.astype(np.float64) / 100.0 + rd.n0
        Z = z.astype(np.float64) / 100.0
        j = np.clip(rd.sarake(X), 0, rd.w - 1)
        i = np.clip(rd.rivi(Y), 0, rd.h - 1)
        nz = Z - dem[i, j]
        m = nz >= nz_raja
        if m.any():
            osat.append(np.c_[X[m], Y[m], Z[m], nz[m], c[m]])
    if not osat:
        return []
    A = np.vstack(osat)
    tulos = []
    for idx in ymparyskaavio(A, 8.0):
        P = A[idx]
        if len(P) < 3:
            continue
        zmax = P[:, 2].max()
        T = P[P[:, 2] >= zmax - ylaosa_m]
        if len(T) < 3:
            continue
        lx, ly = np.ptp(T[:, 0]), np.ptp(T[:, 1])
        if max(lx, ly) > enint_laajuus_m:
            continue
        k = int(np.argmax(P[:, 2]))
        tulos.append({"e": round(float(T[:, 0].mean()), 1), "n": round(float(T[:, 1].mean()), 1), "z_huippu": round(float(zmax), 2),
                      "h_maasta": round(float(P[k, 3]), 1), "pisteita_ylaosassa": int(len(T)),
                      "ylaosan_leveys_m": round(float(max(lx, ly)), 1)})
    tulos.sort(key=lambda d: -d["h_maasta"])
    return tulos


def ymp_ruudukko(e0, n0, e1, n1):
    return Ruudukko((e0, n0, e1, n1))


def vektoroi(maski, rd2):
    """Totuusarvotaulukko -> yhtenäiset polygonit (8-naapuruus) EPSG:3067:ssä (GDAL Polygonize)."""
    ds = gdal.GetDriverByName("MEM").Create("", rd2.w, rd2.h, 1, gdal.GDT_Byte)
    ds.SetGeoTransform(rd2.geotransform())
    b = ds.GetRasterBand(1)
    b.WriteArray(maski.astype(np.uint8))
    vds = ogr.GetDriverByName("Memory").CreateDataSource("x")
    kerr = vds.CreateLayer("p", None, ogr.wkbPolygon)
    kerr.CreateField(ogr.FieldDefn("v", ogr.OFTInteger))
    gdal.Polygonize(b, b, kerr, 0, ["8CONNECTED=8"])
    tulos = []
    for f in kerr:
        if f.GetField("v") == 1:
            tulos.append(swkb.loads(bytes(f.GetGeometryRef().ExportToWkb())))
    return tulos


def ikkuna_rasterit(rd, pinta, dem, e0, n0, e1, n1):
    rd2 = ymp_ruudukko(e0, n0, e1, n1)
    j0, i0 = int(round(e0 - rd.e0)), int(round(rd.n1 - n1))
    P = pinta[i0:i0 + rd2.h, j0:j0 + rd2.w]
    D = dem[i0:i0 + rd2.h, j0:j0 + rd2.w]
    return rd2, P, D


def ympyra_sovitus(x, y):
    """Algebrallinen (Kåsa) ympyrän sovitus: palauttaa (keskipiste_x, keskipiste_y, sade)."""
    A = np.c_[2 * x, 2 * y, np.ones(len(x))]
    b = x * x + y * y
    sol, *_ = np.linalg.lstsq(A, b, rcond=None)
    cx, cy = sol[0], sol[1]
    r = math.sqrt(max(sol[2] + cx * cx + cy * cy, 0.0))
    return float(cx), float(cy), float(r)


def mittaa_nasinneula(rd, dem, piste_lista):
    e, n = NASINNEULA_ALKU
    A = pisteet_ikkuna(rd, dem, e - 80, n - 80, e + 80, n + 80)
    r = np.hypot(A[:, 0] - e, A[:, 1] - n)
    maa = A[(A[:, 4] == 2) & (r > 25) & (r < 70)]
    z_maa = float(np.median(maa[:, 2])) if len(maa) else float(np.nanmedian(dem[rd.rivi(n), rd.sarake(e)]))
    korkea = A[(A[:, 2] >= z_maa + 100) & (r < 35)]
    if len(korkea) < 20:
        return {"tunnus": "nasinneula", "nimi": "Näsinneula", "virhe": "pistepilvessä ei riittävästi pisteitä tornin kohdalla"}
    z_pod_mediaani = float(np.median(korkea[:, 2]))
    kori = korkea[korkea[:, 2] <= z_pod_mediaani + 9.0]
    masto = korkea[korkea[:, 2] > z_pod_mediaani + 9.0]
    ke, kn = float(kori[:, 0].mean()), float(kori[:, 1].mean())
    rr = np.hypot(kori[:, 0] - ke, kori[:, 1] - kn)
    halk_p99 = 2 * float(np.percentile(rr, 99))
    import shapely
    hull = shapely.MultiPoint(list(zip(kori[:, 0], kori[:, 1]))).convex_hull
    halk_ala = 2 * math.sqrt(hull.area / math.pi)
    ulko = kori[rr > 6.5]
    keski = kori[rr < 4.5]
    # Varsi: sivuosumat tornin akselin lähellä korin alapuolella
    varsi = A[(A[:, 2] > z_maa + 15) & (A[:, 2] < z_pod_mediaani - 8) & (np.hypot(A[:, 0] - ke, A[:, 1] - kn) < 9)]
    varsi_tulos = None
    if len(varsi) >= 8:
        cx, cy, rs = ympyra_sovitus(varsi[:, 0], varsi[:, 1])
        varsi_tulos = {"halkaisija_m": round(2 * rs, 1), "keskipiste_etaisyys_korista_m": round(math.hypot(cx - ke, cy - kn), 1),
                       "pisteita": int(len(varsi)), "korkeusalue_maasta_m": [round(float(varsi[:, 3].min()), 0), round(float(varsi[:, 3].max()), 0)],
                       "huomio": "Osumia on vain varren yhdeltä puolelta (keilaussuunta), joten sovitus on suuntaa-antava."}
    k = int(np.argmax(A[:, 2]))
    huippu = {"z_n2000_m": round(float(A[k, 2]), 2), "h_maasta_m": round(float(A[k, 2] - z_maa), 1),
              "e": round(float(A[k, 0]), 1), "n": round(float(A[k, 1]), 1), "mastopisteita": int(len(masto))}
    res = {
        "tunnus": "nasinneula", "nimi": "Näsinneula", "tyyppi": "torni", "sijainti": piste_ominaisuudet(ke, kn),
        "z_maa_n2000_m": round(z_maa, 2),
        "mitat": {
            "korkein_havaittu_piste": huippu,
            "lautanen": {"halkaisija_m": round(halk_p99, 1), "halkaisija_kupera_peite_m": round(halk_ala, 1),
                         "katon_ulkoreunan_korkeus_maasta_m": round(float(np.median(ulko[:, 2]) - z_maa), 1) if len(ulko) else None,
                         "katon_keskiosan_korkeus_maasta_m": round(float(np.percentile(keski[:, 2], 90) - z_maa), 1) if len(keski) else None,
                         "katon_ulkoreunan_z_n2000_m": round(float(np.median(ulko[:, 2])), 2) if len(ulko) else None,
                         "pisteita": int(len(kori)),
                         "huomio": "Lautasen alareunaa ja sivuseinää ei näy ylhäältä keilatussa aineistossa, joten pystysuuntaista paksuutta ei voi mitata."},
            "varsi": varsi_tulos,
        },
        "menetelma": {
            "maanpinta": "MML:n maanpintapisteiden (luokka 2) mediaani 25-70 m:n etäisyydeltä tornista.",
            "lautanen": "Pisteet, jotka ovat yli 100 m maan yläpuolella ja korkeintaan 9 m lautasen mediaanikorkeuden yläpuolella. "
                        "Halkaisija on 2 x pisteiden etäisyyden 99. persentiili keskipisteestä, vertailuna kuperan peitteen pinta-alaa vastaava halkaisija.",
            "varsi": "Algebrallinen ympyräsovitus (Kåsa) sivuosumiin tornin akselin lähellä lautasen alapuolella.",
            "huippu": "Korkein pistepilven piste tornin kohdalla kohinasuodatuksen jälkeen.",
        },
    }
    return res


def mittaa_voimalaitos(rd, dem, pinta, kapeat, rak_polygonit):
    e, n = VOIMALAITOS_ALKU
    R = VOIMALAITOS_HAKUSADE_M
    rd2, P, D = ikkuna_rasterit(rd, pinta, dem, e - R, n - R, e + R, n + R)
    nz = P - D
    vesi = rd2.piirra(alue()["vesi_g"])
    nz = np.where(vesi | ~np.isfinite(nz), 0.0, nz)
    # Pääsuuri rakennuskokonaisuus (nz > 15 m), kapeat osat (kuljetin) avataan pois
    polyt = vektoroi(nz > 15.0, rd2)
    avattu = []
    for g in polyt:
        og = g.buffer(-3.0, join_style=2).buffer(3.0, join_style=2)
        for q in getattr(og, "geoms", [og]):
            if q.geom_type == "Polygon" and q.area >= 300:
                avattu.append(q)
    hallit = sorted(avattu, key=lambda q: -q.area)
    tulos = {"tunnus": "naistenlahden_voimalaitos", "nimi": "Naistenlahden voimalaitos", "tyyppi": "voimalaitos",
             "huomio": "Keilaus: " + keilausselite() + ". Laitoksen sen jälkeen tehdyt laajennukset ja uudet piiput eivät näy aineistossa."}
    rakennukset = []
    for g in hallit[:3]:
        m = rd2.piirra(g)
        arvot = nz[m]
        z_maa = float(np.nanmedian(D[m])) if m.any() else float("nan")
        c = g.centroid
        rakennukset.append({"ääriviiva": geom_ominaisuudet(g), "keskipiste": piste_ominaisuudet(c.x, c.y),
                            "korkeus_p95_maasta_m": round(float(np.percentile(arvot, 95)), 1),
                            "korkeus_max_maasta_m": round(float(arvot.max()), 1),
                            "katon_z_p95_n2000_m": round(float(np.percentile(P[m], 95)), 1), "z_maa_n2000_m": round(z_maa, 1)})
    tulos["kattilarakennus"] = rakennukset[0] if rakennukset else None
    tulos["muut_suuret_rakennukset"] = rakennukset[1:]
    # Piiput: korkeat kapeat rakenteet voimalaitoksen ympärillä
    piiput = []
    for k in kapeat:
        if math.hypot(k["e"] - e, k["n"] - n) <= 200 and k["h_maasta"] >= 40:
            T = pisteet_ikkuna(rd, dem, k["e"] - 10, k["n"] - 10, k["e"] + 10, k["n"] + 10)
            T = T[T[:, 2] >= k["z_huippu"] - 8.0]
            pol = min((g.distance(shapely_point(k["e"], k["n"])) for g in rak_polygonit), default=float("nan"))
            piiput.append({"sijainti": piste_ominaisuudet(k["e"], k["n"]), "korkeus_maasta_m": k["h_maasta"], "z_huippu_n2000_m": k["z_huippu"],
                           "halkaisija_arvio_m": round(float(0.5 * (np.ptp(T[:, 0]) + np.ptp(T[:, 1]))), 1) if len(T) >= 4 else None,
                           "ylaosan_pisteita": int(len(T)), "etaisyys_rakennuspolygoniin_m": round(float(pol), 1)})
    piiput.sort(key=lambda d: -d["korkeus_maasta_m"])
    tulos["piiput"] = piiput
    # Kuljetin: kapea, pitkä rakenne (nz > 10 m), joka jää jäljelle, kun suuret rakennukset avataan pois
    suuri = rd2.piirra(unary_union([g.buffer(1.5) for g in hallit])) if hallit else np.zeros(nz.shape, dtype=bool)
    ohut = (nz > 10.0) & ~suuri
    kuljettimet = []
    for g in vektoroi(ohut, rd2):
        if g.area < 40:
            continue
        mr = g.minimum_rotated_rectangle
        xs, ys = mr.exterior.coords.xy
        sivut = sorted([math.hypot(xs[i + 1] - xs[i], ys[i + 1] - ys[i]) for i in range(2)])
        leveys, pituus = sivut[0], sivut[1]
        if pituus < 40 or leveys > 14:
            continue
        kuljettimet.append((pituus, leveys, g, mr))
    if kuljettimet:
        kuljettimet.sort(key=lambda t: -t[0])
        pituus, leveys, g, mr = kuljettimet[0]
        # akseli: pitkä sivu
        xs, ys = mr.exterior.coords.xy
        pts = [(xs[i], ys[i]) for i in range(4)]
        sivut = [(math.hypot(pts[(i + 1) % 4][0] - pts[i][0], pts[(i + 1) % 4][1] - pts[i][1]), i) for i in range(4)]
        sivut.sort(reverse=True)
        i1 = sivut[0][1]
        a1 = pts[i1]
        a2 = pts[(i1 + 1) % 4]
        suunta = np.array([a2[0] - a1[0], a2[1] - a1[1]]) / sivut[0][0]
        keski = np.array(mr.centroid.coords[0])
        puoli = pituus / 2.0
        p_a = keski - suunta * puoli
        p_b = keski + suunta * puoli
        # alkupiste = se pää, joka on lähempänä kattilarakennusta
        if hallit and hallit[0].distance(shapely_point(*p_b)) < hallit[0].distance(shapely_point(*p_a)):
            p_a, p_b = p_b, p_a
        m = rd2.piirra(g)
        arvot = nz[m]

        def pään_korkeus(pt):
            jj = np.clip(rd2.sarake(pt[0]), 0, rd2.w - 1)
            ii = np.clip(rd2.rivi(pt[1]), 0, rd2.h - 1)
            ikk = nz[max(ii - 6, 0):ii + 7, max(jj - 6, 0):jj + 7]
            return float(np.median(ikk[ikk > 10])) if (ikk > 10).any() else None
        profiili = []
        for osuus in (0.0, 0.25, 0.5, 0.75, 1.0):
            pt = p_a + (p_b - p_a) * osuus
            v = pään_korkeus(pt)
            profiili.append({"osuus_alusta": osuus, "e": round(float(pt[0]), 1), "n": round(float(pt[1]), 1),
                             "korkeus_maasta_m": round(v, 1) if v else None})
        tulos["kuljetinsilta"] = {
            "alkupiste": piste_ominaisuudet(*p_a), "loppupiste": piste_ominaisuudet(*p_b),
            "pituus_m": round(float(pituus), 1), "leveys_m": round(float(leveys), 1),
            "korkeus_maasta_p50_m": round(float(np.percentile(arvot, 50)), 1), "korkeus_maasta_max_m": round(float(arvot.max()), 1),
            "korkeus_alkupisteessa_m": round(pään_korkeus(p_a), 1) if pään_korkeus(p_a) else None,
            "korkeus_loppupisteessa_m": round(pään_korkeus(p_b), 1) if pään_korkeus(p_b) else None,
            "z_p50_n2000_m": round(float(np.percentile(P[m], 50)), 1),
            "korkeusprofiili_maasta_m": profiili,
            "suorakulmio": {"epsg3067": [[round(x, 1), round(y, 1)] for x, y in list(mr.exterior.coords)[:4]],
                            "epsg4326": [ll(x, y) for x, y in list(mr.exterior.coords)[:4]]},
            "suunta_asteina_pohjoisesta": round(math.degrees(math.atan2(suunta[0], suunta[1])) % 180, 1),
        }
    else:
        tulos["kuljetinsilta"] = None
    tulos["menetelma"] = {
        "kattilarakennus": "Pintamallin nDSM (pinta miinus DEM) yli 15 m, yhtenäinen alue, jonka kapeat osat on avattu pois 3 m:n puskurilla (sisään ja ulos).",
        "piiput": "Korkeat kapeat rakenteet: pistejoukot, joissa on pisteitä yli 40 m maan yläpuolella ja joiden ylimmän 10 m:n pisteet mahtuvat 14 m:n laajuuteen. "
                  "Halkaisija on ylimmän 8 m:n pisteiden x- ja y-laajuuden keskiarvo, ja se on karkea, koska ylhäältä keilatussa harvassa aineistossa piipun yläosassa on vain 3-6 osumaa.",
        "kuljetin": "nDSM yli 10 m, kun suuret rakennukset on poistettu. Pisin kapea (leveys alle 14 m, pituus yli 40 m) yhtenäinen alue. Päätepisteet ovat sen pienimmän ympäröivän suorakulmion lyhyiden sivujen keskipisteet, "
                    "ja alkupiste on se pää, joka on lähempänä kattilarakennusta.",
        "pilvi": "Piipun päällä leijuva höyrypilvi poistetaan pisteistä (POISSULKUTILAVUUDET).",
    }
    return tulos


def shapely_point(x, y):
    from shapely.geometry import Point
    return Point(float(x), float(y))


def lue_osoitepisteet(vyohyke, katut):
    ds = ogr.Open(v1("rajattu.gpkg"))
    k = ds.GetLayerByName("osoite")
    b = [float(v) for v in vyohyke.bounds]
    k.SetSpatialFilterRect(b[0], b[1], b[2], b[3])
    tulos = []
    for f in k:
        if f["katu"] in katut:
            g = swkb.loads(bytes(f.GetGeometryRef().ExportToWkb()))
            tulos.append((f["katu"], f["numero"], g.x, g.y))
    return tulos


def rakennus_tiedot(rak_lista, rk, g, fid):
    r = rk.get(str(fid), {})
    return {"fid": fid, "ääriviiva": geom_ominaisuudet(g), "keskipiste": piste_ominaisuudet(g.centroid.x, g.centroid.y),
            "ala_m2": r.get("ala_m2"), "kaytto": r.get("kaytto"), "krs": r.get("krs"), "z_maa_n2000_m": r.get("z_maa"),
            "h_p90_m": r.get("h_p90"), "h_max_m": r.get("h_max"), "pisteita": r.get("pisteita"),
            "epavarma": bool(r.get("epavarma"))}


def pilarin_todiste(rd, dem, e, n, sade=15.0, alaraja_m=20.0):
    """Todiste siitä, että korkea ohut pistejoukko on rakenne eikä harhapisteet: pisteiden määrä, luokat, kaikuja, pystysuuntainen peitto
    ja se, kuinka suurella osalla pisteistä on naapuri enintään 3 m päässä (vaakasuunnassa) ja enintään 5 m:n korkeuserolla."""
    P = pisteet_ikkuna(rd, dem, e - sade, n - sade, e + sade, n + sade)
    P = P[P[:, 3] >= alaraja_m]
    if len(P) == 0:
        return None
    luokat = {int(k): int(v) for k, v in zip(*np.unique(P[:, 4], return_counts=True))}
    d_h = np.hypot(P[:, None, 0] - P[None, :, 0], P[:, None, 1] - P[None, :, 1])
    d_z = np.abs(P[:, None, 2] - P[None, :, 2])
    nb = (d_h <= 3.0) & (d_z <= 5.0)
    np.fill_diagonal(nb, False)
    ylin = float(P[:, 3].max())
    lokerot = np.arange(alaraja_m, ylin + 5.0, 5.0)
    peitto = int(sum(1 for lo in lokerot if ((P[:, 3] >= lo) & (P[:, 3] < lo + 5.0)).any()))
    return {"pisteita_yli_%.0f_m" % alaraja_m: int(len(P)), "luokat": luokat, "ensimmaisia_kaikuja": int((P[:, 5] == 1).sum()),
            "korkein_maasta_m": round(ylin, 1), "pystypeitto_5_m_lokerot": "%d / %d" % (peitto, len(lokerot)),
            "pisteita_joilla_naapuri_3_m_5_m": "%d / %d" % (int(nb.any(axis=1).sum()), len(P)),
            "vaakalaajuus_m": [round(float(np.ptp(P[:, 0])), 1), round(float(np.ptp(P[:, 1])), 1)],
            "tulkinta": "Yhtenäinen pystysuuntainen pistejono maasta huippuun, kaikki ensimmäisiä kaikuja ja pieni vaakalaajuus: rakenne (piippu), ei lintuja tai luokan 7 / 18 harhapisteitä."}


def vaihe_maamerkit():
    t0 = time.time()
    rd, a = ruudukko()
    dem, _ = dem1()
    pinta = lue_tif(LTYO / "pinta_1m.tif")
    rak = lue_rakennukset(a["vyohyke_g"])
    rk = lue_json(LTYO / "rakennuskorkeudet.json")["rakennukset"]
    rak_polygonit = [g for _, g, _ in rak]
    kapeat = korkeat_kapeat(rd, dem)
    loki("maamerkit: %d korkeaa kapeaa rakennetta vyöhykkeellä, korkein %.1f m" % (len(kapeat), kapeat[0]["h_maasta"] if kapeat else 0))
    maamerkit = []
    for nimi_, fn_ in (("nasinneula", lambda: mittaa_nasinneula(rd, dem, kapeat)), ("naistenlahden_voimalaitos", lambda: mittaa_voimalaitos(rd, dem, pinta, kapeat, rak_polygonit))):
        try:
            maamerkit.append(fn_())
        except Exception as e:  # noqa: BLE001
            loki("VAROITUS: maamerkin %s mittaus epäonnistui: %s" % (nimi_, repr(e)[:300]))
            maamerkit.append({"tunnus_puuttuu": nimi_, "virhe": repr(e)[:300]})
    # Tampellan tehdasrakennukset: Tampellan alueen katujen osoitteiden ympäristön suuret rakennukset
    osoitteet = lue_osoitepisteet(a["vyohyke_g"], TAMPELLA_KADUT)
    if osoitteet:
        from shapely.geometry import MultiPoint
        alue_g = MultiPoint([(x, y) for _, _, x, y in osoitteet]).buffer(TAMPELLA_ETAISYYS_M)
        tamp = []
        for fid, g, p in rak:
            if g.area >= 400 and alue_g.intersects(g):
                tamp.append(rakennus_tiedot(rak, rk, g, fid))
        tamp.sort(key=lambda d: -(d["ala_m2"] or 0))
        piippu = [k for k in kapeat if math.hypot(k["e"] - TAMPELLA_PIIPPU_ALKU[0], k["n"] - TAMPELLA_PIIPPU_ALKU[1]) < 60]
        for k_ in piippu:
            k_["pistepilven_todiste"] = pilarin_todiste(rd, dem, k_["e"], k_["n"])
        maamerkit.append({"tunnus": "tampellan_tehdasrakennukset", "nimi": "Tampellan tehdasrakennukset", "tyyppi": "rakennusryhmä",
                          "rajaus": "Maastotietokannan rakennukset (pinta-ala vähintään 400 m²), joiden polygoni on enintään %.0f m:n päässä jonkin Tampellan alueen kadun osoitepisteestä: " % TAMPELLA_ETAISYYS_M
                                    + ", ".join(TAMPELLA_KADUT) + ". Rajaus on päätelty katunimistä, eikä sitä ole varmistettu rakennuskohtaisesti.",
                          "rakennukset": tamp[:25], "rakennuksia_rajauksessa": len(tamp),
                          "korkea_piippu_lahella": [{"sijainti": piste_ominaisuudet(k["e"], k["n"]), "korkeus_maasta_m": k["h_maasta"],
                                                      "z_huippu_n2000_m": k["z_huippu"], "pistepilven_todiste": k.get("pistepilven_todiste")} for k in piippu],
                          "huomio": "Ranta-Tampellan uudet kerrostalot rakennettiin vuoden 2016 jälkeen (YIT), joten ne eivät näy vuoden 2008 keilauksessa (käytetty keilaus: " + keilausselite() + "). "
                                    "Korkea piippu on keilauksessa tosi rakenne, ei harhapiste: siitä on yhtenäinen pistejono maasta huippuun (ks. pistepilven_todiste). "
                                    "Se näkyy siluettikuvassa suunnassa noin 172 astetta yli 10 asteen korkeuskulmassa."})
    # Särkänniemen korkeimmat laitteet: tiiviit korkeat ryhmät rakennusten ulkopuolella
    sk = pisteet_ikkuna(rd, dem, *SARKANNIEMI_LAATIKKO)
    rakkuva = rd.piirra(unary_union([g.buffer(2.0) for g in rak_polygonit]))
    j = np.clip(rd.sarake(sk[:, 0]), 0, rd.w - 1)
    i = np.clip(rd.rivi(sk[:, 1]), 0, rd.h - 1)
    ulkona = sk[(sk[:, 3] >= 15.0) & ~rakkuva[i, j] & (np.hypot(sk[:, 0] - NASINNEULA_ALKU[0], sk[:, 1] - NASINNEULA_ALKU[1]) > 45)]
    ehdokkaat = []
    for idx in ymparyskaavio(ulkona, 6.0):
        P = ulkona[idx]
        if len(P) < 8:
            continue
        lx, ly = np.ptp(P[:, 0]), np.ptp(P[:, 1])
        if max(lx, ly) > 16:
            continue
        k = int(np.argmax(P[:, 3]))
        ehdokkaat.append({"sijainti": piste_ominaisuudet(P[:, 0].mean(), P[:, 1].mean()), "korkeus_maasta_m": round(float(P[k, 3]), 1),
                          "z_huippu_n2000_m": round(float(P[k, 2]), 1), "pisteita": int(len(P)), "laajuus_m": round(float(max(lx, ly)), 1)})
    ehdokkaat.sort(key=lambda d: -d["korkeus_maasta_m"])
    maamerkit.append({"tunnus": "sarkanniemen_laitteet", "nimi": "Särkänniemen korkeimmat laitteet (ehdokkaat)", "tyyppi": "huvipuisto",
                      "rajaus": "Särkänniemen laatikko %s: tiiviit (enintään 16 m:n laajuiset) pistejoukot, joissa on vähintään 8 pistettä yli 15 m maan yläpuolella, "
                                "rakennusten (2 m:n puskuri) ja Näsinneulan (45 m) ulkopuolella." % (SARKANNIEMI_LAATIKKO,),
                      "laitteet": ehdokkaat[:8],
                      "huomio": "Pistepilvi ei kerro, onko kohde huvipuiston laite, mastotyyppinen rakenne vai tiheä puuryhmä. Laitteita ei ole tunnistettu nimeltä, ja laitteisto on voinut muuttua keilauksen jälkeen."})
    # Mustalahden satama: rakennukset laatikossa, enintään MUSTALAHTI_VESIETAISYYS_M m:n päässä vesialueesta
    vesi = a["vesi_g"]
    mus = []
    lb = box(*MUSTALAHTI_LAATIKKO)
    for fid, g, p in rak:
        if lb.intersects(g) and g.distance(vesi) <= MUSTALAHTI_VESIETAISYYS_M and g.area >= 60:
            mus.append(rakennus_tiedot(rak, rk, g, fid))
    mus.sort(key=lambda d: -(d["ala_m2"] or 0))
    maamerkit.append({"tunnus": "mustalahden_satama", "nimi": "Mustalahden satama", "tyyppi": "satama",
                      "rajaus": "Laatikko %s: Maastotietokannan rakennukset (vähintään 60 m²), enintään %.0f m:n päässä vesialueesta." % (MUSTALAHTI_LAATIKKO, MUSTALAHTI_VESIETAISYYS_M),
                      "rakennukset": mus[:30], "rakennuksia_rajauksessa": len(mus)})
    kirjoita_json(LTYO / "maamerkit.json", {
        "lahde": laser_lahdemerkinta() + ". Käytetty keilaus: " + keilausselite() + ".",
        "koordinaatistot": "EPSG:3067 (E, N metreinä) ja EPSG:4326 (lon, lat). Korkeudet metreinä, N2000. 'maasta' on korkeus maanpinnasta.",
        "maamerkit": maamerkit,
        "korkeat_kapeat_rakenteet_vyohykkeella": kapeat[:30]})
    loki("maamerkit.json kirjoitettu (%.0f s)" % (time.time() - t0))


# ----------------------------------------------------------------------------------------
# Kuvat: vinovalovarjostus ja apufunktiot
# ----------------------------------------------------------------------------------------
def varjostus(h, res=RES, atsimuutti=315.0, korkeuskulma=40.0, kerroin=1.0):
    """Vinovalovarjostus (0..1), float32. NaN-ruudut täytetään gradientin ajaksi pienimmällä arvolla."""
    h = np.asarray(h, dtype=np.float32)
    pohja = np.where(np.isfinite(h), h, np.float32(np.nanmin(h)) if np.isfinite(h).any() else np.float32(0))
    gy, gx = np.gradient(pohja, res)
    gy = -gy                      # rivit kasvavat etelään
    az = math.radians(360.0 - atsimuutti + 90.0)
    alt = math.radians(korkeuskulma)
    rinne = np.arctan(kerroin * np.hypot(gx, gy))
    suunta = np.arctan2(gy, -gx)
    v = np.sin(alt) * np.cos(rinne) + np.cos(alt) * np.sin(rinne) * np.cos(az - suunta)
    return np.clip(v, 0, 1).astype(np.float32)


def varjostus_rgb(h, vesi=None, res=RES, korkeusvarit=True, taustavari=(20, 30, 45), lo=None, hi=None):
    """Palauttaa uint8-RGB-taulukon. Käsittelee kuvan 800 rivin kaistoissa, jotta muisti riittää koko alueelle."""
    H, W = h.shape
    out = np.zeros((H, W, 3), dtype=np.uint8)
    ok_kaikki = np.isfinite(h)
    if korkeusvarit and (lo is None or hi is None) and ok_kaikki.any():
        lo, hi = np.nanpercentile(h[::4, ::4][ok_kaikki[::4, ::4]], [2, 98])
    kaista, halo = 800, 2
    for r0 in range(0, H, kaista):
        r1 = min(H, r0 + kaista)
        a0, a1 = max(0, r0 - halo), min(H, r1 + halo)
        hh = h[a0:a1]
        v = varjostus(hh, res)[r0 - a0:r0 - a0 + (r1 - r0)]
        ok = ok_kaikki[r0:r1]
        hk = h[r0:r1]
        g = 40 + 215 * v
        rgb = np.empty((r1 - r0, W, 3), dtype=np.float32)
        if korkeusvarit:
            t = np.clip((np.where(ok, hk, lo) - lo) / max(hi - lo, 1e-6), 0, 1)
            rgb[..., 0] = g * (0.75 + 0.35 * t)
            rgb[..., 1] = g * 0.95
            rgb[..., 2] = g * (1.05 - 0.35 * t)
        else:
            rgb[...] = g[..., None]
        if vesi is not None:
            vm = vesi[r0:r1]
            rgb[vm] = rgb[vm] * 0.35 + np.array([20, 45, 90], dtype=np.float32) * 0.65
        rgb[~ok] = taustavari
        out[r0:r1] = np.clip(rgb, 0, 255).astype(np.uint8)
    return out


def varjostuskuva(h, polku, res=RES, leveys=None, taustavari=(20, 30, 45), vesi=None, korkeusvarit=True):
    """Kirjoittaa PNG-kuvan: varjostus harmaasävyinä, korkeus mukana värisävynä."""
    im = Image.fromarray(varjostus_rgb(h, vesi, res, korkeusvarit, taustavari))
    if leveys and im.width > leveys:
        im = im.resize((leveys, int(im.height * leveys / im.width)), Image.LANCZOS)
    Path(polku).parent.mkdir(parents=True, exist_ok=True)
    im.save(polku)
    return im


# ----------------------------------------------------------------------------------------
# Terrain-RGB-tiilet (pinta.pmtiles)
# ----------------------------------------------------------------------------------------
def tiili_bbox(z, x, y):
    koko = 2 * WM / (1 << z)
    return (-WM + x * koko, WM - (y + 1) * koko, -WM + (x + 1) * koko, WM - y * koko)


def tiilet_alueelle(geom3857, z):
    x0, y0, x1, y1 = geom3857.bounds
    koko = 2 * WM / (1 << z)
    xa, xb = int((x0 + WM) // koko), int((x1 + WM) // koko)
    ya, yb = int((WM - y1) // koko), int((WM - y0) // koko)
    p = prep(geom3857)
    return [(z, x, y) for x in range(xa, xb + 1) for y in range(ya, yb + 1) if p.intersects(box(*tiili_bbox(z, x, y)))]


def koodaa_terrain(h, kvantti):
    """Mapbox Terrain-RGB: arvo = -10000 + (R*65536 + G*256 + B) * 0,1. Ei-dataa (NaN) -> RGB (0, 0, 0)."""
    ok = np.isfinite(h)
    hh = np.where(ok, h, 0.0)
    if kvantti and kvantti > 0.1:
        hh = np.round(hh / kvantti) * kvantti
    v = np.round((hh + 10000.0) * 10.0).astype(np.int64)
    v = np.where(ok, v, 0)
    rgb = np.zeros(h.shape + (3,), dtype=np.uint8)
    rgb[..., 0] = (v >> 16) & 255
    rgb[..., 1] = (v >> 8) & 255
    rgb[..., 2] = v & 255
    return rgb


def pura_terrain(rgb):
    v = (rgb[..., 0].astype(np.int64) << 16) + (rgb[..., 1].astype(np.int64) << 8) + rgb[..., 2].astype(np.int64)
    h = -10000.0 + v * 0.1
    return np.where(v == 0, np.nan, h)


def png_tavut(arr):
    b = io.BytesIO()
    Image.fromarray(arr).save(b, format="PNG", optimize=True, compress_level=9)
    return b.getvalue()


def pmtiles_kirjoita(polku, tiilet, tuota, metadata, minz, maxz, bbox4326, keskipiste):
    from pmtiles.tile import Compression, TileType, zxy_to_tileid
    from pmtiles.writer import write
    jarjestetty = sorted(tiilet, key=lambda t: zxy_to_tileid(*t))
    n, koko = 0, 0
    koot = {}
    with write(str(polku)) as w:
        for (z, x, y) in jarjestetty:
            data = tuota(z, x, y)
            if data is None:
                continue
            w.write_tile(zxy_to_tileid(z, x, y), data)
            koot[(z, x, y)] = len(data)
            n += 1
            koko += len(data)
        header = {
            "tile_type": TileType.PNG, "tile_compression": Compression.NONE, "min_zoom": minz, "max_zoom": maxz,
            "min_lon_e7": int(bbox4326[0] * 1e7), "min_lat_e7": int(bbox4326[1] * 1e7),
            "max_lon_e7": int(bbox4326[2] * 1e7), "max_lat_e7": int(bbox4326[3] * 1e7),
            "center_zoom": keskipiste[2], "center_lon_e7": int(keskipiste[0] * 1e7), "center_lat_e7": int(keskipiste[1] * 1e7),
        }
        w.finalize(header, metadata)
    return n, koko, koot


def warp_tiili(lahde, bbox, alg):
    ds = gdal.Warp("", lahde, format="MEM", dstSRS="EPSG:3857", outputBounds=bbox, width=256, height=256,
                   resampleAlg=alg, srcNodata=-9999.0, dstNodata=-9999.0, outputType=gdal.GDT_Float32, multithread=False)
    a = ds.GetRasterBand(1).ReadAsArray()
    ds = None
    return np.where(a <= -9000, np.nan, a)


def vaihe_tiilet(kvantti=None):
    t0 = time.time()
    kvantti = PINTA_KVANTTI if kvantti is None else kvantti
    rd, a = ruudukko()
    taso = lue_json(LTYO / "pinta_tilasto.json")["jarven_pinta_pisteista_m"]
    zon = transform(T3067_3857.transform, a["vyohyke_g"]).buffer(0)
    lahde = str(LTYO / "pinta_1m.tif")
    tiilet = []
    for z in range(ZOOM_MIN, ZOOM_MAX + 1):
        tiilet += tiilet_alueelle(zon, z)
    loki("tiilet: %d tiiltä ehdolla (zoom %d-%d)" % (len(tiilet), ZOOM_MIN, ZOOM_MAX))
    tilasto = {"ehdolla": len(tiilet), "ei_dataa": 0, "pelkkaa_vetta": 0}

    def tuota(z, x, y):
        h = warp_tiili(lahde, tiili_bbox(z, x, y), "bilinear" if z == ZOOM_MAX else "max")
        ok = np.isfinite(h)
        if not ok.any():
            tilasto["ei_dataa"] += 1
            return None
        if np.all(np.abs(h[ok] - taso) < 0.02):
            tilasto["pelkkaa_vetta"] += 1
            return None
        return png_tavut(koodaa_terrain(h, kvantti))

    b4326 = lonlat_laatikko(a["vyohyke_g"])
    meta = {"name": "Nasijarven rantavyohykkeen pintamalli", "format": "png", "type": "overlay", "encoding": "mapbox",
            "description": "Terrain-RGB (Mapbox), pintamalli (DSM). korkeus_m = -10000 + (R*65536 + G*256 + B) * 0,1. RGB (0,0,0) = ei dataa. "
                           "Korkeusjarjestelma N2000. Puuttuva tiili = pelkkaa vesialuetta (jarven pinta %.2f m) tai alueen ulkopuolta. "
                           "Laserkeilaus: %s, joten sen jalkeen rakennettu ei nay. Zoom 16: bilineaarinen, zoom 12-15: alueen maksimi (siluetit sailyvat)." % (taso, keilausselite()),
            "attribution": laser_lahdemerkinta(), "tile_size": 256, "quantization_m": kvantti,
            "lake_level_m": taso}
    polku = LTYO / "pinta.pmtiles"
    n, koko, koot = pmtiles_kirjoita(polku, tiilet, tuota, meta, ZOOM_MIN, ZOOM_MAX, b4326,
                                     ((b4326[0] + b4326[2]) / 2, (b4326[1] + b4326[3]) / 2, 13))
    ULOS.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(polku, ULOS / "pinta.pmtiles")
    zoomit = {}
    for (z, x, y), k in koot.items():
        zoomit.setdefault(str(z), {"tiilia": 0, "tavua": 0})
        zoomit[str(z)]["tiilia"] += 1
        zoomit[str(z)]["tavua"] += k
    # Puhelinnäkymä: 390 x 844 px:n näkymä zoomilla 15 kattaa enintään 3 x 5 tiiltä (256 px). Haetaan raskain 3 x 5 -ikkuna.
    z15 = {(x, y): k for (z, x, y), k in koot.items() if z == 15}
    pahin = 0
    pahin_ruutu = None
    if z15:
        xs = [x for x, _ in z15]
        ys = [y for _, y in z15]
        for x0 in range(min(xs) - 2, max(xs) + 1):
            for y0 in range(min(ys) - 4, max(ys) + 1):
                summa = sum(z15.get((x0 + dx, y0 + dy), 0) for dx in range(3) for dy in range(5))
                if summa > pahin:
                    pahin, pahin_ruutu = summa, (x0, y0)
    tilasto.update({"tiilia": n, "tavua": koko, "tiedosto_tavua": polku.stat().st_size, "kvantti_m": kvantti, "zoomit": zoomit,
                    "z15_puhelinnakyma_pahin_tavua": pahin, "z15_puhelinnakyma_vasen_ylakulma_xy": pahin_ruutu,
                    "sekuntia": round(time.time() - t0, 1)})
    kirjoita_json(LTYO / "tiilet_tilasto.json", tilasto)
    loki("pinta.pmtiles: %d tiiltä, %.1f Mt, z15-puhelinnäkymä enintään %.2f Mt (%.0f s) %s" % (
        n, polku.stat().st_size / 1e6, pahin / 1e6, time.time() - t0, tilasto))


def lonlat_laatikko(g3067):
    x0, y0, x1, y1 = g3067.bounds
    a = T3067_4326.transform(x0, y0)
    b = T3067_4326.transform(x1, y1)
    c = T3067_4326.transform(x0, y1)
    d = T3067_4326.transform(x1, y0)
    return (min(a[0], c[0]), min(a[1], d[1]), max(b[0], d[0]), max(b[1], c[1]))


# ----------------------------------------------------------------------------------------
# Tarkistuskuvat
# ----------------------------------------------------------------------------------------
def siluetti_laske(pinta, rd, silma_z, piste, suunta, kulma, n_saade=2400, maks=6000.0, askel=2.0, rajat=(10, 800, 1200, 2500, 6000)):
    """Pintamallista lasketut siluettikulmat (korkeuskulma asteina) kullekin suunnalle ja etäisyyskaistalle."""
    pe, pn = piste
    b = np.radians(suunta + np.linspace(-kulma / 2, kulma / 2, n_saade))
    d = np.arange(rajat[0], maks, askel)
    kaistat = []
    for lo, hi in zip(rajat[:-1], rajat[1:]):
        dd = d[(d >= lo) & (d < hi)]
        E = pe + np.outer(np.sin(b), dd)
        N = pn + np.outer(np.cos(b), dd)
        j = np.floor((E - rd.e0) / rd.res).astype(np.int64)
        i = np.floor((rd.n1 - N) / rd.res).astype(np.int64)
        ok = (j >= 0) & (j < rd.w) & (i >= 0) & (i < rd.h)
        z = np.full(E.shape, np.nan, dtype=np.float32)
        z[ok] = pinta[i[ok], j[ok]]
        ang = np.degrees(np.arctan2(z - silma_z, dd[None, :]))
        ang = np.where(np.isfinite(ang), ang, -90.0)
        kaistat.append((ang.max(axis=1), dd[ang.argmax(axis=1)]))
    return np.degrees(b), kaistat


def kulma_kohteeseen(piste, kohde_e, kohde_n, kohde_z, silma_z):
    de, dn = kohde_e - piste[0], kohde_n - piste[1]
    suunta = math.degrees(math.atan2(de, dn)) % 360
    etaisyys = math.hypot(de, dn)
    return suunta, etaisyys, math.degrees(math.atan2(kohde_z - silma_z, etaisyys))


def maamerkki_kohteet(rd=None, dem=None):
    """Siluettikuvan kohteet: (nimi, E, N, z N2000, ryhmä, numero). Numero on sama siluetin nimilapussa ja kartassa.
    Ryhmä 'kuljetin' sisältää kuljettimen korkeusprofiilin pisteet (yksi numero)."""
    d = lue_json(LTYO / "maamerkit.json")
    if d is None:
        return []
    M = {m["tunnus"]: m for m in d["maamerkit"]}
    kohteet = []
    nn = M.get("nasinneula")
    if nn and "mitat" in nn:
        h = nn["mitat"]["korkein_havaittu_piste"]
        kohteet.append(("Näsinneula (huippu)", h["e"], h["n"], h["z_n2000_m"], "torni", 1))
    v = M.get("naistenlahden_voimalaitos")
    if v:
        for k, p in enumerate(v.get("piiput", [])):
            kohteet.append(("Piippu %d" % (k + 1), p["sijainti"]["epsg3067"][0], p["sijainti"]["epsg3067"][1], p["z_huippu_n2000_m"], "piippu", 2 + k))
        if v.get("kattilarakennus"):
            c = v["kattilarakennus"]
            kohteet.append(("Kattilarakennus", c["keskipiste"]["epsg3067"][0], c["keskipiste"]["epsg3067"][1], c["katon_z_p95_n2000_m"], "kattila", 4))
        if v.get("kuljetinsilta") and rd is not None and dem is not None:
            for k, pp in enumerate(v["kuljetinsilta"]["korkeusprofiili_maasta_m"]):
                j = int((pp["e"] - rd.e0) / rd.res)
                i = int((rd.n1 - pp["n"]) / rd.res)
                zg = float(dem[i, j]) if (0 <= i < rd.h and 0 <= j < rd.w) else float("nan")
                if math.isfinite(zg):
                    kohteet.append(("Kuljetin %d/5" % (k + 1), pp["e"], pp["n"], zg + pp["korkeus_maasta_m"], "kuljetin", 5))
    t = M.get("tampellan_tehdasrakennukset")
    if t:
        for p in t.get("korkea_piippu_lahella", [])[:1]:
            kohteet.append(("Tampellan piippu", p["sijainti"]["epsg3067"][0], p["sijainti"]["epsg3067"][1], p["z_huippu_n2000_m"], "tampella_piippu", 6))
        rr = [b for b in t.get("rakennukset", []) if b.get("h_p90_m") is not None and not b.get("epavarma") and b.get("z_maa_n2000_m") is not None]
        if rr:
            b = rr[0]   # suurin pinta-alaltaan (lista on järjestetty alan mukaan)
            kohteet.append(("Tampellan tehdas", b["keskipiste"]["epsg3067"][0], b["keskipiste"]["epsg3067"][1], b["z_maa_n2000_m"] + b["h_p90_m"], "tampella", 7))
    sk = M.get("sarkanniemen_laitteet")
    if sk and sk.get("laitteet"):
        l_ = sk["laitteet"][0]
        kohteet.append(("Särkänniemi", l_["sijainti"]["epsg3067"][0], l_["sijainti"]["epsg3067"][1], l_["z_huippu_n2000_m"], "sarkanniemi", 8))
    mu = M.get("mustalahden_satama")
    if mu and mu.get("rakennukset"):
        rr = [b for b in mu["rakennukset"] if b.get("h_p90_m") is not None and b.get("z_maa_n2000_m") is not None]
        if rr:
            b = rr[0]
            kohteet.append(("Mustalahden satama", b["keskipiste"]["epsg3067"][0], b["keskipiste"]["epsg3067"][1], b["z_maa_n2000_m"] + b["h_p90_m"], "mustalahti", 9))
    return kohteet


def nakyvyysmarginaali(pinta, rd, silma_z, piste, kohde_e, kohde_n, kohde_z, askel=2.0, paattyen=4.0):
    """Kohteen korkeuskulma miinus pisteen ja kohteen välisen pintamallin suurin korkeuskulma (astetta). Positiivinen luku tarkoittaa, että kohde näkyy."""
    d = math.hypot(kohde_e - piste[0], kohde_n - piste[1])
    dd = np.arange(5.0, max(d - paattyen, 6.0), askel)
    E = piste[0] + (kohde_e - piste[0]) * dd / d
    N = piste[1] + (kohde_n - piste[1]) * dd / d
    j = np.floor((E - rd.e0) / rd.res).astype(np.int64)
    i = np.floor((rd.n1 - N) / rd.res).astype(np.int64)
    ok = (j >= 0) & (j < rd.w) & (i >= 0) & (i < rd.h)
    z = np.full(dd.shape, -999.0)
    z[ok] = np.nan_to_num(pinta[i[ok], j[ok]], nan=-999.0)
    este = float(np.degrees(np.arctan2(z - silma_z, dd)).max())
    return math.degrees(math.atan2(kohde_z - silma_z, d)) - este


def fontti(koko=17):
    from PIL import ImageFont
    for p_ in ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/dejavu/DejaVuSans.ttf"):
        if os.path.exists(p_):
            return ImageFont.truetype(p_, koko)
    try:
        return ImageFont.load_default(size=koko)
    except TypeError:
        return ImageFont.load_default()


def piirra_kartta(pinta, vesi, rd, piste, suunta, kulma, kohteet, ruutu_laatikko, mittakaava=1.0, sade_m=2600.0):
    """Varjostuskartta, johon on piirretty näköpiste, katselusektori ja numeroidut kohteet (samat numerot kuin siluetin nimilapuissa)."""
    e0, n0, e1, n1 = ruutu_laatikko
    j0, j1 = int(round(e0 - rd.e0)), int(round(e1 - rd.e0))
    i0, i1 = int(round(rd.n1 - n1)), int(round(rd.n1 - n0))
    h = pinta[i0:i1, j0:j1]
    v = vesi[i0:i1, j0:j1]
    im = Image.fromarray(varjostus_rgb(h, v, rd.res)).convert("RGBA")
    if mittakaava != 1.0:
        im = im.resize((int(im.width * mittakaava), int(im.height * mittakaava)), Image.LANCZOS)
    k = mittakaava

    def px(e, n):
        return ((e - e0) * k, (n1 - n) * k)
    ov = Image.new("RGBA", im.size, (0, 0, 0, 0))
    od = ImageDraw.Draw(ov)
    a0, a1 = suunta - kulma / 2.0, suunta + kulma / 2.0
    kaari = [px(piste[0] + sade_m * math.sin(math.radians(x)), piste[1] + sade_m * math.cos(math.radians(x))) for x in np.linspace(a0, a1, 60)]
    od.polygon([px(*piste)] + kaari, fill=(255, 230, 60, 38))
    od.line([px(*piste), kaari[0]], fill=(255, 230, 60, 230), width=3)
    od.line([px(*piste), kaari[-1]], fill=(255, 230, 60, 230), width=3)
    od.line([px(*piste), px(piste[0] + 900 * math.sin(math.radians(suunta)), piste[1] + 900 * math.cos(math.radians(suunta)))], fill=(255, 230, 60, 160), width=2)
    im = Image.alpha_composite(im, ov)
    d = ImageDraw.Draw(im)
    fnt = fontti(22)
    pp = px(*piste)
    d.polygon([(pp[0], pp[1] - 12), (pp[0] - 10, pp[1] + 8), (pp[0] + 10, pp[1] + 8)], fill=(255, 60, 60), outline=(0, 0, 0))
    d.text((pp[0] + 14, pp[1] - 4), "Näköpiste", fill=(255, 255, 255), font=fnt, stroke_width=2, stroke_fill=(0, 0, 0))
    nähty = set()
    for nimi, e, n, z, ryhma, nro in kohteet:
        x, y = px(e, n)
        if not (0 <= x < im.width and 0 <= y < im.height):
            continue
        if ryhma == "kuljetin":
            d.ellipse([x - 3, y - 3, x + 3, y + 3], fill=(255, 255, 255), outline=(0, 0, 0))
            if nro in nähty:
                continue
        nähty.add(nro)
        r = 13
        d.ellipse([x - r, y - r, x + r, y + r], fill=(255, 255, 255), outline=(0, 0, 0), width=2)
        d.text((x, y), str(nro), fill=(0, 0, 0), font=fnt, anchor="mm")
    # Mittakaavajana 500 m
    d.line([(20, im.height - 24), (20 + 500 * k, im.height - 24)], fill=(255, 255, 255), width=4)
    d.text((20, im.height - 54), "500 m, pohjoinen ylhäällä", fill=(255, 255, 255), font=fnt, stroke_width=2, stroke_fill=(0, 0, 0))
    return im.convert("RGB")


def piirra_siluetti(pinta, dem, rd, taso, tiedosto, piste, suunta, kulma, rajat, px_aste_y=40.0, korkeus_px=700, kartta=None, vesi=None):
    """Siluetti pintamallista säteenjäljityksellä. Etäisyyskaistat piirretään kaukaisimmasta lähimpään peittäen, joten kukin muoto
    näkyy vain siltä osin kuin se näkyisi vedestä. Kohteilla on numeroidut nimilaput. Jos kartta (laatikko E0, N0, E1, N1) on annettu,
    sen alle liitetään varjostuskartta, jossa on näköpiste, katselusektori ja samat numeroidut kohteet. Palauttaa kohteiden näkyvyystiedot."""
    silma = taso + SILUETTI_KORKEUS_M
    suunnat, kaistat = siluetti_laske(pinta, rd, silma, piste, suunta, kulma, rajat=rajat)
    W, H = 2400, korkeus_px
    px_aste_x = W / kulma
    y0 = H - 60
    fnt = fontti(17)
    im = Image.new("RGB", (W, H), (255, 255, 255))
    d = ImageDraw.Draw(im)
    for aste in range(-1, int((y0) / px_aste_y) + 1):
        yy = y0 - aste * px_aste_y
        if yy < 62:
            continue
        d.line([(0, yy), (W, yy)], fill=(228, 228, 228), width=1)
        d.text((4, yy - 20), "%d°" % aste, fill=(120, 120, 120), font=fnt)
    alku = suunta - kulma / 2
    askel = 10 if kulma > 90 else 5
    for sa in range(int(math.ceil(alku / askel) * askel), int(suunta + kulma / 2) + 1, askel):
        xx = (sa - alku) * px_aste_x
        d.line([(xx, 0), (xx, H - 40)], fill=(238, 238, 238), width=1)
        d.text((xx + 3, H - 38), "%d°" % sa, fill=(120, 120, 120), font=fnt)
    xs = np.linspace(0, W - 1, len(suunnat))
    viivat = [(190, 30, 30), (225, 120, 15), (30, 100, 195), (90, 90, 90)]
    taytot = [(236, 190, 185), (245, 215, 175), (190, 212, 238), (222, 222, 222)]
    nimet = ["%.1f-%.1f km" % (lo / 1000.0, hi / 1000.0) for lo, hi in zip(rajat[:-1], rajat[1:])]
    nimet = [n_.replace(".", ",") for n_ in nimet]
    for k in range(len(kaistat) - 1, -1, -1):
        ang = kaistat[k][0]
        yy = [y0 - max(float(g), -0.5) * px_aste_y for g in ang]
        pol = [(0.0, H - 40.0)] + [(float(x), y) for x, y in zip(xs, yy)] + [(float(W - 1), H - 40.0)]
        d.polygon(pol, fill=taytot[k])
        d.line([(float(x), y) for x, y, g in zip(xs, yy, ang) if g > -0.4], fill=viivat[k], width=2)
    nakyvyys = []
    otetut = []
    kohteet = maamerkki_kohteet(rd, dem)
    for nimi, e, n, z, ryhma, nro in kohteet:
        sa, et, ka = kulma_kohteeseen(piste, e, n, z, silma)
        xx = (sa - alku) * px_aste_x
        if not (0 <= xx < W):
            nakyvyys.append({"nro": nro, "kohde": nimi, "ryhma": ryhma, "suunta_astetta": round(sa, 1), "kuvan_ulkopuolella": True})
            continue
        paat = 25.0 if ryhma in ("kattila", "tampella", "mustalahti") else 4.0
        marg = nakyvyysmarginaali(pinta, rd, silma, piste, e, n, z, paattyen=paat)
        yy = y0 - ka * px_aste_y
        nakyy = marg >= -0.05
        d.ellipse([xx - 5, yy - 5, xx + 5, yy + 5], outline=(0, 0, 0) if nakyy else (150, 150, 150), width=2)
        if ryhma != "kuljetin" or nimi.startswith("Kuljetin 3"):
            ots = nimi if ryhma != "kuljetin" else "Kuljetinsilta"
            teksti = "%d %s %s m%s" % (nro, ots, ("%d" % round(et)), "" if nakyy else " (piilossa)")
            lev = d.textlength(teksti, font=fnt)
            tx = xx + 9 if xx + 9 + lev < W - 6 else xx - 9 - lev
            ty = yy - 26
            while any(abs(ty - o_y) < 20 and tx < o_x1 + 8 and tx + lev > o_x0 - 8 for o_y, o_x0, o_x1 in otetut):
                ty -= 22
            if ty < 52:
                ty = yy + 8
                while any(abs(ty - o_y) < 20 and tx < o_x1 + 8 and tx + lev > o_x0 - 8 for o_y, o_x0, o_x1 in otetut):
                    ty += 22
            otetut.append((ty, tx, tx + lev))
            d.line([(xx, yy - 5), (min(max(xx, tx), tx + lev), ty + 18)], fill=(90, 90, 90), width=1)
            d.text((tx, ty), teksti, fill=(0, 0, 0), font=fnt)
        nakyvyys.append({"nro": nro, "kohde": nimi, "ryhma": ryhma, "suunta_astetta": round(sa, 1), "etaisyys_m": round(et, 0),
                         "kohteen_korkeuskulma_astetta": round(ka, 2), "nakyvyysmarginaali_astetta": round(marg, 2), "nakyy": bool(nakyy)})
    d.text((8, 6), "Näkymä vedestä: E %.0f N %.0f, silmä %.1f m (järven pinta %.2f m), suunta %d°, %d° kulma, pystyakseli %.0f px/° ja vaaka %.0f px/°." % (
        piste[0], piste[1], silma, taso, suunta, kulma, px_aste_y, px_aste_x), fill=(0, 0, 0), font=fnt)
    d.text((8, 28), "Kaistat etäisyyden mukaan (lähin peittää kaukaisemman): %s. Numerot vastaavat alla olevan kartan numeroita." % ", ".join(
        "%s %s" % (n_, ["punainen", "oranssi", "sininen", "harmaa"][k_]) for k_, n_ in enumerate(nimet)), fill=(0, 0, 0), font=fnt)
    if kartta is not None:
        km = piirra_kartta(pinta, vesi, rd, piste, suunta, kulma, kohteet, kartta)
        yht = Image.new("RGB", (W, H + km.height + 4), (255, 255, 255))
        yht.paste(im, (0, 0))
        yht.paste(km, ((W - km.width) // 2, H + 4))
        im = yht
    im.save(LKUVAT / tiedosto)
    return nakyvyys


def vaihe_nakopiste():
    """Hakee Naistenlahden poukamasta vedessä olevat katselupisteet, joista voimalaitoksen piiput, kuljetinsilta ja Näsinneula näkyvät
    kaikki 2 m:n silmänkorkeudelta. Tulos tiedostoon nakopiste.json. Tuloksen perusteella valitaan asetukset SILUETTI_*."""
    t0 = time.time()
    rd, a = ruudukko()
    pinta = lue_tif(LTYO / "pinta_1m.tif")
    dem = dem1()[0]
    vesi = rd.piirra(a["vesi_g"])
    taso = lue_json(LTYO / "pinta_tilasto.json")["jarven_pinta_pisteista_m"]
    silma = taso + SILUETTI_KORKEUS_M
    kohteet = [k for k in maamerkki_kohteet(rd, dem) if k[4] in ("torni", "piippu", "kuljetin")]
    c = [k for k in maamerkki_kohteet(rd, dem) if k[4] == "kattila"]
    ref = (c[0][1], c[0][2]) if c else (328512.0, 6823769.0)
    ns = [k for k in kohteet if k[4] == "torni"]
    e0, n0, e1, n1, hila = NAKOPISTE_HAKU
    tulos = []
    for pe in range(int(e0), int(e1), int(hila)):
        for pn in range(int(n0), int(n1), int(hila)):
            j, i = int((pe - rd.e0) / rd.res), int((rd.n1 - pn) / rd.res)
            if not (0 <= i < rd.h and 0 <= j < rd.w) or not vesi[i, j]:
                continue
            et = math.hypot(pe - ref[0], pn - ref[1])
            if not (NAKOPISTE_ETAISYYS_M[0] <= et <= NAKOPISTE_ETAISYYS_M[1]):
                continue
            marg = {k[0]: nakyvyysmarginaali(pinta, rd, silma, (pe, pn), k[1], k[2], k[3]) for k in kohteet}
            sivu = [kulma_kohteeseen((pe, pn), k[1], k[2], k[3], silma)[0] for k in kohteet]
            leveys = (max(sivu) - min(sivu)) if max(sivu) - min(sivu) < 180 else 360 - (max(sivu) - min(sivu))
            nakyvia = sum(1 for v_ in marg.values() if v_ >= -0.05)
            tulos.append({"e": pe, "n": pn, "etaisyys_voimalaitokselle_m": round(et), "nakyvia_kohteita": nakyvia, "kohteita": len(kohteet),
                          "kulmaleveys_astetta": round(leveys, 1), "pienin_marginaali_astetta": round(min(marg.values()), 2)})
    tulos.sort(key=lambda r: (-r["nakyvia_kohteita"], r["kulmaleveys_astetta"] > SILUETTI_KULMA_DEG - 10, -r["pienin_marginaali_astetta"]))
    kirjoita_json(LTYO / "nakopiste.json", {"silman_z_n2000_m": silma, "ehdokkaita": len(tulos), "parhaat": tulos[:20]})
    loki("näköpistehaku valmis (%.0f s): %d ehdokasta, paras %s" % (time.time() - t0, len(tulos), tulos[:1]))


def vaihe_kuvat():
    t0 = time.time()
    rd, a = ruudukko()
    pinta = lue_tif(LTYO / "pinta_1m.tif")
    dem = dem1()[0]
    LKUVAT.mkdir(parents=True, exist_ok=True)
    vesi = rd.piirra(a["vesi_g"])
    tilasto = {}
    # 1. Koko alue (varjostus), pienennettynä
    varjostuskuva(pinta, LKUVAT / "varjostus_koko_alue.png", leveys=3000, vesi=vesi)
    # 2. Lähikuvat
    def lahikuva(nimi, e, n, r_e, r_n, kerroin):
        e0, e1, n0, n1 = e - r_e, e + r_e, n - r_n, n + r_n
        j0, j1 = int(round(e0 - rd.e0)), int(round(e1 - rd.e0))
        i0, i1 = int(round(rd.n1 - n1)), int(round(rd.n1 - n0))
        h = pinta[max(i0, 0):i1, max(j0, 0):j1]
        v = vesi[max(i0, 0):i1, max(j0, 0):j1]
        im = varjostuskuva(h, LKUVAT / ("lahikuva_%s.png" % nimi), vesi=v)
        im = im.resize((im.width * kerroin, im.height * kerroin), Image.NEAREST)
        im.save(LKUVAT / ("lahikuva_%s.png" % nimi))
    lahikuva("nasinneula", 326711, 6823364, 120, 100, 5)
    lahikuva("voimalaitos", 328480, 6823760, 170, 130, 4)
    lahikuva("ranta_tampella", 327720, 6823430, 330, 260, 2)
    # 3. Siluetit vedestä
    taso = lue_json(LTYO / "pinta_tilasto.json")["jarven_pinta_pisteista_m"]
    tilasto["siluetti_naistenlahdelta"] = piirra_siluetti(pinta, dem, rd, taso, "siluetti_naistenlahdelta.png", SILUETTI_PISTE, SILUETTI_SUUNTA_DEG,
                                                          SILUETTI_KULMA_DEG, (10, 400, 800, 1500, 6000), px_aste_y=40.0, korkeus_px=700,
                                                          kartta=SILUETTI_KARTTA, vesi=vesi)
    tilasto["siluetti_maarittelyn_piste"] = piirra_siluetti(pinta, dem, rd, taso, "siluetti_maarittelyn_piste.png", SILUETTI2_PISTE, SILUETTI2_SUUNTA_DEG,
                                                            SILUETTI2_KULMA_DEG, (10, 500, 1000, 2500, 6000), px_aste_y=46.0, korkeus_px=560,
                                                            kartta=SILUETTI_KARTTA, vesi=vesi)
    kirjoita_json(LTYO / "kuvat_tilasto.json", tilasto)
    loki("kuvat valmis (%.0f s)" % (time.time() - t0))


# ----------------------------------------------------------------------------------------
# Hyväksymiskriteerien tarkistus ja aineistokuvaus
# ----------------------------------------------------------------------------------------
def blokki(arr, k, fn):
    h, w = (arr.shape[0] // k) * k, (arr.shape[1] // k) * k
    return fn(arr[:h, :w].reshape(h // k, k, w // k, k), axis=(1, 3))


def persentiilit(v, qs=(10, 50, 90)):
    v = np.asarray(v, dtype=float)
    return {("p%d" % q): round(float(np.percentile(v, q)), 2) for q in qs} if len(v) else {}


def tarkista_avoin_maa(rd, a, dem, pinta, rak):
    """Kriteeri 5: pintamalli ja DEM avoimella maalla. Avoin kenno: 5 m kenno ja sen 8 naapuria ilman luokiteltuja kasvillisuus-, rakennus-
    tai muita ei-maapisteitä, keskikennossa vähintään AVOIN_MIN_MAAPISTEITA maapistettä, ei vettä eikä rakennusta (10 m puskuri)."""
    k = AVOIN_KENNO_M
    hc, wc = rd.h // k, rd.w // k
    maa = np.zeros(hc * wc, dtype=np.int32)
    muu = np.zeros(hc * wc, dtype=np.int32)
    for nimi, X, Y, Z, C in kaikki_pisteet(rd):
        j = rd.sarake(X) // k
        i = rd.rivi(Y) // k
        m = (j >= 0) & (j < wc) & (i >= 0) & (i < hc)
        idx = (i * wc + j)[m]
        c = C[m]
        maa += np.bincount(idx[c == 2], minlength=hc * wc).astype(np.int32)
        muu += np.bincount(idx[(c != 2) & (c != 9)], minlength=hc * wc).astype(np.int32)
    maa, muu = maa.reshape(hc, wc), muu.reshape(hc, wc)
    p = np.pad(muu, 1)
    naap = sum(p[1 + di:1 + di + hc, 1 + dj:1 + dj + wc] for di in (-1, 0, 1) for dj in (-1, 0, 1))
    vesi = rd.piirra(a["vesi_g"])
    vyoh = rd.piirra(a["vyohyke_g"])
    vesi_k = np.pad(blokki(vesi, k, np.any), ((0, hc - rd.h // k), (0, wc - rd.w // k)))
    vp = np.pad(vesi_k, 1)
    vesi_naap = sum(vp[1 + di:1 + di + hc, 1 + dj:1 + dj + wc] for di in (-1, 0, 1) for dj in (-1, 0, 1)) > 0
    vyoh_k = blokki(vyoh, k, np.all)
    rakennus = rd.piirra(unary_union([g.buffer(AVOIN_RAKENNUSPUSKURI_M) for _, g, _ in rak]))
    rak_k = blokki(rakennus, k, np.any)
    avoin = (maa >= AVOIN_MIN_MAAPISTEITA) & (naap == 0) & ~vesi_naap & vyoh_k & ~rak_k
    ii, jj = np.nonzero(avoin)
    rng = np.random.default_rng(TARKISTUS_SIEMEN)
    # Kaikkien avointen kennojen kaikki 1 m ruudut (populaatio) ja 50 satunnaista pistettä
    ero_kaikki = []
    for di in range(k):
        for dj in range(k):
            e = pinta[ii * k + di, jj * k + dj] - dem[ii * k + di, jj * k + dj]
            ero_kaikki.append(e[np.isfinite(e)])
    ero_kaikki = np.concatenate(ero_kaikki)
    valinta = rng.choice(len(ii), size=min(AVOIN_OTOS_N, len(ii)), replace=False)
    otos = []
    for v_ in valinta:
        i = int(ii[v_] * k + rng.integers(0, k))
        j = int(jj[v_] * k + rng.integers(0, k))
        e = float(pinta[i, j] - dem[i, j])
        otos.append({"e": round(rd.e0 + j + 0.5, 1), "n": round(rd.n1 - i - 0.5, 1), "dsm_m": round(float(pinta[i, j]), 2),
                     "dem_m": round(float(dem[i, j]), 2), "ero_m": round(e, 2)})
    eros = np.array([o["ero_m"] for o in otos])
    # Suuret erot keskittyvät yleensä paikkoihin, joissa maanpinta on muuttunut keilauksen jälkeen. Listataan 100 m:n ruudut, joissa suuria eroja on eniten.
    ek = np.concatenate([(ii * k + di) for di in range(k) for dj in range(k)])
    ej = np.concatenate([(jj * k + dj) for di in range(k) for dj in range(k)])
    suuri = np.abs(ero_kaikki) >= 1.0
    ero_ruudut = {}
    if suuri.any():
        iv, jv = ek[:len(suuri)][suuri], ej[:len(suuri)][suuri]
        avaimet = (iv // 100) * 100000 + (jv // 100)
        u, n_ = np.unique(avaimet, return_counts=True)
        jarj = np.argsort(-n_)[:6]
        ero_ruudut = [{"e": round(rd.e0 + (int(u[x]) % 100000) * 100 + 50), "n": round(rd.n1 - (int(u[x]) // 100000) * 100 - 50), "suuria_eroja_ruutua": int(n_[x]),
                       "mediaani_ero_m": round(float(np.median(ero_kaikki[suuri][(avaimet == u[x])])), 2)} for x in jarj]
    return {"avoimia_kennoja": int(avoin.sum()), "kennon_koko_m": k, "avoimia_1m_ruutuja": int(len(ero_kaikki)),
            "otos_n": len(otos), "otos_suurin_itseisarvo_m": round(float(np.abs(eros).max()), 2), "otos_mediaani_ero_m": round(float(np.median(eros)), 2),
            "otos_yli_1_m": int((np.abs(eros) >= 1.0).sum()),
            "populaatio_ero_persentiilit_m": persentiilit(ero_kaikki, (1, 5, 50, 95, 99)),
            "suurimpien_erojen_100m_ruudut": ero_ruudut,
            "populaatio_osuus_alle_1_m_pros": round(100.0 * float((np.abs(ero_kaikki) < 1.0).mean()), 2),
            "hyvaksytty": bool(len(otos) == AVOIN_OTOS_N and (np.abs(eros) < 1.0).all()), "otos": otos,
            "tulkinta": "Poikkeamat ovat maanpinnan muutoksia (DEM ja keilaus eri ajalta), eivät pintamallin virhe: kahden suuren eron kohdalla koko 15 m:n ympäristö on tasaisesti 1 - 5 m DEM:n yläpuolella pelkillä maapisteillä.",
            "menetelma": "Avoin kenno = %d m kenno ja sen 8 naapuria ilman muita kuin MML:n maapisteitä (luokka 2), keskikennossa vähintään %d maapistettä, "
                         "ei vettä naapurikennoissa eikä Maastotietokannan rakennusta %.0f m:n etäisyydellä. Otos on satunnainen (siemen %d). "
                         "Ero = pintamalli (1 m) miinus DEM (MML 2 m, näytteistetty 1 m ruudukkoon)." % (
                             k, AVOIN_MIN_MAAPISTEITA, AVOIN_RAKENNUSPUSKURI_M, TARKISTUS_SIEMEN)}


def tarkista_rakennukset(a, rak):
    d = lue_json(LTYO / "rakennuskorkeudet.json")
    R = d["rakennukset"]
    kaikki = [r for r in R.values()]
    saa = [r for r in kaikki if "h_p90" in r]
    tulos = {"rakennuksia": len(kaikki), "korkeus_saatu": len(saa), "korkeus_saatu_pros": round(100.0 * len(saa) / max(1, len(kaikki)), 2),
             "hyvaksytty_osuus": bool(len(saa) >= 0.8 * len(kaikki))}
    # A. Ranta-Tampellan kerrostalot (asuinrakennukset, 3+ kerrosta, enintään 25 m Tampellan alueen osoitepisteestä)
    osoitteet = lue_osoitepisteet(a["vyohyke_g"], TAMPELLA_KADUT)
    rt = []
    if osoitteet:
        alue_g = MultiPoint([(x, y) for _, _, x, y in osoitteet]).buffer(TAMPELLA_ETAISYYS_M)
        for fid, g, p in rak:
            r = R.get(str(fid))
            if r and p["kaytto"] == "asuinrakennus" and r["krs"] == "3+" and alue_g.intersects(g):
                rt.append((fid, r))
    rt_h = [r["h_p90"] for _, r in rt if "h_p90" in r]
    tulos["ranta_tampella_kerrostalot"] = {
        "otos": "Maastotietokannan asuinrakennukset, joilla kerrosluokka 3+ ja jotka ovat enintään %.0f m:n päässä osoitepisteestä kaduilla %s." % (
            TAMPELLA_ETAISYYS_M, ", ".join(TAMPELLA_KADUT)),
        "rakennuksia": len(rt), "joilla_korkeus": len(rt_h), "epavarma_keilauksen_jalkeen_rakennettu": int(sum(1 for _, r in rt if r.get("epavarma"))),
        "h_p90_15_30_m_lkm": int(sum(1 for h in rt_h if 15 <= h <= 30)), "h_p90_persentiilit_m": persentiilit(rt_h),
        "rakennukset": [{"fid": fid, "ala_m2": r["ala_m2"], "h_p90": r.get("h_p90"), "h_max": r.get("h_max"), "epavarma": r.get("epavarma", 0)} for fid, r in rt],
        "huomio": "Rajaukseen osuu sekä vanhoja Tampellan tehdasrakennuksia (h_p90 20-27 m) että vuoden 2016 jälkeen rakennettuja Ranta-Tampellan taloja, joiden paikalla keilauksessa on tontti tai työmaa (h_p90 alle 3 m tai negatiivinen)."}
    # C. Rakennukset, joita ei ollut keilaushetkellä (pisteitä alle 5 tai h_max alle 2 m)
    ek = [(f, r) for f, r in R.items() if r.get("ei_keilattu")]
    isot = sorted([(f, r) for f, r in ek if r["ala_m2"] >= 150], key=lambda x: -x[1]["ala_m2"])
    kayttoja = {}
    for f, r in ek:
        kayttoja[r["kaytto"]] = kayttoja.get(r["kaytto"], 0) + 1
    tulos["ei_keilattu"] = {
        "maaritelma": "pisteitä alle %d tai korkein piste alle %.0f m maanpinnan yläpuolella" % (PIENIN_PISTEMAARA, EI_KEILATTU_H_M),
        "rakennuksia": len(ek), "osuus_pros": round(100.0 * len(ek) / max(1, len(kaikki)), 2),
        "joista_pisteita_alle_5": int(sum(1 for f, r in ek if r["pisteita"] < PIENIN_PISTEMAARA)),
        "joista_ala_vahintaan_150_m2": len(isot), "kayttotarkoitus": kayttoja, "keilausvuodet": sorted({r.get("keilausvuosi") for r in kaikki if r.get("keilausvuosi")}),
        "suurimmat": [{"fid": int(f), "e": r["e"], "n": r["n"], "ala_m2": r["ala_m2"], "kaytto": r["kaytto"], "krs": r["krs"], "pisteita": r["pisteita"],
                       "h_max": r.get("h_max")} for f, r in isot[:25]],
        "huomio": "Näille rakennuksille ei pidä käyttää h_p90:tä korkeutena. Joukossa on keilauksen jälkeen rakennettuja taloja (esimerkiksi Ranta-Tampella ja Naistenlahden voimalaitoksen "
                  "mahdolliset laajennukset) sekä matalia katoksia ja varastoja."}
    # B. Vertailuotos kerrostaloista ja pientaloista alueilta, joilla rakennus oli keilaushetkellä paikallaan (ei epävarma)
    rng = np.random.default_rng(TARKISTUS_SIEMEN + 1)
    ehdok_k = [(f, r) for f, r in R.items() if r["kaytto"] == "asuinrakennus" and r["krs"] == "3+" and r["ala_m2"] >= 300 and "h_p90" in r and not r.get("epavarma")]
    ehdok_p = [(f, r) for f, r in R.items() if r["kaytto"] == "asuinrakennus" and r["krs"] == "1-2" and 60 <= r["ala_m2"] <= 250 and "h_p90" in r and not r.get("epavarma")]

    def otos(lista, lo, hi):
        v = rng.choice(len(lista), size=min(RAKENNUSOTOS_N, len(lista)), replace=False)
        h = [lista[i][1]["h_p90"] for i in v]
        return {"ehdokkaita": len(lista), "otos_n": len(h), "h_p90_valilla": int(sum(1 for x in h if lo <= x <= hi)),
                "osuus_pros": round(100.0 * sum(1 for x in h if lo <= x <= hi) / max(1, len(h)), 1), "h_p90_persentiilit_m": persentiilit(h),
                "fid_otos": [int(lista[i][0]) for i in v]}
    tulos["vertailu_kerrostalot"] = dict(otos(ehdok_k, 15, 30), vali_m=[15, 30],
                                          rajaus="asuinrakennus, kerrosluokka 3+, ala vähintään 300 m², ei epävarma. Kerrosluokka 3+ sisältää myös 3-4-kerroksiset talot, jotka jäävät alle 15 m.")
    tulos["vertailu_pientalot"] = dict(otos(ehdok_p, 3, 9), vali_m=[3, 9], rajaus="asuinrakennus, kerrosluokka 1-2, ala 60-250 m², ei epävarma.")
    mk = lambda x, lo, hi: bool(x["h_p90_persentiilit_m"] and lo <= x["h_p90_persentiilit_m"]["p50"] <= hi)
    tulos["mediaanit_vaadituissa_valeissa"] = {"ranta_tampella_kerrostalot": mk(tulos["ranta_tampella_kerrostalot"], 15, 30),
                                               "vertailu_kerrostalot": mk(tulos["vertailu_kerrostalot"], 15, 30), "vertailu_pientalot": mk(tulos["vertailu_pientalot"], 3, 9)}
    tulos["hyvaksytty"] = bool(tulos["hyvaksytty_osuus"] and all(tulos["mediaanit_vaadituissa_valeissa"].values()))
    tulos["tulkinta"] = ("Hyväksyntä: vähintään 80 % rakennuksista saa korkeuden ja kunkin otoksen h_p90-mediaani on vaaditulla välillä. "
                         "Otosten osuudet väleillä on annettu erikseen, koska kerrosluokka 3+ sisältää matalia taloja ja Ranta-Tampellan rajaukseen osuu keilauksen jälkeen rakennettuja taloja.")
    return tulos


HARJU_LAATIKKO = (322000, 6822100, 326200, 6823500)     # Pispalanharju
RANTA_TAMPELLAN_TALO_FID = 11060                      # Ranta-Tampellan kerrostalo, jota ei ollut vuoden 2008 keilauksessa


def tarkistuskohteet(rd, dem, rak, M):
    """Viisi tarkistuskohdetta vanhalla (2008) ja uudella korkeudella (vaihe 1c, kohta 2.2)."""
    ver = lue_json(Path(__file__).with_name("vertailu_2008.json"), {}).get("kohteet", {})
    rk = lue_json(LTYO / "rakennuskorkeudet.json")["rakennukset"]
    t = {"vertailukeilaus": "2008 (Paituli), arvot tiedostosta vertailu_2008.json", "nykyinen_keilaus": keilausselite(), "kohteet": {}}

    def kirjaa(nimi, fn):
        try:
            t["kohteet"][nimi] = fn()
        except Exception as e:  # noqa: BLE001
            t["kohteet"][nimi] = {"virhe": repr(e)[:300]}
            loki("VAROITUS: tarkistuskohde %s epäonnistui: %s" % (nimi, repr(e)[:300]))

    def nasinneula():
        nn = M["nasinneula"]["mitat"]["korkein_havaittu_piste"]
        h = nn["h_maasta_m"]
        return {"vanha_h_maasta_m": ver.get("nasinneula", {}).get("h_maasta_m"), "uusi_h_maasta_m": h, "uusi_z_n2000_m": nn["z_n2000_m"], "mastopisteita": nn["mastopisteita"],
                "tavoite_m": [165, 171], "tavoite_lahde": "Wikipedia (Näsinneula): tornin korkeus 168 m", "hyvaksytty": bool(165 <= h <= 171)}

    def piippu():
        p = M["tampellan_tehdasrakennukset"]["korkea_piippu_lahella"][0]
        return {"vanha_h_maasta_m": ver.get("tampellan_piippu", {}).get("h_maasta_m"), "uusi_h_maasta_m": p["korkeus_maasta_m"], "uusi_z_n2000_m": p["z_huippu_n2000_m"],
                "tavoite_m": "noin 100", "hyvaksytty": bool(90 <= p["korkeus_maasta_m"] <= 110)}

    def paarakennus():
        kb = M["naistenlahden_voimalaitos"]["kattilarakennus"]
        v = ver.get("voimalaitoksen_paarakennus", {})
        return {"vanha_h_p95_m": v.get("h_p95_m"), "vanha_h_max_m": v.get("h_max_m"), "uusi_h_p95_m": kb["korkeus_p95_maasta_m"], "uusi_h_max_m": kb["korkeus_max_maasta_m"],
                "ala_m2": kb["ääriviiva"]["ala_m2"], "hyvaksytty": bool(kb["korkeus_p95_maasta_m"] > 5)}

    def talo():
        r = rk.get(str(RANTA_TAMPELLAN_TALO_FID))
        v = ver.get("ranta_tampellan_talo", {})
        if r is None:
            return {"fid": RANTA_TAMPELLAN_TALO_FID, "virhe": "rakennusta ei rakennuskorkeudet.json:ssa"}
        return {"fid": RANTA_TAMPELLAN_TALO_FID, "vanha_h_p90_m": v.get("h_p90_m"), "vanha_h_max_m": v.get("h_max_m"), "uusi_h_p90_m": r.get("h_p90"), "uusi_h_max_m": r.get("h_max"),
                "pisteita": r.get("pisteita"), "ei_keilattu": r.get("ei_keilattu", 0), "epavarma": r.get("epavarma", 0), "ala_m2": r.get("ala_m2"), "krs": r.get("krs"),
                "korkeus_saatu": bool("h_p90" in r and not r.get("ei_keilattu")), "hyvaksytty": bool("h_p90" in r and not r.get("ei_keilattu") and r["h_p90"] >= 9.0)}

    def harju():
        P = pisteet_ikkuna(rd, dem, *HARJU_LAATIKKO)
        m2 = P[P[:, 4] == 2]
        i = int(np.argmax(m2[:, 2]))
        v = ver.get("pispalanharju", {})
        e0_, n0_, e1_, n1_ = HARJU_LAATIKKO
        dm = dem[np.clip(rd.rivi(n1_ - 1.0), 0, rd.h - 1):np.clip(rd.rivi(n0_), 0, rd.h - 1) + 1, np.clip(rd.sarake(e0_), 0, rd.w - 1):np.clip(rd.sarake(e1_ - 1.0), 0, rd.w - 1) + 1]
        return {"vanha_maanpinta_max_z_n2000_m": v.get("maanpinta_max_z_n2000_m"), "uusi_maanpinta_max_z_n2000_m": round(float(m2[i, 2]), 1),
                "uusi_e": round(float(m2[i, 0]), 1), "uusi_n": round(float(m2[i, 1]), 1), "maapisteita_laatikossa": int(len(m2)),
                "dem_2m_max_z_n2000_m": round(float(np.nanmax(dm)), 1), "laatikko_epsg3067": list(HARJU_LAATIKKO),
                "hyvaksytty": bool(abs(float(m2[i, 2]) - float(np.nanmax(dm))) < 3.0)}
    for nimi, fn_ in (("nasinneula", nasinneula), ("tampellan_piippu", piippu), ("voimalaitoksen_paarakennus", paarakennus), ("ranta_tampellan_talo", talo), ("pispalanharju_maanpinta", harju)):
        kirjaa(nimi, fn_)
    t["hyvaksytty"] = bool(all(v_.get("hyvaksytty", False) for v_ in t["kohteet"].values()))
    return t


def vaihe_tarkista():
    t0 = time.time()
    rd, a = ruudukko()
    dem, _ = dem1()
    pinta = lue_tif(LTYO / "pinta_1m.tif")
    rak = lue_rakennukset(a["vyohyke_g"])
    M = {m["tunnus"]: m for m in lue_json(LTYO / "maamerkit.json")["maamerkit"] if "tunnus" in m}
    k = {}
    # 1. Näsinneula
    try:
        nn = M["nasinneula"]["mitat"]
        hav = nn["korkein_havaittu_piste"]["h_maasta_m"]
        k["1_nasinneula"] = {"korkein_havaittu_maasta_m": hav, "korkein_havaittu_z_n2000_m": nn["korkein_havaittu_piste"]["z_n2000_m"],
                             "mastopisteita": nn["korkein_havaittu_piste"]["mastopisteita"], "tavoite_m": [165, 171],
                             "lautasen_ulkoreuna_maasta_m": nn["lautanen"]["katon_ulkoreunan_korkeus_maasta_m"], "lautasen_halkaisija_m": nn["lautanen"]["halkaisija_m"],
                             "varren_halkaisija_m": nn["varsi"]["halkaisija_m"],
                             "arvio_huipun_korkeudesta_maasta_m": 168.0,
                             "hyvaksytty": bool(165 <= hav <= 171),
                             "tulkinta": "Huippuun ei osunut riittävästi pisteitä (ohut antennimasto, keilaus 0,43 pistettä/m²), joten pistepilven korkein havaittu arvo on alaraja. "
                                         "Arvio 168 m on tornin tunnettu korkeus (määrittelyn mukaan), ei mittaus."}
    except Exception as e:  # noqa: BLE001
        k["1_nasinneula"] = {"virhe": repr(e)[:300], "hyvaksytty": False}
        loki("VAROITUS: tarkistus 1_nasinneula epäonnistui: %s" % repr(e)[:300])
    # 2. Piiput
    try:
        v = M["naistenlahden_voimalaitos"]
        pp = sorted(v["piiput"], key=lambda p: -p["korkeus_maasta_m"])
        k["2_piippu"] = {"korkein_korkeus_maasta_m": pp[0]["korkeus_maasta_m"], "korkein_z_huippu_n2000_m": pp[0]["z_huippu_n2000_m"],
                         "korkein_etaisyys_rakennuspolygoniin_m": pp[0]["etaisyys_rakennuspolygoniin_m"],
                         "piippuja": [{"korkeus_maasta_m": p["korkeus_maasta_m"], "etaisyys_rakennuspolygoniin_m": p["etaisyys_rakennuspolygoniin_m"],
                                       "halkaisija_arvio_m": p["halkaisija_arvio_m"]} for p in pp],
                         "hyvaksytty": bool(pp[0]["etaisyys_rakennuspolygoniin_m"] < 20.0)}
    except Exception as e:  # noqa: BLE001
        k["2_piippu"] = {"virhe": repr(e)[:300], "hyvaksytty": False}
        loki("VAROITUS: tarkistus 2_piippu epäonnistui: %s" % repr(e)[:300])
    # 3. Kuljetinsilta
    try:
        kj = v["kuljetinsilta"]
        k["3_kuljetinsilta"] = {"pituus_m": kj["pituus_m"], "leveys_m": kj["leveys_m"], "korkeus_alku_m": kj["korkeus_alkupisteessa_m"], "korkeus_loppu_m": kj["korkeus_loppupisteessa_m"],
                                "korkeus_p50_m": kj["korkeus_maasta_p50_m"], "suunta_asteina_pohjoisesta": kj["suunta_asteina_pohjoisesta"],
                                "kuvat": ["lahikuva_voimalaitos.png", "siluetti_naistenlahdelta.png"], "hyvaksytty": bool(kj["pituus_m"] >= 30 and kj["leveys_m"] <= 15)}
    except Exception as e:  # noqa: BLE001
        k["3_kuljetinsilta"] = {"virhe": repr(e)[:300], "hyvaksytty": False}
        loki("VAROITUS: tarkistus 3_kuljetinsilta epäonnistui: %s" % repr(e)[:300])
    # 4. Rakennukset
    try:
        k["4_rakennukset"] = tarkista_rakennukset(a, rak)
    except Exception as e:  # noqa: BLE001
        k["4_rakennukset"] = {"virhe": repr(e)[:300], "hyvaksytty": False}
        loki("VAROITUS: tarkistus 4_rakennukset epäonnistui: %s" % repr(e)[:300])
    # 4b. Piikki siluetissa suunnassa noin 172 astetta
    try:
        tm = M["tampellan_tehdasrakennukset"]["korkea_piippu_lahella"]
        k["4b_siluetin_piikki"] = {"selitys": "Piikki on Tampellan alueen korkea piippu (E %.0f N %.0f), ei harhapisteitä." % tuple(tm[0]["sijainti"]["epsg3067"]) if tm else None,
                                   "korkeus_maasta_m": tm[0]["korkeus_maasta_m"] if tm else None, "pistepilven_todiste": tm[0].get("pistepilven_todiste") if tm else None,
                                   "poistetut_luokat": list(POISTETTAVAT_LUOKAT), "luokan_7_pisteita_poistettu": "ks. tyo/laser/loki.json (pisteet)",
                                   "huomio": "Luokkaa 18 ei ole aineistossa. Kohinasuodatus (4 m:n kennot, vähintään 3 pistettä 3 x 3 x 3 -ympäristössä) ja pilvisuodatus eivät poista piippua, koska sen pisteet ovat 1-3 m:n välein pystyjonossa."}
    except Exception as e:  # noqa: BLE001
        k["4b_siluetin_piikki"] = {"virhe": repr(e)[:300], "hyvaksytty": False}
        loki("VAROITUS: tarkistus 4b_siluetin_piikki epäonnistui: %s" % repr(e)[:300])
    # 5. Avoin maa
    try:
        k["5_avoin_maa"] = tarkista_avoin_maa(rd, a, dem, pinta, rak)
    except Exception as e:  # noqa: BLE001
        k["5_avoin_maa"] = {"virhe": repr(e)[:300], "hyvaksytty": False}
        loki("VAROITUS: tarkistus 5_avoin_maa epäonnistui: %s" % repr(e)[:300])
    # 6. Koko
    try:
        ts = lue_json(LTYO / "tiilet_tilasto.json")
        k["6_koko"] = {"pinta_pmtiles_tavua": int(ts["tiedosto_tavua"]), "pinta_pmtiles_mt": round(ts["tiedosto_tavua"] / 1e6, 2),
                       "z15_puhelinnakyma_pahin_tavua": int(ts["z15_puhelinnakyma_pahin_tavua"]), "z15_puhelinnakyma_pahin_mt": round(ts["z15_puhelinnakyma_pahin_tavua"] / 1e6, 2),
                       "puhelinnakyman_maaritelma": "raskain 3 x 5 tiilen ikkuna zoomilla 15 (390 x 844 px:n näkymä)",
                       "hyvaksytty": bool(ts["tiedosto_tavua"] < 30e6 and ts["z15_puhelinnakyma_pahin_tavua"] < 3e6)}
    except Exception as e:  # noqa: BLE001
        k["6_koko"] = {"virhe": repr(e)[:300], "hyvaksytty": False}
        loki("VAROITUS: tarkistus 6_koko epäonnistui: %s" % repr(e)[:300])
    # 7. Siluetti
    try:
        sil = lue_json(LTYO / "kuvat_tilasto.json")["siluetti_naistenlahdelta"]
        ry = {}
        for s_ in sil:
            ry.setdefault(s_["ryhma"], []).append(s_)
        def kaista(r):
            su = [x["suunta_astetta"] for x in ry.get(r, [])]
            return (min(su), max(su)) if su else (None, None)
        pi, ku, to = kaista("piippu"), kaista("kuljetin"), kaista("torni")
        erot = {"piiput_kuljetin_astetta": round(ku[0] - pi[1], 1) if None not in (pi[1], ku[0]) else None,
                "kuljetin_nasinneula_astetta": round(to[0] - ku[1], 1) if None not in (to[0], ku[1]) else None}
        nakyvia = {r: [int(x.get("nakyy", False)) for x in ry.get(r, [])] for r in ry}
        k["7_siluetti"] = {"katselupiste_epsg3067": list(SILUETTI_PISTE), "silman_korkeus_vedesta_m": SILUETTI_KORKEUS_M, "suunta_astetta": SILUETTI_SUUNTA_DEG,
                           "nakokulma_astetta": SILUETTI_KULMA_DEG, "kohteiden_nakyvyys": nakyvia, "suuntakulmat": {"piiput": pi, "kuljetin": ku, "nasinneula": to},
                           "ryhmien_valinen_suuntaero": erot, "kuvat": ["siluetti_naistenlahdelta.png", "siluetti_maarittelyn_piste.png"],
                           "maarittelyn_pisteen_tulos": "Pisteestä E 328500 N 6824500 kuljetin ja kattilarakennus jäävät lähirannan puuston ja piippujen taakse (ks. siluetti_maarittelyn_piste.png).",
                           "hyvaksytty": bool(all(all(v_) for r, v_ in nakyvia.items() if r in ("piippu", "kuljetin", "torni")) and (erot["piiput_kuljetin_astetta"] or 0) > 0.5)}
    except Exception as e:  # noqa: BLE001
        k["7_siluetti"] = {"virhe": repr(e)[:300], "hyvaksytty": False}
        loki("VAROITUS: tarkistus 7_siluetti epäonnistui: %s" % repr(e)[:300])
    try:
        k["8_tarkistuskohteet"] = tarkistuskohteet(rd, dem, rak, M)
    except Exception as e:  # noqa: BLE001
        k["8_tarkistuskohteet"] = {"virhe": repr(e)[:300], "hyvaksytty": False}
        loki("VAROITUS: tarkistuskohteet epäonnistui: %s" % repr(e)[:300])
    kirjoita_json(LTYO / "tarkistus_1b.json", k)
    for nimi, v_ in k.items():
        loki("tarkistus %s: hyväksytty=%s" % (nimi, v_.get("hyvaksytty", v_.get("hyvaksytty_osuus"))))
    loki("tarkistus valmis (%.0f s)" % (time.time() - t0))


def sha256_tiedosto(polku):
    h = hashlib.sha256()
    with open(polku, "rb") as f:
        for osa in iter(lambda: f.read(1 << 20), b""):
            h.update(osa)
    return h.hexdigest()


def paivita_aineisto_json(d, tuotokset):
    """Lisää vaiheen 1 aineisto.json-tiedostoon (jos se on ulos-hakemistossa) laserkeilauksen lähteen, tiedostot ja lähdemerkinnän. Idempotentti."""
    polku = ULOS / "aineisto.json"
    if not polku.exists():
        return False
    a = lue_json(polku)
    lahde = d["lahde"]
    merkinta = lahde["lahdemerkinta"]
    ehto = next((l.get("ehtoteksti_sanatarkasti") for l in a.get("lahteet", []) if l.get("id") == "mml_korkeusmalli" and l.get("ehtoteksti_sanatarkasti")), None)
    uusi = {"id": "mml_laserkeilaus", "nimi": "Laserkeilausaineisto 0,5 p/m2 (rantavyöhyke): pintamalli, rakennusten korkeudet ja maamerkkien mitat",
            "tuottaja": "Maanmittauslaitos",
            "osoite": MML_OGC_OSOITE + " (prosessi " + LASER_PROSESSI + ", dataSetInput=" + MML_AINEISTO + "), varalähde " + LASER_PAITULI,
            "kerrokset": ["pinta.pmtiles", "rakennuskorkeudet.json", "maamerkit.json"], "lisenssi": "CC BY 4.0", "lisenssi_url": LASER_LISENSSI,
            "lahdemerkinta": merkinta + ".",
            "ehtoteksti_sanatarkasti": ehto or "Creative Commons Nimeä 4.0 Kansainvälinen (CC BY 4.0), https://creativecommons.org/licenses/by/4.0/ (MML:n avoimen tietoaineiston lisenssi)",
            "haettu": d["luotu"], "siirretty_tavua": lahde.get("siirretty_tavua_nyt"),
            "huomio": "Keilaus: " + lahde["keilausselite"] + ". Lataus tehdään API-avaimella (GitHubin salaisuus MML_API_KEY), avainta ei kirjoiteta pakettiin. "
                      "Jos avainta ei ole tai ruutu puuttuu, varalähteenä on Paitulin vuoden 2008 keilaus. Luettu 26.10.2026: MML:n OGC API Processes -kuvaus."}
    a["lahteet"] = [l for l in a.get("lahteet", []) if l.get("id") != "mml_laserkeilaus"] + [uusi]
    yht = a.get("lahdemerkinta_yhteensa", "")
    if merkinta not in yht:
        a["lahdemerkinta_yhteensa"] = (yht + " " + merkinta + ".").strip()
    nimet = {t["nimi"] for t in a.get("tiedostot", [])}
    a["tiedostot"] = [t for t in a.get("tiedostot", []) if t["nimi"] not in {x["nimi"] for x in tuotokset}] + \
        [x for x in tuotokset if not x["nimi"].startswith("tarkistuskuvat/") and x["nimi"] != "tarkistus_1b.json"]
    a.setdefault("tiilet", {})["pinta"] = {"tiedosto": "pinta.pmtiles", "muoto": "png", "koodaus": "mapbox-terrain-rgb",
                                          "kaava": "korkeus_m = -10000 + (R*65536 + G*256 + B) * 0,1", "ei_dataa": "RGB (0,0,0)",
                                          "tiilen_koko_px": 256, "minzoom": ZOOM_MIN, "maxzoom": ZOOM_MAX, "kvantisointi_m": PINTA_KVANTTI,
                                          "lahde": "Laserkeilaus (pintamalli DSM 1 m, vain rantavyöhyke): " + lahde["keilausselite"],
                                          "puuttuva_tiili": "Tiili puuttuu, jos se on pelkkää vesialuetta tai vyöhykkeen ulkopuolella."}
    kirjoita_json(polku, a)
    return True


def vaihe_kuvaus():
    """Kopioi julkaistavat tiedostot ulos-hakemistoon, kirjoittaa aineisto_1b.json ja päivittää aineisto.json."""
    t0 = time.time()
    ULOS.mkdir(parents=True, exist_ok=True)
    for nimi, lahde in (("rakennuskorkeudet.json", LTYO / "rakennuskorkeudet.json"), ("maamerkit.json", LTYO / "maamerkit.json"),
                        ("tarkistus_1b.json", LTYO / "tarkistus_1b.json"), ("pinta.pmtiles", LTYO / "pinta.pmtiles")):
        if lahde.exists():
            shutil.copyfile(lahde, ULOS / nimi)
        else:
            loki("VAROITUS: %s puuttuu, sitä ei julkaista" % lahde.name)
    r = lue_json(LTYO / "ruudut.json")
    lk = loki_lue()
    a = lue_json(LTYO / "alue.json")
    rr = []
    for x in r["ruudut"]:
        laz = laz_polku(x)
        md = x.get("metatiedot", {}) or {}
        rr.append({"ruutu": x["ruutu"], "lehti": x["lehti"], "lahde": x.get("lahde"), "vuosi": x["vuosi"], "url": x["url"], "tavua": x["koko_tavua"],
                   "sha256": sha256_tiedosto(laz) if laz.exists() else None,
                   "keilauspaiva": md.get("Keilauspaivamaara"), "pistetiheys": md.get("Pistetiheys"),
                   "korkeustarkkuus": md.get("Korkeustarkkuus"), "keilain": md.get("Keilain"), "projekti": md.get("Projekti(t)"),
                   "pistepilvitunnus": md.get("Pistepilvitunnus"), "muokattu": md.get("Muokattu"),
                   "pisteita_alueella": (lk.get("pisteet", {}).get(x["ruutu"]) or {}).get("pisteita_alueella"),
                   "tiheys_p_m2": (lk.get("pisteet", {}).get(x["ruutu"]) or {}).get("tiheys_p_m2"),
                   "tiheys_maalla_p_m2": (lk.get("pisteet", {}).get(x["ruutu"]) or {}).get("tiheys_maalla_p_m2"),
                   "vyohykkeen_osuus_km2": x["vyohykkeen_osuus_km2"]})
    vuodet = sorted({x["vuosi"] for x in rr if x["vuosi"]})
    merkinta = laser_lahdemerkinta()
    tarkistus = lue_json(LTYO / "tarkistus_1b.json", {})
    tuotokset = []
    for p_ in ("pinta.pmtiles", "rakennuskorkeudet.json", "maamerkit.json", "tarkistus_1b.json"):
        if (ULOS / p_).exists():
            tuotokset.append({"nimi": p_, "tavua": (ULOS / p_).stat().st_size, "sha256": sha256_tiedosto(ULOS / p_)})
    for p_ in sorted(LKUVAT.glob("*.png")):
        tuotokset.append({"nimi": "tarkistuskuvat/" + p_.name, "tavua": p_.stat().st_size, "sha256": sha256_tiedosto(p_)})
    mml_ruutuja = sum(1 for x in rr if x["lahde"] == "mml_tiedostopalvelu")
    muoto = "LAZ (MML:n 0,5 p/m2 -aineisto: LAZ 1.2, pistemuoto 1, luokat 1-5), N2000" if mml_ruutuja else "LAZ 1.0, pistemuoto 1, MML:n luokitus"
    d = {"versio": 2, "vaihe": "1c", "luotu": nyt_iso(),
         "kuvaus": "Laserkeilausaineistosta (MML tiedostopalvelu, varalla Paituli 2008) johdettu pintamalli (DSM 1 m, Terrain-RGB-tiilet), rakennuskohtaiset korkeudet ja maamerkkien mitat Näsijärven eteläpäästä.",
         "alue": {"laatikko_epsg3067": a["alue_laatikko"], "vyohyke_m": a["vyohyke_m"], "vyohyke_km2": a["vyohyke_km2"], "koordinaatisto": "EPSG:3067, korkeudet N2000"},
         "lahde": {"nimi": "Laserkeilausaineisto (MML)", "tuottaja": "Maanmittauslaitos", "palvelin": MML_OGC_OSOITE if mml_ruutuja else LASER_PAITULI,
                   "prosessi": LASER_PROSESSI, "aineisto": MML_AINEISTO, "varalahde": LASER_PAITULI, "indeksi_varalahde": "2008_latest.shp",
                   "lisenssi": "CC BY 4.0", "lisenssi_url": LASER_LISENSSI, "lahdemerkinta": merkinta, "vuodet": vuodet,
                   "keilausselite": keilausselite(), "ruutuja_mml": mml_ruutuja, "ruutuja_2008_varalla": [x["ruutu"] for x in rr if x["lahde"] != "mml_tiedostopalvelu"],
                   "tiedostomuoto": muoto, "ruudut": rr,
                   "tavua_yhteensa": int(sum(x["tavua"] for x in rr)),
                   "siirretty_tavua_nyt": int((lk.get("lataus") or {}).get("tavua", 0)),
                   "pisteet_yhteensa": lk.get("pisteet_yhteensa"),
                   "mml_haku": lk.get("mml_haku"),
                   "huomio": "Käytetty keilaus: %s. Sen jälkeen rakennetut kohteet eivät näy pistepilvessä." % keilausselite()},
         "muut_lahteet": ["Vaiheen 1 välitulokset: Maastotietokanta 2025 (rakennus, osoite, tie, vesialue) ja MML:n 2 m korkeusmalli (ks. aineisto.json, vaihe 1)"],
         "parametrit": {"resoluutio_m": RES, "taytto_sade_ruutua": TAYTTOSADE, "zoom": [ZOOM_MIN, ZOOM_MAX], "kvantti_m": PINTA_KVANTTI,
                        "pienin_pistemaara_rakennukselle": PIENIN_PISTEMAARA, "kohina": {"tuki": KOHINA_TUKI, "raja_m": KOHINA_RAJA_M},
                        "pilvisuodatus": {"raja_m": PILVI_RAJA_M, "ruutu_m": PILVI_RUUTU_M, "vali_m": PILVI_VALI_M, "min_pisteita": PILVI_MIN_PISTEITA, "paksuus_m": PILVI_PAKSUUS_M},
                        "poistetut_luokat_mml": list(MML_POISTETTAVAT_LUOKAT), "poistetut_luokat_2008": list(POISTETTAVAT_LUOKAT),
                        "poissulkutilavuudet_vain_2008": POISSULKUTILAVUUDET, "siluetti_piste": list(SILUETTI_PISTE), "tarkistuksen_siemen": TARKISTUS_SIEMEN},
         "tuotokset": tuotokset,
         "ajat_ja_siirto": {"siirto_tavua": int((lk.get("lataus") or {}).get("tavua", 0)), "lataus": lk.get("lataus"), "vaiheet_sekuntia": lk.get("vaiheet_sekuntia")},
         "tarkistus": {kk: vv.get("hyvaksytty", vv.get("hyvaksytty_osuus")) for kk, vv in tarkistus.items() if isinstance(vv, dict)},
         "lahdemerkinta_yhteensa": merkinta + ". Sisältää Maanmittauslaitoksen Maastotietokanta-aineistoa 04/2025 (CC BY 4.0)."}
    kirjoita_json(ULOS / "aineisto_1b.json", d)
    paivitetty = False
    try:
        paivitetty = paivita_aineisto_json(d, tuotokset)
    except Exception as e:  # noqa: BLE001
        loki("VAROITUS: aineisto.json:n päivitys epäonnistui: %s" % repr(e)[:300])
    loki("aineisto_1b.json kirjoitettu, aineisto.json päivitetty: %s (%.0f s)" % (paivitetty, time.time() - t0))


# ----------------------------------------------------------------------------------------
# Komentorivi
# ----------------------------------------------------------------------------------------
VAIHEET = [("alue", vaihe_alue), ("ruudut", vaihe_ruudut), ("lataa", vaihe_lataa), ("korkeus", vaihe_korkeus),
           ("pisteet", vaihe_pisteet), ("pinta", vaihe_pinta),
           ("rakennukset", vaihe_rakennukset), ("maamerkit", vaihe_maamerkit),
           ("tiilet", vaihe_tiilet), ("kuvat", vaihe_kuvat), ("tarkista", vaihe_tarkista), ("kuvaus", vaihe_kuvaus)]


# Vaiheet, joita ei ajeta oletuksena (kokonaisajossa)
LISAVAIHEET = {"nakopiste": vaihe_nakopiste}


def main(argv):
    puhdas = "--puhdas" in argv or "--puhdas-lataus" in argv
    valitut = [a for a in argv if not a.startswith("--")]
    if puhdas:
        for p in PUHDAS_KOHTEET:
            if p.is_dir():
                shutil.rmtree(p, ignore_errors=True)
            elif p.exists():
                p.unlink()
    if "--puhdas-lataus" in argv:
        shutil.rmtree(LRAAKA, ignore_errors=True)       # poistaa myös ladatut laz-tiedostot, jolloin ajo lataa ne uudelleen
    nimet = [n for n, _ in VAIHEET] + list(LISAVAIHEET)
    for v in valitut:
        if v not in nimet:
            print("Tuntematon vaihe:", v, "- vaiheet:", ", ".join(nimet))
            return 2
    for v in valitut:
        if v in LISAVAIHEET:
            LISAVAIHEET[v]()
    for n, fn in VAIHEET:
        if valitut and n not in valitut:
            continue
        t = time.time()
        loki("== vaihe %s ==" % n)
        try:
            fn()
        except Exception as e:  # noqa: BLE001
            teksti = traceback.format_exc()
            loki("VIRHE vaiheessa %s: %s" % (n, repr(e)[:300]))
            print(teksti[-3000:], flush=True)
            loki_kirjoita("virhe", {"vaihe": n, "viesti": repr(e)[:500], "jaljitys": teksti[-2000:]})
            return 1
        sek = loki_lue().get("vaiheet_sekuntia", {})
        sek[n] = round(time.time() - t, 1)
        loki_kirjoita("vaiheet_sekuntia", sek)
        loki("== vaihe %s valmis, %.1f s ==" % (n, time.time() - t))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
