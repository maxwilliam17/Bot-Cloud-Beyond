import os
import json
import threading
import random
import base64
from datetime import datetime
from functools import wraps
from flask import Flask, render_template, request, jsonify, redirect, session
from flask_cors import CORS
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = os.environ.get('FLASK_SECRET', 'beyondbot-2024')
CORS(app)

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, 'data')
UPLOADS = os.path.join(BASE, 'uploads')
PHOTOS = os.path.join(BASE, 'photos')
for _d in [DATA, UPLOADS, PHOTOS]:
    os.makedirs(_d, exist_ok=True)

BOT_PASSWORD = os.environ.get('BOT_PASSWORD', 'admin123')

CFG_F = os.path.join(DATA, 'config.json')
ACC_F = os.path.join(DATA, 'accounts.json')
STAT_F = os.path.join(DATA, 'stats.json')
COMBO_F = os.path.join(DATA, 'combos.json')
LIST_F = os.path.join(DATA, 'listings.json')

DEF_CFG = {
    'selected_account': '',
    'default_location': 'Laval, Quebec',
    'listings_csv_file': '',
    'firebase_credentials_path': '',
    'firebase_credentials_content': '',
    'firebase_enabled': False,
    'advanced_settings': {
        'min_delay': 10, 'max_delay': 20,
        'randomize_order': False,
        'stealth_mode': True,
        'headless_mode': True
    }
}

DEF_STAT = {
    'total_posts_attempted': 0,
    'total_posts_success': 0,
    'total_posts_failed': 0,
    'total_sessions': 0,
    'accounts_stats': {},
    'posting_history': [],
    'daily_stats': {}
}

firebase = None
firebase_ready = False
fb_lock = threading.Lock()

bot_state = {
    'is_running': False, 'progress': 0, 'total': 0,
    'completed': 0, 'success': 0, 'failed': 0,
    'current_listing': '', 'last_run': None,
    'account': '', 'error': None,
    'pending_combinations': [],
}

import builtins as _builtins
_REAL_PRINT = _builtins.print

LOG_FILE = os.path.join(DATA, 'bot_logs.json')


def write_log(message, level='info'):
    try:
        entry = {
            'time': datetime.now().strftime('%H:%M:%S'),
            'message': str(message),
            'level': level
        }
        logs = []
        if os.path.exists(LOG_FILE):
            try:
                with open(LOG_FILE, 'r') as f:
                    logs = json.load(f)
            except Exception:
                logs = []
        logs.append(entry)
        if len(logs) > 300:
            logs = logs[-300:]
        with open(LOG_FILE, 'w') as f:
            json.dump(logs, f)
        _REAL_PRINT('[' + level.upper() + '] ' + str(message))
    except Exception as e:
        _REAL_PRINT('[LOG_ERROR] ' + str(e))


def read_logs(since=0):
    try:
        if os.path.exists(LOG_FILE):
            with open(LOG_FILE, 'r') as f:
                logs = json.load(f)
            return logs[since:], len(logs)
    except Exception:
        pass
    return [], 0


def clear_logs():
    try:
        with open(LOG_FILE, 'w') as f:
            json.dump([], f)
    except Exception:
        pass


def rj(path, default):
    try:
        if os.path.exists(path):
            with open(path, 'r') as f:
                d = json.load(f)
            if isinstance(default, dict):
                r = default.copy()
                r.update(d)
                return r
            return d
    except Exception:
        pass
    return default.copy() if isinstance(default, dict) else default


def wj(path, data):
    try:
        with open(path, 'w') as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        _REAL_PRINT('[JSON] Write error: ' + str(e))


def login_required(f):
    @wraps(f)
    def dec(*args, **kwargs):
        if not session.get('logged_in'):
            if request.path.startswith('/api/') or request.path.startswith('/test'):
                return jsonify({'error': 'Not logged in'}), 401
            return redirect('/login')
        return f(*args, **kwargs)
    return dec


def get_photos():
    exts = ('.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp')
    result = []
    if os.path.exists(PHOTOS):
        for f in sorted(os.listdir(PHOTOS)):
            if f.lower().endswith(exts):
                result.append(os.path.join(PHOTOS, f))
    return result


def get_listings():
    cached = rj(LIST_F, [])
    if cached:
        return cached, 'firebase'
    cfg = rj(CFG_F, DEF_CFG)
    csv_file = cfg.get('listings_csv_file', '')
    if csv_file and os.path.exists(csv_file):
        import csv
        listings = []
        for enc in ['utf-8', 'utf-8-sig', 'latin-1']:
            try:
                with open(csv_file, 'r', encoding=enc) as f:
                    for row in csv.DictReader(f):
                        item = {
                            'title': row.get('title', '').strip(),
                            'description': row.get('description', '').strip(),
                            'price': row.get('price', '0').strip(),
                            'location': row.get('location', '').strip(),
                            'category': row.get('category', 'Household').strip() or 'Household',
                            'condition': row.get('condition', 'New').strip() or 'New'
                        }
                        if item['title']:
                            listings.append(item)
                break
            except UnicodeDecodeError:
                continue
        if listings:
            return listings, 'csv'
    return [], 'none'


def update_progress(current, total, title=''):
    bot_state['completed'] = current
    bot_state['total'] = total
    bot_state['progress'] = int(current / total * 100) if total > 0 else 0
    bot_state['current_listing'] = title


