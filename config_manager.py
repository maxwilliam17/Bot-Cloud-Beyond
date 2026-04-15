import json
import os
from datetime import datetime, timedelta

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, 'data')
os.makedirs(DATA_DIR, exist_ok=True)

CONFIG_FILE = os.path.join(DATA_DIR, "config.json")
ACCOUNTS_FILE = os.path.join(DATA_DIR, "accounts.json")
STATS_FILE = os.path.join(DATA_DIR, "stats.json")

DEFAULT_CONFIG = {
    "selected_account": "",
    "default_location": "Laval, Quebec",
    "listings_csv_file": "",
    "firebase_credentials_path": "",
    "firebase_credentials_content": "",
    "firebase_enabled": False,
    "first_time_setup_done": False,
    "advanced_settings": {
        "min_delay": 10,
        "max_delay": 20,
        "randomize_order": False,
        "stealth_mode": True,
        "headless_mode": True
    }
}

DEFAULT_STATS = {
    "total_posts_attempted": 0,
    "total_posts_success": 0,
    "total_posts_failed": 0,
    "total_sessions": 0,
    "first_post_date": None,
    "last_post_date": None,
    "accounts_stats": {},
    "posting_history": [],
    "daily_stats": {}
}


def _read(path, default):
    try:
        if os.path.exists(path):
            with open(path, 'r') as f:
                data = json.load(f)
            result = default.copy()
            result.update(data)
            return result
    except Exception:
        pass
    return default.copy()


def _write(path, data):
    try:
        with open(path, 'w') as f:
            json.dump(data, f, indent=2)
        return True
    except Exception:
        return False


def load_config():
    return _read(CONFIG_FILE, DEFAULT_CONFIG)


def save_config(config):
    return _write(CONFIG_FILE, config)


def is_setup_done():
    config = load_config()
    return config.get("first_time_setup_done", False)


def load_accounts():
    return _read(ACCOUNTS_FILE, {})


def save_accounts(accounts):
    return _write(ACCOUNTS_FILE, accounts)


def add_account(name, cookies):
    accs = _read(ACCOUNTS_FILE, {})
    accs[name] = {
        "cookies": cookies,
        "added_date": datetime.now().isoformat(),
        "last_used": None
    }
    return _write(ACCOUNTS_FILE, accs)


def delete_account(name):
    accs = _read(ACCOUNTS_FILE, {})
    if name in accs:
        del accs[name]
        _write(ACCOUNTS_FILE, accs)
    return True


def get_account_cookies(name):
    accs = _read(ACCOUNTS_FILE, {})
    return accs.get(name, {}).get("cookies", "")


def get_account_names():
    return list(_read(ACCOUNTS_FILE, {}).keys())


def update_account_cookies(name, new_cookies):
    accs = _read(ACCOUNTS_FILE, {})
    if name in accs:
        accs[name]["cookies"] = new_cookies
        accs[name]["updated_date"] = datetime.now().isoformat()
        _write(ACCOUNTS_FILE, accs)
    return True


def update_last_used(name):
    accs = _read(ACCOUNTS_FILE, {})
    if name in accs:
        accs[name]["last_used"] = datetime.now().isoformat()
        _write(ACCOUNTS_FILE, accs)


def load_stats():
    return _read(STATS_FILE, DEFAULT_STATS)


def save_stats(stats):
    return _write(STATS_FILE, stats)


def add_posting_session(account_name, total, success, failed, titles=None):
    s = _read(STATS_FILE, DEFAULT_STATS)
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")
    s["total_posts_attempted"] = s.get("total_posts_attempted", 0) + total
    s["total_posts_success"] = s.get("total_posts_success", 0) + success
    s["total_posts_failed"] = s.get("total_posts_failed", 0) + failed
    s["total_sessions"] = s.get("total_sessions", 0) + 1
    if not s.get("first_post_date"):
        s["first_post_date"] = now.isoformat()
    s["last_post_date"] = now.isoformat()
    ds = s.setdefault("daily_stats", {})
    day = ds.setdefault(today, {"attempted": 0, "success": 0, "failed": 0})
    day["attempted"] += total
    day["success"] += success
    day["failed"] += failed
    ac = s.setdefault("accounts_stats", {})
    a = ac.setdefault(account_name, {"total_attempted": 0, "total_success": 0, "total_failed": 0, "sessions": 0})
    a["total_attempted"] += total
    a["total_success"] += success
    a["total_failed"] += failed
    a["sessions"] = a.get("sessions", 0) + 1
    a["last_used"] = now.isoformat()
    hist = s.setdefault("posting_history", [])
    hist.insert(0, {"date": now.isoformat(), "account": account_name, "attempted": total, "success": success, "failed": failed, "titles": (titles or [])[:5]})
    s["posting_history"] = hist[:50]
    _write(STATS_FILE, s)
    return s


def get_stats_summary():
    s = _read(STATS_FILE, DEFAULT_STATS)
    t = s.get("total_posts_attempted", 0)
    rate = round(s.get("total_posts_success", 0) / t * 100, 1) if t > 0 else 0
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")
    daily = s.get("daily_stats", {})
    td = daily.get(today, {})
    wa = ws = 0
    for i in range(7):
        d = (now - timedelta(days=i)).strftime("%Y-%m-%d")
        if d in daily:
            wa += daily[d].get("attempted", 0)
            ws += daily[d].get("success", 0)
    accs = s.get("accounts_stats", {})
    best = None
    best_rate = 0
    for n, st in accs.items():
        if st.get("total_attempted", 0) > 0:
            r = st["total_success"] / st["total_attempted"] * 100
            if r > best_rate:
                best_rate = r
                best = n
    return {
        "total_attempted": t,
        "total_success": s.get("total_posts_success", 0),
        "total_failed": s.get("total_posts_failed", 0),
        "total_sessions": s.get("total_sessions", 0),
        "success_rate": rate,
        "today_attempted": td.get("attempted", 0),
        "today_success": td.get("success", 0),
        "week_attempted": wa,
        "week_success": ws,
        "best_account": best,
        "best_account_rate": round(best_rate, 1),
        "posting_history": s.get("posting_history", [])[:10],
        "accounts_stats": accs
    }


def get_account_stats(name):
    summary = get_stats_summary()
    return summary.get("accounts_stats", {}).get(name, {})


def reset_stats():
    _write(STATS_FILE, DEFAULT_STATS.copy())
    return True