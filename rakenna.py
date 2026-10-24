#!/usr/bin/env python3
"""Vaihe 2: rakentaa julkaistavat tiedostot hakemistoon ulos/.

Ajo:  python3 rakenna.py              kaikki osat
      python3 rakenna.py vektori      vain vektoritiilet (nasijarvi.pmtiles)
      python3 rakenna.py maasto       vain maaston korkeustiilet (maasto.pmtiles)
      python3 rakenna.py puusto       vain puuston tiilet (puusto.pmtiles)
      python3 rakenna.py kuvaus       vain aineisto.json ja sivuston tiedostot

Tuotokset (hakemisto ulos/):
  nasijarvi.pmtiles   vektoritiilet (MVT), tasot 8-16
  maasto.pmtiles      Terrain-RGB (Mapbox-koodaus) PNG-rasteritiilet, tasot 8-14
  puusto.pmtiles      puuston pituus ja latvuspeitto PNG-rasteritiileinä, tasot 10-14
  aineisto.json       kuvaus: bbox, lähteet, lisenssit, kerrokset, kentät, tiedostot
  testi.html + lib/   testisivu (Leaflet + PMTiles)
"""
import hashlib
import io
import json
import math
import re
import shutil
import sys
import time
import traceback
from pathlib import Path

from asetukset import *  # noqa: F401,F403

import numpy as np  # noqa: E402
from osgeo import gdal, ogr, osr  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402
from shapely import wkb as swkb  # noqa: E402
from shapely.geometry import box, shape, Point  # noqa: E402
from shapely.ops import transform, unary_union  # noqa: E402
from shapely.prepared import prep  # noqa: E402
import pyproj  # noqa: E402

gdal.UseExceptions()
ogr.UseExceptions()

GJ = TYO / "geojson"
RAJATTU = TYO / "rajattu.gpkg"
T3067_4326 = pyproj.Transformer.from_crs(3067, 4326, always_xy=True)
T3067_3857 = pyproj.Transformer.from_crs(3067, 3857, always_xy=True)
T4326_3857 = pyproj.Transformer.from_crs(4326, 3857, always_xy=True)
RAKENNUSLOKI = TYO / "rakennus_loki.json"

# ----------------------------------------------------------------------------------------
# Kerrosten määrittely: nimi, minzoom, maxzoom, kuvaus
# ----------------------------------------------------------------------------------------
KERROKSET = {
    "rakennus": dict(tyyppi="polygon", minzoom=13, kuvaus="Rakennukset (Maastotietokanta)"),
    "kiinteistoraja": dict(tyyppi="line", minzoom=14, kuvaus="Kiinteistörajat (MML kiinteistörekisterikartta)"),
    "kiinteistotunnus": dict(tyyppi="point", minzoom=15, kuvaus="Kiinteistötunnukset palstojen kohdalla"),
    "maastokuvio": dict(tyyppi="polygon", minzoom=8, kuvaus="Maastokuviot ja vesialueet (Maastotietokanta)"),
    "tie": dict(tyyppi="line", minzoom=8, kuvaus="Tiet ja rautatiet (Maastotietokanta)"),
    "osoite": dict(tyyppi="point", minzoom=15, kuvaus="Rakennusten osoitteet (DVV, poiminta 3.2.2025)"),
    "turvalaite": dict(tyyppi="point", minzoom=8, kuvaus="Väyläviraston turvalaitteet valotunnuksineen ja sektoreineen"),
    "navigointilinja": dict(tyyppi="line", minzoom=10, kuvaus="Väyläviraston navigointilinjat"),
    "vaylaalue": dict(tyyppi="polygon", minzoom=8, kuvaus="Väyläviraston väyläalueet"),
    "vayla": dict(tyyppi="line", minzoom=8, kuvaus="Väylien keskilinjat"),
    "taululinja": dict(tyyppi="line", minzoom=10, kuvaus="Taululinjat"),
    "vesiliikennemerkki": dict(tyyppi="point", minzoom=12, kuvaus="Vesiliikennemerkit"),
    "nopeusrajoitus": dict(tyyppi="polygon", minzoom=10, kuvaus="Vesiväylien nopeusrajoitusalueet"),
    "sulkukanava": dict(tyyppi="polygon", minzoom=8, kuvaus="Sulkukanavat ja avattavat sillat"),
    "rantaviiva": dict(tyyppi="line", minzoom=8, kuvaus="Rantaviiva (järvien yhdistetty reuna)"),
    "syvyysalue": dict(tyyppi="polygon", minzoom=8, kuvaus="Syvyysalueet (Traficom)"),
    "syvyyskayra": dict(tyyppi="line", minzoom=10, kuvaus="Syvyyskäyrät (Traficom)"),
    "syvyyspiste": dict(tyyppi="point", minzoom=12, kuvaus="Syvyyspisteet (Traficom)"),
    "vesieste": dict(tyyppi="mixed", minzoom=12, kuvaus="Vesikivet, matalikot, aallonmurtajat ja laiturit (Maastotietokanta)"),
}

# Tieluokkien minzoom (näkyvyys karttatasoilla)
TIE_MINZOOM = {12111: 8, 12112: 8, 12121: 8, 12122: 9, 12131: 10, 12132: 10, 12141: 11, 12151: 8, 12152: 8,
               12311: 13, 12312: 13, 12313: 14, 12314: 14, 12316: 14, 14111: 9, 14112: 9, 14121: 11, 14131: 11}
MAASTOKUVIO_MINZOOM = {"jarvi": 8, "virtavesi": 11, "suo": 11, "soistuma": 12, "pelto": 11, "niitty": 12,
                       "kallio": 13, "kivikko": 13, "hietikko": 12, "taajama": 9, "puisto": 12,
                       "urheilu_virkistys": 12, "hautausmaa": 12, "autoliikenne": 12, "lentokentta": 10}


def kirjoita_rivit(polku, rivit):
    """Kirjoittaa GeoJSONSeq-tiedoston. Zoom-rajaukset tehdään tippecanoen -j-suodattimella (ks. zoom_suodatin),
    koska kohdekohtainen tippecanoe-minzoom-jäsen pudotti tiilestä kaikki paitsi yhden kohteen."""
    n = 0
    with open(polku, "w", encoding="utf-8") as f:
        for r in rivit:
            r.pop("tippecanoe", None)
            f.write(json.dumps(r, ensure_ascii=False, separators=(",", ":")))
            f.write("\n")
            n += 1
    return n


def gpkg_rivit(kerros, nimi_kentat=None, where=None):
    """Lue kerros rajattu.gpkg:stä, muunna EPSG:4326:een ja tuota GeoJSON-kohteita."""
    ds = ogr.Open(str(RAJATTU))
    k = ds.GetLayerByName(kerros)
    if k is None:
        loki("kerrosta ei löydy:", kerros)
        return
    if where:
        k.SetAttributeFilter(where)
    defn = k.GetLayerDefn()
    nimet = [defn.GetFieldDefn(i).GetName() for i in range(defn.GetFieldCount())]
    for ft in k:
        g = swkb.loads(bytes(ft.GetGeometryRef().ExportToWkb()))
        g = transform(T3067_4326.transform, g)
        props = {n: ft.GetField(n) for n in nimet}
        yield g, props


