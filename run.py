import asyncio
from pyppeteer import connect
from bs4 import BeautifulSoup
from datetime import datetime
import re
import json
import os
import requests
import time
from dotenv import load_dotenv # <-- Tambahan baru: untuk memuat .env

# Muat variabel lingkungan dari file .env segera setelah import
load_dotenv() 

# ================= Konstanta Telegram untuk Tombol =================
TELEGRAM_BOT_LINK = "https://t.me/zuraxridbot"
TELEGRAM_ADMIN_LINK = "https://t.me/Imr1d"

# ================= Telegram Configuration (Loaded from .env) =================
# Ambil variabel dari lingkungan. Perhatikan konversi tipe data.
BOT = os.getenv("TELEGRAM_BOT_TOKEN") 
CHAT = os.getenv("TELEGRAM_CHAT_ID")   
# ID Admin harus berupa integer untuk perbandingan
try:
    ADMIN_ID = int(os.getenv("TELEGRAM_ADMIN_ID")) 
except (ValueError, TypeError):
    print("⚠️ WARNING: TELEGRAM_ADMIN_ID tidak valid. Perintah admin dinonaktifkan.")
    ADMIN_ID = None

LAST_ID = 0 # Variabel status internal

# ================= Utils =================

# Fungsi baru untuk membuat keyboard inline
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

def format_otp_message(otp_data):
    otp = otp_data.get('otp', 'N/A')
    phone = otp_data.get('phone', 'N/A')
    service = otp_data.get('service', 'Unknown')
    range_text = otp_data.get('range', 'N/A') 
    timestamp = otp_data.get('timestamp', datetime.now().strftime('%H:%M:%S'))
    full_message = otp_data.get('raw_message', 'N/A')

    return f"""🔐 <b>New OTP Received</b>

🏷️ Range: <b>{range_text}</b>

📱 Number: <code>{phone}</code>
🌐 Service: <b>{service}</b>
🔢 OTP: <code>{otp}</code>

FULL MESSAGES:
<blockquote>{full_message}</blockquote>"""

def format_multiple_otps(otp_list):
    if len(otp_list) == 1:
        return format_otp_message(otp_list[0])
    
    header = f"🔐 <b>{len(otp_list)} New OTPs Received</b>\n\n"
    items = []
    for i, otp_data in enumerate(otp_list, 1):
        otp = otp_data['otp']
        phone = otp_data['phone']
        service = otp_data['service']
        range_text = otp_data.get('range', 'N/A')
        items.append(f"<b>{i}.</b> <code>{otp}</code> | {service} | <code>{phone}</code> | {range_text}")
    return header + "\n".join(items) + "\n\n<i>Tap any OTP to copy it!</i>"


def extract_otp_from_text(text):
    if not text:
        return None
    patterns = [
        r'\b(\d{6})\b', r'\b(\d{5})\b', r'\b(\d{4})\b',
        r'code[:\s]*(\d+)', r'verification[:\s]*(\d+)',
        r'otp[:\s]*(\d+)', r'pin[:\s]*(\d+)'
    ]
    for p in patterns:
        m = re.search(p, text, re.I)
        if m:
            return m.group(1)
    return None

def clean_phone_number(phone):
    if not phone:
        return "N/A"
    cleaned = re.sub(r'[^\d+]', '', phone)
    if cleaned and not cleaned.startswith('+'):
        if len(cleaned) >= 10:
            cleaned = '+' + cleaned
    return cleaned or phone

def clean_service_name(service):
    if not service:
        return "Unknown"
    s = service.strip().title()
    maps = {
        'fb':'Facebook','google':'Google','whatsapp':'WhatsApp',
        'telegram':'Telegram','instagram':'Instagram',
        'twitter':'Twitter','linkedin':'LinkedIn','tiktok':'TikTok'
    }
    l = s.lower()
    for k,v in maps.items():
        if k in l:
            return v
    return s

def get_status_message(stats):
    return f"""🤖 <b>Bot Status</b>

⚡ Status: <b>Online</b>
⏱️ Uptime: {stats['uptime']}
📨 Total OTPs Sent: <b>{stats['total_otps_sent']}</b>
🔍 Last Check: {stats['last_check']}
💾 Cache Size: {stats['cache_size']} items

<i>Bot is running</i>"""

