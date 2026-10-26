#!/usr/bin/env python3
"""Vaihe 1: lataa lähteet ja rajaa ne Näsijärven alueeseen (hakemisto tyo/).

Ajo:  python3 lataa.py            kaikki vaiheet
      python3 lataa.py mtk aoi    vain nimetyt vaiheet
      python3 lataa.py --pakota   tee kaikki uudelleen, vaikka tulos olisi jo olemassa

Vaiheet suoritetaan tässä järjestyksessä:
  indeksit   Paitulin lehtijakoindeksit (korkeusmallit, maastotietokanta)
  mtk        Maastotietokannan lehtikohtaiset Shapefile-paketit hakualueelle
  aoi        Näsijärven vesialue, 3 km maapuskuri ja lopullinen rajauslaatikko
  mtkrajaus  Maastotietokannan tasot rajattuna alueeseen (tyo/mtk.gpkg)
  kiinteisto Kiinteistörajat ja palstatunnukset lehdittäin
  dvv        DVV:n osoiteaineisto
  dem10      Korkeusmalli 10 m
  dem2       Korkeusmalli 2 m rantavyöhykkeeltä
  luke       Luken puuston keskipituus, latvuspeitto ja lajitilavuudet (lehtipuuosuus)
  corine     SYKEn Corine 2018 -rasteri (ruovikot, valinnainen)
  vayla      Väyläviraston WFS-kerrokset
  traficom   Traficomin syvyysaineisto

Jokaisen lähteen osoite, hakuhetki, siirretty tavumäärä ja kesto kirjataan tiedostoon
tyo/lataus_loki.json. Jos jokin lähde epäonnistuu, virhe kirjataan ja ajo jatkuu seuraavaan.
"""
import concurrent.futures as cf
import json
import math
import os
import re
import sys
import time
import traceback
import urllib.parse
import zipfile
from pathlib import Path

from asetukset import *  # noqa: F401,F403

from osgeo import gdal, ogr, osr  # noqa: E402
from shapely import wkb as swkb  # noqa: E402
from shapely.geometry import Point, box, mapping, shape  # noqa: E402
from shapely.ops import transform, unary_union  # noqa: E402
from shapely.prepared import prep  # noqa: E402
import pyproj  # noqa: E402

gdal.UseExceptions()
ogr.UseExceptions()
gdal.SetConfigOption("CPL_VSIL_CURL_USE_HEAD", "YES")
gdal.SetConfigOption("GDAL_HTTP_USERAGENT", KAYTTAJA)

LOKIPOLKU = TYO / "lataus_loki.json"
TAULU_4326_3067 = pyproj.Transformer.from_crs(4326, 3067, always_xy=True)
TAULU_3067_4326 = pyproj.Transformer.from_crs(3067, 4326, always_xy=True)


# ----------------------------------------------------------------------------------------
# Lokin pito
# ----------------------------------------------------------------------------------------
def lokiin(lahde, **tiedot):
    data = lue_json(LOKIPOLKU, {})
    ed = data.get(lahde, {})
    ed.update(tiedot)
    data[lahde] = ed
    kirjoita_json(LOKIPOLKU, data)


def rinnakkain(tehtavat, toiminto, saikeita=4):
    """Aja toiminto jokaiselle tehtävälle rinnakkain. Palauttaa (tavut, sekunnit, ladattuja)."""
    tavut = 0
    ladattu = 0
    alku = time.time()
    with cf.ThreadPoolExecutor(saikeita) as ex:
        for n, dt, uusi in ex.map(toiminto, tehtavat):
            tavut += n if uusi else 0
            ladattu += 1 if uusi else 0
    return tavut, time.time() - alku, ladattu


# ----------------------------------------------------------------------------------------
# Indeksit ja lehtijako
# ----------------------------------------------------------------------------------------
INDEKSIT = {
    "dem2m": "mml/dem2m/2008_latest/dem2m",
    "dem10m": "mml/dem10m/2019/dem10m",
    "mtk": "mml/maastotietokanta/2025/shp/mtk_2025",
}


def vaihe_indeksit():
    n = 0
    for nimi, pohja in INDEKSIT.items():
        for pääte in ("shp", "shx", "dbf", "prj"):
            b, _, _ = hae(PAITULI + pohja + "." + pääte, RAAKA / "indeksi" / (nimi + "." + pääte), kerro=False)
            n += b
    lokiin("indeksit", osoite=PAITULI + "mml/{dem2m,dem10m,maastotietokanta}/…", haettu=nyt_iso(), tavua=n)


def lehdet(indeksi, bbox):
    """Palauttaa indeksin lehdet (label, path), joiden alue leikkaa bboxin."""
    ds = ogr.Open(str(RAAKA / "indeksi" / (indeksi + ".shp")))
    kerros = ds.GetLayer(0)
    kerros.SetSpatialFilterRect(*bbox)
    tulos = []
    for ft in kerros:
        tulos.append({"label": ft.GetField("label"), "path": ft.GetField("path"),
                      "wkt": ft.GetGeometryRef().ExportToWkt()})
    tulos.sort(key=lambda d: d["label"])
    return tulos


def lehdet_geometrialla(indeksi, geom):
    """Kuten lehdet(), mutta suodattaa tarkasti shapely-geometrialla."""
    p = prep(geom)
    tulos = []
    for d in lehdet(indeksi, geom.bounds):
        if p.intersects(shape_wkt(d["wkt"])):
            tulos.append(d)
    return tulos


def shape_wkt(wkt):
    from shapely import wkt as swkt
    return swkt.loads(wkt)


# ----------------------------------------------------------------------------------------
# Maastotietokanta (Shapefile-lehdet)
# ----------------------------------------------------------------------------------------
def vaihe_mtk():
    """Lataa maastotietokannan lehtikohtaiset paketit hakualueelle.

    Koko Suomen GeoPackage-tiedostoja ei ladata: /vsicurl/-luku mitattiin ja todettiin liian
    hitaaksi (ks. RAPORTTI_vaihe1.md), joten käytetään lehtikohtaisia Shapefile-paketteja.
    """
    ls = lehdet("mtk", HAKUBBOX)
    loki("MTK-lehtiä hakualueella:", len(ls))

    def yksi(d):
        return hae(PAITULI + d["path"], RAAKA / "mtk" / (d["label"] + ".shp.zip"), kerro=False)

    tavut, dt, n = rinnakkain(ls, yksi, 4)
    lokiin("mtk", osoite=PAITULI + "mml/maastotietokanta/2025/shp/<1:200k>/<1:100k>/<lehti>.shp.zip",
           haettu=nyt_iso(), lehtia=len(ls), tavua=tavut, sekuntia=round(dt, 1),
           lehtilista=[d["label"] for d in ls],
           huomio="Lehtijako: mtk_2025.shp; lehti on 12 x 12 km (L = länsi- ja R = itäpuolisko 1:25 000 -lehdestä)")
    loki("MTK ladattu: %.0f Mt, %.0f s" % (tavut / 1e6, dt))


