"""Leikkivälittäjä: Nordnetin kulumalli, salkku ja toimeksiantojen toteutus.

Kaikki kaupat tehdään kokonaisina osakkeina. Toimeksianto annetaan päivän
päätöskurssin jälkeen ja toteutetaan SEURAAVAN kauppapäivän avauskurssiin
(näin et voi vahingossa "nähdä tulevaisuuteen").
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, asdict

import pandas as pd

from .data import markkina


# ---------------------------------------------------------------- Kulut
class Kulumalli:
    def __init__(self, kulut_cfg: dict):
        self.cfg = kulut_cfg

    def kulu(self, ticker: str, summa: float) -> float:
        c = self.cfg[markkina(ticker)]
        valitys = max(c["minimi"], summa * c["prosentti"] / 100)
        if "katto_alle" in c and summa < c["katto_alle"]:
            valitys = min(valitys, summa * c["katto_prosentti"] / 100)
        valuutta = summa * c.get("valuutanvaihto_prosentti", 0) / 100
        return round(valitys + valuutta, 2)

    def pienin_jarkeva_kauppa(self, ticker: str, max_kulu_pct: float) -> float:
        """Pienin kauppasumma, jolla kulu on enintään max_kulu_pct %."""
        for summa in range(10, 20001, 10):
            if self.kulu(ticker, summa) <= summa * max_kulu_pct / 100:
                return float(summa)
        return float("inf")


# ---------------------------------------------------------------- Tietorakenteet
@dataclass
class Toimeksianto:
    ticker: str
    suunta: str            # "OSTA" / "MYY"
    summa: float = 0.0     # ostoille: tavoitesumma euroina
    kpl: int = 0           # myynneille: kappalemäärä
    syy: str = ""
    annettu: str = ""      # päivämäärä
    rajahinta: float = 0.0 # ostoille: korkein hyväksytty hinta (0 = markkinahintaan)
    voimassa: int = 3      # ostoille: montako kauppapäivää rajahintatoimeksianto odottaa


@dataclass
class Positio:
    kpl: int
    hankintahinta: float   # sis. kulut, per osake
    ostopaiva: str
    huippu: float


@dataclass
class Kauppa:
    paiva: str
    ticker: str
    suunta: str
    kpl: int
    hinta: float
    kulu: float
    syy: str
    voitto: float | None = None
    pitoaika_pv: int | None = None


@dataclass
class Salkku:
    kateinen: float
    positiot: dict[str, Positio] = field(default_factory=dict)
    odottavat: list[Toimeksianto] = field(default_factory=list)
    kaupat: list[Kauppa] = field(default_factory=list)
    kulut_yht: float = 0.0
    arvohistoria: dict[str, float] = field(default_factory=dict)
    viimeisin_paatos: str = ""

    # -- arvo
    def arvo(self, hinnat: pd.Series) -> float:
        return self.kateinen + sum(p.kpl * float(hinnat.get(t, p.hankintahinta)) for t, p in self.positiot.items())

    # -- tallennus
    def to_dict(self) -> dict:
        return {
            "kateinen": self.kateinen,
            "positiot": {t: asdict(p) for t, p in self.positiot.items()},
            "odottavat": [asdict(o) for o in self.odottavat],
            "kaupat": [asdict(k) for k in self.kaupat],
            "kulut_yht": self.kulut_yht,
            "arvohistoria": self.arvohistoria,
            "viimeisin_paatos": self.viimeisin_paatos,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Salkku":
        return cls(
            kateinen=d["kateinen"],
            positiot={t: Positio(**p) for t, p in d["positiot"].items()},
            odottavat=[Toimeksianto(**o) for o in d["odottavat"]],
            kaupat=[Kauppa(**k) for k in d["kaupat"]],
            kulut_yht=d["kulut_yht"],
            arvohistoria=d.get("arvohistoria", {}),
            viimeisin_paatos=d.get("viimeisin_paatos", ""),
        )


# ---------------------------------------------------------------- Toteutus
class LeikkiValittaja:
    def __init__(self, kulut: Kulumalli):
        self.kulut = kulut

    @staticmethod
    def hintaero(vaihto_eur: float | None) -> float:
        """Arvio osto- ja myyntihinnan erotuksen puolikkaasta (osuutena hinnasta).
        Vähän vaihdetuissa osakkeissa ero on suuri: ostaja maksaa enemmän ja myyjä saa vähemmän
        kuin "kurssi" näyttää."""
        if vaihto_eur is None or pd.isna(vaihto_eur):
            return 0.004
        if vaihto_eur >= 20e6:
            return 0.0005
        if vaihto_eur >= 5e6:
            return 0.001
        if vaihto_eur >= 1e6:
            return 0.002
        if vaihto_eur >= 300e3:
            return 0.004
        return 0.007

    def toteuta(self, salkku: Salkku, paiva: pd.Timestamp, avaus: pd.Series,
                matala: pd.Series | None = None, vaihto: pd.Series | None = None) -> list[Kauppa]:
        """Toteuttaa odottavat toimeksiannot päivän avauskurssiin. Myynnit ensin.
        Ostot ovat rajahintatoimeksiantoja: jos kurssi avaa rajan yläpuolella, osto toteutuu
        rajahintaan vain, jos päivän alin kurssi käy rajassa. Muuten toimeksianto odottaa."""
        tehdyt, jaljelle = [], []
        jarjestys = sorted(salkku.odottavat, key=lambda o: o.suunta != "MYY")
        for o in jarjestys:
            hinta = avaus.get(o.ticker)
            if hinta is None or pd.isna(hinta) or hinta <= 0:
                jaljelle.append(o)          # ei kauppaa tänään -> odottaa
                continue
            ero = self.hintaero(vaihto.get(o.ticker) if vaihto is not None else None)
            # Ostaja maksaa myyntitarjouksen hinnan, myyjä saa ostotarjouksen hinnan
            hinta = float(hinta) * (1 + ero if o.suunta == "OSTA" else 1 - ero)
            ps = paiva.strftime("%Y-%m-%d")
            if o.suunta == "OSTA" and o.rajahinta > 0 and hinta > o.rajahinta:
                # Avaus rajahinnan yläpuolella: toteutuu vain, jos kurssi käy päivän aikana rajassa
                alin = matala.get(o.ticker) if matala is not None else None
                if alin is not None and not pd.isna(alin) and float(alin) * (1 + ero) <= o.rajahinta:
                    hinta = o.rajahinta
                else:
                    o.voimassa -= 1
                    if o.voimassa > 0:
                        jaljelle.append(o)   # odottaa notkahdusta
                    continue
            if o.suunta == "MYY":
                pos = salkku.positiot.get(o.ticker)
                if not pos:
                    continue
                kpl = min(o.kpl or pos.kpl, pos.kpl)
                summa = kpl * hinta
                kulu = self.kulut.kulu(o.ticker, summa)
                salkku.kateinen += summa - kulu
                salkku.kulut_yht += kulu
                voitto = summa - kulu - kpl * pos.hankintahinta
                pitoaika = (paiva - pd.Timestamp(pos.ostopaiva)).days
                k = Kauppa(ps, o.ticker, "MYY", kpl, hinta, kulu, o.syy, round(voitto, 2), pitoaika)
                pos.kpl -= kpl
                if pos.kpl <= 0:
                    del salkku.positiot[o.ticker]
            else:
                kaytettava = min(o.summa, salkku.kateinen)
                kpl = math.floor(kaytettava / hinta)
                while kpl > 0 and kpl * hinta + self.kulut.kulu(o.ticker, kpl * hinta) > salkku.kateinen:
                    kpl -= 1
                if kpl <= 0:
                    continue
                summa = kpl * hinta
                kulu = self.kulut.kulu(o.ticker, summa)
                salkku.kateinen -= summa + kulu
                salkku.kulut_yht += kulu
                vanha = salkku.positiot.get(o.ticker)
                if vanha:
                    yht = vanha.kpl + kpl
                    vanha.hankintahinta = (vanha.kpl * vanha.hankintahinta + summa + kulu) / yht
                    vanha.kpl = yht
                else:
                    salkku.positiot[o.ticker] = Positio(kpl, (summa + kulu) / kpl, ps, hinta)
                k = Kauppa(ps, o.ticker, "OSTA", kpl, hinta, kulu, o.syy)
            salkku.kaupat.append(k)
            tehdyt.append(k)
        salkku.odottavat = jaljelle
        return tehdyt

    @staticmethod
    def paivita_huiput(salkku: Salkku, paatos: pd.Series) -> None:
        for t, p in salkku.positiot.items():
            h = paatos.get(t)
            if h is not None and not pd.isna(h):
                p.huippu = max(p.huippu, float(h))