def save_session(account, total, ok, failed):
    s = rj(STAT_F, DEF_STAT)
    now = datetime.now()
    today = now.strftime('%Y-%m-%d')
    s['total_posts_attempted'] = s.get('total_posts_attempted', 0) + total
    s['total_posts_success'] = s.get('total_posts_success', 0) + ok
    s['total_posts_failed'] = s.get('total_posts_failed', 0) + failed
    s['total_sessions'] = s.get('total_sessions', 0) + 1
    ds = s.setdefault('daily_stats', {})
    day = ds.setdefault(today, {'attempted': 0, 'success': 0, 'failed': 0})
    day['attempted'] += total
    day['success'] += ok
    day['failed'] += failed
    ac = s.setdefault('accounts_stats', {})
    a = ac.setdefault(account, {'total_attempted': 0, 'total_success': 0, 'total_failed': 0})
    a['total_attempted'] += total
    a['total_success'] += ok
    a['total_failed'] += failed
    hist = s.setdefault('posting_history', [])
    hist.insert(0, {'date': now.isoformat(), 'account': account, 'attempted': total, 'success': ok, 'failed': failed})
    s['posting_history'] = hist[:50]
    wj(STAT_F, s)


def run_bot_thread(bot_data):
    account = bot_data['account_name']
    combos = bot_data.get('combinations', [])
    total = len(bot_data['listings'])

    bot_state.update({
        'is_running': True, 'progress': 0, 'total': total,
        'completed': 0, 'success': 0, 'failed': 0,
        'account': account, 'error': None, 'current_listing': ''
    })

    write_log('=== BOT STARTED === Account: ' + account + ' | Listings: ' + str(total), 'success')
    write_log('Cookies: ' + str(len(bot_data.get('cookie_string', ''))) + ' chars', 'info')
    write_log('Photos: ' + str(sum(len(l.get('images', [])) for l in bot_data['listings'])), 'info')

    def cap(*args, **kw):
        try:
            msg = ' '.join(str(a) for a in args)
            if msg.strip():
                try:
                    entry = {
                        'time': datetime.now().strftime('%H:%M:%S'),
                        'message': msg,
                        'level': 'info'
                    }
                    logs = []
                    if os.path.exists(LOG_FILE):
                        try:
                            with open(LOG_FILE, 'r') as lf:
                                logs = json.load(lf)
                        except Exception:
                            logs = []
                    logs.append(entry)
                    if len(logs) > 300:
                        logs = logs[-300:]
                    with open(LOG_FILE, 'w') as lf:
                        json.dump(logs, lf)
                except Exception:
                    pass
        except Exception:
            pass
        _REAL_PRINT(*args, **kw)

    _builtins.print = cap

    try:
        write_log('Importing bot_engine...', 'info')
        import bot_engine
        write_log('bot_engine OK. Starting Chrome...', 'success')

        results = bot_engine.run_facebook_bot_multiple(
            bot_data,
            progress_callback=update_progress
        )

        write_log('Bot finished. Results: ' + str(len(results)), 'info')

        ok = sum(1 for r in results if r.get('status') == 'success')
        fail = total - ok

        # Save stats locally
        save_session(account, total, ok, fail)
        write_log('Stats saved locally', 'info')

        # Save stats to Firebase
        if firebase_ready:
            try:
                firebase.add_posting_session(account, total, ok, fail)
                write_log('Stats saved to Firebase', 'success')
            except Exception as e:
                write_log('Firebase stats error: ' + str(e), 'warning')

        # Save used combinations
        if combos:
            new_keys = []
            for i, r in enumerate(results):
                if r.get('status') == 'success' and i < len(combos):
                    if not combos[i].get('is_repeated'):
                        new_keys.append(combos[i]['key'])

            if new_keys:
                write_log('Saving ' + str(len(new_keys)) + ' used combinations...', 'info')

                # Save locally
                d = rj(COMBO_F, {'accounts': {}})
                accs_combo = d.setdefault('accounts', {})
                acc_combo = accs_combo.setdefault(account, {'used_keys': [], 'total_used': 0})
                existing = set(acc_combo.get('used_keys', []))
                existing.update(new_keys)
                acc_combo['used_keys'] = list(existing)
                acc_combo['total_used'] = len(existing)
                wj(COMBO_F, d)
                write_log('Combinations saved locally: ' + str(len(existing)) + ' total', 'success')

                # Save to Firebase
                if firebase_ready:
                    try:
                        combos_to_save = []
                        for k in new_keys:
                            parts = k.split('_')
                            combos_to_save.append({
                                'key': k,
                                'listing_index': int(parts[0]),
                                'photo_index': int(parts[1]),
                                'is_repeated': False
                            })
                        firebase.save_used_combinations(account, combos_to_save)
                        write_log('Combinations saved to Firebase', 'success')
                    except Exception as e:
                        write_log('Firebase combos error: ' + str(e), 'warning')
            else:
                write_log('No successful unique combinations to save', 'info')

        bot_state['success'] = ok
        bot_state['failed'] = fail
        bot_state['progress'] = 100
        bot_state['last_run'] = datetime.now().isoformat()
        write_log('=== DONE: ' + str(ok) + '/' + str(total) + ' successful ===', 'success')

    except Exception as e:
        write_log('BOT ERROR: ' + str(e), 'error')
        import traceback
        write_log(traceback.format_exc()[:500], 'error')
        bot_state['error'] = str(e)
    finally:
        _builtins.print = _REAL_PRINT
        bot_state['is_running'] = False
        bot_state['current_listing'] = ''
        bot_state['pending_combinations'] = []
        write_log('Bot thread ended', 'info')


