import sqlite3
import requests
from datetime import date, datetime, timedelta, time

import pandas as pd
import altair as alt
import streamlit as st
from icalendar import Calendar

ICAL_URL = "link"
DB_PATH = "coach.db"

# Gent
LAT = 51.0543
LON = 3.7174

WEEKLY_TARGETS = {"run": 2, "strength": 2}

MOOD_LABELS = {
    "good": "Goede dag",
    "normal": "Gewone dag",
    "bad": "Mindere dag",
}

MOOD_EMOJI = {
    "good": "🔥",
    "normal": "🙂",
    "bad": "💛",
}

RUN_ROTATION = [
    {
        "type": "easy_run",
        "title": "Rustige loop",
        "duration": "25–30 min",
        "details": [
            "5 min wandelen/inlopen",
            "20 min rustig lopen",
            "5 min uitwandelen",
        ],
        "why": "Goed voor basisconditie en tennisuithouding.",
    },
    {
        "type": "interval",
        "title": "Interval",
        "duration": "25–35 min",
        "details": [
            "5 min rustig inlopen",
            "6x 1 min sneller lopen + 1 min wandelen",
            "5 min uitwandelen",
        ],
        "why": "Helpt voor explosiviteit en sneller herstel tussen tennisrally’s.",
    },
    {
        "type": "long_run",
        "title": "Langere rustige loop",
        "duration": "35–45 min",
        "details": [
            "5 min wandelen/inlopen",
            "30–35 min rustig lopen",
            "5 min uitwandelen",
        ],
        "why": "Bouwt algemene conditie op.",
    },
]

STRENGTH_ROTATION = [
    {
        "type": "legs",
        "title": "Kracht — benen",
        "duration": "30 min",
        "details": [
            "Squats — 3x10",
            "Lunges — 3x8 per been",
            "Romanian deadlift — 3x10",
            "Glute bridge — 3x12",
            "Calf raises — 3x12",
        ],
        "why": "Sterkere benen helpen bij versnellen, afremmen en draaien op tennis.",
    },
    {
        "type": "upper_body",
        "title": "Kracht — armen/schouders",
        "duration": "25–30 min",
        "details": [
            "Bicep curls — 3x10",
            "Shoulder press — 3x10",
            "Bent-over rows — 3x10",
            "Tricep extension — 3x10",
            "Side raises — 3x12",
        ],
        "why": "Goed voor schouders, houding en bovenlichaamstabiliteit.",
    },
    {
        "type": "core",
        "title": "Kracht — core",
        "duration": "20–25 min",
        "details": [
            "Plank — 3x30 sec",
            "Side plank — 2x20 sec per kant",
            "Dead bug — 3x10 per kant",
            "Russian twists — 3x12 per kant",
            "Leg raises — 3x8",
            "Mountain climbers — 3x20 sec",
        ],
        "why": "Core helpt bij stabiliteit, rotatie en balans tijdens tennis.",
    },
]


# ---------------- DB ----------------

def get_conn():
    return sqlite3.connect(DB_PATH, check_same_thread=False)


def init_db(conn):
    conn.execute("""
    CREATE TABLE IF NOT EXISTS daily_choices (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chosen_on TEXT NOT NULL UNIQUE,
        mood TEXT NOT NULL,
        has_plans INTEGER NOT NULL,
        recommended_type TEXT,
        recommended_title TEXT,
        chosen_action_type TEXT,
        chosen_action_title TEXT,
        weather_temp REAL,
        weather_rain REAL,
        weather_wind REAL,
        note TEXT DEFAULT '',
        created_at TEXT NOT NULL
    )
    """)

    conn.execute("""
    CREATE TABLE IF NOT EXISTS run_stats (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        logged_on TEXT NOT NULL,
        distance_km REAL,
        duration_min REAL,
        avg_pace TEXT,
        avg_hr INTEGER,
        effort INTEGER,
        created_at TEXT NOT NULL
    )
    """)

    conn.execute("""
    CREATE TABLE IF NOT EXISTS injuries (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        start_date TEXT NOT NULL,
        end_date TEXT NOT NULL,
        area TEXT NOT NULL,
        note TEXT DEFAULT '',
        active INTEGER DEFAULT 1,
        created_at TEXT NOT NULL
    )
    """)

    conn.commit()


