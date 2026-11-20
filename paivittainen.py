"""Päivittäinen leikkikauppa. Aja kerran päivässä pörssin sulkeuduttua (klo 19 jälkeen).

  python paivittainen.py            # päivitä botit ja tee raportti
  python paivittainen.py --nollaa   # aloita leikkikauppa alusta

Jos jokin päivä jää väliin, botti käsittelee välistä puuttuvat päivät
seuraavalla ajokerralla automaattisesti.
"""
from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from botti import lataa_asetukset
from botti.data import Paneeli, lataa_paneeli, synteettinen_paneeli
from botti import uutiset as uutismoduuli
from botti.versiot import aja_kaikki
from botti.moottori import Moottori
from botti.raportti import html_raportti, markkinasarja
from botti.signaalit import Signaalit
from botti.valittaja import Salkku, Toimeksianto

TILA = Path("tila/salkut.json")
TILAVERSIO = 3   # kasvatetaan, kun bottien kokoonpano muuttuu -> vanha tila talletetaan ja aloitetaan alusta
ARKISTO = Path("arkisto")
DOCS = Path("docs")


def arkistoi_kurssit(paneeli: Paneeli, paivat) -> None:
    """Tallentaa käsiteltyjen päivien kurssit omaan arkistoon (kuukausittaiset CSV:t).
    Näin data säilyy, vaikka Yahoo muuttaisi tai poistaisi historiaa."""
    for p in paivat:
        rivit = pd.DataFrame({"avaus": paneeli.avaus.loc[p], "paatos": paneeli.paatos.loc[p],
                              "vaihto_eur": paneeli.vaihto.loc[p]}).dropna(subset=["paatos"]).round(4)
        rivit.insert(0, "paiva", str(p.date()))
        rivit.index.name = "osake"
        f = ARKISTO / "kurssit" / f"{p:%Y-%m}.csv"
        f.parent.mkdir(parents=True, exist_ok=True)
        if f.exists():
            vanhat = pd.read_csv(f, index_col="osake")
            rivit = pd.concat([vanhat[vanhat["paiva"] != str(p.date())], rivit])
        rivit.to_csv(f)


def julkaise(sivu: str, paiva: pd.Timestamp) -> None:
    """Raporttisivu docs/-kansioon (GitHub Pages) + päiväkohtainen arkisto."""
    (DOCS / "arkisto").mkdir(parents=True, exist_ok=True)
    (DOCS / ".nojekyll").touch()
    (DOCS / "index.html").write_text(sivu, encoding="utf-8")
    (DOCS / "arkisto" / f"{paiva.date()}.html").write_text(sivu, encoding="utf-8")
    raportit = sorted((DOCS / "arkisto").glob("20*.html"), reverse=True)
    linkit = "".join(f'<li><a href="{r.name}">{r.stem}</a></li>' for r in raportit)
    (DOCS / "arkisto" / "index.html").write_text(
        '<!DOCTYPE html><html lang="fi"><meta charset="utf-8"><meta name="viewport" content="width=device-width">'
        '<title>Raporttiarkisto</title><body style="font:15px system-ui;max-width:600px;margin:30px auto">'
        f'<h1>Raporttiarkisto</h1><p><a href="../">← Uusin raportti</a></p><ul>{linkit}</ul></body></html>',
        encoding="utf-8")


def uutisjarjestys(cfg: dict, paneeli, tila: dict) -> list[str]:
    """Yhtiöuutiset haetaan tärkeysjärjestyksessä (hakuja on rajallisesti):
    omistukset ja odottavat kaupat -> perusvalikoima -> laajan valikoiman vahvimmat nousijat."""
    tarkeat = []
    for d in tila.get("botit", {}).values():
        tarkeat += list(d.get("positiot", {})) + [o["ticker"] for o in d.get("odottavat", [])]
    perus = cfg["valikoimat_tickerit"].get("perus", [])
    muut = [t for t in cfg["tickerit"] if t not in perus]
    if muut:
        c = paneeli.paatos[[t for t in muut if t in paneeli.paatos.columns]]
        nousu = (c.iloc[-1] / c.iloc[-21] - 1).abs().sort_values(ascending=False)   # isoimmat liikkeet ensin
        muut = list(nousu.index) + [t for t in muut if t not in nousu.index]
    jarjestys = []
    for t in tarkeat + perus + muut:
        if t not in jarjestys:
            jarjestys.append(t)
    return jarjestys


