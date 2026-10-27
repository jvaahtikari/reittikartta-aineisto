#!/usr/bin/env python3
"""Vaihe 1d: kiinnitettyjen veneiden paikat Maanmittauslaitoksen ortokuvasta (Paituli).

Ajo:  python3 veneet.py                       kaikki satamat, kirjoittaa ulos/veneet.json ja päivittää ulos/aineisto.json
      python3 veneet.py Naistenlahti Mustalahti   vain nimetyt satamat (väliajo, ei päivitä aineisto.json:ia)
      python3 veneet.py --ei-kuvia            ohittaa tarkistuskuvat

Ympäristömuuttuja VENEET_KOPIO: hakemisto, johon veneet.json kopioidaan lisäksi (paikallinen ajo).

Menetelmä (selitettävä, ei koneoppimista):
  1. Paitulin ortokuvaindeksistä (ortho_all.shp) haetaan satamat kattavat 6 x 6 km:n lehdet ja niiden kuvausvuodet. Uusin vuosi, joka on
     kesäkuva (vihreän osuus vähintään 4 %), valitaan. Kevään lehdetön kuva hylätään, koska veneet eivät ole vielä vedessä.
  2. Tunnistusalue: Maastotietokannan järvipolygonin vesialue, jolla on laituri 0-60 m päässä tai joka on 0-150 m päässä rannasta
     satamakohteen ympärillä (poijukentät ja kirjaamattomat laiturit). Rakennettu rantaviiva (aallonmurtajat, kaiteet) jää vesialueen ulkopuolelle.
  3. Veden taustasävy lasketaan liukuvalla mediaanilla (26 m:n ikkuna). Pikseli on ehdokas, jos kirkkaus poikkeaa taustasta yli kynnyksen
     (vaaleat ja tummat erikseen). Laiturit (vesieste-kerros, puskuri 1,5 m) ja kirjatut vesikivet rajataan pois.
  4. Morfologinen avaus ja sulku, yhtenäiset alueet, pääakseli (PCA). Kohde pidetään, jos pituus 3-16 m, leveys 1,3-5 m ja suhde 1,3-5.
     Liian suuret alueet jaetaan etäisyysmuunnoksen huippujen mukaan (yhteen kiinni olevat veneet).
  5. Keula: ensisijaisesti muodosta (keula on kapeampi, jolloin pinta-alan painopiste on perää kohti), toissijaisesti laiturin suunta
     (keula laituria kohti), muuten oletus pienellä varmuudella.
  6. Luokka pituudesta ja muodosta (soutu, pieni, keski, purje). Varmuus yhdistää muodon täyttöasteen, koon uskottavuuden ja kontrastin.
"""
import hashlib
import json
import math
import os
import shutil
import sys
import time
import traceback
from pathlib import Path

from asetukset import *  # noqa: F401,F403

import numpy as np  # noqa: E402
from osgeo import gdal, ogr  # noqa: E402
from PIL import Image, ImageDraw, ImageFont  # noqa: E402
from scipy import ndimage as ndi  # noqa: E402
from shapely import wkb as swkb  # noqa: E402
from shapely.geometry import Point, Polygon, box  # noqa: E402
from shapely.ops import unary_union  # noqa: E402

gdal.UseExceptions()
ogr.UseExceptions()

VTYO = TYO / "veneet"
OTYO = TYO / "orto"
JP2 = OTYO / "jp2"
INDEKSI = OTYO / "indeksi"
RAJATTU = TYO / "rajattu.gpkg"
SHOTS = JUURI / "shots"
KUVAT = ULOS / "tarkistuskuvat"

ORTO_POLKU = "mml/orto/normal_color_3067/"
ORTO_INDEKSI = PAITULI + ORTO_POLKU + "ortho_all"           # + .shp .shx .dbf .prj .cpg
ORTO_LISENSSI = "CC BY 4.0"

RES = 0.5                      # ortokuvan pikselikoko (m)

# ----------------------------------------------------------------------------------------
# Parametrit (lopulliset arvot kirjataan veneet.json-tiedostoon ja raporttiin)
# ----------------------------------------------------------------------------------------
PARAM = {
    "kesakuva_min_vihrea_osuus": 0.04,   # osuus pikseleistä, joissa G > R + 6 ja G > B + 6 (kevään lehdetön kuva: 0,001, kesäkuva: 0,08-0,30)
    "laituri_vyohyke_m": 60,             # tunnistusalue laitureiden ympärillä
    "ranta_vyohyke_m": 150,              # poijukenttä: vesialue enintään näin kaukana rannasta satamakohteen ympärillä
    "laituri_puskuri_m": 1.5,            # laituriviivan poissulku
    "kivi_puskuri_m": 3.0,               # kirjatun pinnassa olevan vesikiven poissulku
    "silta_puskuri_m": 11.0,             # siltojen (tie, taso >= 1) poissulku, leveät siltakannet jakoineen ja kevyen liikenteen väylineen ulottuvat yli 7 m keskiviivasta
    "tausta_ikkuna_m": 26,               # taustan liukuva mediaani
    "kynnys_vaalea": 45,                 # kirkkauden ylitys taustaan nähden (0-255)
    "kynnys_tumma": 22,                  # kirkkauden alitus taustaan nähden
    "avaus_px": 3,                       # morfologinen avaus (neliö, px)
    "sulku_px": 3,                       # morfologinen sulku (neliö, px)
    "pituus_m": (3.0, 16.0),
    "leveys_m": (1.3, 5.0),
    "suhde": (1.3, 5.0),
    "pinta_ala_max_m2": 60.0,            # tätä suuremmat alueet yritetään jakaa
    "alus_leveys_max_m": 7.0,            # yli 16 m:n pitkänomainen alue, jonka leveys on enintään tämä ja ala enintään alus_ala_max_m2, on iso alus eikä vene
    "alus_ala_max_m2": 160.0,
    "leveys_salli_m": 6.0,               # jakamaton alue hyväksytään yhtenä isona veneenä, jos leveys on enintään tämä ja ala enintään pinta_ala_salli_m2
    "pinta_ala_salli_m2": 80.0,
    "jako_huippu_etaisyys_m": 1.2,       # etäisyysmuunnoksen huippujen vähimmäisetäisyys varajaossa
    "jako_askel": 12,                    # kynnyksen korotus portain jaossa (kirkkausasteikko 0-255)
    "vesi_kirkkaus_max": 90,             # vedenkaltainen pikseli (vesi ja sen varjot): kirkkaus enintään tämä
    "tumma_ranta_m": 6.0,                # tummat havainnot (muurien varjot) tätä lähempänä rantaa hylätään
    "vesiosuus_min": 0.25,               # kohteen ympärillä on oltava vähintään tämä osuus vettä, muuten kyse on sillasta tai rakenteesta
    "paallekkain_max": 0.50,             # suorakulmioiden päällekkäisyys (osuus pienemmästä), jonka yli heikompi kohde poistetaan
    "jako_saumasyvyys": 25,              # tumman sauman vähimmäissyvyys (musta huippuhattu) jaon toisessa vaiheessa
    "jako_min_px": 14,                   # jaon osan vähimmäiskoko siemenenä (px, 0,25 m2 per px)
    "ponttoni_sinisyys_min": 35.0,       # kapea (enintään ponttoni_leveys_max_m), selvästi sinertävä kohde (sinisen ja punaisen keskiarvon ero) on ponttoonilaiturin sormi, ei vene (veneet: alle 29)
    "ponttoni_leveys_max_m": 2.2,
    "keula_vinouma_min": 0.04,           # painopisteen siirtymä pituudesta, jonka yli muoto ratkaisee keulan
    "laituri_vaikutus_m": 12.0,          # laituri vaikuttaa keulan suuntaan enintään tältä etäisyydeltä
}

