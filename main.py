import asyncio
from pyppeteer import connect
from bs4 import BeautifulSoup
from datetime import datetime
import re
import json
import os
import requests
import time
from dotenv import load_dotenv
import socket
from threading import Thread
from flask import Flask, jsonify, render_template

# ================= Konfigurasi =================
load_dotenv()
RDP_PUBLIC_IP = os.getenv("RDP_PUBLIC_IP", "127.0.0.1")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
TELEGRAM_ADMIN_ID = os.getenv("TELEGRAM_ADMIN_ID")

try:
    FLASK_PORT = int(os.getenv("FLASK_PORT", 5000))
except:
    FLASK_PORT = 5000

BOT = TELEGRAM_BOT_TOKEN
CHAT = TELEGRAM_CHAT_ID
ADMIN_ID = int(TELEGRAM_ADMIN_ID) if TELEGRAM_ADMIN_ID else None

LAST_ID = 0
GLOBAL_ASYNC_LOOP = None
SMC_FILE = "smc.json"

# ================= Utils =================
def clean_phone_number(phone):
    if not phone: return "N/A"
    cleaned = re.sub(r'[^\d+]', '', phone)
    if cleaned and not cleaned.startswith('+') and len(cleaned) >= 8:
        cleaned = '+' + cleaned
    return cleaned

def mask_phone_number(phone):
    if not phone or phone == "N/A": return phone
    if len(phone) < 10: return phone
    return f"{phone[:5]}****{phone[-4:]}"

def clean_range_text(text):
    """Menghapus semua angka dan simbol, hanya menyisakan teks alfabet."""
    if not text: return "N/A"
    # 1. Hapus angka
    text_no_digits = re.sub(r'[0-9]', '', text)
    # 2. Hapus simbol, sisakan huruf dan spasi
    cleaned = re.sub(r'[^a-zA-Z\s]+', '', text_no_digits).strip()
    return cleaned.upper() if cleaned else "UNKNOWN"

def extract_otp_from_text(text):
    if not text: return None
    # Pola 1: WhatsApp style (Contoh: 687-947)
    wa_match = re.search(r'\b(\d{3}-\d{3})\b', text)
    if wa_match: return wa_match.group(1)
    
    # Pola 2: Angka murni 4-6 digit
    patterns = [r'\b(\d{6})\b', r'\b(\d{5})\b', r'\b(\d{4})\b']
    for p in patterns:
        m = re.search(p, text)
        if m: return m.group(1)
    return None

def clean_service_name(service):
    if not service: return "Unknown"
    s = service.strip().lower()
    maps = {'whatsapp': 'WhatsApp', 'google': 'Google', 'facebook': 'Facebook', 'telegram': 'Telegram'}
    for k, v in maps.items():
        if k in s: return v
    return service.title()

# ================= Storage Engine =================
class OTPFilter:
    def __init__(self, file='otp_cache.json'):
        self.file = file
        self.cache = self._load()
        self.unsaved_changes = False
        
    def _load(self):
        if os.path.exists(self.file):
            try: return json.load(open(self.file, 'r'))
            except: return {}
        return {}
        
    def _save(self):
        try:
            with open(self.file, 'w') as f:
                json.dump(self.cache, f, indent=2)
        except Exception as e: print(f"❌ Cache Save Error: {e}")

    def is_dup(self, d):
        # Key unik berdasarkan nomor dan OTP
        key = f"{d['phone']}_{d['otp']}"
        return key in self.cache

    def add(self, d):
        key = f"{d['phone']}_{d['otp']}"
        self.cache[key] = datetime.now().isoformat()
        self.unsaved_changes = True

otp_filter = OTPFilter()

def save_to_smc(otp_data):
    data = []
    if os.path.exists(SMC_FILE):
        try:
            with open(SMC_FILE, 'r') as f: data = json.load(f)
        except: pass
    data.append(otp_data)
    try:
        with open(SMC_FILE, 'w') as f: json.dump(data[-100:], f, indent=2)
    except Exception as e: print(f"❌ SMC Save Error: {e}")

# ================= Telegram Engine =================
def send_tg(text, target_chat_id=None):
    chat_id = target_chat_id or CHAT
    if not BOT or not chat_id: return
    url = f"https://api.telegram.org/bot{BOT}/sendMessage"
    payload = {'chat_id': chat_id, 'text': text, 'parse_mode': 'HTML'}
    try: requests.post(url, data=payload, timeout=10)
    except Exception as e: print(f"❌ TG Error: {e}")

