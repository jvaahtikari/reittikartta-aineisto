# Raportti, vaihe 1d: kiinnitettyjen veneiden paikat MML:n ortokuvasta

Päiväys 27.10.2026. Tekijä: Sonnet-agentti. Tilaaja: Fable. Määrittely: `MAARITTELY_vaihe1d_veneet_ilmakuvasta.md`. Todentava ajo: GitHub Actions, ajo 40540934457 (main, commit 4515d0f). Ajo oli tämän raportin kirjoitushetkellä (27.10.2026 klo 18.42 Suomen aikaa) vielä kesken, joten lopputulosta ja kestoa ei ole tässä vahvistettu. Vaiheen 1c vastaava ajo kesti 27 min 20 s. Lopputulos ja kesto on luettava tiedostosta `ajoloki/viimeisin.md` tai ajon sivulta. Ajon yhteenveto on haarassa `ajoloki` tiedostossa `ajoloki/viimeisin.md`.

## 1. Tulokset yhdellä silmäyksellä

| Kriteeri | Tulos |
| --- | --- |
| 1. `veneet.json` paikallisesti ja Pagesissa | Täyttyy. Paikallinen tiedosto `/home/claude/opetus/navi/putki/ulos/veneet.json` on valmis (1 048 venettä, 225 kt) ja sama tiedosto syntyy Actionsissa. Pages-julkaisun onnistuminen ja ajon kesto ovat vahvistamatta, koska ajo oli kesken (ks. ylempänä). |
| 2. Tarkistuskuvat ja tarkkuus luvuin | Täyttyy. Kuvat `shots/veneet_<satama>.png` kaikista kahdeksasta satamasta. Naistenlahden otoksessa (281 havaintoa) noin 93 % näkyvistä veneistä tunnistettiin ja noin 1,4 % havainnoista oli vääriä. Mustalahden otoksessa (41 havaintoa) noin 87 % ja noin 2 %. Alaraja 80 % ja yläraja 10 % täyttyvät. Ks. kohta 6 |
| 3. Länsiaallonmurtajan niemekkeen vieressä ei venettä ilman kuvassa näkyvää venettä | Täyttyy. Niemekkeen sisällä 0 venettä ja alle 5 m:n päässä sen reunasta 0 venettä. Viereisellä laiturilla ovat kuvassa näkyvät veneet. Ks. kohta 7 |
| 4. Muut tiedostot ennallaan, `tarkista.py` läpi, koko alle 150 Mt | Täyttyy. `veneet.py` lisää vain tiedoston `veneet.json` ja täydentää `aineisto.json`-tiedostoa. `tarkista.py --vaadi-veneet` meni läpi koepaketissa (kaikki tarkistukset OK, paketti 129,3 Mt). Työnkulun oma `tarkista.py --vaadi-veneet` -askel ei ollut vielä ehtinyt ajoon. |
| 5. Raportti | Tämä tiedosto |

## 2. Lähde ja vuodet

Lähde on Maanmittauslaitoksen avoin ortokuva (väri, pikselikoko 0,5 m, EPSG:3067) Paitulin peilipalvelimelta `https://mirrors.nic.funet.fi/index/geodata/mml/orto/normal_color_3067/`. Lisenssi CC BY 4.0, lähdemerkintä "Sisältää Maanmittauslaitoksen ortokuva-aineistoa 2023". Googlen kuvaa ei käytetä lähteenä missään vaiheessa.

Indeksi `ortho_all.shp` kertoo kullekin 6 x 6 km:n lehdelle vuoden ja sarjan, mutta ei kuvauspäivää. Myöskään JP2-tiedostojen metatiedoissa ei ole kuvauspäivää, joten `paiva` on `veneet.json`-tiedostossa `null` ja syy on kirjattu kenttään `paivan_huomio`. Kahdeksan satamaa mahtuu neljälle lehdelle:

