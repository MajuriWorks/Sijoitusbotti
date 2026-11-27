"""Teemat: mitä maailman tapahtumat tarkoittavat eri toimialoille (v2).

Sama uutinen voi olla toiselle toimialalle huono ja toiselle hyvä. Sota on riski koko
markkinalle, mutta puolustusteollisuudelle se tarkoittaa tilauksia. Korkojen lasku auttaa
kiinteistöyhtiöitä mutta heikentää pankkien tulosta.

Teeman voimakkuus lasketaan maailmanuutisten määrästä (paino, hiipuminen 10 pv) suhteessa
tavalliseen tasoon. Osakkeen teemasignaali = sen toimialan altistus x teemojen voimakkuus.
Toimialat haetaan Yahoosta kerran ja tallennetaan (arkisto/toimialat.json).
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

import numpy as np
import pandas as pd

TOIMIALAT = Path("arkisto/toimialat.json")

# vaikutukset: (toimiala- tai alatoimiala-hakulauseke, +1 hyötyy / -1 kärsii)
TEEMAT = [
    {"nimi": "Sota ja varustautuminen",
     "haku": r"\b(war|missile|invasion|airstrike|defen[cs]e spending|rearm\w*|nato|military aid|"
             r"sota\w*|hyökkäy\w*|ohjus\w*|puolustusmeno\w*|varustautu\w*|asehank\w*)",
     "vaikutus": [(r"aerospace|defen", +1.0), (r"airline|travel|leisure|resort", -0.6)]},
    {"nimi": "Öljyn hinta nousee",
     "haku": r"\b(oil (price|prices)? (jump|surge|rise|rall|soar|climb)\w*|crude (jump|surge|rise|rall)\w*|"
             r"opec (cut|curb)\w*|öljyn hinta nous\w*|öljy kallist\w*)",
     "vaikutus": [(r"oil|gas|energy|petrol", +1.0), (r"airline|chemical|trucking|auto", -0.6)]},
    {"nimi": "Öljyn hinta laskee",
     "haku": r"\b(oil (price|prices)? (fall|drop|slump|plunge|tumble|sink)\w*|crude (fall|drop|slump)\w*|"
             r"öljyn hinta (las|putos)\w*)",
     "vaikutus": [(r"oil|gas|energy|petrol", -1.0), (r"airline|chemical|trucking", +0.6)]},
    {"nimi": "Korot laskevat",
     "haku": r"\b(rate cut\w*|cuts? (interest )?rates|lower(s|ing)? rates|dovish|easing|"
             r"koronlasku\w*|laskee korko\w*|korot laske\w*)",
     "vaikutus": [(r"real estate|reit|utilit|homebuild|construction", +0.8),
                  (r"software|semiconductor|technology", +0.4), (r"bank", -0.4)]},
    {"nimi": "Korot nousevat",
     "haku": r"\b(rate hike\w*|raises? (interest )?rates|hawkish|tighten\w*|"
             r"koronnosto\w*|nostaa korko\w*|korot nouse\w*)",
     "vaikutus": [(r"bank|insurance", +0.6), (r"real estate|reit|utilit|homebuild|construction", -0.8)]},
    {"nimi": "Tekoälybuumi",
     "haku": r"\b(ai boom|ai demand|ai spending|ai chips?|data cent(er|re)s?|generative ai|"
             r"tekoälybuum\w*|datakeskus\w*)",
     "vaikutus": [(r"semiconductor|software|information technology|electronic|communication equipment", +1.0),
                  (r"utilit|electrical equipment", +0.4)]},
    {"nimi": "Kauppasota ja tullit",
     "haku": r"\b(tariff\w*|trade war|export (ban|control)\w*|tulli\w*|kauppasota\w*|vientikiel\w*)",
     "vaikutus": [(r"auto|semiconductor|machinery|industrial|steel|paper|forest", -0.7)]},
    {"nimi": "Taantumapelko",
     "haku": r"\b(recession|downturn|slowdown|layoffs? surge|taantum\w*|lama\w*|talous supist\w*)",
     "vaikutus": [(r"consumer defensive|staples|healthcare|utilit|telecom", +0.6),
                  (r"industrial|basic materials|consumer cyclical|auto|steel|paper", -0.7)]},
    {"nimi": "Kryptonousu",
     "haku": r"\b(bitcoin (jump|surge|rall|soar|record|hits)\w*|crypto (rally|surge|boom)|"
             r"bitcoin nous\w*|kryptovaluuttojen nousu)",
     "vaikutus": [(r"crypto|blockchain|capital markets", +0.8)]},
    {"nimi": "Pandemia",
     "haku": r"\b(pandemic|outbreak|epidemic|lockdown|pandemi\w*|epidemi\w*|rajoitustoim\w*)",
     "vaikutus": [(r"healthcare|biotech|pharma|diagnostic", +0.6),
                  (r"airline|travel|leisure|restaurant|resort", -0.8)]},
]


def lataa_toimialat(tickerit: list[str]) -> dict[str, str]:
    """{ticker: "sektori | toimiala"} Yahoosta, tallennetaan kerran."""
    data = json.loads(TOIMIALAT.read_text(encoding="utf-8")) if TOIMIALAT.exists() else {}
    puuttuvat = [t for t in tickerit if t not in data]
    if puuttuvat:
        try:
            import yfinance as yf
        except ImportError:
            return data
        haettu = 0
        for t in puuttuvat:
            try:
                info = yf.Ticker(t).info or {}
                arvo = f"{info.get('sector', '')} | {info.get('industry', '')}".strip(" |")
                if not arvo and info.get("quoteType") == "ETF":
                    arvo = f"ETF | {info.get('longName', '')}"
            except Exception:  # noqa: BLE001
                continue
            if arvo:
                data[t] = arvo
                haettu += 1
            time.sleep(0.3)
        if haettu:
            TOIMIALAT.parent.mkdir(parents=True, exist_ok=True)
            TOIMIALAT.write_text(json.dumps(data, ensure_ascii=False, indent=0, sort_keys=True), encoding="utf-8")
    return data


def _hiipuva(sarja: pd.Series, puoliintuminen: float) -> pd.Series:
    k = 0.5 ** (1 / puoliintuminen)
    out, ed = [], 0.0
    for x in sarja.to_numpy(dtype=float):
        ed = ed * k + x
        out.append(ed)
    return pd.Series(out, index=sarja.index)


class Teemat:
    def __init__(self, uutiset, paivat: pd.DatetimeIndex, tickerit: list[str], paiva_indeksi):
        self.toimialat = lataa_toimialat(tickerit)
        voimat = {}
        self.otsikot: dict[str, list] = {}
        for teema in TEEMAT:
            haku = re.compile(teema["haku"], re.I)
            impulssit = pd.Series(0.0, index=paivat)
            for u in uutiset:
                if u.tickerit and u.tyyppi != "maailma":
                    continue          # teemat luetaan maailmanuutisista
                if not haku.search(u.otsikko):
                    continue
                i = paiva_indeksi(u.aika)
                if i is None:
                    continue
                impulssit.iloc[i] += max(u.paino, 0.3)
                self.otsikot.setdefault(teema["nimi"], []).append((i, u.otsikko))
            s = _hiipuva(impulssit, 10)
            perus = s.rolling(60, min_periods=10).median().shift(1)
            # Voimakkuus 0 ... 2: kuinka paljon tavallista enemmän teemasta uutisoidaan
            voimat[teema["nimi"]] = ((s / perus.clip(lower=1.0)) - 1).clip(0, 2).fillna(0)
        self.voimat = pd.DataFrame(voimat)

        altistus = {}
        for t in tickerit:
            ala = self.toimialat.get(t, "").lower()
            rivi = {}
            for teema in TEEMAT:
                rivi[teema["nimi"]] = sum(v for kuvio, v in teema["vaikutus"] if ala and re.search(kuvio, ala))
            altistus[t] = rivi
        self.altistus = pd.DataFrame(altistus).T.reindex(columns=self.voimat.columns).fillna(0)
        # Osakekohtainen teemasignaali päivittäin
        self.signaali = pd.DataFrame(self.voimat.to_numpy() @ self.altistus.T.to_numpy(),
                                     index=paivat, columns=self.altistus.index)

    def selitys(self, t: str, paiva) -> str:
        if t not in self.altistus.index:
            return ""
        osat = []
        for teema, voima in self.voimat.loc[paiva].items():
            a = self.altistus.at[t, teema]
            if voima > 0.2 and a:
                osat.append(f"{teema} ({'hyötyy' if a > 0 else 'kärsii'})")
        return ", ".join(osat)

    def aktiiviset(self, paiva) -> dict[str, float]:
        v = self.voimat.loc[paiva]
        return {k: round(float(x), 2) for k, x in v.items() if x > 0.2}