# Satamat: nimi, keskipiste (EPSG:3067), säde poijukenttävyöhykkeelle (m), lähin paikannimi (MML Paikannimet 2020)
SATAMAT = [
    {"nimi": "Naistenlahti", "e": 328240, "n": 6823793, "r": 420, "paikannimi": "Naistenlahti (lahti, 40 m)"},
    {"nimi": "Mustalahti", "e": 326932, "n": 6823418, "r": 520, "paikannimi": "Mustalahti (lahti, 141 m), Särkänniemi"},
    {"nimi": "Santalahti", "e": 325065, "n": 6823803, "r": 380, "paikannimi": "Santalahti (kylä, 317 m)"},
    {"nimi": "Jänissaari", "e": 325451, "n": 6826459, "r": 380, "paikannimi": "Jänissaari (niemi, 134 m), Lentävänniemi"},
    {"nimi": "Perkiönlahti", "e": 323531, "n": 6826586, "r": 300, "paikannimi": "Perkiönlahti (lahti, 159 m)"},
    {"nimi": "Rauhaniemi", "e": 329500, "n": 6824380, "r": 520, "paikannimi": "Rauhaniemi (niemi, 383 m), Kaupinojanlahti"},
    {"nimi": "Aitolahti", "e": 337193, "n": 6824636, "r": 350, "paikannimi": "Olkahistenlahti (lahti, 65 m), Aitolahti"},
    {"nimi": "Teisko", "e": 323949, "n": 6836573, "r": 400, "paikannimi": "Pimeäsalmi (lahti, 199 m)"},
]

# Käsin todetut poissulkualueet: rakenteita, jotka ortokuvassa näyttävät veneiltä mutta eivät ole veneitä eikä niitä ole Maastotietokannan
# laiturikerroksessa (laituriviivat ovat kapeita, eivätkä ne kata leveitä kansia). Jokainen alue on tarkistettu ortokuvasta silmämääräisesti.
POISSULKUALUEET = [
    {"satama": "Mustalahti", "nimi": "Särkänniemen rantaterassi", "e0": 326905, "n0": 6823400, "e1": 326950, "n1": 6823432,
     "syy": "leveä terassikansi aurinkovarjoineen ja pöytineen rakennuksen edessä (6 väärää havaintoa)"},
    {"satama": "Mustalahti", "nimi": "Rautatiesillan ristikko", "e0": 327350, "n0": 6823380, "e1": 327368, "n1": 6823392,
     "syy": "rautatiesillan ristikkorakenne, joka näyttää kapealta vaalealta kohteelta (1 väärä havainto)"},
]


# ----------------------------------------------------------------------------------------
# Ortokuvaindeksi ja kuvien valinta
# ----------------------------------------------------------------------------------------
def hae_indeksi():
    INDEKSI.mkdir(parents=True, exist_ok=True)
    for pate in ("shp", "shx", "dbf", "prj", "cpg"):
        hae(ORTO_INDEKSI + "." + pate, INDEKSI / ("ortho_all." + pate), kerro=False)
    return INDEKSI / "ortho_all.shp"


def indeksin_lehdet(shp, geom):
    """Kaikki indeksin lehdet (kaikki vuodet), jotka leikkaavat geometrian: [{lehti, vuosi, sarja, path}]."""
    ds = ogr.Open(str(shp))
    k = ds.GetLayer(0)
    k.SetSpatialFilterRect(*geom.bounds)
    ulos = []
    for ft in k:
        g = swkb.loads(bytes(ft.GetGeometryRef().ExportToWkb()))
        if not g.intersects(geom):
            continue
        nimi = ft.GetField("label")               # esim. "M4212G (2023)"
        lehti, vuosi = nimi.split(" (")[0], int(nimi.split("(")[1].rstrip(")"))
        polku = ft.GetField("path")               # mml/orto/normal_color_3067/smk_v_15000_50/2023/M42/02m/1/M4212G.jp2
        sarja = polku.split("/")[3]
        ulos.append({"lehti": lehti, "vuosi": vuosi, "sarja": sarja, "path": polku, "bounds": list(g.bounds)})
    return ulos


def vihrea_osuus(polku):
    """Osuus pikseleistä, joissa vihreä ylittää punaisen ja sinisen (kuvan 1/8-esikatselusta). Lehdetön kevätkuva on lähes 0."""
    ds = gdal.Open(str(polku))
    a = [ds.GetRasterBand(i).ReadAsArray(buf_xsize=1500, buf_ysize=1500).astype(np.int16) for i in (1, 2, 3)]
    return float(((a[1] > a[0] + 6) & (a[1] > a[2] + 6)).mean())


def valitse_ortokuvat(lehdet_ja_vuodet, loki_):
    """Valitsee kullekin lehdelle uusimman kesäkuvan. Palauttaa {lehti: tiedot} ja kirjaa hylätyt vuodet."""
    valitut = {}
    # kevätkuvien hylkäykset muistetaan (JP2/hylatyt.json, välimuistissa jp2-hakemiston mukana), ettei satojen megatavujen kuvia ladata joka ajolla uudelleen
    hylatyt_tied = JP2 / "hylatyt.json"
    muistissa = lue_json(hylatyt_tied) if hylatyt_tied.exists() else {}
    for lehti, ehdokkaat in sorted(lehdet_ja_vuodet.items()):
        ehdokkaat = sorted({(d["vuosi"], d["sarja"]): d for d in ehdokkaat}.values(), key=lambda d: (-d["vuosi"], d["sarja"]))
        uusin = ehdokkaat[0]
        hylatyt = []
        for e in ehdokkaat:
            kohde = JP2 / ("%s_%d_%s.jp2" % (lehti, e["vuosi"], e["sarja"]))
            avain = "%s_%d_%s" % (lehti, e["vuosi"], e["sarja"])
            if avain in muistissa and muistissa[avain] < PARAM["kesakuva_min_vihrea_osuus"]:
                hylatyt.append({"vuosi": e["vuosi"], "sarja": e["sarja"], "vihrea_osuus": muistissa[avain],
                                "syy": "kevätkuva (lehdetön, vihreän osuus alle %.2f), aiemmasta ajosta muistettu" % PARAM["kesakuva_min_vihrea_osuus"]})
                continue
            try:
                n, dt, uusi = hae(PAITULI + e["path"], kohde, kerro=False)
            except Exception as ex:  # noqa: BLE001
                hylatyt.append({"vuosi": e["vuosi"], "sarja": e["sarja"], "syy": "lataus epäonnistui: " + repr(ex)[:120]})
                continue
            vo = vihrea_osuus(kohde)
            muistissa[avain] = round(vo, 4)
            kirjoita_json(hylatyt_tied, muistissa)
            if vo < PARAM["kesakuva_min_vihrea_osuus"]:
                hylatyt.append({"vuosi": e["vuosi"], "sarja": e["sarja"], "vihrea_osuus": round(vo, 4),
                                "syy": "kevätkuva (lehdetön, vihreän osuus alle %.2f)" % PARAM["kesakuva_min_vihrea_osuus"]})
                kohde.unlink(missing_ok=True)
                continue
            valitut[lehti] = {"lehti": lehti, "vuosi": e["vuosi"], "sarja": e["sarja"], "paiva": None,
                              "tiedosto": kohde.name, "polku_paitulissa": e["path"], "tavua": kohde.stat().st_size,
                              "sha256": sha256(kohde), "vihrea_osuus": round(vo, 4),
                              "uusin_indeksissa": {"vuosi": uusin["vuosi"], "sarja": uusin["sarja"]},
                              "hylatyt_uudemmat": hylatyt, "ladattu_nyt": bool(uusi),
                              "indeksin_vuodet": sorted({d["vuosi"] for d in ehdokkaat})}
            loki("ortokuva %s: valittu %d (%s), vihreää %.3f, hylätty uudempia %d" % (lehti, e["vuosi"], e["sarja"], vo, len(hylatyt)))
            break
        else:
            loki("VAROITUS: lehdelle %s ei löytynyt kesäkuvaa" % lehti)
    return valitut


