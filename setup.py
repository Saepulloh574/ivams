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
# --- Import Tambahan untuk Flask ---
from flask import Flask, jsonify, send_file
from threading import Thread
# -----------------------------------

# Muat variabel lingkungan
load_dotenv()

# ================= KONSTANTA & KONFIGURASI BOT (SAMA) =================
# ... (Semua konstanta, BOT, CHAT, ADMIN_ID, dan fungsi utility seperti clean_phone_number, format_otp_message, dll. tetap sama) ...
# PENTING: Pastikan semua fungsi utility yang dibutuhkan tetap di atas.

# Inisialisasi Bot dan Filter
otp_filter = OTPFilter()
start = time.time()
total_sent = 0
monitor = SMSMonitor()
# Variabel Global untuk Status
BOT_STATUS = {
    "status": "Initializing...",
    "uptime": "--",
    "total_otps_sent": 0,
    "last_check": "--",
    "cache_size": 0,
    "monitoring_active": True
}


# ================= FUNGSI UPDATE STATUS GLOBAL =================
def update_global_status(uptime_seconds):
    global BOT_STATUS
    uptime = uptime_seconds
    
    BOT_STATUS["uptime"] = f"{int(uptime//3600)}h {int((uptime%3600)//60)}m {int(uptime%60)}s"
    BOT_STATUS["total_otps_sent"] = total_sent
    BOT_STATUS["last_check"] = datetime.now().strftime("%H:%M:%S")
    BOT_STATUS["cache_size"] = len(otp_filter.cache)
    BOT_STATUS["status"] = "Running" if BOT_STATUS["monitoring_active"] else "Paused"
    
    return BOT_STATUS

# ================= FUNGSI MONITOR LOOP (MODIFIKASI RINGAN) =================

async def monitor_sms_loop():
    global total_sent
    global BOT_STATUS

    # ... (Logika inisialisasi dan koneksi browser SAMA) ...
    try:
        await monitor.initialize()
    except Exception as e:
        print(f"FATAL ERROR: Failed to initialize SMSMonitor... {e}")
        send_tg("🚨 **FATAL ERROR**: Gagal terhubung ke Chrome/Pyppeteer...")
        BOT_STATUS["status"] = "FATAL ERROR"
        return

    while True:
        try:
            # ... (Logika fetch_sms dan filter SAMA) ...
            
            # --- Update Global Status setelah setiap pengecekan ---
            uptime_seconds = time.time() - start
            current_stats = update_global_status(uptime_seconds)

            check_cmd(current_stats) # Cek perintah Telegram
            
        except Exception as e:
            # ... (Logika penanganan error SAMA) ...
            pass
        
        await asyncio.sleep(5) # Delay 5 detik

# ================= FLASK WEB SERVER UNTUK DASHBOARD =================

app = Flask(__name__)