def q(conn, sql, params=()):
    return conn.execute(sql, params).fetchall()


def exec_(conn, sql, params=()):
    conn.execute(sql, params)
    conn.commit()


def get_day_log(conn, d: date):
    rows = q(conn, """
        SELECT chosen_on, mood, has_plans, recommended_type, recommended_title,
               chosen_action_type, chosen_action_title, weather_temp, weather_rain, weather_wind, note
        FROM daily_choices
        WHERE chosen_on=?
    """, (d.isoformat(),))

    if not rows:
        return None

    r = rows[0]
    return {
        "date": r[0],
        "mood": r[1],
        "has_plans": bool(r[2]),
        "recommended_type": r[3],
        "recommended_title": r[4],
        "chosen_action_type": r[5],
        "chosen_action_title": r[6],
        "temp": r[7],
        "rain": r[8],
        "wind": r[9],
        "note": r[10] or "",
    }


def upsert_day_log(conn, d, mood, has_plans, rec, chosen, weather, note=""):
    exec_(conn, """
        INSERT INTO daily_choices(
            chosen_on, mood, has_plans, recommended_type, recommended_title,
            chosen_action_type, chosen_action_title, weather_temp, weather_rain,
            weather_wind, note, created_at
        )
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(chosen_on) DO UPDATE SET
            mood=excluded.mood,
            has_plans=excluded.has_plans,
            recommended_type=excluded.recommended_type,
            recommended_title=excluded.recommended_title,
            chosen_action_type=excluded.chosen_action_type,
            chosen_action_title=excluded.chosen_action_title,
            weather_temp=excluded.weather_temp,
            weather_rain=excluded.weather_rain,
            weather_wind=excluded.weather_wind,
            note=excluded.note
    """, (
        d.isoformat(),
        mood,
        1 if has_plans else 0,
        rec["type"],
        rec["title"],
        chosen["type"],
        chosen["title"],
        weather.get("temp"),
        weather.get("rain"),
        weather.get("wind"),
        note,
        datetime.now().isoformat(timespec="seconds"),
    ))


def get_recent_logs(conn, days=120):
    start = (date.today() - timedelta(days=days)).isoformat()
    return q(conn, """
        SELECT chosen_on, mood, has_plans, recommended_title, chosen_action_title, chosen_action_type
        FROM daily_choices
        WHERE chosen_on >= ?
        ORDER BY chosen_on DESC
    """, (start,))


def get_yesterday_action(conn):
    return get_day_log(conn, date.today() - timedelta(days=1))


def count_this_week(conn, action_prefix):
    today = date.today()
    start = today - timedelta(days=today.weekday())
    rows = q(conn, """
        SELECT COUNT(*)
        FROM daily_choices
        WHERE chosen_on >= ?
          AND chosen_action_type LIKE ?
    """, (start.isoformat(), f"{action_prefix}%"))
    return rows[0][0] or 0


def count_all_actions(conn, action_prefix):
    rows = q(conn, """
        SELECT COUNT(*)
        FROM daily_choices
        WHERE chosen_action_type LIKE ?
    """, (f"{action_prefix}%",))
    return rows[0][0] or 0


def log_run_stats(conn, logged_on, distance_km, duration_min, avg_pace, avg_hr, effort):
    exec_(conn, """
        INSERT INTO run_stats(
            logged_on, distance_km, duration_min, avg_pace, avg_hr, effort, created_at
        )
        VALUES(?,?,?,?,?,?,?)
    """, (
        logged_on,
        float(distance_km or 0),
        float(duration_min or 0),
        avg_pace,
        int(avg_hr or 0),
        int(effort or 0),
        datetime.now().isoformat(timespec="seconds"),
    ))


