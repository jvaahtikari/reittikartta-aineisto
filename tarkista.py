#!/usr/bin/python3
"""Tarkistaa valmiin paketin (hakemisto ulos/) ja kirjoittaa tulokset tiedostoon ulos/tarkistus.json.

Ajo:  python3 tarkista.py            tarkistaa ja kirjoittaa tulokset, palauttaa 1 jos jokin pakollinen tarkistus epäonnistuu
      python3 tarkista.py --kevyt    ohittaa korkeusmallitarkistuksen (ei tarvitse tyo/-hakemistoa)

Tarkistukset vastaavat määrittelyn hyväksymiskriteerejä 1-6 niiltä osin kuin ne voidaan mitata paketista:
 1  korkeudet tunnetuissa pisteissä (järven pinta, Pispalanharju, Näsinneulan juuri), mitataan korkeusmallista
    ja paketin maastotiilistä
 2  rakennusten määrä
 3  valaistut turvalaitteet: valotunnus ja sektorit paketin vektoritiilissä, vertailualue Mustalahti
 4  osoitteiden määrä ja kolme testiosoitetta
 5  paketin koko ja yhden puhelinnäkymän tiilimäärä
 6  aineisto.json:n rakenne, tiedostokoot ja tarkistussummat
"""
import gzip
import hashlib
import json
import math
import sys
from collections import Counter
from pathlib import Path

JUURI = Path(__file__).resolve().parent
ULOS = JUURI / "ulos"
TYO = JUURI / "tyo"

from pmtiles.reader import MmapSource, Reader, all_tiles  # noqa: E402
import mapbox_vector_tile  # noqa: E402

TULOKSET = {"tarkistukset": {}, "huomiot": []}
VIRHEITA = []


def kirjaa(nimi, ok, **tiedot):
    TULOKSET["tarkistukset"][nimi] = dict(ok=bool(ok), **tiedot)
    print(("OK    " if ok else "VIRHE ") + nimi + "  " + json.dumps(tiedot, ensure_ascii=False, default=str)[:300])
    if not ok:
        VIRHEITA.append(nimi)


def tiili_xy(lon, lat, z):
    n = 2 ** z
    x = int((lon + 180) / 360 * n)
    y = int((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n)
    return x, y


def haversine(lon1, lat1, lon2, lat2):
    r = 6371008.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


class Tiilet:
    def __init__(self, polku):
        self.f = open(polku, "rb")
        self.r = Reader(MmapSource(self.f))
        self.h = self.r.header()

    def raaka(self, z, x, y):
        return self.r.get(z, x, y)

    def mvt(self, z, x, y):
        t = self.r.get(z, x, y)
        return mapbox_vector_tile.decode(gzip.decompress(t)) if t else {}


def mvt_piirteet(d, kerros, z, x, y):
    """Palauttaa (lon, lat, ominaisuudet) tiilen pistepiirteille."""
    out = []
    k = d.get(kerros)
    if not k:
        return out
    n = 2 ** z
    ext = k.get("extent", 4096)
    for f in k["features"]:
        g = f["geometry"]
        pts = [g["coordinates"]] if g["type"] == "Point" else (g["coordinates"] if g["type"] == "MultiPoint" else [])
        for px, py in pts:
            lon = (x + px / ext) / n * 360 - 180
            lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (y + 1 - py / ext) / n))))
            out.append((lon, lat, f["properties"]))
    return out


