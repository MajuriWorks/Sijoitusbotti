"""Tunnusluvut ja HTML-raportti."""
from __future__ import annotations

import html
import json
import math
from datetime import datetime

import numpy as np
import pandas as pd

from .data import Paneeli
from .valittaja import Kulumalli, Salkku

VARIT = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4"]          # vaalea tila
VARIT_TUMMA = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181"]    # tumma tila


# ---------------------------------------------------------------- luvut
def markkinasarja(paneeli: Paneeli, alku, alkupaaoma: float) -> pd.Series:
    """Vertailukohta: Helsingin pörssin seuratut osakkeet tasapainoisesti, ilman kuluja."""
    hel = [t for t in paneeli.paatos.columns if t.endswith(".HE")] or list(paneeli.paatos.columns)
    c = paneeli.paatos.loc[alku:, hel]
    r = c.pct_change().mean(axis=1).fillna(0)
    return alkupaaoma * (1 + r).cumprod()


def tunnusluvut(sarja: pd.Series, alkupaaoma: float, salkku: Salkku | None = None) -> dict:
    sarja = sarja.dropna()
    if len(sarja) < 2:
        return {}
    vuodet = max((sarja.index[-1] - sarja.index[0]).days / 365.25, 1 / 365)
    loppu = float(sarja.iloc[-1])
    tuotto = loppu / alkupaaoma - 1
    d = {
        "Loppuarvo": f"{loppu:,.0f} €".replace(",", " "),
        "Tuotto": f"{tuotto:+.1%}",
        "Vuosituotto": f"{(loppu / alkupaaoma) ** (1 / vuodet) - 1:+.1%}" if vuodet >= 1 else "–",
        "Suurin pudotus": f"{(sarja / sarja.cummax() - 1).min():.1%}",
    }
    if salkku is not None:
        myynnit = [k for k in salkku.kaupat if k.suunta == "MYY" and k.voitto is not None]
        voittavat = sum(1 for k in myynnit if k.voitto > 0)
        d["Kauppoja"] = str(len(salkku.kaupat))
        d["Kulut yhteensä"] = f"{salkku.kulut_yht:,.0f} €".replace(",", " ")
        d["Voitollisia myyntejä"] = f"{voittavat}/{len(myynnit)}" if myynnit else "–"
        voitot = [k.voitto for k in myynnit if k.voitto > 0]
        tappiot = [k.voitto for k in myynnit if k.voitto <= 0]
        d["Keskim. voitto / kauppa"] = f"{np.mean(voitot):+.0f} €" if voitot else "–"
        d["Keskim. tappio / kauppa"] = f"{np.mean(tappiot):+.0f} €" if tappiot else "–"
        d["Suurin tappio"] = f"{min(tappiot):+.0f} €" if tappiot else "–"
        ennusteet = [k for k in myynnit if k.odotettu is not None and k.toteutunut is not None]
        if ennusteet:
            oikein = sum(1 for k in ennusteet if (k.toteutunut > 0) == (k.odotettu > 0))
            d["Ennuste vs. toteutunut"] = (f"{np.mean([k.odotettu for k in ennusteet]):+.1%} / "
                                           f"{np.mean([k.toteutunut for k in ennusteet]):+.1%}")
            d["Ennusteen suunta oikein"] = f"{oikein}/{len(ennusteet)}"
        else:
            d["Ennuste vs. toteutunut"] = "–"
            d["Ennusteen suunta oikein"] = "–"
        d["Keskim. pitoaika"] = (f"{np.mean([k.pitoaika_pv for k in myynnit]):.0f} pv" if myynnit else "–")
    return d


def vuosituotot(sarjat: dict[str, pd.Series]) -> pd.DataFrame:
    out = {}
    for nimi, s in sarjat.items():
        v = s.groupby(s.index.year).last()
        alku = s.iloc[0]
        out[nimi] = v.pct_change().fillna(v.iloc[0] / alku - 1)
    return pd.DataFrame(out)