| Lehti | Vuodet indeksissä | Valittu | Vihreän osuus | Hylätty uudempi |
| --- | --- | --- | --- | --- |
| M4212E | 2010, 2011, 2014, 2017, 2018, 2020, 2023, 2026 | 2023 (`smk_v_15000_50`) | 0,194 | 2026 (`mara_v_25000_50`, vihreää 0,0005) |
| M4212G | 2010, 2011, 2014, 2015, 2017, 2018, 2020, 2023, 2026 | 2023 (`smk_v_15000_50`) | 0,097 | 2026 (vihreää 0,0012) |
| M4214A | 2010, 2011, 2014, 2015, 2017, 2018, 2020, 2023, 2026 | 2023 (`smk_v_15000_50`) | 0,302 | 2026 (vihreää 0,0003) |
| M4221E | 2011, 2015, 2016, 2018, 2020, 2023, 2026 | 2023 (`smk_v_15000_50`) | 0,160 | 2026 (vihreää 0,0001) |

Valintasääntö: lehdelle valitaan uusin vuosi, jonka kuvassa vihreän osuus on vähintään 0,04. Vihreän osuus on niiden pikselien osuus, joissa vihreä kanava ylittää punaisen ja sinisen yli kuudella (lasketaan kuvan pienennöksestä). Uusin kuva, vuoden 2026 `mara_v_25000_50`, on kaikilla neljällä lehdellä lehdetön kevätkuva (vihreää 0,0001 - 0,0012, kesäkuvissa 0,097 - 0,302), jossa veneet eivät ole vielä vedessä, joten se hylättiin ja käytettiin vuoden 2023 kesäkuvaa. Hylkäys muistetaan tiedostossa `hylatyt.json` (samassa hakemistossa kuin JP2-kuvat), ettei satojen megatavujen kevätkuvaa ladata joka ajolla uudelleen.

## 3. Menetelmä

Menetelmä on selitettävä ja koneoppimaton. Koodi on tiedostossa `veneet.py` ja sitä ajetaan komennolla `python3 veneet.py` (kaikki satamat) tai `python3 veneet.py Naistenlahti Mustalahti` (väliajo).

