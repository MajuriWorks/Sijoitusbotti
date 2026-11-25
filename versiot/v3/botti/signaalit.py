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

import re

from .uutiset import VAKAVA, Uutinen

# v3: otsikko, joka kertoo kriisin päättyneen tai jääneen vaikutuksettomaksi, ei ole hätäuutinen
# (esim. "Equinor says cyberattack has stopped; production unaffected" laukaisi v1:ssä hätämyynnin)
RAUHOITTAVA = re.compile(
    r"\b(unaffected|not affected|no (material |financial )?(impact|effect)|without impact|has (been )?stopped|"
    r"(was|were|been|is) stopped|stopped after|ended|is over|resolved|restored|contained|under control|"
    r"back to normal|resum\w+|lifted|dropped (charges|probe|lawsuit)|charges dropped|cleared|acquitted|"
    r"dismiss\w+|settle[sd]?|rejects? (claims?|allegations?)|denies|false alarm|"
    r"ei vaikut\w*|ei vaikuta|päättyi|päättynyt|ohi\b|saatu hallintaan|palautettu|palautui|jatkuu normaalisti|"
    r"hylät\w*|vapautet\w*)\b", re.I)

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


def _onko_maailma(u: Uutinen) -> bool:
    return (u.lahde in ("maailma", "testi", "suuret_mediat", "rss_syotteet", "jattiyhtiot") and not u.tickerit) \
        or u.tyyppi == "maailma"


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
            if _onko_maailma(u):
                maailma.iloc[i] += arvo
                continue
            if not u.tickerit:
                continue      # yleishaun uutinen, jossa ei mainita seurattua yhtiötä
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
            if _onko_maailma(u):
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

        # Vakavat kielteiset uutiset: kriisitaso (maailma) ja hätäsignaali (yhtiöt)
        vakava_maailma = pd.Series(0.0, index=paivat)
        vakava = nolla()
        self.vakavat_otsikot: dict[tuple, Uutinen] = {}
        # v3: yhtiöuutisten vakavuus arvioidaan samalla säännöllä kaikille uutisille (arkiston merkintä
        # riippui siitä, millä koodilla uutinen kerättiin) ja rauhoittavat otsikot jätetään pois.
        # Maailmanuutiset (kriisitaso) lasketaan kuten ennen.
        vakava_yhtio = pd.DataFrame(False, index=paivat, columns=list(tickerit))
        for u in uutiset:
            merkitty = bool(u.lisatieto.get("vakava"))
            yhtio_vakava = (merkitty or (u.tunnelma < -0.2 and bool(VAKAVA.search(u.otsikko)))) \
                and not RAUHOITTAVA.search(u.otsikko)
            if not merkitty and not yhtio_vakava:
                continue
            i = self._paiva_indeksi(u.aika)
            if i is None:
                continue
            if merkitty and _onko_maailma(u):
                vakava_maailma.iloc[i] += 1
            if not yhtio_vakava:
                continue
            for t in u.tickerit:
                if t in vakava.columns:
                    vakava_yhtio.iat[i, vakava_yhtio.columns.get_loc(t)] = True
                    vakava.iat[i, vakava.columns.get_loc(t)] += u.tunnelma * max(u.paino, 0.9)
                    vanha = self.vakavat_otsikot.get((t, i))
                    if vanha is None or u.tunnelma < vanha.tunnelma:
                        self.vakavat_otsikot[(t, i)] = u
        self.vakava = _hiipuva(vakava, 1)
        # v3: jatkouutisointi = samasta yhtiöstä vakavia uutisia jo 2–5 kauppapäivää aiemmin
        aiemmat = vakava_yhtio.astype(int).shift(2).rolling(4, min_periods=1).sum().fillna(0)
        self.jatkouutinen = aiemmat > 0
        # Kriisitaso = vakavien maailmanuutisten määrä suhteessa tavalliseen (1 = normaali päivä)
        # Vertailutaso lasketaan vain päiviltä, joilta uutisia on kerätty, ja vasta kun niitä on
        # vähintään 10 (muuten uusien lähteiden lisääminen näyttäisi kriisiltä).
        keratty = lkm.copy()
        for u in uutiset:
            i = self._paiva_indeksi(u.aika)
            if i is not None:
                keratty.iloc[i] += 1
        # v3: kriisitaso = vakavien OSUUS kaikista maailmanuutisista suhteessa tavalliseen osuuteen.
        # Uutislähteiden määrän kasvu ei näin näytä kriisiltä.
        kaikki_maailma = pd.Series(0.0, index=paivat)
        for u in uutiset:
            if _onko_maailma(u):
                i = self._paiva_indeksi(u.aika)
                if i is not None:
                    kaikki_maailma.iloc[i] += 1
        osuus = (vakava_maailma / kaikki_maailma.where(kaikki_maailma >= 20)).where(keratty.cumsum() > 0)
        perus = osuus.rolling(20, min_periods=10).median().shift(1)
        self.vakavat_maailma = vakava_maailma
        self.kriisitaso = (osuus / perus.clip(lower=0.02)).fillna(0)

        # v2: teemat – mitä maailman tapahtumat tarkoittavat eri toimialoille
        try:
            from .teemat import Teemat
            self.teemat = Teemat(uutiset, paivat, tickerit, self._paiva_indeksi)
            self.teema = self.teemat.signaali.reindex(index=paivat, columns=tickerit).fillna(0)
        except Exception as e:  # noqa: BLE001
            print(f"  ! teemojen laskenta epäonnistui: {e}")
            self.teemat = None
            self.teema = nolla()

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

    def kriisissa(self, paiva) -> bool:
        """Poikkeuksellisen paljon vakavia maailmanuutisia (sodat, katastrofit, romahdukset)."""
        return bool(self.kriisitaso.loc[paiva] >= 2.0 and self.vakavat_maailma.loc[paiva] >= 8)

    # v3: hätämyynti vaatii, että kurssi vahvistaa uutisen (vähintään -3 % kahdessa päivässä).
    # Otsikoiden määrä ei kerro vakavuudesta (jättiyhtiöstä kirjoitetaan kymmeniä juttuja), markkina kertoo.
    # Aamulla ennen avausta kurssireaktiota ei vielä ole -> aamutarkistus vain peruu ostoja.
    HATA_RAJA = -0.4
    HATA_KURSSIRAJA = -0.03

    def hatauutinen(self, ticker: str, paiva, kurssimuutos: float | None = None) -> Uutinen | None:
        """Vakava kielteinen uutinen yhtiöstä viimeisen päivän aikana -> myydään heti.
        kurssimuutos = osakkeen 2 päivän kurssimuutos (None = ei tiedossa, esim. aamulla ennen avausta)."""
        if ticker not in self.vakava.columns:
            return None
        taso = self.vakava.at[paiva, ticker]
        if taso > self.HATA_RAJA:
            return None
        if bool(self.jatkouutinen.at[paiva, ticker]):
            return None          # sama tapahtuma jatkuu: hätämyynnin hetki oli jo, stop-loss suojaa edelleen
        vahvistettu = kurssimuutos is not None and not pd.isna(kurssimuutos) and kurssimuutos <= self.HATA_KURSSIRAJA
        if not vahvistettu:
            return None
        i = int(self.paivat.searchsorted(paiva))
        return self.vakavat_otsikot.get((ticker, i)) or self.vakavat_otsikot.get((ticker, i - 1))

    def kielteinen_uutinen(self, ticker: str, paiva) -> bool:
        if ticker not in self.uutis_lyhyt.columns:
            return False
        # v3: ostoa perutaan jo pelkästä vakavasta uutisesta (ei vaadita kurssireaktiota)
        return bool(self.uutis_lyhyt.at[paiva, ticker] < -0.2) or bool(
            ticker in self.vakava.columns and self.vakava.at[paiva, ticker] <= self.HATA_RAJA)

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