def init_firebase_bg():
    global firebase, firebase_ready
    try:
        cred_path = os.path.join(DATA, 'firebase_creds.json')
        cred_json = os.environ.get('FIREBASE_CREDENTIALS', '')
        if cred_json and cred_json.strip().startswith('{'):
            with open(cred_path, 'w') as f:
                f.write(cred_json.strip())
        if not os.path.exists(cred_path) or os.path.getsize(cred_path) < 10:
            cfg = rj(CFG_F, DEF_CFG)
            saved = cfg.get('firebase_credentials_content', '')
            if saved and saved.strip().startswith('{'):
                with open(cred_path, 'w') as f:
                    f.write(saved)
        if os.path.exists(cred_path) and os.path.getsize(cred_path) > 10:
            from firebase_manager import get_firebase_manager
            fb = get_firebase_manager()
            if fb.initialize(cred_path):
                with fb_lock:
                    firebase = fb
                    firebase_ready = True
                cfg = rj(CFG_F, DEF_CFG)
                cfg['firebase_enabled'] = True
                cfg['firebase_credentials_path'] = cred_path
                wj(CFG_F, cfg)
                write_log('Firebase connected!', 'success')
                # Sync accounts
                try:
                    accs = fb.get_all_accounts()
                    if accs:
                        wj(ACC_F, accs)
                        write_log('Synced ' + str(len(accs)) + ' accounts', 'success')
                except Exception:
                    pass
                # Sync listings
                try:
                    items = fb.get_all_listings()
                    if items:
                        listings = [{'title': x.get('title', ''), 'description': x.get('description', ''), 'price': x.get('price', '0'), 'location': x.get('location', ''), 'category': x.get('category', 'Household'), 'condition': x.get('condition', 'New')} for x in items]
                        wj(LIST_F, listings)
                        write_log('Synced ' + str(len(listings)) + ' listings', 'success')
                except Exception:
                    pass
                # Sync photos
                try:
                    existing = get_photos()
                    if not existing:
                        fb_photos = fb.get_all_photos()
                        if fb_photos:
                            restored = 0
                            os.makedirs(PHOTOS, exist_ok=True)
                            for fname, b64 in fb_photos.items():
                                try:
                                    fp = os.path.join(PHOTOS, fname)
                                    if not os.path.exists(fp):
                                        with open(fp, 'wb') as pf:
                                            pf.write(base64.b64decode(b64))
                                        restored += 1
                                except Exception:
                                    pass
                            write_log('Restored ' + str(restored) + ' photos', 'success')
                except Exception:
                    pass
                # Sync stats from Firebase
                try:
                    fb_stats = fb.get_stats_summary()
                    if fb_stats and fb_stats.get('total_attempted', 0) > 0:
                        local_stats = {
                            'total_posts_attempted': fb_stats.get('total_attempted', 0),
                            'total_posts_success': fb_stats.get('total_success', 0),
                            'total_posts_failed': fb_stats.get('total_failed', 0),
                            'total_sessions': fb_stats.get('total_sessions', 0),
                            'accounts_stats': fb_stats.get('accounts_stats', {}),
                            'posting_history': fb_stats.get('posting_history', []),
                            'daily_stats': {}
                        }
                        wj(STAT_F, local_stats)
                        write_log('Stats synced from Firebase: ' + str(fb_stats.get('total_attempted', 0)) + ' total posts', 'success')
                except Exception as e:
                    write_log('Stats sync error: ' + str(e), 'warning')
                # Sync combinations from Firebase
                try:
                    accs_list = list(rj(ACC_F, {}).keys())
                    if accs_list:
                        combos_data = {'accounts': {}}
                        for acc_name in accs_list:
                            try:
                                combo_data = fb.get_account_combinations(acc_name)
                                if combo_data and combo_data.get('used_keys'):
                                    combos_data['accounts'][acc_name] = {
                                        'used_keys': combo_data.get('used_keys', []),
                                        'total_used': combo_data.get('total_used', 0)
                                    }
                            except Exception:
                                pass
                        wj(COMBO_F, combos_data)
                        total_combos = sum(len(v.get('used_keys', [])) for v in combos_data['accounts'].values())
                        write_log('Combinations synced from Firebase: ' + str(total_combos) + ' used keys', 'success')
                except Exception as e:
                    write_log('Combos sync error: ' + str(e), 'warning')
                write_log('Firebase sync complete!', 'success')
                return True
    except Exception as e:
        _REAL_PRINT('[FIREBASE] Error: ' + str(e))
    return False


@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        if request.form.get('password', '') == BOT_PASSWORD:
            session['logged_in'] = True
            return redirect('/')
        error = 'Wrong password!'
    return render_template('dashboard.html', page='login', error=error)


@app.route('/logout')
def logout():
    session.clear()
    return redirect('/login')


@app.route('/')
@login_required
def index():
    return render_template('dashboard.html', page='dashboard')


@app.route('/health')
def health():
    return jsonify({
        'status': 'alive',
        'running': bot_state['is_running'],
        'firebase': firebase_ready,
        'accounts': len(rj(ACC_F, {})),
        'listings': len(rj(LIST_F, [])),
        'photos': len(get_photos())
    })


@app.route('/ping')
def ping():
    return 'pong', 200


@app.route('/test-chrome')
@login_required
def test_chrome():
    write_log('Chrome test starting...', 'info')
    result = {'chrome': False, 'error': None, 'details': []}
    for p in ['/usr/bin/google-chrome-stable', '/usr/bin/google-chrome']:
        result['details'].append(p + ': ' + str(os.path.exists(p)))
    for p in ['/usr/local/bin/chromedriver']:
        result['details'].append(p + ': ' + str(os.path.exists(p)))
    try:
        import bot_engine
        d = bot_engine.setup_driver()
        result['chrome'] = True
        d.get('https://www.google.com')
        import time
        time.sleep(2)
        result['details'].append('Page: ' + d.title)
        write_log('Chrome test PASSED: ' + d.title, 'success')
        d.quit()
    except Exception as e:
        result['error'] = str(e)
        write_log('Chrome test FAILED: ' + str(e), 'error')
    return jsonify(result)


