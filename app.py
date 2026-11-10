import os
import re
import json
import base64
import difflib
import time
import threading
import csv
import io
import secrets
import hashlib
import hmac
import zipfile
from datetime import datetime, timezone
from functools import wraps

import requests
from flask import Flask, request, jsonify, session, redirect, url_for, render_template, send_file, send_from_directory, abort, has_request_context

try:
    import config
except ImportError:
    class _ConfigFallback:
        ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "change-me")
        SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key-change-in-production")
        AI_PROVIDER = os.environ.get("AI_PROVIDER", "gemini")
        GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
        GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.8-flash")
        GEMINI_FALLBACK_MODELS = ["gemini-3.5-flash-lite"]
        ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
        AI_MODEL = os.environ.get("AI_MODEL", "claude-sonnet-4-6")
    config = _ConfigFallback()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(BASE_DIR, "data.json")
LOCK = threading.Lock()

app = Flask(__name__)
app.secret_key = config.SECRET_KEY
app.config.update(
    MAX_CONTENT_LENGTH=40 * 1024 * 1024,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SECURE", "0").lower() in ("1", "true", "yes"),
    PERMANENT_SESSION_LIFETIME=60 * 60 * 8,
)
BACKUP_DIR = os.path.join(BASE_DIR, "backups")
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
UPLOAD_NAME_RE = re.compile(r"^[0-9a-f]{24}\.(png|jpg|webp)$")
LOGO_PATH_RE = re.compile(r"^/uploads/[0-9a-f]{24}\.(png|jpg|webp)$")
AUDIT_FILE = os.path.join(BASE_DIR, "activity.json")
SCHEDULE_FILE = os.path.join(BASE_DIR, "schedules.json")
USERS_FILE = os.path.join(BASE_DIR, "admin_users.json")
TEAM_LOGOS_FILE = os.path.join(BASE_DIR, "team_logos.json")
LOGIN_ATTEMPTS = {}
REGISTRATION_ATTEMPTS = {}
LOGIN_LOCK = threading.Lock()


def csrf_token():
    token = session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["csrf_token"] = token
    return token


app.jinja_env.globals["csrf_token"] = csrf_token


@app.before_request
def protect_post_requests():
    if request.method != "POST":
        return None
    if request.endpoint == "register_team":
        return None
    expected = session.get("csrf_token", "")
    supplied = request.headers.get("X-CSRF-Token") or request.form.get("csrf_token", "")
    if not expected or not supplied or not hmac.compare_digest(expected, supplied):
        return jsonify(error="Your session token expired. Refresh the page and try again."), 400
    return None


def read_json_file(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError, TypeError):
        return default


