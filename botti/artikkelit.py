"""Artikkelien leipätekstin luku ja tulkinta.

Otsikot ovat usein klikkiotsikoita, joten tärkeimmistä uutisista luetaan myös itse teksti,
kun se on saatavilla (maksumuurin takaa saadaan yleensä vain ingressi). Tekstin tunnelma
painaa enemmän kuin otsikon. Johdon liiketoimista tekstistä selviää kaupan suunta
(osto vai myynti), jota otsikossa ei kerrota.

Arkistoon EI tallenneta artikkelien tekstiä (tekijänoikeudet), vain tulkinnan tulos.
"""
from __future__ import annotations

import re
import time

from .uutiset import UA, Uutinen, _hakuavaimet, _kieli, _MALLIT, avainsanatulkinta, mallitulkinta

LAUSE = re.compile(r"(?<=[.!?])\s+(?=[A-ZÅÄÖ0-9\"“])")
INSIDER_OSTO = re.compile(r"(nature of (the )?transaction|liiketoimen luonne)\W{0,5}(acquisition|subscription|"
                          r"hankinta|merkintä|osto)", re.I)
INSIDER_MYYNTI = re.compile(r"(nature of (the )?transaction|liiketoimen luonne)\W{0,5}(disposal|luovutus|myynti)", re.I)
OHITA_DOMAINIT = re.compile(r"(youtube\.com|twitter\.com|x\.com|facebook\.com|instagram\.com|tiktok\.com)", re.I)


# ---------------------------------------------------------------- osoite
def ratkaise_osoite(u: Uutinen) -> str | None:
    """Google Newsin linkit ovat uudelleenohjauksia; puretaan oikeaksi osoitteeksi."""
    url = u.linkki or ""
    if not url.startswith("http"):
        return None
    if "news.google.com" not in url:
        return url
    try:  # pip install googlenewsdecoder
        import googlenewsdecoder as g
        fn = getattr(g, "gnewsdecoder", None) or getattr(g, "new_decoderv1", None)
        if fn:
            r = fn(url, interval=1)
            if r and r.get("status") and r.get("decoded_url"):
                return r["decoded_url"]
    except Exception:  # noqa: BLE001
        pass
    try:  # vanhemmat linkit ohjautuvat suoraan
        import requests
        r = requests.get(url, headers=UA, timeout=10, allow_redirects=True)
        if "news.google.com" not in r.url:
            return r.url
    except Exception:  # noqa: BLE001
        pass
    return None


# ---------------------------------------------------------------- teksti
def hae_teksti(url: str) -> str:
    import requests
    r = requests.get(url, headers={**UA, "Accept-Language": "fi,en;q=0.8"}, timeout=12)
    r.raise_for_status()
    html = r.text
    try:  # paras tekstin erottelija, jos asennettu
        import trafilatura
        t = trafilatura.extract(html, include_comments=False, include_tables=False, favor_precision=True)
        if t and len(t) > 150:
            return t
    except ImportError:
        pass
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "nav", "header", "footer", "aside", "form"]):
        tag.decompose()
    juuri = soup.find("article") or soup.find("main") or soup.body or soup
    kappaleet = [p.get_text(" ", strip=True) for p in juuri.find_all(["p", "li"])]
    return "\n".join(k for k in kappaleet if len(k) > 40)


def valitse_lauseet(teksti: str, avaimet: list[str], n: int = 10) -> list[str]:
    """Ingressi (3 ensimmäistä lausetta) + lauseet, joissa yhtiö mainitaan, alkuperäisessä järjestyksessä."""
    lauseet = [l.strip() for l in LAUSE.split(teksti.replace("\n", " ")) if 30 <= len(l.strip()) <= 400]
    valitut = [l for i, l in enumerate(lauseet)
               if i < 3 or any(a.strip() and a.strip() in l.lower() for a in avaimet)]
    return valitut[:n]