def tarkista_aineisto_json():
    from jsonschema import Draft202012Validator
    a = json.load(open(ULOS / "aineisto.json", encoding="utf-8"))
    skeema = {
        "type": "object",
        "required": ["versio", "paiva", "alue", "koordinaatistot", "tiedostot", "tiilet", "lahteet", "kayttorajoitukset",
                     "lahdemerkinta_yhteensa", "kerrosmaarat"],
        "properties": {
            "versio": {"type": "integer"},
            "paiva": {"type": "string", "pattern": r"^\d{4}-\d{2}-\d{2}$"},
            "alue": {"type": "object", "required": ["bbox_wgs84", "bbox_epsg3067"],
                     "properties": {"bbox_wgs84": {"type": "array", "minItems": 4, "maxItems": 4, "items": {"type": "number"}}}},
            "tiedostot": {"type": "array", "minItems": 3,
                          "items": {"type": "object", "required": ["nimi", "tavua", "sha256"],
                                    "properties": {"tavua": {"type": "integer", "minimum": 1},
                                                   "sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"}}}},
            "tiilet": {"type": "object", "required": ["vektori", "maasto", "puusto"]},
            "lahteet": {"type": "array", "minItems": 7,
                        "items": {"type": "object", "required": ["id", "nimi", "tuottaja", "lisenssi", "lahdemerkinta"],
                                  "properties": {"lahdemerkinta": {"type": "string", "minLength": 20}}}},
            "lahdemerkinta_yhteensa": {"type": "string", "minLength": 100},
        },
    }
    virheet = [e.message for e in Draft202012Validator(skeema).iter_errors(a)]
    for t in a.get("tiedostot", []):
        p = ULOS / t["nimi"]
        if not p.exists():
            virheet.append("tiedosto puuttuu: " + t["nimi"])
            continue
        if p.stat().st_size != t["tavua"]:
            virheet.append("koko ei täsmää: " + t["nimi"])
        h = hashlib.sha256()
        with open(p, "rb") as f:
            for osa in iter(lambda: f.read(1 << 20), b""):
                h.update(osa)
        if h.hexdigest() != t["sha256"]:
            virheet.append("tarkistussumma ei täsmää: " + t["nimi"])
    for l in a.get("lahteet", []):
        if l["id"] == "traficom_syvyys" and "Ei navigointikäyttöön" not in l["lahdemerkinta"]:
            virheet.append("Traficomin lähdemerkinnästä puuttuu navigointikäyttökielto")
        if not l.get("ehtoteksti_sanatarkasti"):
            virheet.append("lähteeltä %s puuttuu sanatarkka ehtoteksti" % l["id"])
    kirjaa("6_aineisto_json", not virheet, virheita=virheet, lahteita=len(a.get("lahteet", [])))
    return a


def tarkista_koot(a):
    kok = sum(p.stat().st_size for p in ULOS.rglob("*") if p.is_file() and p.name != "tarkistus.json")
    pmt = sum((ULOS / n).stat().st_size for n in ("nasijarvi.pmtiles", "maasto.pmtiles", "puusto.pmtiles"))
    kirjaa("5_paketin_koko", kok < 150e6, kokonaiskoko_mt=round(kok / 1e6, 1), pmtiles_yhteensa_mt=round(pmt / 1e6, 1),
           raja_mt=150)


