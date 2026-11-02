import os
import re
import json
import base64
import difflib
import time
import threading
from functools import wraps

import requests
from flask import Flask, request, jsonify, session, redirect, url_for, render_template

import config

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(BASE_DIR, "data.json")
LOCK = threading.Lock()

app = Flask(__name__)
app.secret_key = config.SECRET_KEY
app.config["MAX_CONTENT_LENGTH"] = 40 * 1024 * 1024


def blank_result():
    return {"rank": None, "kills": None, "noshow": False, "pk": [None] * 4}


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
    s["kill_points"] = kp if kp is not None else 2
    pp = raw.get("placement_points")
    if isinstance(pp, list):
        s["placement_points"] = [to_num(x) or 0 for x in pp][:30]

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
        teams.append({"name": str(t.get("name", ""))[:40], "aliases": clean[:60], "players": pl})
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
                "pk": pk,
            })
        results.append(row)
    s["results"] = results
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


def load_state(sid=None):
    ensure_store()
    sid = sid if valid_id(sid) else current_id()
    with LOCK:
        try:
            with open(scrim_path(sid), "r", encoding="utf-8") as f:
                return sanitize(json.load(f))
        except (ValueError, OSError):
            return default_state()


def save_state(state, sid=None):
    ensure_store()
    # a brand-new scrim has no file yet, so only the id's shape is checked here
    sid = sid if sid and ID_RE.match(str(sid)) else current_id()
    with LOCK:
        write_json(scrim_path(sid), state)


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
            if not r["noshow"]:
                if r["rank"] and 1 <= r["rank"] <= len(pp):
                    place_pts = pp[r["rank"] - 1]
                kills = r["kills"] or 0
            games.append({
                "rank": r["rank"],
                "kills": kills,
                "place_pts": place_pts,
                "points": place_pts + kills * kp,
                "noshow": r["noshow"],
            })
            total_place += place_pts
            total_kills += kills
        rows.append({
            "slot": i + 1,
            "name": name,
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
        "standings": compute(s),
    })


@app.route("/api/scrims")
def public_scrims():
    return jsonify({
        "current": current_id(),
        "scrims": [{"id": x["id"], "title": x["title"], "date": x["date"]} for x in list_scrims()],
    })


@app.route("/login", methods=["GET", "POST"])
def login():
    error = ""
    if request.method == "POST":
        if request.form.get("password", "") == config.ADMIN_PASSWORD:
            session["admin"] = True
            return redirect(url_for("admin"))
        error = "Wrong password"
    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))


@app.route("/admin")
@admin_required
def admin():
    return render_template("admin.html", scan_prompt=SCAN_PROMPT)


@app.route("/api/admin/state")
@admin_required
def admin_state():
    s = load_state()
    return jsonify({"state": s, "standings": compute(s)})


@app.route("/api/admin/save", methods=["POST"])
@admin_required
def admin_save():
    s = sanitize(request.get_json(silent=True))
    save_state(s)
    return jsonify({"state": s, "standings": compute(s)})


@app.route("/api/admin/scrims")
@admin_required
def admin_scrims():
    return jsonify({"current": current_id(), "scrims": list_scrims()})


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
    else:
        s = default_state()
        for k in ("games", "slots", "kill_points", "placement_points"):
            s[k] = base[k]
    title = str(d.get("title") or "").strip()
    s["title"] = title or (base["title"] + " (copy)" if mode == "all" else "NEW SCRIM")
    s["date"] = str(d.get("date") or "").strip() if mode != "all" or d.get("date") else base["date"]
    s = sanitize(s)
    sid = new_id()
    save_state(s, sid)
    set_current(sid)
    return jsonify({"id": sid, "state": s, "standings": compute(s)})


@app.route("/api/admin/scrims/switch", methods=["POST"])
@admin_required
def admin_scrim_switch():
    sid = (request.get_json(silent=True) or {}).get("id")
    if not valid_id(sid):
        return jsonify(error="That scrim no longer exists"), 404
    set_current(sid)
    s = load_state(sid)
    return jsonify({"id": sid, "state": s, "standings": compute(s)})


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
    if was_current:
        ids = sorted(list_ids(), key=lambda i: os.path.getmtime(scrim_path(i)), reverse=True)
        set_current(ids[0])
    cur = current_id()
    s = load_state(cur)
    return jsonify({"id": cur, "state": s, "standings": compute(s)})


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
    s = sanitize(s)
    for i, t in enumerate(old["teams"]):
        if i < len(s["teams"]):
            s["teams"][i]["name"] = t["name"]
            s["teams"][i]["aliases"] = t["aliases"]
            s["teams"][i]["players"] = t.get("players", [""] * 4)
    save_state(s)
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
    "without the shared team prefix), team_tag (the prefix or tag shared by the players, if any, otherwise an empty string). "
    "Return ONLY a JSON array like "
    '[{"rank":1,"lobby_no":1,"kills":12,"players":["name1","name2"],"team_tag":"TAG"}] with no other text.'
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
        used_rows.add(ri)
        used_slots.add(slot)
    for row in rows:
        row.setdefault("suggested_slot", 0)
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


def call_gemini(images):
    key = getattr(config, "GEMINI_API_KEY", "")
    if not key or key.startswith("PASTE"):
        raise ScanError("Set GEMINI_API_KEY in config.py first", False)
    models = [getattr(config, "GEMINI_MODEL", "gemini-3.8-flash")]
    models += list(getattr(config, "GEMINI_FALLBACK_MODELS", []))
    parts = [{"inline_data": {"mime_type": mt, "data": b64}} for mt, b64 in images]
    parts.append({"text": SCAN_PROMPT})
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


def call_anthropic(images):
    key = getattr(config, "ANTHROPIC_API_KEY", "")
    if not key or key.startswith("PASTE"):
        raise ScanError("Set ANTHROPIC_API_KEY in config.py first", False)
    content = [
        {"type": "image", "source": {"type": "base64", "media_type": mt, "data": b64}}
        for mt, b64 in images
    ]
    content.append({"type": "text", "text": SCAN_PROMPT})
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
        rows.append({
            "rank": to_int(r.get("rank")),
            "kills": to_int(r.get("kills")) or 0,
            "lobby_no": to_int(r.get("lobby_no")),
            "players": [str(p) for p in (r.get("players") or [])][:8],
            "team_tag": str(r.get("team_tag") or ""),
        })
    if not rows:
        raise ScanError("AI found no teams in the screenshots", True)
    return rows


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
    for f in files[:12]:
        data = f.read()
        mt = f.mimetype if f.mimetype in ("image/jpeg", "image/png", "image/webp", "image/gif") else "image/jpeg"
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


if __name__ == "__main__":
    app.run(debug=True)