def jaksotuotot(sarjat: dict[str, pd.Series], saanto: str, alkupaaoma: float) -> pd.DataFrame:
    """Tuotto jaksoittain (viikko 'W-FRI', kuukausi 'ME', vuosi 'YE'), uusin ensin."""
    df = pd.DataFrame(sarjat).ffill()
    loput = df.resample(saanto).last().dropna(how="all")
    edell = loput.shift(1)
    edell.iloc[0] = alkupaaoma
    tuotot = loput / edell - 1
    if saanto.startswith("W"):
        tuotot.index = [f"vk {d.isocalendar()[1]}/{d.year}" for d in tuotot.index]
    elif saanto == "ME":
        tuotot.index = [f"{d.month}/{d.year}" for d in tuotot.index]
    else:
        tuotot.index = [str(d.year) for d in tuotot.index]
    return tuotot.iloc[::-1]


def _jaksohtml(sarjat, alkupaaoma) -> str:
    osat = ['<div class="jaksot">']
    for otsikko, saanto, n in (("Viikoittain", "W-FRI", 8), ("Kuukausittain", "ME", 12), ("Vuosittain", "YE", 10)):
        t = jaksotuotot(sarjat, saanto, alkupaaoma).head(n)
        rivit = [[str(i)] + [f"{x:+.1%}" if pd.notna(x) else "–" for x in t.loc[i]] for i in t.index]
        osat.append(f"<div><h3>{otsikko}</h3>" + _taulukko(rivit, [""] + list(t.columns), "luvut pieni") + "</div>")
    osat.append("</div>")
    return "".join(osat)


