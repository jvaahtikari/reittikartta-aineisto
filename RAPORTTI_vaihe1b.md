# Raportti, vaihe 1b: laserkeilaus rantavyöhykkeeltä

Päiväys 25.10.2026. Tekijä: Sonnet-agentti. Tilaaja: Fable. Tuotokset ovat hakemistossa `/home/claude/aineisto-1b/ulos/`, ja koko tuotanto ajetaan yhdellä komennolla `laser.py`. Moduuli ei muuta `rakenna.py`- eikä `lataa.py`-tiedostoja.

## 1. Mitä tehtiin

1. Alue: ETRS-TM35FIN E 322 000–334 000, N 6 822 100–6 827 000 (määrittelyn laatikko 322 000–334 000, 6 820 000–6 827 000 rajattuna vesialueen 1 km vyöhykkeeseen). Vyöhykkeen pinta-ala on 41,5 km², josta vettä 23,5 km². Näsinneula, Naistenlahden voimalaitos, Tampella ja Ranta-Tampella ovat mukana. Alue vaihdetaan asetuksella `ALUE_LAATIKKO` ja `VYOHYKE_M`.
2. Lähde: Paitulin laserkeilausaineisto, **lehti M421, keilaus 18.4.2008** (ei lehti M344 vuodelta 2013, kuten tehtävänannossa arvioitiin). Lehdelle M344 ei ole ruutuja tällä alueella. Ruudut on valittu 2008_latest-indeksistä ja hakemistolistauksista: M4212E1–E4, M4212G1–G4, M4214A1 ja M4214A2 eli 10 ruutua. Muita vuosia ei ole saatavilla samoille ruuduille. Keilain Optech ALTM Gemini, pistetiheys 0,43 pistettä/m², korkeustarkkuus 0,15 m, LAZ 1.0, N2000. Lisenssi CC BY 4.0, lähdemerkintä "Sisältää Maanmittauslaitoksen laserkeilausaineistoa 2008 (CC BY 4.0)".
3. Pistepilvi luettiin laspy- ja lazrs-kirjastoilla. Luokat 7 ja 18 poistettiin (luokkaa 18 ei ole aineistossa, luokkaa 7 on 678 pistettä). Lisäksi ajettiin kohinasuodatus (4 m:n kennot, vähintään 3 pistettä 3 x 3 x 3 -ympäristössä yli 4 m maan yläpuolella), pilvisuodatus yli 45 m:n korkeudelle ja yksi käsin rajattu poissulkutilavuus Naistenlahden höyrypilvelle. Tallennettuja pisteitä on 33,9 miljoonaa.
4. Pintamalli (DSM) 1 m: korkein piste per ruutu. Maa ja vesi täytetään erikseen enintään 3 ruudun päästä, loput täytetään maalla DEM:stä (0,99 % vyöhykkeen maaruuduista) ja vedessä järven pinnasta 95,42 m N2000. Pintamalli ei mene maanpinnan alapuolelle. Terrain-RGB-koodaus (0,5 m kvantti), tasot 12–16, puhtaat vesitiilet jätetty pois.
5. Rakennuskorkeudet maastotietokannan 7 013 rakennukselle (`fid` on `rajattu.gpkg`:n kerroksen `rakennus` FID). Kentät `z_maa`, `h_max`, `h_p90`, `h_med`, `pisteita`, `epavarma`, uusina `keilausvuosi` ja `ei_keilattu`.
6. Maamerkit: pistepilvestä mitatut Näsinneula, Naistenlahden voimalaitos, Tampellan piippu ja tehdasrakennukset, Särkänniemen korkeat ehdokaskohteet ja Mustalahden sataman rakennukset. Mittatavat ovat `maamerkit.json`:ssa jokaisen mitan vieressä.
7. Tarkistuskuvat: koko alueen varjostus, kolme lähikuvaa ja kaksi siluettia vedestä. Siluetteihin on numeroidut nimilaput ja niiden alle varjostuskartta, jossa on näköpiste, katselusektori ja samat kohteet numeroituina.