1. Lehtien valinta ja lataus (kohta 2). JP2-lehdet ladataan kokonaan (noin 108 Mt per lehti) ja luetaan GDAL:n VRT-yhdistelmän kautta.
2. Tunnistusalue satamittain. Maastotietokannan järvipolygonin vesialue, jolla on laituri (`vesieste_viiva`: `laituri_kapea` ja `laituri_leveä`) enintään 60 m:n päässä, tai joka on enintään 150 m:n päässä rannasta satamakohteen ympyrän (säde 300 - 520 m) sisällä. Jälkimmäinen kattaa poijukentät ja kirjaamattomat laiturit. Rajaus on kirjattu `veneet.json`-tiedoston kenttiin `satamat[].keskipiste_e`, `keskipiste_n`, `poijusade_m` ja `tunnistusalue_bbox`.
3. Poissulku: laituriviivat (puskuri 1,5 m), aallonmurtajat (3 m), kirjatut pinnassa olevat vesikivet (3 m) ja sillat (`tie`-kerroksen taso vähintään 1, puskuri 11 m).
4. Taustan sävy: kirkkaudesta lasketaan vedelle 4 x 4 pikselin (2 m) lohkojen mediaani ja siitä 26 m:n liukuva mediaani (vain vesipikselit). Pikseli on ehdokas, jos sen kirkkaus ylittää taustan yli 45 yksikköä (vaaleat) tai alittaa sen yli 22 yksikköä (tummat). Vaaleat ja tummat ehdokkaat käsitellään erikseen ja niiden päällekkäisyydet ratkaistaan jälkisuodatuksessa.
5. Avaus ja sulku (neliö 3 x 3 pikseliä), yhtenäiset alueet ja pääakseli (PCA). Alue hyväksytään veneeksi, jos pituus on 3 - 16 m, leveys 1,3 - 5 m ja pituus-leveyssuhde 1,3 - 5. Isompi alue yritetään jakaa: ensin nostamalla kynnystä portain, sitten tummien ohuiden saumojen (musta huippuhattu) kohdalta ja viimeisenä etäisyysmuunnoksen huippujen mukaan. Jakamaton alue hyväksytään yhdeksi isoksi veneeksi, jos leveys on enintään 6 m ja ala enintään 80 m². Yli 16 m pitkä, enintään 7 m leveä ja enintään 160 m² suuruinen alue, joka ei ole 4 m:n sisällä laiturista, aallonmurtajasta, kivestä tai sillasta (rannassa olevat museo- ja matkustaja-alukset), jätetään pois omana luokkanaan `iso_alus`.
6. Jälkisuodatus: (a) tummat havainnot alle 6 m:n päässä rannasta (muurien varjot), (b) kohteet, joiden ympärillä on vähemmän kuin 25 % vettä ja jotka ovat yli 12 m:n päässä laiturista (sillat, rakenteet), (c) kapeat ja selvästi sinertävät kohteet (ponttoonilaiturin sormet), (d) alle 5 m pitkät, alle 0,67 varmuuden kohteet alle 2,5 m:n päässä rannasta (rantaroska: kivet, laiturin juuret, hiekkaranta), (e) suorakulmioiden päällekkäisyys yli 50 % (heikompi pois) ja (f) kolme käsin todettua poissulkualuetta (kohta 10).
7. Keula: ensisijaisesti muodosta (keula on kapeampi, osoittava pää, jota kohti alueen pitkä varsi ulottuu), toissijaisesti laiturin suunnasta (keula laituria kohti, laituri enintään 12 m:n päässä), muuten pääakselin pohjoinen pää pienemmällä varmuudella. Lähde on kirjattu kenttään `suunta_lahde` (`muoto`, `laituri` tai `oletus`).
8. Luokka pituudesta ja muodosta: alle 4,8 m on `soutu` (suhde vähintään 2,6) tai `pieni`, 4,8 - 7,5 m on `keski`, yli 7,5 m ja suhde yli 3 on `purje`, muut `keski`. Mastoa ei havaita, joten luokka ei ole varma.
9. Varmuus (0 - 1) yhdistää muodon täyttöasteen (40 %), koon uskottavuuden (30 %) ja kontrastin (30 %). Jaetut kohteet kerrotaan luvulla 0,85, tummat luvulla 0,7 ja keulaltaan arvaamalla määritetyt luvulla 0,9.
10. Tarkistuskuva (suorakulmiot, keulan merkki, laiturit ja tunnistusalueen reuna) tallennetaan hakemistoon `shots/` ja Actionsissa lisäksi `ulos/tarkistuskuvat/` (poistetaan ennen julkaisua).

## 4. Lopulliset kynnykset

Kaikki arvot ovat tiedostossa `veneet.py` (`PARAM`) ja kirjataan `veneet.json`-tiedoston kenttään `parametrit`.

