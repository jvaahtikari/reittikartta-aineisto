#!/usr/bin/python3
"""Kirjoittaa ajon yhteenvedon Markdown-tiedostoon (oletus ajoloki/viimeisin.md).

GitHub Actions työntää tiedoston haaraan `ajoloki`, josta se luetaan rajapinnalla
(gh api repos/<repo>/contents/ajoloki/viimeisin.md?ref=ajoloki), koska työnkulun lokit eivät ole kaikkien ulottuvilla.

Yhteenveto kokoaa: laserosan lähteen (vuosi, ruudut, pisteet, tiheys, 2008-varalla olleet ruudut), viisi tarkistuskohdetta vanhalla ja uudella korkeudella,
maaston korkeustarkistuksen, puuston lehtipuuosuuden, tarkista.py:n tuloksen, tiedostokoot ja lokien lopun.
API-avainta ei kirjoiteta: kaikki teksti puhdistetaan ympäristömuuttujan MML_API_KEY arvosta ja sen Basic-muodosta.

Ajo:  python3 ajoloki.py [kohde.md]     (ympäristö: GITHUB_RUN_ID, GITHUB_SHA, AJO_ALKU = ajon alkuhetki sekunteina)
"""
import base64
import json
import os
import sys
import time
from pathlib import Path

JUURI = Path(__file__).resolve().parent
TYO = JUURI / "tyo"
LTYO = TYO / "laser"
ULOS = JUURI / "ulos"

SALAISET = []


def alusta_salaiset():
    avain = os.environ.get("MML_API_KEY", "").strip()
    if len(avain) >= 8:
        SALAISET.extend([avain, base64.b64encode((avain + ":").encode()).decode(), base64.b64encode(avain.encode()).decode()])


def siivoa(teksti):
    teksti = str(teksti)
    for s in SALAISET:
        teksti = teksti.replace(s, "***")
    # api-key-parametri URL-osoitteissa
    import re
    return re.sub(r"(api-key=)[^&\s\"')]+", r"\1***", teksti)


