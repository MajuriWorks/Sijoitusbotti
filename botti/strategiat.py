"""Botit eli strategiat.

Jokainen strategia vastaa kahteen kysymykseen päätöspäivänä:
  1. Mitkä osakkeet ovat nyt parhaita ostettavaksi (järjestyksessä)?
  2. Mitkä nykyisistä omistuksista kannattaa vielä pitää?
Riskienhallinta (riskit.py) päättää lopulliset kaupat.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .data import Paneeli


@dataclass
class Ehdotus:
    ostettavat: list[str]          # parhaasta huonoimpaan
    pidettavat: set[str]           # nykyiset omistukset, jotka saa pitää
    perustelut: dict[str, str]     # ticker -> selitys


class Strategia:
    nimi = "perus"
    kuvaus = ""

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.min_vaihto = cfg["riskit"].get("min_paivavaihto_eur", 0)

    def valmistele(self, paneeli: Paneeli) -> None:
        """Laskee indikaattorit kerran koko datalle (vain menneisyyttä käyttäen)."""
        raise NotImplementedError

    def onko_paatospaiva(self, paiva: pd.Timestamp, edellinen: str) -> bool:
        raise NotImplementedError

    def ehdota(self, paiva: pd.Timestamp, omistukset: set[str], n: int) -> Ehdotus:
        raise NotImplementedError


def _riittava_historia(c: pd.DataFrame, pv: int = 252) -> pd.DataFrame:
    return c.notna().rolling(pv, min_periods=pv).sum() >= pv


def _likvidi(paneeli: Paneeli, min_vaihto: float) -> pd.DataFrame:
    """Osake kelpaa, jos sen päivävaihdon mediaani 20 pv ajalta ylittää rajan."""
    return paneeli.vaihto.rolling(20, min_periods=10).median() >= min_vaihto


# ====================================================================== Trendi
class Trendi(Strategia):
    nimi = "trendi"
    kuvaus = ("Viikoittain tarkistettava trendinseuraaja. Ostaa osakkeita, joiden kurssi on "
              "nousutrendissä (yli 200 pv keskiarvon) ja jotka ovat nousseet eniten 3 kk aikana. "
              "Myy, kun trendi katkeaa (alle 100 pv keskiarvon) tai osake putoaa kärkijoukosta.")

    def valmistele(self, paneeli: Paneeli) -> None:
        c = paneeli.paatos
        self.c = c
        self.sma50 = c.rolling(50).mean()
        self.sma100 = c.rolling(100).mean()
        self.sma200 = c.rolling(200).mean()
        self.r63 = c / c.shift(63) - 1
        self.ok = _riittava_historia(c) & _likvidi(paneeli, self.min_vaihto)

    def onko_paatospaiva(self, paiva, edellinen):
        if not edellinen:
            return True
        return paiva.isocalendar()[:2] != pd.Timestamp(edellinen).isocalendar()[:2]

    def ehdota(self, paiva, omistukset, n):
        c, s50, s100, s200 = self.c.loc[paiva], self.sma50.loc[paiva], self.sma100.loc[paiva], self.sma200.loc[paiva]
        r = self.r63.loc[paiva].where(self.ok.loc[paiva])
        kelpaa = (c > s200) & (s50 > s200) & (r > 0)
        jarjestys = r.dropna().sort_values(ascending=False)
        sijat = {t: i for i, t in enumerate(jarjestys.index)}
        ostettavat = [t for t in jarjestys.index if kelpaa.get(t, False)]
        raja = max(3 * n, 6)
        pidettavat = {t for t in omistukset
                      if t in sijat and sijat[t] < raja and c.get(t, 0) > s100.get(t, np.inf)}
        perustelut = {t: f"3 kk nousu {r[t]:+.1%}, kurssi {c[t] / s200[t] - 1:+.1%} yli 200 pv keskiarvon"
                      for t in ostettavat[:10]}
        for t in omistukset - pidettavat:
            if c.get(t, 0) <= s100.get(t, 0):
                perustelut[t] = "Trendi katkesi: kurssi alle 100 pv keskiarvon"
            else:
                perustelut[t] = "Pudonnut kärkijoukosta, parempia vaihtoehtoja"
        return Ehdotus(ostettavat, pidettavat, perustelut)


# ================================================================= Rauhallinen
class Rauhallinen(Strategia):
    nimi = "rauhallinen"
    kuvaus = ("Kuukausittain tarkistettava pitkän aikavälin botti. Valitsee osakkeita, jotka ovat "
              "nousseet tasaisesti viimeisen vuoden (12 kk tuotto suhteessa heiluntaan). "
              "Jos koko markkina on laskussa, jää käteiselle. Vaihtaa omistuksia harvoin.")

    def valmistele(self, paneeli: Paneeli) -> None:
        c = paneeli.paatos
        self.c = c
        self.sma200 = c.rolling(200).mean()
        self.mom = c.shift(21) / c.shift(252) - 1
        self.vol = np.log(c).diff().rolling(126).std() * np.sqrt(252)
        self.pisteet = self.mom / self.vol
        self.ok = _riittava_historia(c, 260) & _likvidi(paneeli, self.min_vaihto)

    def onko_paatospaiva(self, paiva, edellinen):
        if not edellinen:
            return True
        e = pd.Timestamp(edellinen)
        return (paiva.year, paiva.month) != (e.year, e.month)

    def ehdota(self, paiva, omistukset, n):
        c, s200 = self.c.loc[paiva], self.sma200.loc[paiva]
        p = self.pisteet.loc[paiva].where(self.ok.loc[paiva])
        m = self.mom.loc[paiva]
        kelpaa = (m > 0) & (c > s200)
        jarjestys = p.dropna().sort_values(ascending=False)
        sijat = {t: i for i, t in enumerate(jarjestys.index)}
        ostettavat = [t for t in jarjestys.index if kelpaa.get(t, False)]
        pidettavat = {t for t in omistukset
                      if t in sijat and sijat[t] < max(2 * n, 4) and c.get(t, 0) > s200.get(t, np.inf)}
        perustelut = {t: f"12 kk nousu {m[t]:+.1%}, heilunta {self.vol.loc[paiva, t]:.0%}/v"
                      for t in ostettavat[:10]}
        for t in omistukset - pidettavat:
            perustelut[t] = ("Pitkä trendi katkesi (alle 200 pv keskiarvon)"
                             if c.get(t, 0) <= s200.get(t, 0) else "Pudonnut kärkijoukosta")
        return Ehdotus(ostettavat, pidettavat, perustelut)


# ===================================================================== Indeksi
class Indeksi(Strategia):
    nimi = "indeksi"
    kuvaus = ("Ostaa maailmanindeksi-ETF:n kerran ja pitää sen. Ei yritä olla fiksu – juuri siksi "
              "se on reilu vertailukohta: aktiivisen botin pitää voittaa tämä kulujen jälkeen.")

    def valmistele(self, paneeli: Paneeli) -> None:
        self.etf = self.cfg["botit"]["indeksi"]["etf"]
        self.c = paneeli.paatos

    def onko_paatospaiva(self, paiva, edellinen):
        if not edellinen:
            return True
        e = pd.Timestamp(edellinen)   # tarkistus kuukausittain; ostaa vain, jos salkku on tyhjä
        return (paiva.year, paiva.month) != (e.year, e.month)

    def ehdota(self, paiva, omistukset, n):
        if self.etf not in self.c.columns or pd.isna(self.c.loc[paiva].get(self.etf)):
            return Ehdotus([], set(omistukset), {})
        return Ehdotus([self.etf], {self.etf}, {self.etf: "Osta ja pidä: koko maailman osakemarkkina"})

    max_positiot = 1
    kayta_stop_lossia = False   # osta ja pidä: ei myydä pudotuksissa


KAIKKI = {"trendi": Trendi, "rauhallinen": Rauhallinen, "indeksi": Indeksi}