# --- Simpan HTML Dashboard ke file sementara (atau buat file index.html) ---
DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Telegram OTP Bot - Dashboard</title>
    <style>
        /* ... (CSS Anda yang panjang DITEMPATKAN DI SINI) ... */
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            margin: 0;
            padding: 20px;
            min-height: 100vh;
        }
        .container {
            max-width: 800px;
            margin: 0 auto;
            background: white;
            border-radius: 15px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.2);
            overflow: hidden;
        }
        .header {
            background: linear-gradient(45deg, #1e3c72, #2a5298);
            color: white;
            padding: 30px;
            text-align: center;
        }
        .header h1 {
            margin: 0;
            font-size: 2.5em;
        }
        .header p {
            margin: 10px 0 0 0;
            opacity: 0.9;
        }
        .content {
            padding: 30px;
        }
        .status-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }
        .status-card {
            background: #f8f9fa;
            border-radius: 10px;
            padding: 20px;
            border-left: 4px solid #007bff;
        }
        .status-card h3 {
            margin: 0 0 10px 0;
            color: #333;
            font-size: 1.1em;
        }
        .status-value {
            font-size: 1.5em;
            font-weight: bold;
            color: #007bff;
        }
        .buttons {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
            margin-top: 30px;
        }
        .btn {
            background: #007bff;
            color: white;
            border: none;
            padding: 12px 20px;
            border-radius: 8px;
            cursor: pointer;
            font-size: 1em;
            transition: all 0.3s ease;
            text-decoration: none;
            text-align: center;
            display: block;
        }
        .btn:hover {
            background: #0056b3;
            transform: translateY(-2px);
        }
        .btn.success { background: #28a745; }
        .btn.success:hover { background: #1e7e34; }
        .btn.warning { background: #ffc107; color: #212529; }
        .btn.warning:hover { background: #e0a800; }
        .btn.danger { background: #dc3545; }
        .btn.danger:hover { background: #c82333; }
        .logs {
            background: #1e1e1e;
            color: #00ff00;
            border-radius: 8px;
            padding: 20px;
            margin-top: 20px;
            font-family: 'Courier New', monospace;
            max-height: 300px;
            overflow-y: auto;
        }
        .feature-list {
            background: #e9ecef;
            border-radius: 8px;
            padding: 20px;
            margin-top: 20px;
        }
        .feature-list h3 {
            margin-top: 0;
            color: #333;
        }
        .feature-list ul {
            margin: 0;
            padding-left: 20px;
        }
        .feature-list li {
            margin: 8px 0;
            color: #555;
        }
        .alert {
            background: #d1ecf1;
            border: 1px solid #bee5eb;
            border-radius: 8px;
            padding: 15px;
            margin-bottom: 20px;
            color: #0c5460;
        }
        .footer {
            text-align: center;
            padding: 20px;
            color: #6c757d;
            border-top: 1px solid #dee2e6;
            margin-top: 30px;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🤖 Telegram OTP Bot</h1>
            <p>Automated IVASMS OTP Monitoring & Telegram Integration</p>
        </div>
        
        <div class="content">
            <div class="alert">
                <strong>📡 Status:</strong> <span id="botStatus">Loading...</span>
            </div>
            
            <div class="status-grid">
                <div class="status-card">
                    <h3>⏱️ Uptime</h3>
                    <div class="status-value" id="uptime">--</div>
                </div>
                <div class="status-card">
                    <h3>📨 OTPs Sent</h3>
                    <div class="status-value" id="otpsSent">--</div>
                </div>
                <div class="status-card">
                    <h3>🔍 Last Check</h3>
                    <div class="status-value" id="lastCheck">--</div>
                </div>
                <div class="status-card">
                    <h3>💾 Cache Size</h3>
                    <div class="status-value" id="cacheSize">--</div>
                </div>
            </div>
            
            <div class="buttons">
                <a href="/manual-check" class="btn">🔍 Manual Check</a>
                <a href="/test-message" class="btn success">📤 Test Message</a>
                <a href="/telegram-status" class="btn">📊 Send Status</a>
                <a href="/clear-cache" class="btn warning">🗑️ Clear Cache</a>
                <a href="#" class="btn success disabled">▶️ Monitor Running</a>
                <a href="#" class="btn danger disabled">⏹️ Monitor Running</a>
            </div>
            
            <div class="feature-list">
                <h3>🎯 Bot Features</h3>
                <ul>
                    <li>✅ Automatic IVASMS login and OTP extraction</li>
                    <li>✅ Real-time Telegram notifications with touch-to-copy format</li>
                    <li>✅ Duplicate OTP filtering with smart caching</li>
                    <li>✅ Background monitoring with 5-second intervals</li>
                    <li>✅ Live Status Dashboard (This page!)</li>
                    <li>✅ Auto-Refresh & Screenshot to Admin after OTPs are sent.</li>
                    <li>✅ Comprehensive error handling and logging</li>
                    <li>✅ Security-focused with environment variable management</li>
                </ul>
            </div>
            
            <div class="logs" id="consoleLogs">
                <div>🚀 Bot Dashboard Loaded</div>
                <div>📡 Checking connection status...</div>
                <div>⚡ Ready for OTP monitoring</div>
            </div>
        </div>
        
        <div class="footer">
            <p>💡 <strong>Tip:</strong> Use UptimeRobot to ping this dashboard every 5 minutes to keep the bot alive on free hosting platforms.</p>
            <p>🔐 <strong>Security:</strong> This bot should only be used for authorized accounts and ethical purposes.</p>
        </div>
    </div>

    <script>
        // Auto-refresh status every 30 seconds
        function updateStatus() {
            // Meminta data dari endpoint Flask /api/status
            fetch('/api/status')
                .then(response => response.json())
                .then(data => {
                    // Update Status Cards
                    document.getElementById('botStatus').textContent = data.status || 'Unknown';
                    document.getElementById('uptime').textContent = data.uptime || '--';
                    document.getElementById('otpsSent').textContent = data.total_otps_sent || '0';
                    document.getElementById('lastCheck').textContent = data.last_check || 'Never';
                    document.getElementById('cacheSize').textContent = data.cache_size || '0';
                    
                    // Update Log Entry
                    const logs = document.getElementById('consoleLogs');
                    const timestamp = new Date().toLocaleTimeString();
                    logs.innerHTML += \`<div>📊 [\${timestamp}] Status updated - \${data.total_otps_sent} OTPs sent</div>\`;
                    logs.scrollTop = logs.scrollHeight;
                    
                    // Update status bar color
                    const alertDiv = document.querySelector('.alert');
                    if (data.status.includes('Running')) {
                        alertDiv.style.backgroundColor = '#d4edda'; // Greenish
                        alertDiv.style.borderColor = '#c3e6cb';
                        alertDiv.style.color = '#155724';
                    } else if (data.status.includes('FATAL')) {
                        alertDiv.style.backgroundColor = '#f8d7da'; // Reddish
                        alertDiv.style.borderColor = '#f5c6cb';
                        alertDiv.style.color = '#721c24';
                    } else {
                        alertDiv.style.backgroundColor = '#d1ecf1'; // Blueish (default)
                        alertDiv.style.borderColor = '#bee5eb';
                        alertDiv.style.color = '#0c5460';
                    }

                })
                .catch(error => {
                    console.error('Error updating status:', error);
                    document.getElementById('botStatus').textContent = 'Web Server Connection Error';
                });
        }

        // Update status immediately and then every 30 seconds
        updateStatus();
        setInterval(updateStatus, 30000);

        // Add click handlers to buttons (untuk logging di dashboard saja)
        document.querySelectorAll('a.btn').forEach(button => {
            button.addEventListener('click', function(e) {
                const logs = document.getElementById('consoleLogs');
                const timestamp = new Date().toLocaleTimeString();
                const action = this.textContent;
                logs.innerHTML += \`<div>🔥 [\${timestamp}] Action: \${action} sent to backend.</div>\`;
                logs.scrollTop = logs.scrollHeight;
            });
        });
    </script>
</body>
</html>
"""
# --------------------------------------------------------------------------

@app.route('/', methods=['GET'])
def dashboard_html():
    """Menyajikan halaman HTML dashboard."""
    return DASHBOARD_HTML

@app.route('/api/status', methods=['GET'])
def get_status_json():
    """Mengembalikan data status bot dalam format JSON."""
    return jsonify(BOT_STATUS)

# --- Endpoint sederhana untuk memicu perintah Telegram ---

@app.route('/telegram-status', methods=['GET'])
def send_telegram_status():
    """Memanggil fungsi untuk mengirim status ke Telegram (HANYA admin)."""
    if ADMIN_ID is None:
        return jsonify({"message": "Error: Admin ID not configured."}), 400
    
    # Kirim status ke admin
    send_tg(get_status_message(BOT_STATUS), target_chat_id=ADMIN_ID)
    
    return jsonify({"message": "Status sent to Telegram Admin."})

@app.route('/clear-cache', methods=['GET'])
def clear_otp_cache():
    """Membersihkan cache OTP."""
    global otp_filter
    otp_filter.cache = {}
    otp_filter._save()
    
    return jsonify({"message": "OTP Cache cleared successfully."})


# ================= FUNGSI UTAMA START =================

def run_flask():
    """Fungsi untuk menjalankan Flask di thread terpisah."""
    # Anda mungkin ingin mengubah port di lingkungan produksi
    app.run(host='0.0.0.0', port=os.getenv("PORT", 5000), debug=False, use_reloader=False)

if __name__ == "__main__":
    if not BOT or not CHAT:
        print("FATAL ERROR: Pastikan TELEGRAM_BOT_TOKEN dan TELEGRAM_CHAT_ID ada di file .env.")
    else:
        print("Starting SMS Monitor Bot and Flask Dashboard...")
        
        # 1. Mulai Flask di thread terpisah
        flask_thread = Thread(target=run_flask)
        flask_thread.start()
        print(f"✅ Flask Dashboard running on http://0.0.0.0:{os.getenv('PORT', 5000)}")
        
        # 2. Kirim Pesan Aktivasi Telegram
        send_tg("✅ <b>BOT ACTIVE MONITORING IS RUNNING.</b>\nDashboard: http://localhost:5000", with_inline_keyboard=False)
        
        # 3. Mulai loop asinkron monitoring
        try:
            asyncio.run(monitor_sms_loop())
        except KeyboardInterrupt:
            print("Bot shutting down...")
        finally:
            # Di lingkungan yang kompleks, menghentikan Flask thread dan Pyppeteer mungkin diperlukan,
            # tetapi untuk skrip sederhana, ini cukup.
            pass