def sha256(polku):
    h = hashlib.sha256()
    with open(polku, "rb") as f:
        for osa in iter(lambda: f.read(1 << 20), b""):
            h.update(osa)
    return h.hexdigest()


# ----------------------------------------------------------------------------------------
# Vektoriaineisto (tyo/rajattu.gpkg)
# ----------------------------------------------------------------------------------------
def lue_geometriat(kerros, bbox, where=None):
    ds = ogr.Open(str(RAJATTU))
    k = ds.GetLayerByName(kerros)
    if where:
        k.SetAttributeFilter(where)
    k.SetSpatialFilterRect(*bbox)
    nimet = [k.GetLayerDefn().GetFieldDefn(i).GetName() for i in range(k.GetLayerDefn().GetFieldCount())]
    ulos = []
    for ft in k:
        g = ft.GetGeometryRef()
        if g is None:
            continue
        ulos.append((swkb.loads(bytes(g.ExportToWkb())), {n: ft.GetField(i) for i, n in enumerate(nimet)}))
    return ulos


def vesialue(bbox):
    return unary_union([g for g, _ in lue_geometriat("maastokuvio", bbox, "luokka='jarvi'")]).intersection(box(*bbox))


def rantaviiva(bbox):
    """Rantaviiva tekee vesialueen oikean reunan (ei laatikon reunaa)."""
    gs = [g.boundary for g, _ in lue_geometriat("maastokuvio", bbox, "luokka='jarvi'")]
    return unary_union(gs).intersection(box(*bbox))


# ----------------------------------------------------------------------------------------
# Rasterointi ja kuva-apufunktiot
# ----------------------------------------------------------------------------------------
class Ikkuna:
    """Ortokuvan ikkuna (e0, n1 = vasen yläkulma) ja koordinaattimuunnokset."""

    def __init__(self, e0, n1, w, h):
        self.e0, self.n1, self.w, self.h = e0, n1, w, h

    def px(self, x, y):
        return ((x - self.e0) / RES, (self.n1 - y) / RES)

    def maailma(self, c, r):
        return (self.e0 + (c + 0.5) * RES, self.n1 - (r + 0.5) * RES)

    def rasteroi(self, geom):
        """Shapely-geometria (alue) -> totuusarvomaski."""
        im = Image.new("L", (self.w, self.h), 0)
        d = ImageDraw.Draw(im)
        for p in alueet(geom):
            d.polygon([self.px(x, y) for x, y in p.exterior.coords], fill=1)
            for ri in p.interiors:
                d.polygon([self.px(x, y) for x, y in ri.coords], fill=0)
        return np.asarray(im, dtype=bool)


def alueet(g):
    if g is None or g.is_empty:
        return []
    if g.geom_type == "Polygon":
        return [g]
    return [p for part in getattr(g, "geoms", []) for p in alueet(part)]


def lue_rgb(vrt, e0, n0, e1, n1):
    """Lukee RGB-ikkunan (n0 < n1) VRT:stä. Palauttaa (taulukko, Ikkuna)."""
    ds = gdal.Open(str(vrt))
    gt = ds.GetGeoTransform()
    w, h = int(round((e1 - e0) / RES)), int(round((n1 - n0) / RES))
    xo, yo = int(round((e0 - gt[0]) / gt[1])), int(round((gt[3] - n1) / -gt[5]))
    a = np.stack([ds.GetRasterBand(i).ReadAsArray(xo, yo, w, h) for i in (1, 2, 3)], axis=-1)
    return a, Ikkuna(gt[0] + xo * gt[1], gt[3] + yo * gt[5], w, h)


def kirkkaus(rgb):
    return (0.299 * rgb[..., 0] + 0.587 * rgb[..., 1] + 0.114 * rgb[..., 2]).astype(np.float32)


def taustakirkkaus(Y, vesi):
    """Veden taustasävy: lohkomediaani (2 m) ja liukuva mediaani (PARAM tausta_ikkuna_m), vain vesipikseleistä."""
    k = 4
    h2, w2 = Y.shape[0] // k, Y.shape[1] // k
    yl = Y[:h2 * k, :w2 * k].reshape(h2, k, w2, k).transpose(0, 2, 1, 3).reshape(h2, w2, k * k)
    vl = vesi[:h2 * k, :w2 * k].reshape(h2, k, w2, k).transpose(0, 2, 1, 3).reshape(h2, w2, k * k)
    med = np.median(yl, axis=2)
    ok = vl.mean(axis=2) > 0.5
    if not ok.any():
        return np.full(Y.shape, 40.0, np.float32)
    # ei-vesilohkojen tilalle lähin vesilohko
    idx = ndi.distance_transform_edt(~ok, return_distances=False, return_indices=True)
    med = med[idx[0], idx[1]]
    ikk = int(round(PARAM["tausta_ikkuna_m"] / (RES * k))) | 1
    tausta = ndi.median_filter(med, size=ikk, mode="nearest")
    iso = ndi.zoom(tausta, k, order=1, mode="nearest")
    out = np.empty(Y.shape, np.float32)
    out[:] = iso[-1, -1]
    out[:iso.shape[0], :iso.shape[1]] = iso[:Y.shape[0], :Y.shape[1]]
    return out


# ----------------------------------------------------------------------------------------
# Tunnistus
# ----------------------------------------------------------------------------------------
def pca_mitat(rr, cc):
    """Alueen pääakseli: (pituus, leveys, kulma_rad (pääakseli, kuvakoordinaatit x oikealle, y alas), keskipiste, u-skew)."""
    x = (cc + 0.5) * RES
    y = (rr + 0.5) * RES
    mx, my = x.mean(), y.mean()
    dx, dy = x - mx, y - my
    cov = np.array([[np.mean(dx * dx), np.mean(dx * dy)], [np.mean(dx * dy), np.mean(dy * dy)]])
    val, vec = np.linalg.eigh(cov)
    v1, v2 = vec[:, 1], vec[:, 0]
    u = dx * v1[0] + dy * v1[1]
    v = dx * v2[0] + dy * v2[1]
    pituus = u.max() - u.min() + RES
    leveys = v.max() - v.min() + RES
    return pituus, leveys, v1, v2, (mx, my), (u.min(), u.max(), float(u.mean()))


