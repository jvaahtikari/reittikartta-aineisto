#!/usr/bin/env python3
"""Koeajo MML:n tiedostopalvelun OGC API Processes -rajapintaa vastaan GitHub Actionsissa (avain ympäristömuuttujassa MML_API_KEY).

Kirjoittaa yhteenvedon tiedostoon probe_ulos/probe.md ja probe_ulos/probe.json. Avainta ei kirjoiteta mihinkään.
"""
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mml_asiakas import LASER_PROSESSI, MmlAsiakas, MmlVirhe  # noqa: E402

ULOS = Path("probe_ulos")
TYO = Path("probe_tyo")
LEHDET = ["M4212E1", "M4212E2", "M4212E3", "M4212E4", "M4212G1", "M4212G2", "M4212G3", "M4212G4", "M4214A1", "M4214A2"]

rivit = []
tulos = {"alku": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
asiakas = None


def kirjaa(*a):
    s = " ".join(str(x) for x in a)
    if asiakas is not None:
        s = asiakas.siivoa_teksti(s)
    print(time.strftime("%H:%M:%S"), s, flush=True)
    rivit.append(s)


def laz_tiedot(polku):
    import datetime
    import laspy
    import numpy as np
    las = laspy.read(str(polku))
    h = las.header
    luokat = {int(k): int(v) for k, v in zip(*np.unique(np.asarray(las.classification), return_counts=True))}
    d = {"versio": "%d.%d" % (h.version.major, h.version.minor), "pistemuoto": int(h.point_format.id), "pisteita": int(h.point_count),
         "luotu": str(h.creation_date), "luokat": luokat, "x": [float(h.mins[0]), float(h.maxs[0])], "y": [float(h.mins[1]), float(h.maxs[1])],
         "z": [float(h.mins[2]), float(h.maxs[2])], "ohjelmisto": str(h.generating_software).strip("\x00"), "jarjestelma": str(h.system_identifier).strip("\x00"),
         "vlr": [str(v.user_id)[:30] + "/" + str(v.record_id) for v in h.vlrs][:8]}
    try:
        d["global_encoding"] = int(h.global_encoding.value)
    except Exception:  # noqa: BLE001
        d["global_encoding"] = str(h.global_encoding)
    dims = list(las.point_format.dimension_names)
    d["kentat"] = dims
    for nimi in ("return_number", "number_of_returns"):
        if nimi in dims:
            d[nimi + "_max"] = int(np.asarray(las[nimi]).max())
    if "gps_time" in dims:
        t = np.asarray(las.gps_time)
        d["gps_time"] = [float(t.min()), float(t.max()), float(np.median(t))]
        for nimi, arvo in (("min", float(t.min())), ("med", float(np.median(t))), ("max", float(t.max()))):
            if arvo > 1e8:
                sek = arvo + (1e9 if arvo < 5e8 else 0.0)
                d["gps_paiva_" + nimi] = (datetime.datetime(1980, 1, 6) + datetime.timedelta(seconds=sek - 18)).strftime("%Y-%m-%d")
    pinta = max(1.0, (d["x"][1] - d["x"][0]) * (d["y"][1] - d["y"][0]))
    d["tiheys_p_m2_laatikossa"] = round(d["pisteita"] / pinta, 3)
    return d


def main():
    global asiakas
    avain = os.environ.get("MML_API_KEY", "")
    asiakas = MmlAsiakas(avain, loki=kirjaa)
    tulos["avain_asetettu"] = bool(avain)
    tulos["avaimen_pituus_ok"] = len(avain) > 10
    try:
        ids = asiakas.yhteys()
    except MmlVirhe as e:
        kirjaa("YHTEYS EI TOIMI:", e)
        tulos["yhteys"] = str(e)
        return 1
    tulos["tunnistus"] = asiakas.tunnistus
    tulos["prosesseja"] = len(ids)
    tulos["laser_prosessi_listassa"] = LASER_PROSESSI in ids
    kirjaa("laser-prosessi listassa:", LASER_PROSESSI in ids, "- laser/korkeusmalli-prosessit:", [i for i in ids if "laser" in i or "korkeusmalli_2m" in i])
    try:
        kuv = asiakas.prosessi()
        tulos["prosessin_kuvaus"] = kuv
        kirjaa("prosessin kuvaus:", json.dumps(kuv, ensure_ascii=False)[:3500])
    except MmlVirhe as e:
        kirjaa("prosessin kuvaus epäonnistui:", e)
    # 1. Yksi lehti
    t0 = time.time()
    try:
        job, vast = asiakas.kaynnista(["M4212E3"])
        kirjaa("käynnistysvastaus:", json.dumps(vast, ensure_ascii=False)[:800])
        lop = asiakas.odota(job, enint_s=900, vali_s=4, kerro=lambda j, s, p, dt: kirjaa("  työ", j[:8], s, p, "%.0f s" % dt))
        kirjaa("lopputila:", json.dumps(lop, ensure_ascii=False)[:800])
        tulos["yksi_lehti"] = {"tila": lop.get("status"), "sekuntia": round(time.time() - t0, 1)}
        if lop.get("status") == "successful":
            tul = asiakas.tulokset(job)
            kirjaa("tulokset:", json.dumps(tul, ensure_ascii=False)[:2500])
            tulos["yksi_lehti"]["tulokset"] = tul
            tied = asiakas.tiedostot(tul)
            kirjaa("tiedostolinkit:", json.dumps(tied, ensure_ascii=False)[:1500])
            for t in tied:
                if t["nimi"].lower().endswith(".laz"):
                    kohde = TYO / t["nimi"]
                    a = time.time()
                    n = asiakas.lataa(t["path"], kohde)
                    kirjaa("ladattu %s: %.1f Mt, %.1f s" % (t["nimi"], n / 1e6, time.time() - a))
                    tiedot = laz_tiedot(kohde)
                    tulos["yksi_lehti"]["laz"] = tiedot
                    kirjaa("LAZ-tiedot:", json.dumps(tiedot, ensure_ascii=False))
    except MmlVirhe as e:
        kirjaa("yhden lehden ajo epäonnistui:", e)
        tulos["yksi_lehti"] = {"virhe": str(e)}
    # 2. Kaikki kymmenen lehteä yhtenä työnä
    t0 = time.time()
    try:
        job, vast = asiakas.kaynnista(LEHDET)
        lop = asiakas.odota(job, enint_s=1200, vali_s=5, kerro=lambda j, s, p, dt: kirjaa("  työ(10)", j[:8], s, p, "%.0f s" % dt))
        tulos["kymmenen_lehtea"] = {"tila": lop.get("status"), "sekuntia": round(time.time() - t0, 1)}
        kirjaa("kymmenen lehden lopputila:", json.dumps(lop, ensure_ascii=False)[:600])
        if lop.get("status") == "successful":
            tul = asiakas.tulokset(job)
            tied = asiakas.tiedostot(tul)
            tulos["kymmenen_lehtea"]["tiedostot"] = [{k: v for k, v in t.items() if k != "path"} for t in tied]
            kirjaa("tiedostoja:", len(tied), [t["nimi"] for t in tied])
            kaikki = []
            for t in tied:
                if not t["nimi"].lower().endswith(".laz"):
                    continue
                kohde = TYO / "kaikki" / t["nimi"]
                a = time.time()
                n = asiakas.lataa(t["path"], kohde)
                tiedot = laz_tiedot(kohde)
                tiedot["lehti"] = t["lehti"]
                tiedot["tavua"] = n
                tiedot["lataus_s"] = round(time.time() - a, 1)
                kaikki.append(tiedot)
                kirjaa("  %s: %.1f Mt, versio %s, pisteita %d, tiheys %.2f, luotu %s, gps-paiva %s..%s, luokat %s" % (
                    t["nimi"], n / 1e6, tiedot["versio"], tiedot["pisteita"], tiedot["tiheys_p_m2_laatikossa"], tiedot["luotu"],
                    tiedot.get("gps_paiva_min"), tiedot.get("gps_paiva_max"), tiedot["luokat"]))
            tulos["kymmenen_lehtea"]["laz"] = kaikki
        else:
            tulos["kymmenen_lehtea"]["vastaus"] = lop
    except MmlVirhe as e:
        kirjaa("kymmenen lehden ajo epäonnistui:", e)
        tulos["kymmenen_lehtea"] = {"virhe": str(e)}
    tulos["pyyntoja"] = asiakas.pyyntoja
    return 0


if __name__ == "__main__":
    ULOS.mkdir(exist_ok=True)
    try:
        rc = main()
    except Exception:  # noqa: BLE001
        import traceback
        kirjaa("POIKKEUS:", traceback.format_exc()[-1500:])
        rc = 1
    tulos["loppu"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    teksti = json.dumps(tulos, ensure_ascii=False, indent=1, default=str)
    if asiakas is not None:
        teksti = asiakas.siivoa_teksti(teksti)
    (ULOS / "probe.json").write_text(teksti, encoding="utf-8")
    (ULOS / "probe.md").write_text("# MML-rajapinnan koeajo\n\n```\n" + "\n".join(rivit) + "\n```\n", encoding="utf-8")
    sys.exit(0)
