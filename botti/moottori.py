"""Moottori: yksi kauppapäivä yhdelle botille.

Sama koodi ajaa sekä historiatestin että päivittäisen leikkikaupan, joten
testissä nähty käytös on täsmälleen sitä, mitä botti tekee oikeasti.
"""
from __future__ import annotations

import pandas as pd

from .data import Paneeli
from .strategiat import Strategia
from . import skeptikko
from .valittaja import Kulumalli, LeikkiValittaja, Salkku, Toimeksianto


class Moottori:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.riskit = cfg["riskit"]
        self.kulut = Kulumalli(cfg["kulut"])
        self.valittaja = LeikkiValittaja(self.kulut)
        self.paatosloki: list[dict] | None = None   # leikkikaupassa lista, historiatestissä None

    def _likviditeetti(self, paneeli, paiva) -> pd.Series:
        """Päivävaihdon mediaani 20 pv ajalta (hintaeron arviointiin)."""
        if getattr(self, "_lik_id", None) != id(paneeli):
            self._lik = paneeli.vaihto.rolling(20, min_periods=5).median().shift(1)
            self._lik_id = id(paneeli)
        return self._lik.loc[paiva]

    def _likviditeetti_nyt(self, paiva):
        return self._lik.loc[paiva] if getattr(self, "_lik_id", None) is not None else None

    # ------------------------------------------------------------------ päivä
    def askel(self, salkku: Salkku, strategia: Strategia, paneeli: Paneeli, paiva: pd.Timestamp) -> list[str]:
        """Palauttaa listan huomioita (esim. ohitetut kaupat)."""
        avaus = paneeli.avaus.loc[paiva]
        paatos = paneeli.paatos.loc[paiva]
        huomiot: list[str] = []

        # 1) Eilen annetut toimeksiannot toteutuvat tämän päivän avauksessa
        self.valittaja.toteuta(salkku, paiva, avaus, paneeli.matala.loc[paiva], self._likviditeetti(paneeli, paiva))
        self.valittaja.paivita_huiput(salkku, paatos)

        # 2) Stop-loss tarkistetaan joka päivä
        sl = (getattr(strategia, "stop_loss", None) or self.riskit["stop_loss_prosentti"]) / 100
        myytavana = {o.ticker for o in salkku.odottavat if o.suunta == "MYY"}
        for t, p in (salkku.positiot.items() if getattr(strategia, "kayta_stop_lossia", True) else []):
            h = paatos.get(t)
            if t in myytavana or h is None or pd.isna(h):
                continue
            raja, syy = self.myyntiraja(p, sl)
            if h <= raja:
                salkku.odottavat.append(Toimeksianto(
                    t, "MYY", kpl=p.kpl, annettu=str(paiva.date()),
                    syy=f"{syy}: kurssi {h / p.huippu - 1:.1%} huipusta, {h / p.hankintahinta - 1:+.1%} ostohinnasta"))
                myytavana.add(t)

        # 2b) Hätämyynti: vakava kielteinen uutinen omistetusta yhtiöstä (skandaali, petos, tulosvaroitus...)
        sig = getattr(strategia, "sig", None)
        if sig is not None and getattr(strategia, "kayta_stop_lossia", True):
            for t, p in salkku.positiot.items():
                if t in myytavana:
                    continue
                u = sig.hatauutinen(t, paiva)
                if u is not None:
                    salkku.odottavat.append(Toimeksianto(
                        t, "MYY", kpl=p.kpl, annettu=str(paiva.date()),
                        syy=f"HÄTÄMYYNTI: vakava uutinen: {u.otsikko[:100]}"))
                    myytavana.add(t)
            # Perutaan toteutumattomat ostot osakkeista, joista on tullut kielteinen uutinen
            salkku.odottavat = [o for o in salkku.odottavat
                                if o.suunta != "OSTA" or not sig.kielteinen_uutinen(o.ticker, paiva)]

        # 3) Strategian päätös
        if strategia.onko_paatospaiva(paiva, salkku.viimeisin_paatos):
            salkku.viimeisin_paatos = str(paiva.date())
            huomiot += self._paata(salkku, strategia, paiva, paatos, myytavana)

        salkku.arvohistoria[str(paiva.date())] = round(salkku.arvo(paatos), 2)
        return huomiot

    @staticmethod
    def myyntiraja(p, sl: float) -> tuple[float, str]:
        """Liukuva myyntiraja: tavallinen stop-loss huipusta, mutta voiton kasvaessa raja nousee
        niin, että jo saavutettu voitto lukitaan:
          huippu +10 % ostohinnasta -> raja vähintään ostohinta (ei tappiota)
          huippu +20 % -> raja vähintään +10 %, huippu +30 % -> vähintään +20 % jne."""
        raja, syy = p.huippu * (1 - sl), "Stop-loss"
        nousu = p.huippu / p.hankintahinta - 1
        if nousu >= 0.10:
            askel = int(nousu * 10 + 1e-9)          # 1 = +10 %, 2 = +20 % ...
            lukko = p.hankintahinta * (1 + 0.10 * (askel - 1))
            if lukko > raja:
                raja, syy = lukko, f"Voitto lukittu (raja {0.10 * (askel - 1):+.0%} ostohinnasta)"
        return raja, syy

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
                "estetty": ehd.estetty or ehd.varovaisuus,
            })

        myydaan = omistukset - ehd.pidettavat
        for t in myydaan:
            salkku.odottavat.append(Toimeksianto(
                t, "MYY", kpl=salkku.positiot[t].kpl, annettu=pv, syy=ehd.perustelut.get(t, "")))

        pidetaan = omistukset & ehd.pidettavat
        odottavat_ostot = {o.ticker: o.summa for o in salkku.odottavat if o.suunta == "OSTA"}
        vapaat = n - len(pidetaan) - len(odottavat_ostot)
        if vapaat <= 0:
            return huomiot

        # Arvioidaan käytettävissä oleva raha myyntien jälkeen (päätöskursseilla)
        raha = salkku.kateinen
        for t in myydaan | myytavana:
            if t in salkku.positiot:
                s = salkku.positiot[t].kpl * float(paatos[t])
                raha += s - self.kulut.kulu(t, s)
        varaus = (self.riskit["kateisvara_prosentti"] / 100) * salkku.arvo(paatos)
        raha -= varaus + sum(odottavat_ostot.values())

        uudet = [t for t in ehd.ostettavat
                 if t not in pidetaan and t not in myytavana and t not in odottavat_ostot][:vapaat]
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
        lik = self._likviditeetti_nyt(paiva)
        arviot = {}
        for t in uudet:
            summa = osuus
            odotettu = None
            if hasattr(strategia, "odotettu") and getattr(strategia, "sig", None) is not None:
                # Skeptikko: viimeinen tarkistus ennen ostoa
                tuomio, syyt = skeptikko.arvioi(strategia, t, paiva, lik.get(t) if lik is not None else None)
                arviot[t] = {"tuomio": tuomio, "syyt": syyt}
                if tuomio == "hylkää":
                    huomiot.append(f"{pv}: skeptikko hylkäsi {t}: {'; '.join(syyt)}")
                    continue
                if tuomio == "puolikas":
                    summa = osuus / 2
                # Odotetun hyödyn pitää ylittää kaupan kokonaiskulut (osto + myynti + hintaero) selvästi
                odotettu = strategia.odotettu(t, paiva)
                ero = self.valittaja.hintaero(lik.get(t) if lik is not None else None)
                kulut = 2 * self.kulut.kulu(t, summa) / summa + 2 * ero
                arviot[t].update({"odotettu": round(odotettu or 0, 4), "kulut": round(kulut, 4)})
                if odotettu is None or odotettu < kulut + self.riskit.get("vaadittu_marginaali", 0.005):
                    huomiot.append(f"{pv}: ohitettiin {t} – odotettu tuotto {0 if odotettu is None else odotettu:.1%} "
                                   f"ei ylitä kuluja {kulut:.1%} + marginaali")
                    arviot[t]["tuomio"] = "hylkää (kulut)"
                    continue
            raja = self.kulut.pienin_jarkeva_kauppa(t, max_kulu)
            if summa < raja or summa < float(paatos[t]):
                huomiot.append(f"{pv}: ohitettiin {t} – {summa:.0f} € on liian pieni kauppa "
                               f"(kulut > {max_kulu} %, raja {raja:.0f} €)")
                continue
            syy = ehd.perustelut.get(t, "")
            if odotettu is not None:
                syy += f" | odotettu {odotettu:+.1%} vs. kulut {kulut:.1%}"
            if arviot.get(t, {}).get("tuomio") == "puolikas":
                syy += f" | skeptikko: puolikas ({'; '.join(arviot[t]['syyt'])})"
            # Rajahinta: enintään 1 % yli päätöskurssin -> ei jahdata uutisen aiheuttamaa hyppyä
            salkku.odottavat.append(Toimeksianto(
                t, "OSTA", summa=summa, annettu=pv, syy=syy,
                rajahinta=round(float(paatos[t]) * 1.01, 4), odotettu=round(odotettu or 0, 4)))
        if self.paatosloki is not None and arviot:
            self.paatosloki[-1]["skeptikko"] = arviot
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
