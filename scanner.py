import requests
import os
import datetime
import time
import pandas as pd
import yfinance as yf

# --- CONFIGURATION ---
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
GOAPI_KEY = os.environ.get("GOAPI_KEY")
WATCHLIST_FILE = "watchlist.txt"

# --- KAMUS BROKER ---
BROKER_MAP = {
    'YP': 'Mirae (Ritel)', 'PD': 'IndoPremier (Ritel)', 'XC': 'Ajaib (Ritel)', 
    'XL': 'Stockbit (Ritel)', 'SQ': 'BCA Sekuritas', 'NI': 'BNI Sekuritas',
    'KK': 'Phillip (Ritel)', 'CC': 'Mandiri', 'DR': 'RHB', 'OD': 'Danareksa',
    'AZ': 'Sucor', 'MG': 'Semesta (Bandar)', 'BK': 'JP Morgan', 'AK': 'UBS', 
    'ZP': 'Maybank', 'KZ': 'CLSA', 'RX': 'Macquarie', 'BB': 'Verdhana', 
    'AI': 'UOB', 'YU': 'CGS CIMB', 'LG': 'Trimegah', 'RF': 'Buana', 
    'IF': 'Samuel', 'CP': 'Valbury', 'HP': 'Henan Putihrai', 'YJ': 'Lautandhana'
}
RETAIL_CODES = ['YP', 'PD', 'XC', 'XL', 'KK', 'CC', 'NI', 'SQ']

def get_my_watchlist():
    if not os.path.exists(WATCHLIST_FILE):
        print("⚠️ Watchlist file not found, using default.")
        return ["BBCA", "BBRI", "BMRI", "ADRO", "TLKM", "ASII", "GOTO", "ANTM"]
    with open(WATCHLIST_FILE, 'r') as f:
        return list(set([line.strip().upper().replace(".JK", "") for line in f.readlines() if line.strip()]))

def get_initial_target_date():
    utc_now = datetime.datetime.utcnow()
    wib_now = utc_now + datetime.timedelta(hours=7)
    
    if wib_now.hour < 12:
        start_date = wib_now - datetime.timedelta(days=1)
    else:
        start_date = wib_now
    return start_date

def fetch_data_with_fallback(ticker, start_date):
    """
    Mengambil data dengan Debugging Print yang lengkap
    """
    current_check_date = start_date
    # Kurangi retry jadi 3 hari saja dulu biar ga abis kuota/kena limit
    max_retries = 3 
    
    url = f"https://api.goapi.io/stock/idx/{ticker}/broker_summary"
    headers = {"X-API-KEY": GOAPI_KEY, "Accept": "application/json"}
    
    for i in range(max_retries):
        while current_check_date.weekday() > 4:
            current_check_date -= datetime.timedelta(days=1)
            
        date_str = current_check_date.strftime("%Y-%m-%d")
        
        try:
            # DEBUG: Print URL yang ditembak (biar tau script jalan)
            # print(f"   🔎 Checking {ticker} on {date_str}...") 
            
            # PENTING: Jeda diperlama jadi 1.5 detik per request
            # GoAPI Free Tier sangat sensitif.
            time.sleep(1.5) 
            
            res = requests.get(url, headers=headers, params={"date": date_str}, timeout=10)
            
            # DIAGNOSA ERROR
            if res.status_code != 200:
                print(f"   ❌ API Error {res.status_code} for {ticker}: {res.text}")
                # Jika errornya 429 (Too Many Requests), berhenti maksa
                if res.status_code == 429:
                    print("   ⚠️ RATE LIMIT HIT! Istirahat 5 detik...")
                    time.sleep(5)
                # Lanjut ke tanggal berikutnya (loop continue)
                current_check_date -= datetime.timedelta(days=1)
                continue

            data = res.json()
            
            if data.get('status') == 'success' and data.get('data'):
                d = data['data']
                if 'top_buyers' in d and d['top_buyers']:
                    return d, date_str
            else:
                # API 200 OK tapi data kosong/message error dari API
                # print(f"   ⚠️ Data Empty for {ticker}: {data}") # Uncomment kalo mau liat detail
                pass
                
        except Exception as e:
            print(f"   🔥 Exception Connection: {e}")
        
        current_check_date -= datetime.timedelta(days=1)
        
    return None, None

