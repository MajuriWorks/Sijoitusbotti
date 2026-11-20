"""Skeptikko: viimeinen tarkistus ennen jokaista ostoa.

Etsii syitä olla ostamatta. Tuomio:
  "hyväksy"  – osto tehdään normaalin kokoisena
  "puolikas" – osto tehdään puolikkaana (epävarmuutta, mutta ei estettä)
  "hylkää"   – ei ostoa
Säännöt ovat ilmaisia. Jos myöhemmin otetaan käyttöön maksullinen tekoäly, tämän voi korvata
kielimallilla, joka saa samat tiedot.
"""
from __future__ import annotations

import pandas as pd

_TULOSPAIVAT: dict[str, pd.Timestamp | None] = {}


def _seuraava_tulosjulkistus(ticker: str) -> pd.Timestamp | None:
    """Seuraava tulosjulkistus Yahoosta (vain leikkikaupassa, ei historiatestissä)."""
    if ticker in _TULOSPAIVAT:
        return _TULOSPAIVAT[ticker]
    paiva = None
    try:
        import yfinance as yf
        kal = yf.Ticker(ticker).calendar or {}
        paivat = kal.get("Earnings Date") if isinstance(kal, dict) else None
        if paivat:
            paiva = pd.Timestamp(paivat[0])
    except Exception:  # noqa: BLE001
        paiva = None
    _TULOSPAIVAT[ticker] = paiva
    return paiva


def arvioi(strategia, ticker: str, paiva: pd.Timestamp, likviditeetti: float | None) -> tuple[str, list[str]]:
    sig = strategia.sig
    c = strategia.c[ticker].loc[:paiva].dropna()
    if len(c) < 25:
        return "hylkää", ["liian lyhyt kurssihistoria"]
    hylkaa, puolikas = [], []
    lyhyt = strategia.nimi.endswith("lyhyt")

    # 1) Kielteinen tai vakava uutinen
    if sig.kielteinen_uutinen(ticker, paiva):
        hylkaa.append("kielteinen uutinen viime päiviltä")

    # 2) Ylikuumentunut: kurssi on jo ehtinyt nousta paljon -> nousu voi olla jo hinnoiteltu
    nyt = float(c.iloc[-1])
    yli20 = nyt / float(c.iloc[-20:].mean()) - 1
    r5 = nyt / float(c.iloc[-6]) - 1
    if lyhyt and (r5 > 0.12 or yli20 > 0.15):
        hylkaa.append(f"ylikuumentunut (5 pv {r5:+.0%}, {yli20:+.0%} yli 20 pv keskiarvon)")
    elif not lyhyt and yli20 > 0.20:
        puolikas.append(f"kurssi {yli20:+.0%} yli 20 pv keskiarvon – voi olla ylikuumentunut")

    # 3) Uutiset: ristiriitaiset tai yhden heikon lähteen varassa
    i = int(sig.paivat.searchsorted(paiva))
    tuoreet = [u for j in range(max(0, i - 3), i + 1) for u in sig._otsikot.get((ticker, j), [])]
    if any(u.tunnelma > 0.5 for u in tuoreet) and any(u.tunnelma < -0.5 for u in tuoreet):
        puolikas.append("ristiriitaisia uutisia")
    if lyhyt and sig.onko_dataa:
        vahvat = [u for u in tuoreet if u.tunnelma * u.paino > 0.2]
        if len(vahvat) == 1 and vahvat[0].paino < 0.5:
            puolikas.append("signaali yhden heikon lähteen varassa")

    # 4) Kriisi maailmalla
    if sig.kriisissa(paiva):
        puolikas.append("kriisitila maailmalla")

    # 5) Vähän vaihdettu osake: hintaero ja myynnin vaikeus
    if likviditeetti is not None and not pd.isna(likviditeetti) and likviditeetti < 500_000:
        puolikas.append(f"vähän kauppaa ({likviditeetti / 1000:.0f} k€/pv)")

    # 6) Tulosjulkistus lähellä: kurssi voi heittää kumpaan suuntaan tahansa
    if sig.onko_dataa:
        tp = _seuraava_tulosjulkistus(ticker)
        if tp is not None and pd.Timestamp(paiva) <= tp <= pd.Timestamp(paiva) + pd.Timedelta(days=7):
            (puolikas if not lyhyt else hylkaa).append(f"tulosjulkistus tulossa {tp.date()}")

    if hylkaa:
        return "hylkää", hylkaa + puolikas
    if puolikas:
        return "puolikas", puolikas
    return "hyväksy", []
