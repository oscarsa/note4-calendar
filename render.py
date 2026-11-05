"""Render a Google Calendar + weather dashboard for the Note4 e-paper (400x300, 1bpp).

Outputs a PNG preview and a ZEP1 page (32-byte header + 15000 bytes, 1 = white)
that Note4 Open Platform downloads as its remote sleep cover.

Environment:
  ICAL_URLS   one or more secret iCal addresses, separated by spaces/newlines
  LAT, LON    weather location (Open-Meteo, no key needed)
  CITY        label shown under the weather
  TZ_NAME     default Europe/Madrid
  DEMO=1      use sample events instead of fetching calendars
"""
import datetime as dt
import json
import os
import struct
import sys
import time
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo

from PIL import Image, ImageDraw, ImageFont

W, H = 400, 300
HERE = Path(__file__).resolve().parent
TZ = ZoneInfo(os.environ.get("TZ_NAME", "Europe/Madrid"))
DAYS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
DAYS_SHORT = ["LUN", "MAR", "MIÉ", "JUE", "VIE", "SÁB", "DOM"]
MONTHS = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
          "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
BLACK, WHITE = 0, 1
LEFT = 132            # width of the black date/weather column
BATTERY_BOX = (340, 0, 400, 22)   # kept white: the device stamps its battery here


def font(name, size):
    return ImageFont.truetype(str(HERE / "fonts" / name), size)


def inter(size, weight=400):
    f = font("Inter.ttf", size)
    try:
        f.set_variation_by_axes([size if size < 32 else 32, weight])
    except Exception:
        try:
            f.set_variation_by_axes([weight])
        except Exception:
            pass
    return f


SANS = lambda s: font("DejaVuSans.ttf", s)
BOLD = lambda s: font("DejaVuSans-Bold.ttf", s)


