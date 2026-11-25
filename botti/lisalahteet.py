"""Lisälähteet (v3→): pörssitiedotteet suoraan Nasdaqilta ja Trumpin Truth Social -päivitykset.

Tallennetaan omaan arkistoonsa (arkisto/lisalahteet/), jotta vanhojen versioiden (v1, v2)
tietopohja ei muutu. Uudet versiot lukevat sekä uutisarkiston että tämän.

- Nasdaq Nordic: kaikki Helsingin, Tukholman ja Kööpenhaminan pörssitiedotteet (tulokset,
  sisäpiiritieto, johdon liiketoimet, liputukset eli isojen omistajien muutokset). Koko teksti,
  ei klikkiotsikoita, ja ne ilmestyvät ensimmäisenä.
- Trump: trumpstruth.org-arkisto (ilmainen, ei kuulu Truth Socialiin).
"""
from __future__ import annotations

import html
import json
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from .uutiset import UA, Uutinen, tunnista_tickerit

ARKISTO = Path("arkisto/lisalahteet")
NASDAQ_URL = "https://api.news.eu.nasdaq.com/news/query.action"
NASDAQ_MARKKINAT = {"Main Market, Helsinki": ".HE", "First North Finland": ".HE", "Main Market, Stockholm": ".ST",
                    "Main Market, Copenhagen": ".CO"}
TRUMP_URL = "https://www.trumpstruth.org/feed"

# Nasdaqin tiedoteluokka -> uutistyyppi
LUOKKA_TYYPPI = {
    "managers' transactions": "sisapiiri",
    "major shareholder announcements": "liputus",
    "changes in company's own shares": "tiedote",
}


def _nasdaq_tyyppi(luokka: str) -> str:
    return LUOKKA_TYYPPI.get((luokka or "").strip().lower(), "tiedote")


def hae_nasdaq(nimet: dict[str, str], paivia: int = 3, max_sivuja: int = 5) -> list[Uutinen]:
    import requests
    alku = (datetime.now(ZoneInfo("Europe/Stockholm")) - timedelta(days=paivia)).strftime("%Y-%m-%d")
    out, nahty = [], set()
    for markkina, paate in NASDAQ_MARKKINAT.items():
        oman_porssin = {t: n for t, n in nimet.items() if t.endswith(paate)}
        for sivu in range(0, 200 * max_sivuja, 200):
            r = requests.get(NASDAQ_URL, timeout=30, headers=UA, params={
                "type": "json", "showAttachments": "false", "showCnsSpecific": "true", "showCompany": "true",
                "countResults": "false", "market": markkina, "fromDate": alku, "globalGroup": "exchangeNotice",
                "globalName": "NordicMainMarkets", "displayLanguage": "en", "timeZone": "CET",
                "dateMask": "yyyy-MM-dd HH:mm:ss", "limit": 200, "start": sivu, "dir": "DESC"})
            r.raise_for_status()
            rivit = r.json().get("results", {}).get("item", [])
            for d in rivit:
                yhtio = d.get("company") or ""
                tickerit = tunnista_tickerit(yhtio, oman_porssin)[:1]
                if not tickerit:
                    continue        # ei seurattu yhtiö
                # Sama tiedote eri kielillä: englanninkielinen ensin (paras tulkintamalli), muut ohitetaan
                avain = (tickerit[0], d["releaseTime"])
                if avain in nahty:
                    continue
                if d.get("language") != "en" and any(x.get("language") == "en" and x.get("company") == yhtio
                                                     and x.get("releaseTime") == d["releaseTime"] for x in rivit):
                    continue
                nahty.add(avain)
                aika = datetime.strptime(d["releaseTime"], "%Y-%m-%d %H:%M:%S").replace(
                    tzinfo=ZoneInfo("Europe/Stockholm")).astimezone(timezone.utc)
                if aika.strftime("%Y-%m-%d") < alku:
                    continue        # vanha tiedote, joka on päivitetty myöhemmin
                out.append(Uutinen(aika=aika.isoformat(timespec="seconds"), otsikko=f"{yhtio}: {d['headline']}",
                                   lahde="nasdaq", linkki=d.get("messageUrl", ""), tickerit=tickerit,
                                   tyyppi=_nasdaq_tyyppi(d.get("cnsCategory")),
                                   lisatieto={"luokka": d.get("cnsCategory", ""), "julkaisija": "Nasdaq"}))
            if len(rivit) < 200:
                break
            time.sleep(1)
        time.sleep(1)
    return out