def add_injury(conn, start_date, rest_days, area, note):
    end_date = start_date + timedelta(days=int(rest_days))
    exec_(conn, """
        INSERT INTO injuries(start_date, end_date, area, note, active, created_at)
        VALUES(?,?,?,?,1,?)
    """, (
        start_date.isoformat(),
        end_date.isoformat(),
        area,
        note,
        datetime.now().isoformat(timespec="seconds"),
    ))


def get_active_injury(conn, check_date=None):
    d = (check_date or date.today()).isoformat()
    rows = q(conn, """
        SELECT id, area, start_date, end_date, note
        FROM injuries
        WHERE active=1 AND start_date <= ? AND end_date >= ?
        ORDER BY end_date DESC
        LIMIT 1
    """, (d, d))

    if not rows:
        return None

    r = rows[0]
    return {
        "id": r[0],
        "area": r[1],
        "start_date": r[2],
        "end_date": r[3],
        "note": r[4] or "",
    }


def get_run_stats_by_date(conn):
    rows = q(conn, """
        SELECT logged_on, distance_km, duration_min, avg_pace, avg_hr, effort
        FROM run_stats
        ORDER BY logged_on DESC
    """)
    out = {}
    for r in rows:
        out.setdefault(r[0], []).append({
            "distance_km": r[1],
            "duration_min": r[2],
            "avg_pace": r[3],
            "avg_hr": r[4],
            "effort": r[5],
        })
    return out


# ---------------- Weather ----------------

@st.cache_data(ttl=60 * 30)
def get_weather_gent():
    try:
        url = (
            "https://api.open-meteo.com/v1/forecast"
            f"?latitude={LAT}&longitude={LON}"
            "&current=temperature_2m,precipitation,wind_speed_10m"
            "&timezone=Europe%2FBrussels"
        )
        data = requests.get(url, timeout=10).json()
        cur = data.get("current", {})
        return {
            "temp": cur.get("temperature_2m"),
            "rain": cur.get("precipitation"),
            "wind": cur.get("wind_speed_10m"),
            "ok": True,
        }
    except Exception:
        return {"temp": None, "rain": None, "wind": None, "ok": False}


def weather_is_good(weather):
    temp = weather.get("temp")
    rain = weather.get("rain")
    wind = weather.get("wind")

    if temp is None or rain is None or wind is None:
        return True

    return temp >= 7 and rain < 0.5 and wind < 30


# ---------------- Google Calendar via iCal ----------------

@st.cache_data(ttl=900)
def get_ical_events():
    url = st.secrets.get("ICAL_URL", "")

    if not url:
        return []

    try:
        r = requests.get(url, timeout=10)
        r.raise_for_status()

        cal = Calendar.from_ical(r.content)
        events = []

        for component in cal.walk():
            if component.name != "VEVENT":
                continue

            start = component.get("dtstart").dt
            end = component.get("dtend").dt

            if not isinstance(start, datetime) or not isinstance(end, datetime):
                continue

            if start.tzinfo:
                start = start.astimezone().replace(tzinfo=None)
            if end.tzinfo:
                end = end.astimezone().replace(tzinfo=None)

            events.append({
                "start": start,
                "end": end,
                "summary": str(component.get("summary", "")),
            })

        return events

    except Exception:
        return []


def has_evening_plans_from_ical(check_date=None):
    events = get_ical_events()

    d = check_date or date.today()
    evening_start = datetime.combine(d, time(17, 30))
    evening_end = datetime.combine(d, time(21, 30))

    for ev in events:
        if ev["end"] > evening_start and ev["start"] < evening_end:
            return True

    return False


# ---------------- Decision engine ----------------

def next_run_type(conn, simulated_run_count=None):
    n = simulated_run_count if simulated_run_count is not None else count_all_actions(conn, "run")
    return RUN_ROTATION[n % len(RUN_ROTATION)]