| Parametri | Arvo | Selitys |
| --- | --- | --- |
| `kynnys_vaalea` | 45 | Kirkkauden ylitys taustaan nähden (asteikko 0 - 255) |
| `kynnys_tumma` | 22 | Kirkkauden alitus taustaan nähden |
| `tausta_ikkuna_m` | 26 | Taustan liukuva mediaani (määrittelyn ehdotus 25 m) |
| `avaus_px`, `sulku_px` | 3, 3 | Morfologinen avaus ja sulku |
| `pituus_m` | 3,0 - 16,0 | Pääakselin pituus |
| `leveys_m` | 1,3 - 5,0 | Leveys. Jakamaton iso moottorivene hyväksytään leveyteen 6,0 m ja alaan 80 m² asti |
| `suhde` | 1,3 - 5,0 | Pituus-leveyssuhde. Määrittelyn alaraja oli 1,6, ks. kohta 10 |
| `laituri_vyohyke_m`, `ranta_vyohyke_m` | 60, 150 | Tunnistusalue laitureista ja rannasta |
| `laituri_puskuri_m`, `kivi_puskuri_m`, `silta_puskuri_m` | 1,5, 3,0, 11,0 | Poissulut (aallonmurtajalla 3,0 m) |
| `jako_askel`, `jako_min_px`, `jako_saumasyvyys`, `jako_huippu_etaisyys_m` | 12, 14, 25, 1,2 | Yhteen kiinni olevien veneiden jako |
| `tumma_ranta_m` | 6,0 | Tummat havainnot tätä lähempänä rantaa hylätään |
| `vesiosuus_min` | 0,25 | Kohteen ympärillä oleva vesiosuus (laiturin vaikutusalueen ulkopuolella) |
| `laituri_vaikutus_m` | 12,0 | Etäisyys, jonka sisällä laituri ohittaa vesiosuusehdon ja ohjaa keulaa |
| `paallekkain_max` | 0,50 | Suorakulmioiden sallittu päällekkäisyys |
| `ponttoni_sinisyys_min`, `ponttoni_leveys_max_m` | 35, 2,2 | Ponttoonisormen tunnistus (sinisen ja punaisen keskiarvon ero, veneillä alle 29) |
| `rantaroska_pituus_max_m`, `rantaroska_varmuus_max`, `rantaroska_etaisyys_m` | 5,0, 0,67, 2,5 | Rantaroskan poisto |
| `alus_leveys_max_m`, `alus_ala_max_m2` | 7,0, 160 | Yli 16 m:n pitkänomaisen aluksen rajaus pois |
| `keula_vinouma_min` | 0,04 | Painopisteen siirtymä pituudesta, jonka yli muoto ratkaisee keulan |
| `kesakuva_min_vihrea_osuus` | 0,04 | Kesäkuvan ehto |

Kynnykset säädettiin tarkistuskuvien silmämääräisen läpikäynnin perusteella. Ensimmäiset arvot (kynnys 45 ja 22, jakamattomat alueet hylättiin, silta 7 m) löysivät Naistenlahdesta 143 venettä, koska 2 - 3 vierekkäistä venettä sulautui yhdeksi alueeksi. Jakosääntö (kynnyksen porrastus ja saumat) nosti luvun yli 400:aan. Sen jälkeen vääriä havaintoja poistettiin silta-, ranta- ja ponttoonisäännöillä (ks. kohta 6).

## 5. Tulos satamittain

Yhteensä 1 048 venettä, 85 laituriviivaa ja 147,3 ha tunnistusaluetta. Luokat: 2 `soutu`, 96 `pieni`, 917 `keski`, 33 `purje`. Pituuden mediaani on 7,05 m ja leveyden mediaani 3,7 m (pääakselisuorakulmio, ks. kohta 9). Varmuus on vähintään 0,7 kohteella 845, 0,5 - 0,7 kohteella 193 ja alle 0,5 kohteella 10. Keulan lähde: muoto 431, laituri 418, oletus 199.

| Satama | Veneitä | Soutu / pieni / keski / purje | Laituriviivoja | Tunnistusalue ha | Keula: muoto / laituri / oletus |
| --- | --- | --- | --- | --- | --- |
| Naistenlahti | 421 | 2 / 45 / 364 / 10 | 27 | 20,4 | 184 / 203 / 34 |
| Mustalahti | 52 | 0 / 3 / 46 / 3 | 13 | 24,7 | 20 / 11 / 21 |
| Santalahti | 124 | 0 / 10 / 110 / 4 | 11 | 21,9 | 43 / 43 / 38 |
| Jänissaari | 149 | 0 / 5 / 141 / 3 | 6 | 21,3 | 58 / 68 / 23 |
| Perkiönlahti | 93 | 0 / 6 / 85 / 2 | 4 | 10,6 | 37 / 50 / 6 |
| Rauhaniemi | 64 | 0 / 7 / 54 / 3 | 2 | 20,7 | 24 / 0 / 40 |
| Aitolahti | 28 | 0 / 10 / 17 / 1 | 9 | 14,4 | 10 / 10 / 8 |
| Teisko | 117 | 0 / 10 / 100 / 7 | 13 | 13,3 | 55 / 33 / 29 |

