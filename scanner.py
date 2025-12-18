import yfinance as yf
import requests
import os
import pandas as pd
import datetime
import time

# --- CONFIGURATION ---
WATCHLIST_FILE = "watchlist.txt"
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
GOAPI_KEY = os.environ.get("GOAPI_KEY")

# Daftar Broker Ritel (Indikasi Distribusi jika mereka Top Buyer)
RETAIL_BROKERS = ['YP', 'PD', 'KK', 'NI', 'XC', 'CC', 'XL', 'GR', 'SQ']

def get_tickers_from_file():
    """Load watchlist, default ke saham likuid jika file kosong"""
    if not os.path.exists(WATCHLIST_FILE):
        return ["BBRI", "BBCA", "BMRI", "TLKM", "ASII", "ADRO", "UNTR", "GOTO"]
    
    with open(WATCHLIST_FILE, 'r') as f:
        # Bersihkan format ticker (hapus .JK, uppercase, trim)
        codes = [line.strip().upper().replace(".JK", "") for line in f.readlines() if line.strip()]
    return codes

def send_telegram_message(message):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("Telegram Credentials not set.")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    
    # Chunk message agar tidak error jika terlalu panjang
    max_len = 4000
    for i in range(0, len(message), max_len):
        chunk = message[i:i+max_len]
        payload = {"chat_id": CHAT_ID, "text": chunk, "parse_mode": "HTML", "disable_web_page_preview": True}
        requests.post(url, json=payload)

def get_broker_summary(ticker, date_str):
    """
    Mengambil data Broker Summary dari GoAPI.io
    Endpoint: /stock/idx/{ticker}/broker_summary
    """
    # URL UPDATE: Menggunakan domain baru goapi.io
    url = f"https://api.goapi.io/stock/idx/{ticker}/broker_summary"
    
    # Header wajib + User Agent agar lebih aman
    headers = {
        "X-API-KEY": GOAPI_KEY, 
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0 (GitHubActions; PythonScript) v1.0"
    }
    
    params = {"date": date_str}
    
    try:
        # Sleep sebentar untuk rate limiting (penting untuk free/basic plan)
        time.sleep(1) 
        
        response = requests.get(url, headers=headers, params=params, timeout=15)
        
        # Cek status code HTTP
        if response.status_code != 200:
            print(f"GoAPI Error {ticker}: HTTP {response.status_code}")
            return None

        data = response.json()
        
        # Validasi struktur JSON return dari GoAPI.io
        if data.get('status') != 'success' or not data.get('data'):
            return None
            
        summary = data['data']
        
        # Kadang data kosong jika hari libur atau belum update
        if not summary.get('top_buyers') or not summary.get('top_sellers'):
            return None

        return analyze_bandar_flow(summary['top_buyers'], summary['top_sellers'])
        
    except Exception as e:
        print(f"Exception for {ticker}: {e}")
        return None

def analyze_bandar_flow(buyers, sellers):
    """Logika Analisa Akumulasi vs Distribusi"""
    
    # Ambil Top 3 Buyer & Seller
    # Filter: Pastikan data buyer/seller ada isinya
    buyers = buyers[:3] if buyers else []
    sellers = sellers[:3] if sellers else []
    
    if not buyers or not sellers:
        return None

    top3_buy_vol = sum([float(b['volume']) for b in buyers])
    top3_sell_vol = sum([float(s['volume']) for s in sellers])
    
    top1_buyer_code = buyers[0]['code']
    top1_seller_code = sellers[0]['code']
    
    # Logic Penentuan Status
    status = "NEUTRAL"
    strength = 0 # Skala -5 (Distribusi Kuat) s.d +5 (Akumulasi Kuat)
    
    # Rasio Dominasi
    # Jika Top 3 Buyer volume > 1.2x Top 3 Seller volume -> Akumulasi
    if top3_buy_vol > top3_sell_vol * 1.15:
        status = "ACCUMULATION"
        strength = 3
        # Cek Kualitas Broker (Bandar vs Ritel)
        if top1_buyer_code not in RETAIL_BROKERS and top1_seller_code in RETAIL_BROKERS:
            status = "BIG ACCUM (Ritel Jualan)"
            strength = 5 
            
    elif top3_sell_vol > top3_buy_vol * 1.15:
        status = "DISTRIBUTION"
        strength = -3
        if top1_buyer_code in RETAIL_BROKERS:
            status = "BIG DIST (Ritel Nampung)"
            strength = -5

    return {
        "status": status,
        "strength": strength,
        "top_buyer": top1_buyer_code,
        "top_seller": top1_seller_code,
        "top3_buy_codes": ",".join([b['code'] for b in buyers]),
        "top3_sell_codes": ",".join([s['code'] for s in sellers]),
        "buy_avg": int(float(buyers[0]['avg_price']))
    }

