import asyncio
from pyppeteer import connect
from bs4 import BeautifulSoup
from datetime import datetime
import re
import json
import os
import requests
import time
# from dotenv import load_dotenv # Hapus import ini
import socket
from threading import Thread

from flask import Flask, jsonify, render_template

# ================= Konfigurasi Variabel (Pengganti .env) =================
# Anda dapat mengubah nilai di sini
RDP_PUBLIC_IP = "103.186.30.186" # IP yang digunakan untuk login ke RDP (tanpa port)
TELEGRAM_BOT_TOKEN = "8355352388:AAFjePLqG9D4v88GSNk18brV_lAtVVEaucE"
TELEGRAM_CHAT_ID = "-1003492226491"
TELEGRAM_ADMIN_ID = "7184123643"
FLASK_PORT = 5000 # Port untuk Flask

# --- Load environment (Variabel di atas akan menggantikan ini) ---
# load_dotenv() # Tidak lagi diperlukan

# ================= Konstanta Telegram =================
TELEGRAM_BOT_LINK = "https://t.me/newgettbot"
TELEGRAM_ADMIN_LINK = "https://t.me/Imr1d"

# Ambil nilai dari variabel konfigurasi di atas
BOT = TELEGRAM_BOT_TOKEN
CHAT = TELEGRAM_CHAT_ID
try:
    # Menggunakan int(os.getenv(...)) diganti dengan konversi langsung
    ADMIN_ID = int(TELEGRAM_ADMIN_ID)
except (ValueError, TypeError):
    print("⚠️ WARNING: TELEGRAM_ADMIN_ID tidak valid. Admin command dinonaktifkan.")
    ADMIN_ID = None

LAST_ID = 0
GLOBAL_ASYNC_LOOP = None

# ================= Utils =================
def get_local_ip():
    s = None
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80)) 
        return s.getsockname()[0]
    except:
        return "127.0.0.1"
    finally:
        if s: s.close()

def create_inline_keyboard():
    keyboard = {
        "inline_keyboard": [
            [
                {"text": "➡️ GetNumber", "url": TELEGRAM_BOT_LINK},
                {"text": "👤 Admin", "url": TELEGRAM_ADMIN_LINK}
            ]
        ]
    }
    return json.dumps(keyboard)

def clean_phone_number(phone):
    if not phone: return "N/A"
    cleaned = re.sub(r'[^\d+]', '', phone)
    if cleaned and not cleaned.startswith('+') and len(cleaned) >= 8:
        cleaned = '+' + cleaned
    return cleaned or phone

def mask_phone_number(phone, visible_start=4, visible_end=4):
    if not phone or phone == "N/A": return phone
    prefix = '+' if phone.startswith('+') else ''
    digits = phone[1:] if prefix else phone
    if len(digits) <= visible_start + visible_end:
        return phone
    masked = '*' * (len(digits) - visible_start - visible_end)
    return f"{prefix}{digits[:visible_start]}{masked}{digits[-visible_end:]}"

def clean_range_text(text):
    """Hanya ambil huruf, buang angka, dan ubah ke huruf besar."""
    if not text: return "N/A"
    cleaned = re.sub(r'[^a-zA-Z\s]+', '', text).strip()
    return cleaned.upper() if cleaned else "UNKNOWN RANGE"

def escape_html(text):
    if not isinstance(text, str): return text
    return text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

def format_otp_message(otp_data):
    otp = otp_data.get('otp', 'N/A')
    phone = otp_data.get('phone', 'N/A')
    masked_phone = mask_phone_number(phone)
    service = otp_data.get('service', 'Unknown')
    range_text = clean_range_text(otp_data.get('range', 'N/A'))
    timestamp = otp_data.get('timestamp', datetime.now().strftime('%H:%M:%S'))
    full_message = escape_html(otp_data.get('raw_message', 'N/A'))

    return f"""🔐 <b>New OTP Received</b>

🏷️ Range: <b>{range_text}</b>
📱 Number: <code>{masked_phone}</code>
🌐 Service: <b>{service}</b>
🔢 OTP: <code>{otp}</code>

FULL MESSAGE:
<blockquote>{full_message}</blockquote>"""

def extract_otp_from_text(text):
    if not text: return None
    patterns = [r'\b(\d{6})\b', r'\b(\d{5})\b', r'\b(\d{4})\b', r'(?:code|verification|otp|pin)[\s\:\-]*(\d+)']
    for p in patterns:
        m = re.search(p, text, re.I)
        if m:
            otp = m.group(1) if len(m.groups()) == 1 else m.group(0)
            if 4 <= len(otp) <= 6 and not (len(otp) == 4 and '20' in otp):
                return otp
            elif len(otp) > 6:
                if re.search(r'\d{4,6}', otp):
                    return re.search(r'\d{4,6}', otp).group(0)
    return None