# ================= OTP Filter =================
class OTPFilter:
    def __init__(self, file='otp_cache.json', expire=30):
        self.file = file
        self.expire = expire
        self.cache = self._load()
    def _load(self):
        if os.path.exists(self.file):
            try:
                # Pastikan hanya memuat jika file tidak kosong
                if os.stat(self.file).st_size > 0:
                    return json.load(open(self.file))
                else:
                    return {}
            except Exception as e:
                print(f"Error loading cache: {e}")
                return {}
        return {}
    def _save(self):
        json.dump(self.cache, open(self.file,'w'), indent=2)
    def _cleanup(self):
        now = datetime.now()
        dead = []
        for k,v in self.cache.items():
            try:
                t = datetime.fromisoformat(v['timestamp'])
                if (now-t).total_seconds() > self.expire*60:
                    dead.append(k)
            except:
                dead.append(k)
        for k in dead:
            del self.cache[k]
        self._save()
    def key(self, d):
        return f"{d['otp']}_{d['phone']}_{d['service']}_{d.get('range', 'N/A')}" 
    def is_dup(self, d):
        self._cleanup()
        return self.key(d) in self.cache
    def add(self, d):
        self.cache[self.key(d)] = {'timestamp':datetime.now().isoformat()}
        self._save()
    def filter(self, lst):
        out = []
        for d in lst:
            if d.get('otp') and d.get('phone') != 'N/A': 
                if not self.is_dup(d):
                    out.append(d)
                    self.add(d)
        return out

otp_filter = OTPFilter()

# ================= Telegram Functionality =================

def send_tg(text, with_inline_keyboard=False):
    if not BOT or not CHAT:
        print("❌ Telegram config missing (BOT or CHAT ID). Cannot send message.")
        return

    payload = {
        'chat_id': CHAT,
        'text': text,
        'parse_mode': 'HTML'
    }
    
    if with_inline_keyboard:
        # Tambahkan keyboard inline hanya jika with_inline_keyboard=True
        payload['reply_markup'] = create_inline_keyboard()

    try:
        response = requests.post(
            f"https://api.telegram.org/bot{BOT}/sendMessage",
            data=payload,
            timeout=10 # Tambahkan timeout untuk mencegah hang
        )
        if not response.ok:
            # Print error dari API Telegram jika respons tidak OK
            print(f"⚠️ Telegram API Error ({response.status_code}): {response.text}")

    except requests.exceptions.RequestException as e:
        # Tangani error koneksi atau timeout
        print(f"❌ Telegram Connection Error: {e}")
    except Exception as e:
        print(f"❌ Unknown Error in send_tg: {e}")


def check_cmd(stats):
    global LAST_ID
    # Hanya jalankan jika ID Admin valid
    if ADMIN_ID is None:
        return

    try:
        upd = requests.get(
            f"https://api.telegram.org/bot{BOT}/getUpdates?offset={LAST_ID+1}",
            timeout=5
        ).json()
        
        for u in upd.get("result",[]):
            LAST_ID = u["update_id"]
            msg = u.get("message",{})
            text = msg.get("text","")
            user_id = msg.get("from", {}).get("id")

            # --- Perintah Admin ---
            if user_id == ADMIN_ID:
                if text == "/status":
                    # Kirim pesan status ke grup/chat yang sama
                    send_tg(get_status_message(stats))
            
    except requests.exceptions.RequestException as e:
        print(f"❌ Error during getUpdates: {e}")
    except Exception as e:
        print(f"❌ Unknown Error in check_cmd: {e}")

# ================= Scraper =================
URL = "https://www.ivasms.com/portal/live/my_sms"
start = time.time()
total_sent = 0

# Pola deteksi spesifik untuk membersihkan pesan di struktur DIV
OTP_MESSAGE_PATTERNS = [
    r'(FB[-\s]?\d+[\s]+adalah kode konfirmasi Facebook anda)',
    r'(FB[-\s]?\d+[\s]+is your Facebook confirmation code)',
    r'(#\s*\d+[\s]+adalah kode Facebook Anda.*)',
    r'(#\s*\d+[\s]+is your Facebook code.*)',
]

def find_clean_message(full_text):
    for pattern in OTP_MESSAGE_PATTERNS:
        # re.I (IGNORECASE) untuk mencocokkan huruf besar/kecil
        match = re.search(pattern, full_text, re.I) 
        if match:
            # Mengembalikan pesan yang bersih sesuai pola yang terdeteksi
            return match.group(1).strip()
    return None


