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
    tickerit = []
    for ryhma in cfg["osakkeet"].values():
        tickerit += [t for t in (ryhma or []) if t not in tickerit]
    etf = (cfg["botit"].get("indeksi") or {}).get("etf")
    if etf and etf not in tickerit:
        tickerit.append(etf)
    cfg["tickerit"] = tickerit
    cfg["kaytossa_botit"] = [b for b, a in cfg["botit"].items() if a.get("kaytossa")]
    return cfg