def hae_trump(n: int = 100) -> list[Uutinen]:
    import requests
    r = requests.get(TRUMP_URL, params={"limit": n}, timeout=30, headers=UA)
    r.raise_for_status()
    out = []
    for it in ET.fromstring(r.content).findall(".//item"):
        teksti = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", it.findtext("description") or ""))).strip()
        if len(teksti) < 20 or teksti.startswith("http"):
            continue          # pelkkä kuva tai linkki
        aika = datetime.strptime(it.findtext("pubDate"), "%a, %d %b %Y %H:%M:%S %z").astimezone(timezone.utc)
        out.append(Uutinen(aika=aika.isoformat(timespec="seconds"), otsikko=teksti[:400], lahde="trump",
                           linkki=it.findtext("link") or "", tickerit=[], tyyppi="maailma",
                           lisatieto={"kirjoittaja": "Donald J. Trump"}))
    return out


def _nahdyt() -> set[str]:
    out = set()
    for f in sorted(ARKISTO.glob("*.jsonl"))[-2:]:
        for rivi in f.read_text(encoding="utf-8").splitlines():
            try:
                d = json.loads(rivi)
                out.add(Uutinen(**{k: d[k] for k in ("aika", "otsikko", "lahde")}).tunniste)
            except (ValueError, KeyError, TypeError):
                pass
    return out


def keraa(cfg: dict, nimet: dict[str, str]) -> tuple[list[Uutinen], dict]:
    """Hakee lisälähteet, tulkitsee ne ja palauttaa (uudet, lähteiden tila)."""
    from .uutiset import mallitulkinta, avainsanatulkinta, laatupainotus, vakavuus, hintaliikekorjaus
    lahteet = cfg.get("uutiset", {}).get("lahteet", {})
    tila, uudet = {}, []
    # Ensimmäisellä kerralla haetaan tiedotteet leikkikaupan alusta asti (uusi versio ajetaan alusta)
    alusta = not any(ARKISTO.glob("*.jsonl"))
    paivia = 16 if alusta else 3
    for nimi, fn, kaytossa in (("nasdaq_tiedotteet", lambda: hae_nasdaq(nimet, paivia, 25 if alusta else 5),
                                lahteet.get("nasdaq", True)),
                               ("trump", hae_trump, lahteet.get("trump", True))):
        if not kaytossa:
            continue
        t = tila.setdefault(nimi, {"ok": 0, "virheet": 0, "viimeisin_virhe": ""})
        try:
            rivit = fn()
            t["ok"] = len(rivit)
            uudet += rivit
        except Exception as e:  # noqa: BLE001
            t["virheet"] += 1
            t["viimeisin_virhe"] = f"{type(e).__name__}: {str(e)[:120]}"
    nahdyt = _nahdyt()
    uudet = [u for u in uudet if u.tunniste not in nahdyt]
    uudet = list({u.tunniste: u for u in uudet}.values())
    if uudet:
        mallitulkinta(uudet)
        for u in uudet:
            if u.tulkinta != "malli":
                u.tunnelma, u.paino = avainsanatulkinta(u.otsikko, u.tyyppi if u.tyyppi != "liputus" else "tiedote")
                u.tulkinta = "avainsanat"
        # Pörssitiedotteista luetaan koko teksti (sisäpiirikaupan suunta, tuloksen sävy)
        tiedotteet = [u for u in uudet if u.lahde == "nasdaq"]
        if tiedotteet and cfg.get("uutiset", {}).get("lue_artikkelit", True):
            from .artikkelit import lue_ja_tulkitse
            vanhat = {id(u): u.tyyppi for u in tiedotteet}
            for u in tiedotteet:
                if u.tyyppi == "liputus":
                    u.tyyppi = "tiedote"
            try:
                tila["nasdaq_tekstit"] = {"ok": 0, "virheet": 0, "viimeisin_virhe": "",
                                          **lue_ja_tulkitse(tiedotteet, nimet, 250 if alusta else 120)}
                tila["nasdaq_tekstit"]["ok"] = tila["nasdaq_tekstit"]["luettu"]
            except Exception as e:  # noqa: BLE001
                tila["nasdaq_tekstit"] = {"ok": 0, "virheet": 1, "viimeisin_virhe": f"{type(e).__name__}: {e}"[:150]}
            for u in tiedotteet:
                u.tyyppi = vanhat[id(u)]
        for u in uudet:
            hintaliikekorjaus(u)
            laatupainotus(u)
            vakavuus(u)
    return uudet, tila


def tallenna(uutiset: list[Uutinen]) -> None:
    for u in uutiset:
        f = ARKISTO / f"{u.aika[:7]}.jsonl"
        f.parent.mkdir(parents=True, exist_ok=True)
        with open(f, "a", encoding="utf-8") as h:
            h.write(json.dumps(asdict(u), ensure_ascii=False) + "\n")


def lataa(kk: int = 6) -> list[Uutinen]:
    out = []
    for f in sorted(ARKISTO.glob("*.jsonl"))[-kk:]:
        for rivi in f.read_text(encoding="utf-8").splitlines():
            try:
                out.append(Uutinen(**json.loads(rivi)))
            except (ValueError, TypeError):
                pass
    return out
