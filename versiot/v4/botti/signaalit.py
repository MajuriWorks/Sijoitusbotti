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

import dataclasses
import json
from pathlib import Path

from .uutiset import VAKAVA, Uutinen, _hakuavaimet

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


# ---------------------------------------------------------------- v3: uutisten esikäsittely
# Google-haku yhtiön nimellä tuo myös juttuja, jotka eivät koske yhtiötä ("Elisa Schneider dies",
# "Alexandria High School", "gusts target north Georgia", "Ylen kone näyttää"). Monitulkintaisen
# nimen uutiselta vaaditaan taloussana; yksiselitteiset nimet (Nokia, Equinor...) hyväksytään sellaisenaan.
KONTEKSTI = re.compile(
    r"\b(oyj|abp|plc|asa|ab|a/s|corp\w*|inc|ltd|group|konserni\w*|yhtiö\w*|company|companies|firm|"
    r"shares?|stocks?|osake\w*|osakkee\w*|aktie\w*|pörssi\w*|börs\w*|"
    r"ceo|cfo|toimitusjohtaja\w*|johtaja\w*|board|hallitu\w*|chairman|"
    r"results?|tulos\w*|tulokse\w*|earnings|revenue|sales|liikevaihto\w*|myynti\w*|profit\w*|voitto\w*|ebit\w*|"
    r"margin|q[1-4]|quarter\w*|kvartaal\w*|neljännes\w*|osavuosi\w*|interim|half-year|annual|"
    r"guidance|ohjeistu\w*|outlook|näkym\w*|forecast|ennust\w*|"
    r"dividend\w*|osinko\w*|buyback|takaisinosto\w*|"
    r"price target|tavoitehin\w*|suositu\w*|upgrade\w*|downgrade\w*|analyst\w*|analyytik\w*|rating|bullish|bearish|"
    r"acqui\w*|merger|yrityskau\w*|ostotarjou\w*|tender offer|takeover|divest\w*|"
    r"orders?|tilau\w*|contract\w*|sopimu\w*|deal|agreement|investoi\w*|plant|tehda\w*|factory|"
    r"layoffs?|job cuts|yt-\w*|muutosneuvottel\w*|irtisano\w*|lomaut\w*|"
    r"launch\w*|lanseera\w*|patent\w*|fda|"
    r"customers?|asiakka\w*|market share|markkinaosuu\w*|telecom|operaattori\w*|"
    r"lawsuit|fine[sd]?|sakko\w*|probe|investigation|cyber\w*|kyber\w*|"
    r"bonds?|joukkovelka\w*|rahoitu\w*|financing|ipo|listau\w*|"
    r"nasdaq|nyse|omx\w*)\b", re.I)
# Henkilö- ja paikannimet, joita "pienellä kirjaimella" -testi ei tunnista
MONITULKINTAISET = {"ELISA.HE", "ALEX.HE", "ILKKA.HE", "INVE-B.ST", "VIK1V.HE", "SAMPO.HE", "ORNBV.HE",
                    "PNDORA.CO", "ROL", "CMI", "ALB", "IT", "NOW", "LOW", "COST", "NWSA"}
VARMAT_LAHTEET = ("yahoo", "nasdaq", "sisapiiri", "analyytikot")
# Pörssitiedotteet: rutiinit eivät ole uutisia (päivittäiset omien osakkeiden ostot ym.)
RUTIINILUOKAT = {"changes in company's own shares", "financial calendar", "total number of voting rights and capital",
                 "notice to general meeting", "decisions of general meeting", "prospectus/announcement of prospectus",
                 "articles of association", "annual distribution of information"}
RUTIINI = re.compile(r"buy-?back.{0,40}transactions|transactions? in own shares|repurchase of own shares|"
                     r"omien osakkeiden (hankin|osto|luovutu)|financial calendar|taloudellinen kalenteri|"
                     r"final terms|base prospectus|lopulliset ehdot|notice to the (annual|extraordinary) general", re.I)
OSAKEANTI = re.compile(r"rights issue|share issue|directed issue|osakeanti|osakeannin|merkintäetuoikeu", re.I)


