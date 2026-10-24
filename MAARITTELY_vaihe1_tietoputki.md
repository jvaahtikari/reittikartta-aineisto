# Määrittely, vaihe 1: Näsijärven aineistopaketti (tietoputki)

Päiväys 24.10.2026. Tekijä: Sonnet-agentti. Tilaaja: Fable. Tausta: "Opetusohjelma/Navigointisimulaattori suunnitelma.md" (kohdat 3–5) ja vaiheen 0 tulokset `AINEISTOT.md` ja `RAPORTTI_vaihe0.md` (erityisesti raportin kohta 8). Lue ne ennen työtä.

## 1. Tavoite

Kerran ajettava ja kuukausittain toistettava tietoputki, joka tuottaa Näsijärven alueesta staattisen aineistopaketin, jota Reittikartan uudet tasot (vaihe 2) ja simulaattori (vaihe 3) lukevat suoraan selaimella. Paketti julkaistaan staattisina tiedostoina, eikä sen käyttö vaadi palvelinta, avainta tai tietokantaa.

Tietoputki rakennetaan tässä työtilassa ja testataan tässä työtilassa. Lopputuotos on hakemisto `opetus/navi/putki/`, jonka sisältö sellaisenaan kopioidaan uuteen GitHub-repoon `reittikartta-aineisto` (tai Reittikartan repon alihakemistoon, tilaaja päättää). Käyttäjä ei tee terminaalityötä, joten GitHub Actions -työnkulun pitää toimia ilman käsin tehtäviä asetuksia, ja ainoa mahdollisesti tarvittava salaisuus on `MML_API_KEY`, jota ei tämän määrittelyn mukaan tarvita lainkaan (ks. kohta 3).

## 2. Alue ja koordinaatistot

Alue: Näsijärvi Tampereen Mustalahdesta Muroleen kanavalle ja Kuru–Ruovesi-suunnan vesille, rantojen ympärillä 3 km maapuskuri. Rajauslaatikko ETRS-TM35FIN (EPSG:3067) noin E 300 000–345 000, N 6 815 000–6 880 000. Agentti tarkentaa rajauksen vesialueen perusteella ensimmäisessä ajossa ja kirjaa lopullisen bboxin `aineisto.json`-tiedostoon. Käsittely EPSG:3067, julkaisu Web Mercator (EPSG:3857) -tiilinä kuten Reittikartassa.

Karttalehdet (UTM-lehtijako, todennettu Paitulin hakemistoista): alue osuu 1:100 000 -lehdille M34 ja N33, mahdollisesti M33 ja N34 reunoilta. Agentti laskee tarvittavat 1:10 000 -lehdet (esimerkiksi `M3411A`) bboxista lehtijaon kaavalla tai Paitulin lehtijakoindeksistä, ja kirjaa luettelon.

## 3. Lähteet, todennettu vaiheessa 0 ja tilaajan tarkastuksessa

Ensisijainen lähde on CSC:n Paituli-peilipalvelin `https://mirrors.nic.funet.fi/index/geodata/`, joka toimii tästä työtilasta ja GitHub Actionsista ilman avainta. Hakemistot ja tiedostomuodot on todennettu 24.10.2026 listaamalla palvelin:

