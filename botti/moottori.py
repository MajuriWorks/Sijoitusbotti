"""Moottori: yksi kauppapäivä yhdelle botille.

Sama koodi ajaa sekä historiatestin että päivittäisen leikkikaupan, joten
testissä nähty käytös on täsmälleen sitä, mitä botti tekee oikeasti.
"""
from __future__ import annotations

import pandas as pd

from .data import Paneeli
from .strategiat import Strategia
from .valittaja import Kulumalli, LeikkiValittaja, Salkku, Toimeksianto


class Moottori:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.riskit = cfg["riskit"]
        self.kulut = Kulumalli(cfg["kulut"])
        self.valittaja = LeikkiValittaja(self.kulut)
        self.paatosloki: list[dict] | None = None   # leikkikaupassa lista, historiatestissä None

    # ------------------------------------------------------------------ päivä
    def askel(self, salkku: Salkku, strategia: Strategia, paneeli: Paneeli, paiva: pd.Timestamp) -> list[str]:
        """Palauttaa listan huomioita (esim. ohitetut kaupat)."""
        avaus = paneeli.avaus.loc[paiva]
        paatos = paneeli.paatos.loc[paiva]
        huomiot: list[str] = []

        # 1) Eilen annetut toimeksiannot toteutuvat tämän päivän avauksessa
        self.valittaja.toteuta(salkku, paiva, avaus)
        self.valittaja.paivita_huiput(salkku, paatos)

        # 2) Stop-loss tarkistetaan joka päivä
        sl = (getattr(strategia, "stop_loss", None) or self.riskit["stop_loss_prosentti"]) / 100
        myytavana = {o.ticker for o in salkku.odottavat if o.suunta == "MYY"}
        for t, p in (salkku.positiot.items() if getattr(strategia, "kayta_stop_lossia", True) else []):
            h = paatos.get(t)
            if t not in myytavana and h is not None and not pd.isna(h) and h <= p.huippu * (1 - sl):
                salkku.odottavat.append(Toimeksianto(
                    t, "MYY", kpl=p.kpl, annettu=str(paiva.date()),
                    syy=f"Stop-loss: kurssi {h / p.huippu - 1:.1%} huipusta"))
                myytavana.add(t)

        # 3) Strategian päätös
        if strategia.onko_paatospaiva(paiva, salkku.viimeisin_paatos):
            salkku.viimeisin_paatos = str(paiva.date())
            huomiot += self._paata(salkku, strategia, paiva, paatos, myytavana)

        salkku.arvohistoria[str(paiva.date())] = round(salkku.arvo(paatos), 2)
        return huomiot

    # ------------------------------------------------------------------ päätös
    def _paata(self, salkku, strategia, paiva, paatos, myytavana) -> list[str]:
        n = getattr(strategia, "max_positiot", None) or self.riskit["max_positiot"]
        omistukset = set(salkku.positiot) - myytavana
        strategia.positiot = salkku.positiot
        ehd = strategia.ehdota(paiva, omistukset, n)
        huomiot = []
        pv = str(paiva.date())
        if self.paatosloki is not None:
            self.paatosloki.append({
                "paiva": pv, "botti": strategia.nimi, "omistukset": sorted(omistukset),
                "pidetaan": sorted(omistukset & ehd.pidettavat),
                "ehdokkaat": [{"osake": t, "perustelu": ehd.perustelut.get(t, "")} for t in ehd.ostettavat[:10]],
                "myydaan": {t: ehd.perustelut.get(t, "") for t in sorted(omistukset - ehd.pidettavat)},
                "estetty": ehd.estetty,
            })

        myydaan = omistukset - ehd.pidettavat
        for t in myydaan:
            salkku.odottavat.append(Toimeksianto(
                t, "MYY", kpl=salkku.positiot[t].kpl, annettu=pv, syy=ehd.perustelut.get(t, "")))

        pidetaan = omistukset & ehd.pidettavat
        vapaat = n - len(pidetaan)
        if vapaat <= 0:
            return huomiot

        # Arvioidaan käytettävissä oleva raha myyntien jälkeen (päätöskursseilla)
        raha = salkku.kateinen
        for t in myydaan | myytavana:
            if t in salkku.positiot:
                s = salkku.positiot[t].kpl * float(paatos[t])
                raha += s - self.kulut.kulu(t, s)
        varaus = (self.riskit["kateisvara_prosentti"] / 100) * salkku.arvo(paatos)
        raha -= varaus

        uudet = [t for t in ehd.ostettavat if t not in pidetaan and t not in myytavana][:vapaat]
        if not uudet:
            return huomiot
        max_kulu = self.riskit["max_kulu_prosentti"]
        # Pieni salkku: yksi osake saa maksaa enemmän kuluja kuin tavallisesti,
        # muuten botti jäisi pysyvästi käteiselle tappioiden jälkeen.
        if raha < self.kulut.pienin_jarkeva_kauppa(uudet[0], max_kulu):
            max_kulu = max_kulu * 1.6
        # Jos raha ei riitä järkevän kokoisiin kauppoihin kaikille, ostetaan vähemmän osakkeita
        raja1 = self.kulut.pienin_jarkeva_kauppa(uudet[0], max_kulu)
        mahtuu = max(1, int(raha // raja1)) if raja1 > 0 else len(uudet)
        uudet = uudet[:mahtuu]
        osuus = raha / len(uudet)
        for t in uudet:
            raja = self.kulut.pienin_jarkeva_kauppa(t, max_kulu)
            if osuus < raja or osuus < float(paatos[t]):
                huomiot.append(f"{pv}: ohitettiin {t} – {osuus:.0f} € on liian pieni kauppa "
                               f"(kulut > {max_kulu} %, raja {raja:.0f} €)")
                continue
            salkku.odottavat.append(Toimeksianto(
                t, "OSTA", summa=osuus, annettu=pv, syy=ehd.perustelut.get(t, "")))
        return huomiot

    # ------------------------------------------------------------------ jakso
    def aja(self, salkku: Salkku, strategia: Strategia, paneeli: Paneeli,
            alku: pd.Timestamp | None = None) -> list[str]:
        """Ajaa kaikki päivät alusta (tai viimeksi käsitellyn jälkeisestä päivästä) loppuun."""
        paivat = paneeli.paatos.index
        if salkku.arvohistoria:
            viimeisin = pd.Timestamp(max(salkku.arvohistoria))
            paivat = paivat[paivat > viimeisin]
        elif alku is not None:
            paivat = paivat[paivat >= alku]
        huomiot = []
        for p in paivat:
            huomiot += self.askel(salkku, strategia, paneeli, p)
        return huomiot
