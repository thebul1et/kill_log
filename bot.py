#!/usr/bin/env python3
"""Rob Run death logger: reads the killer's name + ID off your death screen
(screen capture, on this PC only) and shows a kill log page on this PC.

Run:  python bot.py --calibrate   (once, while the death screen is showing)
      python bot.py               (normal use)
"""
import argparse, json, os, re, sqlite3, subprocess, sys, threading, time, webbrowser
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import requests
from PIL import Image

# Windows log files default to a codec that can't print emoji or progress bars.
for _out in (sys.stdout, sys.stderr):
    try:
        _out.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

HERE = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))  # bundled read-only files
if getattr(sys, "frozen", False) and os.environ.get("APPDATA"):
    DATA = Path(os.environ["APPDATA"]) / "RobRunDeathLog"      # your settings + saved deaths
else:
    DATA = Path(__file__).parent
DATA.mkdir(parents=True, exist_ok=True)
CFG_PATH = DATA / "config.json"
if not CFG_PATH.exists():
    CFG_PATH.write_text((HERE / "config.json").read_text(encoding="utf-8"), encoding="utf-8")
CFG = json.loads(CFG_PATH.read_text(encoding="utf-8"))
DB_PATH = DATA / "deaths.db"
log = print  # the desktop app swaps this for its own log window
DB = sqlite3.connect(DB_PATH, check_same_thread=False)  # the app logs from a worker thread
DB.execute("""CREATE TABLE IF NOT EXISTS deaths (
    id INTEGER PRIMARY KEY, killer_name TEXT, killer_id TEXT,
    died_at TEXT, posted INTEGER DEFAULT 0, kind TEXT DEFAULT 'kill')""")
if "kind" not in [r[1] for r in DB.execute("PRAGMA table_info(deaths)")]:
    DB.execute("ALTER TABLE deaths ADD COLUMN kind TEXT DEFAULT 'kill'")  # older database
DB.commit()

_reader = None


def grab():
    """Return a picture of your screen (the monitor set in config.json)."""
    import mss
    with mss.mss() as sct:
        shot = sct.grab(sct.monitors[CFG.get("monitor", 1)])
        return Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")


def _read_text(arr):
    """Read all text in an image. Uses RapidOCR (small, fast); falls back to EasyOCR if installed."""
    global _reader
    if _reader is None:
        try:
            from rapidocr_onnxruntime import RapidOCR
            _reader = ("rapid", RapidOCR())
        except ImportError:
            import easyocr
            _reader = ("easy", easyocr.Reader(["en"], gpu=False, verbose=False))
    kind, engine = _reader
    if kind == "rapid":
        found, _ = engine(arr)
        found = sorted(found or [], key=lambda r: (round(r[0][0][1] / 20), r[0][0][0]))  # top-to-bottom
        return " ".join(r[1] for r in found)
    return " ".join(engine.readtext(arr, detail=0))


def ocr(img):
    """Crop to the configured region and read the text. Returns (crop, text)."""
    w, h = img.size
    x, y, rw, rh = CFG["region"]
    crop = img.crop((int(x * w), int(y * h), int((x + rw) * w), int((y + rh) * h)))
    if crop.width < 700:  # only enlarge small crops; 1440p crops are already big
        crop = crop.resize((crop.width * 2, crop.height * 2))
    return crop, _read_text(np.array(crop))


def parse(text):
    """Return (name, id) if the text looks like a kill/arrest screen, else None.
    The ID can be blank when the screen only shows a player name."""
    words = CFG.get("trigger_words") or []
    if words and not any(t.lower() in text.lower() for t in words):
        return None
    if not CFG.get("log_arrests", True) and "arrested by" in text.lower():
        return None  # arrests switched off in config.json
    for pat in CFG.get("patterns") or [CFG["pattern"]]:
        m = re.search(pat, text, re.I | re.S)
        if m:
            g = m.groupdict()
            if g.get("name"):
                return g["name"], (g.get("id") or "")
    return None