def write_json_file(path, value):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(value, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def audit(action, details="", coalesce=False):
    """Add a row to the activity log. With coalesce=True, a repeat of the newest row
    (same user, action and details within 5 minutes) just bumps its time and count."""
    now = datetime.now(timezone.utc)
    user = session.get("username", "system") if has_request_context() else "system"
    action = str(action)[:80]
    details = str(details)[:240]
    with LOCK:
        rows = read_json_file(AUDIT_FILE, [])
        if coalesce and rows:
            top = rows[0]
            try:
                age = (now - datetime.fromisoformat(top.get("time", ""))).total_seconds()
            except (ValueError, TypeError):
                age = None
            if (age is not None and 0 <= age < 300 and top.get("user") == user
                    and top.get("action") == action and top.get("details") == details):
                top["time"] = now.isoformat(timespec="seconds")
                top["count"] = int(top.get("count", 1)) + 1
                write_json_file(AUDIT_FILE, rows[:300])
                return
        rows.insert(0, {
            "time": now.isoformat(timespec="seconds"),
            "user": user,
            "action": action,
            "details": details,
        })
        write_json_file(AUDIT_FILE, rows[:300])


BACKUP_STAMP = "%Y%m%dT%H%M%S%fZ"


def backup_files(prefix):
    if not os.path.isdir(BACKUP_DIR):
        return []
    return sorted(n for n in os.listdir(BACKUP_DIR) if n.startswith(prefix + "_") and n.endswith(".json"))


def store_backup(prefix, src, min_gap=0, keep=50):
    """Copy src into backups/ as <prefix>_<timestamp>.json.
    If the newest copy is younger than min_gap seconds, skip: a burst of edits is one undo step."""
    if not os.path.exists(src):
        return False
    os.makedirs(BACKUP_DIR, exist_ok=True)
    now = datetime.now(timezone.utc)
    existing = backup_files(prefix)
    if min_gap and existing:
        try:
            stamp = existing[-1][len(prefix) + 1:-5]
            last = datetime.strptime(stamp, BACKUP_STAMP).replace(tzinfo=timezone.utc)
            if 0 <= (now - last).total_seconds() < min_gap:
                return False
        except ValueError:
            pass
    target = os.path.join(BACKUP_DIR, "%s_%s.json" % (prefix, now.strftime(BACKUP_STAMP)))
    with open(src, "rb") as fin, open(target, "wb") as fout:
        fout.write(fin.read())
    for name in backup_files(prefix)[:-keep]:
        try:
            os.remove(os.path.join(BACKUP_DIR, name))
        except OSError:
            pass
    return True


def snapshot_scrim(sid, min_gap=0):
    return store_backup(sid, scrim_path(sid), min_gap)


def clear_redo(sid):
    for name in backup_files("redo_" + sid):
        try:
            os.remove(os.path.join(BACKUP_DIR, name))
        except OSError:
            pass


def password_hash(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("ascii"), 240000).hex()
    return {"salt": salt, "hash": digest}


def load_users():
    users = read_json_file(USERS_FILE, None)
    if isinstance(users, dict) and users:
        return users
    # One-time migration from the original single-password configuration.
    initial = password_hash(getattr(config, "ADMIN_PASSWORD", "change-this-before-launch"))
    users = {getattr(config, "ADMIN_USERNAME", "admin"): initial}
    write_json_file(USERS_FILE, users)
    return users


def check_password(username, password):
    users = load_users()
    record = users.get(username)
    if not isinstance(record, dict):
        # Do a comparable amount of work for unknown usernames.
        password_hash(password or "invalid")
        return False
    candidate = password_hash(password, record.get("salt", ""))["hash"]
    return hmac.compare_digest(candidate, record.get("hash", ""))


def analytics_for(state):
    teams = compute(state)
    team_stats = []
    player_map = {}
    for row in teams:
        played = [g for g in row["games"] if not g["noshow"] and not g.get("dq") and g["rank"]]
        ranks = [g["rank"] for g in played]
        team_stats.append({
            "slot": row["slot"], "name": row["name"], "total": row["total"],
            "kills": row["kills"], "wins": sum(1 for rank in ranks if rank == 1),
            "top3": sum(1 for rank in ranks if rank <= 3),
            "average_placement": round(sum(ranks) / len(ranks), 2) if ranks else None,
            "games_played": len(played),
        })
    for slot, team in enumerate(state["teams"]):
        if not team.get("name", "").strip():
            continue
        for player_index, player in enumerate(team.get("players", [])):
            player = str(player or "").strip()
            if not player:
                continue
            key = "%d:%s" % (slot + 1, player.casefold())
            entry = player_map.setdefault(key, {"name": player, "team": team["name"], "kills": 0, "games_played": 0, "best_game": 0})
            for game in state["results"]:
                result = game[slot] if slot < len(game) else blank_result()
                if result.get("noshow") or result.get("dq"):
                    continue
                per_player = result.get("pk") or []
                kills = per_player[player_index] if player_index < len(per_player) else None
                if kills is not None:
                    entry["kills"] += max(0, int(kills))
                    entry["games_played"] += 1
                    entry["best_game"] = max(entry["best_game"], int(kills))
    players = list(player_map.values())
    for player in players:
        player["average_kills"] = round(player["kills"] / player["games_played"], 2) if player["games_played"] else 0
    team_stats.sort(key=lambda x: (-x["total"], x["slot"]))
    players.sort(key=lambda x: (-x["kills"], -x["best_game"], x["name"].casefold()))
    return {"teams": team_stats, "players": players, "player_kills_note": "Player kill totals include only games where individual player kills were entered."}



def blank_result():
    return {"rank": None, "kills": None, "noshow": False, "dq": False, "pk": [None] * 4}


DEFAULT_THEME_COLOR = "#7b2fe0"
HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def clean_theme(raw):
    """Only one value is stored: the base colour. The page derives the whole palette from it."""
    color = raw.get("color") if isinstance(raw, dict) else None
    color = str(color or "").strip()
    return {"color": color.lower() if HEX_RE.match(color) else DEFAULT_THEME_COLOR}


def default_state():
    return {
        "title": "ST6 MIXED SCRIMMAGE",
        "date": "",
        "games": 4,
        "slots": 25,
        "kill_points": 2,
        "placement_points": [15, 12, 10, 8, 6, 4, 2],
        "teams": [{"name": "", "aliases": [], "players": [""] * 4} for _ in range(25)],
        "results": [[blank_result() for _ in range(25)] for _ in range(4)],
        "locked": [False] * 4,
        "theme": {"color": DEFAULT_THEME_COLOR},
    }


def to_num(v):
    try:
        f = float(v)
        return int(f) if f == int(f) else f
    except (TypeError, ValueError, OverflowError):
        return None


def to_int(v):
    n = to_num(v)
    return int(n) if n is not None else None


def sanitize(raw):
    s = default_state()
    if not isinstance(raw, dict):
        return s
    s["title"] = str(raw.get("title", s["title"]))[:80]
    s["date"] = str(raw.get("date", ""))[:30]
    s["games"] = min(max(to_int(raw.get("games")) or 1, 1), 12)
    s["slots"] = min(max(to_int(raw.get("slots")) or 1, 1), 50)
    kp = to_num(raw.get("kill_points"))
    s["kill_points"] = max(0, kp) if kp is not None else 2
    pp = raw.get("placement_points")
    if isinstance(pp, list):
        s["placement_points"] = [max(0, to_num(x) or 0) for x in pp][:30]

    raw_teams = raw.get("teams") if isinstance(raw.get("teams"), list) else []
    teams = []
    for i in range(s["slots"]):
        t = raw_teams[i] if i < len(raw_teams) and isinstance(raw_teams[i], dict) else {}
        aliases = t.get("aliases") if isinstance(t.get("aliases"), list) else []
        clean = []
        for a in aliases:
            a = str(a).strip()[:40]
            if a and a not in clean:
                clean.append(a)
        pl = t.get("players") if isinstance(t.get("players"), list) else []
        pl = [str(x)[:30] for x in pl[:4]]
        pl += [""] * (4 - len(pl))
        logo = str(t.get("logo", "")).strip()[:300]
        if logo and not (logo.startswith("https://") or LOGO_PATH_RE.match(logo)):
            logo = ""
        teams.append({"name": str(t.get("name", ""))[:40], "aliases": clean[:60], "players": pl, "logo": logo})
    s["teams"] = teams

    raw_results = raw.get("results") if isinstance(raw.get("results"), list) else []
    results = []
    for g in range(s["games"]):
        rg = raw_results[g] if g < len(raw_results) and isinstance(raw_results[g], list) else []
        row = []
        for i in range(s["slots"]):
            r = rg[i] if i < len(rg) and isinstance(rg[i], dict) else {}
            rank = to_int(r.get("rank"))
            kills = to_int(r.get("kills"))
            pk = r.get("pk") if isinstance(r.get("pk"), list) else []
            pk = [to_int(x) for x in pk[:4]]
            pk = [x if x is not None and x >= 0 else None for x in pk]
            pk += [None] * (4 - len(pk))
            row.append({
                "rank": rank if rank and rank > 0 else None,
                "kills": kills if kills is not None and kills >= 0 else None,
                "noshow": bool(r.get("noshow")),
                "dq": bool(r.get("dq")),
                "pk": pk,
            })
        results.append(row)
    s["results"] = results

    raw_locked = raw.get("locked") if isinstance(raw.get("locked"), list) else []
    s["locked"] = [bool(raw_locked[g]) if g < len(raw_locked) else False for g in range(s["games"])]
    s["theme"] = clean_theme(raw.get("theme"))
    return s


SCRIM_DIR = os.path.join(BASE_DIR, "scrims")
CUR_FILE = os.path.join(SCRIM_DIR, "current.txt")
ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,40}$")


def scrim_path(sid):
    return os.path.join(SCRIM_DIR, sid + ".json")


def new_id():
    return time.strftime("%Y%m%d-%H%M%S") + "-" + os.urandom(2).hex()


def list_ids():
    try:
        names = os.listdir(SCRIM_DIR)
    except OSError:
        return []
    return [f[:-5] for f in names if f.endswith(".json") and ID_RE.match(f[:-5])]


def write_json(path, state):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def set_current(sid):
    with open(CUR_FILE, "w", encoding="utf-8") as f:
        f.write(sid)


def ensure_store():
    """First run: the old data.json (if any) becomes the first saved scrim."""
    with LOCK:
        os.makedirs(SCRIM_DIR, exist_ok=True)
        if list_ids():
            return
        st = default_state()
        if os.path.exists(DATA_FILE):
            try:
                with open(DATA_FILE, "r", encoding="utf-8") as f:
                    st = sanitize(json.load(f))
            except (ValueError, OSError):
                pass
        sid = new_id()
        write_json(scrim_path(sid), st)
        set_current(sid)


def current_id():
    ensure_store()
    try:
        with open(CUR_FILE, "r", encoding="utf-8") as f:
            sid = f.read().strip()
    except OSError:
        sid = ""
    if ID_RE.match(sid) and os.path.exists(scrim_path(sid)):
        return sid
    ids = sorted(list_ids(), key=lambda i: os.path.getmtime(scrim_path(i)), reverse=True)
    set_current(ids[0])
    return ids[0]


def valid_id(sid):
    return bool(sid) and bool(ID_RE.match(str(sid))) and os.path.exists(scrim_path(str(sid)))


def team_logo_key(name):
    return re.sub(r"\s+", " ", str(name or "").strip()).casefold()