@app.route('/api/status')
@login_required
def api_status():
    return jsonify({
        'is_running': bot_state['is_running'],
        'progress': bot_state['progress'],
        'total': bot_state['total'],
        'completed': bot_state['completed'],
        'success': bot_state['success'],
        'failed': bot_state['failed'],
        'current_listing': bot_state['current_listing'],
        'account': bot_state['account'],
        'error': bot_state['error'],
        'last_run': bot_state['last_run'],
    })


@app.route('/api/logs')
@login_required
def api_logs():
    since = request.args.get('since', 0, type=int)
    logs, total = read_logs(since)
    return jsonify({'logs': logs, 'total': total})


@app.route('/api/logs/clear', methods=['POST'])
@login_required
def api_clear_logs():
    clear_logs()
    return jsonify({'success': True})


@app.route('/api/stats')
@login_required
def api_stats():
    s = rj(STAT_F, DEF_STAT)
    # If local stats empty but Firebase ready, try Firebase
    if s.get('total_posts_attempted', 0) == 0 and firebase_ready:
        try:
            fb_stats = firebase.get_stats_summary()
            if fb_stats and fb_stats.get('total_attempted', 0) > 0:
                return jsonify({
                    'total_attempted': fb_stats.get('total_attempted', 0),
                    'total_success': fb_stats.get('total_success', 0),
                    'total_failed': fb_stats.get('total_failed', 0),
                    'success_rate': fb_stats.get('success_rate', 0),
                    'today_success': fb_stats.get('today_success', 0),
                    'today_attempted': fb_stats.get('today_attempted', 0),
                    'posting_history': fb_stats.get('posting_history', [])[:10],
                    'accounts_stats': fb_stats.get('accounts_stats', {})
                })
        except Exception:
            pass
    t = s.get('total_posts_attempted', 0)
    rate = round(s.get('total_posts_success', 0) / t * 100, 1) if t > 0 else 0
    today = datetime.now().strftime('%Y-%m-%d')
    td = s.get('daily_stats', {}).get(today, {})
    return jsonify({
        'total_attempted': t,
        'total_success': s.get('total_posts_success', 0),
        'total_failed': s.get('total_posts_failed', 0),
        'success_rate': rate,
        'today_success': td.get('success', 0),
        'today_attempted': td.get('attempted', 0),
        'posting_history': s.get('posting_history', [])[:10],
        'accounts_stats': s.get('accounts_stats', {})
    })


@app.route('/api/stats/reset', methods=['POST'])
@login_required
def api_reset_stats():
    wj(STAT_F, DEF_STAT.copy())
    if firebase_ready:
        try:
            firebase.reset_stats()
        except Exception:
            pass
    write_log('Stats reset', 'warning')
    return jsonify({'success': True})


@app.route('/api/firebase/status')
@login_required
def api_fb_status():
    return jsonify({
        'connected': firebase_ready,
        'listings': len(rj(LIST_F, [])),
        'accounts': len(rj(ACC_F, {})),
        'photos': len(get_photos())
    })


@app.route('/api/firebase/upload', methods=['POST'])
@login_required
def api_fb_upload():
    global firebase, firebase_ready
    if 'file' not in request.files:
        return jsonify({'error': 'No file'}), 400
    f = request.files['file']
    if not f.filename or not f.filename.endswith('.json'):
        return jsonify({'error': 'JSON required'}), 400
    fp = os.path.join(DATA, 'firebase_creds.json')
    try:
        f.save(fp)
        with open(fp, 'r') as rf:
            cred = json.load(rf)
        cfg = rj(CFG_F, DEF_CFG)
        cfg['firebase_credentials_path'] = fp
        cfg['firebase_credentials_content'] = json.dumps(cred)
        wj(CFG_F, cfg)
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    firebase = None
    firebase_ready = False
    try:
        from firebase_manager import FirebaseManager
        FirebaseManager._initialized = False
        FirebaseManager._instance = None
        FirebaseManager._app = None
        import firebase_admin
        for n in list(firebase_admin._apps.keys()):
            firebase_admin.delete_app(firebase_admin.get_app(n))
    except Exception:
        pass
    threading.Thread(target=init_firebase_bg, daemon=True).start()
    return jsonify({'success': True, 'message': 'Connecting...'})


@app.route('/api/accounts')
@login_required
def api_accounts():
    accs = rj(ACC_F, {})
    cfg = rj(CFG_F, DEF_CFG)
    sel = cfg.get('selected_account', '')
    listings, _ = get_listings()
    photos = get_photos()
    result = []
    for name, data in accs.items():
        cs = {}
        if listings and photos:
            try:
                d = rj(COMBO_F, {'accounts': {}})
                used = len(d.get('accounts', {}).get(name, {}).get('used_keys', []))
                mx = len(listings) * len(photos)
                avail = max(0, mx - used)
                cs = {'available': avail, 'used': used, 'max_combinations': mx, 'percentage_available': round(avail / mx * 100, 1) if mx > 0 else 0, 'all_exhausted': avail == 0 and mx > 0}
            except Exception:
                pass
        result.append({
            'name': name,
            'added_date': data.get('added_date', ''),
            'last_used': data.get('last_used', ''),
            'status': data.get('status', 'active'),
            'selected': name == sel,
            'cookies_length': len(data.get('cookies', '') or ''),
            'combinations': cs
        })
    return jsonify({'accounts': result, 'selected': sel, 'source': 'firebase' if firebase_ready else 'local', 'count': len(result)})


