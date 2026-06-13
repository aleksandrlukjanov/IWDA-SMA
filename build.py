#!/usr/bin/env python3
"""
Atnaujina IWDA 8-men. SMA screeneri.

Ka daro:
  1. Parsisiunchia IWDA duomenis (pagrindinis saltinis: Yahoo; atsarginis: Stooq).
  2. Paima paskutinius 8 UZBAIGTUS menesiu uzdarymus (einamasis menuo praleidziamas).
  3. Paima naujausia dienos uzdaryma kaip dabartine kaina.
  4. Irasho shiuos skaichius i index.html DATA bloka ir issaugo i site/index.html.

Jei abu saltiniai neveikia -> skriptas baigiasi klaida (exit 1), GitHub Action'as nukris,
ir liks paskutine gera versija (blogu/tushchiu duomenu neperdeploys). Tau ateis laiskas.

Priklausomybe: pip install yfinance   (atsarginis Stooq variantas naudoja tik standartine biblioteka)
"""

import json
import re
import sys
import io
import csv
import datetime
import pathlib
import urllib.request

TICKER = "IWDA.AS"   # Yahoo: EUR, Euronext Amsterdam.  USD versija: "IWDA.L"
STOOQ = "iwda.nl"    # Stooq atitikmuo (Amsterdam)
SRC = pathlib.Path("index.html")
OUT_DIR = pathlib.Path("site")
ASSETS = ["preview.png"]


# ---------- saltiniai: kiekvienas grazina (monthly_pairs, cur, asof) ----------

def fetch_yahoo():
    import yfinance as yf
    t = yf.Ticker(TICKER)
    monthly = t.history(period="3y", interval="1mo", auto_adjust=False)["Close"].dropna()
    if monthly.empty:
        raise RuntimeError("Yahoo: tuschi menesiniai duomenys")
    pairs = [(f"{ts.year:04d}-{ts.month:02d}", round(float(v), 2)) for ts, v in monthly.items()]
    daily = t.history(period="7d", interval="1d", auto_adjust=False)["Close"].dropna()
    if daily.empty:
        raise RuntimeError("Yahoo: tuschi dienos duomenys")
    return pairs, round(float(daily.iloc[-1]), 2), daily.index[-1].date().isoformat()


def _stooq_csv(interval):
    url = f"https://stooq.com/q/d/l/?s={STOOQ}&i={interval}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        text = r.read().decode("utf-8", "replace")
    return list(csv.DictReader(io.StringIO(text)))


def fetch_stooq():
    rows_m = _stooq_csv("m")
    pairs = []
    for row in rows_m:
        d, c = row.get("Date"), row.get("Close")
        if not d or not c or c in ("N/D", ""):
            continue
        pairs.append((f"{d[:4]}-{d[5:7]}", round(float(c), 2)))
    if not pairs:
        raise RuntimeError("Stooq: tuschi menesiniai duomenys")
    rows_d = [r for r in _stooq_csv("d") if r.get("Close") not in (None, "", "N/D")]
    if not rows_d:
        raise RuntimeError("Stooq: tuschi dienos duomenys")
    last = rows_d[-1]
    return pairs, round(float(last["Close"]), 2), last["Date"]


# ---------- bendra logika ----------

def assemble(pairs, cur, asof):
    today = datetime.date.today()
    completed = [(lbl, v) for lbl, v in pairs
                 if (int(lbl[:4]), int(lbl[5:7])) != (today.year, today.month)]
    last8 = completed[-8:]
    if len(last8) < 8:
        raise RuntimeError(f"Rasta tik {len(last8)} uzbaigtu menesiu (reikia 8)")
    return {"asof": asof, "cur": cur, "closes": [[l, v] for l, v in last8]}


def get_data():
    errors = []
    for name, fn in (("Yahoo", fetch_yahoo), ("Stooq", fetch_stooq)):
        try:
            pairs, cur, asof = fn()
            data = assemble(pairs, cur, asof)
            print(f"[saltinis: {name}]")
            return data
        except Exception as e:  # noqa: BLE001
            errors.append(f"{name}: {e}")
    raise RuntimeError("Visi saltiniai neveikia -> " + " | ".join(errors))


def main():
    data = get_data()
    html = SRC.read_text(encoding="utf-8")
    block = ("/* DATA-START */\n  const DATA = "
             + json.dumps(data, ensure_ascii=False, indent=2).replace("\n", "\n  ")
             + ";\n  /* DATA-END */")
    new_html, n = re.subn(r"/\* DATA-START \*/.*?/\* DATA-END \*/",
                          lambda _m: block, html, flags=re.S)
    if n != 1:
        raise RuntimeError(f"DATA blokas index.html faile rastas {n} kartu (turi buti 1)")

    OUT_DIR.mkdir(exist_ok=True)
    (OUT_DIR / "index.html").write_text(new_html, encoding="utf-8")
    for asset in ASSETS:
        p = pathlib.Path(asset)
        if p.exists():
            (OUT_DIR / asset).write_bytes(p.read_bytes())

    sma = sum(v for _, v in data["closes"]) / len(data["closes"])
    signal = "HOLD / BUY" if data["cur"] >= sma else "SELL CORE / DCA"
    print(f"OK | {data['asof']} | kaina {data['cur']:.2f} | SMA {sma:.2f} | {signal}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # noqa: BLE001
        print("BUILD FAILED:", e, file=sys.stderr)
        sys.exit(1)