## 2. Kriteerit 1–7

| Kriteeri | Tulos | Hyväksytty |
|---|---|---|
| 1. Näsinneulan huippu 165–171 m | Korkein havaittu 152,0 m maasta (261,2 m N2000, 6 pistettä). Arvio 168 m on tornin tunnettu korkeus, ei mittaus. | Ei täyty lukuna, kirjattu määrittelyn varavaihtoehdon mukaisesti |
| 2. Korkein piippu | 90,6 m maasta (189,02 m N2000), toinen piippu 90,0 m. Korkeimman etäisyys rakennuspolygoniin 9,8 m ja toisen 0 m. | Kyllä |
| 3. Kuljetinsilta | Pituus 72,9 m, leveys 6,7 m, suunta 42,6° pohjoisesta, korkeus 30,3 m kattilarakennuksen päässä ja 15,8 m toisessa päässä (mediaani 19,6 m). Näkyy kuvissa `lahikuva_voimalaitos.png` ja `siluetti_naistenlahdelta.png`. | Kyllä |
| 4. Rakennukset | 7 005 / 7 013 saa korkeuden (99,9 %). Otosten mediaanit ovat vaadituilla väleillä, mutta osuudet ovat pienempiä (ks. kohta 3). | Kyllä mediaaneilla, osuuksin rajoituksin |
| 5. Avoin maa, DSM miinus DEM alle 1 m | 50 satunnaisesta pisteestä 48 alle 1 m. Kaksi ylittää (1,02 ja 4,91 m), molemmat Lielahdessa. | Ei (48 / 50) |
| 6. Koko | `pinta.pmtiles` 15,38 Mt. Raskain 3 x 5 tiilen puhelinnäkymä tasolla 15 on 0,54 Mt. | Kyllä |
| 7. Siluetti | Piiput, kuljetin ja Näsinneula näkyvät erillisinä muotoina kuvassa `siluetti_naistenlahdelta.png`. | Kyllä |

Kriteerin 1 selitys: Näsinneulan antennimasto on ohut, ja keilauksen tiheys 0,43 pistettä/m² riittää vain kuuteen mastopisteeseen. Havaittu 152,0 m on siksi alaraja. Lautasen ulkoreunan katto on 129,0 m maasta, lautasen halkaisija 27,0 m ja varren halkaisija noin 9,1 m (sovitus yhden puolen osumista, suuntaa antava). Torni on pisteessä E 326 711, N 6 823 364, ja maanpinta on 109,16 m N2000.

Kriteerin 2 selitys: piipun korkeus on korkein pistepilven piste piipun kohdalla, joten todellinen korkeus voi olla hieman suurempi. Piipun halkaisijat ovat arvioita (5,4 m ja 4,6 m). Kattilarakennuksen katto on mediaanikorkeudeltaan 46 m (p95) ja korkeimmillaan 90 m (polygonin korkein piste).

Kriteerin 3 selitys: kuljetin on kapea suorakulmio, jonka korkeusprofiili laskee kattilarakennukselta lounaaseen. Suorakulmion kulmat ja profiili ovat `maamerkit.json`:ssa.

Kriteerin 5 selitys: avoin maa tunnistettiin pistepilvestä niin, että 5 m:n kenno ja sen kahdeksan naapuria sisältävät vain maapisteitä (vähintään 5 maapistettä keskikennossa), eikä vettä tai rakennusta (10 m:n puskuri) ole lähellä. Avoimia kennoja on 39 077 eli 976 925 1 m:n ruutua. Koko joukossa ero on mediaanina 0,0 m, 95. persentiili 0,26 m ja 99. persentiili 4,54 m, ja 96,9 % ruuduista on alle 1 m. Suuret erot keskittyvät kahteen paikkaan: Lielahteen (E 323 350–323 450, N 6 824 350–6 824 550, mediaaniero +4,8 m) ja kohtaan E 322 150–322 250, N 6 825 750 (+1,8–2,1 m). Näissä paikoissa pelkät maapisteet ovat tasaisesti yli metrin DEM:n yläpuolella 15 m:n ympäristössä, joten kyse on maanpinnan muutoksesta (maansiirto) DEM:n ja keilauksen välillä eikä pintamallin virheestä. Tämä on tulkinta, jota en voinut varmentaa DEM:n omasta keilausvuodesta. Kriteeri ei täyty sellaisenaan.