def load_team_logos():
    logos = read_json_file(TEAM_LOGOS_FILE, None)
    if isinstance(logos, dict):
        return logos
    # Initialize from existing saved scrims (oldest to newest so newest wins)
    logos = {}
    ids = sorted(list_ids(), key=lambda i: os.path.getmtime(scrim_path(i)))
    for sid in ids:
        try:
            with open(scrim_path(sid), "r", encoding="utf-8") as f:
                raw = json.load(f)
            for t in raw.get("teams") or []:
                if isinstance(t, dict):
                    k = team_logo_key(t.get("name"))
                    lg = str(t.get("logo") or "").strip()
                    if k and lg and (lg.startswith("https://") or LOGO_PATH_RE.match(lg)):
                        logos[k] = lg
        except (ValueError, OSError):
            pass
    if logos:
        write_json_file(TEAM_LOGOS_FILE, logos)
    return logos


def remember_team_logos(state):
    if not isinstance(state, dict):
        return
    logos = load_team_logos()
    changed = False
    for t in state.get("teams") or []:
        if not isinstance(t, dict):
            continue
        k = team_logo_key(t.get("name"))
        lg = str(t.get("logo") or "").strip()
        if k and lg and (lg.startswith("https://") or LOGO_PATH_RE.match(lg)):
            if logos.get(k) != lg:
                logos[k] = lg
                changed = True
    if changed:
        write_json_file(TEAM_LOGOS_FILE, logos)


def apply_saved_team_logos(state):
    if not isinstance(state, dict):
        return state
    logos = load_team_logos()
    if not logos:
        return state
    for t in state.get("teams") or []:
        if not isinstance(t, dict):
            continue
        if not str(t.get("logo") or "").strip():
            k = team_logo_key(t.get("name"))
            if k and k in logos:
                t["logo"] = logos[k]
    return state


def load_state(sid=None):
    ensure_store()
    sid = sid if valid_id(sid) else current_id()
    with LOCK:
        try:
            with open(scrim_path(sid), "r", encoding="utf-8") as f:
                st = sanitize(json.load(f))
            return apply_saved_team_logos(st)
        except (ValueError, OSError):
            return default_state()


def save_state(state, sid=None, snap_gap=30):
    ensure_store()
    # a brand-new scrim has no file yet, so only the id's shape is checked here
    sid = sid if sid and ID_RE.match(str(sid)) else current_id()
    with LOCK:
        remember_team_logos(state)
        apply_saved_team_logos(state)
        path = scrim_path(sid)
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    old = json.load(f)
                if old != state:
                    snapshot_scrim(sid, snap_gap)
                    clear_redo(sid)
            except (ValueError, OSError):
                snapshot_scrim(sid)
        write_json(path, state)
    audit("Saved scrim", str(state.get("title", sid)), coalesce=True)


def list_scrims():
    ensure_store()
    cur = current_id()
    out = []
    for sid in list_ids():
        try:
            with open(scrim_path(sid), "r", encoding="utf-8") as f:
                raw = json.load(f)
            teams = raw.get("teams") if isinstance(raw.get("teams"), list) else []
            named = sum(1 for t in teams if isinstance(t, dict) and str(t.get("name", "")).strip())
            out.append({
                "id": sid,
                "title": str(raw.get("title", ""))[:80],
                "date": str(raw.get("date", ""))[:30],
                "teams": named,
                "games": to_int(raw.get("games")) or 1,
                "updated": os.path.getmtime(scrim_path(sid)),
                "current": sid == cur,
            })
        except (ValueError, OSError):
            continue
    out.sort(key=lambda x: x["updated"], reverse=True)
    return out


def compute(s):
    pp = s["placement_points"]
    kp = s["kill_points"]
    rows = []
    for i, t in enumerate(s["teams"]):
        name = t["name"].strip()
        if not name:
            continue
        games = []
        total_place = 0
        total_kills = 0
        for g in range(s["games"]):
            r = s["results"][g][i]
            place_pts = 0
            kills = 0
            if not r["noshow"] and not r.get("dq"):  # a disqualified game scores 0
                if r["rank"] and 1 <= r["rank"] <= len(pp):
                    place_pts = pp[r["rank"] - 1]
                kills = r["kills"] or 0
            games.append({
                "rank": r["rank"],
                "kills": kills,
                "place_pts": place_pts,
                "points": place_pts + kills * kp,
                "noshow": r["noshow"],
                "dq": bool(r.get("dq")),
            })
            total_place += place_pts
            total_kills += kills
        rows.append({
            "slot": i + 1,
            "name": name,
            "logo": t.get("logo", ""),
            "games": games,
            "place_pts": total_place,
            "kills": total_kills,
            "total": total_place + total_kills * kp,
        })
    rows.sort(key=lambda x: (-x["total"], x["slot"]))
    for n, r in enumerate(rows, 1):
        r["rank"] = n
    return rows


def admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("admin"):
            if request.path.startswith("/api/"):
                return jsonify(error="Not logged in"), 401
            return redirect(url_for("login"))
        return fn(*args, **kwargs)
    return wrapper


@app.route("/")
def index():
    csrf_token()
    return render_template("index.html")


@app.route("/api/state")
def public_state():
    sid = request.args.get("s")
    sid = sid if valid_id(sid) else current_id()
    s = load_state(sid)
    return jsonify({
        "id": sid,
        "title": s["title"],
        "date": s["date"],
        "games": s["games"],
        "slots": s["slots"],
        "kill_points": s["kill_points"],
        "placement_points": s["placement_points"],
        "theme": s["theme"],
        "standings": compute(s),
    })


@app.route("/api/scrims")
def public_scrims():
    schedules = get_schedules()
    return jsonify({
        "current": current_id(),
        "scrims": [dict({"id": x["id"], "title": x["title"], "date": x["date"]}, archived=bool(schedules.get(x["id"], {}).get("archived"))) for x in list_scrims()],
    })


@app.route("/login", methods=["GET", "POST"])
def login():
    error = ""
    if request.method == "POST":
        username = str(request.form.get("username", "admin")).strip()[:40]
        now = time.time()
        with LOGIN_LOCK:
            attempts = [t for t in LOGIN_ATTEMPTS.get(request.remote_addr, []) if now - t < 900]
            if len(attempts) >= 8:
                LOGIN_ATTEMPTS[request.remote_addr] = attempts
                error = "Too many attempts. Wait 15 minutes before trying again."
            elif check_password(username, request.form.get("password", "")):
                LOGIN_ATTEMPTS.pop(request.remote_addr, None)
                session.clear()
                session["admin"] = True
                session["username"] = username
                initial_password_file = os.path.join(BASE_DIR, ".initial_admin_password")
                if os.path.exists(initial_password_file):
                    try:
                        os.remove(initial_password_file)
                    except OSError:
                        pass
                session.permanent = True
                csrf_token()
                audit("Login", username)
                return redirect(url_for("admin"))
            else:
                attempts.append(now)
                LOGIN_ATTEMPTS[request.remote_addr] = attempts
                error = "Incorrect username or password"
    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    audit("Logout", session.get("username", ""))
    session.clear()
    return redirect(url_for("index"))