| Aineisto | Polku Paitulissa | Muoto ja huomiot |
|---|---|---|
| Korkeusmalli 2 m | `mml/dem2m/2008_latest/<1:200k>/<1:100k>/<lehti>.tif`, esimerkiksi `M3/M34/M3411A.tif` | GeoTIFF per 1:10 000 -lehti, EPSG:3067, N2000. Myös `dem2m_direct.vrt` koko maalle. Käytetään vain 500 m rantavyöhykkeellä. |
| Korkeusmalli 10 m | `mml/dem10m/2019/M3/M34/M3411.tif` ja vastaavat | GeoTIFF per 1:25 000 -lehti. Koko alueelle. |
| Maastotietokanta | `mml/maastotietokanta/2025/gpkg/MTK-<teema>_25-04-03.gpkg`, teemat kallio, korkeussuhteet, maastokuvionreuna, muut, rakennus, suo, tie, vakavesi, virtavesi | Koko Suomi yhdessä tiedostossa per teema, 2,7–32 Gt. EI ladata kokonaan: luetaan GDAL:n `/vsicurl/`-polulla ja `-spat`-rajauksella (GeoPackagessa on R-puuindeksi), tai vaihtoehtoisesti `shp/`-hakemistosta, jos se on lehdittäin. Agentti kokeilee ensin `/vsicurl/`-rajausta rakennus-teemaan ja mittaa siirtomäärän. Kohdeluokkien koodit ovat `maastotietokanta_kohdemalli_2023-01.xlsx` samassa hakemistossa. Huomio: Z-koordinaatin arvo -999.999 on tihennyspiste, poistetaan. |
| Kiinteistörajat | `mml/kiinteisto/2025/<1:200k>/<1:100k>/...` (hakemistot M33, M34, N33, N34 todennettu) | Lehdittäin. Agentti todentaa tiedostomuodon ja kentät (palstat, kiinteistötunnukset). Omistajatietoja ei ole eikä niitä haeta. |
| Paikannimet | `mml/paikannimet/2020/` | Vain tarkistus. Reittikartta hakee nimistön jo elävästä rajapinnasta, joten pakettiin ei tarvita nimistöä. |
| DVV osoitteet | `dvv/osoitteet/2025/osoiteet_2025.shp` (+dbf, prj, cpg) | Koko Suomi, Shapefile. Poiminta 3.2.2025, 3 872 156 rakennusta, vain koordinaatilliset ja postinumerolliset. HUOMIO: DVV lopetti aineiston avoimen jakelun 14.3.2025, joten tämä on viimeinen avoin versio eikä se päivity. Kirjataan `aineisto.json`-tiedostoon. Lisenssi CC BY 4.0 (`dvv/DVV_ehdot_CC.txt`). |
| Luke MVMI 2023 | `luke/vmi/2023/keskipituus_vmi1x_1923.tif` ja `latvuspeitto_vmi1x_1923.tif` | Koko Suomi, GeoTIFF 16 m. Luetaan `/vsicurl/` + `gdal_translate -projwin`. Lisenssi CC BY 4.0 (`luke/luke_ehdot.txt`). Lue `README-2023.txt` ja kirjaa yksiköt (keskipituus desimetreinä tai metreinä, latvuspeitto prosentteina) ja no data -arvo. |
| Väylävirasto | WFS `https://avoinapi.vaylapilvi.fi/vaylatiedot/ows`, FeatureTypet `vesivaylatiedot:turvalaitteet_uusi`, `loistot_uusi`, `valosektorit_uusi`, `navigointilinjat_uusi`, `vaylaalueet_uusi`, `vaylat_uusi`, `taululinjat_uusi`, `vesiliikennemerkit_uusi`, `vesivaylien_nopeusrajoitusalueet`, `turvalaitteet_muut_vaylanpitajat`, `navigointilinjat_muut_vaylanpitajat` | GetFeature, `VERSION=1.0.0`, `OUTPUTFORMAT=application/json`, `SRSNAME=EPSG:4326`, bbox muodossa `minlon,minlat,maxlon,maxlat,EPSG:4326` (ilman päätettä tulee tyhjä vastaus). Kentät ks. AINEISTOT.md kohta J. |
| Traficom syvyysalueet | WFS `https://julkinen.traficom.fi/inspirepalvelu/rajoitettu/wfs`, `rajoitettu:DepthArea_A` (ja `Sounding_P`) | Käytetään kuten Reittikartassa (`lahdekoodi/js/chart.js` rivit 217 ja 292 näyttävät kutsun). Lisenssi: muu kuin navigointikäyttö, ei-kaupallinen, lähdemerkintä tiedonsiirron ajankohtineen. |

