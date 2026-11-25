# Miten botti toimii

Kaaviot kuvaavat uusimman version (v3) toimintaa. Vanhat versiot toimivat samoin, mutta niistä
puuttuvat v3:n lisäykset (merkitty **v3**). Muutokset: [MUUTOKSET.md](MUUTOKSET.md).

## 1. Päivän kulku

Pilvi (GitHub Actions) ajaa botin arkisin noin klo 19.45 ja tekee aamutarkistuksen klo 8.15.
Ajastetut ajot alkavat usein 30–60 minuuttia myöhässä.

```mermaid
flowchart TD
    A[Ilta-ajo arkisin ~19.45] --> B[Kurssit Yahoosta<br/>päätöskurssi ja vaihto]
    A --> C[Uutiset: Google News, Yahoo,<br/>suuret mediat, RSS, Inderes]
    A --> D[v3: pörssitiedotteet<br/>Nasdaqilta]
    C --> E[Tulkinta: FinBERT-malli<br/>+ avainsanat]
    D --> E
    E --> F[Tärkeimmistä luetaan<br/>artikkelin teksti]
    F --> G[v3: väärät yhtiöosumat<br/>ja rutiinitiedotteet pois]
    G --> H[Signaalit osakkeittain:<br/>uutiset, analyytikot,<br/>johdon kaupat, teemat,<br/>maailman tunnelma, kriisitaso]
    B --> I
    H --> I[Jokainen botti tekee<br/>päätöksensä, kaavio 2]
    I --> J[Toimeksiannot seuraavan<br/>päivän avaukseen]
    J --> K[Raportti: majuriworks.github.io/Sijoitusbotti<br/>+ arkisto + päätösloki]
    L[Aamutarkistus ~8.15] --> M[Yön uutiset]
    M --> N{Kielteinen uutinen<br/>ostettavasta?}
    N -- kyllä --> O[Osto perutaan]
    N -- ei --> P[Toimeksiannot ennallaan]
```

## 2. Yhden botin päätös (joka kauppapäivä)

```mermaid
flowchart TD
    S[Uusi kauppapäivä] --> T[Eilen annetut toimeksiannot<br/>toteutuvat avauskurssiin.<br/>Ostoissa rajahinta enintään +1 %]
    T --> U{Stop-loss?<br/>−15 % huipusta<br/>Lyhyt −8 %}
    U -- kyllä --> MY[Myydään]
    U -- ei --> V{Vakava uutinen<br/>omistuksesta?}
    V -- kyllä --> V2{v3: kurssi vahvistaa?<br/>−3 % / 2 pv, ei rauhoittava,<br/>ei jatkouutinen}
    V2 -- kyllä --> MY
    V2 -- ei --> W
    V -- ei --> W{Päätöspäivä?<br/>Lyhyt: joka päivä<br/>Pitkä: kuun 1. kauppapäivä}
    W -- ei --> Z[Päivän arvo talteen]
    W -- kyllä --> X[Strategia pisteyttää osakkeet:<br/>kurssitrendi + uutiset +<br/>analyytikot + johdon kaupat + teemat]
    X --> Y{Omistus rikkoo sääntöjä?<br/>trendi katkesi, kielteinen<br/>uutinen, pudonnut kärjestä}
    Y -- kyllä --> MY
    Y -- ei --> VA{v3: salkku täynnä ja<br/>ehdokas selvästi parempi?<br/>ero > vaihdon kulut + 1,5 %}
    VA -- kyllä --> MY
    VA -- ei --> OS
    MY --> OS{Vapaata tilaa ostoille?}
    OS -- ei --> Z
    OS -- kyllä --> TA[Neljä tarkastajaa:<br/>uutiset, kurssi,<br/>riski ja hajautus, ajoitus]
    TA -- ohita --> Z
    TA -- osta / pienennä --> KU{Odotettu tuotto ><br/>osto- ja myyntikulut<br/>+ marginaali?}
    KU -- ei --> KE{v3 Lyhyt: kannattaisiko<br/>koko rahalla yhteen?}
    KE -- ei --> Z
    KE -- kyllä --> OT
    KU -- kyllä --> OT[Ostotoimeksianto<br/>seuraavan päivän avaukseen]
    OT --> Z
```

## Botit

| Botti | Tarkistaa | Pitoaika | Valitsee |
|---|---|---|---|
| **Lyhyt** | joka päivä | päivistä viikkoihin | tuore myönteinen uutinen + nouseva kurssi |
| **Pitkä** | kerran kuussa | kuukausista vuosiin | vuoden tasainen nousu + myönteinen uutisvirta |
| **Yhdistelmä** | molemmat | molemmat | 60 % Pitkän ja 40 % Lyhyen säännöillä |
| *Indeksi* | – | aina | vertailukohta: maailmanindeksi ostettuna ja pidettynä |

Versiot ajetaan rinnakkain samoilla tiedoilla: v1 (alkuperäinen), v2 (teemat) ja v3 (uusin).
Raportissa ne näkyvät nimillä "Lyhyt v1", "Lyhyt teema v2", "Lyhyt v3" ja niin edelleen.