async def fetch_sms_from_chrome():
    # Pastikan browser chrome/chromium berjalan dengan --remote-debugging-port=9222
    browser = await connect(browserURL="http://127.0.0.1:9222")
    pages = await browser.pages()

    page = None
    for p in pages:
        if URL in p.url:
            page = p
            break
    if not page:
        page = await browser.newPage()
        await page.goto(URL)

    html = await page.content()
    soup = BeautifulSoup(html, "html.parser")

    messages = []

    # ================= 1. AMBIL DARI STRUKTUR TABLE NORMAL =================
    tables = soup.find_all("table")
    for tb in tables:
        rows = tb.find_all("tr")[1:]
        for r in rows:
            tds = r.find_all("td")
            if len(tds) >= 3:
                td_message = tds[2]
                
                # Ambil teks murni dari kolom pesan
                raw_contents = [c.strip() for c in td_message.contents if isinstance(c, str)]
                raw = " ".join(raw_contents).strip()
                
                otp = extract_otp_from_text(raw)
                
                if otp:
                    service_raw = tds[1].get_text(strip=True)
                    range_text = service_raw # Universal Range
                        
                    messages.append({
                        "otp": otp,
                        "phone": clean_phone_number(tds[0].get_text(strip=True)),
                        "service": clean_service_name(service_raw), 
                        "range": range_text, 
                        "timestamp": datetime.now().strftime("%H:%M:%S"),
                        "raw_message": raw
                    })

    # ================= 2. AMBIL DARI STRUKTUR DIV BARU (IvaSMS style) =================
    flex_boxes = soup.find_all("div", class_="flex-1 ml-3")
    for box in flex_boxes:
        h6 = box.find("h6")
        p = box.find("p")
        
        if h6 and p:
            range_text = h6.get_text(strip=True) 
            phone_text = p.get_text(strip=True)
            
            parent_row = box.find_parent("div", class_="row") 
            raw_message_temp = None
            
            if parent_row:
                full_text_with_noise = parent_row.get_text(" ", strip=True)
                raw_message_temp = find_clean_message(full_text_with_noise)
            
            if raw_message_temp:
                otp = extract_otp_from_text(raw_message_temp)
            else:
                otp = None
            
            if otp:
                messages.append({
                    "otp": otp,
                    "phone": clean_phone_number(phone_text),
                    "service": clean_service_name(raw_message_temp),
                    "range": range_text,
                    "timestamp": datetime.now().strftime("%H:%M:%S"),
                    "raw_message": raw_message_temp
                })
    
    return messages

# --- FUNGSI UTAMA LOOP ---

async def monitor_sms_loop():
    global total_sent

    while True:
        try:
            msgs = await fetch_sms_from_chrome()
            new = otp_filter.filter(msgs)

            if new:
                print(f"✅ Found {len(new)} new OTP(s). Sending to Telegram...")
                for otp_data in new:
                    message_text = format_otp_message(otp_data)
                    # Kirim pesan dengan tombol inline (True)
                    send_tg(message_text, with_inline_keyboard=True) 
                    total_sent += 1
        
        except Exception as e:
            error_message = f"Error during fetch/send: {e.__class__.__name__}: {e}"
            print(error_message)
            # Pesan error hanya dikirim jika itu bukan Pyppeteer/koneksi
            if "pyppeteer" not in str(e).lower() and "browser" not in str(e).lower():
                send_tg(f"⚠️ **Error Fetching SMS**: `{error_message}`")


        uptime = time.time() - start
        stats = {
            "uptime": f"{int(uptime//3600)}h {int((uptime%3600)//60)}m {int(uptime%60)}s",
            "total_otps_sent": total_sent, 
            "last_check": datetime.now().strftime("%H:%M:%S"),
            "cache_size": len(otp_filter.cache)
        }

        check_cmd(stats) # Cek perintah admin
        print(get_status_message(stats))

        await asyncio.sleep(5) # Delay 5 detik sebelum cek berikutnya

if __name__ == "__main__":
    if not BOT or not CHAT:
        print("FATAL ERROR: Pastikan TELEGRAM_BOT_TOKEN dan TELEGRAM_CHAT_ID ada di file .env.")
    else:
        print("Starting SMS Monitor Bot...")
        asyncio.run(monitor_sms_loop())