def jaa_edt(maski):
    """Varajako: jakaa yhteen kiinni olevat kohteet etäisyysmuunnoksen huippujen mukaan. Palauttaa nimiöidyn taulukon (0 = tausta) tai None."""
    et = ndi.distance_transform_edt(np.pad(maski, 1))
    et = ndi.gaussian_filter(et, 0.7)[1:-1, 1:-1]
    r = max(2, int(round(PARAM["jako_huippu_etaisyys_m"] / RES)))
    huiput = (et == ndi.maximum_filter(et, size=2 * r + 1)) & (et >= 2.0) & maski
    mark, n = ndi.label(huiput, structure=np.ones((3, 3)))
    if n <= 1:
        return None
    idx = ndi.distance_transform_edt(mark == 0, return_distances=False, return_indices=True)
    uusi = mark[idx[0], idx[1]]
    uusi[~maski] = 0
    return uusi


def jaa_alue(maski, voima, t, edt_ok=True):
    """Jakaa yhteen kiinni olevat veneet. Kynnystä nostetaan portain (PARAM jako_askel), kunnes alue hajoaa vähintään kahdeksi riittävän
    isoksi osaksi. Veneiden rungot ovat kirkkaita ja niiden väliset saumat (varjo, vesirako, laituri) tummempia. Osat kasvatetaan takaisin
    alkuperäiseen alueeseen lähimmän siemenen mukaan. Jos kynnys ei erota osia, käytetään etäisyysmuunnoksen huippuja.
    Palauttaa listan (osamaski, kynnys, tapa) tai None."""
    minpx = PARAM["jako_min_px"]
    askel = PARAM["jako_askel"]
    tt = t + askel
    while tt < 250:
        m2 = maski & (voima > tt)
        lab, n = ndi.label(m2, structure=np.ones((3, 3)))
        if n == 0:
            break
        ala = ndi.sum(m2, lab, index=np.arange(1, n + 1))
        hyva = [k + 1 for k, a in enumerate(ala) if a >= minpx]
        if len(hyva) >= 2:
            siemen = np.zeros(maski.shape, np.int32)
            for j, k in enumerate(hyva, start=1):
                siemen[lab == k] = j
            idx = ndi.distance_transform_edt(siemen == 0, return_distances=False, return_indices=True)
            osat = siemen[idx[0], idx[1]]
            osat[~maski] = 0
            return [(osat == j, tt, "kynnys") for j in range(1, len(hyva) + 1)]
        if not hyva:
            break
        tt += askel
    # toinen yritys: tummat ohuet saumat (musta huippuhattu, kapeampi kuin 2,5 m) leikataan pois alueesta
    syvyys = ndi.grey_closing(voima, size=(5, 5)) - voima
    sauma = (syvyys >= PARAM["jako_saumasyvyys"]) & maski
    if sauma.any():
        m2 = maski & ~sauma
        lab, n = ndi.label(m2, structure=np.ones((3, 3)))
        if n >= 2:
            ala = ndi.sum(m2, lab, index=np.arange(1, n + 1))
            hyva = [k + 1 for k, a in enumerate(ala) if a >= minpx]
            if len(hyva) >= 2:
                siemen = np.zeros(maski.shape, np.int32)
                for j, k in enumerate(hyva, start=1):
                    siemen[lab == k] = j
                idx = ndi.distance_transform_edt(siemen == 0, return_distances=False, return_indices=True)
                osat = siemen[idx[0], idx[1]]
                osat[~maski] = 0
                return [(osat == j, t, "sauma") for j in range(1, len(hyva) + 1)]
    if not edt_ok:
        return None
    osat = jaa_edt(maski)
    if osat is None:
        return None
    return [(osat == j, t, "etaisyys") for j in np.unique(osat[osat > 0])]


def luokka_ja_muoto(pituus, leveys):
    suhde = pituus / leveys
    if pituus < 4.8:
        return "soutu" if suhde >= 2.6 else "pieni"
    if pituus <= 7.5:
        return "keski"
    if suhde > 3.0:
        return "purje"
    return "keski"


class Kohteet:
    """Yhtenäisten alueiden käsittely veneehdokkaiksi. Liian suuret alueet jaetaan rekursiivisesti (jaa_alue)."""

    def __init__(self, Y, tausta, ikk, tumma, voima, ei_vesi=None, dbg=None, rgb=None):
        self.Y, self.tausta, self.ikk, self.tumma, self.voima, self.dbg = Y, tausta, ikk, tumma, voima, dbg
        self.rgb = rgb                    # värikuva (sinisyyden laskentaan: ponttoonilaiturien erottaminen veneistä)
        self.ei_vesi = ei_vesi            # laiturit yms., joita ei lasketa mukaan vesiosuuteen
        self.ulos = []
        self.tilasto = {"alueita": 0, "hyvaksytty": 0, "liian_pieni": 0, "liian_iso": 0, "sopimaton_muoto": 0, "jaettu_alueita": 0,
                        "jako_kynnys": 0, "jako_sauma": 0, "jako_etaisyys": 0}

    def vesiosuus(self, rr, cc):
        """Kohdetta ympäröivän 2,5 m:n renkaan vedenkaltaisten (tummien) pikselien osuus. Rengasta ei lasketa laiturien eikä kirkkaiden pikselien
        (naapuriveneet) osalta. Sillat ja rakenteet ovat MML:n järvipolygonin sisällä, mutta niiden ympärillä ei ole tummaa vettä."""
        H, W = self.Y.shape
        pad = 7
        r0, r1 = max(0, rr.min() - pad), min(H, rr.max() + pad + 1)
        c0, c1 = max(0, cc.min() - pad), min(W, cc.max() + pad + 1)
        kohde = np.zeros((r1 - r0, c1 - c0), bool)
        kohde[rr - r0, cc - c0] = True
        rengas = ndi.binary_dilation(kohde, iterations=5) & ~ndi.binary_dilation(kohde, iterations=1)
        Ya = self.Y[r0:r1, c0:c1]
        rengas &= Ya < 140
        if self.ei_vesi is not None:
            rengas &= ~self.ei_vesi[r0:r1, c0:c1]
        n = int(rengas.sum())
        if n < 8:
            return 1.0
        vesi = Ya <= PARAM["vesi_kirkkaus_max"]
        return float((vesi & rengas).sum() / n)

    def laiturin_lahella(self, rr, cc):
        """Onko alueen 4 m:n sisällä laituri-, aallonmurtaja-, kivi- tai siltakohde (poissulkumaskissa)."""
        if self.ei_vesi is None:
            return False
        H, W = self.Y.shape
        r0, r1 = max(0, rr.min() - 8), min(H, rr.max() + 9)
        c0, c1 = max(0, cc.min() - 8), min(W, cc.max() + 9)
        return bool(self.ei_vesi[r0:r1, c0:c1].any())

    def kasittele(self, sub, r0, c0, t, syvyys=0, jaettu=False):
        tl = self.tilasto
        rr, cc = np.nonzero(sub)
        rr = rr + r0
        cc = cc + c0
        lo, hi = PARAM["pituus_m"], PARAM["leveys_m"]

        def _d(tila):
            if self.dbg is not None:
                self.dbg.append((tila, rr, cc))
        if len(rr) < 6:
            tl["liian_pieni"] += 1
            return
        ala = len(rr) * RES * RES
        pit, lev, v1, v2, (mx, my), (umin, umax, uka) = pca_mitat(rr, cc)
        if pit < lo[0] * 0.6 or ala < 1.5:
            tl["liian_pieni"] += 1
            _d("pieni")
            return
        liian_iso = ala > PARAM["pinta_ala_max_m2"] or pit > lo[1] or lev > hi[1]
        if syvyys == 0 and pit > lo[1] and lev <= PARAM["alus_leveys_max_m"] and ala <= PARAM["alus_ala_max_m2"] and not self.laiturin_lahella(rr, cc):
            # yli 16 m:n pitkänomainen alus rannassa (museo- tai matkustaja-alus): ei veneiden joukkoon eikä jaeta osiin
            tl["liian_iso"] += 1
            tl["iso_alus"] = tl.get("iso_alus", 0) + 1
            _d("iso_alus")
            return
        if liian_iso:
            if syvyys < 5:
                # etäisyysmuunnoksella jaetaan vain selvästi liian suuret alueet, jottei yksittäinen suuri vene hajoa kahdeksi
                edt_ok = lev > 6.0 or pit > 18.0 or ala > 90.0
                osat = jaa_alue(sub, self.voima[r0:r0 + sub.shape[0], c0:c0 + sub.shape[1]], t, edt_ok)
                if osat is not None:
                    tl["jaettu_alueita"] += 1
                    tl["jako_" + osat[0][2]] = tl.get("jako_" + osat[0][2], 0) + 1
                    for m, t2, _ in osat:
                        self.kasittele(m, r0, c0, t2, syvyys + 1, True)
                    return
            # ei jakautunut: iso moottorivene (leveys enintään 6 m) hyväksytään yhtenä veneenä
            if not (pit <= lo[1] and lev <= PARAM["leveys_salli_m"] and ala <= PARAM["pinta_ala_salli_m2"]):
                tl["liian_iso"] += 1
                _d("iso" if not jaettu else "iso_osa")
                return
        suhde = pit / lev
        if not (lo[0] <= pit <= lo[1] and hi[0] <= lev <= PARAM["leveys_salli_m"] and PARAM["suhde"][0] <= suhde <= PARAM["suhde"][1]):
            tl["sopimaton_muoto"] += 1
            _d("muoto:%.1f x %.1f" % (pit, lev))
            return
        _d("ok")
        kontrasti = float(np.mean(np.abs(self.Y[rr, cc] - self.tausta[rr, cc])))
        vesiosuus = self.vesiosuus(rr, cc)
        sinisyys = 0.0
        if self.rgb is not None:
            sinisyys = float(self.rgb[rr, cc, 2].mean()) - float(self.rgb[rr, cc, 0].mean())
        tayttoaste = ala / (math.pi / 4 * pit * lev)
        x0, y0 = self.ikk.maailma(mx / RES - 0.5, my / RES - 0.5)
        # pääakseli maailmakoordinaateissa: kuvan y-akseli osoittaa alas, joten n-komponentti vaihtaa merkkiä
        akseli = (float(v1[0]), -float(v1[1]))
        skew = (umax - uka) - (uka - umin)        # >0: pidempi varsi akselin positiiviseen suuntaan
        self.ulos.append({"e": x0, "n": y0, "pituus": float(pit), "leveys": float(lev), "akseli": akseli, "skew": float(skew),
                          "kontrasti": kontrasti, "tayttoaste": float(tayttoaste), "ala": float(ala), "tumma": bool(self.tumma),
                          "jaettu": bool(jaettu), "vesiosuus": vesiosuus, "sinisyys": sinisyys})
        tl["hyvaksytty"] += 1