## 3. Keilausvuosi ja sen seuraukset rakennuksille

Kaikkien kymmenen ruudun keilausvuosi on **2008** (keilauspäivä 18.4.2008). Tilaajan viestissä mainittua vuotta 2013 ei aineistossa ole. Seuraukset ovat siksi vielä suuremmat kuin vuoden 2013 aineistolla:

1. Ranta-Tampellan uudet kerrostalot (rakennettu 2017 alkaen) ja kaikki muu vuoden 2008 jälkeen rakennettu puuttuvat pistepilvestä. Naistenlahden voimalaitoksen mahdolliset uudet laajennukset (Naistenlahti 3, 2022) eivät näy pistepilvessä, eikä kyseisen rakennuksen tunnistaminen maastotietokannan polygoneista onnistunut varmasti.
2. Maastotietokannan 2025 rakennukselle antaa `h_p90` tai `h_max` silloin joko tyhjän (tontin, työmaan tai kasvillisuuden) tai väärän korkeuden. Siksi jokaisella rakennuksella on nyt `keilausvuosi`, ja lippu `ei_keilattu` on 1, kun pisteitä on alle 5 tai `h_max` on alle 2 m maanpinnan yläpuolella. Lisäksi vanha lippu `epavarma` (vähintään 150 m² ja `h_max` alle 3 m) säilyy.
3. Lippu `ei_keilattu` koskee **298 rakennusta eli 4,25 %** alueen 7 013 rakennuksesta. Näistä 8:ssa on alle 5 pistettä ja 77 on vähintään 150 m² kokoisia. Käyttötarkoitus: muu rakennus 196, asuinrakennus 82, toimisto- tai julkinen rakennus 11, teollisuusrakennus 8 ja lomarakennus 1. Joukossa on myös matalia katoksia ja varastoja, jotka ovat oikeasti alle 2 m. Täydellinen 25 suurimman lista on `tarkistus_1b.json`:ssa (kohta `4_rakennukset`, `ei_keilattu`). Kymmenen suurinta:

| fid | E | N | ala m² | käyttö | krs | pisteitä | h_max m |
|---|---|---|---|---|---|---|---|
| 9176 | 330139 | 6823873 | 2904,2 | muu rakennus | 1-2 | 2402 | 0,16 |
| 11060 | 327766 | 6823296 | 2256,9 | asuinrakennus | 3+ | 1042 | 0,82 |
| 14049 | 322049 | 6825807 | 1857,8 | teollisuusrakennus | 1-2 | 791 | 1,85 |
| 17782 | 323569 | 6825354 | 1198,8 | toimisto- tai julkinen rakennus | 1-2 | 552 | -1,59 |
| 18260 | 323466 | 6825458 | 1104,3 | asuinrakennus | 3+ | 540 | 0,49 |
| 18257 | 323404 | 6825450 | 935,8 | asuinrakennus | 3+ | 466 | 0,99 |
| 11520 | 327456 | 6823466 | 824,2 | asuinrakennus | 3+ | 390 | 1,44 |
| 17780 | 323618 | 6825352 | 802,8 | asuinrakennus | 3+ | 368 | -0,78 |
| 17784 | 323577 | 6825335 | 776,1 | asuinrakennus | 3+ | 363 | -0,65 |
| 9179 | 330059 | 6823864 | 740,4 | toimisto- tai julkinen rakennus | 1-2 | 642 | 0,51 |