def clean_service_name(service):
    if not service: return "Unknown"
    s = service.strip().title()
    maps = {'fb':'Facebook','google':'Google','whatsapp':'WhatsApp','telegram':'Telegram',
            'instagram':'Instagram','twitter':'Twitter','linkedin':'LinkedIn','tiktok':'TikTok'}
    for k,v in maps.items():
        if k in s.lower(): return v
    return s

def get_status_message(stats):
    return f"""🤖 <b>Bot Status</b>

⚡ Status: <b>{stats['status']}</b>
⏱️ Uptime: {stats['uptime']}
📨 Total OTPs Sent: <b>{stats['total_otps_sent']}</b>
🔍 Last Check: {stats['last_check']}
💾 Cache Size: {stats['cache_size']} items

<i>Bot is running</i>"""

# ================= OTP Filter =================
class OTPFilter:
    def __init__(self, file='otp_cache.json', expire=999999):
        self.file = file
        self.expire = expire
        self.cache = self._load()
        self.unsaved_changes = False
        
    def _load(self):
        if os.path.exists(self.file):
            try:
                if os.stat(self.file).st_size > 0:
                    return json.load(open(self.file,'r'))
            except:
                pass
        return {}
        
    def _save(self):
        try:
            with open(self.file,'w') as f:
                json.dump(self.cache, f, indent=2)
        except Exception as e:
            print(f"❌ Failed saving cache: {e}")

    def key(self, d):
        return f"{d['otp']}_{d['phone']}_{clean_service_name(d['service'])}_{clean_range_text(d.get('range','N/A'))}"

    def is_dup(self, d):
        return self.key(d) in self.cache

    def add(self, d):
        self.cache[self.key(d)] = {'timestamp': datetime.now().isoformat()}
        self.unsaved_changes = True

    def filter(self, lst):
        out = []
        for d in lst:
            if d.get('otp') and d.get('phone') != 'N/A' and not self.is_dup(d):
                out.append(d)
                self.add(d)
        return out

otp_filter = OTPFilter()

# ================= SMC.json =================
SMC_FILE = "smc.json"

def save_to_smc(otp_data):
    entry = {
        "range": clean_range_text(otp_data.get("range", "N/A")),
        "number": otp_data.get("phone", "N/A"),
        "otp": otp_data.get("otp", "N/A")
    }
    data = []
    if os.path.exists(SMC_FILE):
        try:
            with open(SMC_FILE,'r') as f:
                content = f.read().strip()
                if content:
                    data = json.loads(content)
        except:
            pass
    data.append(entry)
    try:
        with open(SMC_FILE,'w') as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"❌ Failed to save to smc.json: {e}")

# ================= Telegram =================
def send_tg(text, with_inline_keyboard=False, target_chat_id=None):
    chat_id_to_use = target_chat_id if target_chat_id else CHAT
    if not BOT or not chat_id_to_use:
        print("❌ Telegram config missing.")
        return
    payload = {'chat_id': chat_id_to_use,'text': text,'parse_mode':'HTML'}
    if with_inline_keyboard: payload['reply_markup'] = create_inline_keyboard()
    try:
        r = requests.post(f"https://api.telegram.org/bot{BOT}/sendMessage", data=payload, timeout=15)
        if not r.ok:
            print(f"⚠️ Telegram API error: {r.text}")
    except Exception as e:
        print(f"❌ send_tg error: {e}")

def send_photo_tg(photo_path, caption="", target_chat_id=None):
    chat_id_to_use = target_chat_id if target_chat_id else CHAT
    if not BOT or not chat_id_to_use:
        print("❌ Telegram config missing.")
        return False
    try:
        with open(photo_path,'rb') as photo_file:
            files = {'photo': photo_file}
            data = {'chat_id': chat_id_to_use,'caption':caption,'parse_mode':'HTML'}
            r = requests.post(f"https://api.telegram.org/bot{BOT}/sendPhoto", files=files, data=data, timeout=20)
        if not r.ok: print(f"⚠️ Telegram Photo API error: {r.text}"); return False
        return True
    except Exception as e:
        print(f"❌ send_photo_tg error: {e}")
        return False

# ================= SMS Monitor =================
URL = "https://www.ivasms.com/portal/live/my_sms"

