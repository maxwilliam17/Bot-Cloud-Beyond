import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime
import os
import csv
import hashlib
import base64
import json

try:
    from cryptography.fernet import Fernet
    ENCRYPTION_AVAILABLE = True
except ImportError:
    ENCRYPTION_AVAILABLE = False
    print('[FIREBASE] cryptography not installed')


class FirebaseManager:
    _instance = None
    _initialized = False
    _app = None

    ACCOUNTS = "accounts"
    LISTINGS = "marketplace_listings"
    SESSIONS = "posting_sessions"
    COMBINATIONS = "combinations"
    STATS = "stats"
    PHOTOS = "photos"

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if not hasattr(self, 'db'):
            self.db = None
            self.credentials_path = None
            self._encryption_key = None

    def auto_initialize(self):
        if FirebaseManager._initialized and self.db is not None:
            return True
        try:
            base = os.path.dirname(os.path.abspath(__file__))
            paths = [
                os.path.join(base, "data", "firebase_creds.json"),
                os.path.join(base, "firebase_creds.json"),
            ]
            for p in paths:
                if os.path.exists(p) and os.path.getsize(p) > 10:
                    print('[FIREBASE] Auto-init from: ' + p)
                    return self.initialize(p)
            config_path = os.path.join(base, "data", "config.json")
            if os.path.exists(config_path):
                with open(config_path, 'r') as f:
                    config = json.load(f)
                cred_path = config.get("firebase_credentials_path", "")
                if cred_path and os.path.exists(cred_path):
                    print('[FIREBASE] Auto-init from config: ' + cred_path)
                    return self.initialize(cred_path)
            return False
        except Exception as e:
            print('[FIREBASE] Auto-init error: ' + str(e))
            return False

    def initialize(self, credentials_path):
        print('[FIREBASE] initialize() called: ' + str(credentials_path))
        try:
            if FirebaseManager._initialized and self.db is not None:
                print('[FIREBASE] Already initialized')
                return True
            if not credentials_path:
                print('[FIREBASE] ERROR: No path given')
                return False
            if not os.path.exists(credentials_path):
                print('[FIREBASE] ERROR: File not found: ' + credentials_path)
                return False
            file_size = os.path.getsize(credentials_path)
            print('[FIREBASE] File size: ' + str(file_size) + ' bytes')
            if file_size < 10:
                print('[FIREBASE] ERROR: File too small')
                return False
            try:
                with open(credentials_path, 'r') as f:
                    cred_data = json.load(f)
                print('[FIREBASE] Project: ' + str(cred_data.get('project_id', 'unknown')))
                print('[FIREBASE] Type: ' + str(cred_data.get('type', 'unknown')))
            except Exception as e:
                print('[FIREBASE] ERROR: Invalid JSON: ' + str(e))
                return False
            try:
                try:
                    existing_app = firebase_admin.get_app()
                    print('[FIREBASE] App already exists')
                    FirebaseManager._app = existing_app
                except ValueError:
                    print('[FIREBASE] Creating Firebase app...')
                    cred = credentials.Certificate(credentials_path)
                    FirebaseManager._app = firebase_admin.initialize_app(cred)
                    print('[FIREBASE] App created!')
            except Exception as e:
                print('[FIREBASE] ERROR creating app: ' + str(e))
                import traceback
                traceback.print_exc()
                return False
            try:
                print('[FIREBASE] Getting Firestore client...')
                self.db = firestore.client()
                print('[FIREBASE] Firestore client OK')
            except Exception as e:
                print('[FIREBASE] ERROR getting Firestore: ' + str(e))
                import traceback
                traceback.print_exc()
                return False
            self.credentials_path = credentials_path
            FirebaseManager._initialized = True
            self._init_encryption()
            self._init_stats()
            print('[FIREBASE] Initialization COMPLETE!')
            return True
        except Exception as e:
            print('[FIREBASE] CRITICAL ERROR: ' + str(e))
            import traceback
            traceback.print_exc()
            return False

    def is_initialized(self):
        return FirebaseManager._initialized and self.db is not None

    def _init_encryption(self):
        if not ENCRYPTION_AVAILABLE:
            return
        try:
            key_str = 'beyondbot-fixed-encryption-key-2024'
            key_base = hashlib.sha256(key_str.encode()).digest()
            self._encryption_key = base64.urlsafe_b64encode(key_base)
        except Exception as e:
            print('[FIREBASE] Encryption init error: ' + str(e))

    def _encrypt(self, data):
        if not data:
            return ''
        if ENCRYPTION_AVAILABLE and self._encryption_key:
            try:
                f = Fernet(self._encryption_key)
                return f.encrypt(data.encode()).decode()
            except Exception:
                pass
        return data

    def _decrypt(self, data):
        if not data:
            return ''
        if ENCRYPTION_AVAILABLE and self._encryption_key:
            try:
                f = Fernet(self._encryption_key)
                return f.decrypt(data.encode()).decode()
            except Exception:
                pass
        return data

    def _init_stats(self):
        try:
            stats_ref = self.db.collection(self.STATS).document("global")
            if not stats_ref.get().exists:
                stats_ref.set({
                    "total_posts_attempted": 0,
                    "total_posts_success": 0,
                    "total_posts_failed": 0,
                    "total_sessions": 0,
                    "created_at": datetime.now().isoformat(),
                    "last_updated": datetime.now().isoformat()
                })
        except Exception as e:
            print('[FIREBASE] Stats init error: ' + str(e))

    def add_account(self, name, cookies):
        try:
            if not self.is_initialized():
                return False
            encrypted = self._encrypt(cookies)
            doc_ref = self.db.collection(self.ACCOUNTS).document(name)
            doc = doc_ref.get()
            if doc.exists:
                doc_ref.update({
                    "cookies_encrypted": encrypted,
                    "updated_at": datetime.now().isoformat(),
                    "status": "active"
                })
            else:
                doc_ref.set({
                    "name": name,
                    "cookies_encrypted": encrypted,
                    "added_date": datetime.now().isoformat(),
                    "last_used": None,
                    "status": "active",
                    "total_posts": 0,
                    "total_success": 0,
                    "total_failed": 0,
                    "success_rate": 0,
                    "combinations_used": 0,
                    "updated_at": datetime.now().isoformat()
                })
            return True
        except Exception as e:
            print('[FIREBASE] add_account error: ' + str(e))
            return False

    def get_account(self, name):
        try:
            if not self.is_initialized():
                return None
            doc = self.db.collection(self.ACCOUNTS).document(name).get()
            if doc.exists:
                data = doc.to_dict()
                if "cookies_encrypted" in data and data["cookies_encrypted"]:
                    try:
                        data["cookies"] = self._decrypt(data["cookies_encrypted"])
                    except Exception:
                        data["cookies"] = data["cookies_encrypted"]
                elif "cookies" not in data:
                    data["cookies"] = ""
                return data
            return None
        except Exception as e:
            print('[FIREBASE] get_account error: ' + str(e))
            return None

    def get_account_cookies(self, name):
        account = self.get_account(name)
        return account.get("cookies", "") if account else ""

    def get_all_accounts(self):
        try:
            if not self.is_initialized():
                return {}
            accounts = {}
            docs = self.db.collection(self.ACCOUNTS).stream()
            for doc in docs:
                try:
                    data = doc.to_dict()
                    if "cookies_encrypted" in data and data["cookies_encrypted"]:
                        try:
                            data["cookies"] = self._decrypt(data["cookies_encrypted"])
                        except Exception:
                            data["cookies"] = data["cookies_encrypted"]
                    elif "cookies" not in data:
                        data["cookies"] = ""
                    accounts[doc.id] = data
                except Exception as e:
                    print('[FIREBASE] Error reading account ' + doc.id + ': ' + str(e))
                    continue
            print('[FIREBASE] Loaded ' + str(len(accounts)) + ' accounts')
            return accounts
        except Exception as e:
            print('[FIREBASE] get_all_accounts error: ' + str(e))
            return {}

    def get_account_names(self):
        return list(self.get_all_accounts().keys())

    def update_account_cookies(self, name, new_cookies):
        try:
            if not self.is_initialized():
                return False
            encrypted = self._encrypt(new_cookies)
            self.db.collection(self.ACCOUNTS).document(name).update({
                "cookies_encrypted": encrypted,
                "updated_at": datetime.now().isoformat(),
                "status": "active"
            })
            return True
        except Exception as e:
            print('[FIREBASE] update_account_cookies error: ' + str(e))
            return False

    def delete_account(self, name):
        try:
            if not self.is_initialized():
                return False
            self.db.collection(self.ACCOUNTS).document(name).delete()
            try:
                self.db.collection(self.COMBINATIONS).document(name).delete()
            except Exception:
                pass
            return True
        except Exception as e:
            print('[FIREBASE] delete_account error: ' + str(e))
            return False

    def update_last_used(self, name):
        try:
            if not self.is_initialized():
                return
            self.db.collection(self.ACCOUNTS).document(name).update({
                "last_used": datetime.now().isoformat()
            })
        except Exception:
            pass

    def add_posting_session(self, account_name, attempted, success,
                            failed, listings_titles=None, duration=0):
        try:
            if not self.is_initialized():
                return None
            now = datetime.now()
            session_data = {
                "account_name": account_name,
                "timestamp": now.isoformat(),
                "date": now.strftime("%Y-%m-%d"),
                "attempted": attempted,
                "success": success,
                "failed": failed,
                "success_rate": round((success / attempted * 100), 1) if attempted > 0 else 0,
                "listings_titles": (listings_titles or [])[:10],
                "duration_seconds": duration
            }
            self.db.collection(self.SESSIONS).add(session_data)
            stats_ref = self.db.collection(self.STATS).document("global")
            doc = stats_ref.get()
            if doc.exists:
                current = doc.to_dict()
                stats_ref.update({
                    "total_posts_attempted": current.get("total_posts_attempted", 0) + attempted,
                    "total_posts_success": current.get("total_posts_success", 0) + success,
                    "total_posts_failed": current.get("total_posts_failed", 0) + failed,
                    "total_sessions": current.get("total_sessions", 0) + 1,
                    "last_updated": now.isoformat()
                })
            try:
                acc_ref = self.db.collection(self.ACCOUNTS).document(account_name)
                acc_doc = acc_ref.get()
                if acc_doc.exists:
                    data = acc_doc.to_dict()
                    tp = data.get("total_posts", 0) + attempted
                    ts = data.get("total_success", 0) + success
                    acc_ref.update({
                        "total_posts": tp,
                        "total_success": ts,
                        "total_failed": data.get("total_failed", 0) + failed,
                        "success_rate": round((ts / tp * 100), 1) if tp > 0 else 0,
                        "last_used": now.isoformat()
                    })
            except Exception:
                pass
            return True
        except Exception as e:
            print('[FIREBASE] add_posting_session error: ' + str(e))
            return None

    def get_stats_summary(self):
        try:
            if not self.is_initialized():
                return self._empty_stats()
            doc = self.db.collection(self.STATS).document("global").get()
            gs = doc.to_dict() if doc.exists else {}
            total = gs.get("total_posts_attempted", 0)
            rate = round((gs.get("total_posts_success", 0) / total * 100), 1) if total > 0 else 0
            accounts = self.get_all_accounts()
            accs = {}
            for name, data in accounts.items():
                accs[name] = {
                    "total_attempted": data.get("total_posts", 0),
                    "total_success": data.get("total_success", 0),
                    "total_failed": data.get("total_failed", 0)
                }
            recent = []
            try:
                docs = (
                    self.db.collection(self.SESSIONS)
                    .order_by("timestamp", direction=firestore.Query.DESCENDING)
                    .limit(10)
                    .stream()
                )
                for d in docs:
                    dd = d.to_dict()
                    recent.append({
                        "date": dd.get("timestamp", ""),
                        "account": dd.get("account_name", ""),
                        "attempted": dd.get("attempted", 0),
                        "success": dd.get("success", 0),
                        "failed": dd.get("failed", 0)
                    })
            except Exception:
                pass
            return {
                "total_attempted": total,
                "total_success": gs.get("total_posts_success", 0),
                "total_failed": gs.get("total_posts_failed", 0),
                "total_sessions": gs.get("total_sessions", 0),
                "success_rate": rate,
                "today_attempted": 0,
                "today_success": 0,
                "posting_history": recent,
                "accounts_stats": accs
            }
        except Exception as e:
            print('[FIREBASE] get_stats_summary error: ' + str(e))
            return self._empty_stats()

    def _empty_stats(self):
        return {
            "total_attempted": 0, "total_success": 0, "total_failed": 0,
            "total_sessions": 0, "success_rate": 0,
            "today_attempted": 0, "today_success": 0,
            "posting_history": [], "accounts_stats": {}
        }

    def reset_stats(self):
        try:
            if not self.is_initialized():
                return False
            self.db.collection(self.STATS).document("global").set({
                "total_posts_attempted": 0,
                "total_posts_success": 0,
                "total_posts_failed": 0,
                "total_sessions": 0,
                "created_at": datetime.now().isoformat(),
                "last_updated": datetime.now().isoformat()
            })
            return True
        except Exception as e:
            print('[FIREBASE] reset_stats error: ' + str(e))
            return False

    def get_account_combinations(self, account_name):
        try:
            if not self.is_initialized():
                return {"used_keys": [], "total_used": 0}
            doc = self.db.collection(self.COMBINATIONS).document(account_name).get()
            if doc.exists:
                return doc.to_dict()
            return {"used_keys": [], "total_used": 0}
        except Exception as e:
            print('[FIREBASE] get_account_combinations error: ' + str(e))
            return {"used_keys": [], "total_used": 0}

    def save_used_combinations(self, account_name, combinations):
        try:
            if not self.is_initialized():
                return 0
            combo_ref = self.db.collection(self.COMBINATIONS).document(account_name)
            doc = combo_ref.get()
            existing = doc.to_dict().get("used_keys", []) if doc.exists else []
            new_keys = []
            for combo in combinations:
                if not combo.get("is_repeated", False):
                    key = combo.get(
                        "key",
                        str(combo.get('listing_index', 0)) + "_" + str(combo.get('photo_index', 0))
                    )
                    if key not in existing and key not in new_keys:
                        new_keys.append(key)
            if new_keys:
                all_keys = existing + new_keys
                combo_ref.set({
                    "used_keys": all_keys,
                    "total_used": len(all_keys),
                    "last_updated": datetime.now().isoformat()
                })
            return len(new_keys)
        except Exception as e:
            print('[FIREBASE] save_used_combinations error: ' + str(e))
            return 0

    def get_combination_stats(self, account_name, total_listings, total_photos):
        mx = total_listings * total_photos if total_listings > 0 and total_photos > 0 else 0
        combo_data = self.get_account_combinations(account_name)
        used = combo_data.get("total_used", 0)
        avail = max(0, mx - used)
        return {
            "max_combinations": mx,
            "used": used,
            "available": avail,
            "percentage_available": round((avail / mx * 100), 2) if mx > 0 else 0,
            "all_exhausted": avail == 0 and mx > 0
        }

    def reset_account_combinations(self, account_name):
        try:
            if not self.is_initialized():
                return False
            self.db.collection(self.COMBINATIONS).document(account_name).set({
                "used_keys": [],
                "total_used": 0,
                "reset_at": datetime.now().isoformat()
            })
            return True
        except Exception as e:
            print('[FIREBASE] reset_account_combinations error: ' + str(e))
            return False

    def get_all_listings(self):
        try:
            if not self.is_initialized():
                return []
            listings = []
            try:
                docs = self.db.collection(self.LISTINGS).where("active", "==", True).stream()
                for doc in docs:
                    try:
                        data = doc.to_dict()
                        data["id"] = doc.id
                        listings.append(data)
                    except Exception:
                        continue
            except Exception:
                docs = self.db.collection(self.LISTINGS).stream()
                for doc in docs:
                    try:
                        data = doc.to_dict()
                        data["id"] = doc.id
                        listings.append(data)
                    except Exception:
                        continue
            print('[FIREBASE] Loaded ' + str(len(listings)) + ' listings')
            return listings
        except Exception as e:
            print('[FIREBASE] get_all_listings error: ' + str(e))
            return []

    def get_listings_count(self):
        try:
            if not self.is_initialized():
                return 0
            try:
                return sum(1 for _ in self.db.collection(self.LISTINGS).where("active", "==", True).stream())
            except Exception:
                return sum(1 for _ in self.db.collection(self.LISTINGS).stream())
        except Exception:
            return 0

    def upload_from_csv(self, csv_path):
        try:
            listings = []
            for enc in ['utf-8', 'utf-8-sig', 'latin-1', 'cp1252']:
                try:
                    with open(csv_path, 'r', encoding=enc) as f:
                        listings = list(csv.DictReader(f))
                    break
                except UnicodeDecodeError:
                    continue
            success = failed = 0
            for row in listings:
                listing = {
                    'title': row.get('title', '').strip(),
                    'price': row.get('price', '0').strip(),
                    'description': row.get('description', '').strip(),
                    'location': row.get('location', '').strip(),
                    'category': row.get('category', 'Household').strip() or 'Household',
                    'condition': row.get('condition', 'New').strip() or 'New',
                    'active': True,
                    'created_at': datetime.now().isoformat()
                }
                if listing['title']:
                    try:
                        self.db.collection(self.LISTINGS).add(listing)
                        success += 1
                    except Exception:
                        failed += 1
                else:
                    failed += 1
            return (success, failed)
        except Exception as e:
            print('[FIREBASE] upload_from_csv error: ' + str(e))
            return (0, 0)

    def delete_all_listings(self):
        try:
            if not self.is_initialized():
                return 0
            batch = self.db.batch()
            docs = list(self.db.collection(self.LISTINGS).stream())
            count = 0
            for doc in docs:
                batch.delete(doc.reference)
                count += 1
                if count % 400 == 0:
                    batch.commit()
                    batch = self.db.batch()
            if count % 400 != 0:
                batch.commit()
            return count
        except Exception as e:
            print('[FIREBASE] delete_all_listings error: ' + str(e))
            return 0

    def save_photo(self, filename, base64_data):
        try:
            if not self.is_initialized():
                print('[FIREBASE] save_photo: not initialized')
                return False
            if not filename or not base64_data:
                return False
            size_bytes = len(base64_data.encode('utf-8'))
            size_kb = round(size_bytes / 1024, 1)
            if size_bytes > 900 * 1024:
                print('[FIREBASE] save_photo: too large ' + filename + ' (' + str(size_kb) + 'KB)')
                return False
            self.db.collection(self.PHOTOS).document(filename).set({
                "filename": filename,
                "data": base64_data,
                "uploaded_at": datetime.now().isoformat(),
                "size_kb": size_kb
            })
            return True
        except Exception as e:
            print('[FIREBASE] save_photo error for ' + str(filename) + ': ' + str(e))
            return False

    def save_photos_batch(self, photos_dict):
        try:
            if not self.is_initialized():
                return 0
            saved = 0
            for filename, b64data in photos_dict.items():
                if self.save_photo(filename, b64data):
                    saved += 1
            return saved
        except Exception as e:
            print('[FIREBASE] save_photos_batch error: ' + str(e))
            return 0

    def get_all_photos(self):
        try:
            if not self.is_initialized():
                return {}
            photos = {}
            docs = self.db.collection(self.PHOTOS).stream()
            for doc in docs:
                try:
                    data = doc.to_dict()
                    photos[data.get("filename", doc.id)] = data.get("data", "")
                except Exception:
                    continue
            print('[FIREBASE] Loaded ' + str(len(photos)) + ' photos')
            return photos
        except Exception as e:
            print('[FIREBASE] get_all_photos error: ' + str(e))
            return {}

    def get_photos_count(self):
        try:
            if not self.is_initialized():
                return 0
            return sum(1 for _ in self.db.collection(self.PHOTOS).stream())
        except Exception:
            return 0

    def get_photo_names(self):
        try:
            if not self.is_initialized():
                return []
            return [doc.id for doc in self.db.collection(self.PHOTOS).stream()]
        except Exception:
            return []

    def delete_photo(self, filename):
        try:
            if not self.is_initialized():
                return False
            self.db.collection(self.PHOTOS).document(filename).delete()
            return True
        except Exception:
            return False

    def delete_all_photos(self):
        try:
            if not self.is_initialized():
                return 0
            batch = self.db.batch()
            docs = list(self.db.collection(self.PHOTOS).stream())
            count = 0
            for doc in docs:
                batch.delete(doc.reference)
                count += 1
                if count % 400 == 0:
                    batch.commit()
                    batch = self.db.batch()
            if count % 400 != 0:
                batch.commit()
            return count
        except Exception:
            return 0

    def check_migration_needed(self):
        return {"any": False, "accounts": False, "stats": False, "combinations": False}


_firebase_manager = None


def get_firebase_manager():
    global _firebase_manager
    if _firebase_manager is None:
        _firebase_manager = FirebaseManager()
    return _firebase_manager