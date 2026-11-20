"""Sijoitusbotti – leikkirahasimulaatio Helsingin (ja USA:n) pörsseille."""
from pathlib import Path

import yaml


def lataa_asetukset(polku: str | Path = "config.yaml", kuluprofiili: str | None = None) -> dict:
    with open(polku, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    nimi = kuluprofiili or cfg["kuluprofiili"]
    if nimi not in cfg["kuluprofiilit"]:
        raise SystemExit(f"Tuntematon kuluprofiili '{nimi}'. Vaihtoehdot: {', '.join(cfg['kuluprofiilit'])}")
    cfg["kulut"] = cfg["kuluprofiilit"][nimi]
    cfg["kuluprofiili"] = nimi
    # Ryhmät: lista tunnuksia tai "auto" (haetaan automaattisesti, ks. valikoimat.py)
    ryhmat, nimet = {}, {}
    for ryhma, lista in cfg["osakkeet"].items():
        if lista == "auto":
            from .valikoimat import hae
            data = hae(ryhma)
            ryhmat[ryhma] = list(data)
            nimet.update(data)
        else:
            ryhmat[ryhma] = list(lista or [])
    cfg["valmiit_nimet"] = nimet
    etf = (cfg["botit"].get("indeksi") or {}).get("etf")
    # Valikoimat: nimetyt ryhmäyhdistelmät; botti käyttää omaansa (oletus "perus")
    valikoimat = cfg.get("valikoimat") or {"perus": list(ryhmat)}
    cfg["valikoimat_tickerit"] = {}
    for vnimi, ryhmanimet in valikoimat.items():
        lista = []
        for r in ryhmanimet:
            lista += [t for t in ryhmat.get(r, []) if t not in lista]
        if etf and etf not in lista:
            lista.append(etf)
        cfg["valikoimat_tickerit"][vnimi] = lista
    kaytossa = {a.get("valikoima", "perus") for a in cfg["botit"].values() if a.get("kaytossa")}
    tickerit = []
    for vnimi in ["perus"] + sorted(kaytossa - {"perus"}):
        tickerit += [t for t in cfg["valikoimat_tickerit"].get(vnimi, []) if t not in tickerit]
    cfg["tickerit"] = tickerit
    # Historiatesti ajaa perusbotit nykyisellä koodilla; leikkikauppa ajaa jokaisen botin omalla versiollaan
    cfg["kaytossa_botit"] = [b for b, a in cfg["botit"].items() if a.get("kaytossa") and "pohja" not in a]
    return cfg