4. Ranta-Tampellan otos: maastotietokannan asuinrakennukset, joilla kerrosluokka 3+ ja jotka ovat enintään 25 m:n päässä osoitepisteestä kaduilla Verstaankatu, Alaverstaanraitti, Juhlatalonkatu, Turpiininkatu, Valssipadonraitti ja Tampellan esplanadi. Otoksessa on 17 rakennusta, joista 10:llä `h_p90` on 15–30 m (mediaani 22,4 m). Loput 7 ovat joko uudisrakennuksia (`h_p90` alle 3 m tai negatiivinen, 3 niistä `epavarma`-lipulla), yksi on aivan alle rajan (14,2 m) ja yksi ylittää rajan piipun vuoksi (42,9 m). Rajaus on päätelty katunimistä, joten Ranta-Tampellan uusien talojen ja vanhojen Tampellan rakennusten erottelu ei ole rakennuskohtaisesti varmennettu.
5. Vertailuotokset alueilta, joilla rakennus oli keilaushetkellä paikallaan (satunnaisotos 40 rakennusta, siemen 20261025):
   - Kerrostalot (asuinrakennus, krs 3+, ala vähintään 300 m², ei `epavarma`): `h_p90` on 15–30 m 24 rakennuksella eli 60 %, mediaani 16,3 m. Kerrosluokka 3+ sisältää myös 3–4-kerroksiset talot, jotka jäävät alle 15 m.
   - Pientalot (asuinrakennus, krs 1–2, ala 60–250 m², ei `epavarma`): `h_p90` on 3–9 m 31 rakennuksella eli 77,5 %, mediaani 7,8 m. Yli 9 m olevat ovat korkeita kaksikerroksisia taloja, joissa piste osuu harjalle tai lähipuuhun.
6. Kriteerin 4 hyväksyntä on tässä luettu niin, että vähintään 80 % rakennuksista saa korkeuden ja jokaisen otoksen `h_p90`-mediaani on vaaditulla välillä. Määrittely ei anna osuusrajaa otoksille.

## 4. Siluettikuvan piikki suunnassa noin 170°

Tilaajan havaitsema yli 10° korkeuskulmaan nouseva piikki 0,4–0,8 km:n kaistassa ei ole harhapiste. Se on Tampellan alueen korkea piippu pisteessä E 327 815, N 6 823 431, ja se on 555 m näköpisteestä suunnassa 172,3°. Piippu ei ole Naistenlahden eteläpuolella vaan Tampellassa, noin 1,6 km voimalaitokselta lounaaseen.

Todisteet pistepilvestä:

1. Pintamallissa on 40 ruutua yli 150 m N2000 vain tässä kohdassa (9 x 7 m), ja korkein on 199,62 m eli 100,7 m maanpinnan yläpuolella. Naistenlahden eteläpuolella ei ole yhtään ruutua yli 150 m (korkein 149,06 m).
2. Raakapisteitä on 49 kappaletta korkeusvälillä 133–199,6 m ja alueella 6 x 5 m, tasaisesti noin 1–3 m välein pystyjonona maasta huippuun. Lähes kaikki ovat ensimmäisiä kaikuja (luokka 1, viisi luokkaa 3). Lähellä (15 m) olevista yli 20 m:n pisteistä 53 / 57:llä on naapuri enintään 3 m päässä vaakasuunnassa ja enintään 5 m:n korkeuserolla. Pystypeitto on 14 / 18 viiden metrin lokerossa.
3. Luokkia 7 ja 18 ei ole piipun pisteissä. Luokkaa 18 ei ole aineistossa lainkaan, ja luokkaan 7 kuuluvat 678 pistettä poistetaan jo (luokka 18 lisättiin poistettaviin luokkiin varmuuden vuoksi).
4. Pyydetty "yksinäisten pisteiden" suodatus vastaa jo olemassa olevaa kohinasuodatusta, joka on pyydettyä tiukempi (vähintään 3 pistettä 12 m:n kuutiossa). Piippu läpäisee sen, joten suodatus ei poista piikkiä eikä sitä pidä poistaa.
5. Piippua ei voinut varmentaa ulkopuolisesta lähteestä (verkkohaku ei tuottanut korkeutta). Korkeus 100,7 m perustuu pistepilveen.

