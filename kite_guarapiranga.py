#!/usr/bin/env python3
"""
Guarapiranga kite wind alert (image + WhatsApp link version).

What it does, in order:
  1. Pulls today's hourly wind forecast for the Guarapiranga reservoir from Open-Meteo.
  2. Decides go / no-go for kiting.
  3. Renders a Windguru-style PNG (wind, gusts, direction) into forecast/<date>.png.
  4. Writes the WhatsApp message (verdict + link to the image) to out_message.txt.

Sending is done by the GitHub Actions workflow AFTER the image is pushed, so the
link is already live when you tap it. To test locally, run the script and then open
forecast/<date>.png and read out_message.txt.

Data: Open-Meteo (free, no API key). https://open-meteo.com
"""

import os
import json
import math
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

# ------------------------------- CONFIG -------------------------------
LAT = -23.71              # Guarapiranga reservoir (kite area). Move to your launch spot.
LON = -46.73
TIMEZONE = "America/Sao_Paulo"

MIN_KNOTS = 12            # minimum sustained wind to go out (12-14 kn, big kite, lighter)
MIN_GOOD_HOURS = 2        # how many hours in the window must hit MIN_KNOTS to say GO
WINDOW_START = 11         # sailable window start hour (thermal wind builds in the afternoon)
WINDOW_END = 18           # sailable window end hour (inclusive)
DAY_OFFSET = 0            # 0 = today, 1 = tomorrow

CHART_START = 8           # first hour drawn on the chart
CHART_END = 21            # last hour drawn on the chart
# ----------------------------------------------------------------------


def fetch_forecast():
    params = {
        "latitude": LAT,
        "longitude": LON,
        "hourly": "wind_speed_10m,wind_gusts_10m,wind_direction_10m",
        "wind_speed_unit": "kn",
        "timezone": TIMEZONE,
        "forecast_days": 2,
    }
    url = "https://api.open-meteo.com/v1/forecast?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "kite-guarapiranga/2.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def target_date():
    now = datetime.now(ZoneInfo(TIMEZONE))
    return (now + timedelta(days=DAY_OFFSET)).strftime("%Y-%m-%d")


def rows_for_day(data, date, h0, h1):
    h = data["hourly"]
    out = []
    for i, t in enumerate(h["time"]):
        d, clock = t.split("T")
        hh = int(clock.split(":")[0])
        if d == date and h0 <= hh <= h1 and h["wind_speed_10m"][i] is not None:
            out.append((hh, h["wind_speed_10m"][i], h["wind_gusts_10m"][i], h["wind_direction_10m"][i]))
    return out


def deg_to_compass(deg):
    if deg is None:
        return "?"
    dirs = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
            "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
    return dirs[int((deg / 22.5) + 0.5) % 16]


def knots_color(k):
    if k < 6:   return (0.88, 0.94, 1.0)
    if k < 9:   return (0.74, 0.92, 0.80)
    if k < 12:  return (0.45, 0.84, 0.48)
    if k < 16:  return (0.62, 0.85, 0.30)
    if k < 20:  return (0.97, 0.86, 0.22)
    if k < 25:  return (0.97, 0.64, 0.22)
    if k < 30:  return (0.93, 0.38, 0.22)
    return (0.82, 0.16, 0.16)


def analyze(rows):
    window = [r for r in rows if WINDOW_START <= r[0] <= WINDOW_END]
    if not window:
        return None
    good = [r for r in window if r[1] >= MIN_KNOTS]
    peak = max(window, key=lambda r: r[1])
    gusts = [r[2] for r in window if r[2] is not None]
    return {
        "go": len(good) >= MIN_GOOD_HOURS,
        "good_hours": [r[0] for r in good],
        "peak_knots": round(peak[1]),
        "peak_hour": peak[0],
        "peak_gust": round(max(gusts)) if gusts else round(peak[1]),
        "peak_dir": deg_to_compass(peak[3]),
    }