@app.route("/admin")
@admin_required
def admin():
    return render_template("admin.html", scan_prompt=SCAN_PROMPT, csrf=csrf_token(), username=session.get("username", "admin"))


@app.route("/analytics")
def analytics_page():
    return render_template("analytics.html")


@app.route("/schedule")
def schedule_page():
    return render_template("schedule.html")


@app.route("/history")
def history_page():
    return render_template("history.html")


@app.route("/api/analytics")
def public_analytics():
    sid = request.args.get("s")
    sid = sid if valid_id(sid) else current_id()
    return jsonify({"id": sid, "analytics": analytics_for(load_state(sid))})


def get_schedules():
    data = read_json_file(SCHEDULE_FILE, {})
    return data if isinstance(data, dict) else {}


@app.route("/api/schedules")
def public_schedules():
    schedules = get_schedules()
    output = []
    for item in list_scrims():
        meta = schedules.get(item["id"], {})
        if meta.get("archived"):
            continue
        public_meta = {k: v for k, v in meta.items() if k != "registrations"}
        public_meta["registrations_count"] = len(meta.get("registrations", []))
        output.append(dict(item, schedule=public_meta))
    return jsonify({"schedules": output})


@app.route("/api/admin/schedules")
@admin_required
def admin_schedules():
    schedules = get_schedules()
    return jsonify(schedules=[dict(item, schedule=schedules.get(item["id"], {})) for item in list_scrims()])


@app.route("/api/admin/schedule", methods=["POST"])
@admin_required
def update_schedule():
    data = request.get_json(silent=True) or {}
    sid = str(data.get("id", ""))
    if not valid_id(sid):
        return jsonify(error="Invalid scrim"), 400
    title = str(data.get("title", ""))[:100]
    start_at = str(data.get("start_at", ""))[:40]
    status = str(data.get("status", "upcoming"))
    if status not in ("upcoming", "registration", "ongoing", "completed", "cancelled"):
        return jsonify(error="Invalid status"), 400
    try:
        max_teams = min(50, max(1, int(data.get("max_teams", 25))))
    except (TypeError, ValueError):
        max_teams = 25
    schedules = get_schedules()
    old = schedules.get(sid, {})
    schedules[sid] = {
        "title": title,
        "start_at": start_at,
        "status": status,
        "registration_open": bool(data.get("registration_open")),
        "max_teams": max_teams,
        "notes": str(data.get("notes", ""))[:500],
        "registrations": old.get("registrations", []),
        "archived": bool(old.get("archived", False)),
    }
    write_json_file(SCHEDULE_FILE, schedules)
    audit("Updated schedule", title or sid)
    return jsonify(schedule=schedules[sid])


@app.route("/api/scrims/<sid>/register", methods=["POST"])
def register_team(sid):
    now = time.time()
    recent = [t for t in REGISTRATION_ATTEMPTS.get(request.remote_addr, []) if now - t < 3600]
    if len(recent) >= 8:
        return jsonify(error="Too many registration attempts. Try again later."), 429
    recent.append(now)
    REGISTRATION_ATTEMPTS[request.remote_addr] = recent
    if not valid_id(sid):
        return jsonify(error="Scrim not found"), 404
    schedules = get_schedules()
    meta = schedules.get(sid, {})
    if meta.get("archived") or not meta.get("registration_open") or meta.get("status") in ("completed", "cancelled"):
        return jsonify(error="Registration is closed"), 400
    data = request.get_json(silent=True) or {}
    team = str(data.get("team", "")).strip()[:40]
    captain = str(data.get("captain", "")).strip()[:40]
    contact = str(data.get("contact", "")).strip()[:80]
    if not team or not captain:
        return jsonify(error="Team name and captain are required"), 400
    regs = meta.get("registrations", [])
    if any(x.get("team", "").casefold() == team.casefold() for x in regs):
        return jsonify(error="That team is already registered"), 409
    if len(regs) >= int(meta.get("max_teams", 25)):
        return jsonify(error="Registration is full"), 409
    regs.append({"team": team, "captain": captain, "contact": contact, "registered_at": datetime.now(timezone.utc).isoformat(timespec="seconds")})
    meta["registrations"] = regs
    schedules[sid] = meta
    write_json_file(SCHEDULE_FILE, schedules)
    return jsonify(message="Registration received"), 201


@app.route("/api/admin/registrations/<sid>")
@admin_required
def admin_registrations(sid):
    if not valid_id(sid):
        return jsonify(error="Scrim not found"), 404
    return jsonify(registrations=get_schedules().get(sid, {}).get("registrations", []))


@app.route("/api/admin/registrations/<sid>/delete", methods=["POST"])
@admin_required
def delete_registration(sid):
    if not valid_id(sid):
        return jsonify(error="Scrim not found"), 404
    data = request.get_json(silent=True) or {}
    schedules = get_schedules()
    meta = schedules.get(sid, {})
    regs = meta.get("registrations", [])
    index = data.get("index")
    if not isinstance(index, int) or index < 0 or index >= len(regs):
        return jsonify(error="Registration not found"), 404
    removed = regs.pop(index)
    meta["registrations"] = regs
    schedules[sid] = meta
    write_json_file(SCHEDULE_FILE, schedules)
    audit("Removed registration", removed.get("team", ""))
    return jsonify(registrations=regs)


@app.route("/api/export/<sid>.csv")
def export_csv(sid):
    if not valid_id(sid):
        abort(404)
    state = load_state(sid)
    rows = compute(state)
    output = io.StringIO()
    writer = csv.writer(output)
    headers = ["Rank", "Slot", "Team", "Total Points", "Total Kills"]
    for game in range(state["games"]):
        headers.extend(["Game %d Placement" % (game + 1), "Game %d Kills" % (game + 1), "Game %d Points" % (game + 1)])
    writer.writerow(headers)
    for row in rows:
        values = [row["rank"], row["slot"], row["name"], row["total"], row["kills"]]
        for game in row["games"]:
            values.extend([game["rank"] or "", game["kills"], game["points"]])
        writer.writerow(values)
    mem = io.BytesIO(output.getvalue().encode("utf-8-sig"))
    mem.seek(0)
    return send_file(mem, mimetype="text/csv", as_attachment=True, download_name="scrim-%s-standings.csv" % sid)


@app.route("/api/export/<sid>-players.csv")
def export_player_csv(sid):
    if not valid_id(sid):
        abort(404)
    state = load_state(sid)
    stats = analytics_for(state)["players"]
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["MVP Rank", "Player", "Team", "Total Kills", "Best Game", "Average Kills", "Games Recorded"])
    for rank, player in enumerate(stats, 1):
        writer.writerow([rank, player["name"], player["team"], player["kills"], player["best_game"], player["average_kills"], player["games_played"]])
    mem = io.BytesIO(output.getvalue().encode("utf-8-sig"))
    mem.seek(0)
    return send_file(mem, mimetype="text/csv", as_attachment=True, download_name="scrim-%s-player-stats.csv" % sid)