Koska suodatuksen lopputulos ei muuttunut, pintamallia ja tiiliä ei muutettu. Ne ajettiin tyhjästä ennen tätä tarkistusta samoilla suodattimilla. Uudelleen ajettiin rakennuskorkeudet, maamerkit, tarkistuskuvat ja tarkistus sekä kuvaus. Piipun todiste on tallennettu `maamerkit.json`:iin (Tampellan piippu) ja `tarkistus_1b.json`:iin (`4b_siluetin_piikki`). Piippu on nyt myös numeroituna maamerkkinä 6 siluettikuvassa.

## 5. Siluettikuvat

1. `siluetti_naistenlahdelta.png`: näköpiste E 327 740, N 6 823 980 (Naistenlahden poukama, 2 m järven pinnan yläpuolella eli 97,42 m N2000), suunta 172°, kulma 160°. Näköpiste on valittu ajamalla vaihe `nakopiste`, joka hakee vedessä olevat pisteet, joista piiput, kuljetin ja Näsinneula näkyvät kaikki säteenjäljityksellä (2 309 ehdokasta, kaikki 8 kohdetta näkyi monesta). Piiput ovat suunnassa 99–104°, kuljetin 109–114° ja Näsinneula 239°, joten niiden välillä on 4,8° ja 125° eroa. Numerot: 1 Näsinneula, 2–3 piiput, 4 kattilarakennus, 5 kuljetinsilta, 6 Tampellan piippu, 7 Tampellan tehdas (suurin rakennus), 8 Särkänniemi (korkein ehdokaslaite), 9 Mustalahden satama (suurin rakennus). Kohteet 7 ja 9 jäävät rantapuuston ja rakennusten taakse ja on merkitty harmaana "piilossa". Kohde 8 on rajalla.
2. `siluetti_maarittelyn_piste.png`: määrittelyn esimerkkipiste E 328 500, N 6 824 500, suunta 180°, kulma 120°. Piiput, Tampellan piippu ja Näsinneula näkyvät, mutta kuljetin ja kattilarakennus jäävät lähirannan puuston ja kattilarakennuksen taakse (korkeuskulma 1,4° ja puuston 5,7°). Siksi pääkuva otettiin poukamasta.
3. Pystyakseli on vääristetty (40–46 px/° ja vaaka 15–20 px/°), jotta matalat muodot erottuvat. Asteikko on kuvassa.

## 6. Mitä oletettiin ja mikä ei onnistunut

1. Vuoden 2008 aineisto on vanhempi kuin maastotietokanta 2025, ks. kohta 3.
2. Näsinneulan huippu ja ohuet piippujen yläosat ovat harvan pistetiheyden vuoksi alarajoja.
3. Tampellan tehtaan, Särkänniemen ja Mustalahden kohteet on poimittu rajauksilla (katunimet, laatikot ja etäisyys vedestä), joita ei ole varmennettu rakennuskohtaisesti. Särkänniemen laitteita ei tunnistettu nimeltä.
4. Näsinneulan varsi on mitattu vain yhdeltä puolelta, joten halkaisija on suuntaa antava.
5. Kriteeri 5 ei täyty: kaksi poikkeamaa Lielahdessa. DEM:n keilausvuotta ei tarkistettu.
6. Kriteeri 1 ei täyty lukuna.

## 7. Siirtomäärä ja ajoaika

Täysi ajo tyhjästä (`python3 laser.py --puhdas-lataus`) kesti 288 s, kun mukaan lasketaan uudelleenlataus. Lataus on 191,3 Mt (10 laz-tiedostoa ja metatietotiedostot) ja kesti 30 s. Vaiheet: alue 4,9 s, ruudut 78,4 s, lataus 30,4 s, korkeus 5,8 s, pisteet 55,3 s, pinta 18,5 s, rakennukset 7,5 s, maamerkit 13,5 s, tiilet 61,1 s, kuvat 11,5 s, tarkistus 8,1 s, kuvaus 0,2 s. Tuotokset: `pinta.pmtiles` 15,4 Mt, `rakennuskorkeudet.json` 1,25 Mt, `maamerkit.json` 0,13 Mt, `tarkistus_1b.json` 21 kt ja `aineisto_1b.json` 9 kt. Kuvat ovat yhteensä noin 13 Mt, eikä niitä julkaista.

