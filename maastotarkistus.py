#!/usr/bin/env python3
"""Maaston korkeustarkistus (vaihe 1c): vertaa ulos/maasto.pmtiles-tiilien korkeuksia MML:n korkeusmalliin suoraan.

Tarkistaa viisi pistettä (Pispalanharju-Pyynikinharju, Näsinneulan juuri, Siilinkari, Naistenlahden ranta, Aitolahden ranta) tiilistä
(zoom 8-14, lähin pikseli ja bilineaarinen) ja DEM 2 m:stä sekä DEM 10 m:stä (bilineaarinen), kirjaa Terrain-RGB-koodauksen (offset, kerroin,
kvantisointi) ja ajaa lisäksi satunnaisotoksen z14-tiilien kaikista pikseleistä DEM 2 m:ään ja z8-13-tiilien pikseleistä DEM 10 m:ään.
Tulos kirjoitetaan tiedostoon tyo/maastotarkistus.json ja tulostetaan tiivistettynä.

Ajo:  python3 maastotarkistus.py [polku/maasto.pmtiles]
"""
import gzip  # noqa: F401
import io
import json
import math
import sys
from pathlib import Path

import numpy as np
import pyproj
from osgeo import gdal, ogr
from PIL import Image
from pmtiles.reader import MmapSource, Reader
from shapely import wkb as swkb
from shapely.geometry import Point
from shapely.ops import nearest_points, unary_union

from asetukset import TYO, ULOS, loki, nyt_iso

gdal.UseExceptions()
ogr.UseExceptions()

T4326_3067 = pyproj.Transformer.from_crs(4326, 3067, always_xy=True)
T3067_4326 = pyproj.Transformer.from_crs(3067, 4326, always_xy=True)
T3067_3857 = pyproj.Transformer.from_crs(3067, 3857, always_xy=True)
WM = 20037508.342789244

# Harjun hakulaatikko (EPSG:3067): Pispalanharju ja sen itäpää Pyynikinharju, laserkeilausvyöhykkeen sisällä (N >= 6 822 100)
HARJU_LAATIKKO = (322000.0, 6822100.0, 326200.0, 6823500.0)
NASINNEULA = (326711.0, 6823364.0)                     # maamerkit.json, vaihe 1b
SIILINKARI_LONLAT = (23.753916, 61.517582)             # Väyläviraston apuloisto Siilinkari (turvalaite 28843)
NAISTENLAHTI_ANKKURI = (328515.0, 6823755.0)           # Naistenlahden voimalaitos, rannan lähin kohta
AITOLAHTI_ANKKURI_LONLAT = (23.825966, 61.532808)      # Kirjoniemen viitta (Aitolahden väylä), rannan lähin kohta
RANTA_SISAANPAIN_M = 10.0
OTOS_Z14 = 250
OTOS_MUUT = 40


class Tiilet:
    def __init__(self, polku):
        self.f = open(polku, "rb")
        self.r = Reader(MmapSource(self.f))
        self.h = self.r.header()

    def kuva(self, z, x, y):
        b = self.r.get(z, x, y)
        if b is None:
            return None
        im = np.array(Image.open(io.BytesIO(b)).convert("RGB")).astype(np.int64)
        return -10000.0 + (im[..., 0] * 65536 + im[..., 1] * 256 + im[..., 2]) * 0.1, im


def tiili_xy_frac(e, n, z):
    wx, wy = T3067_3857.transform(e, n)
    koko = 2 * WM / (1 << z)
    fx, fy = (wx + WM) / koko, (WM - wy) / koko
    return int(fx), int(fy), fx - int(fx), fy - int(fy)