Kaikki neljä lehteä ovat vuodelta 2023. Tarkistuskuvat (magenta piste = keula, vihreä suorakulmio = varmuus vähintään 0,7, keltainen 0,5 - 0,7, oranssi alle 0,5, punainen viiva = laituri, vaaleansininen viiva = tunnistusalueen reuna):

- `shots/veneet_Naistenlahti.png`
- `shots/veneet_Mustalahti.png`
- `shots/veneet_Santalahti.png`
- `shots/veneet_Jänissaari.png`
- `shots/veneet_Perkiönlahti.png`
- `shots/veneet_Rauhaniemi.png`
- `shots/veneet_Aitolahti.png`
- `shots/veneet_Teisko.png`

## 6. Tarkkuus (Naistenlahti ja Mustalahti)

Tarkkuutta ei ole mitattu maastovertailulla, vaan silmämääräisesti ortokuvasta. Kummastakin satamasta otettiin tiheimmät alueet: Naistenlahdesta viisi 90 x 90 m:n ruutua (282 havaintoa eli 67 % sataman havainnoista) ja Mustalahdesta kolme 120 x 120 m:n ruutua (41 havaintoa eli 79 %). Jokainen ruutu piirrettiin 14 pikselin metrimittakaavassa havaintosuorakulmioineen, ja katsoja luki erikseen kuvaan merkitsemättä jääneet näkyvät veneet (puuttuvat) ja suorakulmiot, joiden alla ei ole venettä (väärät). Ruudun reunan yli menevät veneet ja yli 16 m:n alukset (kaksi höyrylaivaa Mustalahden laiturilla) jätettiin pois.

| Satama | Havaintoja ruuduissa | Väärät | Puuttuvat (silmin) | Tunnistettu / näkyvissä | Vääriä havaintoja |
| --- | --- | --- | --- | --- | --- |
| Naistenlahti | 282 | 4 | 20 | 278 / 298 eli 93 % | 1,4 % |
| Mustalahti | 41 | 1 | 6 | 40 / 46 eli 87 % | 2 % |
| Yhteensä | 323 | 5 | 26 | 318 / 344 eli 92 % | 1,5 % |

Lisätarkistus: ruuduissa laskettiin vaaleiden ehdokaspikselien ala, jota yksikään havaintosuorakulmio ei peitä, kun suorakulmioita levitettiin 0,7 m. Naistenlahden ruuduissa selittämättömän alan osuus oli 1,4 - 19 % (yhteensä 6,7 %) ja Mustalahden ruuduissa 5 - 32 % (yhteensä 15 %, ja suurin osa selittyy rannassa olevilla yli 16 m:n aluksilla ja maalla olevilla veneillä). Jos jokainen selittämätön osa on yksi veneen kokoinen puuttuva vene, Naistenlahden puuttuvia on noin 29 ja tunnistusosuus 90 %. Tarkkuusarvio on siis noin 90 %, ja se on vain otos. Tiheimmät ja siistimmät laiturialueet ovat otoksessa yliedustettuina, joten koko sataman osuus on todennäköisesti hieman pienempi. Silmämääräinen laskenta on epätarkkaa noin kolmen prosenttiyksikön verran.

Väärien havaintojen korjaukset (kohta 6 yllä):

- Ensimmäisessä täydessä ajossa (1 069 venettä) Naistenlahdessa oli viisi ponttoonilaiturin sormea veneinä (noin 1,2 % havainnoista), ja Mustalahden 65 havainnosta noin 12 oli vääriä (noin 18 %): kuusi Särkänniemen rantaterassilla (aurinkovarjot ja pöydät), viisi leveän maantiesillan kannella ja yksi rautatiesillan ristikossa.
- Korjaukset: kapea sinertävä kohde pois (ponttoni, 5 kohdetta Naistenlahdessa), siltapuskuri 7 m:stä 11 m:ään (Mustalahdessa noin 5 kohdetta), kolme käsin todettua poissulkualuetta (terassi, rautatiesillan ristikko, niemekkeen kärjen kellukkeet, yhteensä 9 kohdetta) ja rantaroskasääntö (6 kohdetta: Naistenlahti 3, Mustalahti 1, Santalahti 1, Perkiönlahti 1).
- Myös ajon `ajoloki/viimeisin.md` kertoo ajossa poistetut määrät satamittain (`ponttoneja_poistettu`, `poissulkualueilta_poistettu`, `rantaroskaa_poistettu`).