# ---------------------------------------------------------------- HTML
def _svg_kaavio(sarjat: dict[str, pd.Series]) -> str:
    W, H, ml, mr, mt, mb = 900, 320, 56, 190, 16, 28
    df = pd.DataFrame(sarjat).ffill().dropna()
    if len(df) > 600:  # harvennetaan piirtoa varten
        df = df.iloc[np.linspace(0, len(df) - 1, 600).astype(int)]
    ymin, ymax = float(df.min().min()), float(df.max().max())
    pad = (ymax - ymin) * 0.06 or 1
    ymin, ymax = ymin - pad, ymax + pad
    x = lambda i: ml + (W - ml - mr) * i / max(len(df) - 1, 1)
    y = lambda v: mt + (H - mt - mb) * (1 - (v - ymin) / (ymax - ymin))

    osat = [f'<svg viewBox="0 0 {W} {H}" class="kaavio" role="img" aria-label="Salkkujen arvo ajan yli">']
    # ruudukko
    askel = 10 ** math.floor(math.log10((ymax - ymin) / 4))
    for k in (1, 2, 5, 10):
        if (ymax - ymin) / (askel * k) <= 6:
            askel *= k
            break
    v = math.ceil(ymin / askel) * askel
    while v <= ymax:
        osat.append(f'<line x1="{ml}" x2="{W - mr}" y1="{y(v):.1f}" y2="{y(v):.1f}" class="grid"/>'
                    f'<text x="{ml - 8}" y="{y(v) + 4:.1f}" class="akseli" text-anchor="end">{v:,.0f} €</text>'
                    .replace(",", " "))
        v += askel
    # x-akselin vuodet / kuukaudet
    paivat = df.index
    merkit = sorted({(p.year, p.month if (paivat[-1] - paivat[0]).days < 500 else 1) for p in paivat})
    for (yy, mm) in merkit[:: max(1, len(merkit) // 8)]:
        i = paivat.searchsorted(pd.Timestamp(yy, mm, 1))
        if 0 < i < len(paivat):
            lbl = str(yy) if (paivat[-1] - paivat[0]).days >= 500 else f"{mm}/{yy % 100}"
            osat.append(f'<text x="{x(i):.1f}" y="{H - 8}" class="akseli" text-anchor="middle">{lbl}</text>')
    osat.append(f'<line x1="{ml}" x2="{W - mr}" y1="{H - mb}" y2="{H - mb}" class="pohja"/>')
    # viivat + suorat nimilaput
    loput = []
    for j, (nimi, s) in enumerate(df.items()):
        pts = " ".join(f"{x(i):.1f},{y(val):.1f}" for i, val in enumerate(s.values))
        osat.append(f'<polyline points="{pts}" class="sarja s{j}" fill="none"/>')
        loput.append([y(s.values[-1]), nimi, j, s.values[-1]])
    loput.sort()
    for k in range(1, len(loput)):  # estetään päällekkäiset nimilaput
        loput[k][0] = max(loput[k][0], loput[k - 1][0] + 16)
    for yy, nimi, j, val in loput:
        osat.append(f'<text x="{W - mr + 8}" y="{yy + 4:.1f}" class="nimi">'
                    f'<tspan class="t{j}">●</tspan> {html.escape(nimi)} {val:,.0f} €</text>'.replace(",", " "))
    osat.append(f'<line class="risti" x1="0" x2="0" y1="{mt}" y2="{H - mb}" visibility="hidden"/>')
    osat.append(f'<rect class="osuma" x="{ml}" y="{mt}" width="{W - ml - mr}" height="{H - mt - mb}" fill="transparent"/>')
    osat.append("</svg>")
    data = {"paivat": [p.strftime("%d.%m.%Y") for p in df.index],
            "sarjat": {k: [round(float(v), 0) for v in s.values] for k, s in df.items()},
            "ml": ml, "lev": W - ml - mr, "W": W}
    return "".join(osat) + f"<script>const KD={json.dumps(data)};</script>"


def _tunnelmasana(x: float) -> str:
    return "myönteinen" if x > 0.1 else ("kielteinen" if x < -0.1 else "neutraali")


def _tietopohjahtml(sig, paiva, paatokset, lahdetila) -> str:
    osat = []
    ml, mp = float(sig.maailma_lyhyt.loc[paiva]), float(sig.maailma_pitka.loc[paiva])
    yht = lahdetila.get("_yhteenveto", {})
    osat.append("<h2>Tietopohja tänään</h2>")
    osat.append(f'<p class="selite">Maailman uutistunnelma: lyhyellä aikavälillä <b>{_tunnelmasana(ml)}</b> ({ml:+.2f}), '
                f'viikkojen aikavälillä <b>{_tunnelmasana(mp)}</b> ({mp:+.2f}). '
                f'Uusia uutisia ja viestejä tällä ajolla {yht.get("uusia", 0)} kpl, tulkinta: {yht.get("tulkinta", "–")}.</p>')
    rivit = []
    for u in sig.paivan_uutiset(paiva, 15):
        tt = ", ".join(u.tickerit) or "markkina"
        otsikko = html.escape(u.otsikko[:140])
        if u.linkki:
            otsikko = f'<a href="{html.escape(u.linkki)}" target="_blank" rel="noopener">{otsikko}</a>'
        luettu = "teksti" if str(u.lisatieto.get("teksti", "")).startswith("luettu") else "otsikko"
        if u.lisatieto.get("suunta"):
            luettu = f"teksti: {u.lisatieto['suunta']}"
        rivit.append([html.escape(tt), u.tyyppi, f"{u.tunnelma:+.2f}", f"{u.paino:.1f}", otsikko,
                      html.escape(u.lisatieto.get("julkaisija") or u.lahde), luettu])
    if rivit:
        osat.append("<h3>Painavimmat uutiset (2 pv)</h3>" + _taulukko(
            rivit, ["Kohde", "Tyyppi", "Tunnelma", "Paino", "Otsikko", "Lähde", "Luettu"], "pieni"))
    viimeiset = [p for p in paatokset if p["paiva"] == str(paiva.date())]
    if viimeiset:
        rivit = []
        for p in viimeiset:
            ehd = "<br>".join(f"<b>{html.escape(e['osake'])}</b> {html.escape(e['perustelu'])}" for e in p["ehdokkaat"][:3])
            myy = "<br>".join(f"<b>{html.escape(t)}</b> {html.escape(s)}" for t, s in p.get("myydaan", {}).items())
            rivit.append([html.escape(p["botti"]), html.escape(", ".join(p["pidetaan"]) or "–"),
                          myy or "–", ((f"<i>{html.escape(p['estetty'])}</i><br>" if p.get("estetty") else "")
                                       + (ehd or "–"))])
        osat.append("<h3>Bottien päätökset tänään</h3>" + _taulukko(
            rivit, ["Botti / osa", "Pidetään", "Myydään", "Parhaat ostoehdokkaat"], "pieni"))
    lahteet = {k: v for k, v in lahdetila.items() if not k.startswith("_")}
    if lahteet:
        rivit = [[k, str(v["ok"]), str(v["virheet"]), html.escape(v.get("viimeisin_virhe", ""))] for k, v in lahteet.items()]
        osat.append("<h3>Tietolähteiden tila</h3>" + _taulukko(rivit, ["Lähde", "Haettuja", "Virheitä", "Viimeisin virhe"], "pieni"))
    return "".join(osat)


def _taulukko(rivit: list[list[str]], otsikot: list[str], luokka="") -> str:
    th = "".join(f"<th>{html.escape(o)}</th>" for o in otsikot)
    tr = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rivit)
    return f'<table class="{luokka}"><thead><tr>{th}</tr></thead><tbody>{tr}</tbody></table>'


def html_raportti(otsikko: str, tila: str, botit: list[dict], vertailu: pd.Series,
                  paneeli: Paneeli, kulut: Kulumalli, alkupaaoma: float, huomiot: list[str],
                  sig=None, lahdetila: dict | None = None, paatokset: list[dict] | None = None) -> str:
    viimeisin = paneeli.paatos.index[-1]
    hinnat = paneeli.paatos.iloc[-1]
    sarjat = {b["nimi"].capitalize(): b["sarja"] for b in botit}
    sarjat["Helsinki"] = vertailu
    osat = []

    # -- toimeksiannot (tärkein osa leikkikaupassa)
    if tila == "leikkikauppa":
        rivit = []
        for b in botit:
            for o in b["salkku"].odottavat:
                h = float(hinnat.get(o.ticker, np.nan))
                if o.suunta == "OSTA":
                    raja = o.rajahinta or h * 1.01
                    kpl = int(o.summa // raja) if raja > 0 else 0
                else:
                    kpl = o.kpl
                    raja = h * 0.99
                kulu = kulut.kulu(o.ticker, kpl * h) if kpl else 0
                luokka = "osta" if o.suunta == "OSTA" else "myy"
                rivit.append([b["nimi"].capitalize(), f'<b class="{luokka}">{o.suunta}</b>', f"<b>{o.ticker}</b>",
                              f"{kpl} kpl", f"{raja:.2f} €", f"{kpl * h:.0f} €", f"{kulu:.2f} €", html.escape(o.syy)])
        osat.append("<h2>Toimeksiannot seuraavalle kauppapäivälle</h2>")
        if rivit:
            osat.append('<p class="selite">Leikkikaupassa botti toteuttaa nämä itse huomisen avauskurssiin. '
                        'Ostot ovat rajahintatoimeksiantoja (enintään 1 % yli päätöskurssin, voimassa 3 päivää), '
                        'myynnit tehdään markkinahintaan. Simulaatio huomioi välityspalkkion, valuutanvaihdon ja '
                        'osto- ja myyntihinnan eron. Oikealla rahalla tee samat toimeksiannot Nordnetissa.</p>')
            osat.append(_taulukko(rivit, ["Botti", "Suunta", "Osake", "Määrä", "Rajahinta n.", "Summa n.",
                                          "Kulu n.", "Perustelu"], "toimeksiannot"))
        else:
            osat.append('<p class="tyhja">Ei kauppoja – botit pitävät nykyiset omistuksensa.</p>')

    # -- tietopohja: maailma, uutiset, perustelut
    if tila == "leikkikauppa" and sig is not None:
        osat.append(_tietopohjahtml(sig, viimeisin, paatokset or [], lahdetila or {}))

    # -- kaavio + tunnusluvut
    osat.append("<h2>Salkkujen arvo</h2>")
    osat.append('<div class="kaaviokehys">' + _svg_kaavio(sarjat) + '<div class="vihje" hidden></div></div>')
    luvut = {b["nimi"].capitalize(): tunnusluvut(b["sarja"], alkupaaoma, b["salkku"]) for b in botit}
    luvut["Helsinki"] = tunnusluvut(vertailu, alkupaaoma)
    avaimet = list(next(iter(luvut.values())).keys())
    rivit = [[k] + [luvut[n].get(k, "–") for n in luvut] for k in avaimet]
    osat.append(_taulukko(rivit, [""] + list(luvut), "luvut"))
    osat.append('<p class="selite">Helsinki = kaikki seuratut Helsingin osakkeet tasapainoisesti ilman kuluja. '
                'Indeksi = maailmanindeksi ostettuna ja pidettynä, kuluineen. Aktiivisen botin pitää voittaa '
                'molemmat kulujen jälkeen, muuten oikeaa rahaa ei kannata antaa sille.</p>')

    if tila == "leikkikauppa":
        osat.append("<h2>Tuotot jaksoittain</h2>" + _jaksohtml(sarjat, alkupaaoma))

    if tila == "historiatesti":
        vt = vuosituotot(sarjat)
        rivit = [[str(v)] + [f"{x:+.1%}" for x in vt.loc[v]] for v in vt.index]
        osat.append("<h2>Tuotto vuosittain</h2>" + _taulukko(rivit, ["Vuosi"] + list(vt.columns), "luvut"))

    # -- botit tarkemmin
    for b in botit:
        s: Salkku = b["salkku"]
        osat.append(f'<h2>{b["nimi"].capitalize()}</h2><p class="selite">{html.escape(b["kuvaus"])}</p>')
        rivit = []
        for t, p in s.positiot.items():
            h = float(hinnat.get(t, p.hankintahinta))
            rivit.append([f"<b>{t}</b>", str(p.kpl), f"{p.hankintahinta:.2f} €", f"{h:.2f} €",
                          f"{p.kpl * h:.0f} €", f"{h / p.hankintahinta - 1:+.1%}", p.ostopaiva])
        rivit.append(["Käteinen", "", "", "", f"{s.kateinen:.0f} €", "", ""])
        osat.append(_taulukko(rivit, ["Omistus", "Kpl", "Hankinta", "Nyt", "Arvo", "Muutos", "Ostettu"]))
        kaupat = s.kaupat[-12:][::-1]
        if kaupat:
            rivit = [[k.paiva, k.suunta, k.ticker, str(k.kpl), f"{k.hinta:.2f} €", f"{k.kulu:.2f} €",
                      (f"{k.voitto:+.0f} €" if k.voitto is not None else ""), html.escape(k.syy)] for k in kaupat]
            osat.append("<h3>Viimeisimmät kaupat</h3>" + _taulukko(
                rivit, ["Päivä", "Suunta", "Osake", "Kpl", "Hinta", "Kulu", "Tulos", "Syy"], "pieni"))

    if paneeli.puuttuvat:
        osat.append(f"<h3>Tunnukset ilman kursseja ({len(paneeli.puuttuvat)})</h3><p class='selite'>"
                    + html.escape(", ".join(paneeli.puuttuvat))
                    + " – nämä ohitetaan. Tarkista tai poista ne tiedostosta config.yaml.</p>")
    if huomiot:
        nayta = huomiot[-15:]
        osat.append(f"<h3>Huomiot ({len(huomiot)} kpl, viimeisimmät)</h3><ul class='pieni'>" +
                    "".join(f"<li>{html.escape(h)}</li>" for h in nayta) + "</ul>")

    luotu = datetime.now().strftime("%d.%m.%Y %H:%M")
    return SIVU.format(otsikko=html.escape(otsikko), paiva=viimeisin.strftime("%d.%m.%Y"),
                       luotu=luotu, sisalto="\n".join(osat), tila=tila,
                       linkit=(' · <a href="arkisto/">Raporttiarkisto</a> · <a href="historiatesti.html">Historiatesti</a>'
                               if tila == "leikkikauppa" else ""),
                       v=VARIT, vt=VARIT_TUMMA)


SIVU = """<!DOCTYPE html>
<html lang="fi"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{otsikko}</title>
<style>
:root{{--pinta:#fcfcfb;--taso:#f9f9f7;--teksti:#0b0b0b;--teksti2:#52514e;--himmea:#898781;--grid:#e1e0d9;--pohja:#c3c2b7;
--s0:{v[0]};--s1:{v[1]};--s2:{v[2]};--s3:{v[3]};--s4:{v[4]};--hyva:#006300;--paha:#c02c2c;--reuna:rgba(11,11,11,.10)}}
@media (prefers-color-scheme:dark){{:root{{--pinta:#1a1a19;--taso:#0d0d0d;--teksti:#f0efec;--teksti2:#c3c2b7;--grid:#2c2c2a;--pohja:#383835;
--s0:{vt[0]};--s1:{vt[1]};--s2:{vt[2]};--s3:{vt[3]};--s4:{vt[4]};--hyva:#0ca30c;--paha:#e66767;--reuna:rgba(255,255,255,.10)}}}}
body{{font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif;background:var(--taso);color:var(--teksti);margin:0}}
main{{max-width:1080px;margin:0 auto;padding:28px 20px 60px}}
h1{{font-size:24px;margin:0}} h2{{font-size:18px;margin:34px 0 8px}} h3{{font-size:15px;margin:20px 0 6px}}
.meta{{color:var(--teksti2);margin:4px 0 0}} .selite{{color:var(--teksti2);margin:4px 0 10px;max-width:760px}}
.tila{{display:inline-block;padding:2px 8px;border-radius:4px;border:1px solid var(--reuna);font-size:12px;color:var(--teksti2);margin-left:8px;vertical-align:middle}}
table{{border-collapse:collapse;background:var(--pinta);border:1px solid var(--reuna);border-radius:6px;width:100%;font-variant-numeric:tabular-nums}}
th,td{{padding:6px 10px;text-align:left;border-bottom:1px solid var(--grid);vertical-align:top}}
th{{font-weight:600;color:var(--teksti2);font-size:13px}} table.pieni{{font-size:13px}} ul.pieni{{font-size:13px;color:var(--teksti2)}}
table.luvut td:not(:first-child),table.luvut th:not(:first-child){{text-align:right}}
.osta{{color:var(--hyva)}} .myy{{color:var(--paha)}} .tyhja{{background:var(--pinta);border:1px solid var(--reuna);border-radius:6px;padding:14px}}
.kaaviokehys{{position:relative;background:var(--pinta);border:1px solid var(--reuna);border-radius:6px;padding:10px;margin-bottom:12px}}
.kaavio{{width:100%;height:auto;display:block}}
.grid{{stroke:var(--grid);stroke-width:1}} .pohja{{stroke:var(--pohja);stroke-width:1}}
.akseli{{fill:var(--himmea);font-size:11px}} .nimi{{fill:var(--teksti);font-size:12px}}
.sarja{{stroke-width:2;stroke-linejoin:round}} .s0,.t0{{stroke:var(--s0);fill:var(--s0)}} .s1,.t1{{stroke:var(--s1);fill:var(--s1)}}
.s2,.t2{{stroke:var(--s2);fill:var(--s2)}} .s3,.t3{{stroke:var(--s3);fill:var(--s3)}} .s4,.t4{{stroke:var(--s4);fill:var(--s4)}} polyline.sarja{{fill:none}}
.risti{{stroke:var(--pohja);stroke-width:1}}
.vihje{{position:absolute;pointer-events:none;background:var(--pinta);border:1px solid var(--reuna);border-radius:6px;padding:6px 10px;font-size:12px;box-shadow:0 2px 8px rgba(0,0,0,.12);white-space:nowrap}}
.vihje b{{display:block;margin-bottom:2px}}
.jaksot{{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:14px}} .jaksot h3{{margin-top:4px}}
a{{color:var(--s0)}}
footer{{margin-top:40px;color:var(--himmea);font-size:12px}}
</style></head><body><main>
<h1>{otsikko}<span class="tila">{tila}</span></h1>
<p class="meta">Kurssit {paiva} asti · luotu {luotu}{linkit}</p>
{sisalto}
<footer>Leikkirahasimulaatio. Ei sijoitusneuvontaa. Menneisyyden tuotto ei takaa tulevaa.</footer>
</main>
<script>
(function(){{
 const svg=document.querySelector('.kaavio'); if(!svg||typeof KD==='undefined')return;
 const vihje=document.querySelector('.vihje'), risti=svg.querySelector('.risti'), osuma=svg.querySelector('.osuma');
 const n=KD.paivat.length, nimet=Object.keys(KD.sarjat);
 osuma.addEventListener('mousemove',e=>{{
   const r=svg.getBoundingClientRect(), sx=KD.W/r.width, x=(e.clientX-r.left)*sx;
   const i=Math.max(0,Math.min(n-1,Math.round((x-KD.ml)/KD.lev*(n-1))));
   const px=KD.ml+KD.lev*i/(n-1); risti.setAttribute('x1',px); risti.setAttribute('x2',px); risti.setAttribute('visibility','visible');
   vihje.innerHTML='<b>'+KD.paivat[i]+'</b>'+nimet.map((k,j)=>'<span class="t'+j+'" style="color:var(--s'+j+')">●</span> '+k+': '+KD.sarjat[k][i].toLocaleString('fi-FI')+' €').join('<br>');
   vihje.hidden=false; const vx=(px/sx)+16; vihje.style.left=Math.min(vx, r.width-vihje.offsetWidth-4)+'px'; vihje.style.top='20px';
 }});
 osuma.addEventListener('mouseleave',()=>{{vihje.hidden=true; risti.setAttribute('visibility','hidden');}});
}})();
</script></body></html>"""