def flush():
    """Send any deaths that haven't reached the site yet (skipped if no endpoint is set)."""
    if not CFG.get("endpoint"):
        return
    rows = DB.execute("SELECT id, killer_name, killer_id, died_at FROM deaths WHERE posted=0").fetchall()
    for rid, name, kid, ts in rows:
        try:
            r = requests.post(
                CFG["endpoint"],
                json={"killer_name": name, "killer_id": kid, "time": ts},
                headers={"Authorization": f"Bearer {CFG['api_key']}"},
                timeout=10)
            r.raise_for_status()
            DB.execute("UPDATE deaths SET posted=1 WHERE id=?", (rid,))
            DB.commit()
        except Exception as e:
            log(f"  (couldn't post yet, will retry: {e})")
            break


def record(name, kid, kind="kill"):
    ts = datetime.now(timezone.utc).isoformat()
    DB.execute("INSERT INTO deaths (killer_name, killer_id, died_at, kind) VALUES (?,?,?,?)",
               (name, kid, ts, kind))
    DB.commit()
    total = DB.execute("SELECT COUNT(*) FROM deaths").fetchone()[0]
    who_col, who_val = ("killer_id", kid) if kid else ("killer_name", name)
    by = DB.execute(f"SELECT COUNT(*) FROM deaths WHERE {who_col}=? AND kind=?", (who_val, kind)).fetchone()[0]
    who = f"{name} (ID {kid})" if kid else name
    verb = "Arrested" if kind == "arrest" else "Eliminated"
    log(f"💀 {verb} by {who} - {by}x by them, {total} total")
    flush()


LOCAL_DEFAULT = {"enabled": True, "port": 8765}


def _local_json(limit):
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    try:
        recent = [dict(r) for r in con.execute(
            "SELECT killer_name, killer_id, died_at FROM deaths ORDER BY id DESC LIMIT ?", (limit,))]
        players = [dict(r) for r in con.execute(
            "SELECT MAX(killer_name) AS killer_name, MAX(killer_id) AS killer_id, "
            "SUM(CASE WHEN kind = 'arrest' THEN 0 ELSE 1 END) AS kills, "
            "SUM(CASE WHEN kind = 'arrest' THEN 1 ELSE 0 END) AS arrests, "
            "MIN(died_at) AS first_seen, MAX(died_at) AS last_seen FROM deaths "
            "GROUP BY COALESCE(NULLIF(killer_id, ''), killer_name) ORDER BY kills DESC, arrests DESC LIMIT 300")]
        total = con.execute("SELECT COUNT(*) FROM deaths").fetchone()[0]
    finally:
        con.close()
    return {"total": total, "recent": recent, "players": players, "nemesis": players[:10]}


def start_local_page():
    """Serve the kill log on this computer only (127.0.0.1), no password needed."""
    opts = {**LOCAL_DEFAULT, **(CFG.get("local_page") or {})}
    if not opts["enabled"]:
        return None
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from urllib.parse import parse_qs, urlparse

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _send(self, code, body, ctype):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            host = (self.headers.get("Host") or "").rsplit(":", 1)[0]
            if host not in ("127.0.0.1", "localhost"):  # blocks DNS-rebinding tricks
                return self._send(403, b"forbidden", "text/plain")
            url = urlparse(self.path)
            if url.path == "/api/deaths":
                try:
                    limit = min(max(int(parse_qs(url.query).get("limit", ["50"])[0]), 1), 1000)
                except ValueError:
                    limit = 50
                return self._send(200, json.dumps(_local_json(limit)).encode(), "application/json")
            if url.path in ("/", "/killlog"):
                try:
                    html = (HERE / "killlog.html").read_text(encoding="utf-8")
                except OSError:
                    return self._send(500, b"killlog.html is missing from the folder", "text/plain")
                html = re.sub(r'const ENDPOINT = "[^"]*";', 'const ENDPOINT = "/api/deaths?limit=1000";', html)
                html = html.replace("const NO_LOGIN = false;", "const NO_LOGIN = true;")
                return self._send(200, html.encode("utf-8"), "text/html; charset=utf-8")
            self._send(404, b"not found", "text/plain")

    try:
        server = ThreadingHTTPServer(("127.0.0.1", opts["port"]), Handler)
    except OSError as exc:
        log(f"Local kill log couldn't start on port {opts['port']}: {exc}")
        return None
    threading.Thread(target=server.serve_forever, daemon=True).start()
    log(f"Kill log (opens on this computer only): http://127.0.0.1:{opts['port']}")
    return server


_game = {"checked": 0.0, "running": True}