def lue(polku, oletus=None):
    try:
        return json.loads(Path(polku).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return oletus


def luku(x, d=1, yks=""):
    if x is None:
        return "-"
    try:
        return ("%." + str(d) + "f") % float(x) + yks
    except (TypeError, ValueError):
        return str(x)


def pilkku(s):
    """Desimaalipilkku lukuihin (vain teksti, jossa on pisteellä kirjoitettuja desimaaleja)."""
    return s


def lopun_rivit(polku, n=40):
    try:
        rivit = Path(polku).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    return rivit[-n:]


def taulukko(otsikot, rivit):
    out = ["| " + " | ".join(otsikot) + " |", "|" + "|".join("---" for _ in otsikot) + "|"]
    for r in rivit:
        out.append("| " + " | ".join(str(c).replace("|", "/").replace("\n", " ") for c in r) + " |")
    return out


def laserosa():
    t = []
    loki = lue(LTYO / "loki.json", {})
    ruudut = lue(LTYO / "ruudut.json", {}) or {}
    rs = ruudut.get("ruudut", [])
    mh = loki.get("mml_haku") or (ruudut.get("yhteenveto") or {}).get("mml_haku") or {}
    pys = loki.get("pisteet_yhteensa") or {}
    pt = loki.get("pisteet") or {}
    t.append("## 1. Laserosa")
    if not rs:
        t.append("Laserosa ei tuottanut ruutuluetteloa (ks. lokin loppu).")
        v = loki.get("virhe")
        if v:
            t.append("Virhe: vaihe %s, %s" % (v.get("vaihe"), v.get("viesti")))
        return t
    mml = [r for r in rs if r.get("lahde") == "mml_tiedostopalvelu"]
    vara = [r for r in rs if r.get("lahde") != "mml_tiedostopalvelu"]
    vuodet = sorted({r["vuosi"] for r in mml if r.get("vuosi")})
    t.append("- Avain asetettu: **%s**. Tila: %s. Aineisto: `%s`, prosessi `%s`." % ("kyllä" if mh.get("avain_asetettu") else "ei", mh.get("tila"), mh.get("aineisto"), mh.get("prosessi")))
    t.append("- **Käytetty MML:n uutta keilausta: %s.** Keilausvuosi: %s." % ("kyllä" if mml else "ei", ", ".join(str(v) for v in vuodet) or "-"))
    t.append("- Ruutuja yhteensä %d, joista MML:n uutta keilausta %d ja Paitulin 2008-aineistoa (varalla) %d%s." % (
        len(rs), len(mml), len(vara), (": " + ", ".join(r["ruutu"] for r in vara)) if vara else ""))
    t.append("- Pisteitä (vyöhykkeen laatikossa, suodatuksen jälkeen) %s kpl, tiheys %s p/m² (kaikki) ja %s p/m² (vain maa-alue). Pisteitä luettu yhteensä %s kpl." % (
        pys.get("pisteita_alueella"), luku(pys.get("tiheys_p_m2"), 3), luku(pys.get("tiheys_maalla_p_m2"), 3), pys.get("luettu")))
    t.append("- Lataus tällä ajolla: %s Mt, välimuistista %s ruutua, MML-työ `%s` (%s s, %s pyyntöä)." % (
        luku((mh.get("ladattu_nyt_tavua") or 0) / 1e6, 1), mh.get("valimuistista_ruutuja", "-"), str(mh.get("tyon_tunnus"))[:8], mh.get("sekuntia"), mh.get("pyyntoja")))
    if mh.get("virhe"):
        t.append("- **MML-haun virhe:** %s" % mh["virhe"])
    if mh.get("tyon_viesti"):
        t.append("- MML-työn viesti: %s" % mh["tyon_viesti"])
    t.append("")
    rivit = []
    for r in rs:
        p = pt.get(r["ruutu"], {})
        md = r.get("metatiedot") or {}
        rivit.append([r["ruutu"], "MML" if r.get("lahde") == "mml_tiedostopalvelu" else "2008 (varalla)", r.get("vuosi"), luku((r.get("koko_tavua") or 0) / 1e6, 1),
                      md.get("Keilauspaivamaara") or "-", md.get("Pistetiheys") or "-", p.get("luettu", "-"), p.get("pisteita_alueella", "-"),
                      luku(p.get("tiheys_p_m2"), 3), luku(p.get("tiheys_maalla_p_m2"), 3), json.dumps(p.get("luokat_ennen", {}), ensure_ascii=False)])
    t += taulukko(["Ruutu", "Lähde", "Vuosi", "Mt", "Keilauspäivä", "Pistetiheys (MML)", "Pisteitä luettu", "Alueella", "p/m² kaikki", "p/m² maa", "Luokat (kpl)"], rivit)
    t.append("")
    sek = loki.get("vaiheet_sekuntia") or {}
    if sek:
        t.append("Vaiheiden kestot (s): " + ", ".join("%s %s" % (k, v) for k, v in sek.items()))
    v = loki.get("virhe")
    if v:
        t.append("")
        t.append("**Virhe laserosassa:** vaihe %s, %s" % (v.get("vaihe"), v.get("viesti")))
    return t


def tarkistuskohteet(tark):
    t = ["## 2. Tarkistuskohteet (vanha 2008 ja uusi korkeus)"]
    k = (tark or {}).get("8_tarkistuskohteet")
    if not k:
        t.append("Tarkistuskohteita ei saatu (laserosa ei ehtinyt tarkistusvaiheeseen).")
        return t
    t.append("Nykyinen keilaus: %s. Vertailu: %s." % (k.get("nykyinen_keilaus"), k.get("vertailukeilaus")))
    kh = k.get("kohteet", {})
    rivit = []
    n = kh.get("nasinneula")
    if n:
        rivit.append(["Näsinneula (korkein havaittu piste, m maanpinnasta)", luku(n.get("vanha_h_maasta_m")), luku(n.get("uusi_h_maasta_m")),
                      "tavoite 168 ± 3 m (Wikipedia), mastopisteitä %s, huippu N2000 %s m" % (n.get("mastopisteita"), luku(n.get("uusi_z_n2000_m"))), n.get("hyvaksytty", n.get("virhe"))])
    n = kh.get("tampellan_piippu")
    if n:
        rivit.append(["Tampellan piippu (m maanpinnasta)", luku(n.get("vanha_h_maasta_m")), luku(n.get("uusi_h_maasta_m")), "tavoite noin 100 m", n.get("hyvaksytty", n.get("virhe"))])
    n = kh.get("voimalaitoksen_paarakennus")
    if n:
        rivit.append(["Voimalaitoksen päärakennus (kattilarakennus, p95 / max m)", "%s / %s" % (luku(n.get("vanha_h_p95_m")), luku(n.get("vanha_h_max_m"))),
                      "%s / %s" % (luku(n.get("uusi_h_p95_m")), luku(n.get("uusi_h_max_m"))), "ala %s m²" % luku(n.get("ala_m2"), 0), n.get("hyvaksytty", n.get("virhe"))])
    n = kh.get("ranta_tampellan_talo")
    if n:
        rivit.append(["Ranta-Tampellan talo fid %s (h_p90 / h_max m)" % n.get("fid"), "%s / %s" % (luku(n.get("vanha_h_p90_m"), 2), luku(n.get("vanha_h_max_m"), 2)),
                      "%s / %s" % (luku(n.get("uusi_h_p90_m"), 2), luku(n.get("uusi_h_max_m"), 2)),
                      "pisteitä %s, ala %s m², korkeus saatu: %s" % (n.get("pisteita"), luku(n.get("ala_m2"), 0), n.get("korkeus_saatu", n.get("virhe"))), n.get("hyvaksytty", n.get("virhe"))])
    n = kh.get("pispalanharju_maanpinta")
    if n:
        rivit.append(["Pispalanharjun korkein maanpinta (luokan 2 piste, z N2000 m)", luku(n.get("vanha_maanpinta_max_z_n2000_m")), luku(n.get("uusi_maanpinta_max_z_n2000_m")),
                      "DEM 2 m:n maksimi %s m, maapisteitä %s" % (luku(n.get("dem_2m_max_z_n2000_m")), n.get("maapisteita_laatikossa")), n.get("hyvaksytty", n.get("virhe"))])
    t += taulukko(["Kohde", "Vanha (2008)", "Uusi", "Huomio", "Hyväksytty"], rivit)
    for nimi, v in kh.items():
        if "virhe" in v:
            t.append("- Virhe kohteessa %s: %s" % (nimi, v["virhe"]))
    return t


def maamerkit():
    t = ["## 2b. Maamerkit (diagnostiikka)"]
    d = lue(LTYO / "maamerkit.json")
    if not d:
        t.append("maamerkit.json puuttuu.")
        return t
    kap = d.get("korkeat_kapeat_rakenteet_vyohykkeella") or []
    t.append("Korkeat kapeat rakenteet vyöhykkeellä (%d kpl, 12 korkeinta): E / N / korkeus maasta m / huippu N2000 m / pisteitä yläosassa" % len(kap))
    t.append("")
    t += taulukko(["E", "N", "h maasta", "z huippu", "pisteitä ylhäällä", "ylaosan leveys"],
                  [[luku(k.get("e"), 0), luku(k.get("n"), 0), luku(k.get("h_maasta")), luku(k.get("z_huippu")), k.get("pisteita_ylaosassa"), luku(k.get("ylaosan_leveys_m"))] for k in kap[:12]])
    for m in d.get("maamerkit", []):
        if m.get("virhe"):
            t.append("- Maamerkin %s mittaus epäonnistui: %s" % (m.get("tunnus_puuttuu"), m["virhe"]))
        if m.get("tunnus") == "naistenlahden_voimalaitos":
            t.append("- Naistenlahden voimalaitos: piippuja %d (korkeudet m: %s), kuljetinsilta %s" % (
                len(m.get("piiput", [])), ", ".join(luku(p.get("korkeus_maasta_m")) for p in m.get("piiput", [])),
                "tunnistettu, pituus %s m" % luku((m.get("kuljetinsilta") or {}).get("pituus_m")) if m.get("kuljetinsilta") else "ei tunnistettu"))
        if m.get("tunnus") == "naistenlahden_voimalaitos" and m.get("diagnostiikka"):
            dg = m["diagnostiikka"]
            t.append("- Voimalaitoksen diagnostiikka: hallien alat m² %s, kuljetinehdokkaat (nDSM yli 10 m, ilman suuria hallirakennuksia) %s" % (
                dg.get("hallien_ala_m2"), json.dumps(dg.get("kuljetinehdokkaita_nDSM_yli_10_m"), ensure_ascii=False)))
        if m.get("tunnus") == "nasinneula":
            mi = m.get("mitat") or {}
            t.append("- Näsinneula: korkein havaittu %s m maasta, lautasen halkaisija %s m, varren halkaisija %s m" % (
                luku((mi.get("korkein_havaittu_piste") or {}).get("h_maasta_m")), luku((mi.get("lautanen") or {}).get("halkaisija_m")), luku((mi.get("varsi") or {}).get("halkaisija_m"))))
    return t


def aluevertailut(tark):
    t = ["## 2c. Rakennuskohtaiset vertailut (2008 ja uusi)"]
    k = (tark or {}).get("8_tarkistuskohteet") or {}
    for avain, otsikko in (("ranta_tampella", "Ranta-Tampellan kerrostalot"), ("naistenlahden_alue", "Naistenlahden voimalaitoksen alue (sisältää Naistenlahti 3:n)")):
        v = k.get(avain)
        if not v or v.get("virhe"):
            t.append("%s: ei tietoa (%s)" % (otsikko, (v or {}).get("virhe", "puuttuu")))
            continue
        t.append("**%s.** %s Keilauksen jälkeen rakennetuista (2008: ei näkynyt) korkeuden sai %s kpl, ilman korkeutta nyt %s kpl." % (
            otsikko, v.get("selite") or "", v.get("jotka_eivat_nakyneet_2008_ja_saivat_korkeuden"), v.get("ilman_korkeutta_nyt")))
        t.append("")
        t += taulukko(["fid", "ala m²", "käyttö", "h_p90 2008", "h_max 2008", "2008 ei näkynyt", "h_p90 uusi", "h_max uusi", "pisteitä", "uusi ei näkynyt"],
                      [[r["fid"], luku(r.get("ala_m2"), 0), r.get("kaytto"), luku(r.get("vanha_h_p90_m"), 1), luku(r.get("vanha_h_max_m"), 1), r.get("vanha_ei_keilattu"),
                        luku(r.get("uusi_h_p90_m"), 1), luku(r.get("uusi_h_max_m"), 1), r.get("uusi_pisteita"), r.get("uusi_ei_keilattu")] for r in v.get("rakennukset", [])])
        t.append("")
    return t


def rakennukset(tark):
    t = ["## 3. Rakennuskorkeudet"]
    r = (tark or {}).get("4_rakennukset")
    if not r:
        t.append("Ei tietoa.")
        return t
    rt = r.get("ranta_tampella_kerrostalot", {})
    ek = r.get("ei_keilattu", {})
    t.append("- Rakennuksia %s, korkeus saatu %s (%s %%). Hyväksytty (80 %%): %s." % (r.get("rakennuksia"), r.get("korkeus_saatu"), r.get("korkeus_saatu_pros"), r.get("hyvaksytty_osuus")))
    t.append("- Ranta-Tampellan rajaus: %s rakennusta, joilla korkeus %s, h_p90 15-30 m: %s kpl, persentiilit %s, epävarmoja (keilauksen jälkeen rakennettuja) %s." % (
        rt.get("rakennuksia"), rt.get("joilla_korkeus"), rt.get("h_p90_15_30_m_lkm"), rt.get("h_p90_persentiilit_m"), rt.get("epavarma_keilauksen_jalkeen_rakennettu")))
    t.append("- Rakennuksia, joita ei ollut keilaushetkellä (pisteitä alle 5 tai h_max alle 2 m): %s (%s %%), joista alaltaan vähintään 150 m²: %s. Keilausvuodet: %s." % (
        ek.get("rakennuksia"), ek.get("osuus_pros"), ek.get("joista_ala_vahintaan_150_m2"), ek.get("keilausvuodet")))
    for nimi in ("vertailu_kerrostalot", "vertailu_pientalot"):
        v = r.get(nimi) or {}
        t.append("- %s: otos %s, välillä %s m: %s %%, persentiilit %s." % (nimi, v.get("otos_n"), v.get("vali_m"), v.get("osuus_pros"), v.get("h_p90_persentiilit_m")))
    t.append("- Mediaanit vaadituissa väleissä: %s." % r.get("mediaanit_vaadituissa_valeissa"))
    return t


def muut_tarkistukset(tark):
    t = ["## 4. Muut laserosan tarkistukset (vaihe 1b -kriteerit uudella aineistolla)"]
    if not tark:
        t.append("Ei tietoa.")
        return t
    rivit = []
    for k in sorted(tark):
        v = tark[k]
        if not isinstance(v, dict):
            continue
        rivit.append([k, v.get("hyvaksytty", v.get("hyvaksytty_osuus", "-")), v.get("virhe", "")])
    t += taulukko(["Tarkistus", "Hyväksytty", "Virhe"], rivit)
    a = tark.get("5_avoin_maa") or {}
    if a:
        t.append("")
        t.append("Avoin maa, pintamalli vastaan DEM 2 m: %s" % json.dumps({k: a.get(k) for k in ("ruutuja", "otos_n", "ero_abs_p95_m", "osuus_alle_1_m_pros", "ero_mediaani_m") if k in a}, ensure_ascii=False))
    k6 = tark.get("6_koko") or {}
    if k6:
        t.append("")
        t.append("Pintamallin koko: `pinta.pmtiles` %s Mt, raskain puhelinnäkymä z15 %s Mt." % (k6.get("pinta_pmtiles_mt"), k6.get("z15_puhelinnakyma_pahin_mt")))
    return t


def maasto():
    t = ["## 5. Maaston korkeustarkistus (maasto.pmtiles vastaan MML:n 2 m korkeusmalli)"]
    m = lue(TYO / "maastotarkistus.json")
    if not m:
        t.append("Tarkistusta ei tehty tai se epäonnistui (ks. lokin loppu).")
        return t
    rivit = []
    for p in m.get("pisteet", []):
        rivit.append([p.get("nimi"), "%s / %s" % (luku(p.get("e"), 0), luku(p.get("n"), 0)), luku(p.get("dem2_bilin_m"), 2), luku(p.get("dem10_bilin_m"), 2),
                      luku(((p.get("tiili") or {}).get("14") or {}).get("bilin_m"), 2), luku(p.get("ero_z14_dem2_m"), 2), luku(p.get("ero_z14_dem10_m"), 2)])
    t += taulukko(["Piste", "E / N", "DEM 2 m", "DEM 10 m", "Tiili z14", "Ero DEM 2 m", "Ero DEM 10 m"], rivit)
    kd = m.get("koodaus", {})
    t.append("")
    t.append("- Koodaus: %s. Offset %s m, kerroin %s m, metadatan kvantisointi %s m, kaikki tilkan arvot kvantin monikertoja: %s." % (
        kd.get("kaava"), kd.get("offset_m"), kd.get("kerroin_m"), kd.get("metadata_kvantisointi_m"), kd.get("kaikki_arvot_kvantin_monikertoja")))
    y = m.get("yhteenveto", {})
    t.append("- Suurin itseisero z14 / DEM 2 m: %s m, z14 / DEM 10 m: %s m, kaikki viisi alle 1 m: %s." % (y.get("suurin_abs_ero_z14_dem2_m"), y.get("suurin_abs_ero_z14_dem10_m"), y.get("kaikki_alle_1_m_dem2")))
    for nimi, o in (m.get("otokset") or {}).items():
        t.append("- Otos %s: %s tiiltä, mediaaniero %s m, p99 %s m, suurin %s m, alle 1 m: %s %%." % (
            nimi, o.get("tiilia"), o.get("ero_mediaani_m"), o.get("abs_ero_p99_m"), o.get("abs_ero_max_m"), o.get("osuus_alle_1_m_pros")))
        if o.get("rantavyohyke") or o.get("vyohykkeen_ulkopuolella"):
            t.append("  - rantavyöhyke: %s, vyöhykkeen ulkopuolella: %s" % (json.dumps(o.get("rantavyohyke"), ensure_ascii=False)[:300], json.dumps(o.get("vyohykkeen_ulkopuolella"), ensure_ascii=False)[:300]))
    return t


def puusto():
    t = ["## 6. Puusto ja lehtipuuosuus"]
    s = lue(TYO / "puusto_tilasto.json")
    m = lue(TYO / "maastotarkistus.json") or {}
    if s:
        t.append("- `puusto.pmtiles`: %s tiiltä, %s Mt. Lehtipuuosuus alfakanavassa: %s." % (s.get("tiilia_pmtiles"), luku((s.get("tavua") or 0) / 1e6, 1), s.get("lehtipuuosuus_alfassa")))
        lp = s.get("lehtipuuosuus") or {}
        t.append("- Lehtipuuosuus (metsäruudut %s): p10 / p50 / p90 %s %%, tilavuuspainotettu keskiarvo %s %%, yli 50 %% ruutujen osuus %s %%." % (
            lp.get("metsaruutuja"), lp.get("osuus_prosenttipisteet_p10_p50_p90"), lp.get("tilavuuspainotettu_keskiarvo_pros"), lp.get("yli_50_pros_ruutujen_osuus_pros")))
    p = m.get("puusto")
    if p:
        t.append("- Pispalanharjun pohjoisrinteen tarkistus tiilistä: " + siivoa(json.dumps(p, ensure_ascii=False)[:1500]))
    if not s and not p:
        t.append("Ei tietoa.")
    return t


def tarkistus_py():
    t = ["## 7. tarkista.py (paketin tarkistus)"]
    a = lue(ULOS / "tarkistus.json")
    if not a:
        t.append("`ulos/tarkistus.json` puuttuu.")
        return t
    rivit = []
    for k, v in sorted((a.get("tarkistukset") or {}).items()):
        rivit.append([k, v.get("ok") if isinstance(v, dict) else v])
    t += taulukko(["Tarkistus", "OK"], rivit)
    t.append("")
    t.append("Epäonnistuneet tarkistukset: %s" % (a.get("epaonnistuneet") or "ei yhtään"))
    for h in a.get("huomiot", []):
        t.append("- " + h)
    return t


def koot():
    t = ["## 8. Tiedostokoot (ulos/)"]
    rivit = []
    if ULOS.is_dir():
        kaikki = sorted([p for p in ULOS.iterdir() if p.is_file()], key=lambda p: -p.stat().st_size)
        for p in kaikki:
            rivit.append([p.name, luku(p.stat().st_size / 1e6, 2)])
        kok = sum(p.stat().st_size for p in ULOS.rglob("*") if p.is_file())
        rivit.append(["**yhteensä (rekursiivisesti)**", luku(kok / 1e6, 1)])
    t += taulukko(["Tiedosto", "Mt"], rivit)
    return t


def lokit():
    t = ["## 9. Lokien loppu"]
    for nimi in ("ajaa.log", "laser.log", "tarkista_laserin_jalkeen.log", "maastotarkistus.log"):
        r = lopun_rivit(TYO / nimi, 45 if nimi == "laser.log" else 20)
        if r:
            t.append("")
            t.append("`%s` (viimeiset %d riviä):" % (nimi, len(r)))
            t.append("```")
            t += [x[:300] for x in r]
            t.append("```")
    return t


def main(argv):
    alusta_salaiset()
    kohde = Path(argv[0]) if argv else JUURI / "ajoloki" / "viimeisin.md"
    kohde.parent.mkdir(parents=True, exist_ok=True)
    nyt = time.time()
    alku = float(os.environ.get("AJO_ALKU", "0") or 0)
    tark = lue(LTYO / "tarkistus_1b.json", {})
    rivit = ["# Ajon yhteenveto", "",
             "- Ajo: %s, commit %s, haara %s." % (os.environ.get("GITHUB_RUN_ID", "paikallinen"), os.environ.get("GITHUB_SHA", "-")[:10], os.environ.get("GITHUB_REF_NAME", "-")),
             "- Kirjoitettu: %s UTC." % time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(nyt)),
             "- Kesto tähän asti: %s s." % (luku(nyt - alku, 0) if alku else "-"),
             "- Työnkulun tila ennen tätä askelta: %s." % os.environ.get("AJO_TILA", "-"), ""]
    for osa in (laserosa, lambda: tarkistuskohteet(tark), maamerkit, lambda: aluevertailut(tark), lambda: rakennukset(tark), lambda: muut_tarkistukset(tark), maasto, puusto, tarkistus_py, koot, lokit):
        try:
            rivit += osa() + [""]
        except Exception as e:  # noqa: BLE001
            rivit += ["(osan kirjoitus epäonnistui: %s)" % repr(e)[:200], ""]
    teksti = siivoa("\n".join(rivit)) + "\n"
    kohde.write_text(teksti, encoding="utf-8")
    print("Kirjoitettu %s (%d tavua)" % (kohde, len(teksti.encode())))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