def tarkista_puhelinnakyma(vek, mas, pus):
    """Zoom 14, 390 x 844 px, 256 px:n ruudut. Pahin tapaus on 3 x 5 ruutua (ruudukon vastaava osuus)."""
    def koot(t, z):
        d = {}
        for (zz, x, y), data in all_tiles(MmapSource(t.f)):
            if zz == z:
                d[(x, y)] = len(data)
        return d
    kv, km, kp = koot(vek, 14), koot(mas, 14), koot(pus, 14)
    xs = [k[0] for k in kv]
    ys = [k[1] for k in kv]
    paras = (0, None)
    parhaat = {"vektori": (0, None), "maasto": (0, None), "puusto": (0, None), "yhteensa_ilman_puustoa": (0, None),
               "yhteensa_puustolla": (0, None)}
    for x0 in range(min(xs), max(xs) - 1):
        for y0 in range(min(ys), max(ys) - 3):
            s = {"vektori": 0, "maasto": 0, "puusto": 0}
            for dx in range(3):
                for dy in range(5):
                    k = (x0 + dx, y0 + dy)
                    s["vektori"] += kv.get(k, 0)
                    s["maasto"] += km.get(k, 0)
                    s["puusto"] += kp.get(k, 0)
            for nimi, arvo in (("vektori", s["vektori"]), ("maasto", s["maasto"]), ("puusto", s["puusto"]),
                               ("yhteensa_ilman_puustoa", s["vektori"] + s["maasto"]),
                               ("yhteensa_puustolla", s["vektori"] + s["maasto"] + s["puusto"])):
                if arvo > parhaat[nimi][0]:
                    parhaat[nimi] = (arvo, (x0, y0))
    # Tampereen keskusta erikseen
    x0, y0 = tiili_xy(23.7610, 61.4978, 14)
    keskusta = sum(kv.get((x0 - 1 + dx, y0 - 2 + dy), 0) + km.get((x0 - 1 + dx, y0 - 2 + dy), 0) for dx in range(3) for dy in range(5))
    kirjaa("5_puhelinnakyma_z14", parhaat["yhteensa_ilman_puustoa"][0] < 5e6,
           pahin_vektori_ja_maasto_mt=round(parhaat["yhteensa_ilman_puustoa"][0] / 1e6, 2),
           pahin_vektori_mt=round(parhaat["vektori"][0] / 1e6, 2), pahin_maasto_mt=round(parhaat["maasto"][0] / 1e6, 2),
           pahin_puuston_kanssa_mt=round(parhaat["yhteensa_puustolla"][0] / 1e6, 2),
           tampereen_keskusta_vektori_ja_maasto_mt=round(keskusta / 1e6, 2), ruutuja="3 x 5 (390 x 844 px, 256 px:n ruudut)",
           raja_mt=5, huomio="tiilikoot gzip-pakattuina, kuten ne siirtyvät verkon yli ilman HTTP-pakkausta")


def tarkista_valot(vek):
    # Mustalahden vertailualue: 23,72-23,77 / 61,49-61,53 -> haetaan z16-ruudut
    # Väyläviraston WFS tulkitsee bboxin EPSG:3067-tasossa: kulmapisteiden ympäri laskettu suorakulmio.
    # Sama tulkinta käytetään tässä, jotta tulos on vertailukelpoinen vaiheen 0 näytteen (7 kohdetta) kanssa.
    import pyproj
    w, s, e, n = 23.72, 61.49, 23.77, 61.53
    t = pyproj.Transformer.from_crs(4326, 3067, always_xy=True)
    kulmat = [t.transform(a, b) for a, b in ((w, s), (w, n), (e, s), (e, n))]
    ex0, ex1 = min(k[0] for k in kulmat), max(k[0] for k in kulmat)
    ey0, ey1 = min(k[1] for k in kulmat), max(k[1] for k in kulmat)
    x0, y1 = tiili_xy(w - 0.01, s - 0.01, 16)
    x1, y0 = tiili_xy(e + 0.01, n + 0.01, 16)
    laitteet = {}
    for x in range(x0, x1 + 1):
        for y in range(y0, y1 + 1):
            d = vek.mvt(16, x, y)
            for lon, lat, p in mvt_piirteet(d, "turvalaite", 16, x, y):
                ex, ey = t.transform(lon, lat)
                if ex0 <= ex <= ex1 and ey0 <= ey <= ey1:
                    laitteet[p["numero"]] = (lon, lat, p)
    valaistut = {k: v for k, v in laitteet.items() if v[2].get("valaistu") == "K"}
    ilman = [k for k, v in valaistut.items() if not v[2].get("valotunnus")]
    ilman_sek = [k for k, v in valaistut.items() if not v[2].get("sektorit")]
    kirjaa("3_mustalahden_vertailualue", len(laitteet) == 7 and len(valaistut) == 5 and not ilman,
           turvalaitteita=len(laitteet), valaistuja=len(valaistut), ilman_valotunnusta=ilman, ilman_sektoreita=ilman_sek,
           odotettu="7 turvalaitetta, joista 5 valaistua (WFS-bbox-tulkinta, ks. koodin kommentti)",
           valaistut=[{"numero": k, "nimi": v[2].get("nimi"), "valotunnus": v[2].get("valotunnus"),
                       "sektorit": v[2].get("sektorit")} for k, v in sorted(valaistut.items())])
    # Koko alue: jokaisella valaistulla turvalaitteella valotunnus (z16-ruudut kattavat kaikki pistekohteet)
    kaikki = {}
    for (z, x, y), data in all_tiles(MmapSource(vek.f)):
        if z != 16:
            continue
        d = mapbox_vector_tile.decode(gzip.decompress(data))
        for lon, lat, p in mvt_piirteet(d, "turvalaite", z, x, y):
            kaikki[p["numero"]] = p
    val = {k: p for k, p in kaikki.items() if p.get("valaistu") == "K"}
    ilman_k = sorted(k for k, p in val.items() if not p.get("valotunnus"))
    ilman_s = sorted(k for k, p in val.items() if not p.get("sektorit"))
    kirjaa("3_koko_alue_valotunnukset", not ilman_k and not ilman_s, turvalaitteita=len(kaikki), valaistuja=len(val),
           ilman_valotunnusta=ilman_k, ilman_sektoreita=ilman_s,
           sektoreita_yhteensa=sum(len(json.loads(p["sektorit"])) for p in val.values() if p.get("sektorit")))


