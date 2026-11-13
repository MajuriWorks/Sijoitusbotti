"""Signaalikerros: muuttaa uutiset, tiedotteet, foorumit ja maailman tapahtumat
päivittäisiksi lukuarvoiksi osakkeittain. Kaikki botit käyttävät samoja signaaleja.

Jokainen uutinen on "impulssi" (tunnelma x paino), joka hiipuu ajan myötä:
  - lyhyt muisti (puoliintumisaika 2 pv) -> Lyhyt-botti
  - pitkä muisti (15 pv) -> Pitkä-botti
Signaali voi käyttää vain uutisia, jotka ovat ilmestyneet viimeistään päätöspäivänä.
"""
from __future__ import annotations

from datetime import timezone
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from .uutiset import Uutinen

HKI = ZoneInfo("Europe/Helsinki")
YHTIO_TYYPIT = ("tiedote", "uutinen", "analyytikko", "sisapiiri")


def _hiipuva(impulssit: pd.DataFrame, puoliintuminen: float) -> pd.DataFrame:
    k = 0.5 ** (1 / puoliintuminen)
    arvot = impulssit.to_numpy(dtype=float)
    out = np.zeros_like(arvot)
    edellinen = np.zeros(arvot.shape[1])
    for i in range(len(arvot)):
        edellinen = edellinen * k + arvot[i]
        out[i] = edellinen
    return pd.DataFrame(out, index=impulssit.index, columns=impulssit.columns)


class Signaalit:
    def __init__(self, uutiset: list[Uutinen], paivat: pd.DatetimeIndex, tickerit: list[str]):
        self.paivat, self.tickerit = paivat, tickerit
        self.uutiset = uutiset
        nolla = lambda: pd.DataFrame(0.0, index=paivat, columns=tickerit)  # noqa: E731
        yhtio, analyytikko, sisapiiri, foorumi = nolla(), nolla(), nolla(), nolla()
        maailma = pd.Series(0.0, index=paivat)
        self._otsikot: dict[tuple, list[Uutinen]] = {}

        for u in uutiset:
            i = self._paiva_indeksi(u.aika)
            if i is None:
                continue
            p = paivat[i]
            arvo = u.tunnelma * u.paino
            if u.tyyppi == "maailma" or (not u.tickerit and u.tyyppi != "foorumi"):
                maailma.iloc[i] += arvo
                continue
            for t in u.tickerit:
                if t not in yhtio.columns:
                    continue
                if u.tyyppi == "foorumi":
                    foorumi.at[p, t] += 1 + max(0, arvo)
                    continue
                yhtio.at[p, t] += arvo
                if u.tyyppi == "analyytikko":
                    analyytikko.at[p, t] += arvo
                if u.tyyppi == "sisapiiri":
                    sisapiiri.at[p, t] += arvo
                self._otsikot.setdefault((t, i), []).append(u)

        self.uutis_lyhyt = _hiipuva(yhtio, 2)
        self.uutis_pitka = _hiipuva(yhtio, 15)
        self.analyytikko = _hiipuva(analyytikko, 20)
        self.sisapiiri = _hiipuva(sisapiiri, 45)
        f7 = foorumi.rolling(7, min_periods=1).sum()
        f60 = foorumi.rolling(60, min_periods=1).mean() * 7
        self.foorumi = np.log1p(f7) - np.log1p(f60)        # > 0: keskustellaan tavallista enemmän
        # Maailma: keskiarvo, jotta uutismäärä ei vääristä
        lkm = pd.Series(0.0, index=paivat)
        for u in uutiset:
            if u.tyyppi == "maailma" or (not u.tickerit and u.tyyppi != "foorumi"):
                i = self._paiva_indeksi(u.aika)
                if i is not None:
                    lkm.iloc[i] += 1
        m_s = _hiipuva(maailma.to_frame(), 2).iloc[:, 0]
        m_n = _hiipuva(lkm.to_frame(), 2).iloc[:, 0]
        self.maailma_lyhyt = (m_s / m_n.replace(0, np.nan)).fillna(0)
        m_s = _hiipuva(maailma.to_frame(), 10).iloc[:, 0]
        m_n = _hiipuva(lkm.to_frame(), 10).iloc[:, 0]
        self.maailma_pitka = (m_s / m_n.replace(0, np.nan)).fillna(0)
        self.onko_dataa = len(uutiset) > 0

    @classmethod
    def tyhja(cls, paivat, tickerit) -> "Signaalit":
        """Historiatestiin: uutisia ei ole saatavilla -> kaikki signaalit nollia."""
        return cls([], paivat, tickerit)

    def _paiva_indeksi(self, aika_iso: str):
        try:
            ts = pd.Timestamp(aika_iso)
            if ts.tzinfo is None:
                ts = ts.tz_localize(timezone.utc)
            pv = pd.Timestamp(ts.tz_convert(HKI).date())
        except (ValueError, TypeError):
            return None
        if pv < self.paivat[0] - pd.Timedelta(days=5):
            return None
        i = int(self.paivat.searchsorted(pv))           # ensimmäinen kauppapäivä >= uutisen päivä
        return min(i, len(self.paivat) - 1)

    def tuorein_otsikko(self, ticker: str, paiva: pd.Timestamp, pv: int = 5) -> Uutinen | None:
        """Painavin uutinen viimeisten päivien ajalta (perusteluihin)."""
        i = int(self.paivat.searchsorted(paiva))
        ehdokkaat = []
        for j in range(max(0, i - pv), i + 1):
            ehdokkaat += self._otsikot.get((ticker, j), [])
        if not ehdokkaat:
            return None
        return max(ehdokkaat, key=lambda u: abs(u.tunnelma * u.paino))

    def paivan_uutiset(self, paiva: pd.Timestamp, n: int = 15) -> list[Uutinen]:
        i = int(self.paivat.searchsorted(paiva))
        kaikki = [u for u in self.uutiset if self._paiva_indeksi(u.aika) in (i, i - 1)]
        kaikki.sort(key=lambda u: abs(u.tunnelma * u.paino), reverse=True)
        return kaikki[:n]