def tiili_nayte(t, e, n, z):
    """Tiilen arvo pisteessä: (lähin pikseli, bilineaarinen) tai (None, None). Ei-data (RGB 0,0,0) -> None."""
    x, y, fx, fy = tiili_xy_frac(e, n, z)
    k = t.kuva(z, x, y)
    if k is None:
        return None, None
    h, rgb = k
    ok = ~((rgb[..., 0] == 0) & (rgb[..., 1] == 0) & (rgb[..., 2] == 0))
    w = h.shape[1]
    px, py = fx * w - 0.5, fy * w - 0.5
    x0, y0 = int(math.floor(px)), int(math.floor(py))
    tx, ty = px - x0, py - y0
    lahin = None
    j, i = min(w - 1, max(0, int(fx * w))), min(w - 1, max(0, int(fy * w)))
    if ok[i, j]:
        lahin = float(h[i, j])
    arvot, paino = 0.0, 0.0
    for dy in (0, 1):
        for dx in (0, 1):
            xi, yi = min(w - 1, max(0, x0 + dx)), min(w - 1, max(0, y0 + dy))
            if ok[yi, xi]:
                p = (tx if dx else 1 - tx) * (ty if dy else 1 - ty)
                arvot += p * h[yi, xi]
                paino += p
    return lahin, (arvot / paino if paino > 0 else None)


def dem_nayte(ds, e, n):
    """DEM:n arvo pisteessä: (lähin, bilineaarinen) metreinä tai (None, None)."""
    gt = ds.GetGeoTransform()
    b = ds.GetRasterBand(1)
    nd = b.GetNoDataValue()
    px, py = (e - gt[0]) / gt[1] - 0.5, (n - gt[3]) / gt[5] - 0.5
    x0, y0 = int(math.floor(px)), int(math.floor(py))
    tx, ty = px - x0, py - y0
    if x0 < 0 or y0 < 0 or x0 + 2 > ds.RasterXSize or y0 + 2 > ds.RasterYSize:
        return None, None
    a = b.ReadAsArray(x0, y0, 2, 2).astype(np.float64)
    ok = (a > -9000) if nd is None else (a != nd) & (a > -9000)
    lahin = None
    jx, jy = (1 if tx >= 0.5 else 0), (1 if ty >= 0.5 else 0)
    if ok[jy, jx]:
        lahin = float(a[jy, jx])
    arvot, paino = 0.0, 0.0
    for dy in (0, 1):
        for dx in (0, 1):
            if ok[dy, dx]:
                p = (tx if dx else 1 - tx) * (ty if dy else 1 - ty)
                arvot += p * a[dy, dx]
                paino += p
    return lahin, (arvot / paino if paino > 0 else None)


def dem_max_laatikossa(ds, laatikko):
    gt = ds.GetGeoTransform()
    e0, n0, e1, n1 = laatikko
    c0, c1 = int((e0 - gt[0]) / gt[1]), int((e1 - gt[0]) / gt[1])
    r0, r1 = int((n1 - gt[3]) / gt[5]), int((n0 - gt[3]) / gt[5])
    a = ds.GetRasterBand(1).ReadAsArray(c0, r0, c1 - c0, r1 - r0).astype(np.float64)
    a = np.where(a < -9000, np.nan, a)
    i = int(np.nanargmax(a))
    r, c = divmod(i, a.shape[1])
    return float(a[r, c]), gt[0] + (c0 + c + 0.5) * gt[1], gt[3] + (r0 + r + 0.5) * gt[5]


def rantapiste(vesi, ankkuri):
    """Rannan lähin kohta ankkurille ja piste RANTA_SISAANPAIN_M m maalle päin ankkurin suuntaan."""
    a = Point(*ankkuri)
    rp = nearest_points(vesi.boundary, a)[0]
    dx, dy = ankkuri[0] - rp.x, ankkuri[1] - rp.y
    d = math.hypot(dx, dy) or 1.0
    sisalla = (rp.x + dx / d * RANTA_SISAANPAIN_M, rp.y + dy / d * RANTA_SISAANPAIN_M)
    return (rp.x, rp.y), sisalla, float(rp.distance(a))