def kohteet_maskista(maski, Y, tausta, ikk, tumma, voima, t0, ei_vesi=None, dbg=None, rgb=None):
    """Yhtenäiset alueet -> veneehdokkaat. voima: kirkkauden poikkeama taustasta (tummille käännettynä), t0: perusraja. Palauttaa (hyväksytyt, tilasto)."""
    lab, n = ndi.label(maski, structure=np.ones((3, 3)))
    K = Kohteet(Y, tausta, ikk, tumma, voima, ei_vesi, dbg, rgb)
    K.tilasto["alueita"] = int(n)
    if n:
        for i, s in enumerate(ndi.find_objects(lab), start=1):
            if s is not None:
                K.kasittele(lab[s] == i, s[0].start, s[1].start, t0)
    return K.ulos, K.tilasto


def suorakulma(k):
    """Kohteen pääakselin suuntainen suorakulmio (shapely)."""
    ax, ay = k["akseli"]
    L, W = k["pituus"] / 2, k["leveys"] / 2
    vx, vy = -ay, ax
    return Polygon([(k["e"] + ax * L + vx * W, k["n"] + ay * L + vy * W), (k["e"] + ax * L - vx * W, k["n"] + ay * L - vy * W),
                    (k["e"] - ax * L - vx * W, k["n"] - ay * L - vy * W), (k["e"] - ax * L + vx * W, k["n"] - ay * L + vy * W)])


def uskottavuus(k):
    """Kohteen koon, muodon ja kontrastin perusteella laskettu pistemäärä (0-1), jota käytetään varmuutena ja päällekkäisyyksien ratkaisussa."""
    koko = 1.0 if (4.0 <= k["pituus"] <= 14.0 and 1.5 <= k["leveys"] <= 4.5) else 0.6
    tayttoaste_p = max(0.0, 1.0 - abs(k["tayttoaste"] - 1.0) / 0.5)
    kontrasti_p = min(1.0, k["kontrasti"] / 100.0)
    v = 0.4 * tayttoaste_p + 0.3 * koko + 0.3 * kontrasti_p
    if k.get("jaettu"):
        v *= 0.85
    if k["tumma"]:
        v *= 0.7
    return v


def poista_paallekkaiset(kohteet):
    """Jos kahden kohteen suorakulmiot menevät yli PARAM paallekkain_max verran päällekkäin (osuus pienemmästä), pidetään uskottavampi.
    Palauttaa (pidetyt, poistettujen määrä)."""
    if len(kohteet) < 2:
        return kohteet, 0
    polyt = [suorakulma(k) for k in kohteet]
    jarj = sorted(range(len(kohteet)), key=lambda i: -uskottavuus(kohteet[i]))
    pidetyt = []
    for i in jarj:
        ok = True
        for j in pidetyt:
            if polyt[i].intersects(polyt[j]):
                a = polyt[i].intersection(polyt[j]).area
                if a / min(polyt[i].area, polyt[j].area) > PARAM["paallekkain_max"]:
                    ok = False
                    break
        if ok:
            pidetyt.append(i)
    return [kohteet[i] for i in sorted(pidetyt)], len(kohteet) - len(pidetyt)


def laituriapu(laiturit):
    """Laituriviivat listana (shapely LineString)."""
    out = []
    for g in laiturit:
        out.extend(getattr(g, "geoms", [g]))
    return out


