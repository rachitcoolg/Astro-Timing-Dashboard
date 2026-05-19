import re
from html import escape
from datetime import datetime, time, timedelta

import pandas as pd
import requests
import streamlit as st
import yfinance as yf
from bs4 import BeautifulSoup


EPH_URL = "https://www.mpanchang.com/planets/ephemeris/"
HORA_URL = "https://www.drikpanchang.com/muhurat/hora.html"
NIFTY_TICKER = "^NSEI"
MUMBAI_GEONAME_ID = "1275339"

HEADERS = {"User-Agent": "Mozilla/5.0"}
VALID_PLANETS = ["Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn"]
PLANET_ORDER = ["Sun", "Moon", "Mercury", "Venus", "Mars", "Jupiter", "Saturn"]
PLANET_SYMBOLS = {
    "Sun": "☉",
    "Moon": "☾",
    "Mercury": "☿",
    "Venus": "♀",
    "Mars": "♂",
    "Jupiter": "♃",
    "Saturn": "♄",
}
PLANET_COLORS = {
    "Sun": "#e2a400",
    "Moon": "#8f9fb3",
    "Mercury": "#2f7d5e",
    "Venus": "#b85c8a",
    "Mars": "#c24130",
    "Jupiter": "#8a6f2a",
    "Saturn": "#5f6470",
}
SIGN_OFFSETS = {
    "Aries": 0,
    "Taurus": 30,
    "Gemini": 60,
    "Cancer": 90,
    "Leo": 120,
    "Virgo": 150,
    "Libra": 180,
    "Scorpio": 210,
    "Sagittarius": 240,
    "Capricorn": 270,
    "Aquarius": 300,
    "Pisces": 330,
}


@st.cache_data(ttl=60 * 30)
def fetch_planet_data(day, month, year):
    session = requests.Session()
    initial_response = session.get(EPH_URL, headers=HEADERS, timeout=20)
    initial_response.raise_for_status()

    initial_soup = BeautifulSoup(initial_response.text, "lxml")
    token_input = initial_soup.find("input", {"name": "__RequestVerificationToken"})
    token = token_input.get("value", "") if token_input else ""

    payload = {
        "__RequestVerificationToken": token,
        "Year": year,
        "Month": month,
        "Day": day,
        "Hour": "09",
        "Minute": "15",
        "Second": "00",
        "GeoId": "",
    }

    response = session.post(EPH_URL, headers=HEADERS, data=payload, timeout=20)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "lxml")
    planet_rows = []
    absolute_values = []

    for row in soup.find_all("tr"):
        cols = [col.get_text(" ", strip=True) for col in row.find_all("td")]

        if len(cols) >= 2 and cols[0] == "Deg. Absolute":
            absolute_match = re.search(r"\d+(?:\.\d+)?", cols[1])

            if absolute_match:
                absolute_values.append(float(absolute_match.group(0)))

            continue

        if len(cols) < 3:
            continue

        planet = cols[0]
        if planet not in VALID_PLANETS:
            continue

        degree_match = re.search(r"\d+(?:\.\d+)?", cols[1])
        sign = cols[2]

        if not degree_match or sign not in SIGN_OFFSETS:
            continue

        degree = float(degree_match.group(0))
        deg_absolute = SIGN_OFFSETS[sign] + degree

        planet_rows.append(
            {
                "Planet": planet,
                "Degree": round(degree, 2),
                "Deg. Absolute": round(deg_absolute, 2),
            }
        )

    for index, absolute_value in enumerate(absolute_values[: len(planet_rows)]):
        planet_rows[index]["Deg. Absolute"] = round(absolute_value, 2)

    return pd.DataFrame(planet_rows)


@st.cache_data(ttl=60 * 30)
def fetch_hora_text(day, month, year):
    response = requests.get(
        HORA_URL,
        headers=HEADERS,
        params={
            "geoname-id": MUMBAI_GEONAME_ID,
            "date": f"{day}/{month}/{year}",
        },
        timeout=20,
    )
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "lxml")
    return soup.get_text("\n", strip=True)


def parse_time_value(value, period):
    parsed = datetime.strptime(f"{value} {period}", "%I:%M %p")
    return time(parsed.hour, parsed.minute)


