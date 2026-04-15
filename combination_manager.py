import json
import os
import random
import csv
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, 'data')
os.makedirs(DATA_DIR, exist_ok=True)
COMBOS_FILE = os.path.join(DATA_DIR, "combinations.json")


def _fb():
    try:
        from config_manager import load_config
        config = load_config()
        if config.get("firebase_enabled"):
            from firebase_manager import get_firebase_manager
            fb = get_firebase_manager()
            if fb.is_initialized():
                return fb
    except Exception:
        pass
    return None


def _read_combos():
    try:
        if os.path.exists(COMBOS_FILE):
            with open(COMBOS_FILE, 'r') as f:
                return json.load(f)
    except Exception:
        pass
    return {"accounts": {}}


def _write_combos(data):
    try:
        with open(COMBOS_FILE, 'w') as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass


def load_listings_from_csv(csv_file):
    listings = []
    if not csv_file or not os.path.exists(csv_file):
        return listings
    for enc in ['utf-8', 'utf-8-sig', 'latin-1', 'cp1252']:
        try:
            with open(csv_file, 'r', encoding=enc) as f:
                for row in csv.DictReader(f):
                    item = {
                        "title": row.get("title", "").strip(),
                        "description": row.get("description", "").strip(),
                        "price": row.get("price", "0").strip(),
                        "location": row.get("location", "").strip(),
                        "category": row.get("category", "Household").strip() or "Household",
                        "condition": row.get("condition", "New").strip() or "New",
                    }
                    if item["title"]:
                        listings.append(item)
            break
        except UnicodeDecodeError:
            continue
        except Exception:
            break
    return listings


def get_photos_list(photos_folder):
    photos = []
    if not photos_folder or not os.path.exists(photos_folder):
        return photos
    exts = ('.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp')
    for f in sorted(os.listdir(photos_folder)):
        if f.lower().endswith(exts):
            photos.append(os.path.join(photos_folder, f))
    return photos


def get_used_keys(account):
    fb = _fb()
    if fb:
        try:
            data = fb.get_account_combinations(account)
            return set(data.get("used_keys", []))
        except Exception:
            pass
    d = _read_combos()
    return set(d.get("accounts", {}).get(account, {}).get("used_keys", []))


def get_combination_stats(account, total_listings, total_photos):
    fb = _fb()
    if fb:
        try:
            return fb.get_combination_stats(account, total_listings, total_photos)
        except Exception:
            pass
    mx = total_listings * total_photos if total_listings > 0 and total_photos > 0 else 0
    used = len(get_used_keys(account))
    avail = max(0, mx - used)
    return {
        "total_listings": total_listings,
        "total_photos": total_photos,
        "max_combinations": mx,
        "used": used,
        "available": avail,
        "percentage_available": round((avail / mx * 100), 2) if mx > 0 else 0,
        "percentage_used": round((used / mx * 100), 2) if mx > 0 else 0,
        "all_exhausted": avail == 0 and mx > 0
    }


def get_available_combinations_count(account, total_listings, total_photos):
    stats = get_combination_stats(account, total_listings, total_photos)
    return stats["available"]


def generate_unique_combinations(account, listings, photos, count, allow_repeats=True):
    if not listings:
        return [], {"error": "No listings available"}
    if not photos:
        return [], {"error": "No photos available"}
    tl = len(listings)
    tp = len(photos)
    mx = tl * tp
    used = get_used_keys(account)
    available = []
    for li in range(tl):
        for pi in range(tp):
            key = str(li) + "_" + str(pi)
            if key not in used:
                available.append((li, pi, key))
    random.shuffle(available)
    combos = []
    unique = 0
    repeated = 0
    for x in range(count):
        if available:
            li, pi, key = available.pop()
            listing_data = listings[li]
            listing_copy = listing_data.copy() if isinstance(listing_data, dict) else {"title": str(listing_data)}
            combos.append({
                "listing_index": li,
                "photo_index": pi,
                "listing": listing_copy,
                "photo": photos[pi],
                "is_repeated": False,
                "key": key
            })
            unique += 1
        elif allow_repeats:
            li = random.randint(0, tl - 1)
            pi = random.randint(0, tp - 1)
            listing_data = listings[li]
            listing_copy = listing_data.copy() if isinstance(listing_data, dict) else {"title": str(listing_data)}
            combos.append({
                "listing_index": li,
                "photo_index": pi,
                "listing": listing_copy,
                "photo": photos[pi],
                "is_repeated": True,
                "key": str(li) + "_" + str(pi)
            })
            repeated += 1
        else:
            break
    stats = {
        "requested": count,
        "unique_generated": unique,
        "repeated_generated": repeated,
        "total_generated": len(combos),
        "unique_available_after": len(available),
        "max_combinations": mx,
        "all_exhausted": len(available) == 0
    }
    return combos, stats


def save_used_combinations(account, combinations):
    new_keys = []
    for c in combinations:
        if not c.get("is_repeated", False):
            new_keys.append(c.get("key", str(c["listing_index"]) + "_" + str(c["photo_index"])))
    if not new_keys:
        return 0
    fb = _fb()
    if fb:
        try:
            fb.save_used_combinations(account, combinations)
        except Exception:
            pass
    d = _read_combos()
    accs = d.setdefault("accounts", {})
    acc = accs.setdefault(account, {"used_keys": [], "total_used": 0})
    existing = set(acc.get("used_keys", []))
    existing.update(new_keys)
    acc["used_keys"] = list(existing)
    acc["total_used"] = len(existing)
    acc["last_posted"] = datetime.now().isoformat()
    _write_combos(d)
    return len(new_keys)


def reset_account_combinations(account):
    fb = _fb()
    if fb:
        try:
            fb.reset_account_combinations(account)
        except Exception:
            pass
    d = _read_combos()
    if account in d.get("accounts", {}):
        d["accounts"][account] = {"used_keys": [], "total_used": 0}
        _write_combos(d)
    return True


def reset_all_combinations():
    """Reset combinations for ALL accounts."""
    fb = _fb()
    if fb:
        try:
            names = fb.get_account_names()
            for name in names:
                fb.reset_account_combinations(name)
        except Exception:
            pass
    d = _read_combos()
    d["accounts"] = {}
    _write_combos(d)
    print("All combinations reset for all accounts")
    return True


def validate_csv_file(csv_file):
    result = {"valid": False, "rows": 0, "columns": [], "errors": []}
    if not csv_file or not os.path.exists(csv_file):
        result["errors"].append("File not found")
        return result
    try:
        for enc in ['utf-8', 'utf-8-sig', 'latin-1', 'cp1252']:
            try:
                with open(csv_file, 'r', encoding=enc) as f:
                    reader = csv.DictReader(f)
                    result["columns"] = reader.fieldnames or []
                    result["rows"] = sum(1 for x in reader)
                break
            except UnicodeDecodeError:
                continue
        if "title" not in result["columns"]:
            result["errors"].append("Missing 'title' column")
        result["valid"] = len(result["errors"]) == 0
    except Exception as e:
        result["errors"].append(str(e))
    return result


def get_csv_preview(csv_file, limit=5):
    return load_listings_from_csv(csv_file)[:limit]


def get_all_accounts_stats(listings, photos):
    d = _read_combos()
    tl = len(listings)
    tp = len(photos)
    stats = []
    for account in d.get("accounts", {}):
        s = get_combination_stats(account, tl, tp)
        s["account_name"] = account
        stats.append(s)
    return stats