"""Tarkastajat: viimeinen tarkistus ennen jokaista ostoa.

Neljä tarkastajaa katsoo ostoa eri kulmista ja eri tiedoista:
  Uutistarkastaja    – mitä yhtiöstä kerrotaan (kielteiset, ristiriitaiset, heikot lähteet)
  Kurssitarkastaja   – onko hinta jo karannut (ylikuumeneminen, hyppy)
  Riskitarkastaja    – kaupankäynnin määrä, heilunta ja hajautus nykyisiin omistuksiin
  Ajoitustarkastaja  – tuleva tulosjulkistus ja maailman kriisitila

Kukin antaa tuloksen "osta", "pienennä" tai "ohita".
Yhteispäätös:
  yksikin "ohita"            -> ohita
  vähintään 3 "pienennä"     -> ohita (liian monta varoitusmerkkiä yhtä aikaa)
  1–2 "pienennä"             -> pienennä (osto puolet pienempänä)
  muuten                     -> osta
"""
from __future__ import annotations

import numpy as np
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


def _tulos(ohita: list[str], pienenna: list[str]) -> tuple[str, list[str]]:
    if ohita:
        return "ohita", ohita + pienenna
    if pienenna:
        return "pienennä", pienenna
    return "osta", []


# ------------------------------------------------------------------ tarkastajat
def uutistarkastaja(strategia, t, paiva, **_):
    sig = strategia.sig
    ohita, pienenna = [], []
    if sig.kielteinen_uutinen(t, paiva):
        ohita.append("kielteinen uutinen viime päiviltä")
    i = int(sig.paivat.searchsorted(paiva))
    tuoreet = [u for j in range(max(0, i - 3), i + 1) for u in sig._otsikot.get((t, j), [])]
    if any(u.tunnelma > 0.5 for u in tuoreet) and any(u.tunnelma < -0.5 for u in tuoreet):
        pienenna.append("ristiriitaisia uutisia")
    if strategia.nimi.endswith("lyhyt") and sig.onko_dataa:
        vahvat = [u for u in tuoreet if u.tunnelma * u.paino > 0.2]
        if len(vahvat) == 1 and vahvat[0].paino < 0.5:
            pienenna.append("signaali yhden heikon lähteen varassa")
    return _tulos(ohita, pienenna)


def kurssitarkastaja(strategia, t, paiva, **_):
    c = strategia.c[t].loc[:paiva].dropna()
    if len(c) < 25:
        return "ohita", ["liian lyhyt kurssihistoria"]
    ohita, pienenna = [], []
    nyt = float(c.iloc[-1])
    yli20 = nyt / float(c.iloc[-20:].mean()) - 1
    r5 = nyt / float(c.iloc[-6]) - 1
    r1 = nyt / float(c.iloc[-2]) - 1
    if strategia.nimi.endswith("lyhyt"):
        if r5 > 0.12 or yli20 > 0.15:
            ohita.append(f"ylikuumentunut (5 pv {r5:+.0%}, {yli20:+.0%} yli 20 pv keskiarvon)")
    elif yli20 > 0.20:
        pienenna.append(f"kurssi {yli20:+.0%} yli 20 pv keskiarvon")
    if r1 > 0.08:
        pienenna.append(f"kurssi hyppäsi päivässä {r1:+.0%} – nousu voi olla jo hinnassa")
    return _tulos(ohita, pienenna)


def riskitarkastaja(strategia, t, paiva, likviditeetti=None, **_):
    ohita, pienenna = [], []
    if likviditeetti is not None and not pd.isna(likviditeetti) and likviditeetti < 500_000:
        pienenna.append(f"vähän kauppaa ({likviditeetti / 1000:.0f} k€/pv)")
    r = np.log(strategia.c.loc[:paiva]).diff().iloc[-60:]
    vol = r[t].std() * np.sqrt(252) if t in r else np.nan
    if not pd.isna(vol) and vol > 0.6:
        pienenna.append(f"erittäin suuri heilunta ({vol:.0%}/v)")
    # Hajautus: jos uusi osake liikkuu lähes samoin kuin jo omistettu, riski kasautuu
    for oma in getattr(strategia, "positiot", {}) or {}:
        if oma in r and t in r:
            k = r[[oma, t]].dropna().corr().iloc[0, 1]
            if not pd.isna(k) and k > 0.75:
                pienenna.append(f"liikkuu samoin kuin omistettu {oma} (korrelaatio {k:.2f})")
    return _tulos(ohita, pienenna)


def ajoitustarkastaja(strategia, t, paiva, **_):
    sig = strategia.sig
    ohita, pienenna = [], []
    if sig.kriisissa(paiva):
        pienenna.append("kriisitila maailmalla")
    if sig.onko_dataa:
        tp = _seuraava_tulosjulkistus(t)
        if tp is not None and pd.Timestamp(paiva) <= tp <= pd.Timestamp(paiva) + pd.Timedelta(days=7):
            (ohita if strategia.nimi.endswith("lyhyt") else pienenna).append(f"tulosjulkistus tulossa {tp.date()}")
    return _tulos(ohita, pienenna)


TARKASTAJAT = {
    "Uutistarkastaja": uutistarkastaja,
    "Kurssitarkastaja": kurssitarkastaja,
    "Riskitarkastaja": riskitarkastaja,
    "Ajoitustarkastaja": ajoitustarkastaja,
}


def arvioi(strategia, ticker: str, paiva: pd.Timestamp, likviditeetti: float | None):
    """Palauttaa (yhteispäätös, syyt, tarkastajakohtaiset tulokset)."""
    tulokset = {}
    for nimi, fn in TARKASTAJAT.items():
        try:
            tulokset[nimi] = fn(strategia, ticker, paiva, likviditeetti=likviditeetti)
        except Exception as e:  # noqa: BLE001  – virhe ei saa päästää ostoa läpi
            tulokset[nimi] = ("ohita", [f"tarkastus epäonnistui ({type(e).__name__})"])
    syyt = [f"{n}: {s}" for n, (_, ss) in tulokset.items() for s in ss]
    ohitukset = sum(1 for v, _ in tulokset.values() if v == "ohita")
    pienennykset = sum(1 for v, _ in tulokset.values() if v == "pienennä")
    if ohitukset or pienennykset >= 3:
        paatos = "ohita"
    elif pienennykset:
        paatos = "pienennä"
    else:
        paatos = "osta"
    return paatos, syyt, {n: v for n, (v, _) in tulokset.items()}
