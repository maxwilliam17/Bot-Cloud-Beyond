import time
import os
import random
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains
from selenium.common.exceptions import TimeoutException, NoSuchElementException

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def parse_cookies(cookie_str):
    cookies = []
    if not cookie_str:
        print('[COOKIES] Empty cookie string!')
        return cookies
    for item in cookie_str.split(';'):
        if '=' in item:
            name, value = item.strip().split('=', 1)
            cookies.append({
                'name': name.strip(),
                'value': value.strip(),
                'domain': '.facebook.com'
            })
    print('[COOKIES] Parsed ' + str(len(cookies)) + ' cookies')
    return cookies


def safe_click(driver, element):
    try:
        element.click()
        return True
    except Exception:
        pass
    try:
        driver.execute_script('arguments[0].click();', element)
        return True
    except Exception:
        pass
    try:
        ActionChains(driver).move_to_element(element).click().perform()
        return True
    except Exception:
        pass
    return False


def scroll_to(driver, element):
    try:
        driver.execute_script('arguments[0].scrollIntoView({block: "center"});', element)
        time.sleep(0.5)
    except Exception:
        pass


def find_element(driver, xpaths, timeout=10):
    if isinstance(xpaths, str):
        xpaths = [xpaths]
    for xpath in xpaths:
        try:
            return WebDriverWait(driver, timeout).until(
                EC.presence_of_element_located((By.XPATH, xpath))
            )
        except Exception:
            continue
    return None


def find_clickable(driver, xpaths, timeout=10):
    if isinstance(xpaths, str):
        xpaths = [xpaths]
    for xpath in xpaths:
        try:
            return WebDriverWait(driver, timeout).until(
                EC.element_to_be_clickable((By.XPATH, xpath))
            )
        except Exception:
            continue
    return None


def type_slow(element, text, delay=0.05):
    for char in text:
        element.send_keys(char)
        time.sleep(delay)


def setup_driver(settings=None):
    if settings is None:
        settings = {}
    print('[BROWSER] Setting up Chrome...')
    options = Options()
    options.add_argument('--headless=new')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-gpu')
    options.add_argument('--disable-software-rasterizer')
    options.add_argument('--disable-setuid-sandbox')
    options.add_argument('--single-process')
    options.add_argument('--no-zygote')
    options.add_argument('--window-size=1920,1080')
    options.add_argument('--disable-extensions')
    options.add_argument('--disable-background-timer-throttling')
    options.add_argument('--disable-backgrounding-occluded-windows')
    options.add_argument('--disable-renderer-backgrounding')
    options.add_argument('--js-flags=--max-old-space-size=512')
    options.add_argument('--log-level=3')
    options.add_argument('--silent')
    options.add_argument('--disable-blink-features=AutomationControlled')
    options.add_experimental_option('excludeSwitches', ['enable-automation', 'enable-logging'])
    options.add_experimental_option('useAutomationExtension', False)
    options.add_argument(
        'user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/120.0.0.0 Safari/537.36'
    )
    print('[BROWSER] Stealth mode enabled')
    chrome_bin = os.environ.get('CHROME_BIN', '')
    if chrome_bin and os.path.exists(chrome_bin):
        options.binary_location = chrome_bin
    else:
        for p in ['/usr/bin/google-chrome-stable', '/usr/bin/google-chrome']:
            if os.path.exists(p):
                options.binary_location = p
                print('[BROWSER] Chrome: ' + p)
                break
    service = None
    for p in ['/usr/local/bin/chromedriver', '/usr/bin/chromedriver']:
        if os.path.exists(p):
            service = Service(executable_path=p)
            print('[BROWSER] ChromeDriver: ' + p)
            break
    if service is None:
        try:
            from webdriver_manager.chrome import ChromeDriverManager
            service = Service(ChromeDriverManager().install())
        except Exception:
            service = Service()
    driver = webdriver.Chrome(service=service, options=options)
    driver.set_page_load_timeout(60)
    try:
        driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
            'source': "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
        })
    except Exception:
        pass
    print('[BROWSER] Chrome ready!')
    return driver


def check_account_health(cookie_string, headless=True):
    print('[HEALTH] Starting...')
    driver = None
    try:
        driver = setup_driver()
        driver.get('https://www.facebook.com')
        time.sleep(2)
        for c in parse_cookies(cookie_string):
            try:
                driver.add_cookie(c)
            except Exception:
                pass
        driver.refresh()
        time.sleep(4)
        url = driver.current_url.lower()
        if 'login' in url or 'checkpoint' in url:
            return {'status': 'invalid', 'logged_in': False, 'marketplace_access': False, 'account_name': None}
        driver.get('https://www.facebook.com/marketplace')
        time.sleep(3)
        url = driver.current_url.lower()
        ok = 'marketplace' in url and 'login' not in url
        return {
            'status': 'healthy' if ok else 'limited',
            'logged_in': True,
            'marketplace_access': ok,
            'account_name': 'Verified'
        }
    except Exception as e:
        return {'status': 'error', 'logged_in': False, 'marketplace_access': False, 'account_name': None}
    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass


def post_single_listing(driver, wait, listing, num, settings):
    print('\n' + '=' * 60)
    print('[LISTING #' + str(num) + '] ' + str(listing.get('title', ''))[:45])
    print('[LISTING #' + str(num) + '] $' + str(listing.get('price', '0')) + ' | ' + str(listing.get('category', 'Household')))
    print('[LISTING #' + str(num) + '] Images: ' + str(len(listing.get('images', []))))
    print('=' * 60)
    try:
        print('[LISTING #' + str(num) + '] Opening Marketplace...')
        driver.get('https://www.facebook.com/marketplace/create/item')
        time.sleep(random.uniform(4, 6))
        if 'login' in driver.current_url.lower():
            print('[LISTING #' + str(num) + '] Not logged in!')
            return {'status': 'failed', 'title': listing.get('title', ''), 'error': 'Login required'}

        # 1. IMAGE
        if listing.get('images'):
            print('[LISTING #' + str(num) + '] Uploading image...')
            try:
                valid = [os.path.abspath(img) for img in listing['images'] if img and os.path.exists(img)]
                if valid:
                    fi = driver.find_element(By.XPATH, "//input[@type='file']")
                    fi.send_keys('\n'.join(valid))
                    time.sleep(3)
                    print('[LISTING #' + str(num) + '] Image OK')
                else:
                    print('[LISTING #' + str(num) + '] No valid images')
            except Exception as e:
                print('[LISTING #' + str(num) + '] Image error: ' + str(e)[:30])
        time.sleep(1)

        # 2. TITLE
        print('[LISTING #' + str(num) + '] Title...')
        try:
            el = find_clickable(driver, [
                "//label[@aria-label='Title']//input",
                "//span[text()='Title']/ancestor::label//input",
                "//input[contains(@aria-label, 'Title')]",
            ], 10)
            if el:
                el.clear()
                time.sleep(0.2)
                type_slow(el, listing.get('title', ''), 0.03)
                print('[LISTING #' + str(num) + '] Title OK')
            else:
                print('[LISTING #' + str(num) + '] Title NOT FOUND')
        except Exception as e:
            print('[LISTING #' + str(num) + '] Title error: ' + str(e)[:30])
        time.sleep(0.5)

        # 3. PRICE
        print('[LISTING #' + str(num) + '] Price...')
        try:
            el = find_element(driver, [
                "//label[@aria-label='Price']//input",
                "//span[text()='Price']/ancestor::label//input",
            ], 8)
            if el:
                el.clear()
                el.send_keys(str(listing.get('price', '0')))
                print('[LISTING #' + str(num) + '] Price OK')
        except Exception as e:
            print('[LISTING #' + str(num) + '] Price error: ' + str(e)[:30])
        time.sleep(0.5)

        # 4. CATEGORY
        category = listing.get('category', 'Household')
        print('[LISTING #' + str(num) + '] Category: ' + category)
        try:
            dd = find_clickable(driver, [
                "//label[@aria-label='Category']",
                "//span[text()='Category']/ancestor::label",
            ], 5)
            if dd:
                scroll_to(driver, dd)
                safe_click(driver, dd)
                time.sleep(1.5)
                opt = find_clickable(driver, [
                    "//span[text()='" + category + "']",
                    "//div[@role='option']//span[text()='" + category + "']",
                    "//span[text()='Household']",
                ], 5)
                if opt:
                    safe_click(driver, opt)
                    print('[LISTING #' + str(num) + '] Category OK')
        except Exception as e:
            print('[LISTING #' + str(num) + '] Category error: ' + str(e)[:30])
        time.sleep(1)

        # 5. CONDITION
        condition = listing.get('condition', 'New')
        print('[LISTING #' + str(num) + '] Condition: ' + condition)
        try:
            dd = find_clickable(driver, [
                "//label[@aria-label='Condition']",
                "//span[text()='Condition']/ancestor::label",
            ], 5)
            if dd:
                scroll_to(driver, dd)
                safe_click(driver, dd)
                time.sleep(1.5)
                fb_cond = {'New': 'New', 'Used - Like New': 'Used - like new', 'Used - Good': 'Used - good', 'Used - Fair': 'Used - fair'}.get(condition, 'New')
                opt = find_clickable(driver, [
                    "//span[contains(text(), '" + fb_cond + "')]",
                    "//div[@role='option']//span[contains(text(), '" + fb_cond + "')]",
                    "//span[text()='New']",
                ], 5)
                if opt:
                    safe_click(driver, opt)
                    print('[LISTING #' + str(num) + '] Condition OK')
        except Exception as e:
            print('[LISTING #' + str(num) + '] Condition error: ' + str(e)[:30])
        time.sleep(1)

        # 6. DESCRIPTION
        desc = listing.get('description', '')
        if desc:
            print('[LISTING #' + str(num) + '] Description (' + str(len(desc)) + ' chars)...')
            try:
                el = find_element(driver, [
                    "//label[@aria-label='Description']//textarea",
                    "//span[text()='Description']/ancestor::label//textarea",
                    "//textarea[contains(@aria-label, 'Description')]",
                    "//label[contains(@aria-label, 'escription')]//textarea",
                ], 8)
                if el:
                    scroll_to(driver, el)
                    safe_click(driver, el)
                    time.sleep(0.5)
                    el.send_keys(Keys.CONTROL + 'a')
                    time.sleep(0.1)
                    el.send_keys(Keys.BACKSPACE)
                    time.sleep(0.3)
                    typed = False
                    try:
                        el.send_keys(desc)
                        time.sleep(0.3)
                        val = el.get_attribute('value') or ''
                        if len(val) > 3:
                            typed = True
                            print('[LISTING #' + str(num) + '] Description OK')
                    except Exception:
                        pass
                    if not typed:
                        try:
                            el.clear()
                            for char in desc:
                                el.send_keys(char)
                                time.sleep(0.01)
                            typed = True
                            print('[LISTING #' + str(num) + '] Description OK (slow)')
                        except Exception:
                            pass
                    if not typed:
                        try:
                            driver.execute_script("arguments[0].value=arguments[1];arguments[0].dispatchEvent(new Event('input',{bubbles:true}));", el, desc)
                            print('[LISTING #' + str(num) + '] Description OK (JS)')
                        except Exception:
                            pass
                    if not typed:
                        try:
                            ActionChains(driver).click(el).send_keys(desc).perform()
                            print('[LISTING #' + str(num) + '] Description OK (AC)')
                        except Exception:
                            print('[LISTING #' + str(num) + '] Description FAILED')
                else:
                    try:
                        labels = driver.find_elements(By.XPATH, "//span[contains(text(), 'Description')]")
                        for lbl in labels:
                            try:
                                parent = lbl.find_element(By.XPATH, './ancestor::label')
                                safe_click(driver, parent)
                                time.sleep(0.5)
                                driver.switch_to.active_element.send_keys(desc)
                                print('[LISTING #' + str(num) + '] Description OK (label)')
                                break
                            except Exception:
                                continue
                    except Exception:
                        print('[LISTING #' + str(num) + '] Description NOT FOUND')
            except Exception as e:
                print('[LISTING #' + str(num) + '] Description error: ' + str(e)[:40])
        time.sleep(1)

        # 7. LOCATION
        location = listing.get('location', '')
        if location:
            print('[LISTING #' + str(num) + '] Location: ' + location)
            try:
                el = find_clickable(driver, [
                    "//label[@aria-label='Location']//input",
                    "//span[text()='Location']/ancestor::label//input",
                ], 5)
                if el:
                    scroll_to(driver, el)
                    safe_click(driver, el)
                    time.sleep(0.5)
                    el.send_keys(Keys.CONTROL + 'a')
                    el.send_keys(Keys.BACKSPACE)
                    time.sleep(0.5)
                    type_slow(el, location, 0.1)
                    time.sleep(2)
                    el.send_keys(Keys.ARROW_DOWN)
                    time.sleep(0.3)
                    el.send_keys(Keys.ENTER)
                    time.sleep(1)
                    print('[LISTING #' + str(num) + '] Location OK')
            except Exception as e:
                print('[LISTING #' + str(num) + '] Location error: ' + str(e)[:30])
        time.sleep(2)

        # 8. NEXT
        print('[LISTING #' + str(num) + '] Next button...')
        try:
            btn = find_clickable(driver, [
                "//div[@aria-label='Next']",
                "//span[text()='Next']/ancestor::div[@role='button']",
                "//div[@role='button']//span[text()='Next']/..",
            ], 5)
            if btn:
                scroll_to(driver, btn)
                safe_click(driver, btn)
                time.sleep(3)
                print('[LISTING #' + str(num) + '] Next clicked')
            else:
                print('[LISTING #' + str(num) + '] No Next button')
        except Exception:
            print('[LISTING #' + str(num) + '] No Next button')

        # 9. PUBLISH
        print('[LISTING #' + str(num) + '] Publishing...')
        try:
            btn = find_clickable(driver, [
                "//div[@aria-label='Publish']",
                "//span[text()='Publish']/ancestor::div[@role='button']",
                "//div[@role='button']//span[text()='Publish']/..",
                "//div[@aria-label='Publish'][@role='button']",
            ], 10)
            if btn:
                scroll_to(driver, btn)
                time.sleep(0.5)
                safe_click(driver, btn)
                time.sleep(5)
                print('[LISTING #' + str(num) + '] Published!')
            else:
                print('[LISTING #' + str(num) + '] Publish NOT FOUND')
                return {'status': 'failed', 'title': listing.get('title', ''), 'error': 'Publish not found'}
        except Exception as e:
            print('[LISTING #' + str(num) + '] Publish error: ' + str(e)[:30])
            return {'status': 'failed', 'title': listing.get('title', ''), 'error': str(e)}

        print('[LISTING #' + str(num) + '] COMPLETED!')
        return {'status': 'success', 'title': listing.get('title', '')}

    except Exception as e:
        print('[LISTING #' + str(num) + '] FAILED: ' + str(e)[:60])
        import traceback
        traceback.print_exc()
        return {'status': 'failed', 'title': listing.get('title', ''), 'error': str(e)}