@app.route("/api/admin/activity")
@admin_required
def admin_activity():
    return jsonify(activity=read_json_file(AUDIT_FILE, [])[:100])


@app.route("/api/admin/backup")
@admin_required
def download_backup():
    ensure_store()
    mem = io.BytesIO()
    with zipfile.ZipFile(mem, "w", zipfile.ZIP_DEFLATED) as archive:
        for folder, _, files in os.walk(SCRIM_DIR):
            for name in files:
                if name.endswith(".json") or name == "current.txt":
                    path = os.path.join(folder, name)
                    archive.write(path, os.path.relpath(path, BASE_DIR))
        for path in (SCHEDULE_FILE, AUDIT_FILE, USERS_FILE, TEAM_LOGOS_FILE):
            if os.path.exists(path):
                archive.write(path, os.path.basename(path))
        if os.path.isdir(UPLOAD_DIR):
            for name in os.listdir(UPLOAD_DIR):
                if UPLOAD_NAME_RE.match(name):
                    archive.write(os.path.join(UPLOAD_DIR, name), os.path.join("uploads", name))
        if os.path.isdir(BACKUP_DIR):
            for name in os.listdir(BACKUP_DIR):
                if name.endswith(".json"):
                    path = os.path.join(BACKUP_DIR, name)
                    archive.write(path, os.path.join("backups", name))
    mem.seek(0)
    audit("Downloaded backup", "Full scrim data archive")
    return send_file(mem, mimetype="application/zip", as_attachment=True, download_name="scrim-backup.zip")


def restore_from_backup(sid, name, push_to):
    """Make backups/<name> the live scrim. The state being replaced is first stored under
    push_to ("redo_<sid>" for undo, <sid> for redo). Returns the restored state or None."""
    path = os.path.join(BACKUP_DIR, name)
    try:
        with open(path, "r", encoding="utf-8") as f:
            restored = sanitize(json.load(f))
    except (ValueError, OSError):
        try:
            os.remove(path)  # an unreadable backup would block every later undo
        except OSError:
            pass
        return None
    with LOCK:
        store_backup(push_to, scrim_path(sid))
        write_json(scrim_path(sid), restored)
    try:
        os.remove(path)
    except OSError:
        pass
    return restored


@app.route("/api/admin/undo", methods=["POST"])
@admin_required
def undo_last_change():
    sid = current_id()
    files = backup_files(sid)
    if not files:
        return jsonify(error="No previous version is available yet"), 404
    restored = restore_from_backup(sid, files[-1], "redo_" + sid)
    if restored is None:
        return jsonify(error="That saved version could not be read. Try Undo again for the one before it."), 500
    audit("Restored previous version", restored.get("title", sid))
    return jsonify(state=restored, standings=compute(restored), can_redo=True)


@app.route("/api/admin/redo", methods=["POST"])
@admin_required
def redo_last_change():
    sid = current_id()
    files = backup_files("redo_" + sid)
    if not files:
        return jsonify(error="Nothing to redo"), 404
    restored = restore_from_backup(sid, files[-1], sid)
    if restored is None:
        return jsonify(error="That version could not be read"), 500
    audit("Redid undone change", restored.get("title", sid))
    return jsonify(state=restored, standings=compute(restored))


@app.route("/api/admin/users", methods=["GET", "POST"])
@admin_required
def admin_users():
    users = load_users()
    if request.method == "GET":
        return jsonify(users=[{"username": name} for name in sorted(users)])
    data = request.get_json(silent=True) or {}
    username = str(data.get("username", "")).strip()
    password = str(data.get("password", ""))
    if not re.match(r"^[A-Za-z0-9_.-]{3,40}$", username):
        return jsonify(error="Username must be 3–40 characters using letters, numbers, dot, dash or underscore"), 400
    if len(password) < 12:
        return jsonify(error="Password must be at least 12 characters"), 400
    if username in users:
        return jsonify(error="That username already exists"), 409
    users[username] = password_hash(password)
    write_json_file(USERS_FILE, users)
    audit("Created admin account", username)
    return jsonify(users=[{"username": name} for name in sorted(users)])


@app.route("/api/admin/password", methods=["POST"])
@admin_required
def change_admin_password():
    data = request.get_json(silent=True) or {}
    username = session.get("username", "")
    current = str(data.get("current", ""))
    new = str(data.get("new", ""))
    if not check_password(username, current):
        return jsonify(error="Current password is incorrect"), 400
    if len(new) < 12:
        return jsonify(error="New password must be at least 12 characters"), 400
    users = load_users()
    users[username] = password_hash(new)
    write_json_file(USERS_FILE, users)
    audit("Changed admin password", username)
    return jsonify(message="Password updated")


@app.route("/api/admin/users/delete", methods=["POST"])
@admin_required
def delete_admin_user():
    data = request.get_json(silent=True) or {}
    username = str(data.get("username", ""))
    users = load_users()
    if username == session.get("username"):
        return jsonify(error="You cannot delete the account you are currently using"), 400
    if username not in users or len(users) <= 1:
        return jsonify(error="Account cannot be deleted"), 400
    del users[username]
    write_json_file(USERS_FILE, users)
    audit("Deleted admin account", username)
    return jsonify(users=[{"username": name} for name in sorted(users)])


@app.route("/api/admin/state")
@admin_required
def admin_state():
    s = load_state()
    return jsonify({"state": s, "standings": compute(s), "team_logos": load_team_logos()})


def validate_state(raw):
    if not isinstance(raw, dict):
        return ["Invalid state payload"]
    errors = []
    try:
        games = min(12, max(1, int(raw.get("games", 1))))
        slots = min(50, max(1, int(raw.get("slots", 1))))
    except (TypeError, ValueError):
        return ["Games and team slots must be valid numbers"]
    results = raw.get("results") if isinstance(raw.get("results"), list) else []
    teams = raw.get("teams") if isinstance(raw.get("teams"), list) else []
    for g in range(min(games, len(results))):
        seen = set()
        game = results[g] if isinstance(results[g], list) else []
        for i, result in enumerate(game[:slots]):
            if not isinstance(result, dict) or result.get("noshow") or result.get("dq"):
                continue
            rank = to_int(result.get("rank"))
            kills = to_int(result.get("kills"))
            if rank is not None and (rank < 1 or rank > slots):
                errors.append("Game %d has a placement outside 1–%d" % (g + 1, slots))
                break
            if rank is not None and i < len(teams) and isinstance(teams[i], dict) and str(teams[i].get("name", "")).strip():
                if rank in seen:
                    errors.append("Game %d has duplicate placement %d" % (g + 1, rank))
                    break
                seen.add(rank)
            if kills is not None and (kills < 0 or kills > 200):
                errors.append("Game %d has a kill count outside 0–200" % (g + 1))
                break
    return errors


@app.route("/api/admin/save", methods=["POST"])
@admin_required
def admin_save():
    raw = request.get_json(silent=True)
    errors = validate_state(raw)
    if errors:
        return jsonify(error="; ".join(errors)), 400
    s = sanitize(raw)
    old = load_state()
    for g in range(min(s["games"], old["games"])):
        if old["locked"][g] and s["locked"][g]:
            s["results"][g] = old["results"][g]
    s = sanitize(s)
    save_state(s)
    return jsonify({"state": s, "standings": compute(s), "team_logos": load_team_logos()})