@app.route('/api/accounts', methods=['POST'])
@login_required
def api_add_acc():
    data = request.get_json() or {}
    name = data.get('name', '').strip()
    cookies = data.get('cookies', '').strip()
    if not name:
        return jsonify({'error': 'Name required'}), 400
    if len(cookies) < 50:
        return jsonify({'error': 'Cookies too short'}), 400
    accs = rj(ACC_F, {})
    accs[name] = {'cookies': cookies, 'added_date': datetime.now().isoformat(), 'last_used': None, 'status': 'active'}
    wj(ACC_F, accs)
    if firebase_ready:
        threading.Thread(target=lambda: firebase.add_account(name, cookies), daemon=True).start()
    write_log('Account added: ' + name, 'success')
    return jsonify({'success': True})


@app.route('/api/accounts/<name>', methods=['DELETE'])
@login_required
def api_del_acc(name):
    accs = rj(ACC_F, {})
    if name in accs:
        del accs[name]
        wj(ACC_F, accs)
    d = rj(COMBO_F, {'accounts': {}})
    if name in d.get('accounts', {}):
        d['accounts'][name] = {'used_keys': [], 'total_used': 0}
        wj(COMBO_F, d)
    cfg = rj(CFG_F, DEF_CFG)
    if cfg.get('selected_account') == name:
        cfg['selected_account'] = ''
        wj(CFG_F, cfg)
        bot_state['account'] = ''
    if firebase_ready:
        threading.Thread(target=lambda: firebase.delete_account(name), daemon=True).start()
    write_log('Deleted: ' + name, 'warning')
    return jsonify({'success': True})


@app.route('/api/accounts/<name>/select', methods=['POST'])
@login_required
def api_sel_acc(name):
    accs = rj(ACC_F, {})
    if name not in accs:
        return jsonify({'error': 'Not found'}), 404
    cookies = accs[name].get('cookies', '')
    if not cookies:
        return jsonify({'error': 'No cookies'}), 400
    cfg = rj(CFG_F, DEF_CFG)
    cfg['selected_account'] = name
    wj(CFG_F, cfg)
    accs[name]['last_used'] = datetime.now().isoformat()
    wj(ACC_F, accs)
    bot_state['account'] = name
    write_log('Selected: ' + name + ' (' + str(len(cookies)) + ' chars)', 'success')
    return jsonify({'success': True, 'account': name})


@app.route('/api/accounts/<name>/cookies', methods=['GET'])
@login_required
def api_get_cookies(name):
    accs = rj(ACC_F, {})
    cookies = accs.get(name, {}).get('cookies', '')
    return jsonify({'name': name, 'cookies': cookies, 'length': len(cookies)})


@app.route('/api/accounts/<name>/cookies', methods=['PUT'])
@login_required
def api_upd_cookies(name):
    data = request.get_json() or {}
    cookies = data.get('cookies', '').strip()
    if len(cookies) < 50:
        return jsonify({'error': 'Too short'}), 400
    accs = rj(ACC_F, {})
    if name in accs:
        accs[name]['cookies'] = cookies
        accs[name]['updated'] = datetime.now().isoformat()
        wj(ACC_F, accs)
    if firebase_ready:
        threading.Thread(target=lambda: firebase.update_account_cookies(name, cookies), daemon=True).start()
    write_log('Cookies updated: ' + name, 'success')
    return jsonify({'success': True})


@app.route('/api/accounts/<name>/reset-combos', methods=['POST'])
@login_required
def api_reset_combos(name):
    d = rj(COMBO_F, {'accounts': {}})
    if name in d.get('accounts', {}):
        d['accounts'][name] = {'used_keys': [], 'total_used': 0}
        wj(COMBO_F, d)
    if firebase_ready:
        threading.Thread(target=lambda: firebase.reset_account_combinations(name), daemon=True).start()
    write_log('Combos reset: ' + name, 'info')
    return jsonify({'success': True})


@app.route('/api/accounts/<name>/test', methods=['POST'])
@login_required
def api_test_acc(name):
    accs = rj(ACC_F, {})
    cookies = accs.get(name, {}).get('cookies', '')
    if not cookies:
        return jsonify({'error': 'No cookies'}), 404
    try:
        import bot_engine
        result = bot_engine.check_account_health(cookies)
        write_log('Health ' + name + ': ' + result.get('status', '?'), 'info')
        return jsonify(result)
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})


@app.route('/api/listings/info')
@login_required
def api_listings_info():
    listings, source = get_listings()
    return jsonify({'loaded': len(listings) > 0, 'count': len(listings), 'source': source, 'firebase': firebase_ready, 'preview': listings[:3]})