def pisteen_tulos(nimi, kuvaus, e, n, t, dem2, dem10):
    lon, lat = T3067_4326.transform(e, n)
    d2 = dem_nayte(dem2, e, n) if dem2 is not None else (None, None)
    d10 = dem_nayte(dem10, e, n)
    r = {"nimi": nimi, "kuvaus": kuvaus, "e": round(e, 1), "n": round(n, 1), "lon": round(lon, 6), "lat": round(lat, 6),
         "dem2_lahin_m": None if d2[0] is None else round(d2[0], 2), "dem2_bilin_m": None if d2[1] is None else round(d2[1], 2),
         "dem10_bilin_m": None if d10[1] is None else round(d10[1], 2), "tiili": {}}
    for z in range(8, 15):
        la, bi = tiili_nayte(t, e, n, z)
        r["tiili"][str(z)] = {"lahin_m": None if la is None else round(la, 2), "bilin_m": None if bi is None else round(bi, 2)}
    t14 = r["tiili"]["14"]["bilin_m"]
    if t14 is not None and r["dem2_bilin_m"] is not None:
        r["ero_z14_dem2_m"] = round(t14 - r["dem2_bilin_m"], 2)
    if t14 is not None and r["dem10_bilin_m"] is not None:
        r["ero_z14_dem10_m"] = round(t14 - r["dem10_bilin_m"], 2)
    for z in ("8", "10", "12", "13"):
        v = r["tiili"][z]["bilin_m"]
        if v is not None and r["dem10_bilin_m"] is not None:
            r["ero_z%s_dem10_m" % z] = round(v - r["dem10_bilin_m"], 2)
    return r


def bilin_ruudukko(ds, E, N):
    """DEM:n bilineaarinen arvo pistetaulukossa (EPSG:3067). Palauttaa taulukon (NaN, kun ei dataa tai alueen ulkopuolella)."""
    gt = ds.GetGeoTransform()
    pc = (E - gt[0]) / gt[1] - 0.5
    pr = (N - gt[3]) / gt[5] - 0.5
    ulos = np.full(E.shape, np.nan)
    sis = (pc >= 0) & (pr >= 0) & (pc < ds.RasterXSize - 1) & (pr < ds.RasterYSize - 1)
    if not sis.any():
        return ulos
    c0, c1 = int(np.floor(pc[sis].min())), int(np.floor(pc[sis].max())) + 2
    r0, r1 = int(np.floor(pr[sis].min())), int(np.floor(pr[sis].max())) + 2
    a = ds.GetRasterBand(1).ReadAsArray(c0, r0, c1 - c0, r1 - r0).astype(np.float64)
    a = np.where(a < -9000, np.nan, a)
    ic = np.floor(pc[sis]).astype(int) - c0
    ir = np.floor(pr[sis]).astype(int) - r0
    fx, fy = pc[sis] - np.floor(pc[sis]), pr[sis] - np.floor(pr[sis])
    ulos[sis] = (a[ir, ic] * (1 - fx) * (1 - fy) + a[ir, ic + 1] * fx * (1 - fy) + a[ir + 1, ic] * (1 - fx) * fy + a[ir + 1, ic + 1] * fx * fy)
    return ulos


def tiilen_pikselit(z, x, y, koko=256):
    """Tiilen pikselikeskipisteet EPSG:3067:ssä."""
    kk = 2 * WM / (1 << z)
    wx0, wy1 = -WM + x * kk, WM - y * kk
    j = (np.arange(koko) + 0.5) * kk / koko
    X = wx0 + np.repeat(j[None, :], koko, 0)
    Y = wy1 - np.repeat(j[:, None], koko, 1)
    E, N = pyproj.Transformer.from_crs(3857, 3067, always_xy=True).transform(X.ravel(), Y.ravel())
    return np.asarray(E).reshape(koko, koko), np.asarray(N).reshape(koko, koko)


def tilasto_ero(ero):
    ae = np.abs(ero)
    return {"pikseleita": int(len(ero)), "ero_mediaani_m": round(float(np.median(ero)), 3), "ero_keskiarvo_m": round(float(ero.mean()), 3),
            "abs_ero_p95_m": round(float(np.percentile(ae, 95)), 2), "abs_ero_p99_m": round(float(np.percentile(ae, 99)), 2),
            "abs_ero_max_m": round(float(ae.max()), 2), "osuus_alle_1_m_pros": round(100.0 * float((ae < 1.0).mean()), 2),
            "osuus_yli_3_m_pros": round(100.0 * float((ae > 3.0).mean()), 2)}