def mtk_zip_polut():
    return sorted((RAAKA / "mtk").glob("*.shp.zip"))


def lue_kerros(shp_polku, where=None, spat=None):
    """Generaattori: (shapely-geometria, ominaisuudet) Shapefilestä."""
    try:
        ds = ogr.Open(shp_polku)
    except RuntimeError:
        return
    if ds is None:
        return
    k = ds.GetLayer(0)
    if where:
        k.SetAttributeFilter(where)
    if spat:
        k.SetSpatialFilterRect(*spat)
    defn = k.GetLayerDefn()
    nimet = [defn.GetFieldDefn(i).GetName() for i in range(defn.GetFieldCount())]
    for ft in k:
        g = ft.GetGeometryRef()
        if g is None:
            continue
        try:
            geom = swkb.loads(bytes(g.ExportToWkb()))
        except Exception:  # noqa: BLE001
            continue
        yield geom, {n: ft.GetField(i) for i, n in enumerate(nimet)}


def zip_kerros(zippi, etuliite, laji):
    """Polku /vsizip/-kerrokseen, esim. etuliite 'm', laji 'p' -> m_<lehti>_p.shp"""
    lehti = Path(zippi).name.replace(".shp.zip", "")
    return "/vsizip/%s/%s_%s_%s.shp" % (zippi, etuliite, lehti, laji)


# ----------------------------------------------------------------------------------------
# Alue (AOI)
# ----------------------------------------------------------------------------------------
def vaihe_aoi():
    siemen = Point(*TAULU_4326_3067.transform(*SIEMENPISTE_WGS84))
    palat = []
    for z in mtk_zip_polut():
        for g, p in lue_kerros(zip_kerros(z, "m", "p"), where="LUOKKA = 36200"):
            if g.area > 0:
                palat.append(g)
    loki("Järvipolygoneja hakualueella:", len(palat))
    # Lehtien rajalla katkenneet polygonit yhdistyvät, koska rajapisteet ovat täsmälleen samat.
    yhd = unary_union(palat)
    osat = sorted(getattr(yhd, "geoms", [yhd]), key=lambda g: -g.area)
    valittu = None
    for o in osat:
        if o.contains(siemen):
            valittu = o
            break
    if valittu is None:
        valittu = min(osat, key=lambda g: g.distance(siemen))
    # Muroleen kanava jakaa vesistön: liitetään mukaan pääaltaasta enintään LIITOSETAISYYS_M
    # päässä olevat suuret vesialueet, jotta kanavan toinen puoli ja Ruoveden suunta tulevat mukaan.
    kevyt = valittu.simplify(10)
    osat_mukaan = [valittu] + [o for o in osat if o is not valittu and o.area > 1e6
                               and o.simplify(10).distance(kevyt) < LIITOSETAISYYS_M]
    loki("Mukaan liitetyt vesialueet: %d (%s km²)" % (
        len(osat_mukaan), ", ".join("%.0f" % (o.area / 1e6) for o in osat_mukaan)))
    vesi = unary_union(osat_mukaan).intersection(box(*AOI_RAJAUS)).buffer(0)
    loki("Vesialue rajauksen jälkeen: %.1f km², saaria %d" % (
        vesi.area / 1e6, sum(len(p.interiors) for p in getattr(vesi, "geoms", [vesi]))))
    # Puskurit lasketaan kevennetystä reunasta (3 m), koska tarkkuus on tässä muutenkin metreissä.
    kevyt_vesi = vesi.simplify(3)
    puskuri = kevyt_vesi.buffer(RANTAPUSKURI_M, 16)
    alue = puskuri.intersection(box(*AOI_RAJAUS)).buffer(0).simplify(5)
    vyohyke = kevyt_vesi.boundary.buffer(RANTAVYOHYKE_M, 8).intersection(alue).buffer(0).simplify(5)
    x0, y0, x1, y1 = alue.bounds
    bbox = (math.floor(x0 / 100) * 100, math.floor(y0 / 100) * 100,
            math.ceil(x1 / 100) * 100, math.ceil(y1 / 100) * 100)
    lonlat = transform(TAULU_3067_4326.transform, alue)
    bb4326 = lonlat.bounds
    tiedot = {
        "bbox_3067": list(bbox),
        "bbox_4326": [round(v, 5) for v in bb4326],
        "maarittelyn_bbox_3067": list(MAARITTELY_BBOX),
        "vesialue_km2": round(vesi.area / 1e6, 1),
        "alue_km2": round(alue.area / 1e6, 1),
        "rantavyohyke_km2": round(vyohyke.area / 1e6, 1),
        "rantapuskuri_m": RANTAPUSKURI_M,
        "rantavyohyke_m": RANTAVYOHYKE_M,
        "siemenpiste_wgs84": list(SIEMENPISTE_WGS84),
        "rantaviivan_pituus_km": round(vesi.boundary.length / 1e3, 0),
        "laatija": nyt_iso(),
    }
    polku = TYO / "aoi.gpkg"
    if polku.exists():
        polku.unlink()
    ds = ogr.GetDriverByName("GPKG").CreateDataSource(str(polku))
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(3067)
    for nimi, g in (("vesi", vesi), ("alue", alue), ("vyohyke", vyohyke)):
        k = ds.CreateLayer(nimi, srs, ogr.wkbMultiPolygon)
        ft = ogr.Feature(k.GetLayerDefn())
        ft.SetGeometry(ogr.CreateGeometryFromWkb(swkb.dumps(moni(g))))
        k.CreateFeature(ft)
    ds = None
    kirjoita_json(TYO / "aoi.json", tiedot)
    loki("AOI valmis:", json.dumps(tiedot, ensure_ascii=False))
    lokiin("aoi", kuvaus="Näsijärven vesialue Maastotietokannan järvipolygoneista (luokka 36200) ja siihen "
           "enintään %d m päässä liittyvät vesialueet, 3 km maapuskuri" % LIITOSETAISYYS_M,
           haettu=nyt_iso(), **tiedot)


