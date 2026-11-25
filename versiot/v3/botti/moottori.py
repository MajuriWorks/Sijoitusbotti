"""Moottori: yksi kauppapäivä yhdelle botille.

Sama koodi ajaa sekä historiatestin että päivittäisen leikkikaupan, joten
testissä nähty käytös on täsmälleen sitä, mitä botti tekee oikeasti.
"""
from __future__ import annotations

import pandas as pd

from .data import Paneeli
from .strategiat import Strategia
from . import tarkastaja
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

        # 0) Osingot ja osakesplitit omistuksille
        huomiot += self._yhtiotapahtumat(salkku, paneeli, paiva)

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
                # v3: kurssin 2 päivän muutos vahvistaa (tai kumoaa) uutisen vakavuuden
                i = paneeli.paatos.index.get_loc(paiva)
                muutos = (paatos.get(t) / paneeli.paatos[t].iloc[i - 2] - 1) if i >= 2 and t in paneeli.paatos else None
                u = sig.hatauutinen(t, paiva, kurssimuutos=muutos)
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

    def _yhtiotapahtumat(self, salkku, paneeli, paiva) -> list[str]:
        """Yahoo korjaa menneet kurssit taannehtivasti osinkojen ja splittien jälkeen. Verrataan
        ostopäivän kurssia nyt näkyvään: jos se on muuttunut, välissä on ollut osinko tai splitti.
          - splitti (kerroin < 0,6 tai > 1,6): osakemäärä ja hinnat muunnetaan, arvo ei muutu
          - osinko: osinko maksetaan käteisenä (ulkomaisista 15 % lähdevero), hinnat skaalataan,
            jotta kurssin osingonirtoamispudotus ei laukaise stop-lossia
        """
        out = []
        for t, p in salkku.positiot.items():
            if t not in paneeli.paatos.columns:
                continue
            try:
                nyt_viite = float(paneeli.paatos.at[pd.Timestamp(p.ostopaiva), t])
            except (KeyError, ValueError):
                continue
            if pd.isna(nyt_viite) or nyt_viite <= 0:
                continue
            if not p.viite_kurssi:
                p.viite_kurssi = nyt_viite
                continue
            f = nyt_viite / p.viite_kurssi
            if abs(f - 1) < 0.002:
                continue
            if f < 0.6 or f > 1.6:      # splitti tai käänteinen splitti
                suhde = 1 / f
                p.kpl = max(1, int(round(p.kpl * suhde)))
                out.append(f"{paiva.date()}: {t} osakesplitti {suhde:.2f}:1 – osakemäärä nyt {p.kpl}")
            elif f < 1:                 # osinko
                hinta_nyt = float(paneeli.paatos.at[paiva, t])
                osinko = (1 - f) * hinta_nyt / f * p.kpl
                vero = 0.0 if t.endswith(".HE") else 0.15
                salkku.kateinen += osinko * (1 - vero)
                out.append(f"{paiva.date()}: {t} osinko {osinko * (1 - vero):.2f} € käteiseen"
                           + (f" (lähdevero 15 %)" if vero else ""))
            p.hankintahinta *= f
            p.huippu *= f
            p.viite_kurssi = nyt_viite
        return out

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
                "teemat": (strategia.sig.teemat.aktiiviset(paiva)
                           if getattr(getattr(strategia, "sig", None), "teemat", None) is not None else {}),
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
                # Tarkastaja: viimeinen tarkistus ennen ostoa
                tuomio, syyt, kukin = tarkastaja.arvioi(strategia, t, paiva, lik.get(t) if lik is not None else None)
                arviot[t] = {"tuomio": tuomio, "syyt": syyt, "tarkastajat": kukin}
                if tuomio == "ohita":
                    huomiot.append(f"{pv}: tarkastajat ohittivat {t}: {'; '.join(syyt)}")
                    continue
                # v3: "pienennä" ei puolita kauppaa (pienessä salkussa kulut kaksinkertaistuisivat),
                # vaan vaatii odotetulta tuotolta 2 %-yksikköä enemmän
                lisamarginaali = 0.02 if tuomio == "pienennä" else 0.0
                # Odotetun hyödyn pitää ylittää kaupan kokonaiskulut (osto + myynti + hintaero) selvästi
                odotettu = strategia.odotettu(t, paiva)
                ero = self.valittaja.hintaero(lik.get(t) if lik is not None else None)
                kulut = 2 * self.kulut.kulu(t, summa) / summa + 2 * ero
                arviot[t].update({"odotettu": round(odotettu or 0, 4), "kulut": round(kulut, 4)})
                if odotettu is None or odotettu < kulut + self.riskit.get("vaadittu_marginaali", 0.005) + lisamarginaali:
                    huomiot.append(f"{pv}: ohitettiin {t} – odotettu tuotto {0 if odotettu is None else odotettu:.1%} "
                                   f"ei ylitä kuluja {kulut:.1%} + marginaali")
                    arviot[t]["tuomio"] = "ohita (kulut)"
                    continue
            raja = self.kulut.pienin_jarkeva_kauppa(t, max_kulu)
            if summa < raja or summa < float(paatos[t]):
                huomiot.append(f"{pv}: ohitettiin {t} – {summa:.0f} € on liian pieni kauppa "
                               f"(kulut > {max_kulu} %, raja {raja:.0f} €)")
                continue
            syy = ehd.perustelut.get(t, "")
            if odotettu is not None:
                syy += f" | odotettu {odotettu:+.1%} vs. kulut {kulut:.1%}"
            if arviot.get(t, {}).get("tuomio") == "pienennä":
                syy += f" | tarkastajat: varauksin, vaadittu +2 %-yks. lisätuotto ({'; '.join(arviot[t]['syyt'])})"
            # Rajahinta: enintään 1 % yli päätöskurssin -> ei jahdata uutisen aiheuttamaa hyppyä
            salkku.odottavat.append(Toimeksianto(
                t, "OSTA", summa=summa, annettu=pv, syy=syy,
                rajahinta=round(float(paatos[t]) * 1.01, 4), odotettu=round(odotettu or 0, 4)))
        if self.paatosloki is not None and arviot:
            self.paatosloki[-1]["tarkastus"] = arviot
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