@app.route('/api/csv/upload', methods=['POST'])
@login_required
def api_csv_upload():
    if 'file' not in request.files:
        return jsonify({'error': 'No file'}), 400
    f = request.files['file']
    if not f.filename or not f.filename.endswith('.csv'):
        return jsonify({'error': 'CSV only'}), 400
    fn = secure_filename(f.filename)
    fp = os.path.join(UPLOADS, fn)
    f.save(fp)
    import csv
    listings = []
    for enc in ['utf-8', 'utf-8-sig', 'latin-1']:
        try:
            with open(fp, 'r', encoding=enc) as cf:
                for row in csv.DictReader(cf):
                    item = {'title': row.get('title', '').strip(), 'description': row.get('description', '').strip(), 'price': row.get('price', '0').strip(), 'location': row.get('location', '').strip(), 'category': row.get('category', 'Household').strip() or 'Household', 'condition': row.get('condition', 'New').strip() or 'New'}
                    if item['title']:
                        listings.append(item)
            break
        except UnicodeDecodeError:
            continue
    if not listings:
        os.remove(fp)
        return jsonify({'error': 'No valid listings'}), 400
    cfg = rj(CFG_F, DEF_CFG)
    cfg['listings_csv_file'] = fp
    wj(CFG_F, cfg)
    wj(LIST_F, listings)
    wj(COMBO_F, {'accounts': {}})
    write_log('CSV: ' + str(len(listings)) + ' listings. Combos reset.', 'success')
    if firebase_ready:
        def _sync():
            try:
                firebase.delete_all_listings()
                firebase.upload_from_csv(fp)
                write_log('Firebase listings synced', 'success')
            except Exception as e:
                write_log('Firebase sync error: ' + str(e), 'warning')
        threading.Thread(target=_sync, daemon=True).start()
    return jsonify({'success': True, 'count': len(listings), 'file': fn, 'firebase_synced': firebase_ready})


@app.route('/api/csv/info')
@login_required
def api_csv_info():
    listings, source = get_listings()
    if listings:
        cfg = rj(CFG_F, DEF_CFG)
        return jsonify({'loaded': True, 'file': os.path.basename(cfg.get('listings_csv_file', 'firebase')), 'count': len(listings), 'preview': listings[:3]})
    return jsonify({'loaded': False, 'count': 0})


@app.route('/api/photos/upload', methods=['POST'])
@login_required
def api_photos_upload():
    if 'files' not in request.files:
        return jsonify({'error': 'No files'}), 400
    files = request.files.getlist('files')
    exts = ('.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp')
    saved = 0
    fb_photos = {}
    for f in files:
        if not f.filename or not f.filename.lower().endswith(exts):
            continue
        try:
            fname = secure_filename(f.filename)
            fpath = os.path.join(PHOTOS, fname)
            file_data = f.read()
            if len(file_data) > 500 * 1024:
                try:
                    from PIL import Image
                    import io
                    img = Image.open(io.BytesIO(file_data))
                    if img.mode in ('RGBA', 'P'):
                        img = img.convert('RGB')
                    img.thumbnail((800, 800), Image.LANCZOS)
                    out = io.BytesIO()
                    img.save(out, format='JPEG', quality=75, optimize=True)
                    file_data = out.getvalue()
                    fname = os.path.splitext(fname)[0] + '.jpg'
                    fpath = os.path.join(PHOTOS, fname)
                except Exception:
                    pass
            with open(fpath, 'wb') as pf:
                pf.write(file_data)
            saved += 1
            fb_photos[fname] = base64.b64encode(file_data).decode('utf-8')
            write_log('Saved: ' + fname + ' (' + str(round(len(file_data) / 1024, 1)) + 'KB)', 'info')
        except Exception as e:
            write_log('Photo error: ' + str(e), 'error')
    if firebase_ready and fb_photos:
        def _save():
            import time
            for fn2, b64 in fb_photos.items():
                try:
                    firebase.save_photo(fn2, b64)
                    write_log('Firebase photo saved: ' + fn2, 'success')
                except Exception as e:
                    write_log('Firebase photo error: ' + fn2 + ': ' + str(e), 'warning')
                time.sleep(0.3)
        threading.Thread(target=_save, daemon=True).start()
    write_log(str(saved) + ' photos saved', 'success')
    return jsonify({'success': True, 'count': saved, 'firebase_saving': firebase_ready and len(fb_photos) > 0})


@app.route('/api/photos/info')
@login_required
def api_photos_info():
    photos = get_photos()
    names = [os.path.basename(p) for p in photos]
    return jsonify({'loaded': len(photos) > 0, 'count': len(photos), 'files': names[:20], 'firebase_count': len(photos), 'source': 'local'})


@app.route('/api/photos/<name>', methods=['DELETE'])
@login_required
def api_del_photo(name):
    fp = os.path.join(PHOTOS, secure_filename(name))
    if os.path.exists(fp):
        os.remove(fp)
    if firebase_ready:
        threading.Thread(target=lambda: firebase.delete_photo(name), daemon=True).start()
    return jsonify({'success': True})


@app.route('/api/photos/delete-all', methods=['POST'])
@login_required
def api_del_all_photos():
    deleted = 0
    if os.path.exists(PHOTOS):
        for f in os.listdir(PHOTOS):
            try:
                os.remove(os.path.join(PHOTOS, f))
                deleted += 1
            except Exception:
                pass
    fb_del = 0
    if firebase_ready:
        try:
            fb_del = firebase.delete_all_photos()
        except Exception:
            pass
    write_log('Deleted ' + str(deleted) + ' local + ' + str(fb_del) + ' Firebase photos', 'warning')
    return jsonify({'success': True, 'deleted': deleted, 'firebase_deleted': fb_del})


@app.route('/api/combinations/stats')
@login_required
def api_combo_stats():
    cfg = rj(CFG_F, DEF_CFG)
    account = request.args.get('account', cfg.get('selected_account', ''))
    if not account:
        return jsonify({'error': 'No account'}), 400
    listings, _ = get_listings()
    photos = get_photos()
    d = rj(COMBO_F, {'accounts': {}})
    used = len(d.get('accounts', {}).get(account, {}).get('used_keys', []))
    mx = len(listings) * len(photos)
    avail = max(0, mx - used)
    pct = round(avail / mx * 100, 1) if mx > 0 else 0
    return jsonify({'account': account, 'available': avail, 'used': used, 'max_combinations': mx, 'percentage_available': pct, 'all_exhausted': avail == 0 and mx > 0})