class SMSMonitor:
    def __init__(self, url=URL):
        self.url = url
        self.browser = None
        self.page = None

    async def initialize(self):
        # Menggunakan 127.0.0.1:9222 (port default untuk pyppeteer connect)
        self.browser = await connect(browserURL="http://127.0.0.1:9222")
        pages = await self.browser.pages()
        page = next((p for p in pages if self.url in p.url), None)
        if not page:
            page = await self.browser.newPage()
            await page.goto(self.url, {'waitUntil':'networkidle0'})
        self.page = page
        print("✅ Browser page connected.")

    async def fetch_sms(self):
        if not self.page: await self.initialize()
        try:
            await self.page.evaluate('window.scrollBy(0,100)')
            await self.page.evaluate('window.scrollBy(0,-100)')
            await asyncio.sleep(0.1)
        except: pass
        html = await self.page.content()
        soup = BeautifulSoup(html,'html.parser')
        messages = []

        tbody = soup.find("tbody", id="LiveTestSMS")
        if not tbody: return self._fallback_fetch_sms(soup)

        for r in tbody.find_all("tr"):
            tds = r.find_all("td")
            if len(tds)>=5:
                info_div = tds[0].find("div", class_="flex-1 ml-3")
                range_text = info_div.find("h6").get_text(strip=True) if info_div and info_div.find("h6") else "N/A"
                phone_raw = info_div.find("p").get_text(strip=True) if info_div and info_div.find("p") else "N/A"
                phone = clean_phone_number(phone_raw)
                service = clean_service_name(tds[1].get_text(strip=True))
                raw_message = tds[4].get_text(strip=True)
                otp = extract_otp_from_text(raw_message)
                if otp and phone!="N/A":
                    messages.append({"otp":otp,"phone":phone,"service":service,"range":range_text,
                                     "timestamp":datetime.now().strftime("%H:%M:%S"),"raw_message":raw_message})
        return messages

    def _fallback_fetch_sms(self, soup):
        messages = []
        for tb in soup.find_all("table"):
            for r in tb.find_all("tr")[1:]:
                tds = r.find_all("td")
                if len(tds)>=5:
                    raw = tds[4].get_text(strip=True)
                    otp = extract_otp_from_text(raw)
                    if otp:
                        phone = clean_phone_number(tds[0].get_text(strip=True))
                        service = clean_service_name(tds[1].get_text(strip=True)) if len(tds)>1 else "Unknown"
                        range_text = "Unknown Range"
                        messages.append({"otp":otp,"phone":phone,"service":service,"range":range_text,
                                         "timestamp":datetime.now().strftime("%H:%M:%S"),"raw_message":raw})
        return messages

    async def refresh_and_screenshot(self, admin_chat_id):
        if not self.page:
            try: await self.initialize()
            except Exception as e:
                send_tg(f"⚠️ Error init browser: {e}", target_chat_id=admin_chat_id)
                return False
        screenshot_filename = f"screenshot_{int(time.time())}.png"
        try:
            await self.page.reload({'waitUntil':'networkidle0'})
            await self.page.screenshot({'path':screenshot_filename,'fullPage':True})
            caption = f"✅ Page refreshed at {datetime.now().strftime('%H:%M:%S')}\n<i>Pesan OTP di halaman telah dihapus.</i>"
            send_photo_tg(screenshot_filename, caption, target_chat_id=admin_chat_id)
            return True
        except Exception as e:
            send_tg(f"⚠️ Error refresh/screenshot: {e}", target_chat_id=admin_chat_id)
            return False
        finally:
            if os.path.exists(screenshot_filename): os.remove(screenshot_filename)

monitor = SMSMonitor()
start = time.time()
total_sent = 0
BOT_STATUS = {"status":"Initializing...","uptime":"--","total_otps_sent":0,"last_check":"Never","cache_size":0,"monitoring_active":True}

def update_global_status():
    global BOT_STATUS
    uptime_seconds = time.time()-start
    BOT_STATUS.update({
        "uptime":f"{int(uptime_seconds//3600)}h {int((uptime_seconds%3600)//60)}m {int(uptime_seconds%60)}s",
        "total_otps_sent":total_sent,
        "last_check":datetime.now().strftime("%H:%M:%S"),
        "cache_size":len(otp_filter.cache),
        "status":"Running" if BOT_STATUS["monitoring_active"] else "Paused"
    })
    return BOT_STATUS

# ================= Loop Monitor OTP =================
def check_cmd(stats):
    global LAST_ID
    if ADMIN_ID is None or not BOT: return
    try:
        upd = requests.get(f"https://api.telegram.org/bot{BOT}/getUpdates?offset={LAST_ID+1}", timeout=15).json()
        for u in upd.get("result",[]):
            LAST_ID = u["update_id"]
            msg = u.get("message",{})
            text = msg.get("text","")
            user_id = msg.get("from",{}).get("id")
            chat_id = msg.get("chat",{}).get("id")
            if user_id==ADMIN_ID:
                if text=="/status":
                    requests.post(f"https://api.telegram.org/bot{BOT}/sendMessage",
                                  data={'chat_id':chat_id,'text':get_status_message(stats),'parse_mode':'HTML'})
                elif text=="/refresh":
                    send_tg("⏳ Executing page refresh...", target_chat_id=chat_id)
                    if GLOBAL_ASYNC_LOOP:
                        asyncio.run_coroutine_threadsafe(monitor.refresh_and_screenshot(admin_chat_id=chat_id), GLOBAL_ASYNC_LOOP)
                    else:
                        send_tg("❌ Loop error.", target_chat_id=chat_id)
    except Exception as e:
        print(f"❌ check_cmd error: {e}")

