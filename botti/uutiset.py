"""Uutisten, tiedotteiden, foorumien ja maailman tapahtumien keruu.

Lähteet (kaikki ilmaisia, ei tunnuksia):
  - Google News -hakusyöte: yhtiökohtaiset uutiset ja tiedotteet, analyytikkojen
    suositusmuutokset, johdon liiketoimet, maailman tapahtumat
  - Yahoo Finance: yhtiökohtaiset uutiset
  - Inderesin foorumi: mistä yhtiöistä keskustellaan nyt
  - Reddit: sijoitusyhteisöjen keskustelut

Jokainen uutinen saa tunnelman (-1 ... +1) ja painoarvon (0 ... 1). Tulkinta tehdään
tekoälyllä, jos ympäristömuuttuja ANTHROPIC_API_KEY on asetettu, muuten avainsanoilla.
Kaikki tallennetaan arkistoon (arkisto/uutiset/VVVV-KK.jsonl).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import quote_plus

UA = {"User-Agent": "Mozilla/5.0 (sijoitusbotti; +https://github.com/MajuriWorks/sijoitusbotti)"}
ARKISTO = Path("arkisto/uutiset")
TYYPIT = ("tiedote", "uutinen", "analyytikko", "sisapiiri", "foorumi", "maailma")


@dataclass
class Uutinen:
    aika: str                    # ISO, UTC
    otsikko: str
    lahde: str                   # google / yahoo / inderes / reddit
    linkki: str = ""
    tickerit: list[str] = field(default_factory=list)   # tyhjä = koko markkina
    tyyppi: str = "uutinen"
    tunnelma: float = 0.0        # -1 ... +1
    paino: float = 0.5           # 0 ... 1
    tulkinta: str = ""           # "tekoaly" / "avainsanat"
    lisatieto: dict = field(default_factory=dict)

    @property
    def tunniste(self) -> str:
        avain = re.sub(r"\W+", "", self.otsikko.lower())[:120]
        return hashlib.sha1(avain.encode()).hexdigest()[:16]


# ====================================================================== haku
def _get(url: str, timeout=20):
    import requests
    r = requests.get(url, headers=UA, timeout=timeout)
    r.raise_for_status()
    return r


def _rss(url: str) -> list[dict]:
    juuri = ET.fromstring(_get(url).content)
    out = []
    for it in juuri.iter("item"):
        otsikko = (it.findtext("title") or "").strip()
        pvm = it.findtext("pubDate")
        try:
            aika = parsedate_to_datetime(pvm).astimezone(timezone.utc) if pvm else datetime.now(timezone.utc)
        except (TypeError, ValueError):
            aika = datetime.now(timezone.utc)
        lahde = it.find("source")
        out.append({"otsikko": otsikko, "aika": aika, "linkki": it.findtext("link") or "",
                    "julkaisija": lahde.text if lahde is not None else ""})
    return out


def google_news(haku: str, kieli: str = "fi", paivat: int = 2) -> list[dict]:
    if kieli == "fi":
        loppu = "hl=fi&gl=FI&ceid=FI:fi"
    elif kieli == "sv":
        loppu = "hl=sv&gl=SE&ceid=SE:sv"
    else:
        loppu = "hl=en-US&gl=US&ceid=US:en"
    url = f"https://news.google.com/rss/search?q={quote_plus(haku)}+when:{paivat}d&{loppu}"
    rivit = _rss(url)
    for r in rivit:  # Google lisää otsikon perään " - Julkaisija"
        if r["julkaisija"] and r["otsikko"].endswith(" - " + r["julkaisija"]):
            r["otsikko"] = r["otsikko"][: -len(r["julkaisija"]) - 3]
    return rivit


def yahoo_news(ticker: str) -> list[dict]:
    import yfinance as yf
    out = []
    for n in (yf.Ticker(ticker).news or []):
        c = n.get("content", n)
        otsikko = c.get("title") or ""
        aika = c.get("pubDate") or c.get("providerPublishTime")
        try:
            aika = (datetime.fromtimestamp(aika, timezone.utc) if isinstance(aika, (int, float))
                    else datetime.fromisoformat(str(aika).replace("Z", "+00:00")))
        except (TypeError, ValueError):
            aika = datetime.now(timezone.utc)
        linkki = (c.get("canonicalUrl") or {}).get("url") if isinstance(c.get("canonicalUrl"), dict) else c.get("link", "")
        if otsikko:
            out.append({"otsikko": otsikko, "aika": aika, "linkki": linkki or "", "julkaisija": "Yahoo"})
    return out


def inderes_foorumi() -> list[dict]:
    """Inderesin foorumin viimeisimmät keskustelut (Discourse-rajapinta)."""
    out = []
    for sivu in (0, 1):
        data = _get(f"https://forum.inderes.com/latest.json?page={sivu}").json()
        for t in data.get("topic_list", {}).get("topics", []):
            aika = t.get("last_posted_at") or t.get("bumped_at") or t.get("created_at")
            try:
                aika = datetime.fromisoformat(aika.replace("Z", "+00:00"))
            except (AttributeError, ValueError):
                aika = datetime.now(timezone.utc)
            out.append({"otsikko": t.get("title", ""), "aika": aika,
                        "linkki": f"https://forum.inderes.com/t/{t.get('slug')}/{t.get('id')}",
                        "julkaisija": "Inderes-foorumi",
                        "viestit": t.get("posts_count", 0), "katselut": t.get("views", 0)})
        time.sleep(1)
    return out


def reddit(sub: str) -> list[dict]:
    data = _get(f"https://www.reddit.com/r/{sub}/new.json?limit=100").json()
    out = []
    for c in data.get("data", {}).get("children", []):
        d = c.get("data", {})
        out.append({"otsikko": d.get("title", ""), "aika": datetime.fromtimestamp(d.get("created_utc", time.time()), timezone.utc),
                    "linkki": "https://reddit.com" + d.get("permalink", ""), "julkaisija": f"r/{sub}",
                    "pisteet": d.get("score", 0)})
    return out


# ====================================================================== nimet
TURHAT = r"\b(oyj|abp|plc|ab|asa|a/s|as|corporation|corp|group|oy|ltd|publ|the|inc|holding|holdings|company)\b"


def hakunimi(nimi: str) -> str:
    n = re.sub(r"\(.*?\)", "", nimi or "")
    n = re.sub(TURHAT, "", n, flags=re.I)
    n = re.sub(r"[^\w\s&\-]", " ", n)
    return re.sub(r"\s+", " ", n).strip()


def lataa_nimet(tickerit: list[str], polku=Path("arkisto/nimet.json"), valmiit: dict | None = None) -> dict[str, str]:
    """Yhtiöiden nimet uutisten tunnistamiseen. Haetaan Yahoosta kerran ja tallennetaan."""
    nimet = json.loads(polku.read_text(encoding="utf-8")) if polku.exists() else {}
    for t, n in (valmiit or {}).items():
        if t not in nimet and n:
            nimet[t] = hakunimi(n)
    puuttuvat = [t for t in tickerit if t not in nimet]
    if puuttuvat:
        try:
            import yfinance as yf
            for t in puuttuvat:
                try:
                    info = yf.Ticker(t).info or {}
                    nimi = info.get("shortName") or info.get("longName")
                except Exception:  # noqa: BLE001
                    nimi = None
                if nimi:
                    nimet[t] = hakunimi(nimi)
                time.sleep(0.3)
        except ImportError:
            pass
        polku.parent.mkdir(parents=True, exist_ok=True)
        polku.write_text(json.dumps(nimet, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    return {t: nimet.get(t) or t.split(".")[0] for t in tickerit}


# Taivutusmuodot, joita ei voi päätellä nimestä (astevaihtelu) ja tunnetut lyhenteet
ALIAKSET = {
    "SAMPO.HE": ["sammo"], "ERIC-B.ST": ["ericsson"], "ERIBR.HE": ["ericsson"], "NDA-FI.HE": ["nordea"],
    "UPM.HE": ["upm"], "STERV.HE": ["stora enso", "storaenso"], "KESKOB.HE": ["kesko"],
    "TYRES.HE": ["nokian renkaat", "nokian tyres"], "TELIA1.HE": ["telia"], "METSB.HE": ["metsä board"],
    "FIA1S.HE": ["finnair"], "OUT1V.HE": ["outokumpu"], "WRT1V.HE": ["wärtsilä", "wärtsilän"],
    "KNEBV.HE": ["kone oyj", "koneen", "kone "], "NOVO-B.CO": ["novo nordisk"], "MAERSK-B.CO": ["maersk"],
}
YLEISET = {"nokian", "telefonaktiebolaget", "svenska", "skandinaviska", "bank", "group", "investment", "the", "a.p."}


def _hakuavaimet(ticker: str, nimi: str) -> list[str]:
    n = nimi.lower().strip()
    avaimet = list(ALIAKSET.get(ticker, []))
    if len(n) >= 3:
        avaimet.append(n if len(n) <= 5 else n[: max(5, len(n) - 2)])
    eka = n.split(" ")[0].split("-")[0]
    if len(eka) >= 4 and eka not in YLEISET and eka != n:
        avaimet.append(eka)
    return avaimet


def tunnista_tickerit(teksti: str, nimet: dict[str, str]) -> list[str]:
    t = " " + teksti.lower() + " "
    osumat = []
    for ticker, nimi in nimet.items():
        for avain in _hakuavaimet(ticker, nimi):
            # sana alkaa avaimella (taivutusmuodot: "Nokian", "Koneen")
            loppu = r"[a-zåäö:']{0,4}(?![\w])" if len(avain.strip()) <= 6 else ""
            if re.search(r"(?<![\w])" + re.escape(avain.strip()) + loppu, t):
                osumat.append(ticker)
                break
    if "TYRES.HE" in osumat and "NOKIA.HE" in osumat and re.search(r"nokian (renkaat|tyres|renkai)", t):
        osumat.remove("NOKIA.HE")
    return osumat


# ====================================================================== tyyppi
def paattele_tyyppi(otsikko: str, oletus: str) -> str:
    o = otsikko.lower()
    if re.search(r"johdon liiketoim|managers.? transaction|insider|sisäpiiri", o):
        return "sisapiiri"
    if re.search(r"suositu|tavoitehin|price target|upgrade|downgrade|nostaa .*osta|laskee .*myy|inderes|analyytik", o):
        return "analyytikko"
    if re.search(r"pörssitiedote|tiedote|osavuosikat|liiketoimintakatsaus|tulosvaroitus|tilinpäätös|"
                 r"interim report|half-year|annual report|profit warning|tender offer|ostotarjous|yt-neuvottel|"
                 r"muutosneuvottel|osinko|dividend", o):
        return "tiedote"
    return oletus


# ====================================================================== tulkinta: avainsanat
POS = r"""nousu nousi nousee kasvu kasvoi kasvaa paransi paranee parani ylitti vahva vahvisti ennätys ennätyks voitto
 tilaus tilauksen kauppa sopimus sopimuksen ostotarjous yritysosto nostaa nosti nostettiin osta lisää ylipaino positiivi
 hyvä hyvin onnistui menestys läpimurto hyväksyntä hyväksyi lupa kasvattaa laajentaa investoi myönteinen piristy elpy
 beat beats surge surges soar soars jump jumps rally rallies record growth grew upgrade upgraded raises raised raise
 strong stronger outperform buy acquisition approval approved wins win order contract profit profits expands boost
 optimism optimistic rebound recovers recovery bullish higher gains gain""".split()
NEG = r"""lasku laski laskee laskivat heikko heikkeni heikkenee heikensi tappio tappiolli varoitus tulosvaroitus pudotus putosi
 romahti romahdus menetti menettää myy vähennä alipaino leikkaa leikkasi vähentää lomautu irtisano muutosneuvottel
 yt-neuvottel konkurssi saneeraus negatiivi huono epäonnistui viivästy viivästys kielteinen sakko kanne riita tutkinta
 sota pakote pakotteet tulli tullit kriisi taantuma inflaatio pelko epävarmuus huoli
 miss misses missed plunge plunges plunged fall falls fell drop drops dropped slump slumps loss losses losses warning
 downgrade downgraded cut cuts cutting lower weak weaker underperform sell layoffs layoff lawsuit probe investigation
 bankruptcy recession inflation fears fear tariff tariffs war sanctions crisis selloff sell-off bearish decline declines""".split()


def avainsanatulkinta(otsikko: str, tyyppi: str) -> tuple[float, float]:
    o = otsikko.lower()
    sanat = re.findall(r"[\wåäö\-]+", o)
    p = sum(1 for s in sanat for k in POS if s.startswith(k))
    n = sum(1 for s in sanat for k in NEG if s.startswith(k))
    if p == n:
        tunnelma = 0.0
    else:
        tunnelma = max(-1.0, min(1.0, (p - n) / max(p + n, 1)))
    paino = {"tiedote": 0.8, "analyytikko": 0.7, "sisapiiri": 0.6, "uutinen": 0.5,
             "maailma": 0.5, "foorumi": 0.2}.get(tyyppi, 0.4)
    return round(tunnelma, 2), paino


# ====================================================================== tulkinta: tekoäly
TEKOALY_OHJE = """Olet osakemarkkinoiden uutisanalyytikko. Arvioi jokaisen otsikon vaikutus mainittujen
yhtiöiden osakekurssiin seuraavien päivien aikana (tai koko markkinaan, jos yhtiötä ei mainita).
Palauta VAIN JSON-lista, yksi objekti per otsikko, muodossa:
{"i": <numero>, "tunnelma": <-1..1>, "paino": <0..1>, "tyyppi": "<tiedote|uutinen|analyytikko|sisapiiri|foorumi|maailma>",
 "tickerit": ["<tunnus>", ...]}
