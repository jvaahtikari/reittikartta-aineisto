# Määrittely, vaihe 1b: laserkeilaus rantavyöhykkeeltä, rakennusten korkeudet ja maamerkit

Päiväys 24.10.2026. Tekijä: Sonnet-agentti. Tilaaja: Fable. Tausta: vaiheen 1 tietoputki (`/home/claude/reittikartta-aineisto/`, raportti `RAPORTTI_vaihe1.md`) ja suunnitelman vaihe 3 (kuljettajan näkymä). Tämä vaihe tehdään rinnakkain vaiheen 2 kanssa, joka muokkaa Reittikarttaa ja mahdollisesti tietoputken `rakenna.py`-tiedostoa. Siksi tämä työ tehdään OMAAN kopioon `/home/claude/aineisto-1b/` (kopioi sinne `/home/claude/reittikartta-aineisto/` ilman `.git`-hakemistoa) ja uuteen moduuliin `laser.py`, eikä `rakenna.py`- tai `lataa.py`-tiedostoja muuteta. Tilaaja yhdistää tulokset.

## 1. Tavoite

Simulaattorin kuljettajan näkymä tarvitsee Näsijärven eteläpään rannasta tunnistettavat siluetit: Naistenlahden voimalaitos piippuineen ja kuljettimineen, Näsinneula, Tampellan tehdasrakennukset, Ranta-Tampellan talot, Särkänniemen laitteet ja Mustalahden satama. Maastotietokannan rakennuksilla on vain kerrosluokka, joten korkeudet ja muodot otetaan Maanmittauslaitoksen laserkeilausaineistosta. Tuotetaan kolme asiaa:

1. Pintamalli (DSM) rantavyöhykkeeltä Terrain-RGB-tiilinä, josta simulaattori piirtää rannan rakenteet oikean korkuisina.
2. Rakennuskohtaiset korkeudet maastotietokannan rakennuspolygoneille.
3. Maamerkkien mitat käsimallinnusta varten.

## 2. Alue

Ensimmäinen alue on Näsijärven eteläpää Tampereen kaupungin rannalla: Lielahdesta Naistenlahden kautta Aitolahden suuntaan, ETRS-TM35FIN noin E 322 000–334 000, N 6 820 000–6 827 000, rajattuna 1 km rantavyöhykkeeseen (vesialueen `aoi.gpkg` sisältää vesialueen, käytä sitä). Agentti tarkentaa rajauksen niin, että Näsinneula (noin E 326 600, N 6 823 100, tarkista), Naistenlahden voimalaitos ja Ranta-Tampella ovat mukana, ja kirjaa lopullisen bboxin. Koko järven rantavyöhykettä ei tehdä tässä vaiheessa, koska 820 km rantaviivaa tarkoittaisi satoja laserruutuja. Moduuli kirjoitetaan niin, että alueen voi laajentaa asetuksella.

## 3. Lähde

Paitulin peilipalvelin `https://mirrors.nic.funet.fi/index/geodata/mml/laserkeilaus/2008_latest/<vuosi>/<1:50k-lehti>/<1|2>/<ruutu>.laz`, todennettu 24.10.2026. Tampereen lehti M344 on keilattu 2013 (hakemisto `2013/M344/1/` ja `2/`, tiedostot esimerkiksi `M3441C1.laz`, noin 40 Mt kukin, 3 km × 3 km, LAZ 1.2, pisteet luokiteltu MML:n luokituksella, tiheys noin 0,5 pistettä/m²). Lehdet M343 ja M333–M334 on keilattu 2008–2012 ja N33x 2009–2014. Agentti selvittää hakemistolistauksista, mitkä ruudut kattavat alueen, ja ottaa uusimman saatavilla olevan vuoden kullekin ruudulle. Koordinaatisto EPSG:3067, korkeus N2000. Lisenssi CC BY 4.0 (`ehdot/MML_ehdot_CC.txt`), lähdemerkintä "Sisältää Maanmittauslaitoksen laserkeilausaineistoa <vuosi> (CC BY 4.0)".

Lukemiseen käytetään `laspy` + `lazrs` (pip, --break-system-packages) tai PDAL:ia, jos se asentuu apt:lla. Älä lataa ruutuja, jotka eivät leikkaa aluetta. Kirjaa siirtomäärä ja aika.

## 4. Tuotokset hakemistoon `/home/claude/aineisto-1b/ulos/`

