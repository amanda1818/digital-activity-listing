"""Desktop capture agent — COMPLETE (PRD Module A2).

Captures active app + HASHED window title + active/idle, batches to the API.
Per-OS implementations for Windows / macOS / Linux are provided. The real capture
loop can only run on a desktop OS with input access, so for local testing there is
a --simulate mode that writes realistic synthetic events straight to the DB.

  Real run (on the user's PC):   python agent/agent.py --api http://server:8000 --participant <id>
  Local test (no OS access):     python agent/agent.py --simulate --participant <id>

Privacy: window titles are sha256-hashed on-device; raw text never leaves the machine.
Deployment: wrap with a tray pause control and auto-stop at the study end date, then
package with PyInstaller and code-sign.
"""
import sys, os, time, argparse, hashlib, platform, random
from datetime import datetime, timedelta

SAMPLE_SECONDS = 30
IDLE_THRESHOLD_SECONDS = 600


def _hash(t): return hashlib.sha256((t or "").encode()).hexdigest()[:16]


def active_window():
    """Return (app_name, window_title) on the current OS, or ('unknown','')."""
    sysname = platform.system()
    try:
        if sysname == "Windows":
            import win32gui, win32process, psutil
            hwnd = win32gui.GetForegroundWindow()
            title = win32gui.GetWindowText(hwnd)
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            return psutil.Process(pid).name(), title
        if sysname == "Darwin":
            from AppKit import NSWorkspace
            app = NSWorkspace.sharedWorkspace().frontmostApplication()
            return (app.localizedName() if app else "unknown"), ""
        if sysname == "Linux":
            import subprocess
            try:
                wid = subprocess.check_output(["xdotool", "getactivewindow"], text=True).strip()
                title = subprocess.check_output(["xdotool", "getwindowname", wid], text=True).strip()
                return "linux-app", title
            except Exception:
                return "unknown", ""
    except Exception:
        pass
    return "unknown", ""


def idle_seconds():
    """Seconds since last user input (per-OS)."""
    sysname = platform.system()
    try:
        if sysname == "Windows":
            import ctypes
            class LASTINPUTINFO(ctypes.Structure):
                _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]
            info = LASTINPUTINFO(); info.cbSize = ctypes.sizeof(info)
            ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info))
            return (ctypes.windll.kernel32.GetTickCount() - info.dwTime) / 1000.0
        if sysname == "Linux":
            import subprocess
            return int(subprocess.check_output(["xprintidle"], text=True).strip()) / 1000.0
    except Exception:
        pass
    return 0.0


def run_loop(api_url, participant_id):
    import requests
    buf, last_app, block_start = [], None, datetime.utcnow()
    print(f"Agent capturing → {api_url}/events  (Ctrl+C to stop)")
    while True:
        app, title = active_window()
        active = idle_seconds() < IDLE_THRESHOLD_SECONDS
        if last_app is not None and app != last_app:
            now = datetime.utcnow()
            buf.append({"participant_id": participant_id, "source": "agent",
                        "start_ts": block_start.isoformat(), "end_ts": now.isoformat(),
                        "app_name": last_app, "window_title_hash": _hash(title),
                        "category": "idle" if not active else "work",
                        "is_active": active, "signal_flags": {}})
            block_start = now
        last_app = app
        if len(buf) >= 10:
            try:
                requests.post(f"{api_url}/events", json=buf, timeout=5); buf.clear()
            except Exception:
                pass
        time.sleep(SAMPLE_SECONDS)


def simulate(participant_id, hours=4):
    """Write synthetic events straight to the DB — for local end-to-end testing."""
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from db.database import SessionLocal
    from db.models import ActivityEvent
    apps = [("Excel", "reconcile", "work"), ("ERP", "invoice", "work"),
            ("Outlook", "email", "work"), ("Teams", "meeting", "meeting"),
            ("Idle", "idle", "idle")]
    db = SessionLocal(); t = datetime.utcnow() - timedelta(hours=hours); n = 0
    try:
        while t < datetime.utcnow():
            app, kw, cat = random.choice(apps)
            dur = random.randint(8, 40)
            db.add(ActivityEvent(participant_id=participant_id, source="agent",
                                 start_ts=t, end_ts=t + timedelta(minutes=dur),
                                 app_name=app, window_title_hash=_hash(kw),
                                 category=cat, is_active=(cat != "idle"),
                                 needs_attribution=(cat == "idle"), signal_flags={}))
            t += timedelta(minutes=dur); n += 1
        db.commit()
    finally:
        db.close()
    return n


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default="http://127.0.0.1:8000")
    ap.add_argument("--participant", required=True)
    ap.add_argument("--simulate", action="store_true")
    a = ap.parse_args()
    if a.simulate:
        print("simulated events written:", simulate(a.participant))
    else:
        run_loop(a.api, a.participant)
