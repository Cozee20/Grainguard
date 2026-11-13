import argparse, csv, math, os, random, datetime as dt

HERE = os.path.dirname(os.path.abspath(__file__))        # the folder this script sits in
DEFAULT_WEATHER = "lagos_style_hourly_weather.csv"       # read from the same folder when no option is given

def here(path):
    """Use the path as given if it exists or is absolute, otherwise look for it next to this script."""
    return path if os.path.isabs(path) or os.path.exists(path) else os.path.join(HERE, path)

# ---------------------------------------------------------------- settings (same values as the HTML simulator)
OFFSET_T  = [1.2, 0.0, -0.8]     # sensor temperature offsets (upper, middle, lower)
OFFSET_RH = [1.5, 0.0, -1.0]     # sensor humidity offsets
RH_OFF_MARGIN = 5                # fan switches OFF when RH is 5 % below the ON value
T_OFF_MARGIN = 2                 # and 2 C below the temperature ON value
ALARM_CLEAR_MARGIN = 3           # alarm clears 3 C below the alarm temperature
SEASON = {12: "Winter", 1: "Winter", 2: "Winter", 3: "Spring", 4: "Spring", 5: "Spring",
          6: "Summer", 7: "Summer", 8: "Summer", 9: "Fall", 10: "Fall", 11: "Fall"}   # northern hemisphere

# ---------------------------------------------------------------- weather sources
def fetch_weather(lat, lon, start, end):
    import requests
    r = requests.get("https://archive-api.open-meteo.com/v1/archive", params={
        "latitude": lat, "longitude": lon, "start_date": start, "end_date": end,
        "hourly": "temperature_2m,relative_humidity_2m,precipitation", "timezone": "auto"}, timeout=60)
    r.raise_for_status()
    h = r.json()["hourly"]
    return [dict(time=t, out_t=a, out_rh=b, rain=c)
            for t, a, b, c in zip(h["time"], h["temperature_2m"], h["relative_humidity_2m"], h["precipitation"])]

def read_weather_csv(path):
    """Read a local weather file. Accepted column names (first match wins):
       time/timestamp/datetime, out_t/temperature_2m/temperature, out_rh/relative_humidity_2m/humidity,
       rain/precipitation (optional)."""
    def pick(row, names):
        for n in names:
            if n in row and row[n] not in ("", None): return row[n]
        return None
    rows = []
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            t = pick(r, ["time", "timestamp", "datetime"]); a = pick(r, ["out_t", "temperature_2m", "temperature"])
            b = pick(r, ["out_rh", "relative_humidity_2m", "humidity"]); c = pick(r, ["rain", "precipitation"])
            if t is None: raise SystemExit("weather CSV needs a time/timestamp/datetime column")
            rows.append(dict(time=t, out_t=float(a) if a else None, out_rh=float(b) if b else None,
                             rain=float(c) if c else 0.0))
    return rows

def synthetic_weather(start, days):
    """Fake but plausible weather for testing without internet."""
    t0 = dt.datetime.fromisoformat(start); rows = []
    for i in range(days * 24):
        t = t0 + dt.timedelta(hours=i); hr = t.hour
        temp = 27 + 5 * math.sin((hr - 9) / 24 * 2 * math.pi) + random.uniform(-.5, .5)
        rh = max(30, min(99, 75 - 25 * math.sin((hr - 9) / 24 * 2 * math.pi) + random.uniform(-4, 4)))
        rows.append(dict(time=t.isoformat(timespec="minutes"), out_t=round(temp, 1), out_rh=round(rh), rain=0.0))
    return rows

# ---------------------------------------------------------------- dataset (dissertation tables)
def load_table6(path):
    """Return {season: (corn_bulk_temp_C, corn_bulk_rh_percent)} from the extracted Table 6 CSV."""
    out = {}
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            if r["bin_section"] == "Corn bulk":
                out[r["season"]] = (float(r["temperature_C_mean"]), float(r["rh_percent_mean"]))
    if len(out) != 4: raise SystemExit("Table 6 CSV should have 4 'Corn bulk' season rows")
    return out