def next_strength_type(conn, simulated_strength_count=None, avoid_legs=False):
    n = simulated_strength_count if simulated_strength_count is not None else count_all_actions(conn, "strength")

    options = STRENGTH_ROTATION.copy()
    if avoid_legs:
        options = [x for x in options if x["type"] != "legs"]

    if not options:
        options = STRENGTH_ROTATION

    return options[n % len(options)]


def yesterday_was_heavy(conn):
    y = get_yesterday_action(conn)
    if not y:
        return False

    t = y.get("chosen_action_type") or ""
    return t in ["run_interval", "run_long_run", "strength_legs"]


def build_action(action_type, title, duration="", details=None, why=""):
    return {
        "type": action_type,
        "title": title,
        "duration": duration,
        "details": details or [],
        "why": why,
    }


def suggest_options(conn, mood, has_plans, weather):
    injury = get_active_injury(conn)
    avoid_running = injury is not None
    avoid_legs = injury and injury["area"] in ["knie", "enkel", "voet", "scheen", "been"]

    good_weather = weather_is_good(weather)
    heavy_yesterday = yesterday_was_heavy(conn)

    runs_done = count_this_week(conn, "run")
    strength_done = count_this_week(conn, "strength")

    needs_run = runs_done < WEEKLY_TARGETS["run"]
    needs_strength = strength_done < WEEKLY_TARGETS["strength"]

    if has_plans:
        return {
            "good": build_action(
                "read",
                "Lezen",
                "15 min",
                ["Zet timer op 15 min.", "Geen sport vandaag, want je avond zit vol."],
                "Je hebt nog plannen. Niet overplannen is ook slim.",
            ),
            "normal": build_action(
                "water_reset",
                "Water + rustig voorbereiden",
                "5 min",
                ["Drink water.", "Leg klaar wat je nodig hebt.", "Geen extra druk."],
                "Drukke avond: minimum is genoeg.",
            ),
            "bad": build_action(
                "rest",
                "Niets extra",
                "",
                ["Gewoon je avond doen.", "Geen schuldgevoel."],
                "Rust en ruimte zijn vandaag belangrijker dan nog iets toevoegen.",
            ),
        }

    if injury:
        strength = next_strength_type(conn, avoid_legs=avoid_legs)
        return {
            "good": build_action(
                f"strength_{strength['type']}",
                strength["title"],
                strength["duration"],
                strength["details"],
                f"Blessuremodus actief tot {injury['end_date']}. Geen lopen voorstellen.",
            ),
            "normal": build_action(
                "read",
                "Lezen",
                "15 min",
                ["Rustig lezen.", "Herstel eerst."],
                "Je lichaam krijgt voorrang.",
            ),
            "bad": build_action(
                "rest",
                "Rust",
                "",
                ["Geen druk vandaag."],
                "Herstel telt ook.",
            ),
        }

    if not good_weather:
        strength = next_strength_type(conn)

        if needs_strength and not heavy_yesterday:
            good = build_action(
                f"strength_{strength['type']}",
                strength["title"],
                strength["duration"],
                strength["details"],
                "Slecht weer, maar je bent vrij. Krachttraining thuis past goed.",
            )
        else:
            good = build_action(
                "read",
                "Lezen",
                "20 min",
                ["Lees iets rustig.", "Geen sport forceren vandaag."],
                "Slecht weer en je krachtdoel is al oké of gisteren was zwaar.",
            )

        return {
            "good": good,
            "normal": build_action(
                "read",
                "Lezen",
                "15 min",
                ["Zet timer op 15 min.", "Leg je gsm weg."],
                "Op gewone dagen bij slecht weer houden we het laagdrempelig.",
            ),
            "bad": build_action(
                "rest",
                "Rust",
                "",
                ["Douche, zet thee, niets moeten."],
                "Een mindere dag vraagt zachtheid.",
            ),
        }

    run = next_run_type(conn)

    if needs_run and not heavy_yesterday:
        good = build_action(
            f"run_{run['type']}",
            run["title"],
            run["duration"],
            run["details"],
            "Goed weer en je hebt nog een loopdoel deze week. Ideaal voor tennisconditie.",
        )
    elif needs_strength:
        strength = next_strength_type(conn)
        good = build_action(
            f"strength_{strength['type']}",
            strength["title"],
            strength["duration"],
            strength["details"],
            "Je run-doel zit oké of gisteren was zwaar. Vandaag is kracht slim.",
        )
    else:
        good = build_action(
            "walk",
            "Wandeling",
            "20–30 min",
            ["Rustig wandelen.", "Geen training nodig, wel beweging."],
            "Je weekdoelen zitten goed. Onderhouden is genoeg.",
        )

    return {
        "good": good,
        "normal": build_action(
            "walk",
            "Wandelen",
            "20 min",
            ["Rustig tempo.", "Frisse lucht telt ook."],
            "Gewone dag: wel bewegen, geen druk.",
        ),
        "bad": build_action(
            "short_walk",
            "Korte wandeling",
            "10 min",
            ["Gewoon even buiten.", "Daarna mag je stoppen."],
            "Mindere dag: klein houden is beter dan niets.",
        ),
    }