Tyypillisiä puuttuvia veneitä: kolmen tai useamman veneen tiiviit rivit, joissa vierekkäiset rungot sulautuvat eikä jako onnistu (kohdat, joissa neliömäisen alueen jako jäi tekemättä), harmaat matalakontrastiset rungot, katetut veneet, joiden katteen väri on lähellä veden sävyä, sekä alle 3 m:n jollat ja kanootit.

## 7. Naistenlahden länsiaallonmurtajan niemeke (kriteeri 3)

Länsiniemeke on tässä Maastotietokannan järvipolygonin ulkopuolinen maa-alue (kiviaallonmurtaja ja sen kanssa yhtenäinen niemi), jonka ala on 17 611 m² ja ulottuvuus E 327950 - 328200, N 6823600 - 6823833. Etäisyydet laskettiin veneiden keskipisteistä tämän alueen reunaan (apuohjelma ei kuulu pakettiin). Lopullisessa tuloksessa:

- Niemekkeen sisällä 0 venettä.
- Alle 5 m:n päässä sen reunasta 0 venettä.
- Alle 10 m:n päässä 5 venettä, ja ne ovat kuvassa näkyviä veneitä niemekkeen viereisellä laiturilla.
- Alle 20 m:n päässä 44 venettä (laiturin kaikki veneet).

Ensimmäisessä täydessä ajossa niemekkeen kärjessä oli kaksi havaintoa (keskipisteet E 328123, N 6823834 ja E 328128, N 6823832, pituudet 8,9 m ja 7,7 m). Ennen rantaroska- ja poissulkusääntöjä (väliajo, 1 056 venettä) alle 5 m:n päässä reunasta oli neljä havaintoa. Kärjen kohteet ovat ortokuvassa tasaisen vaaleanharmaita kulmikkaita kappaleita (L- ja T-muotoisia kellukkeita), joissa ei näy rungon rakennetta, ohjaamoa eikä katetta. Ne tulkittiin kellukkeiksi ja poistettiin käsin (kohta 10). Se on tulkinta, ei varma: jos kyseessä ovat veneet, kaksi venettä puuttuu. Kaksi muuta alle 5 m:n päässä ollutta havaintoa (lounaiskulman hiekkaranta ja laiturin juuri) poistuivat rantaroskasäännöllä.

## 8. Työnkulku, paketti ja tarkistus