def validate(rows, table6, out_csv):
    by = {s: {"t": [], "rh": []} for s in table6}
    for r in rows:
        s = SEASON[int(r["time"][5:7])]
        by[s]["t"].append(sum(r["t"]) / 3); by[s]["rh"].append(sum(r["rh"]) / 3)
    report, errs_t, errs_rh = [], [], []
    for s in ["Fall", "Winter", "Spring", "Summer"]:
        if not by[s]["t"]: continue
        st = sum(by[s]["t"]) / len(by[s]["t"]); sr = sum(by[s]["rh"]) / len(by[s]["rh"])
        mt, mr = table6[s]
        report.append([s, mt, round(st, 1), round(st - mt, 1), mr, round(sr, 1), round(sr - mr, 1), len(by[s]["t"])])
        errs_t.append(abs(st - mt)); errs_rh.append(abs(sr - mr))
    print("\nValidation against dissertation Table 6 (corn bulk, mean of the three simulated sensors)")
    print(f"{'Season':8}{'T meas':>8}{'T sim':>8}{'diff':>7}{'RH meas':>9}{'RH sim':>8}{'diff':>7}{'hours':>7}")
    for r in report: print(f"{r[0]:8}{r[1]:8.1f}{r[2]:8.1f}{r[3]:7.1f}{r[4]:9.1f}{r[5]:8.1f}{r[6]:7.1f}{r[7]:7d}")
    if errs_t:
        print(f"Mean absolute error: temperature {sum(errs_t)/len(errs_t):.1f} C, humidity {sum(errs_rh)/len(errs_rh):.1f} %")
    with open(out_csv, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["season", "measured_temp_C", "sim_temp_C", "temp_diff", "measured_rh", "sim_rh", "rh_diff", "hours"])
        w.writerows(report)
    print("Saved", out_csv)

# ---------------------------------------------------------------- model and controller (same logic and order as the HTML simulator)
def physics_minute(S, fan, out_t, out_rh):
    """One simulated minute of grain physics. Same equations as physics() in the HTML."""
    for i, s in enumerate(S):
        k = 0.05 if fan else 0.004
        s["t"] += (out_t + OFFSET_T[i] - s["t"]) * k
        if s["rh"] > 75: s["t"] += 0.03
        if fan: s["rh"] += (out_rh * 0.9 + OFFSET_RH[i] - s["rh"]) * 0.03
        else:   s["rh"] += 0.03 + max(0, s["t"] - 25) * 0.01
        s["rh"] = max(15, min(99, s["rh"]))

def controller_minute(S, fan, alarm, rh_on, t_on, temp_alarm, control_fan=True):
    """What the microcontroller does after every minute's readings. Same rules as controller() in the HTML.
       Returns (fan, alarm). When control_fan is False the fan is left as it is (used by the random policy)."""
    max_t = max(s["t"] for s in S); max_rh = max(s["rh"] for s in S)
    if control_fan:
        if not fan and (max_rh > rh_on or max_t > t_on): fan = True
        elif fan and max_rh < rh_on - RH_OFF_MARGIN and max_t < t_on - T_OFF_MARGIN: fan = False
    if not alarm and max_t > temp_alarm: alarm = True
    elif alarm and max_t < temp_alarm - ALARM_CLEAR_MARGIN: alarm = False
    return fan, alarm

def simulate_hour(S, fan, alarm, out_t, out_rh, rh_on, t_on, temp_alarm, control_fan=True):
    """60 minutes, each: physics with the current fan state, then the controller decides the fan and alarm.
       Returns (fan, alarm, minutes_fan_was_on_during_the_physics_steps)."""
    fan_minutes = 0
    for _ in range(60):
        physics_minute(S, fan, out_t, out_rh)
        if fan: fan_minutes += 1
        fan, alarm = controller_minute(S, fan, alarm, rh_on, t_on, temp_alarm, control_fan)
    return fan, alarm, fan_minutes

# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lat", type=float, default=7.38);  ap.add_argument("--lon", type=float, default=3.95)
    ap.add_argument("--start", default="2025-01-01");     ap.add_argument("--end", default="2025-12-31")
    ap.add_argument("--policy", choices=["rules", "random"], default="rules",
                    help="rules = the HTML controller (checked every minute); random = fan on/off in random blocks of hours")
    ap.add_argument("--rh-on", type=float, default=70, help="fan ON above this humidity (HTML slider default 70)")
    ap.add_argument("--t-on", type=float, default=30, help="fan ON above this temperature (HTML slider default 30)")
    ap.add_argument("--temp-alarm", type=float, default=40, help="alarm above this temperature (HTML default 40)")
    ap.add_argument("--offline", action="store_true", help="synthetic weather (no internet)")
    ap.add_argument("--download", action="store_true", help="download weather from Open-Meteo instead of reading the Lagos CSV")
    ap.add_argument("--weather-csv", default=None,
                    help=f"weather CSV to read (default: {DEFAULT_WEATHER} in the same folder as this script)")
    ap.add_argument("--purdue", action="store_true",
                    help="preset: West Lafayette, Indiana weather for Nov 2020 to Nov 2021 (the dissertation period)")
    ap.add_argument("--table6", default=os.path.join(HERE, "table6_seasonal_means_by_bin_section.csv"),
                    help="path to the extracted dissertation Table 6 CSV (default: same folder as this script)")
    ap.add_argument("--init-from-dataset", action="store_true",
                    help="start the grain at the measured corn-bulk T and RH of the starting season")
    ap.add_argument("--validate", action="store_true", help="compare simulated season means with Table 6")
    ap.add_argument("--validation-out", default=os.path.join(HERE, "validation_vs_table6.csv"))
    ap.add_argument("--out", default=os.path.join(HERE, "grainguard_data.csv"))
    a = ap.parse_args()

    if a.purdue: a.lat, a.lon, a.start, a.end = 40.42, -86.92, "2020-11-01", "2021-11-30"

    if a.offline:
        days = (dt.date.fromisoformat(a.end) - dt.date.fromisoformat(a.start)).days + 1
        weather = synthetic_weather(a.start, days)
    elif a.download or a.purdue:
        weather = fetch_weather(a.lat, a.lon, a.start, a.end)
    else:
        path = here(a.weather_csv or DEFAULT_WEATHER)
        if not os.path.exists(path):
            raise SystemExit(f"Weather file not found: {path}\n"
                             f"Put {DEFAULT_WEATHER} in the same folder as this script, or use --weather-csv, --offline or --download.")
        print("Reading weather from", path)
        weather = read_weather_csv(path)
    weather = [w for w in weather if w["out_t"] is not None and w["out_rh"] is not None]   # skip gaps
    if not weather: raise SystemExit("no weather rows")

    t_start, rh_start = 27.0, 62.0      # same starting grain as the HTML simulator
    table6 = load_table6(a.table6) if (a.init_from_dataset or a.validate) else None
    if a.init_from_dataset:
        t_start, rh_start = table6[SEASON[int(weather[0]["time"][5:7])]]
        print(f"Starting grain at {t_start} C and {rh_start} % RH (measured, {SEASON[int(weather[0]['time'][5:7])]})")
    S = [{"t": t_start + OFFSET_T[i], "rh": rh_start + OFFSET_RH[i]} for i in range(3)]

    fan, alarm, block_left, log = False, False, 0, []
    fan_switches, alarm_hours, fan_hours = 0, 0, 0
    cols = ["timestamp", "grain_t1", "grain_t2", "grain_t3", "grain_rh1", "grain_rh2", "grain_rh3",
            "out_t", "out_rh", "rain", "fan_on", "fan_minutes", "alarm_on"]
    with open(a.out, "w", newline="") as f:
        w = csv.writer(f); w.writerow(cols)
        for row in weather:
            if a.policy == "random":
                if block_left == 0: fan, block_left = random.random() < 0.4, random.randint(2, 8)
                block_left -= 1
            fan_before, alarm_before = fan, alarm
            snapshot = ([round(s["t"], 2) for s in S], [round(s["rh"], 2) for s in S])   # state BEFORE this hour's physics
            log.append({"time": row["time"], "t": [s["t"] for s in S], "rh": [s["rh"] for s in S]})
            fan, alarm, fan_minutes = simulate_hour(S, fan, alarm, row["out_t"], row["out_rh"],
                                                    a.rh_on, a.t_on, a.temp_alarm, control_fan=(a.policy == "rules"))
            w.writerow([row["time"]] + snapshot[0] + snapshot[1]
                       + [row["out_t"], row["out_rh"], row["rain"], int(fan_before), fan_minutes, int(alarm_before)])
            fan_hours += fan_minutes / 60.0
            if alarm_before: alarm_hours += 1
            if fan != fan_before: fan_switches += 1
    print("Saved", a.out)
    print(f"{len(weather)} hours simulated. Fan ran {100 * fan_hours / len(weather):.0f} % of the time "
          f"({fan_switches} switch-overs at hour boundaries), alarm active in {alarm_hours} hours.")
    if a.validate: validate(log, table6, a.validation_out)

if __name__ == "__main__":
    main()