def geom_json(g, tarkkuus=6):
    """GeoJSON-geometria pyöristettynä (6 desimaalia = 0,1 m)."""
    def r(c):
        if isinstance(c[0], (list, tuple)):
            return [r(x) for x in c]
        return [round(c[0], tarkkuus), round(c[1], tarkkuus)]
    d = shape_to_dict(g)
    d["coordinates"] = r(d["coordinates"]) if "coordinates" in d else d.get("coordinates")
    return d


def shape_to_dict(g):
    from shapely.geometry import mapping
    d = mapping(g)
    return json.loads(json.dumps(d))


def piirre(g, props, minzoom=None, maxzoom=None):
    """minzoom ja maxzoom otetaan vastaan yhteensopivuuden vuoksi, mutta ne eivät mene tiedostoon."""
    return {"type": "Feature", "geometry": geom_json(g), "properties": {k: v for k, v in props.items() if v is not None}}


# ----------------------------------------------------------------------------------------
# Kerrosten kirjoitus GeoJSONiksi
# ----------------------------------------------------------------------------------------
def aoi_4326():
    from lataa import lataa_aoi
    vesi, alue, vyohyke, tied = lataa_aoi()
    return (transform(T3067_4326.transform, alue), transform(T3067_4326.transform, vesi),
            transform(T3067_4326.transform, vyohyke), tied)


def tee_rakennus():
    def r():
        for g, p in gpkg_rivit("rakennus"):
            yield piirre(g, {"kaytto": p["kaytto"], "krs": p["krs"] or None, "z": p["z"], "luokka": p["luokka"]})
    return kirjoita_rivit(GJ / "rakennus.geojsonl", r())


def tee_kiinteisto():
    n1 = kirjoita_rivit(GJ / "kiinteistoraja.geojsonl",
                        (piirre(g, {"laji": p["laji"]}) for g, p in gpkg_rivit("kiinteistoraja")))
    n2 = kirjoita_rivit(GJ / "kiinteistotunnus.geojsonl",
                        (piirre(g, {"tunnus": p["tunnus"], "kunta": p["kunta"]}) for g, p in gpkg_rivit("kiinteistotunnus")))
    return n1 + n2


def tee_maastokuvio():
    def r():
        for g, p in gpkg_rivit("maastokuvio"):
            yield piirre(g, {"luokka": p["luokka"], "koodi": p["koodi"]}, minzoom=MAASTOKUVIO_MINZOOM.get(p["luokka"], 12))
    return kirjoita_rivit(GJ / "maastokuvio.geojsonl", r())


def tee_tie():
    def r():
        for g, p in gpkg_rivit("tie"):
            yield piirre(g, {"luokka": p["luokka"], "nimi": p["nimi"] or None, "tienumero": p["tienumero"] or None,
                             "paallyste": p["paallyste"], "taso": p["taso"]}, minzoom=TIE_MINZOOM.get(p["luokka"], 12))
    return kirjoita_rivit(GJ / "tie.geojsonl", r())


def tee_rantaviiva():
    def r():
        for g, p in gpkg_rivit("rantaviiva"):
            yield piirre(g, {"luokka": p["luokka"]})
    return kirjoita_rivit(GJ / "rantaviiva.geojsonl", r())


def tee_osoite():
    def r():
        for g, p in gpkg_rivit("osoite"):
            yield piirre(g, {"osoite": p["osoite"], "postinumero": p["postinumero"], "tyyppi": p["tyyppi"]})
    return kirjoita_rivit(GJ / "osoite.geojsonl", r())


def tee_vesieste():
    def r():
        for kerros in ("vesieste_piste", "vesieste_alue", "vesieste_viiva"):
            for g, p in gpkg_rivit(kerros):
                yield piirre(g, {"laji": p["laji"]})
    return kirjoita_rivit(GJ / "vesieste.geojsonl", r())


# -- Väylävirasto ------------------------------------------------------------------------
def lue_wfs(polku):
    try:
        return json.loads(Path(polku).read_text(encoding="utf-8")).get("features", [])
    except FileNotFoundError:
        return []


def parsi_sektorit(teksti):
    """'Alkukulma: 136, Loppukulma: 223, Väri: vi' (useampi sektori eroteltu puolipisteellä tai rivinvaihdolla)."""
    tulos = []
    if not teksti or teksti.strip() in ("-", ""):
        return tulos
    for m in re.finditer(r"Alkukulma:\s*([\d.,]+)\s*,\s*Loppukulma:\s*([\d.,]+)\s*,\s*Väri:\s*([A-Za-zÅÄÖåäö]+)", teksti):
        tulos.append({"alku": float(m.group(1).replace(",", ".")), "loppu": float(m.group(2).replace(",", ".")), "vari": m.group(3)})
    return tulos


def piste_wfs(geom):
    g = shape(geom)
    if g.geom_type == "MultiPoint":
        return g.geoms[0]
    return g