def get_technical_data(ticker):
    """Ambil data teknikal untuk Support/Resistance via yfinance"""
    try:
        # Download data
        df = yf.download(f"{ticker}.JK", period="5d", progress=False)
        if len(df) < 2: return None
        
        # Handle MultiIndex column issue in recent yfinance
        if isinstance(df.columns, pd.MultiIndex):
            try:
                # Coba akses langsung per level jika format baru
                curr_close = df['Close'][f"{ticker}.JK"].iloc[-1]
                prev_close = df['Close'][f"{ticker}.JK"].iloc[-2]
                curr_high = df['High'][f"{ticker}.JK"].iloc[-1]
                curr_low = df['Low'][f"{ticker}.JK"].iloc[-1]
                curr_vol = df['Volume'][f"{ticker}.JK"].iloc[-1]
            except KeyError:
                # Fallback flat access
                curr_close = df['Close'].iloc[-1]
                prev_close = df['Close'].iloc[-2]
                curr_high = df['High'].iloc[-1]
                curr_low = df['Low'].iloc[-1]
                curr_vol = df['Volume'].iloc[-1]
        else:
            curr_close = df['Close'].iloc[-1]
            prev_close = df['Close'].iloc[-2]
            curr_high = df['High'].iloc[-1]
            curr_low = df['Low'].iloc[-1]
            curr_vol = df['Volume'].iloc[-1]

        # Pivot Calculation
        P = (curr_high + curr_low + curr_close) / 3
        S1 = (2 * P) - curr_high
        R1 = (2 * P) - curr_low
        
        change_pct = ((curr_close - prev_close) / prev_close) * 100
        
        return {
            "price": int(curr_close),
            "change": float(change_pct),
            "vol": int(curr_vol),
            "s1": int(S1),
            "r1": int(R1),
            "pivot": int(P)
        }
    except Exception as e:
        # print(f"YF Error {ticker}: {e}") # Debug only
        return None

def main():
    if not GOAPI_KEY:
        print("Error: GOAPI_KEY belum diset di GitHub Secrets")
        return

    tickers = get_tickers_from_file()
    
    # Set Tanggal Analisa (Default Hari Ini)
    today = datetime.date.today()
    
    # Jika Weekend (Sabtu/Minggu), mundur ke Jumat terakhir
    if today.weekday() == 5: # Sabtu
        today = today - datetime.timedelta(days=1)
    elif today.weekday() == 6: # Minggu
        today = today - datetime.timedelta(days=2)
        
    date_str = today.strftime("%Y-%m-%d")
    print(f"--- Mulai Analisa: {date_str} ---")
    
    results = []
    
    for ticker in tickers:
        # 1. Analisa Teknikal (yfinance)
        tech = get_technical_data(ticker)
        if not tech: continue
        
        # Filter Likuiditas Minimal (Value Transaksi > 500 Juta)
        # Menghindari saham gorengan super kecil
        if tech['vol'] * tech['price'] < 500_000_000: 
            continue 

        # 2. Analisa Bandarmology (GoAPI.io)
        print(f"Fetching GoAPI for {ticker}...")
        bandar = get_broker_summary(ticker, date_str)
        
        if bandar:
            # Gabungkan Data
            data = {**tech, **bandar, "code": ticker}
            results.append(data)
        else:
            print(f"  -> No data/Failed for {ticker}")
    
    # Sorting: Prioritaskan Strength Terbesar (Akumulasi)
    sorted_stocks = sorted(results, key=lambda x: x['strength'], reverse=True)
    
    # Ambil Top 15 (Yang Akumulasi atau Netral Bagus)
    # Strength >= 0 artinya tidak sedang distribusi parah
    top_picks = [s for s in sorted_stocks if s['strength'] >= 0][:15]

    if not top_picks:
        send_telegram_message(f"⚠️ Report {date_str}: Tidak ada sinyal akumulasi signifikan.")
        return

    # Format Message Telegram
    msg = f"🦅 <b>BANDARMOLOGY REPORT (GoAPI.io)</b>\n"
    msg += f"📅 {date_str}\n"
    msg += "<i>Tracking Smart Money Flow</i>\n"
    msg += "="*20 + "\n\n"
    
    for s in top_picks:
        icon = "🟢"
        if s['strength'] == 5: icon = "🔥🚀" # Big Accum
        elif s['strength'] == 3: icon = "✅" # Normal Accum
        elif s['strength'] == 0: icon = "⚠️" # Neutral
        
        avg_diff = "Murah" if s['price'] < s['buy_avg'] else "Wajar"
        
        msg += f"<b>{s['code']}</b> ({s['change']:+.2f}%) {icon}\n"
        msg += f"├ <b>Status:</b> {s['status']}\n"
        msg += f"├ <b>Top Buyer:</b> {s['top_buyer']} @ {s['buy_avg']}\n"
        msg += f"├ <b>Structure:</b> [{s['top3_buy_codes']}] vs [{s['top3_sell_codes']}]\n"
        msg += f"│\n"
        msg += f"🎯 <b>PLAN BESOK:</b>\n"
        msg += f"├ Buy: {s['s1']} - {s['pivot']}\n"
        msg += f"├ TP: {s['r1']}++\n"
        msg += f"└ CL: < {int(s['s1']*0.97)}\n"
        msg += "-"*20 + "\n"
        
    send_telegram_message(msg)
    print("Report Telegram Terkirim!")

if __name__ == "__main__":
    main()
