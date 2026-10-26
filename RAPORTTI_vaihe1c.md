# Raportti, vaihe 1c: MML:n uusi laserkeilaus, lehtipuuosuus, maaston korkeustarkistus, ruovikot ja ajoloki

Päiväys 26.10.2026. Tekijä: Sonnet-agentti. Tilaaja: Fable. Määrittely: `MAARITTELY_vaihe1c_mml_laser.md`. Todentava ajo: GitHub Actions, ajo 40309106334 (main, commit d010238), kesto 27 min 20 s, onnistui. Ajon yhteenveto on haarassa `ajoloki` tiedostossa `ajoloki/viimeisin.md`.

## 1. Tulokset yhdellä silmäyksellä

| Kriteeri | Tulos |
| --- | --- |
| 1. Ajo onnistuu avaimella ja ajoloki kertoo uuden keilauksen käytön | Täyttyy. Keilausvuosi 2023, 10 ruutua 10:stä MML:n uutta keilausta, 0 ruutua 2008-varalla, 30 407 593 pistettä rantavyöhykkeellä suodatuksen jälkeen (luettu 51 762 043), tiheys 0,517 p/m² kaikella alalla ja 0,852 p/m² maa-alalla, lataus 405,3 Mt |
| 2. Rakennuskorkeudet | Täyttyy osittain. Ranta-Tampellan talo (fid 11060) saa korkeuden 27,10 m (h_max 29,55 m). Tampellan piippu 100,2 m täyttyy. Näsinneula ei täyty: pistepilven korkein osuma on 152,2 m, kun tavoite on 168 ± 3 m |
| 3. Lehtipuuosuus tiilissä | Täyttyy. Näytepisteessä 100 %, koko Pispalanharjun pohjoisrinteen mediaani 19,0 %. Ks. kohta 5 |
| 4. Maaston korkeustarkistus | Täyttyy. Viidessä pisteessä ero DEM 2 m:ään enintään 0,35 m, tiilet ovat oikein, syy on simulaattorin piirrossa |
| 5. Putki toimii ilman avainta ja `tarkista.py` läpi | Täyttyy rajatusti. `laser.py` ilman avainta ajettiin paikallisesti läpi (2008-aineisto, tulokset samat kuin vaiheessa 1b). `tarkista.py` meni läpi Actionsissa avaimella, 12 tarkistusta 12:sta, sekä ennen laserosaa että sen jälkeen. Avaimetonta koko ajoa Actionsissa ei ajettu |
| 6. Raportti | Tämä tiedosto |

## 2. Rajapinnan kutsumuoto (todennettu 26.10.2026)