def tee_vayla(alue):
    pa = prep(alue)
    ulos = {}
    # Valot ja sektorit
    loistot = {}
    for f in lue_wfs(RAAKA / "vayla" / "loistot_uusi.json"):
        p = f["properties"]
        loistot.setdefault(str(p.get("turvalaitenumero")), []).append(p)
    sektorit = {}
    for f in lue_wfs(RAAKA / "vayla" / "valosektorit_uusi.json"):
        p = f["properties"]
        sektorit.setdefault(str(p.get("tlnumero")), []).append(
            {"alku": p.get("alkukulma"), "loppu": p.get("loppukulma"), "vari": p.get("vari"), "loisto": p.get("loisto")})

    rivit = []
    tilasto = {"turvalaitteita": 0, "valaistuja": 0, "valaistuja_ilman_valotunnusta": [], "sektoreita": 0,
               "valaistuja_ilman_sektoreita": []}
    nahdyt = set()
    for muut, tiedosto in ((False, "turvalaitteet_uusi.json"), (True, "turvalaitteet_muut_vaylanpitajat.json")):
        for f in lue_wfs(RAAKA / "vayla" / tiedosto):
            p = f["properties"]
            g = piste_wfs(f["geometry"])
            if not pa.contains(g):
                continue
            nro = str(p.get("turvalaitenumero"))
            if nro in nahdyt:      # muiden väylänpitäjien kerros toistaa osan Väyläviraston turvalaitteista
                continue
            nahdyt.add(nro)
            lo = loistot.get(nro, [])
            sek = sektorit.get(nro, [])
            valaistu = p.get("valaistu")
            kv = next((l.get("viralvalotunnuse") for l in lo if l.get("viralvalotunnuse")), None)
            fi = next((l.get("virallvalotunnus") for l in lo if l.get("virallvalotunnus")), None)
            # Jos sektorit puuttuvat sektorikerroksesta, luetaan ne turvalaiteen omasta tekstikentästä
            if not sek:
                sek = [dict(s, loisto=None) for s in parsi_sektorit(p.get("valosektorien_tiedot"))]
            props = {
                "numero": nro, "nimi": p.get("nimifi"), "nimi_sv": p.get("nimisv"), "tyyppi": p.get("turvalaitetyyppifi"),
                "alityyppi": p.get("alityyppi"), "navigointilaji": p.get("navigointilajikoodi"), "valaistu": valaistu,
                "valotunnus": kv, "valotunnus_fi": fi,
                "valon_laji": next((l.get("laji") for l in lo if l.get("laji")), None),
                "valon_korkeus_vedesta": next((l.get("korkeusvedesta") for l in lo if l.get("korkeusvedesta") is not None), None),
                "valon_nakyvyys": next((l.get("optinenkanto") for l in lo if l.get("optinenkanto") is not None), None),
                "sektorit": json.dumps([{k: v for k, v in s.items() if k != "loisto" and v is not None} for s in sek],
                                       ensure_ascii=False, separators=(",", ":")) if sek else None,
                "vayla": re.sub(r"^\[(.*?)\].*$", r"\1", p.get("vaylan_nimi") or "") or None,
                "omistaja": p.get("omistajafi") or p.get("omistaja"), "muu_vaylanpitaja": 1 if muut else None,
                "tila": p.get("toimintatilakoodi"),
            }
            rivit.append(piirre(g, props))
            if not muut:
                tilasto["turvalaitteita"] += 1
            if valaistu == "K":
                tilasto["valaistuja"] += 1
                if not (kv or fi):
                    tilasto["valaistuja_ilman_valotunnusta"].append(nro)
                if not sek:
                    tilasto["valaistuja_ilman_sektoreita"].append(nro)
                tilasto["sektoreita"] += len(sek)
    n = kirjoita_rivit(GJ / "turvalaite.geojsonl", rivit)
    ulos["turvalaite"] = n
    ulos["_tilasto"] = tilasto

    def yleinen(tiedosto, nimi, kentat, minzoom=None, geom_muunnos=None):
        rr = []
        for f in lue_wfs(RAAKA / "vayla" / tiedosto):
            g = shape(f["geometry"])
            if g.geom_type == "MultiPoint" and len(g.geoms) == 1:
                g = g.geoms[0]
            if not pa.intersects(g):
                continue
            p = f["properties"]
            pr = {}
            for k_ulos, k_sis in kentat.items():
                v = p.get(k_sis)
                if isinstance(v, str):
                    v = re.sub(r"^\[(.*?)\]\(.*\)$", r"\1", v)
                pr[k_ulos] = v
            rr.append(piirre(g, pr, minzoom=minzoom))
        ulos[nimi] = kirjoita_rivit(GJ / (nimi + ".geojsonl"), rr)

    yleinen("navigointilinjat_uusi.json", "navigointilinja",
            {"tyyppi": "tyyppi", "mitoitussyvays": "mitoitussyvays", "haraussyvyys": "haraussyvyys", "suunta": "suunta",
             "tosisuunta": "tosisuunta", "pituus": "pituus", "vaylan_nimi": "vaylan_nimi", "jnro": "jnro"})
    yleinen("vaylaalueet_uusi.json", "vaylaalue",
            {"tyyppi": "tyyppi", "liikenteentyyppi": "liikenteentyyppi", "mitoitussyvays": "mitoitussyvays",
             "haraussyvyys": "haraussyvyys", "liikennointistatus": "liikennointistatus", "vaylan_nimi": "vaylan_nimi",
             "jnro": "jnro"})
    yleinen("vaylat_uusi.json", "vayla",
            {"nimi": "nimifi", "luokka": "vaylaluokkafi", "laji": "vaylalajifi", "mitoitussyvays": "mitoitussyvays",
             "jnro": "jnro", "valaistus": "valaistusfi"})
    yleinen("taululinjat_uusi.json", "taululinja",
            {"suunta": "suunta", "tyyppi": "tyyppi", "vaylan_nimi": "vaylan_nimi", "jnro": "jnro"})
    yleinen("vesiliikennemerkit_uusi.json", "vesiliikennemerkki",
            {"nimi": "nimifi", "lajityyppi": "vlmlajityyppi", "tyyppi": "vlmtyyppi", "rajoitusarvo": "rajoitusarvo",
             "lisakilpi1": "lisakilventeksti1", "lisakilpi2": "lisakilventeksti2", "vaikutusalue": "vaikutusalue",
             "vaylan_nimi": "vaylan_nimi"})
    yleinen("vesivaylien_nopeusrajoitusalueet.json", "nopeusrajoitus",
            {"tyyppi": "rajoitustyyppi", "suuruus": "suuruus", "poikkeus": "poikkeus", "lisatieto": "lisatieto",
             "paatostila": "paatostila", "alku": "alkupaivamaara", "loppu": "loppupaivamaara", "vaylan_nimi": "vaylan_nimi"})
    yleinen("sulkukanavat_uusi.json", "sulkukanava",
            {"nimi": "nimi", "vesisto": "vesisto", "mista": "mista", "mihin": "mihin", "sulkuleveys": "sulkuleveys",
             "sulkuleveyspituus": "sulkuleveyspituus", "putouskorkeus1": "putouskorkeus1", "putouskorkeus2": "putouskorkeus2",
             "alusleveys": "alusleveys", "aluspituus": "aluspituus", "alussyvyys": "alussyvyys",
             "aluskorkeus": "aluskorkeus", "kayttoselite": "kayttoselite"})
    # Muiden väylänpitäjien navigointilinjat samaan kerrokseen
    ekstra = []
    for f in lue_wfs(RAAKA / "vayla" / "navigointilinjat_muut_vaylanpitajat.json"):
        g = shape(f["geometry"])
        if pa.intersects(g):
            p = f["properties"]
            ekstra.append(piirre(g, {"tyyppi": p.get("tyyppi"), "mitoitussyvays": p.get("mitoitussyvays"),
                                     "haraussyvyys": p.get("haraussyvyys"), "suunta": p.get("suunta"),
                                     "tosisuunta": p.get("tosisuunta"), "muu_vaylanpitaja": 1}))
    if ekstra:
        with open(GJ / "navigointilinja.geojsonl", "a", encoding="utf-8") as f:
            for r in ekstra:
                f.write(json.dumps(r, ensure_ascii=False, separators=(",", ":")) + "\n")
        ulos["navigointilinja"] += len(ekstra)
    return ulos


