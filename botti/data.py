"""Kurssidatan haku (Yahoo Finance), valuuttamuunnokset ja välimuisti.

Kaikki hinnat muunnetaan euroiksi. Palauttaa "paneelin": avaus- ja päätöskurssit
sekä päivävaihto euroina (rivit = päivät, sarakkeet = osakkeet).
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

CACHE_MAX_AGE_H = 12
ERA = 40  # montako tunnusta haetaan yhdellä pyynnöllä

# Pörssin pääte -> (kulumarkkina, valuutta)
PAATTEET = {
    ".HE": ("helsinki", "EUR"),
    ".ST": ("pohjoismaat", "SEK"),
    ".OL": ("pohjoismaat", "NOK"),
    ".CO": ("pohjoismaat", "DKK"),
    ".DE": ("eurooppa", "EUR"),
    ".AS": ("eurooppa", "EUR"),
    ".PA": ("eurooppa", "EUR"),
    ".MI": ("eurooppa", "EUR"),
}
FX_TUNNUS = {"SEK": "EURSEK=X", "NOK": "EURNOK=X", "DKK": "EURDKK=X", "USD": "EURUSD=X"}


def _paate(ticker: str) -> tuple[str, str]:
    t = ticker.upper()
    for p, v in PAATTEET.items():
        if t.endswith(p):
            return v
    return ("usa", "USD")


def markkina(ticker: str) -> str:
    return _paate(ticker)[0]


def valuutta(ticker: str) -> str:
    return _paate(ticker)[1]


@dataclass
class Paneeli:
    avaus: pd.DataFrame
    paatos: pd.DataFrame
    vaihto: pd.DataFrame                      # päivävaihto euroina
    puuttuvat: list[str] = field(default_factory=list)
    matala: pd.DataFrame | None = None        # päivän alin kurssi (rajahintaostoja varten)

    def __post_init__(self):
        if self.matala is None:
            self.matala = pd.concat([self.avaus, self.paatos]).groupby(level=0).min().reindex(self.paatos.index)

    def asti(self, paiva) -> "Paneeli":
        return Paneeli(self.avaus.loc[:paiva], self.paatos.loc[:paiva], self.vaihto.loc[:paiva],
                       self.puuttuvat, self.matala.loc[:paiva])

    def ilman_viimeista(self) -> "Paneeli":
        return Paneeli(self.avaus.iloc[:-1], self.paatos.iloc[:-1], self.vaihto.iloc[:-1],
                       self.puuttuvat, self.matala.iloc[:-1])

    def osajoukko(self, tickerit: list[str]) -> "Paneeli":
        cols = [t for t in tickerit if t in self.paatos.columns]
        return Paneeli(self.avaus[cols], self.paatos[cols], self.vaihto[cols], self.puuttuvat, self.matala[cols])

    @property
    def tickerit(self) -> list[str]:
        return list(self.paatos.columns)


# ---------------------------------------------------------------- Yahoo
def _cache_polku(cache_dir: Path, ticker: str) -> Path:
    return cache_dir / f"{ticker.replace('^', '_').replace('=', '_')}.csv"


def _siisti(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty or "Close" not in df:
        return pd.DataFrame()
    df = df[["Open", "High", "Low", "Close", "Volume"]].dropna(subset=["Close"])
    df.index = pd.to_datetime(df.index).tz_localize(None)
    return df


def _lataa_yahoo(tickerit: list[str], alku: str, cache_dir: Path) -> dict[str, pd.DataFrame]:
    """Hakee usean tunnuksen datan. Käyttää välimuistia, hakee puuttuvat erissä."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    tulos, haettavat = {}, []
    for t in tickerit:
        f = _cache_polku(cache_dir, t)
        if f.exists() and (time.time() - f.stat().st_mtime) < CACHE_MAX_AGE_H * 3600:
            tulos[t] = pd.read_csv(f, index_col=0, parse_dates=True)
        else:
            haettavat.append(t)
    if not haettavat:
        return tulos

    try:
        import yfinance as yf
    except ImportError as e:  # pragma: no cover
        raise SystemExit("Asenna ensin: pip install -r requirements.txt") from e

    for i in range(0, len(haettavat), ERA):
        era = haettavat[i:i + ERA]
        for yritys in range(3):  # Yahoo hylkää välillä pyyntöjä -> yritetään uudelleen
            try:
                raaka = yf.download(era, start=alku, auto_adjust=True, progress=False,
                                    group_by="ticker", threads=True)
            except Exception as e:  # noqa: BLE001
                print(f"  ! haku epäonnistui ({e}), yritetään uudelleen")
                raaka = None
            if raaka is not None and not raaka.empty:
                break
            time.sleep(10 * (yritys + 1))
        for t in era:
            try:
                df = raaka[t] if (raaka is not None and isinstance(raaka.columns, pd.MultiIndex)) else raaka
                df = _siisti(df)
            except (KeyError, TypeError):
                df = pd.DataFrame()
            if not df.empty:
                df.to_csv(_cache_polku(cache_dir, t))
                tulos[t] = df
        time.sleep(1)
    return tulos