def aamutarkistus(tila: dict, sig: Signaalit, paiva) -> list[str]:
    """Yön aikana (USA, Aasia) tulleet vakavat uutiset ennen pörssin avautumista:
    - omistetusta yhtiöstä vakava kielteinen uutinen -> myydään avauksessa
    - kriisihälytys (paljon vakavia maailmanuutisia) -> perutaan odottavat ostot"""
    from datetime import datetime as _dt
    klo = _dt.now(ZoneInfo("Europe/Helsinki")).strftime("%H:%M")
    huomiot = []
    kriisi = sig.kriisissa(paiva)
    for osa, d in tila.get("botit", {}).items():
        if osa == "indeksi":
            continue
        s = Salkku.from_dict(d)
        myytavana = {o.ticker for o in s.odottavat if o.suunta == "MYY"}
        for t, p in s.positiot.items():
            u = sig.hatauutinen(t, paiva)
            if u is not None and t not in myytavana:
                s.odottavat.append(Toimeksianto(t, "MYY", kpl=p.kpl, annettu=str(paiva.date()),
                                                syy=f"AAMUTARKISTUS: vakava uutinen yöllä: {u.otsikko[:100]}"))
                huomiot.append(f"Aamutarkistus {klo} [{osa}]: myydään {t} – {u.otsikko[:80]}")
        perutut = [o.ticker for o in s.odottavat if o.suunta == "OSTA" and sig.kielteinen_uutinen(o.ticker, paiva)]
        if perutut:
            s.odottavat = [o for o in s.odottavat if not (o.suunta == "OSTA" and o.ticker in perutut)]
            huomiot.append(f"Aamutarkistus {klo} [{osa}]: perutaan osto {', '.join(perutut)} – kielteinen uutinen yöllä")
        tila["botit"][osa] = s.to_dict()
    if kriisi:
        huomiot.append(f"Aamutarkistus {klo}: KRIISITILA – vakavia maailmanuutisia {sig.kriisitaso.loc[paiva]:.1f}x "
                       "tavallista. Suoraan osuvat myydään, uudet ostot vain kestävimpiin osakkeisiin.")
    if not huomiot:
        huomiot.append(f"Aamutarkistus {klo}: yön uutisissa ei vakavia muutoksia – toimeksiannot ennallaan")
    for h in huomiot:
        print(" ", h)
    return huomiot


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--nollaa", action="store_true", help="poista vanha leikkisalkku ja aloita alusta")
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--testidata", action="store_true", help="keksitty data (koodin testaus)")
    ap.add_argument("--julkaise", action="store_true", help="kirjoita raportti myös docs/-kansioon (pilviajo)")
    ap.add_argument("--aamu", action="store_true",
                    help="aamutarkistus ennen pörssin avautumista: yön uutiset, hätämyynnit ja kriisihälytys")
    ap.add_argument("--testi-asti", help="testidatalla: käsittele vain tähän päivään asti (YYYY-MM-DD)")
    a = ap.parse_args()

    cfg = lataa_asetukset(a.config)
    if a.nollaa and TILA.exists():
        varmuus = TILA.with_name(f"salkut_{datetime.now():%Y%m%d_%H%M}.json")
        shutil.move(TILA, varmuus)
        print(f"Vanha tila talletettu: {varmuus}")

    # Data: haetaan reilusti historiaa indikaattoreita varten
    alku = (datetime.now() - timedelta(days=500)).strftime("%Y-%m-%d")
    if a.testidata:
        paneeli = synteettinen_paneeli(cfg["tickerit"], "2016-01-01")
        if a.testi_asti:
            paneeli = paneeli.asti(a.testi_asti)
    else:
        paneeli = lataa_paneeli(cfg["tickerit"], alku)
        # Ennen klo 19 tämän päivän rivi on keskeneräinen -> jätetään pois
        nyt = datetime.now(ZoneInfo("Europe/Helsinki"))  # toimii myös pilvessä (UTC-kone)
        tanaan = pd.Timestamp(nyt.date())
        if paneeli.paatos.index[-1] == tanaan and nyt.hour < 19:
            paneeli = paneeli.ilman_viimeista()
    viimeisin = paneeli.paatos.index[-1]

    # Tila
    if TILA.exists():
        tila = json.loads(TILA.read_text(encoding="utf-8"))
        if tila.get("versio") != TILAVERSIO:
            varmuus = TILA.with_name(f"salkut_vanha_v{tila.get('versio', 2)}.json")
            shutil.move(TILA, varmuus)
            print(f"Bottien kokoonpano muuttui – vanha tila talletettu: {varmuus}")
            tila = None
    else:
        tila = None
    if tila is None:
        tila = {"versio": TILAVERSIO, "aloitettu": str(viimeisin.date()), "kuluprofiili": cfg["kuluprofiili"],
                "alkupaaoma": cfg["alkupaaoma"], "botit": {}}
        print(f"Aloitetaan uusi leikkikauppa {viimeisin.date()}, {cfg['alkupaaoma']} € per botti.")
    aloitus = pd.Timestamp(tila["aloitettu"])

    edellinen = tila.get("viimeisin_kasitelty")
    uudet_paivat = (paneeli.paatos.index[paneeli.paatos.index > pd.Timestamp(edellinen)]
                    if edellinen else paneeli.paatos.index[-1:])
    if len(uudet_paivat) == 0:
        print(f"Ei uusia kauppapäiviä ({viimeisin.date()} on jo käsitelty).")

    # Uutiset, tiedotteet, foorumit ja maailma
    lahdetila = {}
    if cfg.get("uutiset", {}).get("kaytossa", True):
        if a.testidata:
            uudet = uutismoduuli.synteettiset_uutiset(cfg["tickerit"], viimeisin)
            lahdetila = {"_yhteenveto": {"uusia": len(uudet), "tekoaly": 0, "tulkinta": "testidata"}}
        else:
            print("Kerätään uutisia...")
            uudet, lahdetila = uutismoduuli.keraa(cfg, uutisjarjestys(cfg, paneeli, tila))
            n = uutismoduuli.uudelleentulkitse_arkisto(uutismoduuli.lataa_nimet(cfg["tickerit"]))
            if n:
                print(f"  {n} aiempaa uutista tulkittu uudelleen")
        uutismoduuli.tallenna(uudet)
        print(f"  {len(uudet)} uutta uutista/viestiä")
    sig = Signaalit(uutismoduuli.lataa_arkisto(), paneeli.paatos.index, paneeli.tickerit)

    aamuhuomiot = aamutarkistus(tila, sig, viimeisin) if a.aamu else []

    moottori = Moottori(cfg)          # raportin kulumallia varten
    if a.aamu:   # aamulla ei käsitellä uusia kauppapäiviä, vain muutetaan odottavia toimeksiantoja
        tila["viimeisin_kasitelty"] = tila.get("viimeisin_kasitelty") or str(viimeisin.date())
    # Jokainen botti ajetaan omalla lukitulla versiollaan (versiot/), rinnakkain samoilla tiedoilla
    tulokset, huomiot, tila["botit"], paatosloki = aja_kaikki(cfg, paneeli, tila["botit"],
                                                              alku=max(aloitus, viimeisin), aloitus=aloitus)
    moottori.paatosloki = paatosloki

    huomiot = aamuhuomiot + huomiot
    tila["viimeisin_kasitelty"] = str(viimeisin.date())
    TILA.parent.mkdir(exist_ok=True)
    TILA.write_text(json.dumps(tila, ensure_ascii=False, indent=1), encoding="utf-8")

    # Arkisto: kurssit + jokainen päätös perusteluineen (uudelleenajoa ja jälkiarviointia varten)
    if not a.testidata:
        arkistoi_kurssit(paneeli, uudet_paivat)
    if moottori.paatosloki:
        ARKISTO.mkdir(exist_ok=True)
        with open(ARKISTO / "paatokset.jsonl", "a", encoding="utf-8") as f:
            for rivi in moottori.paatosloki:
                f.write(json.dumps(rivi, ensure_ascii=False) + "\n")

    vertailu = markkinasarja(paneeli, aloitus, cfg["alkupaaoma"])
    Path("raportit").mkdir(exist_ok=True)
    sivu = html_raportti(f"Leikkikauppa – päivä {len(vertailu)}" + (" – TESTIDATA" if a.testidata else ""),
                         "leikkikauppa", tulokset, vertailu, paneeli, moottori.kulut,
                         cfg["alkupaaoma"], huomiot, sig=sig, lahdetila=lahdetila,
                         paatokset=moottori.paatosloki)
    polku = Path(f"raportit/raportti_{viimeisin.date()}.html")
    polku.write_text(sivu, encoding="utf-8")
    Path("raportit/viimeisin.html").write_text(sivu, encoding="utf-8")
    if a.julkaise:
        julkaise(sivu, viimeisin)

    # Yhteenveto komentoriville
    hinnat = paneeli.paatos.iloc[-1]
    print(f"\nKurssit {viimeisin.date()} asti. Leikkikauppa aloitettu {aloitus.date()}.")
    for t in tulokset:
        s = t["salkku"]
        print(f"  {t['nimi']:<12} arvo {s.arvo(hinnat):8.2f} €  omistukset: "
              f"{', '.join(s.positiot) or '–'}")
        for o in s.odottavat:
            print(f"      -> {o.suunta} {o.ticker}  ({o.syy})")
    print(f"  {'helsinki':<12} arvo {vertailu.iloc[-1]:8.2f} €")
    print(f"\nRaportti: {polku.resolve()}")


if __name__ == "__main__":
    main()