def parse_hora_slots(hora_text):
    lines = [line.strip() for line in hora_text.splitlines() if line.strip()]

    if "Day Hora" in lines:
        lines = lines[lines.index("Day Hora") :]

    if "Night Hora" in lines:
        lines = lines[: lines.index("Night Hora")]

    slots = []
    current_date = datetime.now().date()
    last_start = None

    for index, line in enumerate(lines):
        planet_match = re.match(
            r"^(Sun|Moon|Mars|Mercury|Jupiter|Venus|Saturn)\b",
            line,
            re.IGNORECASE,
        )

        if not planet_match or index + 5 >= len(lines):
            continue

        if lines[index + 3].lower() != "to":
            continue

        if not re.fullmatch(r"\d{1,2}:\d{2}", lines[index + 1]):
            continue

        if not re.fullmatch(r"\d{1,2}:\d{2}", lines[index + 4]):
            continue

        start_time = parse_time_value(lines[index + 1], lines[index + 2])
        end_time = parse_time_value(lines[index + 4], lines[index + 5])
        start_dt = datetime.combine(current_date, start_time)

        if last_start and start_dt <= last_start:
            start_dt += timedelta(days=1)
            current_date = start_dt.date()

        end_dt = datetime.combine(start_dt.date(), end_time)
        if end_dt <= start_dt:
            end_dt += timedelta(days=1)

        slots.append(
            {
                "Planet": planet_match.group(1).title(),
                "Start": start_dt,
                "End": end_dt,
            }
        )
        last_start = start_dt

    return slots


def build_hora_results(top2, hora_text):
    hora_slots = parse_hora_slots(hora_text)
    hora_results = []

    for _, row in top2.iterrows():
        planet = row["Planet"]
        planet_slots = [
            slot
            for slot in hora_slots
            if slot["Planet"] == planet
        ]

        if not planet_slots:
            continue

        next_slot = min(planet_slots, key=lambda slot: slot["Start"])
        alert_dt = next_slot["End"] - timedelta(minutes=15)

        hora_results.append(
            {
                "Planet": planet,
                "Degree": row["Degree"],
                "Hora Start": next_slot["Start"].strftime("%I:%M %p"),
                "Hora End": next_slot["End"].strftime("%I:%M %p"),
                "Alert Time": alert_dt.strftime("%H:%M"),
            }
        )

    return pd.DataFrame(hora_results)


def build_series_levels(limit=5000):
    return list(range(360, limit + 1, 360))


@st.cache_data(ttl=60 * 5)
def fetch_nifty_data(interval, period="1d"):
    return yf.download(
        NIFTY_TICKER,
        interval=interval,
        period=period,
        progress=False,
        auto_adjust=False,
    )


def get_nifty_close_and_level(target_time, interval, fallback_direction="after"):
    closest_level = 0
    nifty_close = 0
    actual_time = ""

    nifty = fetch_nifty_data(interval)
    if nifty.empty:
        return nifty_close, closest_level, actual_time

    if nifty.index.tz is None:
        nifty.index = nifty.index.tz_localize("UTC")

    nifty.index = nifty.index.tz_convert("Asia/Kolkata")
    nifty["Time"] = nifty.index.strftime("%H:%M")
    target_candle = nifty[nifty["Time"] == target_time]

    if target_candle.empty:
        target_time_value = datetime.strptime(target_time, "%H:%M").time()
        if fallback_direction == "before":
            target_candle = nifty[nifty.index.time <= target_time_value].tail(1)
        else:
            target_candle = nifty[nifty.index.time >= target_time_value].head(1)

    if target_candle.empty:
        return nifty_close, closest_level, actual_time

    close_value = target_candle["Close"].iloc[0]
    if isinstance(close_value, pd.Series):
        close_value = close_value.iloc[0]

    nifty_close = float(close_value)
    actual_time = target_candle["Time"].iloc[0]
    extended_levels = list(range(360, 50001, 360))
    closest_level = int(min(extended_levels, key=lambda x: abs(x - nifty_close)))

    return nifty_close, closest_level, actual_time