def tarkista_rakennukset_osoitteet(vek):
    rak = Counter()
    osoitteet = {}
    for (z, x, y), data in all_tiles(MmapSource(vek.f)):
        if z != 14:
            continue
        d = mapbox_vector_tile.decode(gzip.decompress(data))
        if "rakennus" in d:
            rak["z14_piirretta"] += len(d["rakennus"]["features"])
    kerrosmaarat = json.load(open(ULOS / "aineisto.json", encoding="utf-8"))["kerrosmaarat"]
    kirjaa("2_rakennukset", kerrosmaarat["rakennus"] > 20000, rakennuksia=kerrosmaarat["rakennus"],
           rakennuksia_z14_ruuduissa=rak["z14_piirretta"], raja=20000,
           huomio="z14-luku sisältää ruutujen reunoilla katkaistut kohteet kahteen kertaan")
    # Osoitteet
    z = 16
    testit = [("Laiturikatu 8", 23.746282, 61.5053, "Mustalahden satama"),
              ("Rantatie 3", 23.723902, 61.502643, "Santalahti, Näsijärven länsiranta"),
              ("Siilinkari 2", 23.753915, 61.517575, "Siilinkarin majakkasaari")]
    tulokset = []
    for nimi, lon0, lat0, selite in testit:
        x, y = tiili_xy(lon0, lat0, z)
        loydetty = None
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                d = vek.mvt(z, x + dx, y + dy)
                for lon, lat, p in mvt_piirteet(d, "osoite", z, x + dx, y + dy):
                    if p.get("osoite") == nimi:
                        loydetty = (lon, lat, p)
        rec = {"osoite": nimi, "selite": selite, "loytyi": bool(loydetty)}
        if loydetty:
            rec.update(lon=round(loydetty[0], 6), lat=round(loydetty[1], 6), postinumero=loydetty[2].get("postinumero"))
            # Riippumaton vertailu: MML:n saman nimiset tieviivat (osoite) tai Väyläviraston turvalaite (Siilinkari)
            katu = nimi.rsplit(" ", 1)[0]
            parhaat = None
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    d = vek.mvt(z, x + dx, y + dy)
                    k = d.get("tie")
                    if not k:
                        continue
                    n = 2 ** z
                    for f in k["features"]:
                        if (f["properties"].get("nimi") or "").lower() != katu.lower():
                            continue
                        g = f["geometry"]
                        linjat = g["coordinates"] if g["type"] == "MultiLineString" else [g["coordinates"]]
                        for l in linjat:
                            for px, py in l:
                                ll = ((x + dx + px / 4096) / n * 360 - 180,
                                      math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (y + dy + 1 - py / 4096) / n)))))
                                dd = haversine(loydetty[0], loydetty[1], ll[0], ll[1])
                                if parhaat is None or dd < parhaat:
                                    parhaat = dd
            if parhaat is not None:
                rec["etaisyys_samannimiseen_tiehen_m"] = round(parhaat, 1)
            if nimi == "Siilinkari 2":
                a = vek.mvt(z, x, y)
                for lon, lat, p in mvt_piirteet(a, "turvalaite", z, x, y):
                    if p.get("nimi") == "Siilinkari":
                        rec["etaisyys_turvalaitteeseen_m"] = round(haversine(loydetty[0], loydetty[1], lon, lat), 1)
        tulokset.append(rec)
    lkm = json.load(open(ULOS / "aineisto.json", encoding="utf-8"))["kerrosmaarat"]["osoite"]
    ok = lkm > 20000 and all(t["loytyi"] for t in tulokset)
    for t in tulokset:
        if "etaisyys_samannimiseen_tiehen_m" in t and t["etaisyys_samannimiseen_tiehen_m"] > 120:
            ok = False
        if "etaisyys_turvalaitteeseen_m" in t and t["etaisyys_turvalaitteeseen_m"] > 30:
            ok = False
    kirjaa("4_osoitteet", ok, osoitepisteita=lkm, testiosoitteet=tulokset)