Maanmittauslaitoksen OGC API Features -rajapintaa (`avoin-paikkatieto.maanmittauslaitos.fi`, api-key) käytetään vain, jos Paitulista puuttuu jokin kenttä, jota tarvitaan. Siinä tapauksessa agentti kirjaa, mikä kenttä, ja työnkulku lukee avaimen salaisuudesta `MML_API_KEY`, mutta toimii ilman sitä jättämällä kyseisen tason pois.

Luettelo lisenssi- ja ehtotiedostoista: `ehdot/MML_ehdot_CC.txt`, `dvv/DVV_ehdot_CC.txt`, `luke/luke_ehdot.txt`. Agentti lukee ne ja kopioi lähdemerkintöjen sanamuodot `aineisto.json`-tiedostoon.

## 4. Tuotokset

Hakemisto `opetus/navi/putki/` sisältää:

1. `lataa.py` tai vastaava: lataa ja rajaa lähteet alueeseen välihakemistoon `tyo/`. Ei lataa koko Suomen tiedostoja kokonaan (ks. kohta 3). Tallentaa jokaisen lähteen hakuhetken.
2. `rakenna.py`: muuntaa EPSG:3067 → EPSG:4326, yksinkertaistaa tiilitasoittain ja tuottaa:
   - Vektoritiilet PMTiles-muodossa tippecanoella, yksi tiedosto `nasijarvi.pmtiles`, tasot 8–16, kerrokset `rakennus` (polygoni, kerrosluku jos saatavilla, käyttötarkoitus), `kiinteistoraja`, `kiinteistotunnus` (piste), `maastokuvio` (luokka), `tie` (luokka, nimi), `osoite` (piste, osoite, postinumero), `turvalaite` (tyyppi, nimi, numero, valaistu, valotunnus `viralvalotunnuse` ja `virallvalotunnus`, sektorit `valosektorit_uusi`-kerroksesta yhdistettynä kentällä `tlnumero`), `navigointilinja`, `vaylaalue`, `taululinja`, `rantaviiva` ja `syvyysalue`.
   - Maaston korkeustiilet Terrain-RGB PNG-muodossa (Mapbox-koodaus), tasot 8–14, 10 m koko alueella ja 2 m rantavyöhykkeellä tasolla 14, hakemistoon `maasto/{z}/{x}/{y}.png` tai PMTiles-rasterina, agentti valitsee ja perustelee.
   - Puuston korkeustiilet samaan tapaan hakemistoon `puusto/`, tasot 10–14.
   - `aineisto.json`: versio, päiväys, bbox, lähteet osoitteineen ja hakuhetkineen, lisenssit ja lähdemerkinnät sanatarkasti, tiilien osoitteet ja tasot, kerrosten kentät.
3. `.github/workflows/aineisto.yml`: ajetaan käsin (`workflow_dispatch`) ja kuukausittain. Asentaa GDAL:n ja tippecanoen (apt tai valmis binaari), ajaa `lataa.py` ja `rakenna.py`, ja julkaisee paketin GitHub Releaseen tagilla `aineisto-YYYY-MM-DD` tai GitHub Pagesiin, agentti perustelee valinnan tiilien HTTP range -pyyntöjen (PMTiles) kannalta. Ei salaisuuksia, ellei kohdan 3 poikkeus toteudu. Työnkulun pitää mahtua GitHubin ilmaisiin rajoihin: ajoaika alle 60 min, levyn käyttö alle 10 Gt, paketin koko alle 150 Mt.
4. `LUEMINUT.md`: mitä hakemistossa on, miten käyttäjä ottaa työnkulun käyttöön (repon luonti GitHubin verkkosivulla, tiedostojen lataus sinne, Actions-välilehdeltä Run workflow), ilman terminaalia.
5. `RAPORTTI_vaihe1.md`.