def moni(g):
    from shapely.geometry import MultiPolygon
    if g.geom_type == "MultiPolygon":
        return g
    if g.geom_type == "Polygon":
        return MultiPolygon([g])
    return MultiPolygon([p for p in getattr(g, "geoms", []) if p.geom_type == "Polygon"])


def lataa_aoi():
    """Palauttaa (vesi, alue, vyohyke, tiedot) shapely-geometrioina."""
    ds = ogr.Open(str(TYO / "aoi.gpkg"))
    ulos = {}
    for nimi in ("vesi", "alue", "vyohyke"):
        k = ds.GetLayerByName(nimi)
        ft = k.GetNextFeature()
        ulos[nimi] = swkb.loads(bytes(ft.GetGeometryRef().ExportToWkb()))
    return ulos["vesi"], ulos["alue"], ulos["vyohyke"], lue_json(TYO / "aoi.json")


# ----------------------------------------------------------------------------------------
# Rajattu GeoPackage
# ----------------------------------------------------------------------------------------
RAJATTU = TYO / "rajattu.gpkg"
OGR_TYYPIT = {"int": ogr.OFTInteger64, "str": ogr.OFTString, "float": ogr.OFTReal}
GEOM_TYYPIT = {"piste": ogr.wkbPoint, "viiva": ogr.wkbMultiLineString, "alue": ogr.wkbMultiPolygon}


def kirjoita_gpkg(nimi, tyyppi, kentat, rivit):
    """Kirjoita kerros tiedostoon rajattu.gpkg (EPSG:3067). rivit tuottaa (geometria, sanakirja)."""
    ds = ogr.Open(str(RAJATTU), 1) if RAJATTU.exists() else ogr.GetDriverByName("GPKG").CreateDataSource(str(RAJATTU))
    if ds.GetLayerByName(nimi) is not None:
        ds.DeleteLayer(nimi)
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(3067)
    k = ds.CreateLayer(nimi, srs, GEOM_TYYPIT[tyyppi])
    for kentta, tyyp in kentat.items():
        k.CreateField(ogr.FieldDefn(kentta, OGR_TYYPIT[tyyp]))
    k.StartTransaction()
    n = 0
    for g, p in rivit:
        if g is None or g.is_empty:
            continue
        if tyyppi == "alue":
            g = moni(g) if g.geom_type in ("Polygon", "MultiPolygon") else moni_vain_alueet(g)
            if g is None or g.is_empty:
                continue
        elif tyyppi == "viiva":
            g = moni_viiva(g)
            if g is None:
                continue
        ft = ogr.Feature(k.GetLayerDefn())
        ft.SetGeometry(ogr.CreateGeometryFromWkb(swkb.dumps(g)))
        for kentta in kentat:
            v = p.get(kentta)
            if v is not None:
                ft.SetField(kentta, v)
        k.CreateFeature(ft)
        n += 1
        if n % 50000 == 0:
            k.CommitTransaction()
            k.StartTransaction()
    k.CommitTransaction()
    ds = None
    loki("kerros %s: %d kohdetta" % (nimi, n))
    return n


def moni_vain_alueet(g):
    from shapely.geometry import MultiPolygon
    osat = [p for p in getattr(g, "geoms", []) if p.geom_type == "Polygon"]
    return MultiPolygon(osat) if osat else None


def moni_viiva(g):
    from shapely.geometry import MultiLineString
    if g.geom_type == "MultiLineString":
        return g
    if g.geom_type == "LineString":
        return MultiLineString([g])
    osat = [p for p in getattr(g, "geoms", []) if p.geom_type == "LineString"]
    return MultiLineString(osat) if osat else None


# ----------------------------------------------------------------------------------------
# Maastotietokannan rajaus
# ----------------------------------------------------------------------------------------
KAYTTOTARKOITUS = {1: "asuinrakennus", 2: "toimisto- tai julkinen rakennus", 3: "lomarakennus",
                   4: "teollisuusrakennus", 5: "uskonnollinen rakennus", 6: "muu rakennus", 7: "kirkko"}
MAASTOKUVIO = {
    32611: "pelto", 32612: "puutarha", 32800: "niitty", 34100: "kallio", 34700: "kivikko", 34300: "hietikko",
    35300: "soistuma", 35411: "suo", 35412: "suo", 35421: "suo", 35422: "suo",
    33100: "urheilu_virkistys", 32900: "puisto", 32200: "hautausmaa", 32421: "autoliikenne",
    32411: "lentokentta", 32412: "lentokentta", 32413: "lentokentta", 32414: "lentokentta",
    32415: "lentokentta", 32416: "lentokentta", 32417: "lentokentta", 32418: "lentokentta",
    32500: "louhos", 32111: "maa_aines", 32112: "maa_aines", 32113: "maa_aines", 32300: "kaatopaikka",
    33000: "taytemaa", 38900: "varastoalue", 39110: "avoin_alue", 39120: "avoin_alue", 39130: "avoin_alue",
    36313: "virtavesi", 38300: "maatuva_vesialue", 40200: "taajama",
}
VESIESTEET_PISTE = {38511: "vesikivi_vedenalainen", 38512: "vesikivi_pinnassa", 38513: "vesikivi_pinnan_ylapuolella"}
VESIESTEET_ALUE = {38600: "vesikivikko", 38700: "matalikko"}
VESIESTEET_VIIVA = {44100: "aallonmurtaja", 45111: "laituri_kapea", 45112: "laituri_leveä"}
TIELUOKAT = {12111, 12112, 12121, 12122, 12131, 12132, 12141, 12151, 12152, 12312, 12313, 12314, 12316,
             12311, 14111, 14112, 14121, 14131}


def lue_mtk(etuliite, laji, where=None, spat=None):
    for z in mtk_zip_polut():
        yield from lue_kerros(zip_kerros(z, etuliite, laji), where=where, spat=spat)


