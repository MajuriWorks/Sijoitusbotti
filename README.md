# Sijoitusbotti – versio 3

Leikkirahalla toimiva sijoitusbotti. Se seuraa koko Helsingin pörssiä, Pohjoismaiden
suurimpia yhtiöitä ja indeksi-ETF:iä. Botti **ei käy kauppaa oikealla rahalla**: se simuloi
kaupat oikeilla kursseilla ja kertoo raportissa, mitä se ostaisi ja myisi. Kun tulokset ovat
vakuuttavia, samat toimeksiannot voi tehdä Nordnetissa käsin.

## Botit

Kolme bottia, joilla on **sama tietopohja** mutta eri aikajänne:

| Botti | Tarkistus | Pitoaika | Idea |
|---|---|---|---|
| **Lyhyt** | joka päivä | päivistä ~3 viikkoon | Tuoreet myönteiset uutiset/tiedotteet, suositusten nostot tai johdon ostot, jotka kurssi ja kaupankäynti vahvistavat. Stop-loss 8 %. |
| **Pitkä** | kerran kuussa | kuukausista vuosiin | Vuoden tasainen nousu + myönteinen uutisvirta, analyytikot ja johdon kaupat. Välttää ylikuumentuneet pienyhtiöt. Jää käteiselle, jos markkina on laskussa ja maailman tunnelma negatiivinen. |
| **Yhdistelmä** | molemmat | molemmat | 60 % Pitkä-säännöillä (1 osake) + 40 % Lyhyt-säännöillä (1 osake). |
| *Indeksi* | – | aina | Vertailukohta: maailmanindeksi (EUNL) ostettuna ja pidettynä, kuluineen. |
| *Helsinki* | – | – | Vertailukäyrä: Helsingin osakkeet tasapainoisesti, ilman kuluja. |

### Tietopohja (kaikilla boteilla sama)

- **Pörssikurssit ja kaupankäyntimäärät:** Yahoo Finance; Helsinki, Pohjoismaat, ETF:t.
- **Yhtiöuutiset ja pörssitiedotteet:** Google News -hakusyöte yhtiöittäin sekä Yahoo Finance.
- **Analyytikoiden suositusmuutokset:** esim. "nostaa suositusta", "tavoitehinta".
- **Johdon omat osakekaupat:** johdon liiketoimet -tiedotteet.
- **Maailman tapahtumat:** korot, tullit, taantumapelot, öljy ja geopolitiikka. Haut voi muokata tiedostossa `config.yaml`.
- **Foorumit:** Inderesin foorumi ja Reddit. Mitataan, mistä yhtiöistä keskustellaan tavallista enemmän.

Jokainen uutinen saa tunnelman (−1…+1) ja painoarvon. Oletuksena tulkinta tehdään avainsanoilla.
**Tekoälytulkinta** (tarkempi) otetaan käyttöön lisäämällä GitHubiin salaisuus `ANTHROPIC_API_KEY`
(Settings → Secrets and variables → Actions → New repository secret). Kustannus on arviolta muutamia euroja kuukaudessa.
Kaikki uutiset tallentuvat kansioon `arkisto/uutiset/`, ja raportin kohta *Tietolähteiden tila* kertoo, mitkä lähteet toimivat.

**Historiatesti käyttää vain kurssitietoja**, koska menneiden vuosien uutisia ei saa ilmaiseksi.
Uutisten ja somen hyöty nähdään leikkikaupassa.

Yhteiset säännöt (`config.yaml` → `riskit`): enintään 2 osaketta kerrallaan, stop-loss 15 % (Lyhyt 8 %, ei koske Indeksiä),
kauppaa ei tehdä, jos kulut ylittävät 2,5 % kauppasummasta (pienessä salkussa enintään 4 %), ja vähimmäispäivävaihto on 200 000 €.
Toimeksiannot tehdään päivän päätöskurssien ja iltaan mennessä julkaistujen uutisten perusteella, ja ne toteutetaan **seuraavan päivän avauskurssiin**.

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

## Versiot: muutokset rinnalle, ei päälle

Botit on lukittu versioiksi (kansio `versiot/v1/`). Lukittuun versioon ei kosketa.
Kun sääntöjä halutaan muuttaa:
1. Kopioi uusin versio uudeksi (`versiot/v2/`) ja tee muutokset siihen.
2. Lisää `config.yaml`:iin uusi botti, jolla on `versio: v2` ja `pohja: lyhyt` (tai pitka/yhdistelma).
   Lisäksi `aloita: alusta` ajaa sen leikkikaupan alusta asti tallennetuilla kursseilla ja uutisilla,
   jolloin se on suoraan vertailukelpoinen vanhan kanssa.
3. Vanha botti jatkaa ennallaan. Raportissa ne näkyvät rinnakkain (esim. "Lyhyt v1" ja "Lyhyt v2").

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

- [ ] Leikkikaupassa botti voittaa Indeksin kulujen jälkeen (historiatesti ei sisällä uutisia).
- [ ] Suurin pudotus on sellainen, jonka kestäisit oikealla rahalla.
- [ ] Vähintään 2–3 kuukautta leikkikauppaa, ja tulos on linjassa historiatestin kanssa.
- [ ] Kuluprofiili vastaa omaa välittäjääsi.
- [ ] Osakesäästötili on avattu. Huom: osakesäästötilille käyvät vain ETA-alueen pörssiosakkeet (ei ETF:t).

**Historiatestin rajoitus:** ilmaisessa datassa on vain nykyään pörssissä olevat yhtiöt. Konkurssiin menneet ja pörssistä poistuneet puuttuvat, joten historiatesti näyttää todellista paremmalta. Leikkikauppa ei kärsi tästä, joten sen tulos on lopulta luotettavampi.

*Ei sijoitusneuvontaa. Menneisyyden tuotto ei takaa tulevaa.*
