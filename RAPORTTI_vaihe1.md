# Raportti, vaihe 1: Näsijärven tietoputki

Päiväys 24.10.2026. Hakemisto `/home/claude/opetus/navi/putki/` on valmis kopioitavaksi uuden GitHub-repositorion `reittikartta-aineisto` juureksi. Käyttöönotto selaimessa on kuvattu tiedostossa `LUEMINUT.md`.

## 1. Tulos lyhyesti

Putki toimii alusta loppuun yhdellä komennolla (`python3 ajaa.py`). Puhtaasta hakemistosta tehty testiajo kesti 22 minuuttia (lataus 12,5 min, rakennus 7 min, tarkistus 2,5 min) ja vei levyä 1,9 Gt. Valmis paketti on 109,6 Mt ja sisältää kolme PMTiles-tiedostoa, `aineisto.json`-kuvauksen ja testisivun. Kaikki seitsemän hyväksymiskriteeriä täyttyvät mitatuilla arvoilla (kohta 3). GitHubin omalla koneella ajoa ei ole kokeiltu, koska tässä työtilassa ei ole GitHub-tiliä. Työnkulku on kirjoitettu samalle käyttöjärjestelmälle (Ubuntu 24.04) ja samoilla paketeilla kuin testiajo, mutta sen ensimmäinen ajo GitHubissa on vielä tekemättä.

## 2. Tuotokset

| Tiedosto | Koko | Sisältö |
| --- | --- | --- |
| `ulos/nasijarvi.pmtiles` | 52,7 Mt | vektoritiilet (MVT), zoom 8–16, 26 315 tiiltä, 19 kerrosta |
| `ulos/maasto.pmtiles` | 20,7 Mt | Terrain-RGB (Mapbox-koodaus, 0,5 m:n kvantisointi), zoom 8–14, 1 288 tiiltä |
| `ulos/puusto.pmtiles` | 35,8 Mt | puuston pituus ja latvuspeitto RGBA-tiileinä, zoom 10–14, 1 278 tiiltä |
| `ulos/aineisto.json` | 28 kt | alue, lähteet sanatarkkoine ehtoteksteineen, lähdemerkinnät, kerrokset ja kentät, tiedostokoot ja sha256 |
| `ulos/tarkistus.json` | 4 kt | ajon omat tarkistukset |
| `ulos/testi.html` ja `lib/` | 0,3 Mt | Leaflet 1.9.4, pmtiles 4.5.0 ja protomaps-leaflet 5.1.0 paikallisina kopioina (BSD-lisenssit tiedostossa `lib/LISENSSIT.txt`) |

Koodi: `asetukset.py`, `lataa.py` (13 vaihetta, jatkaa keskeytyksestä), `rakenna.py` (vektori, maasto, puusto, kuvaus), `tarkista.py`, `ajaa.py`, `palvele.py` (paikallinen palvelin Range-tuella) ja `kuvakaappaukset.py`. Työnkulku on `.github/workflows/aineisto.yml` (käsin ja kuukausittain 1. päivä klo 03.17 UTC, aikaraja 55 min).

## 3. Hyväksymiskriteerit