def get_nifty_daily_close_level():
    nifty = fetch_nifty_data("1m", period="5d")
    nifty_close = 0
    closest_level = 0
    actual_time = ""

    if nifty.empty:
        return nifty_close, closest_level, actual_time

    if nifty.index.tz is None:
        nifty.index = nifty.index.tz_localize("UTC")

    nifty.index = nifty.index.tz_convert("Asia/Kolkata")
    market_close_window = nifty[
        (nifty.index.time >= time(15, 20))
        & (nifty.index.time <= time(15, 30))
    ]

    if market_close_window.empty:
        return nifty_close, closest_level, actual_time

    target_candle = market_close_window.tail(1)
    close_value = target_candle["Close"].iloc[0]

    if isinstance(close_value, pd.Series):
        close_value = close_value.iloc[0]

    nifty_close = float(close_value)
    actual_time = target_candle.index.strftime("%d-%m-%Y %H:%M")[0]
    extended_levels = list(range(360, 50001, 360))
    closest_level = int(min(extended_levels, key=lambda x: abs(x - nifty_close)))

    return nifty_close, closest_level, actual_time


def build_final_output(df, closest_level):
    final_output = []
    closest_level = int(closest_level)

    for planet in PLANET_ORDER:
        planet_row = df[df["Planet"] == planet]

        if planet_row.empty:
            continue

        degree = float(planet_row["Deg. Absolute"].iloc[0])
        final_projected_level = closest_level + degree

        final_output.append(
            {
                "Planet": planet,
                "Deg. Absolute": round(degree, 2),
                "Closest Level": closest_level,
                "Final Projected Level": round(final_projected_level, 2),
            }
        )

    return pd.DataFrame(final_output)


def build_named_level_output(df, closest_level, source):
    output = build_final_output(df, closest_level)

    if output.empty:
        return output

    output.insert(1, "Level Source", source)
    return output


def closest_360_level(level):
    extended_levels = list(range(360, 50001, 360))
    return int(min(extended_levels, key=lambda x: abs(x - level)))


def build_highest_degree_timing(top2, result_df):
    if top2.empty or result_df.empty:
        return pd.DataFrame()

    highest_planet = top2.iloc[0]["Planet"]
    highest_degree = float(top2.iloc[0]["Degree"])
    timing_row = result_df[result_df["Planet"] == highest_planet]

    if timing_row.empty:
        return pd.DataFrame()

    timing_row = timing_row.iloc[0]

    return pd.DataFrame(
        [
            {
                "Highest Degree Planet": highest_planet,
                "Degree": highest_degree,
                "Hora End": timing_row["Hora End"],
                "Alert Time (-15 min)": timing_row["Alert Time"],
            }
        ]
    )


def with_planet_graphics(df):
    if df.empty or "Planet" not in df.columns:
        return df

    output = df.copy()
    output.insert(0, "Icon", output["Planet"].map(PLANET_SYMBOLS).fillna(""))
    return output