@app.route('/api/combinations/all')
@login_required
def api_all_combos():
    return jsonify({'stats': []})
    
@app.route('/api/overview')
@login_required
def api_overview():
    import datetime as dt
    s = rj(STAT_F, DEF_STAT)
    if s.get('total_posts_attempted', 0) == 0 and firebase_ready:
        try:
            fb_stats = firebase.get_stats_summary()
            if fb_stats and fb_stats.get('total_attempted', 0) > 0:
                s = {
                    'total_posts_attempted': fb_stats.get('total_attempted', 0),
                    'total_posts_success':   fb_stats.get('total_success', 0),
                    'total_posts_failed':    fb_stats.get('total_failed', 0),
                    'total_sessions':        fb_stats.get('total_sessions', 0),
                    'accounts_stats':        fb_stats.get('accounts_stats', {}),
                    'posting_history':       fb_stats.get('posting_history', []),
                    'daily_stats':           {}
                }
        except Exception:
            pass
    t    = s.get('total_posts_attempted', 0)
    ok   = s.get('total_posts_success', 0)
    rate = round(ok / t * 100, 1) if t > 0 else 0
    now  = datetime.now()
    today = now.strftime('%Y-%m-%d')
    daily = s.get('daily_stats', {})
    td    = daily.get(today, {})
    today_ok = td.get('success', 0)
    week_ok = week_total = 0
    for i in range(7):
        d  = (now - dt.timedelta(days=i)).strftime('%Y-%m-%d')
        ds = daily.get(d, {})
        week_ok    += ds.get('success', 0)
        week_total += ds.get('attempted', 0)
    chart_labels = []
    chart_ok     = []
    chart_fail   = []
    for i in range(6, -1, -1):
        d   = (now - dt.timedelta(days=i)).strftime('%Y-%m-%d')
        ds  = daily.get(d, {})
        lbl = (now - dt.timedelta(days=i)).strftime('%b %d')
        chart_labels.append(lbl)
        chart_ok.append(ds.get('success', 0))
        chart_fail.append(ds.get('failed', 0))
    accs     = s.get('accounts_stats', {})
    top_accs = []
    for name, data in accs.items():
        posts = data.get('total_attempted', 0)
        succ  = data.get('total_success', 0)
        r2    = round(succ / posts * 100, 1) if posts > 0 else 0
        top_accs.append({'name': name, 'posts': posts, 'success': succ, 'rate': r2})
    top_accs.sort(key=lambda x: x['posts'], reverse=True)
    history = s.get('posting_history', [])
    return jsonify({
        'total':           t,
        'success':         ok,
        'failed':          t - ok,
        'rate':            rate,
        'today':           today_ok,
        'week_success':    week_ok,
        'week_total':      week_total,
        'chart_labels':    chart_labels,
        'chart_ok':        chart_ok,
        'chart_fail':      chart_fail,
        'top_accounts':    top_accs[:8],
        'recent_sessions': history[:10],
        'updated':         now.strftime('%I:%M:%S %p')
    })


@app.route('/api/sessions')
@login_required
def api_sessions():
    s       = rj(STAT_F, DEF_STAT)
    history = s.get('posting_history', [])
    if not history and firebase_ready:
        try:
            fb_stats = firebase.get_stats_summary()
            history  = fb_stats.get('posting_history', []) if fb_stats else []
        except Exception:
            pass
    return jsonify({'sessions': history[:50]})


@app.route('/api/listings/all')
@login_required
def api_listings_all():
    import datetime as dt
    listings, source = get_listings()
    page  = request.args.get('page', 1, type=int)
    limit = request.args.get('limit', 20, type=int)
    q     = request.args.get('q', '').lower()
    if q:
        listings = [l for l in listings if q in l.get('title', '').lower()]
    total = len(listings)
    start = (page - 1) * limit
    end   = start + limit
    return jsonify({
        'listings': listings[start:end],
        'total':    total,
        'page':     page,
        'pages':    (total + limit - 1) // limit if limit > 0 else 1,
        'source':   source
    })


