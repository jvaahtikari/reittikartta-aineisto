"""MML:n tiedostopalvelun OGC API Processes -asiakas (vain Pythonin vakiokirjasto).

Rajapinta: https://avoin-paikkatieto.maanmittauslaitos.fi/tiedostopalvelu/ogcproc/v1/ (OGC API - Processes, Part 1: Core).
Tunnistus: API-avain HTTP Basic -otsakkeessa (käyttäjätunnus = avain, salasana tyhjä), varalla URL-parametri api-key.
Avainta ei koskaan kirjoiteta lokiin, tiedostoihin eikä virheilmoituksiin: kaikki ulos menevä teksti kulkee funktion
siivoa_teksti kautta.

Kutsut (ks. https://www.maanmittauslaitos.fi/paikkatiedon-tiedostopalvelu/tekninen-kuvaus, luettu 26.10.2026):
  POST {BASE}/processes/laserkeilausaineisto_05_karttalehti/execution
       {"id": "...", "inputs": {"mapSheetInput": ["M3342B4"], "fileFormatInput": "LAZ", "dataSetInput": "Uusin"}}
  GET  {BASE}/jobs/{jobID}            tila: accepted, running, successful, failed, dismissed
  GET  {BASE}/jobs/{jobID}/results/   tulostiedostot (path, format, crs, mimeType, length, mapSheetNumber), zipPath
  GET  .../dl/v1/{jobID}/{tiedosto}   lataus (sama tunnistus)
"""
import base64
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = "https://avoin-paikkatieto.maanmittauslaitos.fi/tiedostopalvelu/ogcproc/v1"
LASER_PROSESSI = "laserkeilausaineisto_05_karttalehti"
KAYTTAJA = "reittikartta-aineisto/1.0 (avoimen datan tietoputki; yhteys: reittikartta-aineisto GitHub-repo)"


class MmlVirhe(RuntimeError):
    pass