## 8. Mitä tietoputkeen pitää lisätä

1. Riippuvuudet: `pip install laspy lazrs` (Ubuntu 24.04:n python3, jossa on GDAL-sidokset). Käytetyt versiot: laspy 2.7.0 ja lazrs 0.8.2. Muita uusia riippuvuuksia ei ole.
2. Työnkulkuun askel `python3 laser.py` vaiheen 1 ajon jälkeen samassa hakemistossa (se lukee `tyo/aoi.gpkg`, `dem2.vrt`, `dem10.tif` ja `rajattu.gpkg`). Muussa hakemistossa osoitetaan ympäristömuuttujalla `LASER_VAIHE1_TYO`. Ajoaika on noin 5 minuuttia, joten ajon aikaraja ei ole ongelma.
3. Laz-ruutujen välimuisti (`tyo/laser/raaka/laz`, 196 Mt) kannattaa ottaa GitHubin välimuistiin, jolloin lataus (30 s) jää pois.
4. Julkaistavat tiedostot hakemistosta `ulos/`: `pinta.pmtiles`, `rakennuskorkeudet.json`, `maamerkit.json` ja `aineisto_1b.json` (tuotokset, sha256 ja lähdemerkintä). Kuvat ja `tarkistus_1b.json` jäävät artefakteiksi. `aineisto_1b.json`:n lähdemerkintä tulee lisätä sivuston lähdemerkintöihin ja vaiheen 1 `aineisto.json`:n `lahdemerkinta_yhteensa`-kenttään.
5. `rakenna.py`:n `rakennus`-kerrokseen yhdistetään `rakennuskorkeudet.json` kentän `fid` mukaan (sama kuin `tee_rakennus`-kierroksen järjestysnumero). Kentät `h_p90`, `h_max` ja `ei_keilattu` otetaan mukaan. Simulaattorin on käytettävä korkeutena `h_p90`:tä vain, kun `ei_keilattu` ei ole 1, muuten kerrosluokasta arvioitu korkeus.
6. `pinta.pmtiles` on lisättävä Reittikartan tasoiksi samalla tavalla kuin `maasto.pmtiles` (Terrain-RGB, kvantti 0,1 m Mapbox-koodauksessa, tasot 12–16, vain rantavyöhyke).
7. Laajennus muulle järvelle: vaihda `ALUE_LAATIKKO` ja `VYOHYKE_M`. Ruudut tulevat automaattisesti indeksistä, mutta ruutuja on satoja, joten kannattaa ajaa osissa.
8. Maamerkkien alkuarviot (`NASINNEULA_ALKU`, `VOIMALAITOS_ALKU`, `TAMPELLA_KADUT`, `TAMPELLA_PIIPPU_ALKU`) ovat asetuksissa. Vuoden 2008 jälkeen rakennetut rakenteet eivät tule mukaan ilman uudempaa aineistoa.

## 9. Tiedostot

- `/home/claude/aineisto-1b/laser.py`
- `/home/claude/aineisto-1b/ulos/pinta.pmtiles`, `rakennuskorkeudet.json`, `maamerkit.json`, `aineisto_1b.json`, `tarkistus_1b.json`
- `/home/claude/aineisto-1b/ulos/tarkistuskuvat/`: `varjostus_koko_alue.png`, `lahikuva_nasinneula.png`, `lahikuva_voimalaitos.png`, `lahikuva_ranta_tampella.png`, `siluetti_naistenlahdelta.png`, `siluetti_maarittelyn_piste.png`
- Välitulokset: `/home/claude/aineisto-1b/tyo/laser/` (mm. `pinta_1m.tif`, `nakopiste.json`, `loki.json`)