| Nro | Kriteeri | Mitattu | Tulos |
| --- | --- | --- | --- |
| 1 | Korkeudet ±3 m | Järven pinta: 400 satunnaispistettä vesialueelta, mediaani 95,51 m (vaihteluväli 95,34–100,69). Tiilestä Mustalahden edustalta (23,7500 E, 61,5075 N) 95,5 m. Pispalanharjun korkein piste (23,71494 E, 61,50237 N): DEM 10 m 160,4 m, DEM 2 m 160,3 m, maastotiilestä 160,0 m. Näsinneulan juuri (arvio 23,7434 E, 61,5031 N): DEM 10 m 98,3 m, DEM 2 m 97,2 m, tiilestä 97,5 m. | täyttyy |
| 2 | Yli 20 000 rakennusta, keskusta tunnistettavissa | 58 975 rakennusta alueella. Kuvakaappaus `shots/tampere_keskusta_z15.png`: korttelirakenne, Tammerkoski ja Paasikivenkatu erottuvat. | täyttyy |
| 3 | Valaistuilla turvalaitteilla valotunnus ja sektorit | Mustalahden vertailualue (WFS-bbox): 7 turvalaitetta, joista 5 valaistua, kaikilla valotunnus ja sektori. Koko alue: 341 turvalaitetta, 10 valaistua, 13 sektoria, ilman valotunnusta 0 ja ilman sektoreita 0. | täyttyy |
| 4 | Uskottava määrä osoitteita ja kolme testiosoitetta | 46 229 osoitepistettä alueella (koko maassa 3 931 654). Laiturikatu 8 (Mustalahden satama): 3,6 m samannimisestä tiestä. Rantatie 3 (Santalahti): 30,6 m samannimisestä tiestä. Siilinkari 2: 0,8 m Väyläviraston Siilinkari-apuloistosta. Näkymä `shots/osoite_laiturikatu_8.png`. | täyttyy |
| 5 | Alle 150 Mt ja puhelinnäkymä alle 5 Mt | Paketti 109,6 Mt. Pahin 390 × 844 px:n näkymä zoomilla 14 (3 × 5 ruutua): vektori 0,43 Mt ja maasto 0,27 Mt, yhteensä 0,65 Mt, puustolla 0,79 Mt. Selaimessa mitattu todellinen siirto Tampereen keskustassa kirjastot mukaan lukien 0,71 Mt. | täyttyy |
| 6 | Yksi komento alle 60 min, `aineisto.json` validoituu | `ajaa.py --puhdas` 1 330 s (22 min). Validointi JSON Schemalla, tiedostokoot ja sha256 tarkistetaan, ja jokaiselta lähteeltä vaaditaan sanatarkka ehtoteksti. | täyttyy |
| 7 | `testi.html` näyttää rakennukset, rajat, turvalaitteet ja varjostuksen, kuvat kolmesta paikasta | `shots/mustalahti.png`, `shots/siilinkari.png`, `shots/muroleen_kanava.png`. Lisäksi puhelinnäkymä, puustotaso ja osoitenäkymä. Konsolissa ei virheitä. | täyttyy |

## 4. Lähteet ja mitattu siirto

Kaikki lähteet ovat avoimia ilman avainta. `MML_API_KEY` ei tarvita, eikä sitä käytetä.

| Lähde | Tapa | Siirto |
| --- | --- | --- |
| Maastotietokanta 04/2025 | Paitulin lehtikohtaiset Shapefile-paketit, 48 lehteä | 306 Mt, 20 s |
| Maastotietokannan tienimet | GeoPackage `MTK-tie_25-04-03.gpkg` (5,33 Gt) GDAL:n `/vsicurl/`-polulla ja `-spat`-rajauksella | 552 Mt (10 % tiedostosta), 1 972 pyyntöä, 357 s |
| Kiinteistörajat 05/2025 | Paitulin lehtikohtaiset zip-tiedostot | 75 Mt, 16 s |
| Korkeusmalli 10 m ja 2 m | Paitulin lehtikohtaiset tiedostot, 2 m vain 500 m:n rantavyöhykkeelle | 98 Mt ja 850 Mt, yhteensä 31 s |
| DVV:n osoitteet (poiminta 3.2.2025) | `.shp` kokonaan (110 Mt) ja `.dbf`-rivit Range-pyynnöin | 123 Mt, 280 pyyntöä |
| Luken MVMI 2023 | `gdal_translate -projwin` `/vsicurl/`-polulta, keskipituus ja latvuspeitto | 19 Mt |
| Väylävirasto | WFS 1.0.0, 12 kerrosta | 1 Mt |
| Traficom | WFS, syvyysalue, syvyyskäyrä ja syvyyspiste | 16 Mt |