def _nimet() -> dict:
    try:
        return json.loads(Path("arkisto/nimet.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def monitulkintaiset_nimet(uutiset: list[Uutinen], nimet: dict) -> set[str]:
    """Yhtiöt, joiden nimi esiintyy otsikoissa usein tavallisena sanana (pienellä alkukirjaimella):
    Tieto ("tieto"), Kone ("kone"), Target ("target"), Titanium, Frontline, Evolution..."""
    n, pieni = {}, {}
    for u in uutiset:
        if u.lahde != "google_yhtiot":
            continue
        for t in u.tickerit:
            for a in _hakuavaimet(t, nimet.get(t, t)):
                a = a.strip()
                if len(a) < 3:
                    continue
                m = re.search(r"(?<![\w])" + re.escape(a), u.otsikko, re.I)
                if m:
                    n[t] = n.get(t, 0) + 1
                    if m.group(0)[0].islower() and m.start() > 0:
                        pieni[t] = pieni.get(t, 0) + 1
                    break
    return MONITULKINTAISET | {t for t, k in n.items() if k >= 8 and pieni.get(t, 0) / k > 0.12}


def esikasittele(uutiset: list[Uutinen], nimet: dict | None = None) -> list[Uutinen]:
    """v3: (1) artikkelin tekstistä luettu tunnelma korvaa otsikon tunnelman, kun se on saatavilla,
    (2) monitulkintaisen nimen osuma hylätään, jos otsikko ei koske liiketoimintaa."""
    nimet = _nimet() if nimet is None else nimet
    monit = monitulkintaiset_nimet(uutiset, nimet)
    # Pörssitiedote suoraan Nasdaqilta korvaa saman päivän Google-kopion (ei tuplapainoa)
    nasdaq = {(t, u.aika[:10], u.tyyppi) for u in uutiset if u.lahde == "nasdaq" for t in u.tickerit}
    out = []
    for u in uutiset:
        if u.lahde == "trump":
            continue      # arkistoidaan, mutta ei käytetä: historiassa ei mitattavaa etua (testattu 11/2026)
        if u.lahde != "nasdaq" and u.tyyppi in ("sisapiiri", "tiedote") and u.tickerit and \
                all((t, u.aika[:10], u.tyyppi) in nasdaq for t in u.tickerit):
            continue
        muutos = {}
        lt = u.lisatieto or {}
        if u.lahde == "nasdaq":
            if (lt.get("luokka") or "").lower() in RUTIINILUOKAT or RUTIINI.search(u.otsikko):
                continue
            if u.tyyppi in ("sisapiiri", "liputus") and "teksti_tunnelma_yhd" not in lt:
                continue  # kaupan suunta (osto/myynti) ei selvinnyt tekstistä
            if OSAKEANTI.search(u.otsikko):
                muutos["tunnelma"] = min(u.tunnelma, -0.3)   # laimentaa omistusta
        if u.tyyppi == "liputus":
            muutos["tyyppi"] = "tiedote"
        if "teksti_tunnelma_yhd" in lt and "tunnelma" not in muutos:
            muutos["tunnelma"] = lt["teksti_tunnelma_yhd"]
            if lt.get("suunta") == "osto":
                muutos["paino"] = max(u.paino, 0.7)
        if u.tickerit and u.lahde not in VARMAT_LAHTEET and u.tyyppi not in ("sisapiiri", "analyytikko", "tiedote"):
            ok = KONTEKSTI.search(u.otsikko) or lt.get("yhtio_tekstissa", 0) >= 2
            pidettavat = [t for t in u.tickerit if t not in monit or ok]
            if len(pidettavat) != len(u.tickerit):
                muutos["tickerit"] = pidettavat
                if not pidettavat and u.tyyppi != "maailma":
                    continue      # ei koske mitään seurattua yhtiötä
        out.append(dataclasses.replace(u, **muutos) if muutos else u)
    return out


class Signaalit:
    def __init__(self, uutiset: list[Uutinen], paivat: pd.DatetimeIndex, tickerit: list[str]):
        uutiset = esikasittele(uutiset)      # v3
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