def game_running():
    """True if Rob Run is running (checked every 5s). If game_process is blank, always True."""
    name = (CFG.get("game_process") or "").strip().lower()
    if not name:
        return True
    if time.time() - _game["checked"] < 5:
        return _game["running"]
    _game["checked"] = time.time()
    try:
        out = subprocess.run(["tasklist"], capture_output=True, text=True,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout.lower()
        _game["running"] = name in out
    except Exception:
        _game["running"] = True  # can't check, so don't block
    return _game["running"]


def selftest():
    """Build check: draw a fake elimination screen, read it back, and parse it. Returns 0 if it works."""
    from PIL import ImageDraw, ImageFont
    img = Image.new("RGB", (1920, 1080), (0, 0, 0))
    d = ImageDraw.Draw(img)
    try:
        font = ImageFont.load_default(size=34)
    except TypeError:
        font = ImageFont.load_default()
    d.text((320, 400), "You have been eliminated. Bag contents and", fill=(235, 235, 235), font=font)
    d.text((320, 450), "equipment have been lost.", fill=(235, 235, 235), font=font)
    d.text((320, 500), "[Tag] ExampleName [1234567890]", fill=(255, 77, 94), font=font)
    saved = CFG["region"]
    CFG["region"] = [0.1, 0.35, 0.8, 0.3]
    try:
        _, text = ocr(img)
    finally:
        CFG["region"] = saved
    hit = parse(text)
    ok = bool(hit and hit[0] == "ExampleName" and hit[1] == "1234567890")
    msg = f"selftest {'OK' if ok else 'FAILED'}: read={text!r} parsed={hit}"
    try:
        (DATA / "selftest.txt").write_text(msg, encoding="utf-8")
    except OSError:
        pass
    log(msg)
    return 0 if ok else 1


def calibrate():
    img = grab()
    crop, text = ocr(img)
    img.save(DATA / "calibrate_frame.png")
    crop.save(DATA / "calibrate_crop.png")
    print("Saved calibrate_frame.png and calibrate_crop.png")
    print("OCR read:", repr(text))
    print("Parsed:  ", parse(text))
    print("\nIf the crop doesn't contain the killer's name/ID, change 'region' in config.json.")
    print("If the text is right but Parsed is None, adjust 'pattern'.")


def run(debug=False, stop=None, on_game=None, open_page=True):
    server = start_local_page()
    if open_page and server and (CFG.get("local_page") or {}).get("open_browser", True):
        webbrowser.open("http://127.0.0.1:%s" % server.server_address[1])
    try:  # warn early if the capture is a black picture
        if np.array(grab()).mean() < 3:
            log("WARNING: your screen capture looks black. Set Rob Run to Borderless / "
                  "Windowed Fullscreen (not exclusive Fullscreen) and restart this.")
    except Exception as exc:
        log("WARNING: couldn't capture the screen:", exc)
    log("Watching for deaths... (Ctrl+C to stop)")
    need = CFG.get("confirm_reads", 2)  # same killer must be read this many times in a row
    last_seen, streak, last_logged = None, 0, 0
    was_running = None
    while not (stop and stop.is_set()):
        try:
            running = game_running()
            if running != was_running:
                log("Rob Run detected - watching." if running else "Rob Run isn't running - paused.")
                was_running = running
                if on_game:
                    on_game(running)
            if not running:
                last_seen, streak = None, 0
                time.sleep(2)
                continue
            crop, text = ocr(grab())
            hit = parse(text)
            if debug:
                crop.save(DATA / "debug_last.png")
                log(f"read: {text!r} -> {hit}")
            streak = (streak + 1 if hit == last_seen else 1) if hit else 0
            last_seen = hit
            if hit and streak >= need and time.time() - last_logged > CFG["cooldown"]:
                log(f"  matched text: {text!r}")
                record(*hit, "arrest" if "arrested by" in text.lower() else "kill")
                last_logged = time.time()
        except KeyboardInterrupt:
            break
        except Exception as e:
            log("error:", e)
            time.sleep(2)
        time.sleep(CFG["interval"])


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--calibrate", action="store_true")
    ap.add_argument("--debug", action="store_true", help="print what is read every cycle")
    args = ap.parse_args()
    calibrate() if args.calibrate else run(args.debug)