@app.route("/api/admin/scrims")
@admin_required
def admin_scrims():
    schedules = get_schedules()
    items = [dict(x, archived=bool(schedules.get(x["id"], {}).get("archived"))) for x in list_scrims()]
    return jsonify({"current": current_id(), "scrims": items})


@app.route("/api/admin/scrims/new", methods=["POST"])
@admin_required
def admin_scrim_new():
    d = request.get_json(silent=True) or {}
    base = load_state()
    mode = d.get("mode")
    if mode == "all":
        s = json.loads(json.dumps(base))
    elif mode == "teams":
        s = json.loads(json.dumps(base))
        s["results"] = [[blank_result() for _ in range(s["slots"])] for _ in range(s["games"])]
        s["locked"] = [False] * s["games"]
    else:
        s = default_state()
        for k in ("games", "slots", "kill_points", "placement_points", "theme"):
            s[k] = base[k]
    title = str(d.get("title") or "").strip()
    s["title"] = title or (base["title"] + " (copy)" if mode == "all" else "NEW SCRIM")
    s["date"] = str(d.get("date") or "").strip() if mode != "all" or d.get("date") else base["date"]
    s = sanitize(s)
    sid = new_id()
    save_state(s, sid)
    set_current(sid)
    return jsonify({"id": sid, "state": s, "standings": compute(s), "team_logos": load_team_logos()})


@app.route("/api/admin/scrims/switch", methods=["POST"])
@admin_required
def admin_scrim_switch():
    sid = (request.get_json(silent=True) or {}).get("id")
    if not valid_id(sid):
        return jsonify(error="That scrim no longer exists"), 404
    set_current(sid)
    s = load_state(sid)
    audit("Switched scrim", s.get("title", sid))
    return jsonify({"id": sid, "state": s, "standings": compute(s), "team_logos": load_team_logos()})


@app.route("/api/admin/scrims/delete", methods=["POST"])
@admin_required
def admin_scrim_delete():
    sid = (request.get_json(silent=True) or {}).get("id")
    if not valid_id(sid):
        return jsonify(error="That scrim no longer exists"), 404
    if len(list_ids()) <= 1:
        return jsonify(error="You cannot delete your only scrim. Create another one first."), 400
    was_current = sid == current_id()
    with LOCK:
        os.remove(scrim_path(sid))
    audit("Deleted scrim", sid)
    if was_current:
        ids = sorted(list_ids(), key=lambda i: os.path.getmtime(scrim_path(i)), reverse=True)
        set_current(ids[0])
    cur = current_id()
    s = load_state(cur)
    return jsonify({"id": cur, "state": s, "standings": compute(s), "team_logos": load_team_logos()})


@app.route("/api/admin/scrims/archive", methods=["POST"])
@admin_required
def admin_scrim_archive():
    data = request.get_json(silent=True) or {}
    sid = str(data.get("id", ""))
    if not valid_id(sid):
        return jsonify(error="Scrim not found"), 404
    schedules = get_schedules()
    meta = schedules.get(sid, {})
    meta["archived"] = bool(data.get("archived"))
    schedules[sid] = meta
    write_json_file(SCHEDULE_FILE, schedules)
    audit("Archived scrim" if meta["archived"] else "Restored scrim", sid)
    return jsonify(archived=meta["archived"])


@app.route("/api/admin/reset", methods=["POST"])
@admin_required
def admin_reset():
    old = load_state()
    s = default_state()
    s["title"] = old["title"]
    s["date"] = old["date"]
    s["games"] = old["games"]
    s["slots"] = old["slots"]
    s["kill_points"] = old["kill_points"]
    s["placement_points"] = old["placement_points"]
    s["theme"] = old["theme"]
    s = sanitize(s)
    for i, t in enumerate(old["teams"]):
        if i < len(s["teams"]):
            s["teams"][i]["name"] = t["name"]
            s["teams"][i]["aliases"] = t["aliases"]
            s["teams"][i]["players"] = t.get("players", [""] * 4)
    save_state(s, snap_gap=0)
    return jsonify({"state": s, "standings": compute(s)})


SCAN_PROMPT = (
    "These screenshots are end-of-match result screens from a mobile battle royale custom room (Sausage Man). "
    "Several screenshots may be scrolled to different positions of the SAME results list, so one team can appear "
    "in more than one screenshot. Merge them and list every team exactly once. "
    "LAYOUT: the left column holds the top 3 teams, marked by large text 1st, 2nd, 3rd beside each team box. "
    "The right column holds the lower teams: the final placement of each is the small faded number just above the "
    "top-left of its box, outside the box. Inside every box, the number in the coloured tab at the top-left corner is "
    "the team's lobby slot number and is NOT the placement. Each box lists its players, each with an "
    "'Elimination(s)' count. Some boxes are cut off at the bottom edge of a screenshot: still include them, and if "
    "the same team is shown more completely in another screenshot, use that complete version. "
    "For every team return: rank (integer final placement), lobby_no (integer from the corner tab), "
    "kills (the sum of the Elimination(s) of all its players), players (list of player names exactly as shown, "
    "without the shared team prefix), player_kills (list of integers: each player's Elimination(s) count, in the "
    "same order as players), team_tag (the prefix or tag shared by the players, if any, otherwise an empty string). "
    "Return ONLY a JSON array like "
    '[{"rank":1,"lobby_no":1,"kills":12,"players":["name1","name2"],"player_kills":[7,5],"team_tag":"TAG"}] with no other text.'
)


def norm(text):
    return re.sub(r"[^a-z0-9]+", "", str(text).lower())


def match_rows(rows, state):
    names_by_slot = {}
    for i, t in enumerate(state["teams"]):
        if t["name"].strip():
            names_by_slot[i + 1] = [norm(t["name"])] + [norm(a) for a in t["aliases"]]
    pairs = []
    for ri, row in enumerate(rows):
        seen = [norm(p) for p in row.get("players", [])] + [norm(row.get("team_tag", ""))]
        seen = [x for x in seen if x]
        for slot, cands in names_by_slot.items():
            best = 0.0
            for a in seen:
                for b in cands:
                    if not b:
                        continue
                    sc = difflib.SequenceMatcher(None, a, b).ratio()
                    if len(b) >= 4 and (b in a or a in b):
                        sc = max(sc, 0.9)
                    best = max(best, sc)
            pairs.append((best, ri, slot))
    pairs.sort(reverse=True)
    used_rows, used_slots = set(), set()
    for sc, ri, slot in pairs:
        if sc < 0.75 or ri in used_rows or slot in used_slots:
            continue
        rows[ri]["suggested_slot"] = slot
        rows[ri]["match_confidence"] = round(sc, 3)
        used_rows.add(ri)
        used_slots.add(slot)
    rank_counts = {}
    lobby_counts = {}
    for row in rows:
        row.setdefault("suggested_slot", 0)
        row.setdefault("match_confidence", 0)
        rank = row.get("rank")
        lobby = row.get("lobby_no")
        if rank:
            rank_counts[rank] = rank_counts.get(rank, 0) + 1
        if lobby:
            lobby_counts[lobby] = lobby_counts.get(lobby, 0) + 1
    for row in rows:
        row["duplicate_rank"] = bool(row.get("rank") and rank_counts.get(row["rank"], 0) > 1)
        row["duplicate_lobby"] = bool(row.get("lobby_no") and lobby_counts.get(row["lobby_no"], 0) > 1)
    return rows


