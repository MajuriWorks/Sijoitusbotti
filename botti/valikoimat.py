"""Laajat osakevalikoimat, jotka haetaan automaattisesti (indeksien kokoonpanot muuttuvat).

  usa_sp500      – S&P 500 -indeksin yhtiöt (Wikipedia)
  usa_nasdaq100  – Nasdaq-100 -indeksin yhtiöt (Wikipedia)

Listat tallennetaan arkistoon ja päivitetään viikoittain. Jos haku epäonnistuu, käytetään
viimeisintä tallennettua listaa tai pientä varalistaa.
"""
from __future__ import annotations

import json
import time
from io import StringIO
from pathlib import Path

KANSIO = Path("arkisto/valikoimat")
UA = {"User-Agent": "Mozilla/5.0 (sijoitusbotti; https://github.com/MajuriWorks/Sijoitusbotti)"}

VARALISTA_USA = {
    "AAPL": "Apple", "MSFT": "Microsoft", "NVDA": "Nvidia", "AMZN": "Amazon", "GOOGL": "Alphabet",
    "META": "Meta Platforms", "TSLA": "Tesla", "AVGO": "Broadcom", "BRK-B": "Berkshire Hathaway",
    "JPM": "JPMorgan Chase", "LLY": "Eli Lilly", "V": "Visa", "UNH": "UnitedHealth", "XOM": "Exxon Mobil",
    "MA": "Mastercard", "JNJ": "Johnson & Johnson", "PG": "Procter & Gamble", "HD": "Home Depot",
    "COST": "Costco", "NFLX": "Netflix", "AMD": "Advanced Micro Devices", "CRM": "Salesforce",
    "KO": "Coca-Cola", "PEP": "PepsiCo", "WMT": "Walmart", "BAC": "Bank of America", "ORCL": "Oracle",
    "ADBE": "Adobe", "CSCO": "Cisco", "INTC": "Intel", "QCOM": "Qualcomm", "DIS": "Walt Disney",
}


def _wikipedia_taulukko(url: str, sarakkeet: tuple[str, str]) -> dict[str, str]:
    import pandas as pd
    import requests
    html = requests.get(url, headers=UA, timeout=30).text
    for df in pd.read_html(StringIO(html)):
        cols = [str(c) for c in df.columns]
        if sarakkeet[0] in cols and sarakkeet[1] in cols:
            return {str(t).strip().replace(".", "-"): str(n).strip()
                    for t, n in zip(df[sarakkeet[0]], df[sarakkeet[1]]) if str(t).strip()}
    raise ValueError("taulukkoa ei löytynyt")


HAKIJAT = {
    "usa_sp500": lambda: _wikipedia_taulukko("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
                                             ("Symbol", "Security")),
    "usa_nasdaq100": lambda: _wikipedia_taulukko("https://en.wikipedia.org/wiki/Nasdaq-100",
                                                 ("Ticker", "Company")),
}


def hae(nimi: str, max_ika_pv: int = 7) -> dict[str, str]:
    """Palauttaa {ticker: yhtiön nimi}."""
    f = KANSIO / f"{nimi}.json"
    if f.exists() and (time.time() - f.stat().st_mtime) < max_ika_pv * 86400:
        return json.loads(f.read_text(encoding="utf-8"))
    try:
        data = HAKIJAT[nimi]()
        if len(data) < 50:
            raise ValueError(f"liian lyhyt lista ({len(data)})")
        KANSIO.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(data, ensure_ascii=False, indent=0, sort_keys=True), encoding="utf-8")
        return data
    except Exception as e:  # noqa: BLE001
        if f.exists():
            return json.loads(f.read_text(encoding="utf-8"))
        print(f"  ! valikoiman {nimi} haku epäonnistui ({e}); käytetään varalistaa")
        return dict(VARALISTA_USA)
