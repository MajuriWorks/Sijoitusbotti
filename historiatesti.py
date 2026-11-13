"""Historiatesti: miten botit olisivat pärjänneet menneinä vuosina.

HUOM: menneiden vuosien uutisia ei ole saatavilla ilmaiseksi, joten historiatesti
käyttää vain kurssitietoja. Uutisten, foorumien ja maailman tapahtumien hyöty
mitataan leikkikaupassa.

  python historiatesti.py                       # oikea data (vaatii netin)
  python historiatesti.py --vertaa-kulut        # sama eri välittäjien kuluilla
  python historiatesti.py --alku 2026-11-16     # uudelleenajo tietystä päivästä
  python historiatesti.py --testidata           # keksityllä datalla (koodin testaus)
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from botti import lataa_asetukset
from botti.botit import aja_botit
from botti.data import lataa_paneeli, synteettinen_paneeli
from botti.moottori import Moottori
from botti.raportti import html_raportti, markkinasarja, tunnusluvut
from botti.signaalit import Signaalit

LAMMITYS_PV = 260  # indikaattorit tarvitsevat noin vuoden historiaa ennen ensimmäistä kauppaa


def aja(cfg, paneeli, testialku):
    moottori = Moottori(cfg)
    sig = Signaalit.tyhja(paneeli.paatos.index, paneeli.tickerit)
    tulokset, huomiot, _ = aja_botit(cfg, paneeli, sig, moottori, alku=testialku)
    return tulokset, huomiot, moottori


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--testidata", action="store_true", help="käytä keksittyä dataa")
    ap.add_argument("--kuluprofiili", help="esim. nordnet, nordnet_osakesaastajat, nordea")
    ap.add_argument("--vertaa-kulut", action="store_true", help="aja kaikilla kuluprofiileilla")
    ap.add_argument("--alku", help="aloita testi tästä päivästä (YYYY-MM-DD)")
    ap.add_argument("--julkaise", action="store_true", help="kirjoita raportti myös docs/-kansioon (pilviajo)")
    ap.add_argument("--config", default="config.yaml")
    a = ap.parse_args()

    cfg = lataa_asetukset(a.config, a.kuluprofiili)
    print(f"Ladataan kurssit ({len(cfg['tickerit'])} kohdetta)...")
    paneeli = (synteettinen_paneeli(cfg["tickerit"], cfg["historia_alku"]) if a.testidata
               else lataa_paneeli(cfg["tickerit"], cfg["historia_alku"]))
    testialku = paneeli.paatos.index[min(LAMMITYS_PV, len(paneeli.paatos) - 1)]
    if a.alku:
        testialku = max(testialku, pd.Timestamp(a.alku))
    print(f"Testijakso {testialku.date()} – {paneeli.paatos.index[-1].date()}, "
          f"alkupääoma {cfg['alkupaaoma']} € per botti (vain kurssitiedot)\n")

    if a.vertaa_kulut:
        print("Loppuarvo / kulut yhteensä eri välittäjillä:")
        for prof in cfg["kuluprofiilit"]:
            c = lataa_asetukset(a.config, prof)
            tulokset, _, _ = aja(c, paneeli, testialku)
            osat = [f"{t['nimi']}: {tunnusluvut(t['sarja'], c['alkupaaoma'], t['salkku'])['Loppuarvo']} "
                    f"(kulut {t['salkku'].kulut_yht:.0f} €)" for t in tulokset]
            print(f"  {prof:<24} " + " | ".join(osat))
        print()

    tulokset, huomiot, moottori = aja(cfg, paneeli, testialku)
    vertailu = markkinasarja(paneeli, testialku, cfg["alkupaaoma"])
    print(f"Kuluprofiili: {cfg['kuluprofiili']}")
    for t in tulokset + [{"nimi": "Helsinki", "sarja": vertailu, "salkku": None}]:
        l = tunnusluvut(t["sarja"], cfg["alkupaaoma"], t["salkku"])
        print(f"  {t['nimi']:<11} " + "  ".join(f"{k}: {v}" for k, v in l.items()))

    Path("raportit").mkdir(exist_ok=True)
    polku = Path("raportit/historiatesti.html")
    polku.write_text(html_raportti(
        f"Historiatesti ({cfg['kuluprofiili']}, vain kurssitiedot)" + (" – TESTIDATA" if a.testidata else ""),
        "historiatesti", tulokset, vertailu, paneeli, moottori.kulut, cfg["alkupaaoma"], huomiot),
        encoding="utf-8")
    if a.julkaise:
        Path("docs").mkdir(exist_ok=True)
        Path("docs/historiatesti.html").write_text(polku.read_text(encoding="utf-8"), encoding="utf-8")
    print(f"\nRaportti: {polku.resolve()}")


if __name__ == "__main__":
    main()