def ruutuotos(t, dem, z, lukumaara, rng, dem_vert=None, vyohyke=None):
    """Satunnaisotos tiilistä: vertaa tiilen pikseleitä DEM:iin (bilineaarinen pikselin keskipisteessä).

    dem_vert (DEM 10 m) kertoo, mistä lähteestä poikkeamat johtuvat. vyohyke (shapely, EPSG:3067) erottaa rantavyöhykkeen, jossa z14 tehdään DEM 2 m:stä."""
    h = t.h
    minlon, maxlon = h["min_lon_e7"] / 1e7, h["max_lon_e7"] / 1e7
    minlat, maxlat = h["min_lat_e7"] / 1e7, h["max_lat_e7"] / 1e7
    n = 1 << z
    x0, x1 = int((minlon + 180) / 360 * n), int((maxlon + 180) / 360 * n)
    ya = int((1 - math.asinh(math.tan(math.radians(maxlat))) / math.pi) / 2 * n)
    yb = int((1 - math.asinh(math.tan(math.radians(minlat))) / math.pi) / 2 * n)
    avaimet, yritykset = [], 0
    while len(avaimet) < lukumaara and yritykset < lukumaara * 80:
        yritykset += 1
        x, y = int(rng.integers(x0, x1 + 1)), int(rng.integers(ya, yb + 1))
        if (x, y) not in avaimet and t.r.get(z, x, y) is not None:
            avaimet.append((x, y))
    kaikki, sisa, ulko, v10 = [], [], [], []
    suurimmat = []
    korkein = -1e9
    muistiin_kauimmaiset = 0
    for x, y in avaimet:
        hh, rgb = t.kuva(z, x, y)
        ok = ~((rgb[..., 0] == 0) & (rgb[..., 1] == 0) & (rgb[..., 2] == 0))
        E, N = tiilen_pikselit(z, x, y)
        v = bilin_ruudukko(dem, E, N)
        sel = ok & np.isfinite(v)
        if not sel.any():
            continue
        ero = (hh - v)[sel]
        kaikki.append(ero)
        korkein = max(korkein, float(hh[ok].max()))
        if vyohyke is not None:
            import shapely
            sis = shapely.contains_xy(vyohyke, E[sel], N[sel])
            sisa.append(ero[sis])
            ulko.append(ero[~sis])
        if dem_vert is not None:
            w = bilin_ruudukko(dem_vert, E, N)
            ok10 = sel & np.isfinite(w)
            v10.append(np.stack([(hh - v)[ok10], (hh - w)[ok10]], axis=1))
        i = int(np.argmax(np.abs(ero)))
        ys, xs = np.where(sel)
        suurimmat.append((float(ero[i]), x, y, round(float(E[ys[i], xs[i]]), 0), round(float(N[ys[i], xs[i]]), 0)))
    if not kaikki:
        return {"tiilia": 0}
    e = np.concatenate(kaikki)
    suurimmat.sort(key=lambda d: -abs(d[0]))
    tulos = dict(tilasto_ero(e), tiilia=len(kaikki), tiilien_korkein_arvo_m=round(korkein, 1),
                 suurimmat_erot_m_x_y_e_n=[[round(a_, 2), b, c, d, f] for a_, b, c, d, f in suurimmat[:3]])
    if sisa and sum(len(a_) for a_ in sisa):
        tulos["rantavyohykkeella"] = tilasto_ero(np.concatenate(sisa))
    if ulko and sum(len(a_) for a_ in ulko):
        tulos["vyohykkeen_ulkopuolella"] = tilasto_ero(np.concatenate(ulko))
    if v10:
        m = np.concatenate(v10)
        poik = np.abs(m[:, 0]) > 1.0
        tulos["poikkeamat_yli_1_m_dem2"] = {"pikseleita": int(poik.sum()), "niista_alle_1_m_dem10": int((np.abs(m[poik, 1]) < 1.0).sum()),
                                           "tulkinta": "Pikselit, joissa tiili poikkeaa DEM 2 m:stä yli 1 m, mutta täsmää DEM 10 m:iin: tiili on tehty DEM 10 m:stä (rantavyöhykkeen ulkopuolella), ja DEM 10 m poikkeaa DEM 2 m:stä lähteessä."}
    return tulos