`/vsicurl/`-mittausten päätelmä: GeoPackage on järkevä vain, kun tarvitaan yksi kerros pienellä alueella ja tieto puuttuu lehtikohtaisista paketeista. Tienimiin se oli ainoa keino, koska Shapefile-paketeissa `nimi_suomi` on tyhjä. Muissa tapauksissa lehtikohtainen Shapefile oli selvästi tehokkaampi. `MTK-vakavesi.gpkg` keskeytettiin 10,5 minuutin ja yli 3 265 pyynnön jälkeen eikä lukua saatu valmiiksi (yli 98 Mt siirretty). DVV:n `.shp` `/vsicurl/`-polulla siirsi noin 1 Gt vain 3 × 3 km:n ikkunaan, joten sen tilalle kirjoitettiin oma Range-lukija. Tienimivaihe on aikarajoitettu (25 min) ja sen epäonnistuessa putki jatkaa nimettömillä tieviivoilla.

## 5. Päätökset

1. **Alueen rajaus.** Alue lasketaan Maastotietokannan järvipolygoneista: Näsijärvi, siihen 300 m:n sisällä liittyvät vesialueet (Muroleen kanavan toinen puoli) ja 3 km:n maapuskuri. Tulos on 314 600–347 500 E ja 6 820 100–6 880 000 N (EPSG:3067), vesialue 303,1 km² ja koko alue 1 122,4 km². Määrittelyn arvio (300 000–345 000 E ja 6 815 000–6 880 000 N) oli karkea. Ilman 300 m:n liitossääntöä alue olisi jäänyt 257 km²:iin ja Murole puuttunut.
2. **Julkaisu GitHub Pagesilla, ei Releasena.** Pages lähettää CORS-otsikot ja tukee Range-pyyntöjä, jotka PMTiles tarvitsee, ja osoite on pysyvä (`…github.io/reittikartta-aineisto/`). Release-liitteiden osoite ohjaa toiselle palvelimelle eikä selaimen Range-lukeminen ole siinä varmaa. Tämä on perusteltu päätelmä, ei kokeiltu GitHubissa. Pages vaatii julkisen repositorion, mikä on `LUEMINUT.md`:ssä.
3. **Tippecanoen zoom-rajaus.** Kerros- ja kohdekohtainen `minzoom` pudotti tiilestä lähes kaikki kohteet (yksi rakennus tiilessä 3 000:n sijaan). Rajaus tehdään siksi `-j`-suodattimella. Lisäksi käytetään `--drop-densest-as-needed`-asetusta, joten tiheimmillä zoomeilla yksittäisiä kohteita voi pudota. Rakennukset, kiinteistörajat ja osoitteet säilyvät silti tarkistetuissa Tampereen ruuduissa.
4. **Maastotiilet.** Pelkkää vesialuetta olevia tiiliä ei ole paketissa (merkitty `aineisto.json`:iin, järven pinta noin 95,5 m). Zoomilla 14 rantavyöhykkeellä käytetään DEM 2 m:ää (533 tiiltä), muualla DEM 10 m:ää.
5. **Valotunnus.** `viralvalotunnuse` (kansainvälinen, esimerkiksi `VQ (3) 5 s`) ensisijaisesti ja `virallvalotunnus` rinnalle kenttään `valotunnus_fi`. Sektorit tulevat `valosektorit_uusi`-kerroksesta numerolla `tlnumero`, ja jos niitä ei ole, turvalaiteen tekstikentästä.
6. **Turvalaitteiden kaksoiskappaleet.** Muiden väylänpitäjien kerros toistaa 19 Väyläviraston turvalaitetta, ja ne poistetaan turvalaitenumeron perusteella. Ilman tätä valaistuja oli 14 ja sektoreita 17, oikein 10 ja 13.
7. **Mustalahden vertailualue.** Väyläviraston WFS 1.0.0 tulkitsee bboxin EPSG:3067-tasossa, jolloin suorakulmio on kulmapisteiden ympärille laskettu. Tulos 7/5 toistuu vain tällä tulkinnalla, ja `tarkista.py` käyttää samaa.
8. **Rakennusten kerrosluku.** Shapefile-aineistossa kerrostieto on vain luokkina `1-2` ja `3+`. Kenttä `krs` on siksi luokka, ei kerrosluku. Tarkka kerrosluku vaatisi MML:n rajapinnan (avain) tai GeoPackagen.