def analyze_flow(ticker, data, found_date):
    if not data: return None

    buyers = data.get('top_buyers', [])
    sellers = data.get('top_sellers', [])
    if not buyers or not sellers: return None

    buy_val = sum([float(x['value']) for x in buyers[:3]])
    sell_val = sum([float(x['value']) for x in sellers[:3]])
    net_money = buy_val - sell_val
    
    top_buyer = buyers[0]['code']
    top_seller = sellers[0]['code']
    avg_price = int(float(buyers[0]['avg_price']))
    
    score = 0
    tags = []
    
    if net_money > 1_000_000_000:
        score += 3
        tags.append("BIG ACCUM")
    elif net_money > 200_000_000:
        score += 1
    elif net_money < -500_000_000:
        score -= 5
        tags.append("DISTRIBUSI")
        
    if top_buyer in RETAIL_CODES:
        score -= 2
        tags.append("RETAIL BUY")
    elif top_buyer in ['BK', 'AK', 'ZP', 'MG', 'BB', 'KZ', 'RX', 'CC']:
        score += 2
        tags.append("WHALE BUY")
        
    if top_seller in RETAIL_CODES and "WHALE BUY" in tags:
        score += 2
        tags.append("EATING RETAIL")

    curr_price = avg_price
    change = 0
    try:
        # PENTING: YFinance juga butuh jeda biar ga diblok
        time.sleep(0.5) 
        df = yf.download(f"{ticker}.JK", period="2d", progress=False)
        if not df.empty:
            # Handle MultiIndex column (YFinance update terbaru)
            if isinstance(df.columns, pd.MultiIndex):
                # Ambil kolom Close untuk ticker tersebut
                # Struktur biasanya ('Close', 'BBCA.JK')
                close_col = df['Close']
                if isinstance(close_col, pd.DataFrame):
                    curr_price = int(close_col.iloc[-1].iloc[0])
                    prev = close_col.iloc[-2].iloc[0]
                else:
                    curr_price = int(close_col.iloc[-1])
                    prev = close_col.iloc[-2]
            else:
                curr_price = int(df['Close'].iloc[-1])
                prev = df['Close'].iloc[-2]
                
            change = ((curr_price - prev) / prev) * 100
    except Exception as e: 
        # print(f"YF Error: {e}") 
        pass

    return {
        "code": ticker,
        "date": found_date, 
        "score": score,
        "net_money": net_money,
        "avg_price": avg_price,
        "curr_price": curr_price,
        "change": change,
        "top_buyer": top_buyer,
        "top_seller": top_seller,
        "tags": tags
    }

def format_money(val):
    if abs(val) >= 1_000_000_000: return f"{val/1_000_000_000:.1f} M"
    if abs(val) >= 1_000_000: return f"{val/1_000_000:.0f} jt"
    return str(int(val))

def send_telegram(message):
    if not TELEGRAM_TOKEN or not CHAT_ID: return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    for i in range(0, len(message), 4000):
        requests.post(url, json={"chat_id": CHAT_ID, "text": message[i:i+4000], "parse_mode": "Markdown"})

def main():
    if not GOAPI_KEY: 
        print("❌ CRITICAL: GOAPI_KEY is missing from env!")
        return
    else:
        # Print 4 huruf awal key untuk memastikan key terbaca benar
        print(f"🔑 API Key Detected: {GOAPI_KEY[:4]}****")

    my_stocks = get_my_watchlist()
    start_date_obj = get_initial_target_date()
    
    print(f"💀 BANDAR WATCHLIST DEBUG MODE")
    print(f"📅 Start Checking from: {start_date_obj.strftime('%Y-%m-%d')}")
    print(f"📋 Total Stocks: {len(my_stocks)}")
    
    results = []
    
    for i, ticker in enumerate(my_stocks):
        # Progress Log
        print(f"[{i+1}/{len(my_stocks)}] Scanning {ticker}...")
        
        data, found_date = fetch_data_with_fallback(ticker, start_date_obj)
        
        if data and found_date:
            print(f"   ✅ Data Found: {found_date}")
            res = analyze_flow(ticker, data, found_date)
            if res: results.append(res)
        else:
            print(f"   ❌ No Data (Checked 3 days back)")
            
    winners = sorted(results, key=lambda x: x['score'], reverse=True)
    
    if not winners:
        print("⚠️ No valid data found for any stock. Check logs above for API Errors.")
        return

    # Reporting
    msg = f"💀 *BANDARMOLOGY REPORT* (Fix)\n"
    msg += f"_Analisa Smart Money_\n\n"
    
    for s in winners:
        icon = "⚪"
        if s['score'] >= 3: icon = "🟢"
        if "EATING RETAIL" in s['tags']: icon = "🐳🔥"
        if s['score'] < 0: icon = "🔴"
        
        b_name = BROKER_MAP.get(s['top_buyer'], s['top_buyer'])
        s_name = BROKER_MAP.get(s['top_seller'], s['top_seller'])
        
        posisi = "Wajar"
        if s['curr_price'] < s['avg_price']: posisi = "💎 Diskon"
        elif s['curr_price'] > s['avg_price'] * 1.05: posisi = "⚠️ Premium"
        
        msg += f"*{s['code']}* ({s['change']:+.1f}%) {icon}\n"
        msg += f"📅 {s['date']}\n" 
        msg += f"💰 Net: `{format_money(s['net_money'])}`\n"
        msg += f"🛒 Buy: *{b_name}* (Avg {s['avg_price']})\n"
        msg += f"📦 Sell: {s_name}\n"
        msg += f"📊 Posisi: {posisi}\n"
        msg += "----------------------------\n"
        
    send_telegram(msg)
    print("✅ Report Sent!")

if __name__ == "__main__":
    main()