async def monitor_sms_loop():
    global total_sent
    try: await monitor.initialize()
    except Exception as e:
        send_tg(f"🚨 FATAL ERROR: Gagal terhubung ke Chrome/Pyppeteer.\n{e}")
        BOT_STATUS["status"]="FATAL ERROR"
        return

    BOT_STATUS["monitoring_active"]=True
    while True:
        try:
            if BOT_STATUS["monitoring_active"]:
                msgs = await monitor.fetch_sms()
                new = otp_filter.filter(msgs)
                if new:
                    for i, otp_data in enumerate(new,1):
                        # Simpan ke smc.json sebelum kirim ke Telegram
                        save_to_smc(otp_data)

                        message_text = f"[{i}/{len(new)}] "+format_otp_message(otp_data)
                        # send_tg(message_text, with_inline_keyboard=True)
                        # Menggunakan CHAT_ID yang sudah didefinisikan secara global
                        send_tg(message_text, with_inline_keyboard=True, target_chat_id=CHAT)
                        total_sent+=1
                        await asyncio.sleep(0.5)
            stats = update_global_status()
            check_cmd(stats)
        except Exception as e:
            print(f"❌ monitor loop error: {e}")
        await asyncio.sleep(5)

# ================= Periodic Save Cache =================
async def periodic_cache_save(interval_seconds=60):
    global otp_filter
    while True:
        await asyncio.sleep(interval_seconds)
        if otp_filter.unsaved_changes:
            try:
                print(f"💾 Saving cache ({len(otp_filter.cache)} items)...")
                otp_filter._save()
                otp_filter.unsaved_changes=False
            except Exception as e:
                print(f"❌ Failed periodic save: {e}")

# ================= Flask =================
app = Flask(__name__, template_folder='templates')

@app.route('/', methods=['GET'])
def index():
    return render_template('dashboard.html')

@app.route('/api/status', methods=['GET'])
def get_status_json():
    update_global_status()
    return jsonify(BOT_STATUS)

@app.route('/manual-check', methods=['GET'])
def manual_check():
    if ADMIN_ID is None:
        return jsonify({"message":"Admin ID not configured"}), 400
    if GLOBAL_ASYNC_LOOP is None:
        return jsonify({"message":"Async loop not initialized"}), 500
    try:
        asyncio.run_coroutine_threadsafe(monitor.refresh_and_screenshot(admin_chat_id=ADMIN_ID), GLOBAL_ASYNC_LOOP)
        return jsonify({"message":"Halaman IVASMS Refresh & Screenshot sedang dikirim ke Admin Telegram."})
    except Exception as e:
        return jsonify({"message":f"Error: {e}"}), 500

@app.route('/telegram-status', methods=['GET'])
def send_telegram_status_route():
    if ADMIN_ID is None:
        return jsonify({"message":"Admin ID not configured"}), 400
    stats_msg = get_status_message(update_global_status())
    send_tg(stats_msg, target_chat_id=ADMIN_ID)
    return jsonify({"message":"Status sent to Telegram Admin."})

@app.route('/clear-cache', methods=['GET'])
def clear_otp_cache_route():
    global otp_filter
    otp_filter.cache = {}
    otp_filter._save()
    otp_filter.unsaved_changes = False
    update_global_status()
    return jsonify({"message":"OTP cache cleared."})

# ================= Main Async Loop =================
def start_async_loop():
    global GLOBAL_ASYNC_LOOP
    loop = asyncio.new_event_loop()
    GLOBAL_ASYNC_LOOP = loop
    asyncio.set_event_loop(loop)
    tasks = [
        monitor_sms_loop(),
        periodic_cache_save(60)
    ]
    loop.run_until_complete(asyncio.gather(*tasks))

# ================= Run Flask + Bot =================
if __name__ == "__main__":
    from threading import Thread
    # Start bot async loop in background thread
    t = Thread(target=start_async_loop, daemon=True)
    t.start()

    # Start Flask web server
    # Menggunakan FLASK_PORT yang telah didefinisikan
    app.run(host='0.0.0.0', port=FLASK_PORT, debug=False)
