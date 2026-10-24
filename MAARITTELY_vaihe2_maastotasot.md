# Määrittely, vaihe 2: Maasto-tasot ja osoitehaku Reittikarttaan

Päiväys 24.10.2026. Tekijä: Sonnet-agentti. Tilaaja: Fable. Tausta: "Opetusohjelma/Navigointisimulaattori suunnitelma.md" (kohta 5, vaihe 2), vaiheen 1 raportti `RAPORTTI_vaihe1.md` ja paketin kuvaus `aineisto.json`.

## 1. Tavoite

Reittikarttaan lisätään Näytä-valikkoon uusi ryhmä Maasto, jonka tasot luetaan vaiheen 1 aineistopaketista, ja haku laajennetaan katuosoitteisiin ja kiinteistötunnuksiin. Tarkoitus on, että tehtäväpaikan voi löytää ilmoittajan antamalla osoitteella tai mökin kiinteistötunnuksella, ja että kartalla näkyvät tarvittaessa rakennukset, tiet, maastotyyppi ja korkeuserot. Nykyinen käyttö ei muutu: kaikki uudet tasot ovat oletuksena pois päältä, ja alueen ulkopuolella ne eivät tee mitään.

## 2. Aineistopaketti

Paketti on julkaistu osoitteessa `https://jvaahtikari.github.io/reittikartta-aineisto/` ja sen kuvaus on `aineisto.json` samassa hakemistossa. Tiedostot ovat `nasijarvi.pmtiles` (vektoritiilet, MVT, zoom 8–16, ruutu 512 px), `maasto.pmtiles` (Terrain-RGB, zoom 8–14) ja `puusto.pmtiles` (zoom 10–14, ei käytetä tässä vaiheessa). Kerrokset ja kentät ovat `aineisto.json`-tiedoston kohdassa `tiilet.vektori.kerrokset`, ja tärkeimmät ovat:

- `rakennus` (polygoni, zoom 13–16): `kaytto`, `krs` (1-2 tai 3+), `z`, `luokka`.
- `kiinteistoraja` (viiva, 14–16): `laji`. `kiinteistotunnus` (piste, 15–16): `tunnus`, `kunta`.
- `maastokuvio` (polygoni, 8–16): `luokka`, `koodi`.
- `tie` (viiva, 8–16): `luokka`, `nimi`, `tienumero`, `paallyste`.
- `osoite` (piste, 15–16): `osoite`, `postinumero`, `tyyppi`.
- `turvalaite`, `navigointilinja`, `vaylaalue`, `syvyysalue` ja muut: näitä EI käytetä Reittikartassa, koska Reittikartta hakee ne elävästä rajapinnasta. Ne ovat simulaattoria varten.

Paketin osoite tallennetaan asetuksiin (`settings.terrainUrl`, oletus yllä), jotta sen voi vaihtaa ilman koodimuutosta, ja `aineisto.json` luetaan käynnistyksessä kerran, kun jokin Maasto-taso on päällä. Lähdemerkinnät otetaan `aineisto.json`-kentästä `lahdemerkinta_yhteensa` ja näytetään kohdassa Ohje → Aineistot ja käyttöehdot sekä kartan attribuutiossa, kun Maasto-tasoja on näkyvissä.

Paketin testisivu `https://jvaahtikari.github.io/reittikartta-aineisto/testi.html` ja sen lähdekoodi repossa `jvaahtikari/reittikartta-aineisto` (`testi.html`, paikallinen kopio `/home/claude/reittikartta-aineisto/testi.html`) näyttävät toimivan tavan lukea pakettia protomaps-leaflet-kirjastolla. Sitä saa käyttää mallina.

## 3. Kirjastot

Reittikartta on yksi HTML-tiedosto, johon kirjastot upotetaan `lahdekoodi/build.py`-skriptillä. Uudet kirjastot lisätään hakemistoon `lahdekoodi/lib/` ja upotetaan samoin kuin Leaflet, lisenssitekstit mukaan samaan tapaan kuin `README.md` kuvaa Leafletin osalta:

- `pmtiles` 4.5.0 (BSD-3-Clause), PMTiles-lukija HTTP range -pyynnöillä.
- `protomaps-leaflet` 5.1.0 (BSD-3-Clause), MVT-tiilien piirto Leafletiin. Suunnitelma mainitsi Leaflet.VectorGridin, mutta protomaps-leaflet on jo todettu toimivaksi paketin kanssa testisivulla ja piirtää canvasille, joten se valitaan. Jos agentti toteaa sen hitaaksi puhelimella (ks. hyväksyminen), se saa vaihtaa Leaflet.VectorGridiin ja perustella.

Kopiot kirjastoista ovat valmiina hakemistossa `/home/claude/reittikartta-aineisto/lib/` lisenssitiedostoineen (`LISENSSIT.txt`).