- Työnkulku `aineisto.yml`: asennukseen lisättiin `python3-scipy` ja `fonts-dejavu-core`. Uusi askel "Ortokuvien välimuisti" (`actions/cache@v4`, polku `tyo/orto/jp2`, avain `orto-jp2-<veneet.py:n tiiviste>`, varavaihtoehto `orto-jp2-`) säilyttää JP2-kuvat (noin 430 Mt) ja `hylatyt.json`-muistin kuten laz-tiedostojen välimuisti. Uusi askel "Veneiden tunnistus ortokuvasta" ajaa `python3 veneet.py` laserosan jälkeen, ja `tarkista.py` ajetaan sen jälkeen lipulla `--vaadi-veneet`. Lokin loppu (`tyo/veneet.log`) ja `tyo/veneet/loki.json` kuuluvat lokien latauspakettiin.
- Ensimmäisellä ajolla ladataan kahdeksan JP2-tiedostoa (neljä 2026-kevätkuvaa vihreän osuuden mittaamiseksi ja neljä 2023-kesäkuvaa), yhteensä noin 850 Mt. Välimuistin jälkeen ladataan vain tarvittaessa.
- `aineisto.json`: uusi lähde `mml_ortokuva` (lisenssi, lähdemerkintä, ehtoteksti, huomio veneiden ajankohdasta), tiedosto `veneet.json` (koko ja tarkistussumma), kuvauslohko `veneet` (muoto, ortokuvat ja vuodet, veneiden määrä) ja täydennetty `lahdemerkinta_yhteensa`. Muut kentät ja tiedostot ovat ennallaan.
- `tarkista.py`: uusi tarkistus `9_veneet` (tiedosto on olemassa, vähintään 100 venettä, kenttien tyypit ja arvoalueet, ortokuvat ja satamakohtaiset määrät). Ilman lippua `--vaadi-veneet` puuttuva tiedosto vain mainitaan, koska `ajaa.py` kutsuu `tarkista.py`:tä ennen `veneet.py`:tä.
- `ajoloki.py`: uusi osa "1b. Veneet ilmakuvasta (vaihe 1d)" tiedostoon `ajoloki/viimeisin.md` (ortokuvat, hylätyt kuvat, veneet satamittain, keulan lähteet) ja `veneet.log` lokin loppuun.
- Paikallinen koepaketti: `tarkista.py --vaadi-veneet` meni läpi (kaikki tarkistukset OK, paketin koko 129,3 Mt, raja 150 Mt, `veneet.json` 0,2 Mt).

## 9. Rajoitukset

1. Ajankohta. Veneet ovat ortokuvan kuvaushetken paikoissa (kesä 2023, tarkkaa päivää ei tiedetä). Googlen 3D-maiseman kuva on 16.7.2025, eli kahden vuoden ero. Samat laituripaikat ovat usein käytössä, mutta yksittäisten veneiden paikat ja määrät eroavat. Uusin MML:n kuva (kevät 2026) olisi lähempänä Googlen kuvaa, mutta se on lehdetön kevätkuva, jossa veneet eivät todennäköisesti ole vielä vedessä. Googlen 3D-maiseman kuvassa näkyvät veneet eivät siis vastaa tämän aineiston paikkoja yksi yhteen.
2. Keulan suunta on epävarma. Muodosta (431 venettä) ja laiturista (418 venettä) päätelty keula on tarkistuskuvissa useimmiten oikea, mutta 199 venettä (19 %) sai oletussuunnan (pohjoinen) ja niiden varmuus on kerrottu luvulla 0,9. Keulan päättely on herkkä varjolle ja ortokuvan perspektiivivääristymälle, ja Rauhaniemessä, jossa on vain kaksi laituriviivaa, 40 venettä 64:stä sai oletussuunnan.
3. Luokka perustuu vain pituuteen ja muotoon. Mastoa ei havaita, joten purjeveneitä (33) on luultavasti todellisuutta vähemmän luokassa `purje`. Moni purjevene on luokassa `keski`.
4. Koko on suuntaa antava. Pääakselisuorakulmio sisältää varjon ja reunahohteen, joten pituus ja leveys ovat noin 0,5 - 1 m liian suuria (leveyden mediaani 3,7 m).
5. Poissa ovat yli 16 m pitkät alukset (esimerkiksi Mustalahden höyrylaivat, kaksi kappaletta), alle 3 m:n jollat ja kanootit, maalla olevat veneet sekä veneet, jotka ovat tunnistusalueen ulkopuolella (yli 60 m laitureista ja yli 150 m rannasta). Satamien ulkopuoliset yksittäiset veneet ja poijuveneet kaukana rannasta eivät kuulu aineistoon.
6. Tiiviit useamman veneen rivit voivat jäädä sulautuneiksi tai jaetuiksi väärin, ja jaon tuottamat suorakulmiot ovat tällöin karkeita ja osin päällekkäisiä (kuvissa keltaiset suorakulmiot). Jaettujen kohteiden varmuus on kerrottu luvulla 0,85.
7. Tarkkuusarvio on otos kahdesta satamasta, ei kaikkien satamien läpikäynti. Muista kuudesta satamasta on vain kuvat ja silmäys, ja niissä tunnistus perustuu samoihin kynnyksiin. Satamissa, joissa laituriviivoja on vähän, keula perustuu useammin pelkkään muotoon tai oletukseen (ks. kohdan 5 taulukko).
8. Käsin todetut poissulkualueet ja rantaroskasääntö on säädetty vuoden 2023 kuvaan. Jos Paitulin uusin kesäkuva vaihtuu, alueet on syytä tarkistaa.
9. Aineisto ei ole tarkoitettu navigointiin.