class ScanError(Exception):
    def __init__(self, msg, retry=True):
        Exception.__init__(self, msg)
        self.msg = msg
        self.retry = retry


def http_error(provider, status, body):
    msg = "%s error %s: %s" % (provider, status, body[:300])
    # bad key / bad model / bad request will not fix themselves; overload and rate limits will
    retry = status in (408, 429) or status >= 500
    low = body.lower()
    if status == 429 and ("perday" in low or "per day" in low or "limit: 0" in low or "billing" in low and "perminute" not in low):
        # daily quota used up (or no free quota for this model): retrying cannot fix it
        msg = ("Gemini quota used up for this key/model (429). Wait until it resets, use another model in "
               "GEMINI_MODEL, or enable billing in Google AI Studio. Details: " + body[:200])
        retry = False
    return ScanError(msg, retry)


def gemini_post(model, key, parts, think):
    cfg = {"temperature": 0, "maxOutputTokens": 8000}
    if think:
        cfg["thinkingConfig"] = {"thinkingLevel": "low"}
    return requests.post(
        "https://generativelanguage.googleapis.com/v1beta/models/%s:generateContent" % model,
        headers={"x-goog-api-key": key, "content-type": "application/json"},
        json={"contents": [{"parts": parts}], "generationConfig": cfg},
        timeout=75,
    )


def call_gemini_model(model, key, parts):
    try:
        resp = gemini_post(model, key, parts, True)
        # some models reject the thinking setting: retry the same call without it
        if resp.status_code == 400 and "think" in resp.text.lower():
            resp = gemini_post(model, key, parts, False)
    except requests.RequestException as e:
        raise ScanError("Could not reach Gemini: %s" % e, True)
    if resp.status_code != 200:
        err = http_error("Gemini (%s)" % model, resp.status_code, resp.text)
        err.status = resp.status_code
        raise err
    try:
        cands = resp.json().get("candidates") or []
        out = (cands[0].get("content") or {}).get("parts") or []
        return "".join(p.get("text", "") for p in out)
    except (ValueError, IndexError, AttributeError):
        raise ScanError("Gemini returned an unreadable answer", True)


def merge_rows(row_lists):
    """Combine rows from several screenshots; the same team (same lobby number) appears once."""
    merged = []
    by_lobby = {}
    for rows in row_lists:
        for r in rows:
            ln = r.get("lobby_no")
            if ln and ln in by_lobby:
                old = by_lobby[ln]
                # keep the more complete version (more players, then more kills)
                if (len(r["players"]), r["kills"]) > (len(old["players"]), old["kills"]):
                    if not r["rank"]:
                        r["rank"] = old["rank"]
                    old.clear()
                    old.update(r)
                elif not old["rank"] and r["rank"]:
                    old["rank"] = r["rank"]
                continue
            merged.append(r)
            if ln:
                by_lobby[ln] = r
    merged.sort(key=lambda x: (x["rank"] is None, x["rank"] or 0, x["lobby_no"] or 0))
    return merged


def scan_gemini_parallel(images):
    from concurrent.futures import ThreadPoolExecutor
    workers = min(len(images), 2)  # gentle on rate limits
    with ThreadPoolExecutor(max_workers=workers) as ex:
        def one(im):
            # retry each screenshot on its own so one failure doesn't redo the others
            for attempt in range(3):
                try:
                    return parse_rows(call_gemini([im]))
                except ScanError as e:
                    # rate limited: don't hammer, let the page back off and retry
                    if not e.retry or attempt == 2 or "429" in e.msg:
                        raise
                    time.sleep(1 + attempt)
        futures = [ex.submit(one, im) for im in images]
        results, errors = [], []
        for f in futures:
            try:
                results.append(f.result())
            except ScanError as e:
                errors.append(e)
    if not results:
        raise errors[0]
    if errors:
        # one screenshot failed: report it so the page retries the whole batch instead of silently missing teams
        raise errors[0]
    return merge_rows(results)


def call_gemini(images, prompt=None):
    key = getattr(config, "GEMINI_API_KEY", "")
    if not key or key.startswith("PASTE"):
        raise ScanError("Set GEMINI_API_KEY in config.py first", False)
    models = [getattr(config, "GEMINI_MODEL", "gemini-3.8-flash")]
    models += list(getattr(config, "GEMINI_FALLBACK_MODELS", []))
    parts = [{"inline_data": {"mime_type": mt, "data": b64}} for mt, b64 in images]
    parts.append({"text": prompt or SCAN_PROMPT})
    last = None
    started = time.time()
    for m in models:
        if last is not None and time.time() - started > 140:
            break
        try:
            return call_gemini_model(m, key, parts)
        except ScanError as e:
            last = e
            # a wrong key or bad request will fail on every model, so stop right away
            if getattr(e, "status", 0) in (400, 401, 403):
                raise
            # busy (429/5xx), unreachable or model gone (404): try the next model
    raise last


def call_anthropic(images, prompt=None):
    key = getattr(config, "ANTHROPIC_API_KEY", "")
    if not key or key.startswith("PASTE"):
        raise ScanError("Set ANTHROPIC_API_KEY in config.py first", False)
    content = [
        {"type": "image", "source": {"type": "base64", "media_type": mt, "data": b64}}
        for mt, b64 in images
    ]
    content.append({"type": "text", "text": prompt or SCAN_PROMPT})
    try:
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            json={"model": config.AI_MODEL, "max_tokens": 4000, "messages": [{"role": "user", "content": content}]},
            timeout=100,
        )
    except requests.RequestException as e:
        raise ScanError("Could not reach Anthropic: %s" % e, True)
    if resp.status_code != 200:
        raise http_error("Anthropic", resp.status_code, resp.text)
    return "".join(b.get("text", "") for b in resp.json().get("content", []) if b.get("type") == "text")


def parse_rows(text):
    m = re.search(r"\[.*\]", text or "", re.S)
    if not m:
        raise ScanError("AI returned no results", True)
    try:
        raw_rows = json.loads(m.group(0))
    except ValueError:
        raise ScanError("AI answer could not be read", True)
    rows = []
    for r in raw_rows:
        if not isinstance(r, dict):
            continue
        players = [str(p) for p in (r.get("players") or [])][:8]
        raw_pk = r.get("player_kills") if isinstance(r.get("player_kills"), list) else []
        player_kills = [to_int(x) for x in raw_pk][:8]
        if len(player_kills) != len(players):
            player_kills = []  # can't tell which kill belongs to whom
        kills = to_int(r.get("kills")) or 0
        if player_kills and not kills and all(x is not None for x in player_kills):
            kills = sum(player_kills)
        rows.append({
            "rank": to_int(r.get("rank")),
            "kills": kills,
            "lobby_no": to_int(r.get("lobby_no")),
            "players": players,
            "player_kills": player_kills,
            "team_tag": str(r.get("team_tag") or ""),
        })
    if not rows:
        raise ScanError("AI found no teams in the screenshots", True)
    return rows