Lähteet: MML:n ohje avaimen käytöstä (https://www.maanmittauslaitos.fi/en/node/13473, luettu 26.10.2026) ja rajapinnan oma prosessikuvaus (`GET /processes/laserkeilausaineisto_05_karttalehti`, luettu koeajossa 26.10.2026). Perusosoite `https://avoin-paikkatieto.maanmittauslaitos.fi/tiedostopalvelu/ogcproc/v1/`.

1. Tunnistautuminen: HTTP Basic, avain käyttäjätunnuksena ja salasana tyhjänä (`Authorization: Basic base64(avain + ":")`). Vaihtoehto on URL-parametri `api-key=<avain>`. Tulosten latauslinkeissä avainta ei ole, joten otsake lisätään myös latauspyyntöön. Ilman avainta rajapinta vastaa 401.
2. `GET /processes` luettelee 36 prosessia. Käytettävä on `laserkeilausaineisto_05_karttalehti` (pistetiheys 0,5 p/m², enintään 100 karttalehteä haussa, arvioitu koko 5,1 Mt/km²).
3. `POST /processes/laserkeilausaineisto_05_karttalehti/execution` rungolla `{"id": "laserkeilausaineisto_05_karttalehti", "inputs": {"mapSheetInput": ["M4212E1", "M4212E2", ...], "fileFormatInput": "LAZ", "dataSetInput": "Uusin"}}`. Vastaus 201: `{"jobID": "...", "status": "accepted"}`. `dataSetInput` on `05p_2008-2019`, `05p_2020-` tai `Uusin`. Karttalehtijako on 1:5000, ja tunnukset ovat samat kuin Paitulin 2008-indeksissä (esimerkiksi M4212E1).
4. `GET /jobs/{jobID}` kunnes `status` on `successful` (muut tilat accepted, running, failed, dismissed). Kymmenen ruudun työ valmistui 5–18 sekunnissa.
5. `GET /jobs/{jobID}/results/` palauttaa `results`-listan, jossa jokaisella ruudulla on `path` (latauslinkki), `length` (merkkijono), `mapSheetNumber`, `lastModified`, `pointCloudID`, `project`, `scanner`, `pointDensity`, `dateOfScanning`, `yearOfScanning`, `elevationSystem` ja `elevationPrecision`, sekä lopussa `zipPath`.
6. Latauslinkki `.../tiedostopalvelu/dl/v1/{jobID}/{ruutu}.laz` haetaan samalla Basic-otsakkeella. Yhden ruudun lataus kesti 18 s (27 Mt), kaikki kymmenen yhteensä noin 97 s Actionsissa.

Aineisto: keilaus 8.–9.6.2023, Leica CityMapper-2L, projekti 20230107_Leica_Tampere_kesa, harvennettu 0,5 p/m² -versio, LAZ 1.2, pistemuoto 1, korkeusjärjestelmä N2000, korkeustarkkuus 0,1 m. Luokat vain 1, 2, 3, 4 ja 5 (ei rakennus-, vesi- eikä matalan pisteen luokkaa).

## 3. Mitä tehtiin

1. `mml_asiakas.py`: standardikirjastoasiakas, joka puhdistaa avaimen kaikesta kirjoitettavasta tekstistä (virheviestit, URL-osoitteet, Basic-muoto).
2. `laser.py`: lähde `mml_tiedostopalvelu`. Kaikki ruudut haetaan yhdellä työllä. Ruudut tallennetaan `tyo/laser/raaka/laz/mml/` (Actions-välimuistin sisälle) tiedostonimen mukaan, ja ne ladataan uudelleen vain, jos MML:n `lastModified` tai koko muuttuu. Toisessa ajossa lataus oli 0,0 Mt, eli välimuisti toimii. Paitulin 2008-aineisto on varalähde ruutu kerrallaan (jos ruutua ei tule, lataus tai avaus epäonnistuu tai avainta ei ole). Lähdemerkintä päivittyy keilausvuoden mukaan ("Sisältää Maanmittauslaitoksen laserkeilausaineistoa 2023 (CC BY 4.0)"). MML-aineistosta poistetaan luokat 7, 15, 16 ja 18, ja 2008-aineiston käsin rajattu höyrypilven poissulkutilavuus koskee vain 2008-aineistoa. Pintamalli, rakennuskorkeudet, maamerkit ja siluetti lasketaan samalla koodilla. Vaiheet ovat virhesietoisia: yhden maamerkin tai tarkistuksen epäonnistuminen kirjataan eikä kaada ajoa. `aineisto.json` saa uuden lähteen `mml_laserkeilaus`, tiedostot `pinta.pmtiles`, `rakennuskorkeudet.json` ja `maamerkit.json` sekä tiilikuvauksen `pinta`.
3. `rakenna.py` ja `lataa.py`: Luken lajitilavuudet (mänty, kuusi, koivu, muu lehtipuu, kokonaistilavuus, lehtipuiden latvuspeitto) ladataan valinnaisina, ja lehtipuuosuus koodataan `puusto.pmtiles`-tiilien alfakanavaan (kohta 5).
4. `maastotarkistus.py`: `maasto.pmtiles` verrataan MML:n 2 m ja 10 m korkeusmalliin (kohta 6). Se ajetaan Actionsissa laserosan jälkeen, ja se tarkistaa myös lehtipuuosuuden.
5. Ruovikot (kohta 7).
6. `ajoloki.py` ja työnkulku: yhteenveto kirjoitetaan tiedostoon `ajoloki/viimeisin.md` ja työnnetään pakotetulla työnnöllä vain haaraan `ajoloki`. `MML_API_KEY` on ympäristömuuttujana vain laserosa-askeleessa ja yhteenvetoaskeleessa (puhdistusta varten). Yhteenvetoaskel tarkistaa vielä ennen työntöä, ettei avain esiinny tiedostossa. Avain ei esiinny missään tiedostossa eikä tulosteessa. Työnkulun oikeudet: `contents: write` pelkästään ajolokin työntöä varten, ja checkoutissa `persist-credentials: false`. Lisäksi `tarkista.py` ajetaan uudelleen laserosan jälkeen, koska laserosa muokkaa `aineisto.json`-tiedostoa.
7. Työnkulun korjaukset: asennusaskel jäi ensimmäisessä ajossa yli 20 minuutiksi jumiin (apt-vaihe odotti todennäköisesti interaktiivista kysymystä, ei varmistettu, koska lokit eivät ole luettavissa täältä). Asennus on nyt kolmessa askeleessa aikarajoin ja ympäristömuuttujilla `DEBIAN_FRONTEND=noninteractive` ja `NEEDRESTART_MODE=a`, jolloin se kestää noin 25 s. Samalla `cancel-in-progress` on `true`, koska jumiin jäänyttä ajoa ei voinut peruuttaa täältä (403). Seuraus: uusi push keskeyttää kesken olevan ajon.

## 4. Viisi tarkistuskohdetta (vanha 2008, uusi 2023)

| Kohde | Vanha 2008 | Uusi 2023 | Huomio |
| --- | --- | --- | --- |
| Näsinneula, korkein pistepilven osuma maanpinnasta | 152,0 m | 152,2 m | Tavoite 168 ± 3 m ei täyty. Huippu N2000 261,5 m, mastopisteitä 3. Lähde tavoitteelle: Wikipedia (englanninkielinen artikkeli Näsinneula, luettu 26.10.2026): 168 m (167,9 m), ravintola 124 m. Suomenkielistä sivua ei saatu haettua |
| Tampellan piippu | 100,7 m | 100,2 m | Täyttyy (noin 100 m). Huippu N2000 199,2 m |
| Voimalaitoksen päärakennus (kattilarakennus), p95 / max | 46,0 / 90,0 m | 52,1 / 89,9 m | Ala 6609 m² (2008: 4712 m²), sisältää nyt laajennusosat |
| Ranta-Tampellan talo fid 11060, h_p90 / h_max | 0,02 / 0,82 m | 27,10 / 29,55 m | 1235 pistettä, 2008 tontilla ei ollut rakennusta |
| Pispalanharjun korkein maanpinta (luokan 2 piste) | 160,7 m (N2000) | 161,1 m | DEM 2 m:n maksimi samalla laatikolla 160,4 m |

Muut rakennuskorkeudet uudesta aineistosta:

1. Rakennuksia vyöhykkeellä 7013, korkeus saatu 7008 (99,93 %). Ilman korkeutta (pisteitä alle 5 tai h_max alle 2 m) on 57 rakennusta (0,81 %), joista alaltaan vähintään 150 m² vain 4. Vuonna 2008 vastaava luku oli 298 rakennusta.
2. Ranta-Tampellan rajaus (17 rakennusta): kaikilla korkeus, h_p90 15–30 m 15 kappaleella, mediaani 26,4 m. Kolme keilauksen jälkeen rakennettua taloa sai korkeuden: fid 11060 27,1 m, fid 11520 15,8 m ja fid 10949 29,5 m. Lisäksi fid 10945 (28,1 m) ja fid 10944 (29,5 m) olivat 2008 harhaanjohtavasti matalia. Vertailuotos 40 kerrostaloa: h_p90-mediaani 20,2 m, 62,5 % välillä 15–30 m. Vertailuotos 40 pientaloa: mediaani 8,05 m, 82,5 % välillä 3–9 m.
3. Naistenlahden voimalaitoksen alue (MTK-rakennukset vähintään 250 m², laatikko E 328350–328750, N 6823650–6824000, 17 kappaletta): fid 10906 (586 m²) 0,6 m → 44,3 m ja fid 10909 (268 m²) 0,2 m → 14,8 m, eli 2008 näkymättömät rakennukset saivat korkeuden. Fid 10961 (347 m²) 3,8 m → 22,7 m ja pääkattilarakennus fid 10905 46,0 m → 50,8 m. Fid 10877 (670 m²) 7,9 m → 0,3 m, eli se on purettu. Yhtään Naistenlahti 3:n rakennusta ei voitu nimetä varmasti, koska MTK:n rakennuksista ei selviä, mitkä kuuluvat Naistenlahti 3:een. Alueen uudet korkeat rakennukset (fid 10906 ja 10961) ovat todennäköisimmät.
4. Voimalaitoksen piiput: 91,8 m ja 89,9 m (2008: 90,6 m ja 90,0 m). Kuljetinsiltaa ei tunnistettu uudesta aineistosta, kun se 2008-aineistossa löytyi (72,9 m pitkä). Syy on epäselvä: silta voi olla purettu tai uusi laajennus on liittänyt sen hallirakennukseen. Diagnostiikka on `ajoloki/viimeisin.md`-tiedoston kohdassa 2b. Kuljetin ei kuulunut vaiheen 1c kriteereihin.
5. Avoimen maan vertailu (pintamalli vastaan DEM 2 m, 50 pistettä) meni tällä kertaa läpi (vaiheen 1b kriteeri 5), mutta lukuarvoja ei tallentunut ajolokiin.

## 5. Lehtipuuosuus (kriteeri 3)

1. Laskenta: (koivu + muu lehtipuu) / (mänty + kuusi + koivu + muu lehtipuu) tilavuuden mukaan, Luken MVMI 2023, 16 m. Jos lajitilavuuksien summa on 0 mutta latvuspeittoa on, käytetään lehtipuiden latvuspeiton osuutta. Muu metsämaa saa 0 %.
2. Koodaus: alfakanava A = 0 on ei metsämaata (kuten ennen), muuten A = 255 − lattia((osuus + 5) / 10), eli osuus % = (255 − A) × 10 ± 5 prosenttiyksikköä, A välillä 245–255. R, G (keskipituus dm = R × 256 + G) ja B (latvuspeitto %) eivät muutu, ja RGB sekä peitemaski ovat vanhoihin tiiliin nähden identtiset. Koodaus on kirjattu `puusto.pmtiles`-metatietoon ja `aineisto.json`-tiedoston kuvaukseen.
3. Miksi alfa on 245–255 eikä 0–255: simulaattori lukee tiilet `createImageBitmap`-kuvana ja 2D-kanvaksen kautta, jolloin selain esikertoo värit alfalla ja pienet alfa-arvot vääristävät R:n, G:n ja B:n. Alueella 245–255 virhe on enintään yksi yksikkö. Simulaattori ja tutka testaavat vain `A > 0` tai `A === 0`. Haittapuoli on karkea, 10 prosenttiyksikön resoluutio.
4. Tulokset: 4 965 193 metsäruutua, joista 4 841 738 laskettiin tilavuudesta ja 114 867 latvuspeitosta. Koko alueen lehtipuuosuuden p10 / p50 / p90 on 1,8 / 13,1 / 58,0 %, tilavuuspainotettu keskiarvo 18,5 %, ruutuja yli 50 % on 12,6 %.
5. Pispalanharjun pohjoisrinne (Luken ruudut laatikossa E 321000–324400, N 6820500–6823500, DEM 10 m:n rinne vähintään 6 astetta ja alamäkisuunta enintään 45 astetta pohjoisesta): 475 ruutua. Näytepiste on säännöllä valittu eli rinneruutujen mediaanisijaintia lähin ruutu (E 322968, N 6823096). Sen lehtipuuosuus on lähderasterissa 100 % ja tiilessä A = 245 eli 100 % tasoilla 12, 13 ja 14 (pituus 20,6 m, latvuspeitto 65 %). Näytepiste on siis välillä 0–100 ja lehtipuuvaltainen. Koko rinteellä jakauma on kuitenkin vaihteleva: p25 / p50 / p75 on 7,3 / 19,0 / 67,3 %, ja vain 30,5 % rinneruuduista on yli 50 %. Pohjoisrinne ei siis ole yleisesti lehtipuuvaltainen, vain näytepisteen ympäristö on. Tiilen alfa poikkeaa lähderasterista enintään 5 prosenttiyksikköä (mediaani 0).
6. Tiedostokoko: `puusto.pmtiles` 39,7 Mt (aiemmin 35,8 Mt), raskain puhelinnäkymä z14 vektori + maasto + puusto 0,82 Mt.

## 6. Maaston korkeustarkistus (kriteeri 4)

Tiilet `maasto.pmtiles` (Terrain-RGB, korkeus = −10000 + (R × 65536 + G × 256 + B) × 0,1 m). Koodauksen offset −10000 m ja kerroin 0,1 m ovat oikein, kvantisointi on 0,5 m (metatiedossa `quantization_m` 0,5, kaikki tarkistetun tilkan arvot ovat kvantin monikertoja, suurin kvantisointivirhe 0,25 m).

| Piste | DEM 2 m | DEM 10 m | Tiili z14 | Ero DEM 2 m | Ero DEM 10 m |
| --- | --- | --- | --- | --- | --- |
| Pispalanharju (harjun korkein DEM 2 m:n ruutu) | 160,42 m | 160,31 m | 160,32 m | −0,10 m | 0,01 m |
| Näsinneulan juuri | 112,37 m | 112,37 m | 112,35 m | −0,02 m | −0,02 m |
| Siilinkari | 96,85 m | 96,18 m | 96,50 m | −0,35 m | 0,32 m |
| Naistenlahden ranta | 98,16 m | 97,69 m | 97,95 m | −0,21 m | 0,26 m |
| Aitolahden ranta | 95,41 m | 95,47 m | 95,50 m | 0,09 m | 0,03 m |

Muut havainnot:

1. Zoom 14 verrattuna DEM 2 m:ään, 237 tiiltä ja 14,8 miljoonaa pikseliä: mediaaniero −0,01 m, p99 0,61 m, 99,76 % pikseleistä alle 1 m. Rantavyöhykkeellä (500 m) 100 % alle 1 m ja suurin ero 1,54 m. Vyöhykkeen ulkopuolella (tiilen lähde DEM 10 m) 99,58 % alle 1 m.
2. Suurimmat yksittäiset erot (19,5 m, 17,8 m ja 15,6 m) ovat vyöhykkeen ulkopuolella, jossa tiili on tehty 10 m:n mallista. Esimerkiksi pisteessä E 330664, N 6823423 DEM 10 m poikkeaa DEM 2 m:stä 19 m paikallisesti. Tämä on lähteiden välinen ero (DEM 10 m on vuodelta 2019), ei tiilivirhe.
3. Matalilla zoomeilla harjun huippu on tiilessä alempana kuin DEM:ssä (z8 −33 m, z10 −9 m, z12 −1,4 m, z13 −0,7 m), koska tiili on silloin pikseleiden keskiarvo. Tämä tekee maastosta matalamman, ei korkeamman.
4. Päätelmä: tiilet ovat oikein, eikä niissä ole latvuston korkeutta, väärää kerrointa tai siirtymää. Käyttäjän havaitsema liian korkea maasto johtuu siis simulaattorin piirrosta (esimerkiksi korkeusskaalauksesta tai tiilisaumoista), joka tutkitaan erikseen. Tiilivirhettä ei korjattu, koska sitä ei ollut.

## 7. Ruovikot

1. Lähde: SYKE Corine maanpeite 2018, kansallinen 20 m:n rasteri `https://wwwd3.ymparisto.fi/d3/Static_rs/spesific/clc2018_fi20m.zip` (273 Mt, EPSG:3067, CC BY 4.0, ei käyttörajoituksia, kuvaus https://ckanfeo.ymparisto.fi/dataset/corine-maanpeite-2018, luettu 26.10.2026). Saatavuus Actionsista todennettiin koeajossa 26.10.2026 (HEAD 200, Range tuettu), ja lataus kesti Actionsissa 5,3 s. Tästä työtilasta isäntä ei ole tavoitettavissa.
2. Luokka: arvo 42 (LEVEL4 4112) "Sisämaan kosteikot vedessä" (Inland marshes, aquatic). Luokkataulukko luettiin rasterin `.vat.dbf`-tiedostosta.
3. Toteutus: `lataa.py` vaihe `corine` leikkaa rasterista aoi-laatikon, `rakenna.py` muuttaa luokan 42 polygoneiksi rantavyöhykkeellä (500 m), yksinkertaistaa 3 m:n toleranssilla ja pudottaa alle 400 m² polygonit. Uusi vektorikerros `ruovikko` (minzoom 11, kentät `luokka`, `clc`, `selite`) on `nasijarvi.pmtiles`-tiedostossa, ja lähde `syke_corine` on `aineisto.json`-tiedostossa ("Sisältää Suomen ympäristökeskuksen Corine maanpeite 2018 -aineistoa (CC BY 4.0)"). Vaihe on valinnainen: jos lataus epäonnistuu, kerros jää pois eikä lähdettä kirjata.
4. Tulos: 1104 polygonia GeoJSON-vaiheessa. Tiilinäytteessä (z13, laatikko lon 23,60–23,95 ja lat 61,47–61,58) 11 tiiltä, joissa 69 kohdetta ja 833 kärkeä. `nasijarvi.pmtiles` kasvoi 52,7 Mt:sta 53,1 Mt:iin.
5. Rajoitus: 20 m ruutu, joten kapeat ruovikot puuttuvat ja reunat ovat porrasmaisia. Luokka sisältää myös muuta vesikasvillisuutta, ei pelkästään ruovikkoa. Simulaattori ei käytä kerrosta vielä.

## 8. Tiedostokoot ja ajoajat

1. Julkaistu paketti noin 133,5 Mt (nasijarvi 53,06, puusto 39,74, maasto 20,74, pinta 15,74, hakemistot 3,8 ja muut pienet tiedostot). `tarkista.py`:n kokonaisrajaa 150 Mt laskettiin aiemmin mukaan tarkistuskuvat (noin 13,8 Mt), jotka eivät mene Pagesiin. Tarkistus laskee nyt vain julkaistavat tiedostot.
2. `pinta.pmtiles` 15,74 Mt (alle 30 Mt), raskain puhelinnäkymä z15 0,54 Mt (alle 3 Mt).
3. Ajon 40309106334 kesto 27 min 20 s. Laserosa-askel kesti noin 4 min 40 s (ensimmäisessä ajossa 405 Mt:n lataus 97 s, toisessa 0 s välimuistista), `tarkista.py` laserosan jälkeen 1 min 43 s ja maastotarkistus noin 2 min.

## 9. Mitä jäi epävarmaksi tai tekemättä

1. Näsinneulan huippu ei näy pistepilvessä: harvennettu 0,5 p/m² -aineisto antaa mastosta vain 3 osumaa ja korkein on 152,2 m. Simulaattorin mallissa tulee käyttää tunnettua korkeutta 168 m ja pistepilven tulosta vain tornin rungon ja lautasen mittoihin (lautasen halkaisija 8,2 m on todennäköisesti aliarvio, vaiheen 1b arvo 27 m tuli toisesta mittaustavasta, joten mitta tarkistetaan ennen mallinnusta).
2. Kuljetinsiltaa ei löytynyt uudesta aineistosta. Siluettikuvan kohta 7 ei siksi mene läpi, ja se pitää tarkistaa erikseen (silta purettu vai tunnistus ei toimi harvalla aineistolla).
3. Naistenlahti 3:n rakennuksia ei voitu tunnistaa nimeltä. Alueen rakennukset ja niiden korkeudet ovat ajolokissa.
4. Pispalanharjun pohjoisrinteen lehtipuuvaltaisuus toteutuu vain näytepisteen ympäristössä (rinteen mediaani 19 %). Alfakoodauksen 10 prosenttiyksikön resoluutio on karkea.
5. Aineistovirheiden diagnostiikka perustuu ajolokiin: Actionsin lokit eivät ole luettavissa tästä työtilasta. Ajolokista puuttuu avoimen maan vertailun lukuarvot (kriteeri 5 vaiheesta 1b).
6. Avaimetonta koko putkea ei ajettu Actionsissa, vain `laser.py` paikallisesti ja MML-polku paikallisella valepalvelimella (9 ruutua uutena, 1 ruutu 2008-varalla). Jos avain poistetaan, `tarkista.py` ajetaan 2008-aineistolla ensimmäisen kerran vasta silloin.
7. Väliaikaiset koehaarat `ajoloki-probe` ja `ajoloki-ruovikko` jäivät repoon, koska haarojen poisto ei onnistunut täältä (oikeus evättiin). Ne voi poistaa GitHubin käyttöliittymästä, ne sisältävät vain koeajojen yhteenvedot.
8. Työnkulun `cancel-in-progress: true` muuttaa vanhaa käytöstä: uusi push keskeyttää kesken olevan ajon. Jos haluat entisen jonotuksen, vaihda arvo takaisin `false`.
9. Ruovikko-kerrosta ja uutta pintamallia ei ole liitetty simulaattoriin eikä Reittikarttaan. Paketin tiedostorakenne ja nykyiset kanavat eivät muuttuneet, mutta `puusto.pmtiles`-tiilien alfa ei ole enää pelkästään 0 tai 255.
