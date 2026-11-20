"""Bottiversiot rinnakkain.

Jokainen botti ajetaan sillä koodiversiolla, joka on merkitty config.yaml:ssa (versio: v1).
Lukitut versiot ovat kansiossa versiot/<versio>/botti, eikä niihin kosketa. Kun sääntöjä
halutaan muuttaa, tehdään uusi versio ja uusi botti sen rinnalle – vanha jatkaa ennallaan,
ja niitä voi verrata samalla jaksolla samoilla tiedoilla.
"""
from __future__ import annotations

import importlib

MODUULIT = ("botit", "moottori", "signaalit", "uutiset")


def lataa_versio(versio: str | None) -> dict:
    juuri = "botti" if versio in (None, "", "kehitys") else f"versiot.{versio}.botti"
    return {m: importlib.import_module(f"{juuri}.{m}") for m in MODUULIT}


def aja_kaikki(cfg: dict, paneeli, tila_botit: dict, alku, aloitus=None):
    """Ajaa kaikki käytössä olevat botit omilla versioillaan.
    Palauttaa (tulokset, huomiot, uusi tila, päätösloki)."""
    ryhmat: dict[str, list[tuple[str, str]]] = {}
    for nimi, asetukset in cfg["botit"].items():
        if asetukset.get("kaytossa"):
            ryhmat.setdefault(asetukset.get("versio", "v1"), []).append((nimi, asetukset.get("pohja", nimi)))
    # aloita: alusta -> uusi botti ajetaan leikkikaupan alusta asti tallennetuilla tiedoilla,
    # jolloin sitä voi verrata vanhoihin samalla jaksolla (uudelleenajo)

    tulokset, huomiot, uusi_tila, paatokset = [], [], dict(tila_botit), []
    lukitut = cfg.get("versiot", {})
    for versio, botit in ryhmat.items():
        M = lataa_versio(versio)
        uutiset = M["uutiset"].lataa_arkisto()
        signaalit = {}
        moottori = M["moottori"].Moottori(cfg)
        moottori.paatosloki = []
        for nimi, pohja in botit:
            # Botin oma valikoima (oletus "perus" = v1-bottien alkuperäinen)
            vnimi = cfg["botit"][nimi].get("valikoima", "perus")
            oma = paneeli.osajoukko(cfg["valikoimat_tickerit"].get(vnimi, paneeli.tickerit))
            if vnimi not in signaalit:
                signaalit[vnimi] = M["signaalit"].Signaalit(uutiset, oma.paatos.index, oma.tickerit)
            sig = signaalit[vnimi]
            def avain(osa, nimi=nimi, pohja=pohja):
                return osa if nimi == pohja else f"{osa}@{nimi}"
            vcfg = dict(cfg, kaytossa_botit=[pohja])
            osatila = {osa: tila_botit[avain(osa)] for osa, *_ in M["botit"].OSAT[pohja] if avain(osa) in tila_botit}
            oma_alku = aloitus if (cfg["botit"][nimi].get("aloita") == "alusta" and aloitus is not None) else alku
            t, h, ot = M["botit"].aja_botit(vcfg, oma, sig, moottori, osatila, alku=oma_alku)
            for osa, d in ot.items():
                uusi_tila[avain(osa)] = d
            for x in t:
                if nimi != pohja:
                    x["nimi"] = cfg["botit"][nimi].get("nimi", nimi)
                x["nimi"] = f"{x['nimi']} {versio}"
                tieto = lukitut.get(versio, {})
                x["kuvaus"] = (f"Versio {versio}" + (f", lukittu {tieto['lukittu']}" if tieto.get("lukittu") else "")
                               + (f": {tieto['muutos']}" if tieto.get("muutos") else "") + ". " + x["kuvaus"])
            tulokset += t
            huomiot += [f"[{nimi} {versio}] {y}" for y in h]
        for p in moottori.paatosloki:
            p["versio"] = versio
        paatokset += moottori.paatosloki
    return tulokset, huomiot, uusi_tila, paatokset