THEME_PROMPT = (
    "You pick colour themes for an esports scrim leaderboard. The leaderboard is a dark table; the theme is ONE accent colour "
    "that the page turns into a full palette. Suggest 4 different accent colours for this idea: \"%s\". "
    "Each must be a saturated, mid-tone colour (not near black, not near white, not grey). "
    "Return ONLY a JSON array like [{\"name\":\"Crimson Wolf\",\"color\":\"#d02040\"}] with 4 items, "
    "name at most 24 characters, color as #rrggbb, no other text."
)


def parse_theme_options(text):
    m = re.search(r"\[.*\]", text or "", re.S)
    if not m:
        raise ScanError("AI returned no colours", True)
    try:
        raw = json.loads(m.group(0))
    except ValueError:
        raise ScanError("AI answer could not be read", True)
    out = []
    for r in raw if isinstance(raw, list) else []:
        if not isinstance(r, dict):
            continue
        color = str(r.get("color", "")).strip().lower()
        if HEX_RE.match(color):
            out.append({"name": re.sub(r"[<>\"']", "", str(r.get("name", "")))[:24] or color, "color": color})
    if not out:
        raise ScanError("AI returned no usable colours", True)
    return out[:4]


@app.route("/api/admin/theme-ai", methods=["POST"])
@admin_required
def admin_theme_ai():
    data = request.get_json(silent=True) or {}
    idea = re.sub(r"[\r\n\"]+", " ", str(data.get("prompt", ""))).strip()[:120]
    if len(idea) < 3:
        return jsonify(error="Describe the look you want, for example: fire, ocean at night, wolf and moon"), 400
    prompt = THEME_PROMPT % idea
    provider = str(getattr(config, "AI_PROVIDER", "gemini")).lower()
    try:
        text = call_anthropic([], prompt) if provider == "anthropic" else call_gemini([], prompt)
        options = parse_theme_options(text)
    except ScanError as e:
        return jsonify(error=e.msg), 502 if e.retry else 400
    return jsonify(options=options)


def image_extension(head):
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if head.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "webp"
    return None


@app.route("/api/admin/upload-logo", methods=["POST"])
@admin_required
def admin_upload_logo():
    f = request.files.get("file")
    if not f:
        return jsonify(error="Choose a picture first"), 400
    data = f.stream.read(512 * 1024 + 1)
    if len(data) > 512 * 1024:
        return jsonify(error="Picture is too big. Use one under 500 KB."), 400
    ext = image_extension(data[:16])
    if not ext:
        return jsonify(error="Use a PNG, JPG or WEBP picture"), 400
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    name = "%s.%s" % (secrets.token_hex(12), ext)
    with open(os.path.join(UPLOAD_DIR, name), "wb") as out:
        out.write(data)
    audit("Uploaded team logo", name)
    return jsonify(url="/uploads/" + name)


@app.route("/uploads/<name>")
def uploaded_logo(name):
    if not UPLOAD_NAME_RE.match(name):
        abort(404)
    resp = send_from_directory(UPLOAD_DIR, name)
    resp.headers["Cache-Control"] = "public, max-age=86400"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    return resp


@app.route("/api/logo-proxy")
def logo_proxy():
    """Fetch an external team logo on the server so the image download can draw it (browsers block it otherwise)."""
    import socket
    import ipaddress
    from urllib.parse import urlparse
    url = request.args.get("u", "").strip()
    if len(url) > 300 or not url.startswith("https://"):
        abort(400)
    host = urlparse(url).hostname or ""
    try:
        for info in socket.getaddrinfo(host, 443):
            ip = ipaddress.ip_address(info[4][0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
                abort(400)
    except socket.gaierror:
        abort(404)
    try:
        r = requests.get(url, timeout=6, stream=True, allow_redirects=False, headers={"User-Agent": "Mozilla/5.0"})
        ctype = r.headers.get("Content-Type", "").split(";")[0].strip().lower()
        if r.status_code != 200 or ctype not in ("image/png", "image/jpeg", "image/webp", "image/gif"):
            abort(404)
        data = r.raw.read(1024 * 1024 + 1, decode_content=True)
    except requests.RequestException:
        abort(404)
    if len(data) > 1024 * 1024:
        abort(413)
    resp = app.response_class(data, mimetype=ctype)
    resp.headers["Cache-Control"] = "public, max-age=86400"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    return resp


@app.route("/api/admin/paste", methods=["POST"])
@admin_required
def admin_paste():
    """Read a result that was copied from the Gemini app (JSON list) instead of calling the API."""
    data = request.get_json(silent=True) or {}
    try:
        rows = parse_rows(str(data.get("text", "")))
    except ScanError as e:
        return jsonify(error="Could not read the pasted text: %s. Make sure you copied the whole JSON list." % e.msg), 400
    rows = merge_rows([rows])
    rows = match_rows(rows, load_state())
    return jsonify({"rows": rows})


@app.route("/api/admin/scan", methods=["POST"])
@admin_required
def admin_scan():
    files = request.files.getlist("images")
    if not files:
        return jsonify(error="No images uploaded", retry=False), 400
    images = []
    if len(files) > 12:
        return jsonify(error="Upload a maximum of 12 screenshots", retry=False), 400
    for f in files:
        data = f.read(8 * 1024 * 1024 + 1)
        if not data or len(data) > 8 * 1024 * 1024:
            return jsonify(error="Each screenshot must be smaller than 8 MB", retry=False), 400
        mt = f.mimetype
        if mt not in ("image/jpeg", "image/png", "image/webp", "image/gif"):
            return jsonify(error="Only JPG, PNG, WEBP or GIF images are accepted", retry=False), 400
        images.append((mt, base64.b64encode(data).decode("ascii")))
    provider = str(getattr(config, "AI_PROVIDER", "gemini")).lower()
    try:
        if provider == "anthropic":
            rows = parse_rows(call_anthropic(images))
        elif len(images) > 1:
            rows = scan_gemini_parallel(images)
        else:
            rows = parse_rows(call_gemini(images))
    except ScanError as e:
        return jsonify(error=e.msg, retry=e.retry), 502 if e.retry else 400
    rows = match_rows(rows, load_state())
    return jsonify({"rows": rows})

@app.route("/manifest.webmanifest")
def web_manifest():
    return send_from_directory(os.path.join(BASE_DIR, "static"), "manifest.webmanifest",
                               mimetype="application/manifest+json")


@app.route("/sw.js")
def service_worker():
    resp = send_from_directory(os.path.join(BASE_DIR, "static"), "sw.js",
                               mimetype="application/javascript")
    resp.headers["Cache-Control"] = "no-cache"
    return resp

if __name__ == "__main__":
    app.run(debug=False)