# ================= SMS Monitor (The Scraper) =================
class SMSMonitor:
    def __init__(self, url="https://www.ivasms.com/portal/live/my_sms"):
        self.url = url
        self.browser = None
        self.page = None

    async def initialize(self):
        try:
            self.browser = await connect(browserURL="http://127.0.0.1:9222")
            pages = await self.browser.pages()
            self.page = next((p for p in pages if self.url in p.url), None)
            if not self.page:
                self.page = await self.browser.newPage()
                await self.page.goto(self.url, {'waitUntil': 'networkidle2'})
            print("✅ Scraper Connected & Ready")
        except Exception as e:
            print(f"❌ Connection Error: {e}. Pastikan Chrome --remote-debugging-port=9222 aktif.")

    async def fetch_sms(self):
        if not self.page: await self.initialize()
        try:
            html = await self.page.content()
            soup = BeautifulSoup(html, 'html.parser')
            messages = []

            tbody = soup.find("tbody", id="LiveTestSMS")
            if not tbody: return []

            for r in tbody.find_all("tr"):
                tds = r.find_all("td")
                if len(tds) >= 5:
                    # 1. Range (Hanya Teks)
                    range_tag = tds[0].find("h6")
                    range_raw = range_tag.get_text(strip=True) if range_tag else "N/A"
                    range_text = clean_range_text(range_raw)
                    
                    # 2. Nomor Telepon
                    phone_tag = tds[0].find("p", class_="CopyText")
                    phone = clean_phone_number(phone_tag.get_text(strip=True)) if phone_tag else "N/A"
                    
                    # 3. Layanan (WhatsApp, dll)
                    service_div = tds[1].find("div", class_="fw-semi-bold")
                    service = clean_service_name(service_div.get_text(strip=True)) if service_div else "Unknown"
                    
                    # 4. Pesan & OTP
                    raw_msg = tds[4].get_text(strip=True)
                    otp = extract_otp_from_text(raw_msg)
                    
                    if otp and phone != "N/A":
                        messages.append({
                            "otp": otp, 
                            "phone": phone, 
                            "service": service, 
                            "range": range_text, 
                            "raw_message": raw_msg
                        })
            return messages
        except Exception as e:
            print(f"❌ Scrape Loop Error: {e}")
            return []

monitor = SMSMonitor()

# ================= Main Monitor Loop =================
async def monitor_sms_loop():
    await monitor.initialize()
    while True:
        try:
            msgs = await monitor.fetch_sms()
            for m in msgs:
                if not otp_filter.is_dup(m):
                    otp_filter.add(m)
                    save_to_smc(m)
                    
                    # Format Pesan Telegram
                    txt = (f"🔐 <b>New OTP Received</b>\n\n"
                           f"🏷️ Range: <b>{m['range']}</b>\n"
                           f"📞 Number: <code>{mask_phone_number(m['phone'])}</code>\n"
                           f"🌐 Service: <b>{m['service']}</b>\n"
                           f"🔑 OTP: <code>{m['otp']}</code>\n\n"
                           f"📝 Full Message:\n"
                           f"<blockquote>{m['raw_message']}</blockquote>")
                    
                    send_tg(txt)
                    print(f"🚀 OTP Sent: {m['phone']} - {m['otp']}")
                    await asyncio.sleep(0.5)
            
            # Save Cache secara berkala
            if otp_filter.unsaved_changes:
                otp_filter._save()
                otp_filter.unsaved_changes = False
                
        except Exception as e:
            print(f"❌ Global Loop Error: {e}")
        await asyncio.sleep(5)

# ================= Flask Server =================
app = Flask(__name__)

@app.route('/')
def index():
    return "<h1>Bot Status: Running</h1>"

def start_async_loop():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(monitor_sms_loop())

if __name__ == "__main__":
    # Jalankan monitor di background thread
    t = Thread(target=start_async_loop, daemon=True)
    t.start()
    
    # Jalankan Flask
    print(f"🌐 Dashboard accessible at port {FLASK_PORT}")
    app.run(host='0.0.0.0', port=FLASK_PORT, debug=False)
