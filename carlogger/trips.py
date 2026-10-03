"""Trip analytics: per-drive summaries from the logged data.

Everything here is pure SQL + arithmetic over what the logger already
captures -- no new hardware, no new processes. Used by the dash
(/api/trip) and the CSV exporter.
"""
from __future__ import annotations

import sqlite3

FUEL_DENSITY_KG_L = 0.745  # gasoline
STOICH_RATIO = 14.7  # air:fuel mass ratio


def _series(conn: sqlite3.Connection, session_id: int,
            name: str) -> list[tuple[float, float]]:
    rows = conn.execute(
        "SELECT ts, value FROM obd2 WHERE session_id=? AND name=? "
        "AND value IS NOT NULL ORDER BY ts",
        (session_id, name)).fetchall()
    return [(r["ts"], r["value"]) for r in rows]


def _integrate(s: list[tuple[float, float]]) -> float:
    """Trapezoid-integrate value-seconds from a (ts, value) series."""
    total = 0.0
    for (t0, v0), (t1, v1) in zip(s, s[1:]):
        dt = t1 - t0
        if 0 < dt < 30:  # ignore gaps (logger restarts, etc.)
            total += (v0 + v1) / 2 * dt
    return total


def _events(s: list[tuple[float, float]], thresh: float,
            above: bool) -> int:
    """Count threshold-crossing events in a derivative series, debounced
    so one maneuver counts once even across several samples."""
    n = 0
    armed = True
    for (t0, v0), (t1, v1) in zip(s, s[1:]):
        dt = t1 - t0
        if not (0 < dt < 30):
            continue
        dv = (v1 - v0) / dt
        hit = dv > thresh if above else dv < thresh
        if hit and armed:
            n += 1
            armed = False
        elif not hit:
            armed = True
    return n


def list_sessions(conn: sqlite3.Connection) -> list[dict]:
    """All sessions, newest first, with per-table sample counts."""
    out = []
    for row in conn.execute(
            "SELECT id, started_at, note FROM sessions ORDER BY id DESC"):
        sid = row["id"]
        counts = {}
        for table in ("obd2", "signals", "vision_events",
                      "dtc_events", "gps_fixes"):
            try:
                counts[table] = conn.execute(
                    f"SELECT COUNT(*) AS n FROM {table} WHERE session_id=?",
                    (sid,)).fetchone()["n"]
            except sqlite3.OperationalError:
                counts[table] = 0  # table from a newer schema, old DB
        out.append({"id": sid, "started_at": row["started_at"],
                    "note": row["note"] or "", "counts": counts})
    return out


def summarize(conn: sqlite3.Connection, session_id: int) -> dict:
    """Compute a drive summary. Missing data -> None fields, never errors."""
    srow = conn.execute(
        "SELECT id, started_at, note FROM sessions WHERE id=?",
        (session_id,)).fetchone()
    if srow is None:
        return {"error": f"no session {session_id}"}

    speed = _series(conn, session_id, "speed")      # km/h
    rpm = _series(conn, session_id, "rpm")
    maf = _series(conn, session_id, "maf")          # g/s

    summary: dict = {
        "session_id": session_id,
        "started_at": srow["started_at"],
        "note": srow["note"] or "",
    }

    if speed:
        t0, t1 = speed[0][0], speed[-1][0]
        duration = t1 - t0
        distance_km = _integrate(speed) / 3600.0
        vmax = max(v for _, v in speed)
        vavg = (distance_km / (duration / 3600.0)) if duration > 0 else 0.0
        idle_s = sum(
            min(t1_ - t0_, 30) for (t0_, v0), (t1_, v1) in zip(speed, speed[1:])
            if v0 < 2 and v1 < 2 and 0 < (t1_ - t0_) < 30)
        summary.update({
            "duration_s": round(duration, 1),
            "distance_km": round(distance_km, 2),
            "avg_speed_kmh": round(vavg, 1),
            "max_speed_kmh": round(vmax, 1),
            "idle_s": round(idle_s, 1),
            "idle_pct": round(100 * idle_s / duration, 1) if duration else 0.0,
            # km/h per second; ~2.8 m/s^2 accel, ~3.3 m/s^2 braking
            "harsh_accel_events": _events(speed, 10.0, above=True),
            "harsh_brake_events": _events(speed, -12.0, above=False),
        })
    else:
        summary.update({k: None for k in (
            "duration_s", "distance_km", "avg_speed_kmh", "max_speed_kmh",
            "idle_s", "idle_pct", "harsh_accel_events",
            "harsh_brake_events")})

    # Fuel from MAF: fuel_gs = maf / 14.7, litres = grams / 1000 / 0.745
    fuel_l: float | None = None
    if maf and summary.get("distance_km"):
        fuel_g = _integrate(maf) / STOICH_RATIO
        fuel_l = fuel_g / 1000.0 / FUEL_DENSITY_KG_L
    summary["fuel_l"] = round(fuel_l, 2) if fuel_l else None
    dist = summary.get("distance_km") or 0
    summary["l_per_100km"] = (round(100 * fuel_l / dist, 2)
                              if fuel_l and dist > 0.5 else None)

    dtcs = conn.execute(
        "SELECT code, description, status, MAX(ts) AS ts FROM dtc_events "
        "WHERE session_id=? GROUP BY code, status",
        (session_id,)).fetchall()
    summary["dtcs"] = [{"code": r["code"],
                        "description": r["description"] or "",
                        "status": r["status"], "ts": r["ts"]} for r in dtcs]
    summary["dtc_count"] = len(dtcs)

    summary["vision_interesting"] = conn.execute(
        "SELECT COUNT(*) AS n FROM vision_events "
        "WHERE session_id=? AND interesting=1",
        (session_id,)).fetchone()["n"]
    summary["vision_events"] = conn.execute(
        "SELECT COUNT(*) AS n FROM vision_events WHERE session_id=?",
        (session_id,)).fetchone()["n"]

    gps = conn.execute(
        "SELECT COUNT(*) AS n, MIN(lat) AS la0, MAX(lat) AS la1, "
        "MIN(lon) AS lo0, MAX(lon) AS lo1 FROM gps_fixes WHERE session_id=?",
        (session_id,)).fetchone()
    summary["gps_fixes"] = gps["n"]
    summary["gps_bbox"] = ([gps["la0"], gps["lo0"], gps["la1"], gps["lo1"]]
                           if gps["n"] else None)
    return summary


def track(conn: sqlite3.Connection, session_id: int,
          max_points: int = 500) -> dict:
    """Decimated GPS track for the dash map: [[lat, lon], ...]."""
    rows = conn.execute(
        "SELECT lat, lon FROM gps_fixes WHERE session_id=? ORDER BY ts",
        (session_id,)).fetchall()
    pts = [(r["lat"], r["lon"]) for r in rows]
    if len(pts) > max_points:
        step = len(pts) / max_points
        pts = [pts[int(i * step)] for i in range(max_points)]
    return {"session_id": session_id, "points": pts}