def simulate_7_day_plan(conn, weather_today, has_plans_today, today_mood="good"):
    plan = []

    runs_done = count_this_week(conn, "run")
    strength_done = count_this_week(conn, "strength")

    y = get_yesterday_action(conn)
    last_action_type = y["chosen_action_type"] if y else ""

    simulated_run_count = count_all_actions(conn, "run")
    simulated_strength_count = count_all_actions(conn, "strength")

    for i in range(7):
        d = date.today() + timedelta(days=i)

        if i == 0:
            mood = today_mood
            has_plans = has_plans_today
            weather = weather_today
        else:
            mood = "good"
            has_plans = has_evening_plans_from_ical(d)
            weather = {"temp": 12, "rain": 0, "wind": 10, "ok": True}

        injury = get_active_injury(conn, d)
        avoid_running = injury is not None
        avoid_legs = injury and injury["area"] in ["knie", "enkel", "voet", "scheen", "been"]

        good_weather = weather_is_good(weather)
        heavy_yesterday_sim = last_action_type in ["run_interval", "run_long_run", "strength_legs"]

        if has_plans:
            action = build_action(
                "read",
                "Lezen",
                "15 min",
                ["Geen sport op drukke avond."],
                "Agenda zit vol.",
            )

        elif mood == "bad":
            action = build_action(
                "short_walk",
                "Korte wandeling",
                "10 min",
                ["Even buiten.", "Daarna mag je stoppen."],
                "Mindere dag: klein houden.",
            )

        elif injury:
            strength = next_strength_type(
                conn,
                simulated_strength_count=simulated_strength_count,
                avoid_legs=avoid_legs,
            )

            action = build_action(
                f"strength_{strength['type']}",
                strength["title"],
                strength["duration"],
                strength["details"],
                f"Blessuremodus tot {injury['end_date']}. Geen lopen.",
            )

            simulated_strength_count += 1
            strength_done += 1

        else:
            needs_run = runs_done < WEEKLY_TARGETS["run"]
            needs_strength = strength_done < WEEKLY_TARGETS["strength"]

            if good_weather and needs_run and not heavy_yesterday_sim:
                run = next_run_type(conn, simulated_run_count)

                action = build_action(
                    f"run_{run['type']}",
                    run["title"],
                    run["duration"],
                    run["details"],
                    "Deze sessie helpt je tennisconditie.",
                )

                runs_done += 1
                simulated_run_count += 1

            elif needs_strength and not heavy_yesterday_sim:
                strength = next_strength_type(conn, simulated_strength_count)

                action = build_action(
                    f"strength_{strength['type']}",
                    strength["title"],
                    strength["duration"],
                    strength["details"],
                    "Kracht helpt voor stabiliteit en blessurepreventie.",
                )

                strength_done += 1
                simulated_strength_count += 1

            elif heavy_yesterday_sim:
                action = build_action(
                    "walk",
                    "Wandeling / herstel",
                    "20 min",
                    ["Rustig wandelen.", "Geen zware training vandaag."],
                    "Na een zware dag is herstel slimmer.",
                )

            else:
                action = build_action(
                    "read",
                    "Lezen of rust",
                    "15–20 min",
                    ["Rustig moment nemen."],
                    "Je trainingsdoelen zitten voorlopig goed.",
                )

        plan.append({"date": d, "action": action})
        last_action_type = action["type"]

    return plan