## 5. Hyväksymiskriteerit lukuina

1. Korkeus tunnetuissa pisteissä ±3 m: Näsijärven pinta noin 95 m (N2000), Pispalanharjun laki yli 150 m, Näsinneulan juuri. Agentti ottaa vertailuarvot korkeusmallista itse ja kirjaa koordinaatit.
2. Rakennuksia Näsijärven ranta-alueella (3 km puskuri) yli 20 000, ja Tampereen keskustan korttelit tunnistettavissa kuvakaappauksesta tasolla 15.
3. Jokaisella Väyläviraston valaistulla turvalaitteella (`valaistu` = K) alueella on valotunnus pakettiin kirjoitettuna, ja sektoriloistoilla sektorit. Vertailu: Mustalahden bboxissa 23,72–23,77 / 61,49–61,53 on 7 turvalaitetta, joista 5 valaistua (vaihe 0).
4. DVV-osoitteita alueella uskottava määrä, ja kolme testiosoitetta löytyvät oikeaan paikkaan (agentti valitsee kolme julkista osoitetta Tampereen Näsijärven rannalta, esimerkiksi Mustanlahden sataman ja Kaupinojan alueelta, ja todentaa paikan kartalta).
5. Paketin koko alle 150 Mt, ja yhden puhelimen näkymän (tasolla 14, 390 × 844 px) lataama määrä alle 5 Mt. Mitataan tiilien koosta.
6. Työnkulku ajaa tässä työtilassa alusta loppuun yhdellä komennolla alle 60 minuutissa, ja `aineisto.json` validoituu.
7. Pieni testisivu `testi.html` (Leaflet + PMTiles-lukija, voi olla CDN-linkeillä, ei vielä Reittikarttaan), joka näyttää rakennukset, kiinteistörajat, turvalaitteet ja maaston varjostuksen, ja josta otetaan kuvakaappaukset kolmesta paikasta: Mustalahti, Siilinkari, Muroleen kanava. Kuvakaappaukset `opetus/navi/putki/shots/`.

## 6. Työtapa

- Tee järjestyksessä: lataus ja rajaus ensin, ja kirjaa jokaisen lähteen siirtomäärä ja aika. Jos jokin lähde ei toimi, siirry seuraavaan ja kirjaa syy, älä jää yrittämään.
- GDAL, tippecanoe ja Python-kirjastot asennetaan tähän työtilaan (apt, pip --break-system-packages, tai tippecanoe käännetään lähteestä). Verkko on sallittu osoitteisiin `mirrors.nic.funet.fi`, `avoinapi.vaylapilvi.fi`, `julkinen.traficom.fi` ja `avoin-paikkatieto.maanmittauslaitos.fi` sekä pakettirekistereihin ja GitHubiin. Muihin osoitteisiin ei pääse, eikä sitä yritetä kiertää.
- Älä muuta Reittikartan koodia tässä vaiheessa. Reittikartan koodi on luettavissa polussa `/home/claude/jvaahtikari/reittikartta/` esimerkiksi WFS-kutsujen mallina.
- Tallenna välituloksia usein. Älä kysy tilaajalta kesken työn, tee ratkaisut itse ja kirjaa ne raporttiin.
- Suomeksi, kokonaisin lausein, desimaalipilkku luvuissa, ei puolipisteitä. Raportti numeroitu ja lyhyt: mitä tehtiin, mitkä luvut saatiin kriteereihin 1–7, mitä oletettiin, mikä ei onnistunut.

Palauta lopuksi tilaajalle lyhyt yhteenveto: tiedostojen polut, kriteerien 1–7 tulokset lukuina ja hyväksytty tai ei, paketin koko, mitä lähteitä ei saatu ja miksi, ja tarvitaanko `MML_API_KEY`-salaisuutta. Älä liitä koodia vastaukseen.