def vaihe_mtkrajaus():
    vesi, alue, vyohyke, tied = lataa_aoi()
    pa = prep(alue)
    b = tied["bbox_3067"]

    # --- rakennukset: sama rakennus voi esiintyä kahdessa lehdessä, joten yhdistetään KOHDEOSO:n mukaan
    ryhmat = {}
    yksittaiset = []
    lkm_raaka = 0
    for g, p in lue_mtk("r", "p", where="LUOKKA >= 42210 AND LUOKKA <= 42270"):
        lkm_raaka += 1
        if not pa.intersects(g):
            continue
        avain = p.get("KOHDEOSO")
        if avain:
            ryhmat.setdefault(avain, []).append((g, p))
        else:
            yksittaiset.append((g, p))
    loki("rakennuksia rajauksessa %d (raaka-lehdillä %d, kohdeosoja %d)" % (
        len(ryhmat) + len(yksittaiset), lkm_raaka, len(ryhmat)))

    def rakennukset():
        for avain, osat in ryhmat.items():
            g = osat[0][0] if len(osat) == 1 else unary_union([o[0] for o in osat])
            yield g, rakennus_ominaisuudet(osat[0][1])
        for g, p in yksittaiset:
            yield g, rakennus_ominaisuudet(p)

    kirjoita_gpkg("rakennus", "alue", {"luokka": "int", "kaytto": "str", "krs": "str", "z": "float"}, rakennukset())

    # --- tiet (varalähde: lehtikohtaiset Shapefilet, joissa tienimet ovat tyhjiä; vaihe tienimet korvaa tämän)
    def tiet():
        for g, p in lue_mtk("l", "v", spat=(b[0], b[1], b[2], b[3])):
            if p["LUOKKA"] in TIELUOKAT and pa.intersects(g):
                yield g, {"luokka": p["LUOKKA"], "paallyste": p.get("PAALLY"), "tienumero": p.get("TIENUM") or None,
                          "nimi": None, "taso": None}
    kirjoita_gpkg("tie", "viiva", {"luokka": "int", "paallyste": "int", "tienumero": "int", "nimi": "str",
                                   "taso": "int"}, tiet())

    # --- maastokuviot
    def kuviot():
        for etu in ("m", "n", "u"):
            for g, p in lue_mtk(etu, "p"):
                luokka = p["LUOKKA"]
                nimi = MAASTOKUVIO.get(luokka)
                if nimi is None or luokka == 36200:
                    continue
                if not pa.intersects(g):
                    continue
                yield g, {"luokka": nimi, "koodi": luokka}
        # järvet: yhdistetty ja rajattu, jotta lehtirajat eivät näy
        for o in getattr(JARVET[0], "geoms", [JARVET[0]]):
            if pa.intersects(o):
                yield o, {"luokka": "jarvi", "koodi": 36200}

    palat = [g for g, p in lue_mtk("m", "p", where="LUOKKA = 36200")]
    JARVET[0] = unary_union(palat)
    kirjoita_gpkg("maastokuvio", "alue", {"luokka": "str", "koodi": "int"}, kuviot())

    # --- rantaviiva: järvien yhdistetty reuna
    def ranta():
        for o in getattr(JARVET[0], "geoms", [JARVET[0]]):
            if not pa.intersects(o):
                continue
            yield o.boundary, {"luokka": "jarvi", "pituus_km": round(o.boundary.length / 1e3, 2)}
    kirjoita_gpkg("rantaviiva", "viiva", {"luokka": "str", "pituus_km": "float"}, ranta())

    # --- vesiesteet: vesikivet, matalikot, aallonmurtajat ja laiturit
    def esteet_p():
        for g, p in lue_mtk("n", "s"):
            if p["LUOKKA"] in VESIESTEET_PISTE and pa.intersects(g):
                yield g, {"laji": VESIESTEET_PISTE[p["LUOKKA"]], "koodi": p["LUOKKA"]}
    kirjoita_gpkg("vesieste_piste", "piste", {"laji": "str", "koodi": "int"}, esteet_p())

    def esteet_a():
        for g, p in lue_mtk("n", "p"):
            if p["LUOKKA"] in VESIESTEET_ALUE and pa.intersects(g):
                yield g, {"laji": VESIESTEET_ALUE[p["LUOKKA"]], "koodi": p["LUOKKA"]}
    kirjoita_gpkg("vesieste_alue", "alue", {"laji": "str", "koodi": "int"}, esteet_a())

    def esteet_v():
        for g, p in lue_mtk("r", "v"):
            if p["LUOKKA"] in VESIESTEET_VIIVA and pa.intersects(g):
                yield g, {"laji": VESIESTEET_VIIVA[p["LUOKKA"]], "koodi": p["LUOKKA"]}
    kirjoita_gpkg("vesieste_viiva", "viiva", {"laji": "str", "koodi": "int"}, esteet_v())


JARVET = [None]