1. `pinta.pmtiles`: pintamalli 1 m ruudukossa (korkein luokiteltu piste per ruutu, maanpinta täytetään DEM 2 m:stä siellä, missä pisteitä ei ole, veden pinnalle järven korkeus), Terrain-RGB-koodaus samoin kuin `maasto.pmtiles`, zoomtasot 12–16. Lisäksi `pinta_1m.tif` välituloksena (ei julkaista).
2. `rakennuskorkeudet.json`: maastotietokannan rakennuksille (`tyo/rajattu.gpkg` tai `tyo/geojson/` vaiheen 1 ajosta, avain MML:n `mtk_id` tai sama tunnus, jota `nasijarvi.pmtiles`-kerros `rakennus` käyttää) kentät `z_maa` (maanpinta N2000, mediaani polygonin reunalla), `h_max` (korkein piste polygonissa miinus maanpinta), `h_p90` (90. persentiili, katon tyypillinen korkeus) ja `pisteita`. Vain rakennukset, joissa on vähintään 5 pistettä. Tämä yhdistetään myöhemmin `rakennus`-kerrokseen tietoputkessa.
3. `maamerkit.json`: käsin valittujen maamerkkien mitat pistepilvestä: Näsinneula (varren halkaisija, lautasen halkaisija ja korkeus, huipun korkeus N2000 ja maanpinnasta), Naistenlahden voimalaitos (kattilarakennuksen ääriviiva ja korkeus, jokaisen piipun sijainti, halkaisija ja korkeus, kuljetinsillan alku- ja loppupiste sekä korkeus), Tampellan tehdasrakennukset (ääriviiva, korkeus), Särkänniemen korkeimmat laitteet (sijainti, korkeus), ja Mustalahden sataman rakennukset. Jokaisesta koordinaatit EPSG:4326 ja EPSG:3067, korkeudet metreinä maanpinnasta ja N2000. Rakenteiden rajaus tehdään pisteiden korkeuden ja ryhmittelyn perusteella, ja agentti kirjaa, miten kukin mitta on saatu.
4. `tarkistuskuvat/`: pintamallista piirretty vinovalovarjostus koko alueesta ja lähikuvat Näsinneulasta, voimalaitoksesta ja Ranta-Tampellasta, sekä yksi "näkymä vedestä" eli pintamallista laskettu siluetti Naistenlahden edustalta (esimerkiksi pisteestä E 328 500, N 6 824 500, 2 m vedenpinnasta) katsottuna etelään 120° kulmalla, viivapiirroksena. Tämä näyttää, erottuvatko voimalaitos, kuljetin ja Näsinneula siluetissa.
5. `laser.py`: koko tuotanto yhdellä komennolla, asetukset tiedoston alussa (alue, vyöhyke, zoomit), ja `aineisto_1b.json`: lähteet ruutuineen ja vuosineen, lisenssi, tuotokset, koot.
6. `RAPORTTI_vaihe1b.md`.

## 5. Hyväksymiskriteerit lukuina

1. Näsinneulan huippu: korkeus maanpinnasta 165–171 m (tornin tunnettu korkeus on noin 168 m). Jos pistepilvessä ei ole osumia huippuun, kirjataan korkein havaittu ja arvio.
2. Naistenlahden voimalaitoksen korkein piippu: korkeus mitattu ja kirjattu, ja sen sijainti rakennuspolygonin sisällä tai vieressä alle 20 m. Vertailuarvoa ei anneta, agentti kirjaa luvun ja mittaustavan.
3. Kuljetinsilta tunnistuu pistepilvestä: pitkä kapea rakenne, pituus ja korkeus kirjattu, näkyy tarkistuskuvassa.
4. Rakennuskorkeudet: alueella vähintään 80 % maastotietokannan rakennuksista saa korkeuden, ja Ranta-Tampellan kerrostalojen `h_p90` on 15–30 m, pientalojen 3–9 m otoksessa, jonka agentti valitsee ja kirjaa.
5. Pintamalli vastaa maastotiilejä avoimella maalla: 50 satunnaisessa pisteessä, joissa ei ole rakennuksia eikä puita, ero DEM 2 m:ään alle 1 m.
6. `pinta.pmtiles` alle 30 Mt, ja yhden puhelinnäkymän siirto tasolla 15 alle 3 Mt.
7. Siluettikuva Naistenlahden edustalta näyttää voimalaitoksen, kuljettimen ja Näsinneulan erillisinä muotoina.

## 6. Työtapa

- Verkko: `mirrors.nic.funet.fi` on sallittu, samoin pakettirekisterit. GDAL ja Python-kirjastot ovat jo asennettuina työtilassa vaiheen 1 ajosta (gdal-bin, numpy, PIL, pyproj, shapely, pmtiles). Älä aja `playwright install`.
- Vaiheen 1 välitulokset ovat hakemistossa `/home/claude/opetus/navi/putki/tyo/` (aoi.gpkg, dem2.vrt, dem10.tif, rajattu.gpkg, geojson/). Käytä niitä lukemiseen, älä muuta.
- Älä muuta `/home/claude/reittikartta-aineisto/`-hakemistoa äläkä `/home/claude/reittikartta-maasto/`-hakemistoa, joissa toinen agentti työskentelee.
- Älä kysy tilaajalta kesken työn, tee ratkaisut itse ja kirjaa ne raporttiin. Tallenna välituloksia usein.
- Suomeksi, kokonaisin lausein, desimaalipilkku, ei puolipisteitä. Raportti numeroitu ja lyhyt: mitä tehtiin, kriteerien 1–7 tulokset lukuina, mitä oletettiin, mikä ei onnistunut, ja mitä pitää lisätä tietoputkeen (`rakenna.py`, työnkulku), jotta tämä ajetaan GitHubissa samassa ajossa.

Palauta lopuksi lyhyt yhteenveto: tiedostojen polut, kriteerien 1–7 tulokset lukuina ja hyväksytty tai ei, maamerkkien mitat lyhyesti (Näsinneula, piiput, kuljetin), siirtomäärä ja ajoaika, ja mitä tietoputkeen pitää lisätä. Älä liitä koodia vastaukseen.