## 6. Avoimet kohdat ja varaukset

1. **Paitulin `robots.txt`.** Peilipalvelimen `robots.txt` kieltää `/index/`-polun kaikilta yleisiltä hakukoneilta ja asettaa `Crawl-delay: 20`. Putki ei ole hakukone, mutta tienimien `/vsicurl/`-haku tekee noin 2 000 pyyntöä kuudessa minuutissa, mikä on selvästi tihempää kuin 20 sekunnin viive. Tilaajan kannattaa päättää, hyväksytäänkö tämä vai jätetäänkö tienimivaihe pois (silloin tienimet puuttuvat, muu paketti pysyy). CSC:n Paituli-palvelun käyttöehtoja ei ole tässä luettu.
2. **GitHubin ajoaika.** Testiajo oli 22 minuuttia tässä työtilassa. GitHubin ilmaisella koneella (2 ydintä) tippecanoen ja rasteritiilien rakennus voi kestää enemmän. Arvio on 25–40 minuuttia, ja aikaraja 55 minuuttia on asetettu tämän varalle. Levytila 1,9 Gt on selvästi alle 10 Gt:n rajan.
3. **Näsinneulan koordinaatit** ovat arvioita, koska riippumatonta mittaustulosta ei ollut. Arvo 97,2–98,3 m on uskottava järven pintaan (95,5 m) nähden, mutta täsmällinen vertailu vaatii tiedetyn pisteen.
4. **Sektoreiden värikoodit** (`v`, `p`, `vi`, `k`) ovat lähdeaineiston omia koodeja, eikä koodiluetteloa löytynyt. Testisivu ja kenttäkuvaus olettavat v = valkoinen, p = punainen, vi = vihreä ja k = keltainen, mutta tulkintaa ei ole varmistettu, ja esimerkiksi Rypynniemen sektorijärjestys (vi, v, p, v) ei ratkaise asiaa. Sektorin alku- ja loppukulmat ovat luotettavia, väri ei ole. Väri on tarkistettava Väyläviraston koodiluettelosta ennen kuin sitä käytetään simulaattorissa.
5. **Rakennusmäärä.** Vaiheessa 0 tehdyssä GeoPackage-näytteessä oli 92 552 riviä, Shapefile-lehdistä kohdeosan tunnuksella yhdistettynä 58 975 rakennusta. Eroa ei selvitetty loppuun. Todennäköinen syy on rakennusten osat ja lehtien päällekkäisyys GeoPackagessa. Kumpikin luku ylittää kriteerin, mutta tarkka rakennusmäärä on epävarma.
6. **DVV-aineisto** on poiminta 3.2.2025 eikä päivity. DVV:n pisteitä oli koko maassa 3 931 654, määrittelyssä mainittiin 3 872 156 rakennusta. Eroa ei selvitetty (todennäköisesti useita osoitteita samaa rakennusta kohden).
7. **Lisenssit.** Kaikki lähteet ovat CC BY 4.0 -aineistoja paitsi Traficom: sen syvyysaineisto on muuhun kuin navigointikäyttöön ja ei-kaupalliseen käyttöön, ja lähdemerkintä vaatii tiedonsiirron ajankohdan (kirjattu muotoon `10/2026`). Väylävirasto toteaa aineiston soveltumattomaksi navigointiin. Rajoitukset ovat `aineisto.json`:n kentässä `kayttorajoitukset` ja testisivun alareunassa.
8. **Ei kokeiltu:** Tampereen 3D-malli (jätetty pois vaiheen 0 päätöksen mukaan, koska lisenssiä ei ole luettu) ja MML:n OGC API (vaatii avaimen, eikä sitä tarvittu).