def rakennus_ominaisuudet(p):
    luokka = p["LUOKKA"]
    kaytto = KAYTTOTARKOITUS.get((luokka // 10) % 10 if luokka != 42270 else 7, "muu rakennus")
    if luokka == 42270:
        kaytto = KAYTTOTARKOITUS[7]
    viim = luokka % 10
    krs = {1: "1-2", 2: "3+"}.get(viim, "")
    z = p.get("KORKEUS")
    return {"luokka": luokka, "kaytto": kaytto, "krs": krs, "z": round(z, 1) if z else None}


# ----------------------------------------------------------------------------------------
# Maastotietokannan tieviivat nimineen (GeoPackage, /vsicurl/-luku rajattuna)
# ----------------------------------------------------------------------------------------
def vaihe_tienimet():
    """Hakee tieviivat nimineen GeoPackagesta /vsicurl/-polulla alueen rajauslaatikolla.

    Lehtikohtaisissa Shapefile-paketeissa tienimikentät ovat tyhjiä, joten nimet saadaan vain
    GeoPackagesta. Tiedostoa ei ladata kokonaan: GDAL lukee vain tarvittavat alueet
    (R-puuindeksi). Siirtomäärä mitataan ja kirjataan lokiin. Jos luku epäonnistuu tai kestää yli
    TIENIMET_AIKARAJA sekuntia, jätetään nimet pois ja käytetään Shapefile-tieviivoja.
    """
    tied = lue_json(TYO / "aoi.json")
    b = tied["bbox_3067"]
    kohde = TYO / "tie_gpkg.gpkg"
    valmis_lataus = TYO / ".tie_gpkg_ladattu"
    if kohde.exists() and not valmis_lataus.exists():
        kohde.unlink()
    osoite = PAITULI + "mml/maastotietokanta/2025/gpkg/MTK-tie_25-04-03.gpkg"
    env = dict(os.environ, CPL_VSIL_CURL_CHUNK_SIZE="262144", CPL_VSIL_CURL_CACHE_SIZE="800000000",
               CPL_DEBUG="ON", GDAL_HTTP_USERAGENT=KAYTTAJA)
    loki_pol = TYO / "tienimet_gdal.log"
    alku = time.time()
    try:
        if not valmis_lataus.exists():
            with open(loki_pol, "w") as lf:
                subprocess.run(["ogr2ogr", "-f", "GPKG", str(kohde), "/vsicurl/" + osoite, "tieviiva",
                                "-spat", str(b[0]), str(b[1]), str(b[2]), str(b[3]), "-dim", "XY",
                                "-select", "kohdeluokka,nimi_suomi,tienumero,paallyste,tasosijainti"],
                               env=env, stderr=lf, stdout=subprocess.DEVNULL, timeout=TIENIMET_AIKARAJA, check=True)
            valmis_lataus.write_text(json.dumps({"haettu": nyt_iso(), "sekuntia": round(time.time() - alku, 1)}))
    except Exception as e:  # noqa: BLE001
        lokiin("tienimet", tila="ei onnistunut", virhe=repr(e)[:300], sekuntia=round(time.time() - alku, 1),
               osoite=osoite)
        loki("Tienimiä ei saatu GeoPackagesta:", repr(e)[:200], "- käytetään Shapefile-tieviivoja")
        kohde.unlink(missing_ok=True)
        return
    tavut = 0
    n = 0
    for rivi in open(loki_pol, errors="replace"):
        if "VSICURL: Downloading" in rivi:
            m = __import__("re").search(r"Downloading (\d+)-(\d+)", rivi)
            if m:
                tavut += int(m.group(2)) - int(m.group(1)) + 1
                n += 1
    vesi, alue, vyohyke, _ = lataa_aoi()
    pa = prep(alue)
    ds = ogr.Open(str(kohde))
    k = ds.GetLayer(0)

    def tiet():
        for ft in k:
            g = swkb.loads(bytes(ft.GetGeometryRef().ExportToWkb()))
            if pa.intersects(g):
                yield g, {"luokka": ft.GetField("kohdeluokka"), "paallyste": ft.GetField("paallyste"),
                          "tienumero": ft.GetField("tienumero"), "nimi": ft.GetField("nimi_suomi"),
                          "taso": ft.GetField("tasosijainti")}
    kirjoita_gpkg("tie", "viiva", {"luokka": "int", "paallyste": "int", "tienumero": "int", "nimi": "str",
                                   "taso": "int"}, tiet())
    try:
        lataus_s = json.loads(valmis_lataus.read_text()).get("sekuntia")
    except Exception:  # noqa: BLE001
        lataus_s = None
    lokiin("tienimet", tila="ok", osoite=osoite, haettu=nyt_iso(), siirretty_tavua=tavut, pyyntoja=n,
           sekuntia=round(time.time() - alku, 1), gdal_lukuaika_s=lataus_s)
    loki("Tienimet GeoPackagesta: %.0f Mt, %d pyyntöä, GDAL-luku %s s" % (tavut / 1e6, n, lataus_s))


TIENIMET_AIKARAJA = 1500


# ----------------------------------------------------------------------------------------
# Kiinteistörajat
# ----------------------------------------------------------------------------------------
def vaihe_kiinteisto():
    vesi, alue, vyohyke, tied = lataa_aoi()
    ls = lehdet_geometrialla("dem2m", alue)
    loki("Kiinteistölehtiä:", len(ls))
    tulos = {}

    def yksi(d):
        url = PAITULI + "mml/kiinteisto/2025/%s/%s.zip" % (d["label"][:3], d["label"])
        try:
            return hae(url, RAAKA / "kiinteisto" / (d["label"] + ".zip"), kerro=False)
        except RuntimeError as e:
            tulos[d["label"]] = str(e)[:200]
            return 0, 0.0, False

    tavut, dt, n = rinnakkain(ls, yksi, 4)
    puuttuvat = sorted(tulos)
    lokiin("kiinteisto", osoite=PAITULI + "mml/kiinteisto/2025/<1:100k>/<1:10k-lehti>.zip", haettu=nyt_iso(),
           lehtia=len(ls), ladattu=n, tavua=tavut, sekuntia=round(dt, 1), puuttuvat=puuttuvat)
    loki("Kiinteistöt ladattu: %.0f Mt, %.0f s, puuttuu %d" % (tavut / 1e6, dt, len(puuttuvat)))
    pa = prep(alue)
    zipit = sorted((RAAKA / "kiinteisto").glob("*.zip"))

    def rajat():
        nahty = set()
        for z in zipit:
            lehti = z.stem
            for g, p in lue_kerros("/vsizip/%s/%s_kiinteistoraja.shp" % (z, lehti)):
                if not pa.intersects(g):
                    continue
                # Lehtien reunalla sama viiva voi olla kahdessa lehdessä: tunniste ID
                if p.get("ID") in nahty:
                    continue
                nahty.add(p.get("ID"))
                yield g, {"laji": p.get("LAJI")}
    kirjoita_gpkg("kiinteistoraja", "viiva", {"laji": "int"}, rajat())

    def tunnukset():
        nahty = set()
        for z in zipit:
            lehti = z.stem
            for g, p in lue_kerros("/vsizip/%s/%s_palstatunnus.shp" % (z, lehti)):
                if not pa.intersects(g):
                    continue
                avain = (p.get("ID"), round(g.x), round(g.y))
                if avain in nahty:
                    continue
                nahty.add(avain)
                yield g, {"tunnus": p.get("TPTEKSTI"), "kunta": p.get("KTUNNUS")}
    kirjoita_gpkg("kiinteistotunnus", "piste", {"tunnus": "str", "kunta": "str"}, tunnukset())


# ----------------------------------------------------------------------------------------
# DVV:n osoitteet (Shapefile, haetaan vain tarvittavat tietueet HTTP Range -pyynnöillä)
# ----------------------------------------------------------------------------------------
def http_range(url, alku, loppu, yrityksia=5):
    viimeinen = None
    for y in range(yrityksia):
        try:
            pyynto = urllib.request.Request(url, headers={"User-Agent": KAYTTAJA, "Range": "bytes=%d-%d" % (alku, loppu)})
            with urllib.request.urlopen(pyynto, timeout=120) as r:
                return r.read()
        except Exception as e:  # noqa: BLE001
            viimeinen = e
            time.sleep(1 + 2 * y)
    raise RuntimeError("Range-haku epäonnistui: %s" % viimeinen)


def vaihe_dvv():
    import numpy as np
    import struct
    vesi, alue, vyohyke, tied = lataa_aoi()
    pohja = PAITULI + "dvv/osoitteet/2025/osoiteet_2025"
    # 1) piste-sijainnit .shp-tiedostosta (105 Mt). Tietueet ovat 28 tavun mittaisia, joten .shx ei tarvita.
    shp = RAAKA / "dvv" / "osoiteet_2025.shp"
    n1, dt1, _ = hae(pohja + ".shp", shp)
    raw = np.fromfile(shp, dtype=np.uint8, offset=100)
    maara = len(raw) // 28
    dt = np.dtype([("rn", ">i4"), ("cl", ">i4"), ("t", "<i4"), ("x", "<f8"), ("y", "<f8")])
    a = np.frombuffer(raw[:maara * 28].tobytes(), dtype=dt)
    b = tied["bbox_3067"]
    ehdokkaat = np.nonzero((a["x"] >= b[0]) & (a["x"] <= b[2]) & (a["y"] >= b[1]) & (a["y"] <= b[3]))[0]
    from shapely import contains_xy
    sisalla = contains_xy(alue, a["x"][ehdokkaat], a["y"][ehdokkaat])
    idx = ehdokkaat[sisalla]
    loki("DVV: %d pistettä, rajauslaatikossa %d, alueella %d" % (maara, len(ehdokkaat), len(idx)))
    # 2) dbf-otsikko
    ots = http_range(pohja + ".dbf", 0, 4095)
    nrec, hlen, rlen = struct.unpack("<IHH", ots[4:12])
    if nrec != maara:
        raise RuntimeError("DVV: shp ja dbf eivät täsmää (%d / %d)" % (maara, nrec))
    kentat = []
    pos = 1
    for i in range(32, hlen - 1, 32):
        nimi = ots[i:i + 11].split(b"\0")[0].decode("ascii")
        pit = ots[i + 16]
        kentat.append((nimi, pos, pit))
        pos += pit
    # 3) tarvittavat tietueet ryhmiteltyinä
    idx = np.sort(idx)
    ryhmat = []
    alku = idx[0]
    ed = idx[0]
    for i in idx[1:]:
        if (i - ed) * rlen > 6000:       # yli ~6 kt aukko, aloitetaan uusi pyyntö
            ryhmat.append((alku, ed))
            alku = i
        ed = i
    ryhmat.append((alku, ed))
    ryhmat2 = []
    for (r0, r1) in ryhmat:               # pilko liian pitkät pyynnöt 4 Mt:n paloihin
        while (r1 - r0 + 1) * rlen > 4_000_000:
            vali = r0 + 4_000_000 // rlen
            ryhmat2.append((r0, vali - 1))
            r0 = vali
        ryhmat2.append((r0, r1))
    loki("DVV: tietuehaut %d pyyntöä" % len(ryhmat2))
    tavut = [0]

    def hae_ryhma(r):
        r0, r1 = r
        d = http_range(pohja + ".dbf", hlen + r0 * rlen, hlen + (r1 + 1) * rlen - 1)
        tavut[0] += len(d)
        return r0, d

    tiedot = {}
    alku_t = time.time()
    with cf.ThreadPoolExecutor(8) as ex:
        for r0, d in ex.map(hae_ryhma, ryhmat2):
            n = len(d) // rlen
            for j in range(n):
                tiedot[r0 + j] = d[j * rlen:(j + 1) * rlen]
    kentta = {nimi: (p, l) for nimi, p, l in kentat}

    def teksti(rec, nimi):
        p, l = kentta[nimi]
        # DVV:n .dbf on UTF-8 (cp1252-luku tuotti ä:n tilalle Ã¤). Varalla cp1252, jos tavut eivät ole kelvollista UTF-8:aa.
        tavut_ = rec[p:p + l]
        try:
            return tavut_.decode("utf-8").strip() or None
        except UnicodeDecodeError:
            return tavut_.decode("cp1252", errors="replace").strip() or None

    def rivit():
        for i in idx:
            rec = tiedot.get(int(i))
            if rec is None or rec[0:1] == b"*":
                continue
            katu = teksti(rec, "katunimi_f")
            num = teksti(rec, "katunumero")
            osoite = (katu + (" " + num if num else "")) if katu else None
            yield Point(float(a["x"][i]), float(a["y"][i])), {
                "osoite": osoite, "katu": katu, "numero": num, "postinumero": teksti(rec, "postinumer"),
                "tyyppi": int(teksti(rec, "rakennusty") or 0), "kunta": teksti(rec, "sijaintiku"),
                "ruotsi": teksti(rec, "katunimi_s")}
    kirjoita_gpkg("osoite", "piste", {"osoite": "str", "katu": "str", "numero": "str", "postinumero": "str",
                                      "tyyppi": "int", "kunta": "str", "ruotsi": "str"}, rivit())
    lokiin("dvv", osoite=pohja + ".{shp,dbf}", haettu=nyt_iso(), siirretty_tavua=n1 + tavut[0],
           sekuntia=round(dt1 + time.time() - alku_t, 1), pisteita_koko_suomi=int(maara),
           osoitteita_alueella=int(len(idx)), pyyntoja=len(ryhmat2),
           huomio="DVV lopetti avoimen jakelun 14.3.2025; aineisto on poimittu 3.2.2025 eikä päivity")
    loki("DVV valmis: siirretty %.0f Mt" % ((n1 + tavut[0]) / 1e6))


# ----------------------------------------------------------------------------------------
# Korkeusmallit
# ----------------------------------------------------------------------------------------
def vaihe_dem10():
    vesi, alue, vyohyke, tied = lataa_aoi()
    ls = lehdet_geometrialla("dem10m", alue)
    loki("DEM 10 m -lehtiä:", len(ls))

    def yksi(d):
        return hae(PAITULI + d["path"], RAAKA / "dem10" / (d["label"] + ".tif"), kerro=False)

    tavut, dt, n = rinnakkain(ls, yksi, 4)
    b = tied["bbox_3067"]
    tifit = sorted(str(p) for p in (RAAKA / "dem10").glob("*.tif"))
    vrt = TYO / "dem10.vrt"
    gdal.BuildVRT(str(vrt), tifit)
    gdal.Translate(str(TYO / "dem10.tif"), str(vrt), projWin=[b[0], b[3], b[2], b[1]],
                   creationOptions=["COMPRESS=DEFLATE", "TILED=YES", "PREDICTOR=3"])
    lokiin("dem10", osoite=PAITULI + "mml/dem10m/2019/<1:200k>/<1:100k>/<lehti>.tif", haettu=nyt_iso(),
           lehtia=len(ls), tavua=tavut, sekuntia=round(dt, 1), lehtilista=[d["label"] for d in ls],
           korkeusjarjestelma="N2000 (EPSG:3900)", hilakoko_m=10, nodata=-9999)
    loki("DEM 10 m ladattu: %.0f Mt, %.0f s" % (tavut / 1e6, dt))


def vaihe_dem2():
    vesi, alue, vyohyke, tied = lataa_aoi()
    ls = lehdet_geometrialla("dem2m", vyohyke)
    loki("DEM 2 m -lehtiä rantavyöhykkeellä:", len(ls))

    def yksi(d):
        return hae(PAITULI + d["path"], RAAKA / "dem2" / (d["label"] + ".tif"), kerro=False)

    tavut, dt, n = rinnakkain(ls, yksi, 4)
    tifit = sorted(str(p) for p in (RAAKA / "dem2").glob("*.tif"))
    gdal.BuildVRT(str(TYO / "dem2.vrt"), tifit)
    lokiin("dem2", osoite=PAITULI + "mml/dem2m/2008_latest/<1:200k>/<1:100k>/<lehti>.tif", haettu=nyt_iso(),
           lehtia=len(ls), tavua=tavut, sekuntia=round(dt, 1), lehtilista=[d["label"] for d in ls],
           korkeusjarjestelma="N2000 (EPSG:3900)", hilakoko_m=2, nodata=-9999)
    loki("DEM 2 m ladattu: %.0f Mt, %.0f s" % (tavut / 1e6, dt))


# ----------------------------------------------------------------------------------------
# Luke MVMI 2023
# ----------------------------------------------------------------------------------------
# Luken lataamat teemat: nimi paketissa -> (tiedosto Paitulissa, yksikkö). Keskipituus ja latvuspeitto ovat pakollisia (puusto.pmtiles),
# lajitilavuudet ja lehtipuiden latvuspeitto (vaihe 1c) ovat lehtipuuosuuden laskentaa varten. Lajitilavuuksien yksikkö on m3/ha.
LUKE_TEEMAT = [
    ("keskipituus", "keskipituus_vmi1x_1923.tif", "dm", True),
    ("latvuspeitto", "latvuspeitto_vmi1x_1923.tif", "%", True),
    ("manty", "manty_vmi1x_1923.tif", "m3/ha", False),
    ("kuusi", "kuusi_vmi1x_1923.tif", "m3/ha", False),
    ("koivu", "koivu_vmi1x_1923.tif", "m3/ha", False),
    ("muulp", "muulp_vmi1x_1923.tif", "m3/ha", False),
    ("tilavuus", "tilavuus_vmi1x_1923.tif", "m3/ha", False),
    ("lehtip_latvuspeitto", "lehtip_latvuspeitto_vmi1x_1923.tif", "%", False),
]


def vaihe_luke():
    vesi, alue, vyohyke, tied = lataa_aoi()
    b = tied["bbox_3067"]
    tavut_yht = 0
    for nimi, tiedosto, yksikko, pakollinen in LUKE_TEEMAT:
        osoite = PAITULI + "luke/vmi/2023/" + tiedosto
        loki_pol = TYO / ("luke_%s.log" % nimi)
        env = dict(os.environ, CPL_DEBUG="ON", GDAL_HTTP_USERAGENT=KAYTTAJA)
        alku = time.time()
        try:
            with open(loki_pol, "w") as lf:
                subprocess.run(["gdal_translate", "-q", "-projwin", str(b[0]), str(b[3]), str(b[2]), str(b[1]),
                                "-co", "COMPRESS=DEFLATE", "-co", "TILED=YES", "/vsicurl/" + osoite,
                                str(TYO / ("luke_%s.tif" % nimi))], env=env, stderr=lf, check=True)
        except Exception as e:  # noqa: BLE001
            if pakollinen:
                raise
            loki("Luke: valinnaista teemaa %s ei saatu (%s), lehtipuuosuutta ei lasketa" % (nimi, repr(e)[:200]))
            continue
        tavut = 0
        for rivi in open(loki_pol, errors="replace"):
            m = __import__("re").search(r"VSICURL: Downloading (\d+)-(\d+)", rivi)
            if m:
                tavut += int(m.group(2)) - int(m.group(1)) + 1
        tavut_yht += tavut
        lokiin("luke_" + nimi, osoite=osoite, haettu=nyt_iso(), siirretty_tavua=tavut,
               sekuntia=round(time.time() - alku, 1), nodata=32767, hilakoko_m=16, yksikko=yksikko)
    loki("Luke ladattu: %.0f Mt" % (tavut_yht / 1e6))


# ----------------------------------------------------------------------------------------
# SYKE Corine maanpeite 2018 (ruovikot, valinnainen, vaihe 1c)
# ----------------------------------------------------------------------------------------
# Kansallinen 20 m:n rasteri (zip 273 Mt, tif 207 Mt, EPSG:3067, CC BY 4.0). Latausosoite ja saatavuus GitHub Actionsista tarkistettu 26.10.2026 (HEAD 200, Range tuettu).
# Luokka 42 (LEVEL4 4112) = Sisämaan kosteikot vedessä (Inland marshes, aquatic), eli ruovikot ja vastaavat vesikasvustot.
CORINE_OSOITE = "https://wwwd3.ymparisto.fi/d3/Static_rs/spesific/clc2018_fi20m.zip"
CORINE_TIF = "Clc2018_FI20m.tif"
CORINE_LUOKKA_RUOVIKKO = 42


def vaihe_corine():
    import zipfile
    tied = lue_json(TYO / "aoi.json")
    b = tied["bbox_3067"]
    h = RAAKA / "corine"
    zip_ = h / "clc2018_fi20m.zip"
    alku = time.time()
    n, dt, uusi = hae(CORINE_OSOITE, zip_, kerro=False)
    with zipfile.ZipFile(zip_) as z:
        z.extract(CORINE_TIF, h)
    kohde = TYO / "corine_maanpeite.tif"
    subprocess.run(["gdal_translate", "-q", "-projwin", str(b[0]), str(b[3]), str(b[2]), str(b[1]), "-co", "COMPRESS=DEFLATE",
                    str(h / CORINE_TIF), str(kohde)], check=True)
    (h / CORINE_TIF).unlink(missing_ok=True)
    zip_.unlink(missing_ok=True)
    lokiin("corine", osoite=CORINE_OSOITE, haettu=nyt_iso(), siirretty_tavua=int(n if uusi else 0), sekuntia=round(time.time() - alku, 1),
           hilakoko_m=20, ruovikkoluokka=CORINE_LUOKKA_RUOVIKKO, luokan_nimi="Sisämaan kosteikot vedessä (CLC 4112)")
    loki("Corine ladattu: %.0f Mt, %.0f s" % (n / 1e6, time.time() - alku))


# ----------------------------------------------------------------------------------------
# Väylävirasto ja Traficom (WFS)
# ----------------------------------------------------------------------------------------
VAYLA_KERROKSET = ["turvalaitteet_uusi", "loistot_uusi", "valosektorit_uusi", "navigointilinjat_uusi",
                   "vaylaalueet_uusi", "vaylat_uusi", "taululinjat_uusi", "vesiliikennemerkit_uusi",
                   "vesivaylien_nopeusrajoitusalueet", "turvalaitteet_muut_vaylanpitajat",
                   "navigointilinjat_muut_vaylanpitajat", "sulkukanavat_uusi"]
TRAFICOM_KERROKSET = ["DepthArea_A", "DepthContour_L", "Sounding_P"]


def wfs_hae(osoite, typename, bbox4326, kohde):
    q = {"SERVICE": "WFS", "VERSION": "1.0.0", "REQUEST": "GetFeature", "TYPENAME": typename,
         "OUTPUTFORMAT": "application/json", "SRSNAME": "EPSG:4326",
         "BBOX": "%.5f,%.5f,%.5f,%.5f,EPSG:4326" % tuple(bbox4326)}
    url = osoite + "?" + urllib.parse.urlencode(q)
    alku = time.time()
    data = hae_teksti(url)
    j = json.loads(data)
    if "features" not in j:
        raise RuntimeError("WFS-vastaus ilman kohteita: %s" % data[:200])
    Path(kohde).parent.mkdir(parents=True, exist_ok=True)
    Path(kohde).write_bytes(data)
    return len(j["features"]), len(data), time.time() - alku


def vaihe_vayla():
    tied = lue_json(TYO / "aoi.json")
    bb = tied["bbox_4326"]
    tulos = {}
    for tn in VAYLA_KERROKSET:
        try:
            n, tavut, dt = wfs_hae(VAYLA_WFS, "vesivaylatiedot:" + tn, bb, RAAKA / "vayla" / (tn + ".json"))
            tulos[tn] = {"kohteita": n, "tavua": tavut, "sekuntia": round(dt, 1)}
            loki("Väylä %s: %d kohdetta, %.0f kt" % (tn, n, tavut / 1e3))
        except Exception as e:  # noqa: BLE001
            tulos[tn] = {"virhe": repr(e)[:300]}
            loki("Väylä %s EPÄONNISTUI: %s" % (tn, repr(e)[:200]))
    lokiin("vayla", osoite=VAYLA_WFS, haettu=nyt_iso(), kerrokset=tulos,
           tavua=sum(v.get("tavua", 0) for v in tulos.values()))


def vaihe_traficom():
    tied = lue_json(TYO / "aoi.json")
    bb = tied["bbox_4326"]
    tulos = {}
    for tn in TRAFICOM_KERROKSET:
        try:
            n, tavut, dt = wfs_hae(TRAFICOM_WFS, "rajoitettu:" + tn, bb, RAAKA / "traficom" / (tn + ".json"))
            tulos[tn] = {"kohteita": n, "tavua": tavut, "sekuntia": round(dt, 1)}
            loki("Traficom %s: %d kohdetta, %.1f Mt" % (tn, n, tavut / 1e6))
        except Exception as e:  # noqa: BLE001
            tulos[tn] = {"virhe": repr(e)[:300]}
            loki("Traficom %s EPÄONNISTUI: %s" % (tn, repr(e)[:200]))
    # Lisenssiteksti ja palvelun tiedot GetCapabilities-vastauksesta
    try:
        caps = hae_teksti(TRAFICOM_WFS + "?SERVICE=WFS&VERSION=2.0.0&REQUEST=GetCapabilities").decode("utf-8", "replace")
        (RAAKA / "traficom" / "capabilities.xml").write_text(caps, encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        loki("Traficom GetCapabilities epäonnistui:", repr(e)[:200])
    lokiin("traficom", osoite=TRAFICOM_WFS, haettu=nyt_iso(), kerrokset=tulos,
           tavua=sum(v.get("tavua", 0) for v in tulos.values()))


# ----------------------------------------------------------------------------------------
# Ehtotiedostot
# ----------------------------------------------------------------------------------------
def vaihe_ehdot():
    tulos = {}
    for nimi, polku in (("MML", "ehdot/MML_ehdot_CC.txt"), ("DVV", "dvv/DVV_ehdot_CC.txt"),
                        ("Luke", "luke/luke_ehdot.txt"), ("MTK", "mml/maastotietokanta/2025/gpkg/Lueminut.txt")):
        try:
            data = hae_teksti(PAITULI + polku)
            for koodaus in ("utf-8", "cp1252"):
                try:
                    teksti = data.decode(koodaus)
                    break
                except UnicodeDecodeError:
                    continue
            (RAAKA / "ehdot").mkdir(parents=True, exist_ok=True)
            (RAAKA / "ehdot" / (nimi + ".txt")).write_text(teksti, encoding="utf-8")
            tulos[nimi] = {"osoite": PAITULI + polku, "teksti": teksti[:1500]}
        except Exception as e:  # noqa: BLE001
            tulos[nimi] = {"osoite": PAITULI + polku, "virhe": repr(e)[:200]}
    lokiin("ehdot", haettu=nyt_iso(), tiedostot=tulos)


VAIHEET = {
    "indeksit": vaihe_indeksit,
    "mtk": vaihe_mtk,
    "aoi": vaihe_aoi,
    "mtkrajaus": vaihe_mtkrajaus,
    "tienimet": vaihe_tienimet,
    "kiinteisto": vaihe_kiinteisto,
    "dvv": vaihe_dvv,
    "dem10": vaihe_dem10,
    "dem2": vaihe_dem2,
    "luke": vaihe_luke,
    "corine": vaihe_corine,
    "vayla": vaihe_vayla,
    "traficom": vaihe_traficom,
    "ehdot": vaihe_ehdot,
}


def main(argv):
    pakota = "--pakota" in argv
    nimet = [a for a in argv if not a.startswith("--")] or list(VAIHEET)
    TYO.mkdir(exist_ok=True)
    for nimi in nimet:
        merkki = TYO / (".valmis_" + nimi)
        if merkki.exists() and not pakota:
            loki("vaihe", nimi, "on jo tehty (--pakota tekee uudelleen)")
            continue
        loki("=== vaihe", nimi)
        alku = time.time()
        try:
            VAIHEET[nimi]()
            merkki.write_text(nyt_iso())
            lokiin("vaihe_" + nimi, sekuntia=round(time.time() - alku, 1), tila="ok")
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            lokiin("vaihe_" + nimi, sekuntia=round(time.time() - alku, 1), tila="virhe", virhe=repr(e)[:400])
            loki("VIRHE vaiheessa", nimi, "- jatketaan seuraavaan")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
