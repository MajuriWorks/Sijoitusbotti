# Sijoitusbotti – ohjeet Claudelle

Leikkirahalla toimiva sijoitusbotti. Omistaja (MajuriWorks) ei ole sijoittamisen tai ohjelmoinnin
asiantuntija: **vastaa suomeksi, selkokielellä**, tee hyviksi todetut ratkaisut ja kerro lyhyesti miksi.

## Ehdoton työtapa: versiot rinnalle, ei päälle
- Lukitut bottiversiot ovat kansiossa `versiot/<v1|v2|v3…>/botti/`. **Lukittuun versioon ei kosketa koskaan.**
- Strategian tai päätöksenteon muutos = uusi versio: kopioi uusin versio → `versiot/vN/`, tee muutokset
  sinne, lisää `config.yaml`:iin uudet botit (`versio: vN`, `pohja: lyhyt|pitka|yhdistelma`, `nimi`,
  `aloita: alusta` jotta ne ajetaan leikkikaupan alusta tallennetuilla tiedoilla) ja kirjaa
  `versiot:`-osioon lukitus­päivä ja muutos. Vanhat botit jatkavat ennallaan.
- Poikkeus (omistajan päätös 25.11.2026): uusinta versiota saa muuttaa, kunnes se on ajanut leikkikauppaa
  pilvessä. Jos se ehti jo ajaa, poista sen salkut `tila/salkut.json`:sta (avaimet `…@<botti>_vN`) ja sen rivit
  `arkisto/paatokset.jsonl`:sta (`"versio": "vN"`), jolloin se ajetaan seuraavalla kerralla uudelleen alusta.
  Ei tuhansia versioita: pienet parannukset kootaan samaan keskeneräiseen versioon.
- `botti/`-kansion koodi on yhteistä infraa (datan haku, uutiskeräys ja -tulkinta, raportti,
  versioiden ajaminen). Sitä saa korjata. Jos korjaus muuttaisi bottien päätöksiä, tee se uutena versiona.
- Omistaja pyysi tätä alusta asti; sen rikkominen on aiemmin sotkenut tulokset.

## Muutosloki ja kaaviot
- Jokaisesta muutoksesta lyhyt selkokielinen merkintä `MUUTOKSET.md`:hen (uusin ylimpänä, päivämäärä,
  merkintä [vN]/[infra]/[korjaus] ja lyhyesti miksi). Omistaja silmäilee sen nopeasti.
- Jos päätöksenteon kulku muuttuu, päivitä kaaviot `TOIMINTA.md`:ssä (Mermaid, näkyy GitHubissa).

## Rakenne
- `paivittainen.py` – leikkikauppa (GitHub Actions ma–pe 19:45 ilta, 8:15 aamutarkistus `--aamu`)
- `historiatesti.py` – historiatesti vain kurssitiedoilla (lauantaisin)
- `config.yaml` – botit, valikoimat (perus/laaja), kulut, riskit, uutislähteet
- `botti/` – infra: `data.py` (Yahoo), `uutiset.py` + `artikkelit.py` (uutiset, tulkinta),
  `versiot.py` (botit omilla versioillaan), `raportti.py`, `valikoimat.py` (S&P 500 / Nasdaq-100),
  `lisalahteet.py` (Nasdaqin pörssitiedotteet + Trump → `arkisto/lisalahteet/`, jota vain v3→ lukee)
- Uuden tietolähteen tieto, joka muuttaisi vanhojen versioiden päätöksiä, tallennetaan erilleen
  (oma arkisto tai `lisatieto`-kenttä), ja vain uudet versiot käyttävät sitä.
- `versiot/vN/botti/` – lukitut strategiat: `strategiat.py`, `moottori.py`, `tarkastaja.py`,
  `signaalit.py`, (v2→) `teemat.py`
- `tila/salkut.json` – leikkisalkut; `arkisto/` – kurssit, uutiset, päätösloki; `docs/` – raporttisivu

## Testaus
- Keksityllä datalla (ei verkkoa): kopioi tiedostot väliaikaiskansioon ja aja siellä, jottei
  oikea `tila/` tai `arkisto/` sotkeudu. Poista kopiosta oikea tila, muuten oikeat omistukset
  arvostetaan keksityillä kursseilla (järjettömiä arvoja, raportin kaavio voi kaatua):
  `rm -rf tila arkisto/paatokset.jsonl arkisto/uutiset arkisto/kurssit docs`
  `python paivittainen.py --testidata --testi-asti 2026-09-01 && python paivittainen.py --testidata`
- Oikealla datalla (vaatii verkon): `python historiatesti.py --vertaa-kulut` (lisäksi `--versio v3` ajaa
  lukitun version; oletus on `botti/`-kansion koodi). Historiatestissä ei ole uutisia.
- Älä koskaan aja testejä repon juuressa ilman `git checkout -- tila arkisto docs` -palautusta.

## Muistettavaa
- Repo on julkinen: **ei omistajan oikeita omistuksia tai tunnuksia tänne.**
- Kaupat tehdään Nordnetissa käsin; botilla ei ole pääsyä Nordnetiin. Arvo-osuustili, 30 % vero.
- Pääoma ~1 000 € per botti; Nordnetin min. kulu 9 € → kulut ratkaisevat paljon.
- Vain ilmaisia ratkaisuja (maksullinen Claude-API uutistulkintaan mahdollinen myöhemmin).
- Raportti: https://majuriworks.github.io/Sijoitusbotti/
