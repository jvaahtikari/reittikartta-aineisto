# Näsijärven aineistopaketti, käyttöönotto selaimessa

Tämä hakemisto on valmis GitHub-repositorion juureksi. Kaikki vaiheet tehdään GitHubin verkkosivulla, terminaalia ei tarvita. Pakettia ei tarvitse ladata omalle koneelle, GitHub rakentaa sen ja julkaisee sen verkkosivuna.

## 1 ja 2. Repositorio ja tiedostot

Repositorio `jvaahtikari/reittikartta-aineisto` on luotu ja tämän hakemiston tiedostot on viety siihen 24.10.2026, mukaan lukien työnkulku `.github/workflows/aineisto.yml`. Näitä kohtia ei tarvitse tehdä. Jos repositorio joskus luodaan uudelleen, tee se julkisena (Pages toimii ilmaisella tilillä vain julkisessa repositoriossa) ja vie kaikki tämän hakemiston tiedostot sinne.

## 3. Salli julkaisu Pages-sivuna

1. Repositorion yläpalkista **Settings**.
2. Vasemmalta **Pages**.
3. Kohdassa **Build and deployment** valitse **Source**-valikosta **GitHub Actions**. Muuta ei tarvitse tehdä, valinta tallentuu itse.

## 4. Käynnistä ensimmäinen rakennus

1. Repositorion yläpalkista **Actions**. Jos GitHub kysyy lupaa ajaa työnkulkuja, paina vihreää painiketta (**I understand my workflows, go ahead and enable them**).
2. Vasemmalta valitse **Rakenna Näsijärven aineistopaketti**.
3. Oikealta **Run workflow**, sitten vihreä **Run workflow**.
4. Rakennus kestää noin 25 minuuttia (testiajossa 22 minuuttia, GitHubin koneella voi mennä 40 minuuttiin). Voit sulkea sivun, ajo jatkuu. Onnistunut ajo näkyy vihreänä rastina, ja sen alla on kaksi vaihetta, `rakenna` ja `julkaise`.

## 5. Mistä paketti löytyy

Onnistuneen ajon jälkeen paketti on osoitteessa `https://KÄYTTÄJÄNIMI.github.io/reittikartta-aineisto/` (korvaa KÄYTTÄJÄNIMI omallasi, pienillä kirjaimilla). Osoite näkyy myös ajon `julkaise`-vaiheen yhteenvedossa.

| Tiedosto | Sisältö |
| --- | --- |
| `nasijarvi.pmtiles` | vektoritiilet, zoom 8–16 (rakennukset, kiinteistörajat, tiet, osoitteet, väylät, turvalaitteet, syvyydet) |
| `maasto.pmtiles` | korkeustiilet Terrain-RGB-koodauksella, zoom 8–14 |
| `puusto.pmtiles` | puuston pituus ja latvuspeitto, zoom 10–14 |
| `osoitteet.json` | osoitehakemisto (kadun nimi, numero, postinumero, kunta ja sijainti), noin 1,7 Mt, Reittikartan osoitehaku lataa sen kerran |
| `kiinteistot.json` | kiinteistötunnushakemisto (tunnus ja sijainti), noin 1,1 Mt, Reittikartan tunnushaku lataa sen kerran |
| `aineisto.json` | paketin kuvaus: alue, lähteet, lisenssit ja lähdemerkinnät, kerrokset ja kentät, tiedostokoot ja tarkistussummat |
| `tarkistus.json` | ajon omat tarkistukset (korkeudet, määrät, koot) |
| `testi.html` | testisivu, avaa selaimessa osoitteesta `.../testi.html` ja katso että kartta piirtyy |

Pages-palvelu tukee sekä CORS-otsikoita että Range-pyyntöjä, joten PMTiles-tiedostot voi lukea suoraan selaimesta.

## 6. Päivitys ja vikatilanteet

- Paketti rakentuu uudelleen automaattisesti joka kuukauden ensimmäinen päivä. Voit ajaa sen milloin tahansa käsin kohdan 4 mukaan.
- Jos ajo epäonnistuu, avaa epäonnistunut ajo **Actions**-välilehdeltä ja katso punaisella merkityn vaiheen loki. Ajon alalaidassa on myös lataus **lokit**, jossa ovat latausloki ja tarkistustulokset. Tyypillinen syy on tilapäinen lähdepalvelun katko, ja uusi ajo auttaa usein.
- Koodia voi muokata selaimessa: avaa tiedosto, paina kynäkuvaketta, tee muutos ja paina **Commit changes**.

## 7. Huomioitavaa

- **Salaisuuksia ei tarvita.** Kaikki lähteet ovat avoimia ilman avainta, joten `MML_API_KEY` ei ole käytössä.
- Aineisto ei ole tarkoitettu navigointiin eikä täytä asianmukaisen merikartan vaatimuksia. Traficomin syvyysaineistoa saa käyttää vain muuhun kuin navigointikäyttöön ja ei-kaupallisesti, ja lähdemerkintä tiedonsiirron ajankohtineen on pidettävä näkyvissä. Kaikki lähdemerkinnät ovat tiedostossa `aineisto.json`, kenttä `lahdemerkinta_yhteensa`.
- Osoiteaineisto on DVV:n poiminta 3.2.2025. DVV lopetti avoimen jakelun 14.3.2025, joten osoitteet eivät päivity.
- Ajon pitää onnistua alle 60 minuutissa ja alle 10 Gt levytilalla (GitHubin ilmaisen version rajat). Työnkulussa on lisäksi 55 minuutin aikaraja.
