"""Bottien kokoonpano. Yhdistelmä-botti koostuu kahdesta osasta, joilla on oma
kassansa: 60 % Pitkä-tyylisesti ja 40 % Lyhyt-tyylisesti. Raportissa ne näkyvät yhtenä bottina."""
from __future__ import annotations

import pandas as pd

from .strategiat import STRATEGIAT
from .valittaja import Kauppa, Positio, Salkku

# botti -> [(osan nimi, strategia, osuus pääomasta, max positiot)]
OSAT = {
    "lyhyt": [("lyhyt", "lyhyt", 1.0, None)],
    "pitka": [("pitka", "pitka", 1.0, None)],
    "yhdistelma": [("yhdistelma_pitka", "pitka", 0.6, 1), ("yhdistelma_lyhyt", "lyhyt", 0.4, 1)],
    "indeksi": [("indeksi", "indeksi", 1.0, 1)],
}
NAYTTONIMI = {"lyhyt": "Lyhyt", "pitka": "Pitkä", "yhdistelma": "Yhdistelmä", "indeksi": "Indeksi"}
YHDISTELMA_KUVAUS = ("Yhdistelmä: 60 % rahasta on pitkäaikaisessa ydinsijoituksessa (Pitkä-botin säännöt, "
                     "1 osake) ja 40 % lyhyissä uutisvetoisissa kaupoissa (Lyhyt-botin säännöt, 1 osake).")


def aja_botit(cfg, paneeli, sig, moottori, osatila: dict | None = None, alku=None):
    """Ajaa kaikki käytössä olevat botit. osatila = aiemmin tallennetut salkut (leikkikauppa).
    Palauttaa (tulokset raporttiin, huomiot, päivitetty osatila)."""
    osatila = dict(osatila or {})
    tulokset, huomiot = [], []
    for botti in cfg["kaytossa_botit"]:
        salkut, kuvaus = [], ""
        for osa, tyyppi, osuus, n in OSAT[botti]:
            strat = STRATEGIAT[tyyppi](cfg, nimi=osa, max_positiot=n)
            strat.valmistele(paneeli, sig)
            kuvaus = strat.kuvaus
            if osa in osatila:
                s = Salkku.from_dict(osatila[osa])
                h = moottori.aja(s, strat, paneeli)
            else:
                s = Salkku(kateinen=float(cfg["alkupaaoma"]) * osuus)
                h = moottori.aja(s, strat, paneeli, alku=alku if alku is not None else paneeli.paatos.index[-1])
            huomiot += [f"[{osa}] {x}" for x in h]
            osatila[osa] = s.to_dict()
            salkut.append(s)
        yhd = yhdista(salkut)
        sarja = pd.Series(yhd.arvohistoria, dtype=float)
        sarja.index = pd.to_datetime(sarja.index)
        tulokset.append({"nimi": NAYTTONIMI.get(botti, botti), "kuvaus": YHDISTELMA_KUVAUS if botti == "yhdistelma" else kuvaus,
                         "salkku": yhd, "sarja": sarja.sort_index()})
    return tulokset, huomiot, osatila


def yhdista(salkut: list[Salkku]) -> Salkku:
    if len(salkut) == 1:
        return salkut[0]
    y = Salkku(kateinen=sum(s.kateinen for s in salkut))
    for s in salkut:
        for t, p in s.positiot.items():
            if t in y.positiot:
                v = y.positiot[t]
                kpl = v.kpl + p.kpl
                y.positiot[t] = Positio(kpl, (v.kpl * v.hankintahinta + p.kpl * p.hankintahinta) / kpl,
                                        min(v.ostopaiva, p.ostopaiva), max(v.huippu, p.huippu))
            else:
                y.positiot[t] = Positio(**vars(p))
        y.odottavat += s.odottavat
        y.kaupat += [Kauppa(**vars(k)) for k in s.kaupat]
        y.kulut_yht += s.kulut_yht
        for pv, a in s.arvohistoria.items():
            y.arvohistoria[pv] = round(y.arvohistoria.get(pv, 0) + a, 2)
    y.kaupat.sort(key=lambda k: k.paiva)
    return y