Tiedostona avatussa Reittikartassa (file://) PMTiles-luku ei toimi ilman verkkoa, ja Pages-osoitteen range-pyynnöt toimivat selaimesta normaalisti. Agentti todentaa, että tasot toimivat sekä Vercel-osoitteessa että tuplaklikatussa tiedostossa, kun verkko on käytössä, ja että ilman verkkoa tasot vain jäävät tyhjiksi ilman virheilmoitusta.

## 4. Toiminnot

### 4.1 Näytä-valikon ryhmä Maasto

Valikon rakenne on `lahdekoodi/js/app.js`-tiedoston `menus`-oliossa (rivi noin 328, Näytä-valikon kohdat riveillä noin 390–425). Uusi otsikko `{ head: 'Maasto (Näsijärvi)' }` ja sen alle valinnat, jokainen tallennettuna `state.settings.show`-olioon uusin avaimin ja oletuksena `false`:

1. Rakennukset (`terrainBuildings`): rakennuspolygonit zoomista 15 alkaen, väri käyttötarkoituksen mukaan hillitysti (asuin harmaanruskea, muu harmaa), napautus näyttää käyttötarkoituksen ja kerrosluokan.
2. Osoitteet (`terrainAddresses`): osoitepisteet zoomista 17 alkaen tekstinä rakennuksen vieressä. Zoomilla 15–16 ei tekstiä, vain piste, jotta kartta ei täyty.
3. Kiinteistörajat (`terrainParcels`): rajat ohuina viivoina zoomista 16, kiinteistötunnus napautuksella (lähin `kiinteistotunnus`-piste 30 m säteellä).
4. Maastotyyppi (`terrainCover`): maastokuviot läpikuultavina väreinä (pelto keltainen, suo violetinharmaa, kallio vaaleanharmaa, taajama vaaleanpunainen, puisto vihreä), zoom 10 alkaen.
5. Korkeuskäyrät ja varjostus (`terrainRelief`): `maasto.pmtiles`-rasterista laskettu vinovalovarjostus canvasille kuten testisivulla, zoom 10–14 (tasolla 15 ja yli käytetään tason 14 tiiliä suurennettuna). Korkeuskäyriä ei piirretä tässä vaiheessa, jos niiden laskenta Terrain-RGB:stä selaimessa osoittautuu hitaaksi, ja silloin valinnan nimi on vain Varjostus.
6. Tiet (`terrainRoads`): tiet luokan mukaan (pääväylät paksummin), nimet zoomista 15, zoom 12 alkaen.

Tasot piirretään vektorikartalla ja rasteri- sekä ENC-pohjalla samoin, maapohjan päälle mutta merikartan merkkien ja reittien alle. Piirtojärjestys: maastotyyppi, varjostus, kiinteistörajat, tiet, rakennukset, osoitteet.

Kun jokin Maasto-taso on päällä ja kartan näkymä on paketin alueen ulkopuolella (`aineisto.json` kenttä `alue`), kartan oikeaan yläkulmaan tulee sama tyyppinen huomautus kuin ENC:n kattavuudesta: "Maastoaineisto kattaa vain Näsijärven". Alueella huomautusta ei näytetä.

### 4.2 Haku

Haku on `lahdekoodi/js/search.js`. Funktio `remote(q, at)` kokoaa lähteet ja `find(q, at)` on tehtäväpaikan haku. Lisätään kaksi lähdettä:

1. Osoitehaku: kun hakusana näyttää katuosoitteelta (kirjaimia ja lopussa numero, esimerkiksi "Kaupinojankatu 12" tai "Laiturikatu 8"), haetaan `osoite`-kerroksesta. Koska PMTiles-pakettia ei voi hakea tekstillä, agentti valitsee toteutustavan ja perustelee: joko (a) tietoputki tuottaa pakettiin erillisen `osoitteet.json`-hakemiston (osoite, postinumero, lat, lon, noin 46 000 riviä, pakattuna arviolta 1 Mt), joka ladataan kerran, kun käyttäjä hakee ensimmäisen kerran osoitetta, tai (b) haku lukee tiilet nykyisen näkymän ympäriltä. Vaihtoehto (a) on todennäköisesti oikea, koska haun pitää löytää osoite mistä tahansa alueelta. Jos (a) valitaan, agentti lisää `osoitteet.json`-tuotannon tietoputkeen (`/home/claude/reittikartta-aineisto/rakenna.py`) ja `aineisto.json`-kuvaukseen, ja tilaaja ajaa tietoputken uudelleen GitHubissa ennen testausta. Vastaavasti kiinteistötunnuksille `kiinteistot.json` (tunnus, lat, lon, noin 200 000 riviä, arvio pakattuna 2–3 Mt, ladataan vain kun haetaan tunnuksella).
2. Kiinteistötunnushaku: hakusana muodossa `837-123-4-56` tai ilman väliviivoja 14-numeroisena.

Hakutulos näytetään muiden tulosten joukossa kunnan ja etäisyyden kanssa kuten nykyiset, lajina "osoite" tai "kiinteistö", ja se kelpaa tehtäväpaikaksi samoin kuin paikannimi. Haku toimii myös, kun Maasto-tasot ovat pois päältä.

### 4.3 Asetukset ja ohje

Tiedosto → Asetukset saa kentän Maastoaineiston osoite (oletus Pages-osoite). Ohje → Aineistot ja käyttöehdot saa uuden kohdan, jossa luetellaan paketin lähteet `aineisto.json`-tiedostosta luettuna (Maanmittauslaitos, DVV, Luke) lisensseineen, ja huomautus siitä, että DVV:n osoitteet ovat poiminta 3.2.2025. `README.md`-tiedoston aineistotaulukkoon lisätään samat rivit.

## 5. Rajaukset

- Reittikartan nykyisiä toimintoja ei muuteta. Olemassa olevat testit (`lahdekoodi/tests/`) menevät läpi muuttamattomina.
- Simulaattorin kerroksia (turvalaitteet, syvyydet paketista) ei käytetä Reittikartassa.
- Puustoa ja korkeuskäyriä ei tehdä, jos ne eivät ole yksinkertaisia (ks. 4.1 kohta 5).
- Ei muutoksia Vercelin välityspalveluun. Suunnitelman maininta kiinteistötietojen polun lisäämisestä MML-proxyyn ei enää päde, koska kiinteistörajat tulevat paketista.

## 6. Hyväksymiskriteerit

1. Osoitehaku löytää Laiturikatu 8, Rantatie 3 ja Siilinkari 2 alle 50 m päähän vaiheen 1 tarkistuksessa todetuista paikoista, ja tulos kelpaa tehtäväpaikaksi.
2. Kiinteistötunnushaku löytää kolme agentin paketista valitsemaa tunnusta (yksi Tampereen keskustasta, yksi Teiskosta, yksi Muroleen läheltä) oikeaan palstaan.
3. Kiinteistötunnus näkyy napautuksella kolmessa paikassa.
4. Kartan vieritys ja zoomaus pysyvät sulavina Pixel 7 -profiililla, kun rakennukset, tiet ja varjostus ovat päällä Tampereen keskustassa zoomilla 15: tiilen piirto alle 100 ms ja yhden näkymän siirto alle 2 Mt, mitattuna Playwrightilla.
5. Alueen ulkopuolella (esimerkiksi Helsinki) tasot eivät aiheuta virheitä konsoliin, verkkopyyntöjä paketin tiiliin ei tehdä alueen ulkopuolella, ja huomautus näkyy.
6. Kaikki nykyiset testit menevät läpi, ja uusi testi `terrain_test.py` kattaa kohdat 1–5 mock-aineistolla tai paketilla.
7. Mobiilitestit (mobile-ux-test: WebKit iPhone 14 ja Chromium Pixel 7) läpi Näytä-valikon, hakutulosten ja napautusten osalta.
8. `build.py` tuottaa yhden tiedoston, jonka koko kasvaa alle 400 kt (kirjastot pakkaamattomina).

## 7. Työtapa

- Työ tehdään haarassa `maasto` Reittikartan repossa. Paikallinen klooni on `/home/claude/jvaahtikari/reittikartta/` (vain luku, shallow), joten agentti tekee työn kopioon `/home/claude/reittikartta-maasto/` ja raportoi, mitkä tiedostot muuttuivat. Tilaaja vie muutokset repoon.
- Lue ensin `README.md` kokonaan ja `lahdekoodi/LUEMINUT.md`, sitten `app.js` (valikot, asetukset), `search.js`, `chart.js` (tasojen piirtojärjestys, attribuutio, ENC-kattavuushuomautus mallina) ja `store.js` (asetusten oletukset ja versiointi).
- Verkko: `jvaahtikari.github.io` EI ole tämän työtilan sallituissa osoitteissa (todettu, 403), joten testeissä paketti tarjoillaan paikallisesti: tiedostot ovat hakemistossa `/home/claude/opetus/navi/putki/ulos/` ja ne tarjoillaan `python3 -m http.server`-komennolla (tukee range-pyyntöjä), ja testit asettavat `settings.terrainUrl`-osoitteeksi paikallisen palvelimen. Tuotanto-oletus koodissa on silti Pages-osoite.
- Työkopio on valmiina hakemistossa `/home/claude/reittikartta-maasto/` (ilman .git-hakemistoa). Tee kaikki muutokset sinne.
- Playwright on asennettu (älä aja `playwright install`). Testit ajetaan kuten `README.md` kohta Testaus kuvaa.
- Älä kysy tilaajalta kesken työn, tee ratkaisut itse ja kirjaa ne raporttiin. Tallenna välituloksia usein.
- Suomeksi, kokonaisin lausein, desimaalipilkku, ei puolipisteitä. Käyttöliittymätekstit Reittikartan nykyisellä tyylillä.
- Raportti `RAPORTTI_vaihe2.md`: numeroitu, lyhyt, kriteerien 1–8 tulokset lukuina, muuttuneet tiedostot, mitä oletettiin, mikä ei onnistunut, tarvitaanko tietoputken uudelleenajo.

Palauta lopuksi lyhyt yhteenveto: muuttuneiden tiedostojen polut, kriteerien 1–8 tulokset ja hyväksytty tai ei, kirjastovalinta perusteluineen, ja tarvitaanko tietoputken uudelleenajo. Älä liitä koodia vastaukseen.