class MmlAsiakas:
    def __init__(self, avain, base=BASE, loki=print):
        self.avain = (avain or "").strip()
        self.base = base.rstrip("/")
        self.loki = loki
        self.tunnistus = "otsake"       # tunnistustapa: "otsake" (Basic) tai "parametri" (api-key)
        self.pyyntoja = 0

    # ------------------------------------------------------------------------------------
    def siivoa_teksti(self, teksti):
        """Poistaa avaimen (ja sen Basic-koodauksen) tekstistä."""
        t = str(teksti)
        if self.avain:
            for v in {self.avain, self._basic(), base64.b64encode(self.avain.encode()).decode(),
                      urllib.parse.quote(self.avain, safe=""), urllib.parse.quote_plus(self.avain)}:
                if v:
                    t = t.replace(v, "***")
        return re.sub(r"(api-key=)[^&\s\"']+", r"\1***", t, flags=re.I)

    def _basic(self):
        return base64.b64encode((self.avain + ":").encode("utf-8")).decode("ascii")

    def _url(self, polku):
        """Täysi osoite. Suhteellinen polku (alkaa /) liitetään palvelimeen, täysi osoite jätetään."""
        if polku.startswith("http://") or polku.startswith("https://"):
            url = polku
        elif polku.startswith("/"):
            url = "https://avoin-paikkatieto.maanmittauslaitos.fi" + polku
        else:
            url = self.base + "/" + polku
        if self.tunnistus == "parametri":
            sep = "&" if "?" in url else "?"
            url += sep + "api-key=" + urllib.parse.quote(self.avain, safe="")
        return url

    def pyynto(self, metodi, polku, runko=None, hyvaksy="application/json", aikaraja=120, yrityksia=4, hyvaksyttavat=(200, 201, 202)):
        """HTTP-pyyntö. Palauttaa (tila, otsakkeet, tavut). Uudelleenyritys verkkovirheille ja 5xx/429-vastauksille."""
        url = self._url(polku)
        otsakkeet = {"User-Agent": KAYTTAJA, "Accept": hyvaksy}
        if self.tunnistus == "otsake":
            otsakkeet["Authorization"] = "Basic " + self._basic()
        data = None
        if runko is not None:
            data = json.dumps(runko).encode("utf-8")
            otsakkeet["Content-Type"] = "application/json"
        viimeinen = None
        for yritys in range(yrityksia):
            self.pyyntoja += 1
            try:
                req = urllib.request.Request(url, data=data, headers=otsakkeet, method=metodi)
                with urllib.request.urlopen(req, timeout=aikaraja) as r:
                    return r.status, dict(r.headers), r.read()
            except urllib.error.HTTPError as e:
                koko = b""
                try:
                    koko = e.read()
                except Exception:  # noqa: BLE001
                    pass
                if e.code in hyvaksyttavat:
                    return e.code, dict(e.headers), koko
                viimeinen = "HTTP %d %s" % (e.code, self.siivoa_teksti(koko[:400].decode("utf-8", "replace")))
                if e.code in (401, 403, 404, 400, 405, 415, 422):
                    raise MmlVirhe("%s %s: %s" % (metodi, self.siivoa_teksti(polku)[:200], viimeinen)) from None
            except Exception as e:  # noqa: BLE001
                viimeinen = self.siivoa_teksti(repr(e))[:300]
            time.sleep(2 + 4 * yritys)
        raise MmlVirhe("%s %s epäonnistui: %s" % (metodi, self.siivoa_teksti(polku)[:200], viimeinen))

    def hae_json(self, metodi, polku, runko=None, **kw):
        tila, ots, tavut = self.pyynto(metodi, polku, runko, **kw)
        try:
            return tila, ots, json.loads(tavut.decode("utf-8")) if tavut else None
        except ValueError as e:
            raise MmlVirhe("Vastaus ei ole JSON-muotoinen (%s %s, tila %d): %s" % (
                metodi, self.siivoa_teksti(polku)[:120], tila, self.siivoa_teksti(tavut[:300].decode("utf-8", "replace")))) from e

    # ------------------------------------------------------------------------------------
    def yhteys(self):
        """Tarkistaa avaimen ja valitsee tunnistustavan. Palauttaa prosessiluettelon tunnukset."""
        if not self.avain:
            raise MmlVirhe("MML_API_KEY puuttuu")
        viimeinen = None
        for tapa in ("otsake", "parametri"):
            self.tunnistus = tapa
            try:
                _, _, d = self.hae_json("GET", "processes")
                ids = sorted(p.get("id") for p in (d or {}).get("processes", []) if isinstance(p, dict))
                self.loki("MML: yhteys toimii (tunnistus: %s), prosesseja %d" % (tapa, len(ids)))
                return ids
            except MmlVirhe as e:
                viimeinen = str(e)
                self.loki("MML: tunnistus tavalla %s ei onnistunut: %s" % (tapa, viimeinen[:200]))
        raise MmlVirhe("Yhteys MML:n rajapintaan ei onnistunut: %s" % viimeinen)

    def prosessi(self, tunnus=LASER_PROSESSI):
        return self.hae_json("GET", "processes/" + tunnus)[2]

    def kaynnista(self, lehdet, tunnus=LASER_PROSESSI, aineisto="Uusin", muoto="LAZ"):
        """Käynnistää työn. Palauttaa jobID:n."""
        runko = {"id": tunnus, "inputs": {"mapSheetInput": list(lehdet), "fileFormatInput": muoto, "dataSetInput": aineisto}}
        tila, ots, d = self.hae_json("POST", "processes/%s/execution" % tunnus, runko)
        job = None
        if isinstance(d, dict):
            job = d.get("jobID") or d.get("jobId") or d.get("id")
        if not job:
            loc = ots.get("Location") or ots.get("location") or ""
            m = re.search(r"/jobs/([^/?#]+)", loc)
            job = m.group(1) if m else None
        if not job:
            raise MmlVirhe("Työn tunnusta ei löytynyt vastauksesta: %s" % self.siivoa_teksti(json.dumps(d)[:300]))
        return job, d

    def tyon_tila(self, job):
        return self.hae_json("GET", "jobs/" + job)[2]

    def odota(self, job, enint_s=1500, vali_s=5, kerro=None):
        """Odottaa työn valmistumista. Palauttaa viimeisen tilavastauksen."""
        alku = time.time()
        edellinen = None
        while True:
            d = self.tyon_tila(job)
            s = (d or {}).get("status")
            if s != edellinen and kerro:
                kerro(job, s, (d or {}).get("progress"), time.time() - alku)
            edellinen = s
            if s in ("successful", "failed", "dismissed"):
                return d
            if time.time() - alku > enint_s:
                raise MmlVirhe("Työ %s ei valmistunut %d sekunnissa (tila %s)" % (job, enint_s, s))
            time.sleep(vali_s)

    def tulokset(self, job):
        return self.hae_json("GET", "jobs/%s/results/" % job)[2]

    @staticmethod
    def tiedostot(tulos):
        """Etsii tulosvastauksesta kaikki tiedostolinkit: [{'path', 'lehti', 'length', ...}]. Rakenne käydään läpi rekursiivisesti."""
        ulos, nahty = [], set()

        def kayt(x):
            if isinstance(x, dict):
                p = x.get("path") or x.get("href") or x.get("url")
                if isinstance(p, str) and re.search(r"\.(laz|las|zip)(\?|$)", p, re.I) and p not in nahty:
                    nahty.add(p)
                    nimi = p.split("?")[0].rsplit("/", 1)[-1]
                    lehti = x.get("mapSheetNumber") or x.get("mapSheet") or re.sub(r"\.(laz|las|zip)$", "", nimi, flags=re.I)
                    ulos.append({"path": p, "lehti": lehti, "nimi": nimi, "length": x.get("length"), "format": x.get("format"),
                                 "crs": x.get("crs"), "mimeType": x.get("mimeType"),
                                 "meta": {k: v for k, v in x.items() if k not in ("path", "href", "url")}})
                for v in x.values():
                    kayt(v)
            elif isinstance(x, list):
                for v in x:
                    kayt(v)
        kayt(tulos)
        return ulos

    def lataa(self, polku, kohde, aikaraja=300, yrityksia=4):
        """Lataa tiedoston levylle (väliaikaistiedoston kautta). Palauttaa tavumäärän."""
        url = self._url(polku)
        otsakkeet = {"User-Agent": KAYTTAJA, "Accept": "*/*"}
        if self.tunnistus == "otsake":
            otsakkeet["Authorization"] = "Basic " + self._basic()
        tmp = str(kohde) + ".osa"
        os.makedirs(os.path.dirname(str(kohde)) or ".", exist_ok=True)
        viimeinen = None
        for yritys in range(yrityksia):
            self.pyyntoja += 1
            try:
                req = urllib.request.Request(url, headers=otsakkeet)
                with urllib.request.urlopen(req, timeout=aikaraja) as r:
                    pituus = r.headers.get("Content-Length")
                    n = 0
                    with open(tmp, "wb") as f:
                        while True:
                            osa = r.read(1 << 20)
                            if not osa:
                                break
                            f.write(osa)
                            n += len(osa)
                if pituus and n != int(pituus):
                    raise IOError("tiedosto katkesi: %d / %s tavua" % (n, pituus))
                os.replace(tmp, kohde)
                return n
            except urllib.error.HTTPError as e:
                viimeinen = "HTTP %d" % e.code
                if e.code in (401, 403, 404):
                    break
            except Exception as e:  # noqa: BLE001
                viimeinen = self.siivoa_teksti(repr(e))[:300]
            time.sleep(2 + 4 * yritys)
        raise MmlVirhe("Lataus epäonnistui (%s): %s" % (self.siivoa_teksti(polku)[:160], viimeinen))