def keula_ja_varmuus(k, laituriviivat, laituri_tree):
    """Päättelee keulan suunnan (tosisuunta asteina) ja kokonaisvarmuuden."""
    ax, ay = k["akseli"]                       # pääakseli (e, n)
    pit, lev = k["pituus"], k["leveys"]
    skew_osuus = k["skew"] / pit
    lahde = "oletus"
    suunta_vektori = (ax, ay)
    muoto_ok = abs(skew_osuus) >= PARAM["keula_vinouma_min"]
    # laituri: lähin piste
    laituri_vektori = None
    if laituriviivat:
        p = Point(k["e"], k["n"])
        lahin = min(laituriviivat, key=lambda l: l.distance(p))
        d = lahin.distance(p)
        if d <= PARAM["laituri_vaikutus_m"]:
            q = lahin.interpolate(lahin.project(p))
            vx, vy = q.x - p.x, q.y - p.y
            nv = math.hypot(vx, vy)
            if nv > 0.2:
                laituri_vektori = (vx / nv, vy / nv)
    if muoto_ok:
        # pitkä varsi on keula (kapeampi, osoittava pää)
        if k["skew"] < 0:
            ax, ay = -ax, -ay
        lahde = "muoto"
    elif laituri_vektori is not None and abs(ax * laituri_vektori[0] + ay * laituri_vektori[1]) >= 0.5:
        if ax * laituri_vektori[0] + ay * laituri_vektori[1] < 0:
            ax, ay = -ax, -ay
        lahde = "laituri"
    else:
        # oletus: keula pohjoiseen, jos ei muuta tietoa (varmuus pieni)
        if ay < 0 or (abs(ay) < 1e-9 and ax < 0):
            ax, ay = -ax, -ay
    suunta = (math.degrees(math.atan2(ax, ay)) + 360.0) % 360.0
    # sopivuus laituriin: samansuuntainen kuin laituriin osoittaminen
    laituri_samaa = None
    if laituri_vektori is not None:
        laituri_samaa = (ax * laituri_vektori[0] + ay * laituri_vektori[1]) > 0.5
    # varmuus
    v = uskottavuus(k)
    if lahde == "oletus":
        v *= 0.9
    return suunta, lahde, round(max(0.05, min(0.99, v)), 2), laituri_samaa


# ----------------------------------------------------------------------------------------
# Satama
# ----------------------------------------------------------------------------------------
def tunnistusalue(h, vesi_laaja, ranta_laaja):
    """Tunnistusalue (shapely): vesi 0-60 m laitureista tai 0-150 m rannasta satamakohteen ympärillä. Palauttaa (alue, laiturit, esteet)."""
    c = Point(h["e"], h["n"])
    iso = c.buffer(h["r"] + 150).bounds
    laiturit = [g for g, p in lue_geometriat("vesieste_viiva", iso, "laji IN ('laituri_kapea','laituri_leveä')")]
    laiturit = [g for g in laiturit if g.distance(c) <= h["r"] + 60]
    aallonmurtajat = [g for g, p in lue_geometriat("vesieste_viiva", iso, "laji='aallonmurtaja'")]
    kivet = [g for g, p in lue_geometriat("vesieste_piste", iso, "koodi IN (38512,38513)")]
    sillat = [g for g, p in lue_geometriat("tie", iso, "taso >= 1")]
    vesi = vesi_laaja
    ympyra = c.buffer(h["r"])
    poiju = vesi.intersection(ranta_laaja.buffer(PARAM["ranta_vyohyke_m"])).intersection(ympyra)
    lait = vesi.intersection(unary_union(laiturit).buffer(PARAM["laituri_vyohyke_m"])) if laiturit else None
    alue = unary_union([g for g in (poiju, lait) if g is not None and not g.is_empty])
    esteet = unary_union([g.buffer(PARAM["laituri_puskuri_m"]) for g in laiturit] +
                         [g.buffer(PARAM["laituri_puskuri_m"] * 2) for g in aallonmurtajat] +
                         [g.buffer(PARAM["kivi_puskuri_m"]) for g in kivet] +
                         [g.buffer(PARAM["silta_puskuri_m"]) for g in sillat]) if (laiturit or aallonmurtajat or kivet or sillat) else None
    return alue, laiturit, esteet


def tunnista_satama(h, vrt, vesi_laaja, ranta_laaja, kuvat=True, kuvanimi=None):
    alku = time.time()
    alue, laiturit, esteet = tunnistusalue(h, vesi_laaja, ranta_laaja)
    if alue.is_empty:
        loki("%s: tunnistusalue tyhjä" % h["nimi"])
        return [], {"nimi": h["nimi"], "veneita": 0, "huomio": "tunnistusalue tyhjä"}, None
    b = alue.bounds
    marg = 25
    e0, n0, e1, n1 = (math.floor(b[0]) - marg, math.floor(b[1]) - marg, math.ceil(b[2]) + marg, math.ceil(b[3]) + marg)
    e0, n0 = e0 - (e0 % 1), n0 - (n0 % 1)
    rgb, ikk = lue_rgb(vrt, e0, n0, e1, n1)
    Y = kirkkaus(rgb)
    vesi_m = ikk.rasteroi(vesi_laaja.intersection(box(e0, n0, e1, n1)))
    zone = ikk.rasteroi(alue)
    pier = ikk.rasteroi(esteet) if esteet is not None else np.zeros_like(zone)
    tausta = taustakirkkaus(Y, vesi_m & ~pier)
    ero = Y - tausta
    sall = zone & ~pier
    tilastot = {}
    kohteet = []
    for tumma, kynnys, nimi in ((False, PARAM["kynnys_vaalea"], "vaalea"), (True, PARAM["kynnys_tumma"], "tumma")):
        ehdokas = ((-ero if tumma else ero) > kynnys) & sall
        a = PARAM["avaus_px"]
        s = PARAM["sulku_px"]
        m = ndi.binary_opening(ehdokas, structure=np.ones((a, a)))
        m = ndi.binary_closing(m, structure=np.ones((s, s)))
        m &= sall
        if tumma:
            # tummat kohteet eivät saa osua vaaleisiin
            m &= ~ndi.binary_dilation(kohteet_peite(kohteet, ikk, m.shape), iterations=2)
        ks, t = kohteet_maskista(m, Y, tausta, ikk, tumma, -ero if tumma else ero, kynnys, ei_vesi=pier, rgb=rgb)
        t["ehdokaspikseleita"] = int(ehdokas.sum())
        tilastot[nimi] = t
        kohteet.extend(ks)
    # Vesiosuus-ehto koskee vain kohteita, joiden lähellä ei ole kirjattua laituria (rannan, siltojen ja rakenteiden väärät havainnot).
    # Laiturien viereisissä tiiviissä venerivistöissä rengas on lähes kokonaan toisia veneitä ja varjoja.
    laituriviivat = laituriapu(laiturit)
    # Tummat havainnot aivan rannan tai laiturimuurin vieressä ovat lähes aina muurin varjoja
    rajat = vesi_laaja.intersection(box(e0, n0, e1, n1)).boundary
    ennen = len(kohteet)
    kohteet = [k for k in kohteet if not k["tumma"] or rajat.distance(Point(k["e"], k["n"])) >= PARAM["tumma_ranta_m"]]
    tummia_poistettu = ennen - len(kohteet)
    ennen = len(kohteet)
    kohteet = [k for k in kohteet if not (k["sinisyys"] >= PARAM["ponttoni_sinisyys_min"] and k["leveys"] <= PARAM["ponttoni_leveys_max_m"])]
    ponttoneja_poistettu = ennen - len(kohteet)
    ennen = len(kohteet)
    kohteet = [k for k in kohteet if k["vesiosuus"] >= PARAM["vesiosuus_min"] or
               any(l.distance(Point(k["e"], k["n"])) <= PARAM["laituri_vaikutus_m"] for l in laituriviivat)]
    ei_vetta = ennen - len(kohteet)
    kohteet, poistettu = poista_paallekkaiset(kohteet)
    ennen = len(kohteet)
    kohteet = [k for k in kohteet if not any(z["satama"] == h["nimi"] and z["e0"] <= k["e"] <= z["e1"] and z["n0"] <= k["n"] <= z["n1"] for z in POISSULKUALUEET)]
    kasin_poistettu = ennen - len(kohteet)
    veneet = []
    samaa = {"muoto": 0, "laituri": 0, "oletus": 0, "laituri_samaa_muodon_kanssa": 0, "laituri_eri_muodon_kanssa": 0}
    for k in kohteet:
        suunta, lahde, varmuus, ls = keula_ja_varmuus(k, laituriviivat, None)
        samaa[lahde] += 1
        if lahde == "muoto" and ls is not None:
            samaa["laituri_samaa_muodon_kanssa" if ls else "laituri_eri_muodon_kanssa"] += 1
        veneet.append({"e": round(k["e"], 1), "n": round(k["n"], 1), "suunta": round(suunta, 1), "pituus": round(k["pituus"], 1),
                       "leveys": round(k["leveys"], 1), "luokka": luokka_ja_muoto(k["pituus"], k["leveys"]), "varmuus": varmuus,
                       "satama": h["nimi"], "suunta_lahde": lahde})
    yhteenveto = {"nimi": h["nimi"], "keskipiste_e": h["e"], "keskipiste_n": h["n"], "poijusade_m": h["r"], "paikannimi": h.get("paikannimi"),
                  "veneita": len(veneet), "paallekkaisia_poistettu": poistettu, "ei_vetta_ymparilla_poistettu": ei_vetta, "tummia_rannalta_poistettu": tummia_poistettu, "ponttoneja_poistettu": ponttoneja_poistettu, "poissulkualueilta_poistettu": kasin_poistettu, "laitureita_alueella": len(laituriviivat), "tunnistusalue_m2": round(alue.area),
                  "tunnistusalue_bbox": [round(v) for v in alue.bounds], "tilastot": tilastot, "keula": samaa,
                  "sekuntia": round(time.time() - alku, 1)}
    loki("%s: %d venettä (%s), %.0f s" % (h["nimi"], len(veneet), json.dumps({k: v["hyvaksytty"] for k, v in tilastot.items()}), time.time() - alku))
    kuva = None
    if kuvat:
        kuva = piirra(h, rgb, ikk, veneet, alue, laituriviivat, kuvanimi)
    return veneet, yhteenveto, kuva