def tekstin_tunnelma(lauseet: list[str]) -> float | None:
    if not lauseet:
        return None
    kieli = _kieli(" ".join(lauseet[:3]))
    malli = _MALLIT.get(kieli)
    if malli is not None:
        try:
            tulokset = malli(lauseet, batch_size=16, truncation=True)
            arvot = []
            for tulos in tulokset:
                p = {d["label"].lower(): d["score"] for d in tulos}
                arvot.append(p.get("positive", 0) - p.get("negative", 0))
            # Painotetaan voimakkaita lauseita: neutraalit täytelauseet eivät laimenna kaikkea
            painot = [0.3 + abs(a) for a in arvot]
            return sum(a * w for a, w in zip(arvot, painot)) / sum(painot)
        except Exception:  # noqa: BLE001
            pass
    arvot = [avainsanatulkinta(l, "uutinen")[0] for l in lauseet]
    nollasta = [a for a in arvot if a]
    return sum(nollasta) / len(nollasta) if nollasta else 0.0


# ---------------------------------------------------------------- kokonaisuus
def lue_ja_tulkitse(uutiset: list[Uutinen], nimet: dict[str, str], max_luettavia: int = 150) -> dict:
    """Lukee tärkeimpien uutisten tekstit ja päivittää tunnelman. Palauttaa tilastot."""
    tila = {"yritetty": 0, "luettu": 0, "maksumuuri_tai_lyhyt": 0, "virheet": 0, "sisapiiri_suunta": 0}
    if _MALLIT == {} and uutiset:
        mallitulkinta(uutiset[:1])          # lataa mallit, jos saatavilla
    ehdokkaat = [u for u in uutiset if u.tickerit and u.tyyppi in ("tiedote", "analyytikko", "sisapiiri", "uutinen")]
    # Tärkeysjärjestys: sisäpiiri ja tiedotteet ensin, sitten voimakkaimmat otsikot
    jarjestys = {"sisapiiri": 0, "tiedote": 1, "analyytikko": 2, "uutinen": 3}
    ehdokkaat.sort(key=lambda u: (jarjestys[u.tyyppi], -abs(u.tunnelma * u.paino)))
    for u in ehdokkaat[:max_luettavia]:
        url = ratkaise_osoite(u)
        if not url or OHITA_DOMAINIT.search(url):
            continue
        tila["yritetty"] += 1
        try:
            teksti = hae_teksti(url)
        except Exception:  # noqa: BLE001
            tila["virheet"] += 1
            continue
        finally:
            time.sleep(0.5)
        if len(teksti) < 200:
            tila["maksumuuri_tai_lyhyt"] += 1
            u.lisatieto["teksti"] = "ei saatavilla"
            continue

        otsikko_tun = u.tunnelma
        if u.tyyppi == "sisapiiri":
            if INSIDER_OSTO.search(teksti):
                u.tunnelma, u.paino = 0.7, max(u.paino, 0.7)
                u.lisatieto["suunta"] = "osto"
                tila["sisapiiri_suunta"] += 1
            elif INSIDER_MYYNTI.search(teksti):
                u.tunnelma, u.paino = -0.3, max(u.paino, 0.5)
                u.lisatieto["suunta"] = "myynti"
                tila["sisapiiri_suunta"] += 1
        else:
            avaimet = [a for t in u.tickerit for a in _hakuavaimet(t, nimet.get(t, t))]
            tt = tekstin_tunnelma(valitse_lauseet(teksti, avaimet))
            if tt is not None:
                # Teksti painaa 70 %, otsikko 30 %. Klikkiotsikko ei enää yksin ratkaise.
                u.tunnelma = round(max(-1.0, min(1.0, 0.3 * otsikko_tun + 0.7 * tt)), 2)
                u.lisatieto["otsikon_tunnelma"] = round(otsikko_tun, 2)
                u.lisatieto["tekstin_tunnelma"] = round(tt, 2)
        u.lisatieto["teksti"] = f"luettu ({len(teksti)} merkkiä)"
        tila["luettu"] += 1
    return tila