PISPALA_LAATIKKO = (321000.0, 6820500.0, 324400.0, 6823500.0)


def puustotarkistus():
    """Lehtipuuosuus puusto.pmtiles-tiilissä (alfakanava): Pispalanharjun pohjoisrinteen näytepiste ja rinteen jakauma.

    Pohjoisrinne = Luken 16 m:n metsäruudut laatikossa PISPALA_LAATIKKO, joissa DEM 10 m:n rinne on vähintään 6 astetta ja rinteen alamäkisuunta on
    pohjoisesta enintään 45 astetta. Näytepiste on se rinneruutu, joka on lähimpänä rinneruutujen mediaanisijaintia (sääntö, ei valittu tuloksen mukaan)."""
    polku_l, polku_p = TYO / "luke_lehtipuuosuus.tif", ULOS / "puusto.pmtiles"
    if not polku_l.exists() or not polku_p.exists():
        return {"tila": "puuttuu: %s" % ("luke_lehtipuuosuus.tif" if not polku_l.exists() else "puusto.pmtiles")}
    L = gdal.Open(str(polku_l))
    gt = L.GetGeoTransform()
    sh = L.GetRasterBand(1).ReadAsArray().astype(np.float64)
    D = gdal.Open(str(TYO / "dem10.tif"))
    dgt = D.GetGeoTransform()
    dem = D.GetRasterBand(1).ReadAsArray().astype(np.float64)
    dem = np.where(dem < -9000, np.nan, dem)
    E0, N0, E1, N1 = PISPALA_LAATIKKO
    rivit = []
    for r in range(int((N1 - gt[3]) / gt[5]), int((N0 - gt[3]) / gt[5])):
        for c in range(int((E0 - gt[0]) / 16), int((E1 - gt[0]) / 16)):
            if sh[r, c] >= 32767:
                continue
            e, n = gt[0] + (c + 0.5) * gt[1], gt[3] + (r + 0.5) * gt[5]
            j, i = int((e - dgt[0]) / dgt[1]), int((n - dgt[3]) / dgt[5])
            z = dem[i - 1:i + 2, j - 1:j + 2]
            if z.shape != (3, 3) or np.isnan(z).any():
                continue
            dzdx = ((z[0, 2] + 2 * z[1, 2] + z[2, 2]) - (z[0, 0] + 2 * z[1, 0] + z[2, 0])) / (8 * dgt[1])
            dzdy = ((z[2, 0] + 2 * z[2, 1] + z[2, 2]) - (z[0, 0] + 2 * z[0, 1] + z[0, 2])) / (8 * dgt[1])   # rivit kasvavat etelään
            rinne = math.degrees(math.atan(math.hypot(dzdx, dzdy)))
            alamaki = math.degrees(math.atan2(-dzdx, dzdy)) % 360.0                                          # 0 = pohjoinen
            rivit.append((e, n, rinne, alamaki, sh[r, c]))
    P = np.array(rivit)
    m = (np.abs(((P[:, 3] + 180.0) % 360.0) - 180.0) < 45.0) & (P[:, 2] >= 6.0)
    Q = P[m]
    ce, cn = float(np.median(Q[:, 0])), float(np.median(Q[:, 1]))
    k = int(np.argmin((Q[:, 0] - ce) ** 2 + (Q[:, 1] - cn) ** 2))
    pe, pn, _, _, lahde_osuus = Q[k]
    t = Tiilet(polku_p)
    tulos = {"pohjoisrinteen_ruutuja": int(m.sum()), "rinteen_osuus_pros_p25_p50_p75": [round(float(v), 1) for v in np.percentile(Q[:, 4], [25, 50, 75])],
             "rinteen_ruuduista_yli_50_pros": round(100.0 * float((Q[:, 4] > 50).mean()), 1),
             "naytepiste_e_n": [round(float(pe), 0), round(float(pn), 0)], "lahderasterin_osuus_pros": round(float(lahde_osuus), 1), "tiilesta": {}}
    for z in (14, 13, 12):
        x, y, fx, fy = tiili_xy_frac(pe, pn, z)
        b = t.r.get(z, x, y)
        if b is None:
            continue
        im = np.array(Image.open(io.BytesIO(b)).convert("RGBA")).astype(np.int64)
        px, py = min(255, int(fx * 256)), min(255, int(fy * 256))
        R, G, B, A = im[py, px]
        tulos["tiilesta"][str(z)] = {"alfa": int(A), "lehtipuuosuus_pros": None if A == 0 else int((255 - A) * 10), "pituus_m": round((R * 256 + G) / 10.0, 1),
                                     "latvuspeitto_pros": int(B)}
    # Koko alueen rinteen tulos tiilestä z14: sama sääntö kaikille rinneruuduille (lähin pikseli), poikkeama lähderasterin osuudesta
    erot = []
    for e, n, _, _, os_ in Q[:: max(1, len(Q) // 150)]:
        x, y, fx, fy = tiili_xy_frac(e, n, 14)
        b = t.r.get(14, x, y)
        if b is None:
            continue
        im = np.array(Image.open(io.BytesIO(b)).convert("RGBA")).astype(np.int64)
        A = im[min(255, int(fy * 256)), min(255, int(fx * 256)), 3]
        if A > 0:
            erot.append((255 - A) * 10 - os_)
    if erot:
        tulos["z14_alfan_ero_lahderasteriin_pros_abs_max"] = round(float(np.max(np.abs(erot))), 1)
        tulos["z14_alfan_ero_lahderasteriin_pros_mediaani"] = round(float(np.median(erot)), 1)
    tulos["koodaus"] = "A = 255 - lattia((osuus + 5) / 10), eli osuus % = (255 - A) * 10, tarkkuus +-5 prosenttiyksikköä; A=0 ei metsämaata"
    return tulos


def main(polku=None):
    polku = Path(polku) if polku else ULOS / "maasto.pmtiles"
    t = Tiilet(polku)
    dem10 = gdal.Open(str(TYO / "dem10.tif"))
    dem2 = gdal.Open(str(TYO / "dem2.vrt")) if (TYO / "dem2.vrt").exists() else None
    ds = ogr.Open(str(TYO / "aoi.gpkg"))
    vesi = unary_union([swkb.loads(bytes(f.GetGeometryRef().ExportToWkb())) for f in ds.GetLayerByName("vesi")])
    pisteet = []
    korkein, ke, kn = dem_max_laatikossa(dem2 or dem10, HARJU_LAATIKKO)
    pisteet.append(pisteen_tulos("Pispalanharju", "Harjun korkein DEM 2 m:n ruutu laatikossa E 322000-326200, N 6822100-6823500 (Pispalanharju ja Pyynikinharju)",
                                 ke, kn, t, dem2, dem10))
    pisteet.append(pisteen_tulos("Näsinneulan juuri", "Tornin keskipiste (maamerkit.json)", NASINNEULA[0], NASINNEULA[1], t, dem2, dem10))
    se, sn = T4326_3067.transform(*SIILINKARI_LONLAT)
    pisteet.append(pisteen_tulos("Siilinkari", "Siilinkarin apuloisto (Väylävirasto 28843)", se, sn, t, dem2, dem10))
    (re_, rn_), (se_, sn_), etaisyys = rantapiste(vesi, NAISTENLAHTI_ANKKURI)
    pisteet.append(pisteen_tulos("Naistenlahden ranta", "Rannan lähin kohta Naistenlahden voimalaitokselle (%.0f m ankkurista), %.0f m maalle päin" % (etaisyys, RANTA_SISAANPAIN_M),
                                 se_, sn_, t, dem2, dem10))
    ae_, an_ = T4326_3067.transform(*AITOLAHTI_ANKKURI_LONLAT)
    (re_, rn_), (se_, sn_), etaisyys = rantapiste(vesi, (ae_, an_))
    pisteet.append(pisteen_tulos("Aitolahden ranta", "Rannan lähin kohta Kirjoniemen viitalle (Aitolahden väylä), %.0f m maalle päin" % RANTA_SISAANPAIN_M,
                                 se_, sn_, t, dem2, dem10))
    # Terrain-RGB:n koodaus: kvantisointi tiilistä
    kvantti = None
    meta = {}
    try:
        meta = t.r.metadata()
        meta = json.loads(meta) if isinstance(meta, (str, bytes)) else (meta or {})
        kvantti = meta.get("quantization_m")
    except Exception:  # noqa: BLE001
        pass
    x, y, _, _ = tiili_xy_frac(ke, kn, 14)
    hh, rgb = t.kuva(14, x, y)
    ok = ~((rgb[..., 0] == 0) & (rgb[..., 1] == 0) & (rgb[..., 2] == 0))
    arvo10 = np.round((hh[ok] + 10000.0) * 10).astype(np.int64)        # 0,1 m:n yksiköinä
    koodaus = {"kaava": "korkeus_m = -10000 + (R*65536 + G*256 + B) * 0,1", "offset_m": -10000.0, "kerroin_m": 0.1,
               "metadata_kvantisointi_m": kvantti, "tilkka_x_y_z14": [x, y],
               "kaikki_arvot_kvantin_monikertoja": bool(kvantti and np.all(np.mod(arvo10, int(round(kvantti * 10))) == 0)),
               "pikseleiden_aste_m": 0.1,
               "tilkan_min_m": round(float(hh[ok].min()), 1), "tilkan_max_m": round(float(hh[ok].max()), 1),
               "tavoite_kvantin_enimmaisvirhe_m": None if not kvantti else round(kvantti / 2.0, 2)}
    rng = np.random.default_rng(20261026)
    otos = {}
    vyohyke = None
    try:
        from lataa import lataa_aoi
        vyohyke = lataa_aoi()[2]
    except Exception as e:  # noqa: BLE001
        loki("rantavyöhykettä ei saatu (%s)" % repr(e)[:120])
    if dem2 is not None:
        otos["z14_vs_dem2"] = ruutuotos(t, dem2, 14, OTOS_Z14, rng, dem_vert=dem10, vyohyke=vyohyke)
    for z in (8, 10, 12, 13):
        otos["z%d_vs_dem10" % z] = ruutuotos(t, dem10, z, OTOS_MUUT, rng)
    ero_arvot = [p.get("ero_z14_dem2_m") for p in pisteet if p.get("ero_z14_dem2_m") is not None]
    ero_dem10 = [p.get("ero_z14_dem10_m") for p in pisteet if p.get("ero_z14_dem10_m") is not None]
    try:
        puusto = puustotarkistus()
    except Exception as e:  # noqa: BLE001
        puusto = {"tila": "virhe: " + repr(e)[:200]}
    tulos = {"tehty": nyt_iso(), "tiedosto": str(polku.name), "puusto": puusto, "pisteet": pisteet, "koodaus": koodaus, "otokset": otos,
             "yhteenveto": {"pisteita": len(pisteet), "suurin_abs_ero_z14_dem2_m": round(max((abs(v) for v in ero_arvot), default=float("nan")), 2),
                            "suurin_abs_ero_z14_dem10_m": round(max((abs(v) for v in ero_dem10), default=float("nan")), 2),
                            "kaikki_alle_1_m_dem2": bool(ero_arvot and all(abs(v) < 1.0 for v in ero_arvot))}}
    (TYO / "maastotarkistus.json").write_text(json.dumps(tulos, ensure_ascii=False, indent=1), encoding="utf-8")
    loki("maastotarkistus: suurin ero z14 / DEM 2 m %.2f m, viidestä pisteestä kaikki alle 1 m: %s" % (
        tulos["yhteenveto"]["suurin_abs_ero_z14_dem2_m"], tulos["yhteenveto"]["kaikki_alle_1_m_dem2"]))
    return tulos


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
