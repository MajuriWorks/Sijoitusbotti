# Sijoitusbotti – versio 2

Leikkirahalla toimiva sijoitusbotti. Se seuraa koko Helsingin pörssiä, Pohjoismaiden
suurimpia yhtiöitä ja indeksi-ETF:iä. Botti **ei käy kauppaa oikealla rahalla**: se simuloi
kaupat oikeilla kursseilla ja kertoo raportissa, mitä se ostaisi ja myisi. Kun tulokset ovat
vakuuttavia, samat toimeksiannot voi tehdä Nordnetissa käsin.

## Botit

| Botti | Tarkistus | Pitoaika | Idea |
|---|---|---|---|
| **Trendi** | kerran viikossa | viikoista kuukausiin | Ostaa nousutrendissä olevia osakkeita, joiden 3 kk nousu on suurin. Myy, kun trendi katkeaa. |
| **Rauhallinen** | kerran kuussa | kuukausista vuosiin | Ostaa osakkeita, jotka ovat nousseet vuoden ajan tasaisesti. Jää käteiselle, jos markkina laskee. |
| **Indeksi** | – | aina | Ostaa maailmanindeksin (EUNL) kerran ja pitää sen. Realistinen vertailukohta kuluineen. |
| *Helsinki* | – | – | Vertailukäyrä: Helsingin osakkeet tasapainoisesti, ilman kuluja. |

Aktiivisen botin (Trendi, Rauhallinen) pitää voittaa Indeksi ja Helsinki kulujen jälkeen.
Muuten oikeaa rahaa ei kannata antaa sille.

Yhteiset säännöt (`config.yaml` → `riskit`):

- enintään 2 osaketta kerrallaan
- 15 %:n stop-loss huipusta (ei koske Indeksiä)
- kauppaa ei tehdä, jos kulut ylittävät 2,5 % kauppasummasta
- osakkeen päivävaihdon pitää olla vähintään 200 000 €; vähän vaihdetut jätetään pois, koska niissä osto- ja myyntihinnan ero syö tuottoa

Toimeksiannot tehdään päivän päätöskurssien perusteella ja toteutetaan **seuraavan päivän avauskurssiin**.
Muiden valuuttojen kurssit (SEK, NOK, DKK) muunnetaan euroiksi päivän valuuttakurssilla.

## Pilveen: botti pyörii ilman omaa konetta (suositus)

GitHub ajaa botin ilmaiseksi joka arki-ilta noin klo 19:45. Se tallentaa leikkisalkkujen tilan
ja päivittää raporttisivun, jota voit katsoa puhelimella milloin vain.

1. Luo tili osoitteessa https://github.com ja valitse **New repository**. Nimeksi esim. `sijoitusbotti`
   ja näkyvyydeksi **Public** (ilmainen raporttisivu vaatii julkisen repon; siinä on vain leikkirahaa).
2. Valitse **uploading an existing file** ja raahaa kaikki tämän kansion tiedostot ja kansiot,
   myös `.github`. Paina **Commit changes**. Tarkista, että `.github/workflows/` näkyy repossa.
3. **Settings → Actions → General → Workflow permissions** → **Read and write permissions** → Save.
4. **Actions** → *Päivittäinen leikkikauppa* → **Run workflow**. Aja samoin myös *Historiatesti*.
5. **Settings → Pages** → *Deploy from a branch*, haara `main`, kansio `/docs` → Save.
   Raportti: `https://<käyttäjänimesi>.github.io/sijoitusbotti/`

Raporttisivulla näkyvät toimeksiannot, salkkujen arvo, tuotot viikoittain, kuukausittain ja
vuosittain sekä linkit raporttiarkistoon ja historiatestiin.

## Varmistukset: mikään ei mene hukkaan

- **Koko historia tallessa.** Jokainen päivä tallennetaan GitHubiin omana versionaan. Minkä tahansa päivän tilan voi palauttaa.
- **Kurssiarkisto** (`arkisto/kurssit/`): jokaisen käsitellyn päivän kurssit tallennetaan, vaikka Yahoo myöhemmin muuttaisi tai poistaisi dataa.
- **Päätösloki** (`arkisto/paatokset.jsonl`): jokainen päätös tallennetaan ehdokkaineen ja perusteluineen. Jälkikäteen voi tarkistaa, miksi botti teki mitä teki ja olisiko jokin muu ollut parempi.
- **Raporttiarkisto** (`docs/arkisto/`): jokaisen päivän raportti säilyy.
- **Uudelleenajo.** Jos sääntöjä muutetaan, uutta versiota voi testata samalla jaksolla, jolla leikkikauppa on jo käynyt:
  `python historiatesti.py --alku 2026-11-13` tai GitHubissa *Historiatesti* → *Run workflow* → aloituspäivä.
- **Uudet botit rinnalle, ei päälle.** Muutettu botti lisätään uudella nimellä, jolloin vanha jatkaa ja niitä voi verrata. Botin nollaaminen (`--nollaa`) tallentaa vanhan tilan varmuuskopioksi.
- **Vajaa data ei sotke.** Jos kursseja saadaan alle puolelle kohteista, ajo keskeytetään eikä salkkuihin kosketa. Seuraava ajo hoitaa välistä puuttuvat päivät.

## Ajo omalla koneella (vaihtoehto)

1. Asenna Python 3.10+ (https://www.python.org/downloads/, ruksi "Add Python to PATH").
2. `pip install -r requirements.txt`
3. Historiatesti: `aja_historiatesti.bat` (tai `python historiatesti.py --vertaa-kulut`)
4. Leikkikauppa joka arki-ilta klo 19 jälkeen: `aja_paivittain.bat` (tai `python paivittainen.py`)

`--testidata` ajaa skriptit keksityllä datalla ilman nettiä. Se on vain koodin testaamiseen.

## Asetukset (`config.yaml`)

- `kuluprofiili`: nordnet / nordnet_osakesaastajat / nordea. **Tarkista omat kulusi.**
- `osakkeet`: Helsinki (126), Pohjoismaat (63) ja ETF:t (5). Yahoo Finance -tunnukset. Raportti kertoo, jos jollekin tunnukselle ei löydy kursseja.
- `riskit`: positioiden määrä, stop-loss, kuluraja ja vaihtoraja.

## Ennen oikeaa rahaa – tarkistuslista

- [ ] Historiatesti oikealla datalla: botti voittaa Indeksin kulujen jälkeen useimpina vuosina.
- [ ] Suurin pudotus on sellainen, jonka kestäisit oikealla rahalla.
- [ ] Vähintään 2–3 kuukautta leikkikauppaa, ja tulos on linjassa historiatestin kanssa.
- [ ] Kuluprofiili vastaa omaa välittäjääsi.
- [ ] Osakesäästötili on avattu. Huom: osakesäästötilille käyvät vain ETA-alueen pörssiosakkeet (ei ETF:t).

**Historiatestin rajoitus:** ilmaisessa datassa on vain nykyään pörssissä olevat yhtiöt. Konkurssiin menneet ja pörssistä poistuneet puuttuvat, joten historiatesti näyttää todellista paremmalta. Leikkikauppa ei kärsi tästä, joten sen tulos on lopulta luotettavampi.

*Ei sijoitusneuvontaa. Menneisyyden tuotto ei takaa tulevaa.*