def render_top_planet_cards(top2):
    cols = st.columns(2)

    for index, (_, row) in enumerate(top2.iterrows()):
        planet = row["Planet"]
        symbol = PLANET_SYMBOLS.get(planet, "")
        color = PLANET_COLORS.get(planet, "#607080")

        with cols[index]:
            st.markdown(
                f"""
                <div class="planet-card" style="border-top-color: {color};">
                    <div class="planet-symbol" style="color: {color};">{escape(symbol)}</div>
                    <div>
                        <div class="planet-name">{escape(str(planet))}</div>
                        <div class="planet-degree">{float(row["Degree"]):.2f}°</div>
                        <div class="planet-note">Deg. Absolute {float(row["Deg. Absolute"]):.2f}</div>
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )


def main():
    st.set_page_config(page_title="Astro Timing Dashboard", layout="wide")
    st.markdown(
        """
        <style>
        .block-container {
            padding-top: 2rem;
            max-width: 1180px;
        }
        .app-subtitle {
            color: #5b6472;
            font-size: 1rem;
            margin-bottom: 1.5rem;
        }
        .planet-card {
            align-items: center;
            background: #ffffff;
            border: 1px solid #e2e7ef;
            border-radius: 8px;
            border-top: 5px solid;
            display: flex;
            gap: 18px;
            min-height: 128px;
            padding: 18px 20px;
            box-shadow: 0 8px 24px rgba(22, 34, 51, 0.08);
        }
        .planet-symbol {
            font-size: 48px;
            line-height: 1;
            width: 56px;
            text-align: center;
        }
        .planet-name {
            color: #1f2937;
            font-size: 22px;
            font-weight: 700;
        }
        .planet-degree {
            color: #111827;
            font-size: 30px;
            font-weight: 800;
            margin-top: 2px;
        }
        .planet-note {
            color: #667085;
            font-size: 14px;
            margin-top: 4px;
        }
        div[data-testid="stDataFrame"] {
            border: 1px solid #e2e7ef;
            border-radius: 8px;
            overflow: hidden;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    today = datetime.now()
    day = today.strftime("%d")
    month = today.strftime("%m")
    year = today.strftime("%Y")

    st.title("Astro Timing Dashboard")
    st.markdown(
        f"<div class='app-subtitle'>Mumbai, India · {day}-{month}-{year} · Planetary positions at 09:15 AM</div>",
        unsafe_allow_html=True,
    )

    try:
        df = fetch_planet_data(day, month, year)
        hora_text = fetch_hora_text(day, month, year)
        nifty_920_close, closest_920_level, actual_920_time = get_nifty_close_and_level("09:20", "5m")
        nifty_914_close, closest_914_level, actual_914_time = get_nifty_close_and_level("09:14", "1m")
        nifty_1530_close, closest_1530_level, actual_1530_time = get_nifty_daily_close_level()
    except Exception as exc:
        st.error(f"Could not load dashboard data: {exc}")
        st.stop()

    if df.empty:
        st.error("No planetary data found.")
        st.stop()

    top2 = df.sort_values(by="Degree", ascending=False).head(2)
    result_df = build_hora_results(top2, hora_text)
    levels_920_df = build_named_level_output(df, closest_920_level, "NIFTY 09:20")
    source_914 = "NIFTY 09:14" if actual_914_time == "09:14" else f"NIFTY 09:14 using {actual_914_time}"
    levels_914_df = build_named_level_output(df, closest_914_level, source_914)
    source_1530 = f"NIFTY Daily Close {actual_1530_time}" if actual_1530_time else "NIFTY Daily Close"
    levels_1530_df = build_named_level_output(df, closest_1530_level, source_1530)

    st.subheader("1. 2 Highest Degree Planets")
    render_top_planet_cards(top2)

    st.subheader("2. 2 Highest Degree Planet Timing")
    if result_df.empty:
        st.warning("Hora timings were not found for the top 2 planets.")
    else:
        st.dataframe(with_planet_graphics(result_df), width="stretch", hide_index=True)

    st.subheader("3. All Levels")
    st.markdown(f"**NIFTY 09:20 Close:** {round(nifty_920_close, 2) if nifty_920_close else '-'}")
    if levels_920_df.empty or not closest_920_level:
        st.warning("09:20 level was not found.")
    else:
        st.dataframe(with_planet_graphics(levels_920_df), width="stretch", hide_index=True)

    label_914 = "09:14" if actual_914_time == "09:14" else f"09:14 request, using {actual_914_time}"
    st.markdown(f"**NIFTY {label_914} Close:** {round(nifty_914_close, 2) if nifty_914_close else '-'}")
    if levels_914_df.empty or not closest_914_level:
        st.warning("09:14 level was not found.")
    else:
        st.dataframe(with_planet_graphics(levels_914_df), width="stretch", hide_index=True)

    label_1530 = actual_1530_time or "03:30 PM"
    st.markdown(f"**NIFTY Daily Close ({label_1530}):** {round(nifty_1530_close, 2) if nifty_1530_close else '-'}")
    if levels_1530_df.empty or not closest_1530_level:
        st.warning("03:30 PM close level was not found.")
    else:
        st.dataframe(with_planet_graphics(levels_1530_df), width="stretch", hide_index=True)

    manual_level = st.number_input(
        "Manual level",
        min_value=0.0,
        value=float(closest_1530_level or closest_920_level or 0),
        step=1.0,
    )
    manual_closest_level = closest_360_level(manual_level)
    st.markdown(f"**Manual closest 360 level:** {manual_closest_level}")
    manual_df = build_named_level_output(df, manual_closest_level, "Manual")
    st.dataframe(with_planet_graphics(manual_df), width="stretch", hide_index=True)


if __name__ == "__main__":
    main()