def kohteet_peite(kohteet, ikk, muoto):
    m = np.zeros(muoto, bool)
    for k in kohteet:
        c, r = ikk.px(k["e"], k["n"])
        rr, cc = int(round(r)), int(round(c))
        ra = int(round(k["pituus"] / RES / 2)) + 1
        m[max(0, rr - ra):rr + ra + 1, max(0, cc - ra):cc + ra + 1] = True
    return m


# ----------------------------------------------------------------------------------------
# Tarkistuskuva
# ----------------------------------------------------------------------------------------
def piirra(h, rgb, ikk, veneet, alue, laituriviivat, nimi):
    S = min(2.0, 2200.0 / max(ikk.w, ikk.h))
    kuva = Image.fromarray(rgb).resize((int(ikk.w * S), int(ikk.h * S)), Image.BILINEAR).convert("RGB")
    d = ImageDraw.Draw(kuva)

    def p(x, y):
        c, r = ikk.px(x, y)
        return (c * S, r * S)

    for pol in alueet(alue):
        d.line([p(x, y) for x, y in pol.exterior.coords], fill=(0, 200, 255), width=1)
    for l in laituriviivat:
        d.line([p(x, y) for x, y in l.coords], fill=(255, 60, 60), width=1)
    for v in veneet:
        a = math.radians(v["suunta"])
        ux, uy = math.sin(a), math.cos(a)            # keulan suunta (e, n)
        vx, vy = uy, -ux                              # poikittainen
        L, W = v["pituus"] / 2, v["leveys"] / 2
        kulmat = [(v["e"] + ux * L + vx * W, v["n"] + uy * L + vy * W), (v["e"] + ux * L - vx * W, v["n"] + uy * L - vy * W),
                  (v["e"] - ux * L - vx * W, v["n"] - uy * L - vy * W), (v["e"] - ux * L + vx * W, v["n"] - uy * L + vy * W)]
        vari = (0, 255, 0) if v["varmuus"] >= 0.7 else ((255, 255, 0) if v["varmuus"] >= 0.5 else (255, 140, 0))
        d.polygon([p(x, y) for x, y in kulmat], outline=vari)
        d.line([p(v["e"], v["n"]), p(v["e"] + ux * L * 1.15, v["n"] + uy * L * 1.15)], fill=(255, 0, 255), width=1)
        px_, py_ = p(v["e"] + ux * L * 1.15, v["n"] + uy * L * 1.15)
        d.ellipse([px_ - 2, py_ - 2, px_ + 2, py_ + 2], fill=(255, 0, 255))
    try:
        fontti = ImageFont.truetype("DejaVuSans.ttf", 14)
    except OSError:
        fontti = ImageFont.load_default()
    teksti = "%s: %d venettä. Vihreä varmuus >= 0,7, keltainen >= 0,5, oranssi alle. Magenta = keula" % (h["nimi"], len(veneet))
    d.rectangle([0, 0, int(d.textlength(teksti, font=fontti)) + 14, 26], fill=(0, 0, 0))
    d.text((7, 5), teksti, fill=(255, 255, 255), font=fontti)
    return kuva


def tallenna_kuva(kuva, nimi):
    out = []
    for hakemisto in (SHOTS, KUVAT):
        hakemisto.mkdir(parents=True, exist_ok=True)
        polku = hakemisto / ("veneet_%s.png" % nimi)
        kuva.save(polku, optimize=True)
        out.append(polku)
    return out