# ---------------------------------------------------------------- data
def fetch(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": "note4-calendar/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def load_events(now, days=7):
    if os.environ.get("DEMO"):
        d = now.date()
        mk = lambda day, h, m, dur, title: (
            dt.datetime.combine(d + dt.timedelta(days=day), dt.time(h, m), TZ),
            dt.datetime.combine(d + dt.timedelta(days=day), dt.time(h, m), TZ) + dt.timedelta(minutes=dur),
            title, False)
        allday = lambda day, title: (dt.datetime.combine(d + dt.timedelta(days=day), dt.time(0), TZ),
                                     dt.datetime.combine(d + dt.timedelta(days=day + 1), dt.time(0), TZ), title, True)
        multi = (dt.datetime.combine(d, dt.time(0), TZ), dt.datetime.combine(d + dt.timedelta(days=3), dt.time(0), TZ),
                 "Feria de muestras", True)
        return [allday(0, "Cumpleaños de Ana"), multi, mk(0, 9, 30, 30, "Daily del equipo"),
                mk(0, 11, 0, 60, "Revisión roadmap Q1"), mk(0, 14, 0, 90, "Comida con Laura"),
                mk(0, 17, 30, 60, "Pádel"), mk(1, 8, 45, 30, "Dentista"),
                mk(1, 10, 0, 60, "1:1 con Marta"), mk(1, 19, 0, 120, "Cena aniversario"),
                mk(2, 9, 0, 480, "Viaje a Madrid"), mk(3, 12, 0, 60, "Entrega propuesta")]
    import icalendar
    import recurring_ical_events
    start = dt.datetime.combine(now.date(), dt.time(0), TZ)
    end = start + dt.timedelta(days=days)
    events = []
    for url in os.environ.get("ICAL_URLS", "").split():
        cal = icalendar.Calendar.from_ical(fetch(url))
        for ev in recurring_ical_events.of(cal).between(start, end):
            if str(ev.get("STATUS", "")).upper() == "CANCELLED" or str(ev.get("TRANSP", "")).upper() == "TRANSPARENT" and False:
                continue
            s, e = ev["DTSTART"].dt, (ev.get("DTEND") or ev["DTSTART"]).dt
            allday = not isinstance(s, dt.datetime)
            if allday:
                s = dt.datetime.combine(s, dt.time(0), TZ)
                e = dt.datetime.combine(e, dt.time(0), TZ) if not isinstance(e, dt.datetime) else e
            else:
                s = s.astimezone(TZ) if s.tzinfo else s.replace(tzinfo=TZ)
                e = e.astimezone(TZ) if e.tzinfo else e.replace(tzinfo=TZ)
            title = str(ev.get("SUMMARY", "(sin título)")).strip() or "(sin título)"
            events.append((s, e, title, allday))
    events.sort(key=lambda x: (x[0], not x[3], x[2]))
    return events


def load_weather():
    lat, lon = os.environ.get("LAT"), os.environ.get("LON")
    if os.environ.get("DEMO") and not lat:
        return {"now": 14, "feels": 9, "max": 17, "min": 6, "code": 2, "rain": 10,
                "wind": 38, "gusts": 62, "dir": 300}
    if not lat:
        return None
    url = ("https://api.open-meteo.com/v1/forecast?latitude=%s&longitude=%s"
           "&current=temperature_2m,apparent_temperature,weather_code,wind_speed_10m,wind_direction_10m,wind_gusts_10m"
           "&daily=temperature_2m_max,temperature_2m_min,weather_code,precipitation_probability_max"
           "&wind_speed_unit=kmh&timezone=%s&forecast_days=1" % (lat, lon, str(TZ)))
    try:
        d = json.loads(fetch(url))
        c = d["current"]
        return {"now": round(c["temperature_2m"]), "feels": round(c["apparent_temperature"]),
                "code": d["daily"]["weather_code"][0],
                "max": round(d["daily"]["temperature_2m_max"][0]), "min": round(d["daily"]["temperature_2m_min"][0]),
                "rain": d["daily"]["precipitation_probability_max"][0],
                "wind": round(c["wind_speed_10m"]), "gusts": round(c["wind_gusts_10m"]),
                "dir": c["wind_direction_10m"]}
    except Exception as error:
        print("weather unavailable:", error, file=sys.stderr)
        return None


# ---------------------------------------------------------------- drawing helpers
def text(draw, xy, s, f, fill=BLACK, anchor="la"):
    draw.text(xy, s, font=f, fill=fill, anchor=anchor)


def fit(draw, s, f, width):
    if draw.textlength(s, font=f) <= width:
        return s
    while s and draw.textlength(s + "…", font=f) > width:
        s = s[:-1]
    return s.rstrip() + "…"


def weather_icon(draw, cx, cy, code, ink=WHITE):
    """Simple line icons: sun, cloud, rain, snow, storm, fog."""
    def sun(x, y, r):
        draw.ellipse((x - r, y - r, x + r, y + r), outline=ink, width=2)
        for dx, dy in ((0, -1), (0, 1), (-1, 0), (1, 0), (-.7, -.7), (.7, .7), (-.7, .7), (.7, -.7)):
            draw.line((x + dx * (r + 3), y + dy * (r + 3), x + dx * (r + 7), y + dy * (r + 7)), fill=ink, width=2)

    def cloud(x, y, fill_bg=True):
        bg = BLACK if ink == WHITE else WHITE
        parts = [(x - 16, y - 2, x + 2, y + 14), (x - 8, y - 12, x + 12, y + 8), (x + 2, y - 4, x + 20, y + 14)]
        for p in parts:
            draw.ellipse(p, fill=bg, outline=ink, width=2)
        draw.rectangle((x - 8, y + 4, x + 12, y + 13), fill=bg)
        draw.line((x - 8, y + 14, x + 12, y + 14), fill=ink, width=2)

    if code in (0, 1):
        sun(cx, cy, 9)
    elif code == 2:
        sun(cx - 8, cy - 8, 7)
        cloud(cx + 2, cy + 2)
    elif code == 3:
        cloud(cx, cy)
    elif code in (45, 48):
        for i in range(4):
            draw.line((cx - 18 + (i % 2) * 4, cy - 9 + i * 7, cx + 18 - (i % 2) * 4, cy - 9 + i * 7), fill=ink, width=2)
    elif code in (71, 73, 75, 77, 85, 86):
        cloud(cx, cy - 6)
        for i in range(3):
            x = cx - 10 + i * 10
            draw.text((x, cy + 12), "*", font=BOLD(14), fill=ink, anchor="mm")
    elif code >= 95:
        cloud(cx, cy - 6)
        draw.line((cx + 2, cy + 9, cx - 4, cy + 17, cx + 4, cy + 17, cx - 2, cy + 25), fill=ink, width=2)
    else:  # drizzle / rain / showers
        cloud(cx, cy - 6)
        for i in range(3):
            x = cx - 10 + i * 10
            draw.line((x, cy + 12, x - 3, cy + 20), fill=ink, width=2)


# ---------------------------------------------------------------- layout
def render(now, events, weather, city):
    img = Image.new("1", (W, H), WHITE)
    d = ImageDraw.Draw(img)
    d.fontmode = "1"

    # Left column: date
    d.rectangle((0, 0, LEFT - 1, H - 1), fill=BLACK)
    cx = LEFT // 2
    text(d, (cx, 16), DAYS[now.weekday()].upper(), BOLD(15), WHITE, "mt")
    text(d, (cx, 36), str(now.day), inter(72, 700), WHITE, "mt")
    text(d, (cx, 102), MONTHS[now.month - 1], SANS(16), WHITE, "mt")
    d.line((18, 130, LEFT - 18, 130), fill=WHITE, width=1)

    # Weather: condition, temperature, feels-like and wind
    if weather:
        weather_icon(d, 36, 156, weather["code"])
        text(d, (LEFT - 12, 140), f"{weather['now']}°", inter(30, 600), WHITE, "ra")
        text(d, (cx, 178), f"sensación {weather['feels']}°", SANS(12), WHITE, "mt")
        if weather.get("wind") is not None:
            text(d, (cx, 200), f"viento {weather['wind']} km/h", BOLD(13), WHITE, "mt")
            cierzo = 270 <= weather["dir"] <= 345 and weather["wind"] >= 20
            text(d, (cx, 224), f"rachas {weather['gusts']} km/h", SANS(11), WHITE, "mt")
            if cierzo:
                label = "CIERZO"
                lw = d.textlength(label, font=BOLD(11))
                d.rectangle((cx - lw / 2 - 5, 239, cx + lw / 2 + 4, 253), fill=WHITE)
                text(d, (cx, 241), label, BOLD(11), BLACK, "mt")
            elif weather.get("rain") is not None and weather["rain"] >= 20:
                text(d, (cx, 240), f"lluvia {weather['rain']}%", SANS(11), WHITE, "mt")
        text(d, (cx, 260), f"máx {weather['max']}°  mín {weather['min']}°", SANS(12), WHITE, "mt")
    text(d, (cx, H - 8), "act. " + now.strftime("%H:%M"), SANS(11), WHITE, "mb")

    # Right: agenda
    x0, x1 = LEFT + 12, W - 8
    y = 8
    today = now.date()
    by_day = {}
    for ev in events:
        day = ev[0].astimezone(TZ).date()
        if ev[3]:
            # all-day events spanning several days appear on each day
            last = (ev[1] - dt.timedelta(seconds=1)).date()
            if last >= today:
                by_day.setdefault(max(day, today), []).append(ev)
        elif ev[1] > now or day > today:
            by_day.setdefault(day, []).append(ev)

    def header(label, y):
        text(d, (x0, y), label, BOLD(13), BLACK)
        lw = d.textlength(label, font=BOLD(13))
        d.line((x0 + lw + 8, y + 8, x1 if y > 20 else BATTERY_BOX[0] - 8, y + 8), fill=BLACK, width=1)
        return y + 20

    day_list = sorted(k for k in by_day if k >= today)
    if today not in by_day:
        y = header("HOY", y)
        text(d, (x0, y + 2), "Nada más por hoy", SANS(14), BLACK)
        y += 28
    shown_next = False
    for day in day_list:
        if y > H - 40:
            break
        label = "HOY" if day == today else "MAÑANA" if day == today + dt.timedelta(days=1) else \
            f"{DAYS_SHORT[day.weekday()]} {day.day}"
        y = header(label, y)
        for s, e, title, allday in by_day[day]:
            if y > H - 22:
                text(d, (x0, y), "…", BOLD(14), BLACK)
                y += 18
                break
            title_x = x0 + 56
            if allday:
                # Full-width title with a dashed rule across the row: it reads as spanning the day.
                last = (e - dt.timedelta(seconds=1)).date()
                caption = f"→ {DAYS_SHORT[last.weekday()].lower()} {last.day}" if last > day else "todo el día"
                cw = d.textlength(caption, font=SANS(11))
                text(d, (x1, y + 4), caption, SANS(11), BLACK, "ra")
                text(d, (x0, y), fit(d, title, SANS(16), x1 - x0 - cw - 10), SANS(16), BLACK)
                for xx in range(x0, x1, 6):
                    d.line((xx, y + 20, min(xx + 2, x1), y + 20), fill=BLACK, width=1)
                y += 24
                continue
            when = s.strftime("%H:%M")
            current = day == today and s <= now < e
            upcoming = day == today and not shown_next and s > now
            tf = SANS(16)
            if current or upcoming:
                shown_next = True
                d.rectangle((x0 - 4, y - 2, x1, y + 19), fill=BLACK)
                ink = WHITE
            else:
                ink = BLACK
            text(d, (x0, y + 1), when, BOLD(15), ink)
            text(d, (title_x, y), fit(d, title, tf, x1 - title_x - 2), tf, ink)
            y += 24
        y += 6
    return img


def page_bytes(img, now_utc, expires_hours=26):
    raw = img.tobytes()                     # mode "1": MSB-first, 1 = white, rows of 50 bytes
    assert len(raw) == 15000
    issued = int(now_utc)
    header = struct.pack("<4sB3xIIIIII", b"ZEP1", 0, issued, issued, issued + expires_hours * 3600, 0, 0, 0)
    assert len(header) == 32
    return header + raw


def main():
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "out")
    out.mkdir(parents=True, exist_ok=True)
    now = dt.datetime.now(TZ)
    if os.environ.get("NOW"):
        now = dt.datetime.fromisoformat(os.environ["NOW"]).replace(tzinfo=TZ)
    events = load_events(now)
    weather = load_weather()
    img = render(now, events, weather, os.environ.get("CITY", ""))
    img.save(out / "preview.png")
    (out / "note4.bin").write_bytes(page_bytes(img, time.time()))
    print(f"rendered {len(events)} events -> {out}/note4.bin")


if __name__ == "__main__":
    main()