@app.route('/api/generate', methods=['POST'])
@login_required
def api_generate():
    data = request.get_json() or {}
    count = int(data.get('count', 5))
    account = data.get('account', '').strip()
    location = data.get('location', '').strip()
    if not account:
        cfg = rj(CFG_F, DEF_CFG)
        account = cfg.get('selected_account', '')
    if not account:
        return jsonify({'error': 'No account selected'}), 400
    listings, source = get_listings()
    if not listings:
        return jsonify({'error': 'No listings. Upload CSV.'}), 400
    photos = get_photos()
    if not photos:
        return jsonify({'error': 'No photos. Upload in Data tab.'}), 400
    d = rj(COMBO_F, {'accounts': {}})
    used_keys = set(d.get('accounts', {}).get(account, {}).get('used_keys', []))
    tl = len(listings)
    tp = len(photos)
    mx = tl * tp
    if len(used_keys) >= mx and mx > 0:
        return jsonify({'error': 'All combinations used. Reset combinations.', 'exhausted': True}), 400
    available = []
    for li in range(tl):
        for pi in range(tp):
            key = str(li) + '_' + str(pi)
            if key not in used_keys:
                available.append((li, pi, key))
    random.shuffle(available)
    combos = []
    unique = repeated = 0
    for _ in range(count):
        if available:
            li, pi, key = available.pop()
            listing = listings[li].copy() if isinstance(listings[li], dict) else {'title': str(listings[li])}
            combos.append({'listing_index': li, 'photo_index': pi, 'listing': listing, 'photo': photos[pi], 'is_repeated': False, 'key': key})
            unique += 1
        else:
            li = random.randint(0, tl - 1)
            pi = random.randint(0, tp - 1)
            listing = listings[li].copy() if isinstance(listings[li], dict) else {'title': str(listings[li])}
            combos.append({'listing_index': li, 'photo_index': pi, 'listing': listing, 'photo': photos[pi], 'is_repeated': True, 'key': str(li) + '_' + str(pi)})
            repeated += 1
    cfg = rj(CFG_F, DEF_CFG)
    if not location:
        location = cfg.get('default_location', 'Laval, Quebec')
    preview = []
    for c in combos:
        listing = c['listing']
        if not listing.get('location'):
            listing['location'] = location
        preview.append({'title': listing.get('title', '')[:60], 'price': listing.get('price', '0'), 'category': listing.get('category', 'Household'), 'condition': listing.get('condition', 'New'), 'location': listing.get('location', ''), 'description': listing.get('description', '')[:100], 'photo': os.path.basename(c.get('photo', '')), 'is_repeated': c.get('is_repeated', False), 'key': c.get('key', '')})
    bot_state['pending_combinations'] = combos
    write_log('Generated ' + str(unique) + ' unique' + (' + ' + str(repeated) + ' repeated' if repeated else '') + ' for ' + account, 'success')
    return jsonify({'success': True, 'count': len(combos), 'preview': preview, 'stats': {'unique_generated': unique, 'repeated_generated': repeated}, 'source': source, 'account': account})


@app.route('/api/start', methods=['POST'])
@login_required
def api_start():
    write_log('=== START CALLED ===', 'success')
    if bot_state['is_running']:
        return jsonify({'error': 'Already running!'}), 400
    data = request.get_json() or {}
    account = data.get('account', '').strip()
    location = data.get('location', '').strip()
    if not account:
        cfg = rj(CFG_F, DEF_CFG)
        account = cfg.get('selected_account', '')
    write_log('Account: ' + str(account), 'info')
    if not account:
        return jsonify({'error': 'No account selected!'}), 400
    accs = rj(ACC_F, {})
    cookies = accs.get(account, {}).get('cookies', '')
    write_log('Cookies: ' + str(len(cookies)) + ' chars', 'info')
    if not cookies or len(cookies) < 50:
        return jsonify({'error': 'No valid cookies for "' + account + '"'}), 400
    combos = bot_state.get('pending_combinations', [])
    write_log('Combos: ' + str(len(combos)), 'info')
    if not combos:
        return jsonify({'error': 'Generate first!'}), 400
    cfg = rj(CFG_F, DEF_CFG)
    settings = cfg.get('advanced_settings', DEF_CFG['advanced_settings'])
    if not location:
        location = cfg.get('default_location', 'Laval, Quebec')
    settings['headless_mode'] = True
    settings['stealth_mode'] = True
    listings_data = []
    pf = pm = 0
    for c in combos:
        item = c['listing'].copy()
        photo = c.get('photo', '')
        if not item.get('location'):
            item['location'] = location
        if photo and os.path.exists(photo):
            item['images'] = [photo]
            pf += 1
        else:
            item['images'] = []
            if photo:
                pm += 1
                write_log('Photo missing: ' + str(photo), 'warning')
        listings_data.append(item)
    write_log('Photos OK: ' + str(pf) + ' | Missing: ' + str(pm), 'info')
    bot_data = {
        'cookie_string': cookies,
        'listings': listings_data,
        'advanced_settings': settings,
        'account_name': account,
        'combinations': combos,
    }
    bot_state['account'] = account
    write_log('Starting bot thread...', 'success')
    t = threading.Thread(target=run_bot_thread, args=(bot_data,), daemon=True)
    t.start()
    return jsonify({'success': True, 'count': len(listings_data), 'account': account, 'photos_found': pf, 'photos_missing': pm, 'message': 'Bot started! Watch Logs tab.'})


@app.route('/api/stop', methods=['POST'])
@login_required
def api_stop():
    bot_state['is_running'] = False
    write_log('Stop requested', 'warning')
    return jsonify({'success': True})


@app.route('/api/settings')
@login_required
def api_settings():
    cfg = rj(CFG_F, DEF_CFG)
    return jsonify({'settings': cfg.get('advanced_settings', {}), 'default_location': cfg.get('default_location', 'Laval, Quebec'), 'selected_account': cfg.get('selected_account', '')})


@app.route('/api/settings', methods=['POST'])
@login_required
def api_save_settings():
    data = request.get_json() or {}
    cfg = rj(CFG_F, DEF_CFG)
    if 'settings' in data:
        cur = cfg.get('advanced_settings', {})
        cur.update(data['settings'])
        cfg['advanced_settings'] = cur
    if 'default_location' in data:
        cfg['default_location'] = data['default_location']
    wj(CFG_F, cfg)
    write_log('Settings saved', 'info')
    return jsonify({'success': True})


_REAL_PRINT('Beyond Bot starting...')
write_log('Beyond Bot starting...', 'info')

threading.Thread(target=init_firebase_bg, daemon=True).start()

try:
    _cfg = rj(CFG_F, DEF_CFG)
    if _cfg.get('selected_account'):
        bot_state['account'] = _cfg['selected_account']
        write_log('Account: ' + _cfg['selected_account'], 'info')
except Exception:
    pass

write_log('Ready!', 'success')

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 7860))
    app.run(host='0.0.0.0', port=port, debug=False, threaded=True)