## 7. Jatkoa varten

Kun GitHubin ensimmäinen ajo on onnistunut, `aineisto.json`:n kenttä `paiva` ja tiedostojen sha256 kertovat, onko simulaattorin välimuisti vanhentunut. Kerrosluvun tarkentaminen ja sektoreiden väri-koodien varmistus ovat pienimmät parannukset seuraavaan vaiheeseen.

## 8. Tilaajan tarkastus ja päätökset (Fable, 24.10.2026)

Vaihe 1 hyväksytään. Kaikki seitsemän hyväksymiskriteeriä täyttyvät lukuina, ja tarkistin kuvakaappaukset Mustalahdesta ja Tampereen keskustasta puhelimen koossa: rakennukset, kiinteistörajat, tiet nimineen, syvyysalueet ja Mustalahden apuloisto sektoreineen piirtyvät oikeisiin paikkoihin, ja lähdemerkinnät ovat näkyvissä. Järven pinnan korkeus 95,5 m (N2000) ja Pispalanharjun 160 m vastaavat tunnettuja arvoja.

Kohdan 6 avoimiin kohtiin tilaajan ratkaisut:

1. Sektoreiden värikoodit on varmistettu Reittikartan tuotantokoodista (`lahdekoodi/js/symbols.js`, rivi 137–139): Väyläviraston koodit ovat v valkoinen, p punainen, vi vihreä, k keltainen ja si sininen. Testisivun oletus on siis oikea, ja koodi `si` lisätään simulaattorin värikarttaan.
2. Paitulin `robots.txt` koskee hakukoneita. CSC:n Paituli-palvelun kuvaus tarjoaa aineistot nimenomaan HTTP-, FTP- ja rsync-massalatauksina, joten lehtipakettien lataus on palvelun tarkoitettua käyttöä. Tienimien noin 2 000 aluepyyntöä GeoPackageen kuudessa minuutissa hyväksytään toistaiseksi, koska ajo on kuukausittainen. Jos se halutaan keventää, vaihtoehto on Paitulin `vayla/digiroad`-hakemiston tienimet tai `MTK-tie`-GeoPackagen kertalataus, ja tämä tehdään vasta, jos CSC huomauttaa tai ajo hidastuu.
3. Tippecanoe on Ubuntu 24.04:n pakettivarastossa (versio 2.49.0), joten työnkulun apt-asennus toimii myös GitHubin koneella. Ensimmäinen ajo GitHubissa on silti tehtävä ja sen aika kirjattava.
4. Rakennusmäärän ero GeoPackagen (92 552 riviä) ja Shapefile-lehtien (58 975 rakennusta) välillä jätetään selvittämättä, koska lehtipaketit ovat tuotantolähde ja luku ylittää kriteerin selvästi. Jos vaiheessa 2 jokin tunnettu rakennus puuttuu, asia avataan.
5. Rakennusten kerrosluku on vain luokka (1–2 tai 3 ja yli). Simulaattorin pursotus tehdään luokasta: 1–2 kerrosta 6 m, 3 ja yli 12 m, ja maamerkit erikseen. Tarkka kerrosluku ei ole tämän projektin kannalta tarpeen.

Tietoputki viedään repoon `jvaahtikari/reittikartta-aineisto` suoraan tästä istunnosta, joten LUEMINUT-tiedoston kohdat 1 ja 2 (repon luonti ja tiedostojen lataus) on jo tehty. Käyttäjän tehtäväksi jäävät Pages-asetus ja ensimmäinen ajo.