# ----------------------------------------------------------------------------------------
# Kokonaisuus
# ----------------------------------------------------------------------------------------
def aja(valitut_nimet=None, kuvat=True, kirjoita_paketti=True):
    alku = time.time()
    VTYO.mkdir(parents=True, exist_ok=True)
    JP2.mkdir(parents=True, exist_ok=True)
    satamat = [h for h in SATAMAT if not valitut_nimet or h["nimi"] in valitut_nimet]
    shp = hae_indeksi()
    # satamien tunnistusalueiden laatikot -> tarvittavat lehdet
    lehdet = {}
    for h in satamat:
        geom = Point(h["e"], h["n"]).buffer(h["r"] + 150)
        for d in indeksin_lehdet(shp, geom):
            lehdet.setdefault(d["lehti"], []).append(d)
    loki("Tarvittavat ortokuvalehdet:", ", ".join("%s (%s)" % (l, "/".join(str(v) for v in sorted({d["vuosi"] for d in ds}))) for l, ds in sorted(lehdet.items())))
    valitut = valitse_ortokuvat(lehdet, None)
    if not valitut:
        raise RuntimeError("Yhtään kesäkuvaa ei löytynyt")
    # VRT valituista lehdistä
    vrt = OTYO / "valitut.vrt"
    gdal.BuildVRT(str(vrt), [str(JP2 / v["tiedosto"]) for v in valitut.values()])
    # vesialue ja rantaviiva koko tunnistusalueelta
    xs = [h["e"] for h in satamat]
    ys = [h["n"] for h in satamat]
    r = max(h["r"] for h in satamat) + 300
    bbox_all = (min(xs) - r, min(ys) - r, max(xs) + r, max(ys) + r)
    vesi_laaja = vesialue(bbox_all)
    ranta_laaja = rantaviiva(bbox_all)
    veneet = []
    yhteenvedot = []
    kuvat_polut = []
    for h in satamat:
        try:
            v, y, kuva = tunnista_satama(h, vrt, vesi_laaja, ranta_laaja, kuvat)
            veneet.extend(v)
            lehti_tiedot = [d["lehti"] for d in indeksin_lehdet(shp, Point(h["e"], h["n"]).buffer(h["r"] + 150)) if d["lehti"] in valitut]
            y["ortokuvalehdet"] = sorted(set(lehti_tiedot))
            y["ortokuvavuodet"] = sorted({valitut[l]["vuosi"] for l in y["ortokuvalehdet"]})
            yhteenvedot.append(y)
            if kuva is not None:
                kuvat_polut.extend(str(p) for p in tallenna_kuva(kuva, h["nimi"].replace(" ", "_")))
        except Exception:  # noqa: BLE001
            traceback.print_exc()
            yhteenvedot.append({"nimi": h["nimi"], "veneita": 0, "virhe": "tunnistus epäonnistui"})
    vuodet = sorted({v["vuosi"] for v in valitut.values()})
    merkinta = "Sisältää Maanmittauslaitoksen ortokuva-aineistoa %s" % "/".join(str(v) for v in vuodet)
    ulos = {"lahde": "Maanmittauslaitoksen avoin ortokuva (Paituli, %s%s), veneet tunnistettu kuva-analyysilla vesialueelta" % (PAITULI, ORTO_POLKU),
            "lisenssi": ORTO_LISENSSI, "lisenssi_url": LISENSSI_CC_BY, "lahdemerkinta": merkinta,
            "luotu": nyt_iso(), "koordinaatisto": "EPSG:3067",
            "ortokuvat": [{"lehti": v["lehti"], "vuosi": v["vuosi"], "paiva": v["paiva"], "sarja": v["sarja"],
                           "tiedosto_paitulissa": v["polku_paitulissa"], "vihrea_osuus": v["vihrea_osuus"],
                           "uusin_indeksissa": v["uusin_indeksissa"], "hylatyt_uudemmat": v["hylatyt_uudemmat"]}
                          for v in sorted(valitut.values(), key=lambda d: d["lehti"])],
            "paivan_huomio": "Paitulin ortokuvaindeksi (ortho_all.shp) sisältää vain lehden ja vuoden, ei kuvauspäivää, joten päivä on null. Kuvat ovat kesäkuvia (lehdet puhjenneet, veneet vedessä).",
            "parametrit": {k: (list(v) if isinstance(v, tuple) else v) for k, v in PARAM.items()},
            "poissulkualueet": POISSULKUALUEET,
            "satamat": yhteenvedot, "veneita_yhteensa": len(veneet),
            "kentat": {"e, n": "veneen keskipiste, EPSG:3067 (m)", "suunta": "keulan tosisuunta asteina (0 = pohjoinen, myötäpäivään)",
                       "pituus, leveys": "m, ortokuvan pikselikoko 0,5 m", "luokka": "soutu, pieni, keski tai purje (pituudesta ja muodosta, ei mastosta)",
                       "varmuus": "0-1, muodon täyttöaste, koon uskottavuus ja kontrasti",
                       "suunta_lahde": "muoto = keula kapeampi pää, laituri = keula laituria kohti, oletus = ei tietoa (keula pohjoiseen)"},
            "veneet": sorted(veneet, key=lambda v: (v["satama"], -v["n"], v["e"]))}
    ULOS.mkdir(exist_ok=True)
    polku = ULOS / "veneet.json"
    kirjoita_json(polku, ulos, kompakti=False)
    kopio = os.environ.get("VENEET_KOPIO")
    if kopio:
        Path(kopio).mkdir(parents=True, exist_ok=True)
        shutil.copyfile(polku, Path(kopio) / "veneet.json")
        loki("veneet.json kopioitu:", Path(kopio) / "veneet.json")
    kirjoita_json(VTYO / "loki.json", {"luotu": nyt_iso(), "sekuntia": round(time.time() - alku, 1), "ortokuvat": list(valitut.values()),
                                       "satamat": yhteenvedot, "kuvat": kuvat_polut})
    if kirjoita_paketti and not valitut_nimet:
        paivita_aineisto_json(ulos)
    loki("Valmis: %d venettä, %d satamaa, %.0f s" % (len(veneet), len(satamat), time.time() - alku))
    return ulos


def paivita_aineisto_json(v):
    """Lisää ulos/aineisto.json-tiedostoon veneet.json, ortokuvalähteen ja lähdemerkinnän. Idempotentti."""
    polku = ULOS / "aineisto.json"
    if not polku.exists():
        loki("aineisto.json puuttuu, ei päivitetä")
        return False
    a = lue_json(polku)
    merkinta = v["lahdemerkinta"]
    ehto = next((l.get("ehtoteksti_sanatarkasti") for l in a.get("lahteet", []) if l.get("id") == "mml_korkeusmalli" and l.get("ehtoteksti_sanatarkasti")),
                "Creative Commons Nimeä 4.0 Kansainvälinen (CC BY 4.0), https://creativecommons.org/licenses/by/4.0/ (MML:n avoimen tietoaineiston lisenssi)")
    uusi = {"id": "mml_ortokuva", "nimi": "Ortokuva 0,5 m (värikuva, kesäkuvat): kiinnitettyjen veneiden paikat satamissa",
            "tuottaja": "Maanmittauslaitos", "osoite": PAITULI + ORTO_POLKU, "kerrokset": ["veneet.json"],
            "lisenssi": ORTO_LISENSSI, "lisenssi_url": LISENSSI_CC_BY, "lahdemerkinta": merkinta + " (CC BY 4.0).",
            "ehtoteksti_sanatarkasti": ehto, "haettu": v["luotu"], "siirretty_tavua": None,
            "huomio": "Ortokuvia ei julkaista, vain niistä tunnistetut veneet (veneet.json). Ortokuvan vuosi: %s. Veneiden paikat ovat ortokuvan kuvaushetken paikkoja eivätkä vastaa muiden aineistojen (esimerkiksi Googlen 3D-maiseman) hetkeä."
                      % ", ".join("%s %d" % (o["lehti"], o["vuosi"]) for o in v["ortokuvat"])}
    a["lahteet"] = [l for l in a.get("lahteet", []) if l.get("id") != "mml_ortokuva"] + [uusi]
    yht = a.get("lahdemerkinta_yhteensa", "")
    if merkinta not in yht:
        a["lahdemerkinta_yhteensa"] = (yht + " " + merkinta + " (CC BY 4.0).").strip()
    p = ULOS / "veneet.json"
    t = {"nimi": "veneet.json", "tavua": p.stat().st_size, "sha256": sha256(p)}
    a["tiedostot"] = [x for x in a.get("tiedostot", []) if x["nimi"] != "veneet.json"] + [t]
    a.setdefault("veneet", {"tiedosto": "veneet.json",
                            "muoto": "{lahde, lisenssi, lahdemerkinta, ortokuvat[], koordinaatisto, satamat[], veneet[{e, n, suunta, pituus, leveys, luokka, varmuus, satama, suunta_lahde}]}",
                            "ortokuvat": [{"lehti": o["lehti"], "vuosi": o["vuosi"]} for o in v["ortokuvat"]],
                            "veneita": v["veneita_yhteensa"]})
    a["veneet"]["ortokuvat"] = [{"lehti": o["lehti"], "vuosi": o["vuosi"]} for o in v["ortokuvat"]]
    a["veneet"]["veneita"] = v["veneita_yhteensa"]
    kirjoita_json(polku_ := ULOS / "aineisto.json", a)
    loki("aineisto.json päivitetty (veneet.json, mml_ortokuva)")
    return True


def main(argv):
    kuvat = "--ei-kuvia" not in argv
    nimet = [a for a in argv if not a.startswith("--")]
    aja(nimet or None, kuvat=kuvat)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