def render_png(rows, date, path):
    hours = [r[0] for r in rows]
    wind = [round(r[1]) for r in rows]
    gust = [round(r[2]) if r[2] is not None else round(r[1]) for r in rows]
    drc = [r[3] for r in rows]
    n = len(rows)

    fig_w = max(11, n * 0.64)
    fig, ax = plt.subplots(figsize=(fig_w, 3.7), dpi=170)
    ax.set_xlim(-2.6, n + 0.2)
    ax.set_ylim(0, 4.5)
    ax.axis("off")

    def row(y, vals):
        for i, v in enumerate(vals):
            ax.add_patch(Rectangle((i, y), 1, 1, facecolor=knots_color(v),
                                   edgecolor="white", linewidth=1.3))
            ax.text(i + 0.5, y + 0.5, str(v), ha="center", va="center", fontsize=11, color="#222")

    for i, hh in enumerate(hours):
        ax.add_patch(Rectangle((i, 3), 1, 1, facecolor="#f2f2f2", edgecolor="white", linewidth=1.3))
        ax.text(i + 0.5, 3.5, "{:02d}h".format(hh), ha="center", va="center", fontsize=9, color="#333")

    row(2, wind)
    for i, v in enumerate(wind):
        if v >= MIN_KNOTS:
            ax.add_patch(Rectangle((i, 2), 1, 1, fill=False, edgecolor="#0a7d2c", linewidth=2.4))
    row(1, gust)

    for i, d in enumerate(drc):
        ax.add_patch(Rectangle((i, 0), 1, 1, facecolor="white", edgecolor="#eaeaea", linewidth=1.0))
        if d is not None:
            rad = math.radians(d)
            u, v = -math.sin(rad), -math.cos(rad)
            ax.annotate("", xy=(i + 0.5 + u * 0.30, 0.5 + v * 0.30),
                        xytext=(i + 0.5 - u * 0.30, 0.5 - v * 0.30),
                        arrowprops=dict(arrowstyle="-|>", color="#555", lw=1.7))

    for y, lab in [(2.5, "Vento (nós)"), (1.5, "Rajada (nós)"), (0.5, "Direção")]:
        ax.text(-0.2, y, lab, ha="right", va="center", fontsize=9.5, color="#111")

    fig.suptitle("Guarapiranga: previsão de vento  -  {}".format(date),
                 x=0.5, y=0.99, fontsize=14, fontweight="bold")
    fig.text(0.5, 0.015,
             "Borda verde = {} nós ou mais (dá pra velejar). Fonte: Open-Meteo.".format(MIN_KNOTS),
             ha="center", fontsize=8, color="#666")

    plt.tight_layout(rect=[0, 0.04, 1, 0.96])
    os.makedirs(os.path.dirname(path), exist_ok=True)
    plt.savefig(path, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def build_message(a, date, image_url):
    if a is None:
        msg = "Guarapiranga {}: sem dados de vento para o dia.".format(date)
    elif a["go"]:
        hours = ", ".join("{}h".format(x) for x in a["good_hours"])
        msg = ("Guarapiranga {}\n"
               "Vai dar pra velejar.\n"
               "Pico ~{} nós às {}h, rajada até {} nós, direção {}.\n"
               "Janela boa: {}.").format(date, a["peak_knots"], a["peak_hour"],
                                         a["peak_gust"], a["peak_dir"], hours)
    else:
        msg = ("Guarapiranga {}\n"
               "Provavelmente não dá hoje.\n"
               "Pico previsto ~{} nós às {}h (seu mínimo: {} nós).").format(
                   date, a["peak_knots"], a["peak_hour"], MIN_KNOTS)
    if image_url:
        msg += "\nGráfico: {}".format(image_url)
    return msg


def main():
    date = target_date()
    data = fetch_forecast()
    rows = rows_for_day(data, date, CHART_START, CHART_END)
    result = analyze(rows)

    image_url = ""
    if rows:
        image_path = "forecast/{}.png".format(date)
        render_png(rows, date, image_path)
        repo = os.environ.get("GITHUB_REPOSITORY", "")
        branch = os.environ.get("GITHUB_REF_NAME", "main")
        if repo:
            image_url = "https://raw.githubusercontent.com/{}/{}/{}".format(repo, branch, image_path)

    message = build_message(result, date, image_url)
    with open("out_message.txt", "w", encoding="utf-8") as f:
        f.write(message)
    print(message)


if __name__ == "__main__":
    main()