tunnelma: -1 erittäin negatiivinen, 0 neutraali, +1 erittäin positiivinen.
paino: kuinka merkittävä uutinen on kurssille (rutiinitiedote 0.1, tulosvaroitus tai ostotarjous 1.0).
tickerit: valitse vain alla olevasta yhtiölistasta; tyhjä lista, jos uutinen koskee yleisesti markkinaa.
Johdon liiketoimet: osto = positiivinen, myynti = lievästi negatiivinen; jos suuntaa ei näe, 0.
Yhtiölista (tunnus: nimi):
"""


def tekoalytulkinta(uutiset: list[Uutinen], nimet: dict[str, str], malli: str) -> int:
    """Tulkitsee uutiset Clauden avulla. Palauttaa tulkittujen määrän."""
    avain = os.environ.get("ANTHROPIC_API_KEY")
    if not avain or not uutiset:
        return 0
    import requests
    lista = "\n".join(f"{t}: {n}" for t, n in nimet.items())
    tehty = 0
    for i in range(0, len(uutiset), 60):
        era = uutiset[i:i + 60]
        rivit = "\n".join(f"{j}. [{u.lahde}] {u.otsikko}" for j, u in enumerate(era))
        try:
            r = requests.post(
                "https://api.anthropic.com/v1/messages",
                headers={"x-api-key": avain, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                json={"model": malli, "max_tokens": 8000,
                      "system": TEKOALY_OHJE + lista,
                      "messages": [{"role": "user", "content": "Otsikot:\n" + rivit}]},
                timeout=120)
            r.raise_for_status()
            teksti = "".join(b.get("text", "") for b in r.json().get("content", []))
            data = json.loads(teksti[teksti.find("["): teksti.rfind("]") + 1])
        except Exception as e:  # noqa: BLE001
            print(f"  ! tekoälytulkinta epäonnistui ({e}); käytetään avainsanoja")
            continue
        for d in data:
            try:
                u = era[int(d["i"])]
            except (KeyError, ValueError, IndexError, TypeError):
                continue
            u.tunnelma = round(max(-1.0, min(1.0, float(d.get("tunnelma", 0)))), 2)
            u.paino = round(max(0.0, min(1.0, float(d.get("paino", 0.5)))), 2)
            if d.get("tyyppi") in TYYPIT and u.tyyppi not in ("foorumi", "maailma"):
                u.tyyppi = d["tyyppi"]
            tt = [t for t in d.get("tickerit", []) if t in nimet]
            if tt or u.tyyppi == "maailma":
                u.tickerit = tt
            u.tulkinta = "tekoaly"
            tehty += 1
    return tehty


# ====================================================================== kokonaisuus
def keraa(cfg: dict, tickerit: list[str]) -> tuple[list[Uutinen], dict]:
    """Kerää kaikista lähteistä. Palauttaa (uudet uutiset, lähteiden tila)."""
    ucfg = cfg.get("uutiset", {})
    lahteet = ucfg.get("lahteet", {})
    nimet = lataa_nimet(tickerit, valmiit=cfg.get("valmiit_nimet"))
    tila: dict[str, dict] = {}
    raaka: list[tuple[dict, str, str, list[str]]] = []   # (rivi, lähde, oletustyyppi, tickerit)

    def aja(nimi, fn, *args, oletus="uutinen", tickerit_=None, kerays=None):
        t = tila.setdefault(nimi, {"ok": 0, "virheet": 0, "viimeisin_virhe": ""})
        try:
            rivit = fn(*args)
            t["ok"] += len(rivit)
            for r in rivit:
                (kerays if kerays is not None else raaka).append((r, nimi, oletus, tickerit_))
        except Exception as e:  # noqa: BLE001
            t["virheet"] += 1
            t["viimeisin_virhe"] = f"{type(e).__name__}: {str(e)[:120]}"

    # 1) Yhtiökohtaiset uutiset ja tiedotteet
    max_haut = ucfg.get("max_yhtiohakuja", 200)
    for i, t in enumerate(tickerit[:max_haut]):
        nimi = nimet[t]
        if t.endswith(".DE"):
            continue  # ETF:t: ei yhtiöuutisia
        if lahteet.get("google_yhtiot", True) and nimi != t.split(".")[0]:
            # Englanniksi kaikille (paras ilmainen tulkintamalli FinBERT on englanninkielinen),
            # Helsingin yhtiöille lisäksi suomeksi (Kauppalehti, Arvopaperi, Inderes...)
            kielet = ["en", "fi"] if t.endswith(".HE") else ["en"]
            for kieli in kielet:
                aja("google_yhtiot", google_news, f'"{nimi}"', kieli, 2, tickerit_=[t])
                time.sleep(0.7)
        if lahteet.get("yahoo", True):
            aja("yahoo", yahoo_news, t, tickerit_=[t])
            time.sleep(0.3)

    # 2) Analyytikot ja sisäpiiri (yleishaut, yhtiö tunnistetaan otsikosta)
    if lahteet.get("analyytikot", True):
        for h in ("nostaa suositusta", "laskee suositusta", "tavoitehinta", "Inderes suositus"):
            aja("analyytikot", google_news, h, "fi", 2, oletus="analyytikko")
            time.sleep(0.7)
    if lahteet.get("sisapiiri", True):
        for h in ("johdon liiketoimet", "managers' transactions"):
            aja("sisapiiri", google_news, h, "fi" if "johdon" in h else "en", 3, oletus="sisapiiri")
            time.sleep(0.7)

    # 3) Maailma
    if lahteet.get("maailma", True):
        for h in ucfg.get("maailma_haut", []):
            kieli = "fi" if re.search(r"[äö]|pörssi|osake", h) else "en"
            aja("maailma", google_news, h, kieli, 1, oletus="maailma", tickerit_=[])
            time.sleep(0.7)

    # 3b) Markkinaa liikuttavat jättiyhtiöt (Nvidia, Apple...): niiden kohut vaikuttavat koko markkinaan
    for nimi in ucfg.get("seuranta_yhtiot", []):
        aja("jattiyhtiot", lambda q: google_news(q, "en", 1)[:20], f'"{nimi}"', oletus="maailma", tickerit_=[])
        time.sleep(0.7)

    # 4) Suuret mediat: talous- ja pääuutiset suoraan (Reuters, Bloomberg, CNN, BBC, HS, Yle...)
    if lahteet.get("suuret_mediat", True):
        for sivu in ucfg.get("mediat", []):
            kieli = "fi" if sivu.endswith(".fi") else ("sv" if sivu.endswith((".se", ".no")) else "en")
            aja("suuret_mediat", lambda q, k: google_news(q, k, 1)[:30], f"site:{sivu}", kieli, oletus="maailma")
            time.sleep(0.7)
        for url in ucfg.get("rss_syotteet", []):
            aja("rss_syotteet", lambda u: _rss(u)[:40], url, oletus="maailma")
            time.sleep(0.5)

    # 5) Foorumit
    if lahteet.get("inderes_foorumi", True):
        aja("inderes_foorumi", inderes_foorumi, oletus="foorumi")
    if lahteet.get("reddit", True):
        for s in ucfg.get("reddit", []):
            aja("reddit", reddit, s, oletus="foorumi")
            time.sleep(2)

    # Muunnos Uutinen-olioiksi, päällekkäisyyksien poisto
    nahdyt = _nahdyt_tunnisteet()
    raja = datetime.now(timezone.utc) - timedelta(days=4)
    uudet, kasitelty = [], set()
    for r, lahde, oletus, tt in raaka:
        if not r.get("otsikko") or r["aika"] < raja:
            continue
        tyyppi = paattele_tyyppi(r["otsikko"], oletus)
        if not r.get("julkaisija") and lahde == "rss_syotteet":
            r["julkaisija"] = re.sub(r"^www\.|/.*$", "", r.get("linkki", "").split("//")[-1])
        if tt and lahde in ("google_yhtiot", "yahoo"):
            # Yhtiöhaun tulos kelpaa vain, jos yhtiö mainitaan otsikossa (muuten uutinen koskee jotain muuta)
            if not tunnista_tickerit(r["otsikko"], {t: nimet[t] for t in tt}):
                continue
        if tt is None:
            tt = tunnista_tickerit(r["otsikko"], nimet)
            if oletus == "foorumi" and not tt:
                continue  # foorumiviesti, jossa ei mainita seurattua yhtiötä
            if oletus == "maailma" and tt and tyyppi == "maailma":
                tyyppi = "uutinen"   # suuren median juttu, jossa mainitaan seurattu yhtiö
        if oletus == "maailma" and not tt and lahde in ("suuret_mediat", "rss_syotteet"):
            tt = []
        u = Uutinen(aika=r["aika"].isoformat(timespec="seconds"), otsikko=r["otsikko"], lahde=lahde,
                    linkki=r.get("linkki", ""), tickerit=tt, tyyppi=tyyppi,
                    lisatieto={k: r[k] for k in ("julkaisija", "viestit", "katselut", "pisteet") if k in r})
        if u.tunniste in nahdyt or u.tunniste in kasitelty:
            continue
        kasitelty.add(u.tunniste)
        uudet.append(u)

    # Tulkinta
    malli = ucfg.get("tekoaly_malli", "claude-haiku-5-5")
    tulkittavat = [u for u in uudet if u.tyyppi != "foorumi" or u.tickerit]
    n_ai = tekoalytulkinta(tulkittavat, nimet, malli)
    n_malli = mallitulkinta([u for u in uudet if u.tulkinta != "tekoaly"])
    for u in uudet:
        if u.tulkinta not in ("tekoaly", "malli"):
            u.tunnelma, u.paino = avainsanatulkinta(u.otsikko, u.tyyppi)
            u.tulkinta = "avainsanat"
    # Tärkeimpien uutisten leipäteksti (otsikko voi olla klikkiotsikko)
    if ucfg.get("lue_artikkelit", True):
        from .artikkelit import lue_ja_tulkitse
        try:
            tila["artikkelit"] = {"ok": 0, "virheet": 0, "viimeisin_virhe": "", **lue_ja_tulkitse(
                uudet, nimet, ucfg.get("max_luettavia_artikkeleita", 150))}
            tila["artikkelit"]["ok"] = tila["artikkelit"]["luettu"]
        except Exception as e:  # noqa: BLE001
            tila["artikkelit"] = {"ok": 0, "virheet": 1, "viimeisin_virhe": f"{type(e).__name__}: {e}"[:150]}
    for u in uudet:
        laatupainotus(u)
    tila["_yhteenveto"] = {"uusia": len(uudet), "tekoaly": n_ai, "malli": n_malli,
                           "tulkinta": ("tekoäly (Claude)" if n_ai else
                                        "ilmaiset mallit (FinBERT + monikielinen)" if n_malli else "avainsanat")}
    return uudet, tila


# ====================================================================== tulkinta: ilmaiset mallit
_MALLIT = {}


def _kieli(otsikko: str) -> str:
    o = otsikko.lower()
    if re.search(r"[äöå]", o) or re.search(r"\b(ja|on|oyj|osake|pörssi|tulos|liikevaihto|yhtiö|suositus|nousi|laski)\b", o):
        return "fi"
    return "en"


def mallitulkinta(uutiset: list[Uutinen]) -> int:
    """Ilmaiset avoimet mallit (Hugging Face), jos transformers-kirjasto on asennettu:
    FinBERT englanninkielisille talousotsikoille, monikielinen malli muille."""
    if not uutiset:
        return 0
    try:
        from transformers import pipeline
    except ImportError:
        return 0
    try:
        if not _MALLIT:
            _MALLIT["en"] = pipeline("text-classification", model="ProsusAI/finbert", top_k=None)
            _MALLIT["fi"] = pipeline("text-classification",
                                     model="cardiffnlp/twitter-xlm-roberta-base-sentiment-multilingual", top_k=None)
    except Exception as e:  # noqa: BLE001
        print(f"  ! ilmaisten mallien lataus epäonnistui ({e}); käytetään avainsanoja")
        return 0
    tehty = 0
    for kieli in ("en", "fi"):
        joukko = [u for u in uutiset if _kieli(u.otsikko) == kieli]
        if not joukko:
            continue
        try:
            tulokset = _MALLIT[kieli]([u.otsikko[:300] for u in joukko], batch_size=32, truncation=True)
        except Exception as e:  # noqa: BLE001
            print(f"  ! mallitulkinta ({kieli}) epäonnistui: {e}")
            continue
        for u, tulos in zip(joukko, tulokset):
            p = {d["label"].lower(): d["score"] for d in tulos}
            tunnelma = p.get("positive", 0) - p.get("negative", 0)
            # Avainsanat tukena: jos malli on epävarma, mutta otsikossa on selvä signaali
            a_tun, paino = avainsanatulkinta(u.otsikko, u.tyyppi)
            if abs(tunnelma) < 0.2 and a_tun:
                tunnelma = 0.5 * a_tun
            u.tunnelma, u.paino, u.tulkinta = round(float(tunnelma), 2), paino, "malli"
            tehty += 1
    return tehty


# ====================================================================== laatu
LAADUKKAAT = re.compile(r"kauppalehti|arvopaperi|inderes|yle|hs\.fi|helsingin sanomat|talouselämä|reuters|bloomberg|"
                        r"financial times|wall street journal|dagens industri|e24|børsen|marketscreener|cision|"
                        r"globenewswire|nasdaq", re.I)
HEIKOT = re.compile(r"motley fool|simply wall st|invezz|ad-hoc-news|tradingview|benzinga|seeking alpha|"
                    r"zacks|insidermonkey|marketbeat|bioengineer", re.I)
KLIKKI = re.compile(r"^\d+ (stocks?|osaketta|dividend|best)|to consider|should you|is it time|worth buying|"
                    r"top \d+|\?$|what to expect|preview|watchlist|kannattaako", re.I)


VAKAVA = re.compile(
    r"\b(war|invasion|invade|missile|airstrike|terror\w*|earthquake|tsunami|hurricane|flood\w*|pandemic|outbreak|"
    r"epidemic|nuclear|coup|martial law|bankrupt\w*|insolven\w*|chapter 11|fraud|scandal|embezzl\w*|bribery|"
    r"indict\w*|arrest\w*|charged|probe|raid\w*|resign\w*|ousted|fired|steps down|sanction\w*|export ban|"
    r"export controls?|embargo|blacklist\w*|cyber ?attack|hack\w*|data breach|recall\w*|default\w*|crash\w*|"
    r"collapse\w*|plung\w*|plummet\w*|trading halt|suspend\w*|profit warning|guidance cut|misconduct|"
    r"harass\w*|lawsuit|class action|"
    r"sota\w*|hyökkäy\w*|ohjus\w*|terrori\w*|maanjäristy\w*|tulva\w*|pandemi\w*|vallankaappau\w*|"
    r"konkurss\w*|saneerau\w*|petos\w*|skandaal\w*|kavallu\w*|lahjo\w*|pidätet\w*|syyte\w*|tutkinta\w*|"
    r"eroaa|erosi|erotettiin|irtisanottiin|pakott\w*|vientikiel\w*|kyberhyökkäy\w*|tietomurto\w*|"
    r"takaisinve\w*|romah\w*|tulosvaroitu\w*|kaupankäynti keskeytet\w*)\b", re.I)


def vakavuus(u: Uutinen) -> None:
    """Merkitsee vakavat kielteiset uutiset (kriisit, katastrofit, skandaalit). Niihin reagoidaan heti."""
    if u.tunnelma < -0.2 and VAKAVA.search(u.otsikko):
        u.lisatieto["vakava"] = True
        u.paino = max(u.paino, 0.9)


def laatupainotus(u: Uutinen) -> None:
    julkaisija = u.lisatieto.get("julkaisija", "")
    kerroin = 1.0
    if LAADUKKAAT.search(julkaisija) or u.tyyppi == "tiedote":
        kerroin *= 1.25
    if HEIKOT.search(julkaisija):
        kerroin *= 0.5
    if KLIKKI.search(u.otsikko):
        kerroin *= 0.3
    u.paino = round(min(1.0, u.paino * kerroin), 2)
    vakavuus(u)


def uudelleentulkitse_arkisto(nimet: dict[str, str], paivia: int = 14) -> int:
    """Tulkitsee arkiston tuoreet avainsanoilla tulkitut uutiset uudelleen paremmalla
    menetelmällä (kun ilmaiset mallit tai tekoäly ovat saatavilla) ja poistaa turhat osumat."""
    raja = (datetime.now(timezone.utc) - timedelta(days=paivia)).isoformat()
    muutettu = 0
    for f in sorted(ARKISTO.glob("*.jsonl"))[-2:]:
        rivit = [Uutinen(**json.loads(r)) for r in f.read_text(encoding="utf-8").splitlines() if r.strip()]
        tuoreet = [u for u in rivit if u.aika >= raja and u.tulkinta == "avainsanat"]
        if not tuoreet:
            continue
        pidetaan = []
        for u in rivit:
            if u in tuoreet and u.tickerit and u.lahde in ("google_yhtiot", "yahoo") and \
                    not tunnista_tickerit(u.otsikko, {t: nimet.get(t, t) for t in u.tickerit}):
                muutettu += 1
                continue
            pidetaan.append(u)
        tuoreet = [u for u in tuoreet if u in pidetaan]
        n = mallitulkinta(tuoreet)
        if n == 0:
            continue
        for u in tuoreet:
            laatupainotus(u)
        muutettu += n
        f.write_text("".join(json.dumps(asdict(u), ensure_ascii=False) + "\n" for u in pidetaan), encoding="utf-8")
    return muutettu


def _nahdyt_tunnisteet(kk=2) -> set[str]:
    out = set()
    for f in sorted(ARKISTO.glob("*.jsonl"))[-kk:]:
        for rivi in f.read_text(encoding="utf-8").splitlines():
            try:
                d = json.loads(rivi)
                out.add(Uutinen(**{k: d[k] for k in ("aika", "otsikko", "lahde")}).tunniste)
            except (json.JSONDecodeError, KeyError, TypeError):
                pass
    return out


def tallenna(uutiset: list[Uutinen]) -> None:
    for u in uutiset:
        f = ARKISTO / f"{u.aika[:7]}.jsonl"
        f.parent.mkdir(parents=True, exist_ok=True)
        with open(f, "a", encoding="utf-8") as h:
            h.write(json.dumps(asdict(u), ensure_ascii=False) + "\n")


def lataa_arkisto(kk: int = 6) -> list[Uutinen]:
    out = []
    for f in sorted(ARKISTO.glob("*.jsonl"))[-kk:]:
        for rivi in f.read_text(encoding="utf-8").splitlines():
            try:
                out.append(Uutinen(**json.loads(rivi)))
            except (json.JSONDecodeError, TypeError):
                pass
    return out


def synteettiset_uutiset(tickerit: list[str], asti, paivia: int = 120, siemen: int = 7) -> list[Uutinen]:
    """Keksityt uutiset koodin testaamiseen ilman verkkoyhteyttä."""
    import random
    import pandas as pd
    out = []
    loppu = pd.Timestamp(asti)
    for d in pd.bdate_range(loppu - pd.Timedelta(days=paivia), loppu):
        rnd = random.Random(f"{siemen}-{d.date()}")
        for k in range(rnd.randint(3, 10)):
            t = rnd.choice(tickerit)
            tyyppi = rnd.choice(["tiedote", "uutinen", "uutinen", "analyytikko", "sisapiiri", "foorumi", "maailma"])
            tun = round(rnd.uniform(-1, 1), 2)
            out.append(Uutinen(aika=(d + pd.Timedelta(hours=rnd.randint(7, 17))).tz_localize("Europe/Helsinki").isoformat(),
                               otsikko=f"TESTI {d.date()} #{k}: {t} {tyyppi} {'hyvä' if tun > 0 else 'huono'} uutinen",
                               lahde="testi", tickerit=[] if tyyppi == "maailma" else [t], tyyppi=tyyppi,
                               tunnelma=tun, paino=round(rnd.uniform(0.2, 1), 2), tulkinta="testi",
                               lisatieto={"vakava": True} if tun < -0.9 else {}))
    return out
