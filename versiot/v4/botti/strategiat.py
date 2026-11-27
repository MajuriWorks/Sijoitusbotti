"""Botit eli strategiat.

Kaikki botit käyttävät SAMAA tietopohjaa:
  - pörssikurssit ja kaupankäyntimäärät
  - yhtiöuutiset ja pörssitiedotteet
  - analyytikkojen suositusmuutokset
  - johdon omat osakekaupat (sisäpiiri)
  - foorumikeskustelut (Inderes, Reddit)
  - maailman tapahtumat ja markkinatunnelma
Erona on aikajänne: Lyhyt reagoi päivittäin, Pitkä katsoo kuukausia.
Yhdistelmä (botit.py) käyttää molempia: 60 % Pitkä + 40 % Lyhyt.
v2: lisäksi teemat (teemat.py) – maailman tapahtumat nostavat hyötyvien ja laskevat kärsivien
toimialojen pisteitä, ja kriisissä hyötyvät toimialat kelpaavat ostettaviksi.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .data import Paneeli
from .signaalit import Signaalit


@dataclass
class Ehdotus:
    ostettavat: list[str]          # parhaasta huonoimpaan
    pidettavat: set[str]           # nykyiset omistukset, jotka saa pitää
    perustelut: dict[str, str]     # ticker -> selitys
    estetty: str = ""              # syy, miksi uusia ostoja ei tehdä
    varovaisuus: str = ""          # kriisi tai synkkä tunnelma: ostetaan vain kestävimpiä


def _sija(df: pd.DataFrame) -> pd.DataFrame:
    """Poikkileikkaussija -0.5 ... +0.5 (kestää ääriarvot)."""
    return df.rank(axis=1, pct=True) - 0.5


def _historia(c: pd.DataFrame, pv: int) -> pd.DataFrame:
    return c.notna().rolling(pv, min_periods=pv).sum() >= pv


def _likvidi(paneeli: Paneeli, min_vaihto: float) -> pd.DataFrame:
    return paneeli.vaihto.rolling(20, min_periods=10).median() >= min_vaihto


class Strategia:
    nimi = "perus"
    kuvaus = ""
    stop_loss: float | None = None         # None = config.yaml riskit.stop_loss_prosentti
    max_positiot: int | None = None        # None = config.yaml riskit.max_positiot

    def __init__(self, cfg: dict, nimi: str | None = None, max_positiot: int | None = None):
        self.cfg = cfg
        self.min_vaihto = cfg["riskit"].get("min_paivavaihto_eur", 0)
        if nimi:
            self.nimi = nimi
        if max_positiot:
            self.max_positiot = max_positiot
        self.positiot = {}                 # moottori asettaa ennen ehdota()-kutsua

    def valmistele(self, paneeli: Paneeli, sig: Signaalit) -> None:
        raise NotImplementedError

    def onko_paatospaiva(self, paiva: pd.Timestamp, edellinen: str) -> bool:
        raise NotImplementedError

    def ehdota(self, paiva: pd.Timestamp, omistukset: set[str], n: int) -> Ehdotus:
        raise NotImplementedError

    # -- yhteiset apurit
    def _uutisteksti(self, t: str, paiva) -> str:
        u = self.sig.tuorein_otsikko(t, paiva)
        if not u:
            return ""
        merkki = "+" if u.tunnelma > 0 else ("−" if u.tunnelma < 0 else "±")
        return f" | uutinen ({merkki}): {u.otsikko[:90]}"

    def _teemateksti(self, t: str, paiva) -> str:
        tm = getattr(self.sig, "teemat", None)
        sel = tm.selitys(t, paiva) if tm is not None else ""
        return f" | teema: {sel}" if sel else ""

    def _markkinasuunta(self, paneeli: Paneeli) -> pd.Series:
        """Helsingin osakkeet tasapainoisesti: onko markkina 200 pv keskiarvon yläpuolella."""
        hel = [t for t in paneeli.paatos.columns if t.endswith(".HE")] or list(paneeli.paatos.columns)
        idx = (1 + paneeli.paatos[hel].pct_change().mean(axis=1).fillna(0)).cumprod()
        return idx > idx.rolling(200, min_periods=100).mean()


# ======================================================================= Lyhyt
class Lyhyt(Strategia):
    nimi = "lyhyt"
    kuvaus = ("v4: kuten v3, mutta kallis osake ostetaan koko rahalla. Lyhyen aikavälin botti. Tarkistaa joka päivä. Ostaa osakkeita, joilla on tuoreita myönteisiä "
              "uutisia tai tiedotteita, analyytikoiden suositusten nostoja tai johdon ostoja, ja joiden kurssi "
              "ja kaupankäynti vahvistavat liikkeen. Pitää päivistä noin kolmeen viikkoon. Ei osta uusia, jos "
              "maailman uutistunnelma on selvästi negatiivinen.")
    stop_loss = 8.0
    max_pito_pv = 15        # kauppapäivää
    min_pito_pv = 3

    def valmistele(self, paneeli, sig):
        self.sig = sig
        c = paneeli.paatos
        self.c, self.sma20, self.sma50 = c, c.rolling(20).mean(), c.rolling(50).mean()
        r5, r20 = c / c.shift(5) - 1, c / c.shift(20) - 1
        self.r5 = r5
        vaihto_piikki = np.log((paneeli.vaihto / paneeli.vaihto.rolling(20, min_periods=10).median()).clip(0.2, 5))
        self.vol = np.log(c).diff().rolling(60).std() * np.sqrt(252)
        u = sig.uutis_lyhyt.reindex_like(c).fillna(0)
        self.uutis = u
        self.pisteet = (0.40 * _sija(r20) + 0.20 * _sija(r5) + 0.10 * vaihto_piikki.clip(-1, 1).fillna(0)
                        + 0.60 * np.tanh(u)
                        + 0.30 * np.tanh(sig.analyytikko.reindex_like(c).fillna(0))
                        + 0.20 * np.tanh(sig.sisapiiri.reindex_like(c).fillna(0))
                        + 0.05 * sig.foorumi.reindex_like(c).fillna(0).clip(-2, 2)
                        + 0.25 * np.tanh(sig.teema.reindex_like(c).fillna(0)))        # v2: teemat
        self.teema = sig.teema.reindex_like(c).fillna(0)
        self.ok = _historia(c, 60) & _likvidi(paneeli, self.min_vaihto)
        self.maailma = sig.maailma_lyhyt.reindex(c.index).fillna(0)
        self.r20 = r20

    def onko_paatospaiva(self, paiva, edellinen):
        return True

    horisontti_pv = 10

    def odotettu(self, t, paiva) -> float | None:
        """Arvio odotetusta tuotosta pitoaikana (osuus): markkinan normaali nousu (~0,3 % / 2 vk)
        + signaalin tuoma etu, joka on suurempi voimakkaasti heiluvissa osakkeissa. Lähtöarvot
        perustuvat tutkimuksiin uutis- ja momentumilmiöistä; ne tarkentuvat, kun ennusteita
        verrataan toteutuneeseen (raportti: Ennuste vs. toteutunut)."""
        p, vol = self.pisteet.at[paiva, t], self.vol.at[paiva, t]
        if pd.isna(p) or pd.isna(vol):
            return None
        return float(0.003 + 0.04 * np.clip(p, 0, 1.5) / 1.5 * np.clip(vol / 0.30, 0.5, 2.0))

    def ehdota(self, paiva, omistukset, n):
        c, s20, s50 = self.c.loc[paiva], self.sma20.loc[paiva], self.sma50.loc[paiva]
        p = self.pisteet.loc[paiva].where(self.ok.loc[paiva])
        u = self.uutis.loc[paiva]
        kelpaa = (c > s20) & (c > s50) & (u > -0.2) & (self.vol.loc[paiva] < 0.8)
        if self.sig.onko_dataa:
            # Uutisdata käytössä: lyhyt kauppa vaatii tuoreen myönteisen uutisen (kulut ovat suuret)
            kelpaa &= u > 0.15
        jarjestys = p.dropna().sort_values(ascending=False)
        sijat = {t: i for i, t in enumerate(jarjestys.index)}
        varovaisuus = ""
        if self.sig.kriisissa(paiva):
            varovaisuus = f"Kriisitila: vakavia maailmanuutisia {self.sig.kriisitaso.loc[paiva]:.1f}x tavallista"
        elif self.maailma.loc[paiva] < -0.3:
            varovaisuus = f"Maailman uutistunnelma synkkä ({self.maailma.loc[paiva]:+.2f})"
        if varovaisuus:
            # Ostetaan vain selvästi myönteisten uutisten osakkeita, jotka ovat pitäneet pintansa markkinaa paremmin
            r5 = self.r5.loc[paiva]
            te = self.teema.loc[paiva]
            # v2: kriisistä hyötyvät toimialat (esim. puolustus sodassa) kelpaavat myös
            kelpaa &= ((u > 0.4) & (r5 > r5.median())) | ((te > 0.5) & (u >= 0))
            varovaisuus += " – ostetaan vain vahvan uutisen ja markkinaa paremmin pärjänneitä osakkeita"
        ostettavat = [t for t in jarjestys.index if kelpaa.get(t, False)]

        pidettavat, perustelut = set(), {}
        ind = self.c.index
        for t in omistukset:
            pos = self.positiot.get(t)
            pito = (ind.searchsorted(paiva) - ind.searchsorted(pd.Timestamp(pos.ostopaiva))) if pos else 0
            if pito < self.min_pito_pv:
                pidettavat.add(t)
            elif pito >= self.max_pito_pv and abs(c.get(t, 0) / pos.hankintahinta - 1) < 0.03:
                # v3: aikaraja koskee vain "kuollutta rahaa": jos osake ei ole liikkunut mihinkään
                # 15 päivässä, raha siirretään parempaan kohteeseen. Nousevaa ei myydä ajan takia.
                perustelut[t] = f"Ei liikettä {pito} kauppapäivässä – raha parempaan kohteeseen"
            elif u.get(t, 0) < -0.3:
                perustelut[t] = "Negatiivinen uutinen" + self._uutisteksti(t, paiva)
            elif c.get(t, 0) < s20.get(t, np.inf):
                perustelut[t] = "Lyhyt trendi katkesi (alle 20 pv keskiarvon)"
            elif sijat.get(t, 10**6) >= 25 and u.get(t, 0) <= 0:
                perustelut[t] = "Uutisvire hiipunut ja signaali heikentynyt"
            else:
                pidettavat.add(t)
        for t in ostettavat[:10]:
            perustelut[t] = (f"pisteet {p[t]:+.2f}, 20 pv nousu {self.r20.loc[paiva, t]:+.1%}"
                             + self._uutisteksti(t, paiva) + self._teemateksti(t, paiva))
        return Ehdotus(ostettavat, pidettavat, perustelut, varovaisuus=varovaisuus)


# ======================================================================= Pitkä
class Pitka(Strategia):
    nimi = "pitka"
    kuvaus = ("v3: teemat, kriisi osuutena. Pitkän aikavälin botti. Tarkistaa kerran kuussa. Valitsee osakkeita, jotka ovat nousseet "
              "tasaisesti vuoden ajan ja joista uutiset, analyytikot ja johdon omat kaupat ovat viime viikkoina "
              "olleet myönteisiä. Välttää jo valmiiksi ylikuumentuneita pienyhtiöitä. Jää käteiselle, jos "
              "markkina on laskutrendissä ja maailman uutistunnelma negatiivinen.")

    def valmistele(self, paneeli, sig):
        self.sig = sig
        c = paneeli.paatos
        self.c, self.sma200 = c, c.rolling(200).mean()
        self.mom = c.shift(21) / c.shift(252) - 1
        self.vol = np.log(c).diff().rolling(126).std() * np.sqrt(252)
        self.uutis = sig.uutis_pitka.reindex_like(c).fillna(0)
        self.pisteet = (_sija(self.mom / self.vol)
                        + 0.40 * np.tanh(self.uutis / 2)
                        + 0.30 * np.tanh(sig.analyytikko.reindex_like(c).fillna(0))
                        + 0.30 * np.tanh(sig.sisapiiri.reindex_like(c).fillna(0))
                        + 0.35 * np.tanh(sig.teema.reindex_like(c).fillna(0)))        # v2: teemat
        self.teema = sig.teema.reindex_like(c).fillna(0)
        self.ok = _historia(c, 260) & _likvidi(paneeli, self.min_vaihto)
        self.kuuma = (self.mom > 1.5) | (self.vol > 0.6)
        self.nousu = self._markkinasuunta(paneeli)
        self.maailma = sig.maailma_pitka.reindex(c.index).fillna(0)

    def onko_paatospaiva(self, paiva, edellinen):
        if not edellinen:
            return True
        e = pd.Timestamp(edellinen)
        return (paiva.year, paiva.month) != (e.year, e.month)

    horisontti_pv = 63

    def odotettu(self, t, paiva) -> float | None:
        p, vol = self.pisteet.at[paiva, t], self.vol.at[paiva, t]
        if pd.isna(p) or pd.isna(vol):
            return None
        # Markkinan normaali nousu (~2 % / 3 kk) + kärkiosakkeiden momentum- ja uutisetu
        return float(0.02 + 0.06 * np.clip(p, 0, 1.0))

    def ehdota(self, paiva, omistukset, n):
        c, s200 = self.c.loc[paiva], self.sma200.loc[paiva]
        p = self.pisteet.loc[paiva].where(self.ok.loc[paiva])
        m, u = self.mom.loc[paiva], self.uutis.loc[paiva]
        kelpaa = (m > 0) & (c > s200) & (~self.kuuma.loc[paiva]) & (u > -0.5)
        jarjestys = p.dropna().sort_values(ascending=False)
        sijat = {t: i for i, t in enumerate(jarjestys.index)}
        varovaisuus = ""
        if self.sig.kriisissa(paiva):
            varovaisuus = f"Kriisitila: vakavia maailmanuutisia {self.sig.kriisitaso.loc[paiva]:.1f}x tavallista"
        elif not bool(self.nousu.loc[paiva]) and self.maailma.loc[paiva] < -0.15:
            varovaisuus = "Markkina laskutrendissä ja maailman uutistunnelma synkkä"
        if varovaisuus:
            # Puolustava valinta: vähän heiluvat osakkeet, joista ei ole kielteisiä uutisia
            te = self.teema.loc[paiva]
            kelpaa &= ((self.vol.loc[paiva] < 0.35) & (u >= 0)) | ((te > 0.5) & (u >= 0))
            varovaisuus += " – ostetaan vain vakaita osakkeita, joista ei ole kielteisiä uutisia"
        ostettavat = [t for t in jarjestys.index if kelpaa.get(t, False)]
        pidettavat, perustelut = set(), {}
        for t in omistukset:
            if c.get(t, 0) <= s200.get(t, np.inf):
                perustelut[t] = "Pitkä trendi katkesi (alle 200 pv keskiarvon)"
            elif u.get(t, 0) < -0.5:
                perustelut[t] = "Uutisvirta selvästi negatiivinen" + self._uutisteksti(t, paiva)
            elif sijat.get(t, 10**6) >= max(3 * n, 6):
                perustelut[t] = "Pudonnut kärkijoukosta"
            else:
                pidettavat.add(t)
        for t in ostettavat[:10]:
            perustelut[t] = (f"12 kk nousu {m[t]:+.1%}, heilunta {self.vol.loc[paiva, t]:.0%}/v"
                             + self._uutisteksti(t, paiva) + self._teemateksti(t, paiva))
        return Ehdotus(ostettavat, pidettavat, perustelut, varovaisuus=varovaisuus)


# ===================================================================== Indeksi
class Indeksi(Strategia):
    nimi = "indeksi"
    kuvaus = ("Vertailukohta: ostaa maailmanindeksi-ETF:n kerran ja pitää sen. Ei yritä olla fiksu – "
              "juuri siksi se on reilu mittari: bottien pitää voittaa tämä kulujen jälkeen.")
    max_positiot = 1
    kayta_stop_lossia = False

    def valmistele(self, paneeli, sig):
        self.etf = self.cfg["botit"]["indeksi"]["etf"]
        self.c = paneeli.paatos

    def onko_paatospaiva(self, paiva, edellinen):
        if not edellinen:
            return True
        e = pd.Timestamp(edellinen)
        return (paiva.year, paiva.month) != (e.year, e.month)

    def ehdota(self, paiva, omistukset, n):
        if self.etf not in self.c.columns or pd.isna(self.c.loc[paiva].get(self.etf)):
            return Ehdotus([], set(omistukset), {})
        return Ehdotus([self.etf], {self.etf}, {self.etf: "Osta ja pidä: koko maailman osakemarkkina"})


STRATEGIAT = {"lyhyt": Lyhyt, "pitka": Pitka, "indeksi": Indeksi}