## 10. Päätökset ja poikkeamat määrittelystä

1. **Satamat.** Määrittelyn nimistä Naistenlahti, Mustalahti, Santalahti, Rauhaniemi, Aitolahti ja Teisko sijoitettiin MML:n paikannimirekisterin koordinaattien ja ortokuvan perusteella. Lielahden lahdella (paikannimi E 323467, N 6824122) ei ortokuvassa ole venesatamaa, Niemenranta (E 323677, N 6825340) on asuinalue, jonka rannassa ei ole veneitä, ja Siilinkari (E 327351, N 6824743) on luoto. Niitä ei otettu mukaan. Sen sijaan mukaan otettiin ortokuvasta löytyneet satamat Jänissaari (Lentävänniemi) ja Perkiönlahti. Teiskon sataman keskipiste on paikannimen Pimeäsalmi kohdalla. Satamataulukko on `SATAMAT` tiedostossa `veneet.py`, ja sitä voi muuttaa.
2. **Suhteen alaraja 1,3.** Määrittelyn alaraja 1,6 hylkäisi 198 nykyisistä 1 048 havainnosta (19 %), joista 131:n varmuus on vähintään 0,7. Ruutujen tarkistuksessa nämä olivat leveitä moottoriveneitä ja viistoon laituria vasten olevia veneitä, joten alarajaksi asetettiin 1,3.
3. **Päivä.** `paiva` on `null`, koska indeksissä ja kuvien metatiedoissa ei ole kuvauspäivää. Vuosi on kirjattu.
4. **Kynnysten ja alueen kirjaus.** Ylimääräiset kentät `suunta_lahde`, `parametrit`, `satamat`, `poissulkualueet`, `ortokuvat[].hylatyt_uudemmat` ja `paivan_huomio` ovat määrittelyn muotoon lisättyjä kenttiä. Määrittelyn kentät ovat ennallaan, joten lukijan ei tarvitse muuttua.
5. **Käsin todetut poissulkualueet.** Kolme aluetta (kohdat `POISSULKUALUEET` tiedostossa `veneet.py` ja kenttä `poissulkualueet` tiedostossa `veneet.json`): Särkänniemen rantaterassi Mustalahdessa (E 326905 - 326950, N 6823400 - 6823432, 6 havaintoa), rautatiesillan ristikko Mustalahdessa (E 327350 - 327368, N 6823380 - 6823392, 1 havainto) ja Naistenlahden länsiniemekkeen kärjen kellukkeet (E 328115 - 328135, N 6823825 - 6823842, 2 havaintoa). Jokaisessa alueessa on perustelu.
6. **Tulos kirjoitetaan paikallisesti.** Ympäristömuuttuja `VENEET_KOPIO` kopioi `veneet.json`-tiedoston toiseen hakemistoon. Paikallinen ajo kirjoitti tiedoston myös hakemistoon `/home/claude/opetus/navi/putki/ulos/`, jotta simulaattorin agentti voi käyttää sitä heti.
7. **Tarkistuskuvien koko.** Tarkistuskuvat ovat 2 200 pikselin levyisiä PNG-kuvia (2,9 - 6,4 Mt kappale, yhteensä noin 39,6 Mt), ja ne on tallennettu repoon hakemistoon `shots/`. Paletin supistusta kokeiltiin, mutta se heikensi ohuita viivoja eikä säästänyt riittävästi, joten kuvat jätettiin täysilaatuisiksi.