def tarkista_korkeudet(mas):
    from osgeo import gdal, ogr, osr
    import numpy as np
    import pyproj
    gdal.UseExceptions()
    dem10 = gdal.Open(str(TYO / "dem10.tif"))
    dem2 = gdal.Open(str(TYO / "dem2.vrt")) if (TYO / "dem2.vrt").exists() else None
    t = pyproj.Transformer.from_crs(4326, 3067, always_xy=True)

    def nayte(ds, lon, lat):
        x, y = t.transform(lon, lat)
        gt = ds.GetGeoTransform()
        px, py = int((x - gt[0]) / gt[1]), int((y - gt[3]) / gt[5])
        if not (0 <= px < ds.RasterXSize and 0 <= py < ds.RasterYSize):
            return None
        v = ds.GetRasterBand(1).ReadAsArray(px, py, 1, 1)[0, 0]
        nd = ds.GetRasterBand(1).GetNoDataValue()
        return None if (nd is not None and v == nd) or v < -100 else float(v)

    def tiilesta(lon, lat, z=14):
        x, y = tiili_xy(lon, lat, z)
        raaka = mas.raaka(z, x, y)
        if raaka is None:
            return None
        from PIL import Image
        import io
        im = np.array(Image.open(io.BytesIO(raaka)).convert("RGB")).astype(np.int64)
        n = 2 ** z
        fx = ((lon + 180) / 360 * n - x)
        fy = ((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n - y)
        px, py = min(255, int(fx * 256)), min(255, int(fy * 256))
        r, g, b = im[py, px]
        return None if (r, g, b) == (0, 0, 0) else -10000 + (r * 65536 + g * 256 + b) * 0.1

    # 1 järven pinta: otos vesialueen sisältä
    aoi_ds = ogr.Open(str(TYO / "aoi.gpkg"))
    vesi = aoi_ds.GetLayerByName("vesi")
    vesi_piirre = vesi.GetNextFeature()
    geom = vesi_piirre.GetGeometryRef()
    rng = np.random.default_rng(1)
    minx, maxx, miny, maxy = geom.GetEnvelope()
    arvot = []
    while len(arvot) < 400:
        x, y = rng.uniform(minx, maxx), rng.uniform(miny, maxy)
        p = ogr.Geometry(ogr.wkbPoint)
        p.AddPoint_2D(x, y)
        if geom.Contains(p):
            gt = dem10.GetGeoTransform()
            v = dem10.GetRasterBand(1).ReadAsArray(int((x - gt[0]) / gt[1]), int((y - gt[3]) / gt[5]), 1, 1)[0, 0]
            if v > -100:
                arvot.append(float(v))
    mediaani = float(np.median(arvot))
    kirjaa("1_jarven_pinta", abs(mediaani - 95.5) <= 3, mediaani_m=round(mediaani, 2), min_m=round(min(arvot), 2),
           max_m=round(max(arvot), 2), otos=len(arvot), odotettu="noin 95 m (N2000), toleranssi 3 m")
    # Tiilestä: Näsijärven keskiosa
    tl = tiilesta(23.7500, 61.5075)
    kirjaa("1_jarven_pinta_tiilesta", tl is not None and abs(tl - 95.5) <= 3, arvo_m=tl, lon=23.75, lat=61.5075,
           huomio="Mustalahden edusta, rantavyöhykkeen tiili. Kokonaan vesialueella olevia tiiliä ei ole paketissa.")

    # 1 Pispalanharju: ikkunan korkein piste
    w = (23.680, 61.480, 23.745, 61.515)
    x0, y0 = t.transform(w[0], w[1])
    x1, y1 = t.transform(w[2], w[3])
    gt = dem10.GetGeoTransform()
    a = dem10.GetRasterBand(1).ReadAsArray(int((x0 - gt[0]) / gt[1]), int((y1 - gt[3]) / gt[5]),
                                           int((x1 - x0) / gt[1]), int((y1 - y0) / abs(gt[5])))
    iy, ix = np.unravel_index(np.argmax(a), a.shape)
    px = x0 + (ix + 0.5) * gt[1]
    py = y1 - (iy + 0.5) * abs(gt[5])
    inv = pyproj.Transformer.from_crs(3067, 4326, always_xy=True)
    lon, lat = inv.transform(px, py)
    h10 = float(a[iy, ix])
    h2 = nayte(dem2, lon, lat) if dem2 else None
    ht = tiilesta(lon, lat)
    kirjaa("1_pispalanharju", h10 > 150, lon=round(lon, 5), lat=round(lat, 5), korkeus_dem10_m=round(h10, 1),
           korkeus_dem2_m=None if h2 is None else round(h2, 1), korkeus_tiilesta_m=None if ht is None else round(ht, 1),
           haku="DEM 10 m:n korkein piste suorakulmiossa lon 23,680-23,745 ja lat 61,480-61,515", raja="yli 150 m")
    # Näsinneula: Särkänniemen kärki, otetaan kolmen pisteen vaihteluväli
    pisteet = {"Näsinneulan juuri (arvio)": (23.7434, 61.5031), "Särkänniemen rantatasanne": (23.7458, 61.5042),
               "Näsilinnankadun ja Satamakadun risteys": (23.7462, 61.5001)}
    nn = {}
    for nimi, (lo, la) in pisteet.items():
        nn[nimi] = {"lon": lo, "lat": la, "dem10_m": None if nayte(dem10, lo, la) is None else round(nayte(dem10, lo, la), 1),
                    "dem2_m": None if not dem2 or nayte(dem2, lo, la) is None else round(nayte(dem2, lo, la), 1),
                    "tiilesta_m": None if tiilesta(lo, la) is None else round(tiilesta(lo, la), 1)}
    v = nn["Näsinneulan juuri (arvio)"]
    ok = v["dem2_m"] is not None and 95 <= v["dem2_m"] <= 110
    kirjaa("1_nasinneulan_juuri", ok, pisteet=nn, huomio="Koordinaatit ovat arvioita, riippumatonta mittaustulosta ei ollut käytettävissä. Hyväksyntäehto: 95-110 m, eli enintään noin 15 m järven pinnan yläpuolella")


def main(argv):
    kevyt = "--kevyt" in argv
    a = tarkista_aineisto_json()
    tarkista_koot(a)
    vek = Tiilet(ULOS / "nasijarvi.pmtiles")
    mas = Tiilet(ULOS / "maasto.pmtiles")
    pus = Tiilet(ULOS / "puusto.pmtiles")
    tarkista_rakennukset_osoitteet(vek)
    tarkista_valot(vek)
    tarkista_puhelinnakyma(vek, mas, pus)
    if not kevyt and (TYO / "dem10.tif").exists():
        tarkista_korkeudet(mas)
    else:
        TULOKSET["huomiot"].append("Korkeusmallitarkistus ohitettiin (--kevyt tai tyo/dem10.tif puuttuu)")
    TULOKSET["epaonnistuneet"] = VIRHEITA
    (ULOS / "tarkistus.json").write_text(json.dumps(TULOKSET, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print("Epäonnistuneet tarkistukset:", VIRHEITA or "ei yhtään")
    return 1 if VIRHEITA else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