# ---------------- UI helpers ----------------

def action_card(title, action, recommended=False):
    badge = "Aanbevolen" if recommended else "Optie"
    st.markdown(
        f"""
        <div class="card">
            <div class="badge">{badge}</div>
            <h3>{title}: {action['title']}</h3>
            <p class="muted">{action.get('duration','')}</p>
            <p>{action.get('why','')}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if action.get("details"):
        with st.expander("Schema / details"):
            for d in action["details"]:
                st.write(f"- {d}")


def render_week_plan(plan):
    for item in plan:
        d = item["date"]
        action = item["action"]

        label = "Vandaag" if d == date.today() else d.strftime("%a %d/%m")

        st.markdown(
            f"""
            <div class="card">
                <b>{label}</b><br>
                {action['title']}<br>
                <span class="muted">{action.get('duration', '')}</span>
            </div>
            """,
            unsafe_allow_html=True,
        )


# ---------------- APP ----------------

st.set_page_config(page_title="Mijn Coach", layout="wide")

st.markdown(
    """
    <style>
    .stApp {
        background: linear-gradient(180deg, #f7fbff 0%, #ffffff 45%);
    }
    .block-container {
        max-width: 980px;
        padding-top: 1.4rem;
    }
    h1, h2, h3 {
        letter-spacing: -0.4px;
    }
    .card {
        background: white;
        padding: 1.2rem 1.4rem;
        border-radius: 22px;
        box-shadow: 0 8px 28px rgba(0,0,0,0.06);
        border: 1px solid rgba(0,0,0,0.04);
        margin-bottom: 1rem;
    }
    .badge {
        display: inline-block;
        font-size: 0.75rem;
        background: #eef4ff;
        color: #315f9d;
        padding: 0.25rem 0.6rem;
        border-radius: 999px;
        margin-bottom: 0.4rem;
    }
    .muted {
        color: #6f7682;
        margin-top: -0.4rem;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

conn = get_conn()
init_db(conn)

st.title("Mijn Coach")

tabs = st.tabs(["Vandaag", "Week", "Kalender"])

# ---------------- TAB 1: Vandaag ----------------

with tabs[0]:
    st.subheader("Vandaag")

    today = date.today()
    weather = get_weather_gent()
    has_plans = has_evening_plans_from_ical()
    injury = get_active_injury(conn)
    y = get_yesterday_action(conn)

    c1, c2, c3 = st.columns(3)

    with c1:
        st.metric("Locatie", "Gent")

    with c2:
        st.metric("Weer", f"{weather['temp']}°C" if weather["ok"] else "onbekend")

    with c3:
        if weather["ok"]:
            st.metric("Regen / wind", f"{weather['rain']} mm · {weather['wind']} km/u")
        else:
            st.metric("Regen / wind", "—")

    if has_plans:
        st.info("📅 Je hebt nog plannen vanavond. Ik plan daarom geen sport.")
    else:
        st.success("📅 Je lijkt vanavond vrij. Sport kan ingepland worden.")

    if injury:
        st.warning(f"Blessuremodus actief: {injury['area']} tot {injury['end_date']}. Geen lopen voorstellen.")

    if y:
        st.caption(f"Gisteren: {y['chosen_action_title']}")

    with st.expander("Blessure of pijn ingeven"):
        area = st.selectbox("Waar?", ["knie", "enkel", "voet", "scheen", "been", "rug", "schouder", "arm", "anders"])
        rest_days = st.slider("Hoeveel dagen geen lopen?", 1, 21, 3)
        injury_note = st.text_input("Notitie", placeholder="bv. lichte pijn na tennis")
        if st.button("Blessure opslaan"):
            add_injury(conn, date.today(), rest_days, area, injury_note)
            st.success("Blessuremodus opgeslagen.")
            st.rerun()

    st.divider()

    saved = get_day_log(conn, today)

    if saved:
        st.success(
            f"Vandaag opgeslagen: {MOOD_EMOJI.get(saved['mood'], '')} "
            f"{MOOD_LABELS.get(saved['mood'])} — {saved['chosen_action_title']}"
        )

        if st.button("Vandaag opnieuw kiezen"):
            exec_(conn, "DELETE FROM daily_choices WHERE chosen_on=?", (today.isoformat(),))
            st.rerun()

    else:
        st.markdown("### Hoe voelt vandaag?")

        mood_label = st.radio(
            "Dagtype",
            ["🔥 Goede dag", "🙂 Gewone dag", "💛 Mindere dag"],
            horizontal=True,
            label_visibility="collapsed",
        )

        mood = {
            "🔥 Goede dag": "good",
            "🙂 Gewone dag": "normal",
            "💛 Mindere dag": "bad",
        }[mood_label]

        options = suggest_options(conn, mood=mood, has_plans=has_plans, weather=weather)
        recommended = options["good"]
        chosen = options[mood]

        st.divider()
        st.markdown("## Jouw dagplanning")

        action_card("🔥 Goede dag", options["good"], recommended=True)
        action_card("🙂 Gewone dag", options["normal"])
        action_card("💛 Mindere dag", options["bad"])

        st.info(f"Op basis van je energieniveau kies ik: **{chosen['title']}**")

        note = st.text_area("Optionele note", placeholder="Alleen invullen als je iets kwijt wil.", height=90)

        if st.button("Opslaan", type="primary", use_container_width=True):
            upsert_day_log(conn, today, mood, has_plans, recommended, chosen, weather, note)
            st.rerun()

    st.divider()
    st.markdown("### Strava / run-output ingeven")

    with st.form("strava_form"):
        run_date = st.date_input("Datum run", value=date.today())
        distance_km = st.number_input("Afstand (km)", min_value=0.0, step=0.1)
        duration_min = st.number_input("Duur (min)", min_value=0.0, step=1.0)
        avg_pace = st.text_input("Gemiddeld tempo", placeholder="bv. 6:20/km")
        avg_hr = st.number_input("Gem. hartslag", min_value=0, step=1)
        effort = st.slider("Hoe zwaar voelde het?", 1, 10, 5)

        save_strava = st.form_submit_button("Run opslaan", type="primary")

    if save_strava:
        log_run_stats(conn, run_date.isoformat(), distance_km, duration_min, avg_pace, avg_hr, effort)
        st.success("Run opgeslagen.")
        st.rerun()


# ---------------- TAB 2: Week ----------------

with tabs[1]:
    st.subheader("Rollend weekschema")

    weather = get_weather_gent()
    has_plans = has_evening_plans_from_ical()

    week_plan = simulate_7_day_plan(
        conn=conn,
        weather_today=weather,
        has_plans_today=has_plans,
        today_mood="good",
    )

    c1, c2 = st.columns(2)
    with c1:
        runs_done = count_this_week(conn, "run")
        st.metric("Lopen deze week", f"{runs_done}/2")
        st.progress(min(runs_done / 2, 1.0))

    with c2:
        strength_done = count_this_week(conn, "strength")
        st.metric("Kracht deze week", f"{strength_done}/2")
        st.progress(min(strength_done / 2, 1.0))

    st.divider()
    render_week_plan(week_plan)

    st.divider()
    st.markdown("### Trainingsbibliotheek")

    st.markdown("#### Lopen")
    for r in RUN_ROTATION:
        with st.expander(f"{r['title']} — {r['duration']}"):
            st.write(r["why"])
            for d in r["details"]:
                st.write(f"- {d}")

    st.markdown("#### Kracht")
    for s in STRENGTH_ROTATION:
        with st.expander(f"{s['title']} — {s['duration']}"):
            st.write(s["why"])
            for d in s["details"]:
                st.write(f"- {d}")


# ---------------- TAB 3: Kalender ----------------

with tabs[2]:
    st.subheader("Kalender & verleden")

    pick = st.date_input("Kies maand", value=date.today())
    month_start = pick.replace(day=1)
    next_month = (month_start.replace(day=28) + timedelta(days=4)).replace(day=1)
    month_end = next_month - timedelta(days=1)

    logs = get_recent_logs(conn, days=180)
    df_logs = pd.DataFrame(
        logs,
        columns=["date", "mood", "has_plans", "planned", "done", "type"],
    ) if logs else pd.DataFrame()

    run_stats = get_run_stats_by_date(conn)

    if df_logs.empty:
        st.info("Nog geen verleden opgeslagen.")
    else:
        st.markdown("### Overzicht")
        df_show = df_logs.copy()
        df_show["mood"] = df_show["mood"].map(MOOD_LABELS)
        df_show["agenda"] = df_show["has_plans"].map(lambda x: "Plannen" if x else "Vrij")
        st.dataframe(df_show[["date", "mood", "agenda", "planned", "done"]], use_container_width=True, hide_index=True)

        st.markdown("### Kalender")

        first_wd = month_start.weekday()
        days_in_month = month_end.day
        day_num = 1

        log_by_date = {row["date"]: row for _, row in df_logs.iterrows()}

        for week in range(6):
            cols = st.columns(7)

            for wd in range(7):
                with cols[wd]:
                    if week == 0 and wd < first_wd:
                        st.write("")
                        continue

                    if day_num > days_in_month:
                        st.write("")
                        continue

                    d = month_start.replace(day=day_num)
                    d_str = d.isoformat()
                    row = log_by_date.get(d_str)

                    if row is None:
                        st.markdown(
                            f"""
                            <div class="card">
                                <b>{day_num}</b><br>
                                <span class="muted">—</span>
                            </div>
                            """,
                            unsafe_allow_html=True,
                        )
                    else:
                        mood = row["mood"]
                        emoji = MOOD_EMOJI.get(mood, "")
                        planned = row["planned"]
                        done = row["done"]

                        runs = run_stats.get(d_str, [])
                        run_txt = ""
                        if runs:
                            r = runs[0]
                            run_txt = f"<br><span class='muted'>{r['distance_km']} km · {r['duration_min']} min · {r['avg_pace']}</span>"

                        st.markdown(
                            f"""
                            <div class="card">
                                <b>{day_num} {emoji}</b><br>
                                <span class="muted">Plan:</span> {planned}<br>
                                <span class="muted">Gedaan:</span> {done}
                                {run_txt}
                            </div>
                            """,
                            unsafe_allow_html=True,
                        )

                    day_num += 1

        st.divider()
        st.markdown("### Strava progressie")

        rows = q(conn, """
            SELECT logged_on, distance_km, duration_min, avg_pace, avg_hr, effort
            FROM run_stats
            ORDER BY logged_on ASC
        """)

        if not rows:
            st.caption("Nog geen Strava-output.")
        else:
            df_runs = pd.DataFrame(
                rows,
                columns=["date", "distance_km", "duration_min", "avg_pace", "avg_hr", "effort"],
            )
            df_runs["date_dt"] = pd.to_datetime(df_runs["date"])

            st.dataframe(df_runs, use_container_width=True, hide_index=True)

            chart = (
                alt.Chart(df_runs)
                .mark_line(point=True)
                .encode(
                    x=alt.X("date_dt:T", title="Datum"),
                    y=alt.Y("distance_km:Q", title="Afstand km"),
                    tooltip=["date", "distance_km", "duration_min", "avg_pace", "effort"],
                )
                .properties(height=300)
            )

            st.altair_chart(chart, use_container_width=True)