def run_facebook_bot_multiple(data, progress_callback=None):
    settings = data.get('advanced_settings', {})
    settings['headless_mode'] = True
    settings['stealth_mode'] = True
    driver = None
    results = []

    print('\n' + '=' * 60)
    print('[BOT] Starting')
    print('[BOT] Account: ' + str(data.get('account_name', '?')))
    print('[BOT] Listings: ' + str(len(data.get('listings', []))))
    print('[BOT] Cookies: ' + str(len(data.get('cookie_string', ''))) + ' chars')
    print('=' * 60)

    if not data.get('cookie_string') or len(data.get('cookie_string', '')) < 50:
        print('[BOT] ERROR: No valid cookies!')
        return [{'status': 'failed', 'title': 'N/A', 'error': 'No valid cookies'}]

    try:
        print('[BOT] Starting Chrome...')
        driver = setup_driver(settings)
        wait = WebDriverWait(driver, 20)
        print('[BOT] Chrome ready!')

        print('[BOT] Opening Facebook...')
        driver.get('https://www.facebook.com')
        time.sleep(3)

        cookies = parse_cookies(data['cookie_string'])
        added = 0
        for c in cookies:
            try:
                driver.add_cookie(c)
                added += 1
            except Exception:
                pass
        print('[BOT] Added ' + str(added) + ' cookies')

        driver.refresh()
        time.sleep(5)

        url = driver.current_url.lower()
        print('[BOT] URL after login: ' + url)

        if 'login' in url:
            print('[BOT] FAILED - Still on login page! Cookies expired!')
            return [{'status': 'failed', 'title': 'Login Failed', 'error': 'Cookies expired'}]

        if 'checkpoint' in url:
            print('[BOT] FAILED - Account checkpoint!')
            return [{'status': 'failed', 'title': 'Checkpoint', 'error': 'Account checkpoint'}]

        try:
            wait.until(EC.presence_of_element_located((By.XPATH, "//div[@aria-label='Account' or @aria-label='Your profile']")))
            print('[BOT] Logged in!')
        except Exception:
            if 'login' not in url:
                print('[BOT] Login unclear but URL ok')
            else:
                print('[BOT] Login failed!')

        total = len(data['listings'])
        print('[BOT] Posting ' + str(total) + ' listings...')

        for i, listing in enumerate(data['listings'], 1):
            if progress_callback:
                try:
                    progress_callback(i, total, listing.get('title', ''))
                except Exception:
                    pass

            result = post_single_listing(driver, wait, listing, i, settings)
            results.append(result)

            if i < total:
                delay = random.uniform(settings.get('min_delay', 10), settings.get('max_delay', 20))
                print('[BOT] Waiting ' + str(int(delay)) + 's...')
                time.sleep(delay)

        ok = sum(1 for r in results if r.get('status') == 'success')
        print('\n' + '=' * 60)
        print('[BOT] DONE: ' + str(ok) + '/' + str(total) + ' successful')
        print('=' * 60)

    except Exception as e:
        print('[BOT] CRITICAL ERROR: ' + str(e))
        import traceback
        traceback.print_exc()
    finally:
        if driver:
            print('[BOT] Closing Chrome...')
            try:
                driver.quit()
            except Exception:
                pass

    return results


def run_facebook_bot(data):
    return run_facebook_bot_multiple({
        'cookie_string': data['cookie_string'],
        'listings': [{
            'title': data['title'],
            'price': data['price'],
            'description': data['description'],
            'location': data['location'],
            'category': data.get('category', 'Household'),
            'condition': data.get('condition', 'New'),
            'images': data['images']
        }],
        'advanced_settings': data.get('advanced_settings', {})
    })