def lataa_paneeli(tickerit: list[str], alku: str, cache_dir: str | Path = "data") -> Paneeli:
    cache_dir = Path(cache_dir)
    tarvittavat_fx = sorted({valuutta(t) for t in tickerit} - {"EUR"})
    fx_data = _lataa_yahoo([FX_TUNNUS[v] for v in tarvittavat_fx], alku, cache_dir)
    fx = {v: fx_data[FX_TUNNUS[v]]["Close"] for v in tarvittavat_fx if FX_TUNNUS[v] in fx_data}
    if "DKK" in tarvittavat_fx and "DKK" not in fx:
        fx["DKK"] = pd.Series(7.46, index=pd.bdate_range(alku, pd.Timestamp.today()))  # kruunu on sidottu euroon

    data = _lataa_yahoo(tickerit, alku, cache_dir)
    avaus, paatos, vaihto, puuttuvat, matala = {}, {}, {}, [], {}
    for t in tickerit:
        df = data.get(t)
        if df is None or df.empty:
            puuttuvat.append(t)
            continue
        v = valuutta(t)
        o, c, lo = df["Open"], df["Close"], df["Low"]
        if v != "EUR":
            if v not in fx:
                puuttuvat.append(t)
                continue
            k = fx[v].reindex(df.index).ffill().bfill()   # EURxxx: 1 € = k xxx
            o, c, lo = o / k, c / k, lo / k
        avaus[t], paatos[t], vaihto[t], matala[t] = o, c, c * df["Volume"], lo

    if puuttuvat:
        print(f"  ! Ei kursseja {len(puuttuvat)} tunnukselle: {', '.join(puuttuvat)}")
    if len(paatos) < 0.5 * len(tickerit):
        # Ei jatketa vajaalla datalla, ettei leikkisalkku tee päätöksiä puuttuvien kurssien varassa.
        raise SystemExit(f"Kurssit saatiin vain {len(paatos)}/{len(tickerit)} tunnukselle – keskeytetään. "
                         "Yritä myöhemmin uudelleen.")
    return _kokoa(avaus, paatos, vaihto, puuttuvat, matala)


def _kokoa(avaus: dict, paatos: dict, vaihto: dict, puuttuvat=None, matala=None) -> Paneeli:
    p = pd.DataFrame(paatos).sort_index()
    a = pd.DataFrame(avaus).reindex(p.index)
    v = pd.DataFrame(vaihto).reindex(p.index)
    # Päätöskurssi viedään eteenpäin enintään 5 päivää (pyhäpäivät eri pörsseissä).
    # Avauskurssia EI täytetä: jos osake ei käy kauppaa, toimeksianto odottaa.
    p = p.ffill(limit=5)
    m = pd.DataFrame(matala).reindex(p.index) if matala else None
    return Paneeli(a, p, v, list(puuttuvat or []), m)


# ---------------------------------------------------------------- Testidata
def synteettinen_paneeli(tickerit: list[str], alku="2016-01-01", loppu="2026-11-13", siemen=1) -> Paneeli:
    """Keksitty kurssidata koodin testaamiseen ilman verkkoyhteyttä.
    Sisältää markkinatekijän, osakekohtaisia trendejä, romahduksia ja vähän vaihdettuja osakkeita."""
    rng = np.random.default_rng(siemen)
    paivat = pd.bdate_range(alku, loppu)
    n = len(paivat)
    markkina_tuotto = rng.normal(0.0003, 0.010, n)
    for alku_i in (int(n * 0.42), int(n * 0.65)):
        markkina_tuotto[alku_i:alku_i + 60] -= 0.004
    avaus, paatos, vaihto, matala = {}, {}, {}, {}
    for t in tickerit:
        drift = rng.normal(0.0001, 0.0004)
        beta = rng.uniform(0.6, 1.4)
        trendi = np.convolve(rng.normal(0, 0.0006, n), np.ones(120) / 120 * 10, mode="same")
        oma = rng.normal(0, rng.uniform(0.010, 0.022), n)
        r = drift + beta * markkina_tuotto + trendi + oma
        hinta = 20 * np.exp(np.cumsum(r)) * rng.uniform(0.3, 3)
        gap = rng.normal(0, 0.004, n)
        paatos[t] = pd.Series(hinta, paivat)
        avaus[t] = pd.Series(np.r_[hinta[0], hinta[:-1]] * np.exp(gap), paivat)
        matala[t] = np.minimum(avaus[t], paatos[t]) * (1 - np.abs(rng.normal(0, 0.008, n)))
        taso = 10 ** rng.uniform(4.5, 7.5)            # 30 k€ ... 30 M€ päivässä
        vaihto[t] = pd.Series(taso * rng.lognormal(0, 0.5, n), paivat)
    return _kokoa(avaus, paatos, vaihto, None, matala)