# -- Traficom ----------------------------------------------------------------------------
def tee_traficom(alue):
    pa = prep(alue)
    ulos = {}

    def luku(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    rr = []
    for f in lue_wfs(RAAKA / "traficom" / "DepthArea_A.json"):
        g = shape(f["geometry"])
        if not pa.intersects(g):
            continue
        p = f["properties"]
        rr.append(piirre(g, {"alin": luku(p.get("DRVAL1")), "ylin": luku(p.get("DRVAL2")), "mitattu": p.get("SORDAT")}))
    ulos["syvyysalue"] = kirjoita_rivit(GJ / "syvyysalue.geojsonl", rr)
    rr = []
    for f in lue_wfs(RAAKA / "traficom" / "DepthContour_L.json"):
        g = shape(f["geometry"])
        if not pa.intersects(g):
            continue
        p = f["properties"]
        rr.append(piirre(g, {"syvyys": luku(p.get("VALDCO")), "mitattu": p.get("SORDAT")}))
    ulos["syvyyskayra"] = kirjoita_rivit(GJ / "syvyyskayra.geojsonl", rr)
    rr = []
    for f in lue_wfs(RAAKA / "traficom" / "Sounding_P.json"):
        g = shape(f["geometry"])
        if g.geom_type == "MultiPoint":
            g = g.geoms[0]
        g = Point(g.x, g.y)
        if not pa.contains(g):
            continue
        p = f["properties"]
        rr.append(piirre(g, {"syvyys": luku(p.get("DEPTH")), "taso": p.get("AHTI_VERDA"), "mitattu": p.get("SORDAT")}))
    ulos["syvyyspiste"] = kirjoita_rivit(GJ / "syvyyspiste.geojsonl", rr)
    return ulos


# ----------------------------------------------------------------------------------------
# Vektoritiilet (tippecanoe)
# ----------------------------------------------------------------------------------------
def zoom_suodatin():
    """Tippecanoen -j-suodatin: kerroksen ja luokan minzoom ($zoom-vertailuna)."""
    def luokittain(kartta, oletus):
        ryhmat = {}
        for luokka, mz in kartta.items():
            ryhmat.setdefault(mz, []).append(luokka)
        ehdot = [["all", ["in", "luokka"] + sorted(l), [">=", "$zoom", mz]] for mz, l in sorted(ryhmat.items())]
        kaikki = sorted(kartta)
        ehdot.append(["all", ["!in", "luokka"] + kaikki, [">=", "$zoom", oletus]])
        return ["any"] + ehdot
    suodatin = {}
    for nimi, k in KERROKSET.items():
        if k["minzoom"] > VEKTORI_MINZ:
            suodatin[nimi] = [">=", "$zoom", k["minzoom"]]
    suodatin["tie"] = luokittain(TIE_MINZOOM, 12)
    suodatin["maastokuvio"] = luokittain(MAASTOKUVIO_MINZOOM, 12)
    return suodatin


def rakenna_vektori():
    GJ.mkdir(parents=True, exist_ok=True)
    alue, vesi, vyohyke, tied = aoi_4326()
    maarat = {}
    t = time.time()
    for nimi, fn in (("rakennus", tee_rakennus), ("kiinteisto", tee_kiinteisto), ("maastokuvio", tee_maastokuvio),
                     ("tie", tee_tie), ("rantaviiva", tee_rantaviiva), ("osoite", tee_osoite),
                     ("vesieste", tee_vesieste)):
        maarat[nimi] = fn()
        loki("kerros %s: %s kohdetta" % (nimi, maarat[nimi]))
    maarat.update(tee_vayla(alue))
    loki("Väylävirasto:", {k: v for k, v in maarat.items() if k in ("turvalaite", "navigointilinja", "vaylaalue")})
    maarat.update(tee_traficom(alue))
    loki("GeoJSON-kerrokset valmiit %.0f s" % (time.time() - t))
    kirjoita_json(TYO / "kerrosmaarat.json", maarat)

    ULOS.mkdir(exist_ok=True)
    tulos = TYO / "nasijarvi.pmtiles"
    komento = ["tippecanoe", "-o", tulos, "-Z%d" % VEKTORI_MINZ, "-z%d" % VEKTORI_MAXZ, "--force",
               "--drop-densest-as-needed", "--no-progress-indicator", "-j", json.dumps(zoom_suodatin(), separators=(",", ":")),
               "--read-parallel", "--name=Nasijarven aineisto", "--attribution=Katso aineisto.json",
               "--description=Nasijarven aineistopaketti: rakennukset, rajat, maasto, vayla ja syvyys"]
    kerrokset = [("rakennus", "rakennus"), ("kiinteistoraja", "kiinteistoraja"), ("kiinteistotunnus", "kiinteistotunnus"),
                 ("maastokuvio", "maastokuvio"), ("tie", "tie"), ("osoite", "osoite"), ("turvalaite", "turvalaite"),
                 ("navigointilinja", "navigointilinja"), ("vaylaalue", "vaylaalue"), ("vayla", "vayla"),
                 ("taululinja", "taululinja"), ("vesiliikennemerkki", "vesiliikennemerkki"),
                 ("nopeusrajoitus", "nopeusrajoitus"), ("sulkukanava", "sulkukanava"), ("rantaviiva", "rantaviiva"),
                 ("syvyysalue", "syvyysalue"), ("syvyyskayra", "syvyyskayra"), ("syvyyspiste", "syvyyspiste"),
                 ("vesieste", "vesieste")]
    for tiedosto, nimi in kerrokset:
        polku = GJ / (tiedosto + ".geojsonl")
        if not polku.exists() or polku.stat().st_size == 0:
            loki("kerros tyhjä, ohitetaan:", nimi)
            continue
        asetus = {"file": str(polku), "layer": nimi}
        komento += ["-L", json.dumps(asetus)]
    t = time.time()
    aja(komento)
    loki("tippecanoe valmis %.0f s, %.1f Mt" % (time.time() - t, tulos.stat().st_size / 1e6))
    shutil.copyfile(tulos, ULOS / "nasijarvi.pmtiles")
    return maarat


# ----------------------------------------------------------------------------------------
# Rasteritiilet
# ----------------------------------------------------------------------------------------
WM = 20037508.342789244


def tiili_bbox(z, x, y):
    koko = 2 * WM / (1 << z)
    return (-WM + x * koko, WM - (y + 1) * koko, -WM + (x + 1) * koko, WM - y * koko)


def lon_lat_tiiliksi(lon, lat, z):
    n = 1 << z
    x = int((lon + 180.0) / 360.0 * n)
    lr = math.radians(lat)
    y = int((1.0 - math.asinh(math.tan(lr)) / math.pi) / 2.0 * n)
    return x, y


def tiilet_alueelle(geom3857, z, jata_pois=None):
    """Kaikki z-tason tiilet, jotka leikkaavat geometriaa."""
    x0, y0, x1, y1 = geom3857.bounds
    koko = 2 * WM / (1 << z)
    xa, xb = int((x0 + WM) // koko), int((x1 + WM) // koko)
    ya, yb = int((WM - y1) // koko), int((WM - y0) // koko)
    p = prep(geom3857)
    tulos = []
    for x in range(xa, xb + 1):
        for y in range(ya, yb + 1):
            tb = box(*tiili_bbox(z, x, y))
            if p.intersects(tb):
                if jata_pois is not None and jata_pois.contains(tb):
                    continue
                tulos.append((z, x, y))
    return tulos


def pmtiles_kirjoita(polku, tiilet, tuota, tyyppi, metadata, minz, maxz, bbox4326, keskipiste):
    """Kirjoittaa PMTiles-arkiston. tiilet: [(z,x,y)], tuota(z,x,y) -> bytes | None."""
    from pmtiles.tile import Compression, TileType, zxy_to_tileid
    from pmtiles.writer import write
    jarjestetty = sorted(tiilet, key=lambda t: zxy_to_tileid(*t))
    n = 0
    koko = 0
    with write(str(polku)) as w:
        for (z, x, y) in jarjestetty:
            data = tuota(z, x, y)
            if data is None:
                continue
            w.write_tile(zxy_to_tileid(z, x, y), data)
            n += 1
            koko += len(data)
        header = {
            "tile_type": tyyppi, "tile_compression": Compression.NONE,
            "min_zoom": minz, "max_zoom": maxz,
            "min_lon_e7": int(bbox4326[0] * 1e7), "min_lat_e7": int(bbox4326[1] * 1e7),
            "max_lon_e7": int(bbox4326[2] * 1e7), "max_lat_e7": int(bbox4326[3] * 1e7),
            "center_zoom": keskipiste[2], "center_lon_e7": int(keskipiste[0] * 1e7),
            "center_lat_e7": int(keskipiste[1] * 1e7),
        }
        w.finalize(header, metadata)
    return n, koko


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


def png_tavut(arr, optimoi=True):
    im = Image.fromarray(arr)
    b = io.BytesIO()
    im.save(b, format="PNG", optimize=optimoi, compress_level=9)
    return b.getvalue()


def warp_muistiin(lahde, bbox, koko, resamppaus, nodata, tyyppi=gdal.GDT_Float32, src_nodata=None):
    """Warppaa rasterin EPSG:3857-tiiliksi (muistiin) ja palauttaa numpy-taulukon."""
    ds = gdal.Warp("", lahde, format="MEM", dstSRS="EPSG:3857", outputBounds=bbox, width=koko, height=koko,
                   resampleAlg=resamppaus, srcNodata=src_nodata if src_nodata is not None else nodata,
                   dstNodata=nodata, outputType=tyyppi, multithread=False)
    a = ds.GetRasterBand(1).ReadAsArray()
    ds = None
    return a


def viivoita_maski(vyohyke3857, bbox, koko):
    """Rasteroi geometrian tiilen pikseleihin (True = geometrian sisällä)."""
    tb = box(*bbox)
    g = vyohyke3857.intersection(tb)
    if g.is_empty:
        return None
    if g.contains(tb) or g.equals(tb):
        return np.ones((koko, koko), dtype=bool)
    im = Image.new("1", (koko, koko), 0)
    d = ImageDraw.Draw(im)
    x0, y0, x1, y1 = bbox
    k = koko / (x1 - x0)

    def pix(c):
        return [((x - x0) * k, (y1 - y) * k) for x, y in c]
    for poly in getattr(g, "geoms", [g]):
        if poly.geom_type != "Polygon":
            continue
        d.polygon(pix(poly.exterior.coords), fill=1)
        for ring in poly.interiors:
            d.polygon(pix(ring.coords), fill=0)
    return np.array(im, dtype=bool)


def rakenna_maasto(kvantti=None):
    kvantti = TERRAIN_KVANTTI if kvantti is None else kvantti
    alue4326, vesi4326, vyohyke4326, tied = aoi_4326()
    from lataa import lataa_aoi
    vesi, alue, vyohyke, _ = lataa_aoi()
    alue_wm = transform(T3067_3857.transform, alue)
    vesi_wm = transform(T3067_3857.transform, vesi.simplify(3)).buffer(0)
    vyoh_wm = transform(T3067_3857.transform, vyohyke).buffer(0)
    vesi_prep = prep(vesi_wm)
    dem10 = str(TYO / "dem10.tif")
    dem2 = str(TYO / "dem2.vrt")
    tiilet = []
    for z in range(TERRAIN_MINZ, TERRAIN_MAXZ + 1):
        tiilet += tiilet_alueelle(alue_wm, z, jata_pois=vesi_wm)
    loki("Maastotiiliä (vain maa- ja rantatiilet): %d" % len(tiilet))
    tilasto = {"kaytetty_2m": 0, "tiilia": 0, "ohitettu_ei_dataa": 0}
    pyyntoja_kpl = [0]

    def tuota(z, x, y):
        bbox = tiili_bbox(z, x, y)
        # Hieman reunaa varten ei tarvita: jokainen tiili lasketaan omasta datastaan.
        h = warp_muistiin(dem10, bbox, TERRAIN_TILE_PX, "bilinear" if z >= 13 else "average", -9999.0)
        h = np.where(h <= -9000, np.nan, h)
        if z == TERRAIN_MAXZ:
            m = viivoita_maski(vyoh_wm, bbox, TERRAIN_TILE_PX)
            if m is not None and m.any():
                h2 = warp_muistiin(dem2, bbox, TERRAIN_TILE_PX, "average", -9999.0)
                h2 = np.where(h2 <= -9000, np.nan, h2)
                kayt = m & np.isfinite(h2)
                if kayt.any():
                    h = np.where(kayt, h2, h)
                    tilasto["kaytetty_2m"] += 1
        if not np.isfinite(h).any():
            tilasto["ohitettu_ei_dataa"] += 1
            return None
        tilasto["tiilia"] += 1
        return png_tavut(koodaa_terrain(h, kvantti))

    t = time.time()
    polku = TYO / "maasto.pmtiles"
    from pmtiles.tile import TileType
    bb = tied["bbox_4326"]
    meta = {"name": "Nasijarven maasto", "format": "png", "type": "baselayer", "encoding": "mapbox",
            "description": "Terrain-RGB (Mapbox). korkeus_m = -10000 + (R*65536 + G*256 + B) * 0,1. RGB (0,0,0) = ei dataa. "
                           "Korkeusjarjestelma N2000. Puuttuva tiili = vesialue.",
            "attribution": "Maanmittauslaitos, Korkeusmalli 2 m ja 10 m, CC BY 4.0", "tile_size": TERRAIN_TILE_PX,
            "quantization_m": kvantti}
    n, koko = pmtiles_kirjoita(polku, tiilet, tuota, TileType.PNG, meta, TERRAIN_MINZ, TERRAIN_MAXZ, bb,
                               ((bb[0] + bb[2]) / 2, (bb[1] + bb[3]) / 2, 11))
    loki("maasto.pmtiles: %d tiiltä, %.1f Mt, %.0f s, tilasto %s" % (n, koko / 1e6, time.time() - t, tilasto))
    shutil.copyfile(polku, ULOS / "maasto.pmtiles")
    kirjoita_json(TYO / "maasto_tilasto.json", dict(tilasto, tiilia_pmtiles=n, tavua=koko, kvantti=kvantti,
                                                    sekuntia=round(time.time() - t, 1)))


def rakenna_puusto():
    from lataa import lataa_aoi
    vesi, alue, vyohyke, tied = lataa_aoi()
    alue_wm = transform(T3067_3857.transform, alue)
    vesi_wm = transform(T3067_3857.transform, vesi.simplify(3)).buffer(0)
    kp = str(TYO / "luke_keskipituus.tif")
    lp = str(TYO / "luke_latvuspeitto.tif")
    tiilet = []
    for z in range(PUUSTO_MINZ, PUUSTO_MAXZ + 1):
        tiilet += tiilet_alueelle(alue_wm, z, jata_pois=vesi_wm)
    loki("Puustotiiliä: %d" % len(tiilet))
    EI = 32767
    tilasto = {"tiilia": 0, "ohitettu_ei_dataa": 0}

    def tuota(z, x, y):
        bbox = tiili_bbox(z, x, y)
        alg = "near" if z >= 13 else "average"
        a = warp_muistiin(kp, bbox, TERRAIN_TILE_PX, alg, float(EI), tyyppi=gdal.GDT_Float32, src_nodata=float(EI))
        c = warp_muistiin(lp, bbox, TERRAIN_TILE_PX, alg, float(EI), tyyppi=gdal.GDT_Float32, src_nodata=float(EI))
        ok = (a < 32000) & (c < 32000)
        if not ok.any():
            tilasto["ohitettu_ei_dataa"] += 1
            return None
        v = np.where(ok, np.round(a), 0).astype(np.int64)
        rgba = np.zeros((TERRAIN_TILE_PX, TERRAIN_TILE_PX, 4), dtype=np.uint8)
        rgba[..., 0] = (v >> 8) & 255
        rgba[..., 1] = v & 255
        rgba[..., 2] = np.where(ok, np.clip(np.round(c), 0, 100), 0).astype(np.uint8)
        rgba[..., 3] = np.where(ok, 255, 0).astype(np.uint8)
        tilasto["tiilia"] += 1
        return png_tavut(rgba)

    from pmtiles.tile import TileType
    bb = tied["bbox_4326"]
    meta = {"name": "Nasijarven puusto", "format": "png", "type": "overlay", "encoding": "puusto",
            "description": "RGBA PNG. Keskipituus desimetreina = R*256 + G. Latvuspeitto prosentteina = B. "
                           "A=0: ei metsamaata tai ei dataa. Luke MVMI 2023, 16 m.",
            "attribution": "Luonnonvarakeskus, monilahteinen valtakunnan metsien inventointi 2023, CC BY 4.0",
            "tile_size": TERRAIN_TILE_PX}
    t = time.time()
    polku = TYO / "puusto.pmtiles"
    n, koko = pmtiles_kirjoita(polku, tiilet, tuota, TileType.PNG, meta, PUUSTO_MINZ, PUUSTO_MAXZ, bb,
                               ((bb[0] + bb[2]) / 2, (bb[1] + bb[3]) / 2, 11))
    loki("puusto.pmtiles: %d tiiltä, %.1f Mt, %.0f s" % (n, koko / 1e6, time.time() - t))
    shutil.copyfile(polku, ULOS / "puusto.pmtiles")
    kirjoita_json(TYO / "puusto_tilasto.json", dict(tilasto, tiilia_pmtiles=n, tavua=koko, sekuntia=round(time.time() - t, 1)))


TERRAIN_KVANTTI = 0.5


# ----------------------------------------------------------------------------------------
# Aineistokuvaus ja sivuston tiedostot
# ----------------------------------------------------------------------------------------
LAHTEET = [
    {"id": "mml_maastotietokanta", "nimi": "Maastotietokanta 2025 (Shapefile-lehdet ja GeoPackage tieviivoille)",
     "tuottaja": "Maanmittauslaitos", "ehtotiedosto": "MML",
     "osoite": PAITULI + "mml/maastotietokanta/2025/", "kerrokset": ["rakennus", "maastokuvio", "tie", "rantaviiva", "vesieste"],
     "lisenssi": "CC BY 4.0", "lisenssi_url": "https://creativecommons.org/licenses/by/4.0/",
     "lahdemerkinta": "Sisältää Maanmittauslaitoksen Maastotietokanta-aineistoa 04/2025 (CC BY 4.0).",
     "huomio": "Rakennusten kerrosluku on MML:n luokittelu (1-2 kerrosta, 3 tai enemmän). Tarkkaa kerroslukua ei ole."},
    {"id": "mml_kiinteisto", "nimi": "Kiinteistörajat ja palstatunnukset 2025",
     "tuottaja": "Maanmittauslaitos", "ehtotiedosto": "MML",
     "osoite": PAITULI + "mml/kiinteisto/2025/", "kerrokset": ["kiinteistoraja", "kiinteistotunnus"],
     "lisenssi": "CC BY 4.0", "lisenssi_url": "https://creativecommons.org/licenses/by/4.0/",
     "lahdemerkinta": "Sisältää Maanmittauslaitoksen kiinteistörajatietoja 05/2025 (CC BY 4.0).",
     "huomio": "Omistajatietoja ei ole eikä niitä haeta."},
    {"id": "mml_korkeusmalli", "nimi": "Korkeusmalli 2 m (rantavyöhyke) ja 10 m",
     "tuottaja": "Maanmittauslaitos", "ehtotiedosto": "MML",
     "osoite": PAITULI + "mml/dem2m/2008_latest/ ja " + PAITULI + "mml/dem10m/2019/", "kerrokset": ["maasto.pmtiles"],
     "lisenssi": "CC BY 4.0", "lisenssi_url": "https://creativecommons.org/licenses/by/4.0/",
     "lahdemerkinta": "Sisältää Maanmittauslaitoksen korkeusmalliaineistoa (2 m ja 10 m) (CC BY 4.0).",
     "huomio": "Korkeusjärjestelmä N2000. Lähteen nodata -9999."},
    {"id": "dvv_osoitteet", "nimi": "Rakennusten osoitetiedot (DVV, poiminta 3.2.2025)",
     "tuottaja": "Digi- ja väestötietovirasto", "ehtotiedosto": "DVV",
     "osoite": PAITULI + "dvv/osoitteet/2025/osoiteet_2025.shp", "kerrokset": ["osoite"],
     "lisenssi": "CC BY 4.0", "lisenssi_url": "https://creativecommons.org/licenses/by/4.0/",
     "lahdemerkinta": "Sisältää Digi- ja väestötietoviraston rakennusten osoitetietoja (poiminta 3.2.2025, CC BY 4.0).",
     "huomio": "DVV lopetti aineiston avoimen jakelun 14.3.2025. Tämä on viimeinen avoin versio eikä se päivity."},
    {"id": "luke_mvmi", "nimi": "Monilähteinen valtakunnan metsien inventointi 2023: puuston keskipituus ja latvuspeitto",
     "tuottaja": "Luonnonvarakeskus", "ehtotiedosto": "Luke",
     "osoite": PAITULI + "luke/vmi/2023/", "kerrokset": ["puusto.pmtiles"],
     "lisenssi": "CC BY 4.0", "lisenssi_url": "https://creativecommons.org/licenses/by/4.0/",
     "lahdemerkinta": "Sisältää Luonnonvarakeskuksen monilähteisen valtakunnan metsien inventoinnin 2023 aineistoa (CC BY 4.0).",
     "huomio": "Resoluutio 16 m. Keskipituus desimetreinä, latvuspeitto prosentteina, 32767 = ei metsämaata tai ei dataa."},
    {"id": "vayla_wfs", "nimi": "Väyläviraston vesiväyläaineisto (Väylätiedot WFS)",
     "tuottaja": "Väylävirasto", "ehtotiedosto": None,
     "osoite": VAYLA_WFS, "kerrokset": ["turvalaite", "navigointilinja", "vaylaalue", "vayla", "taululinja",
                                       "vesiliikennemerkki", "nopeusrajoitus", "sulkukanava"],
     "lisenssi": "CC BY 4.0", "lisenssi_url": "http://creativecommons.org/licenses/by/4.0/",
     "lahdemerkinta": "Sisältää Väyläviraston vesiväyläaineistoa (CC BY 4.0).",
     "huomio": "Palvelun kuvauksen mukaan aineisto ei sovellu navigointikäyttöön."},
    {"id": "traficom_syvyys", "nimi": "Merikarttatietokannan syvyysaineisto (Traficom, INSPIRE-palvelu rajoitettu)",
     "tuottaja": "Liikenne- ja viestintävirasto Traficom", "ehtotiedosto": None,
     "osoite": TRAFICOM_WFS, "kerrokset": ["syvyysalue", "syvyyskayra", "syvyyspiste"],
     "lisenssi": "Traficomin hydrografisen aineiston lisenssi", "lisenssi_url": None,
     "lahdemerkinta": "Sisältää Liikenne- ja viestintäviraston merikarttatietokannan tietoa {kk}/{vuosi}. Ei navigointikäyttöön. Ei täytä asianmukaisen merikartan vaatimuksia.",
     "huomio": "Lupa koskee vain muuta kuin navigointikäyttöä ja ei-kaupallista käyttöä. Lähdemerkintä on tuotava näkyviin tiedonsiirron ajankohtineen ja lisenssin kopio tai linkki mukaan."},
]


def tiedoston_sha(polku):
    h = hashlib.sha256()
    with open(polku, "rb") as f:
        for osa in iter(lambda: f.read(1 << 20), b""):
            h.update(osa)
    return h.hexdigest()


def rakenna_kuvaus():
    ULOS.mkdir(exist_ok=True)
    loki_ = lue_json(TYO / "lataus_loki.json", {})
    aoi = lue_json(TYO / "aoi.json", {})
    maarat = lue_json(TYO / "kerrosmaarat.json", {})
    ehdot = {}
    for nimi in ("MML", "DVV", "Luke", "MTK"):
        p = RAAKA / "ehdot" / (nimi + ".txt")
        if p.exists():
            ehdot[nimi] = p.read_text(encoding="utf-8").strip()
    traficom_haettu = (loki_.get("traficom") or {}).get("haettu") or nyt_iso()
    kk, vuosi = traficom_haettu[5:7], traficom_haettu[:4]
    lahteet = []
    for l in LAHTEET:
        d = dict(l)
        d["lahdemerkinta"] = d["lahdemerkinta"].format(kk=kk, vuosi=vuosi)
        et = d.pop("ehtotiedosto")
        d["ehtoteksti_sanatarkasti"] = ehdot.get(et) if et else None
        if d["id"] == "vayla_wfs":
            d["ehtoteksti_sanatarkasti"] = ("The data in this service is licensed under a Creative Commons Attribution 4.0 "
                                            "license - http://creativecommons.org/licenses/by/4.0/ (WFS GetCapabilities, "
                                            "AccessConstraints). Palvelun kuvaus: Aineisto ei sovellu navigointikäyttöön.")
        if d["id"] == "traficom_syvyys":
            caps = RAAKA / "traficom" / "capabilities.xml"
            teksti = None
            if caps.exists():
                m = re.search(r"<(?:ows:)?AccessConstraints>(.*?)</(?:ows:)?AccessConstraints>", caps.read_text(encoding="utf-8"), re.S)
                teksti = re.sub(r"\s+", " ", m.group(1)).strip() if m else None
            d["ehtoteksti_sanatarkasti"] = teksti
        # haku- ja siirtotiedot lokista
        avain = {"mml_maastotietokanta": "mtk", "mml_kiinteisto": "kiinteisto", "mml_korkeusmalli": "dem2",
                 "dvv_osoitteet": "dvv", "luke_mvmi": "luke_keskipituus", "vayla_wfs": "vayla",
                 "traficom_syvyys": "traficom"}[d["id"]]
        lo = loki_.get(avain) or {}
        d["haettu"] = lo.get("haettu")
        d["siirretty_tavua"] = lo.get("tavua") or lo.get("siirretty_tavua")
        lahteet.append(d)
    tiedostot = []
    for nimi in ("nasijarvi.pmtiles", "maasto.pmtiles", "puusto.pmtiles"):
        p = ULOS / nimi
        if p.exists():
            tiedostot.append({"nimi": nimi, "tavua": p.stat().st_size, "sha256": tiedoston_sha(p)})
    kerrokset = {}
    for nimi, k in KERROKSET.items():
        kerrokset[nimi] = {"tyyppi": k["tyyppi"], "minzoom": k["minzoom"], "maxzoom": VEKTORI_MAXZ, "kuvaus": k["kuvaus"],
                           "kohteita": maarat.get(nimi), "kentat": KENTAT.get(nimi, {})}
    vesitaso = None
    ms = lue_json(TYO / "maasto_tilasto.json", {})
    kuvaus = {
        "versio": 1,
        "paiva": time.strftime("%Y-%m-%d"),
        "luotu": nyt_iso(),
        "alue": {"nimi": "Näsijärvi, Tampereen Mustalahdesta Muroleen kanavan kautta Ruoveden suuntaan",
                 "bbox_epsg3067": aoi.get("bbox_3067"), "bbox_wgs84": aoi.get("bbox_4326"),
                 "rantapuskuri_m": aoi.get("rantapuskuri_m"), "rantavyohyke_2m_m": aoi.get("rantavyohyke_m"),
                 "vesialue_km2": aoi.get("vesialue_km2"), "alue_km2": aoi.get("alue_km2"),
                 "maarittelyn_bbox_epsg3067": aoi.get("maarittelyn_bbox_3067"),
                 "huomio": "Rajaus lasketaan Maastotietokannan järvipolygoneista: Näsijärvi, siihen 300 m:n sisällä liittyvät "
                           "vesialueet (Muroleen kanavan toinen puoli) ja 3 km maapuskuri, rajattuna ylös ja sivuille bboxiin."},
        "koordinaatistot": {"kasittely": "EPSG:3067", "julkaisu": "EPSG:3857 (tiilet), EPSG:4326 (vektorikohteet)",
                            "korkeusjarjestelma": "N2000 (EPSG:3900)"},
        "tiedostot": tiedostot,
        "tiilet": {
            "vektori": {"tiedosto": "nasijarvi.pmtiles", "muoto": "mvt", "minzoom": VEKTORI_MINZ, "maxzoom": VEKTORI_MAXZ,
                        "ruudun_koko": 512, "kerrokset": kerrokset},
            "maasto": {"tiedosto": "maasto.pmtiles", "muoto": "png", "koodaus": "mapbox-terrain-rgb",
                       "kaava": "korkeus_m = -10000 + (R*65536 + G*256 + B) * 0,1", "ei_dataa": "RGB (0,0,0)",
                       "tiilen_koko_px": TERRAIN_TILE_PX, "minzoom": TERRAIN_MINZ, "maxzoom": TERRAIN_MAXZ,
                       "lahde_z8_13": "Korkeusmalli 10 m", "lahde_z14": "Korkeusmalli 2 m rantavyöhykkeellä (500 m), muualla 10 m",
                       "kvantisointi_m": ms.get("kvantti", TERRAIN_KVANTTI),
                       "puuttuva_tiili": "Tiili puuttuu, jos se on kokonaan vesialuetta. Järven pinta on noin 95,5 m (N2000).",
                       "järven_pinta_m": 95.5},
            "puusto": {"tiedosto": "puusto.pmtiles", "muoto": "png", "koodaus": "RGBA: pituus_dm = R*256 + G, latvuspeitto_% = B, A=0 ei metsämaata",
                       "tiilen_koko_px": TERRAIN_TILE_PX, "minzoom": PUUSTO_MINZ, "maxzoom": PUUSTO_MAXZ,
                       "lahde": "Luke MVMI 2023, keskipituus (dm) ja latvuspeitto (%), 16 m"},
        },
        "lahteet": lahteet,
        "kayttorajoitukset": {
            "navigointi": "Aineisto ei ole tarkoitettu navigointikäyttöön eikä täytä asianmukaisen merikartan vaatimuksia.",
            "traficom_syvyys": "Traficomin syvyysaineistoa saa käyttää vain muuhun kuin navigointikäyttöön ja ei-kaupallisesti. "
                                "Lähdemerkintä tiedonsiirron ajankohtineen on pidettävä näkyvissä.",
            "dvv_osoitteet": "Aineisto on poiminta 3.2.2025 eikä se päivity, koska DVV lopetti avoimen jakelun 14.3.2025."},
        "lahdemerkinta_yhteensa": " ".join(l["lahdemerkinta"] for l in lahteet),
        "kerrosmaarat": maarat,
        "lataustiedot": {k: v for k, v in loki_.items() if k in ("mtk", "kiinteisto", "tienimet", "dvv", "dem10", "dem2",
                                                                    "luke_keskipituus", "luke_latvuspeitto", "vayla", "traficom")},
    }
    kirjoita_json(ULOS / "aineisto.json", kuvaus)
    loki("aineisto.json kirjoitettu")
    return kuvaus


KENTAT = {
    "rakennus": {"kaytto": "käyttötarkoitus (luokkakoodista)", "krs": "kerrosluokka: 1-2 tai 3+ (puuttuu, jos ei tiedossa)",
                 "z": "maanpinnan korkeus N2000 (m)", "luokka": "MML:n kohdeluokka"},
    "kiinteistoraja": {"laji": "rajalaji (MML)"},
    "kiinteistotunnus": {"tunnus": "kiinteistötunnus muodossa kunta-kylä-tila-rno", "kunta": "kuntakoodi"},
    "maastokuvio": {"luokka": "maastokuvion luokka", "koodi": "MML:n kohdeluokka"},
    "tie": {"luokka": "MML:n tieluokka", "nimi": "tien nimi", "tienumero": "tienumero", "paallyste": "päällyste (MML)",
            "taso": "tasosijainti"},
    "osoite": {"osoite": "katuosoite", "postinumero": "postinumero", "tyyppi": "1 = asuin- tai toimitilarakennus, 2 = tuotanto- tai muu rakennus"},
    "turvalaite": {"numero": "turvalaitenumero", "nimi": "nimi", "nimi_sv": "nimi ruotsiksi", "tyyppi": "turvalaitetyyppi",
                   "alityyppi": "alityyppi", "navigointilaji": "navigointilajikoodi", "valaistu": "K = valaistu, E = ei",
                   "valotunnus": "kansainvälinen valotunnus (viralvalotunnuse), esim. VQ (3) 5 s",
                   "valotunnus_fi": "suomalainen valotunnus (virallvalotunnus), esim. NPv-ESx (3) 5 s",
                   "valon_laji": "valon laji", "valon_korkeus_vedesta": "valon korkeus vedestä (m)",
                   "valon_nakyvyys": "optinen kanto (merimailia)",
                   "sektorit": "JSON-taulukko: [{alku, loppu, vari}], asteina, väri lähdeaineiston koodina: v = valkoinen, p = punainen, vi = vihreä, k = keltainen (tulkinta on oletus eikä sitä ole varmistettu lähdeaineiston koodiluettelosta)",
                   "vayla": "väylän nimi", "omistaja": "omistaja", "muu_vaylanpitaja": "1 = muun väylänpitäjän turvalaite", "tila": "toimintatilakoodi"},
    "navigointilinja": {"tyyppi": "tyyppi", "mitoitussyvays": "mitoitussyvyys (m)", "haraussyvyys": "haraussyvyys (m)",
                        "suunta": "suunta", "tosisuunta": "todellinen suunta (astetta)", "pituus": "pituus (m)",
                        "vaylan_nimi": "väylä", "jnro": "väylän numero"},
    "vaylaalue": {"tyyppi": "tyyppi", "liikenteentyyppi": "liikenteen tyyppi", "mitoitussyvays": "mitoitussyvyys (m)",
                  "haraussyvyys": "haraussyvyys (m)", "liikennointistatus": "liikennöintistatus", "vaylan_nimi": "väylä"},
    "vayla": {"nimi": "väylän nimi", "luokka": "väyläluokka", "laji": "väylälaji", "mitoitussyvays": "mitoitussyvyys (m)", "valaistus": "valaistus"},
    "taululinja": {"suunta": "suunta", "tyyppi": "tyyppi", "vaylan_nimi": "väylä"},
    "vesiliikennemerkki": {"nimi": "nimi", "lajityyppi": "lajityyppi", "tyyppi": "tyyppi", "rajoitusarvo": "rajoitusarvo",
                           "lisakilpi1": "lisäkilpi 1", "lisakilpi2": "lisäkilpi 2", "vaikutusalue": "vaikutusalue"},
    "nopeusrajoitus": {"tyyppi": "rajoitustyyppi", "suuruus": "rajoituksen suuruus", "poikkeus": "poikkeus", "lisatieto": "lisätieto",
                       "paatostila": "päätöstila", "alku": "alkupäivämäärä", "loppu": "loppupäivämäärä"},
    "sulkukanava": {"nimi": "nimi", "vesisto": "vesistö", "mista": "mistä", "mihin": "mihin", "sulkuleveys": "sulun leveys (m)",
                    "sulkuleveyspituus": "sulun pituus (m)", "putouskorkeus1": "putouskorkeus 1 (m)", "putouskorkeus2": "putouskorkeus 2 (m)",
                    "alusleveys": "alusten suurin leveys (m)", "aluspituus": "alusten suurin pituus (m)", "alussyvyys": "alusten suurin syväys (m)",
                    "aluskorkeus": "alusten suurin korkeus (m)", "kayttoselite": "käyttöselite"},
    "rantaviiva": {"luokka": "jarvi"},
    "syvyysalue": {"alin": "alin syvyys (m, DRVAL1)", "ylin": "ylin syvyys (m, DRVAL2)", "mitattu": "mittauspäivä (SORDAT)"},
    "syvyyskayra": {"syvyys": "syvyys (m)", "mitattu": "mittauspäivä"},
    "syvyyspiste": {"syvyys": "syvyys (m)", "taso": "vertaustaso", "mitattu": "mittauspäivä"},
    "vesieste": {"laji": "vesikivi (vedenalainen, pinnassa, pinnan yläpuolella), vesikivikko, matalikko, aallonmurtaja, laituri"},
}


def kopioi_sivusto():
    ULOS.mkdir(exist_ok=True)
    for nimi in ("testi.html",):
        if (JUURI / nimi).exists():
            shutil.copyfile(JUURI / nimi, ULOS / nimi)
    lib = JUURI / "lib"
    if lib.exists():
        shutil.copytree(lib, ULOS / "lib", dirs_exist_ok=True)


OSAT = {"vektori": rakenna_vektori, "maasto": rakenna_maasto, "puusto": rakenna_puusto,
        "kuvaus": lambda: (kopioi_sivusto(), rakenna_kuvaus())}


def main(argv):
    nimet = argv or list(OSAT)
    ULOS.mkdir(exist_ok=True)
    for n in nimet:
        loki("=== osa", n)
        t = time.time()
        try:
            OSAT[n]()
            loki("osa %s valmis %.0f s" % (n, time.time() - t))
        except Exception:  # noqa: BLE001
            traceback.print_exc()
            loki("VIRHE osassa", n)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
