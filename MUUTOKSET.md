# Muutokset (patch notes)

Uusin ylimpänä. **[vN]** = koskee vain sitä bottiversiota, **[infra]** = yhteinen koodi (ei muuta
vanhojen versioiden päätöksiä), **[korjaus]** = virheen korjaus.

---

## 27.11.2026 – v4: Lyhyt ostaa myös kalliin osakkeen
- **[v4]** Lyhyt v4 ajetaan rinnalle leikkikaupan alusta. Ainoa ero v3:een: jos paras ehdokas on niin kallis, ettei puolikas raha riitä yhteenkään osakkeeseen, raha keskitetään siihen, kunhan osto kannattaa kulujen jälkeen. *Syy: Lyhyt v3 jätti Genmabin (osake noin 518 €, odotettu tuotto +7 %) ostamatta 24.–26.11. Uudelleenajossa Lyhyt v4 olisi ostanut sen 25.11.* Pitkä ja Yhdistelmä v4 olisivat samat kuin v3, joten niitä ei ajeta.
- [infra] Guardianin uutissyöte poistettu, koska se estää GitHubin palvelimet (403).

## 25.11.2026 (ilta) – Trumpin päivitysten keruu pois
- [infra] Trumpin Truth Social -päivityksiä ei kerätä. *Syy: analyysi 14 527 päivityksestä aiheittain (tullit, Kiina, lääkkeet, NATO, öljy, yhtiömaininnat). Yhtiömaininnat (Apple, Nvidia, Tesla) liikuttivat kurssia noin 1,7-kertaisesti tavalliseen verrattuna, mutta suunnan jatkuminen oli kolikonheittoa (noin 50 %), ja liike tapahtuu minuuteissa. Iltabotti ei hyödy tästä.* Koodi jää talteen pois päältä.

## 25.11.2026 – v3 valmis, ajetaan ensimmäisen kerran tänä iltana
v3-botit (Lyhyt, Pitkä, Yhdistelmä) ajetaan leikkikaupan alusta (13.11.) asti, jolloin niitä voi verrata v1:een ja v2:een.

**v3 – päätöksenteko**
- Hätämyynti vain, jos kurssi vahvistaa uutisen (vähintään −3 % kahdessa päivässä). Rauhoittavat otsikot ("hyökkäys pysäytetty", "ei vaikutusta") ja saman asian jatkouutiset eivät enää laukaise myyntiä. *Syy: v1 myi Equinorin uutisesta "cyberattack has stopped".*
- Vaihtolaskelma: heikoin omistus vaihdetaan selvästi parempaan, jos tuottoero kattaa kulut ja 1,5 %:n marginaalin. Ostohinta tai tappio ei vaikuta päätökseen.
- Lyhyt keskittää rahan parhaaseen osakkeeseen, jos kahden 500 euron kaupan kulut estäisivät oston. *Syy: Lyhyt ei ostanut mitään, koska kulut olivat noin 4 %.*
- "Pienennä"-tuomio ei puolita kauppaa, vaan vaatii odotetulta tuotolta +2 %-yksikköä enemmän.
- Kriisitila lasketaan vakavien uutisten osuutena kaikista uutisista, ei pelkkänä määränä.
- Aikaraja koskee vain osakkeita, jotka eivät ole liikkuneet mihinkään.

**v3 – uutisten ymmärtäminen**
- Artikkelin tekstistä luettu sävy korvaa otsikon sävyn (klikkiotsikot).
- Väärät yhtiöosumat pois: monitulkintaiset nimet (Elisa, Alexandria, Kone, Tieto, Target…) vaativat otsikkoon talousaiheisen sanan.
- Pörssitiedotteet suoraan Nasdaqilta: rutiinitiedotteet jätetään pois, johdon kaupat ja liputukset otetaan mukaan vain, kun suunta on luettu tekstistä, ja osakeanti tulkitaan kielteiseksi.

**Infra**
- [korjaus] Artikkelien luku: Google-linkit hylättiin virheen takia, joten vain noin 5 artikkelia 150:stä luettiin.
- [korjaus] Yahoon rikkinäinen kurssihistoria (SSAB A: negatiivisia kursseja) jätetään pois.
- [korjaus] HS:n lakannut uutissyöte poistettu.
- Uusi lähde: Nasdaqin pörssitiedotteet (Helsinki, Tukholma, Kööpenhamina) omaan arkistoonsa (`arkisto/lisalahteet/`, vain v3 lukee).
- Aamutarkistus käyttää kunkin botin oman version sääntöjä.
- Historiatesti osaa ajaa lukitun version: `python historiatesti.py --versio v3`.

## 20.11.2026 – v1 lukittu, v2 ja laaja valikoima rinnalle
- **v1 lukittu** (ensimmäinen versio).
- **v2:** teemat. Maailman tapahtumat (korot, sota, tullit…) nostavat hyötyviä ja laskevat kärsiviä toimialoja.
- **Laaja valikoima:** v1:n säännöt koko valikoimalla (mukana S&P 500, Nasdaq-100 ja enemmän ETF:iä).
- Neljä tarkastajaa ennen jokaista ostoa (uutiset, kurssi, riski/hajautus, ajoitus), kaksi kierrosta.
- Odotetun tuoton pitää ylittää kaupan kulut. Ennusteita verrataan toteutuneeseen.
- Hätämyynti, kriisitila ja aamutarkistus klo 8.15.
- Suuret mediat mukaan (Reuters, Bloomberg, HS, Yle, Kauppalehti…).
- Osto- ja myyntihinnan ero, osingot ja osakesplitit mukaan laskelmiin. Verot raporttiin.

## 14.11.2026 – alku
- Kolme bottia (Lyhyt, Pitkä, Yhdistelmä) ja Indeksi vertailukohtana. Leikkikauppa ja historiatesti GitHubin pilvessä.
- Ilmainen uutistulkinta (FinBERT-malli + avainsanat). Ostot rajahinnalla.
- Leikkikauppa alkoi 13.11.2026, 1 000 € per botti.
