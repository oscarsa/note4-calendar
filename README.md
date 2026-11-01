# Note4 calendar screen

Renders a Google Calendar + weather dashboard for a ZECTRIX Note4 running
[Note4 Open Platform](https://github.com/Tinnci/zectrix-note4-platform) and publishes it
with GitHub Pages as a `ZEP1` remote page (400×300, 1 bpp). The device downloads it
on its own schedule and shows it as its sleep cover.

- `render.py` – fetches the calendar(s) and Open-Meteo weather, draws the page.
- `.github/workflows/update.yml` – runs hourly during the day and deploys to Pages.

Configuration:

| Name | Kind | Value |
| --- | --- | --- |
| `ICAL_URLS` | secret | secret iCal address(es), space separated |
| `PAGE_DIR` | secret | random directory name the page is published under |
| `LAT`, `LON`, `CITY` | variables | weather location |

Local preview with sample data: `DEMO=1 python render.py out`.

Fonts: DejaVu Sans (Bitstream Vera license) and Inter (SIL OFL 1.1), see `fonts/`.
