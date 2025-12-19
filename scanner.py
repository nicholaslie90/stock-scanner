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

# BATAS AMAN: Gunakan 25 hit saja, sisa 5 buat cadangan
DAILY_API_LIMIT = 25 

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
        print("⚠️ Watchlist file not found.")
        return []
    with open(WATCHLIST_FILE, 'r') as f:
        # Return list ticker bersih
        return list(set([line.strip().upper().replace(".JK", "") for line in f.readlines() if line.strip()]))

def get_last_market_date():
    """
    Trik Hemat Kuota:
    Cek data BBCA di YFinance (Gratis) untuk tahu kapan terakhir market buka.
    Jadi kita TIDAK PERLU buang kuota GoAPI untuk menebak tanggal libur/buka.
    """
    try:
        # Ambil data 7 hari terakhir
        df = yf.download("BBCA.JK", period="7d", progress=False)
        if df.empty:
            # Fallback manual jika YF error
            return (datetime.datetime.now() - datetime.timedelta(days=1)).strftime("%Y-%m-%d")
        
        # Ambil tanggal terakhir dari index dataframe
        last_date = df.index[-1]
        
        # Cek jam sekarang (WIB)
        utc_now = datetime.datetime.utcnow()
        wib_now = utc_now + datetime.timedelta(hours=7)
        
        # Jika run PAGI (sebelum jam 10 pagi), kita pasti mau data KEMARIN (Close sebelumnya)
        # Jika last_date == hari ini, berarti data hari ini sudah masuk (run sore).
        # Jika run pagi, data hari ini blm ada, jadi last_date pasti kemarin (atau jumat lalu).
        
        date_str = last_date.strftime("%Y-%m-%d")
        print(f"📅 Market Date Detected (via YFinance): {date_str}")
        return date_str
    except Exception as e:
        print(f"⚠️ YF Date Check Error: {e}")
        # Default mundur 1 hari
        return (datetime.datetime.now() - datetime.timedelta(days=1)).strftime("%Y-%m-%d")

def filter_top_stocks(tickers, limit):
    """
    FILTER GRATIS:
    Urutkan saham berdasarkan Value Transaksi (Rupiah) menggunakan YFinance.
    Kita hanya akan pakai kuota GoAPI untuk saham yang RAMAI saja.
    """
    print(f"🔍 Pre-screening {len(tickers)} saham via YFinance (Unlimited)...")
    
    yf_tickers = [f"{t}.JK" for t in tickers]
    valid_stocks = []
    
    try:
        # Download batch cepat
        data = yf.download(yf_tickers, period="2d", group_by='ticker', progress=False)
        
        for t in tickers:
            try:
                df = data[f"{t}.JK"]
                if df.empty: continue
                
                # Ambil data terakhir
                close = float(df['Close'].iloc[-1])
                prev = float(df['Close'].iloc[-2])
                vol = float(df['Volume'].iloc[-1])
                val = close * vol # Value Transaksi
                change = ((close - prev) / prev) * 100
                
                valid_stocks.append({
                    'code': t,
                    'value': val,
                    'price': int(close),
                    'change': change
                })
            except:
                continue
                
        # URUTKAN DARI TRANSAKSI TERBESAR
        valid_stocks.sort(key=lambda x: x['value'], reverse=True)
        
        # POTONG SESUAI KUOTA API
        top_picks = valid_stocks[:limit]
        
        print(f"✅ Terpilih {len(top_picks)} saham teramai untuk di-scan Bandarmology.")
        return top_picks
        
    except Exception as e:
        print(f"⚠️ YFinance Batch Error: {e}")
        # Fallback darurat: Ambil list depan aja
        return [{'code': t, 'price': 0, 'change': 0} for t in tickers[:limit]]

def get_broker_summary(ticker, date_str):
    """
    PANGGILAN MAHAL (Hati-hati, ini mengurangi kuota!)
    """
    url = f"https://api.goapi.io/stock/idx/{ticker}/broker_summary"
    headers = {"X-API-KEY": GOAPI_KEY, "Accept": "application/json"}
    
    try:
        # Jeda 1 detik biar sopan
        time.sleep(1.0) 
        
        res = requests.get(url, headers=headers, params={"date": date_str}, timeout=10)
        
        if res.status_code == 429:
            print("🛑 KUOTA HABIS / RATE LIMIT!")
            return None
        
        if res.status_code != 200:
            print(f"   ❌ API Error {ticker}: {res.status_code}")
            return None
            
        data = res.json()
        if data.get('status') == 'success' and data.get('data'):
            return data['data']
            
    except Exception as e:
        print(f"   ⚠️ Connection Exception: {e}")
    
    return None

def analyze_flow(stock_info, broker_data):
    if not broker_data or 'top_buyers' not in broker_data: return None

    buyers = broker_data.get('top_buyers', [])
    sellers = broker_data.get('top_sellers', [])
    if not buyers or not sellers: return None

    # Hitung Net Buy Top 3
    buy_val = sum([float(x['value']) for x in buyers[:3]])
    sell_val = sum([float(x['value']) for x in sellers[:3]])
    net_money = buy_val - sell_val
    
    top_buyer = buyers[0]['code']
    top_seller = sellers[0]['code']
    avg_price = int(float(buyers[0]['avg_price']))
    
    score = 0
    tags = []
    
    # Scoring Logic
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
    elif top_buyer in ['BK', 'AK', 'ZP', 'MG', 'BB', 'CC']:
        score += 2
        tags.append("WHALE BUY")
        
    if top_seller in RETAIL_CODES and "WHALE BUY" in tags:
        score += 2
        tags.append("EATING RETAIL")

    return {
        "code": stock_info['code'],
        "score": score,
        "net_money": net_money,
        "avg_price": avg_price,
        "curr_price": stock_info['price'],
        "change": stock_info['change'],
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
        print("❌ API Key Missing")
        return

    # 1. SETUP & CEK TANGGAL (Gratis)
    my_stocks = get_my_watchlist()
    target_date = get_last_market_date() # Ini pakai YFinance (Gratis)
    
    print(f"💀 SNIPER MODE: Target Date {target_date}")
    
    # 2. FILTERING (Gratis)
    # Hanya ambil Top 25 saham teramai dari watchlist Anda
    target_stocks = filter_top_stocks(my_stocks, limit=DAILY_API_LIMIT)
    
    results = []
    
    # 3. EKSEKUSI (Berbayar - Hemat Hits)
    print(f"🚀 Scanning {len(target_stocks)} saham prioritas...")
    for i, stock in enumerate(target_stocks):
        print(f"   [{i+1}/{len(target_stocks)}] Cek Bandar {stock['code']}...")
        
        b_data = get_broker_summary(stock['code'], target_date)
        
        if b_data:
            res = analyze_flow(stock, b_data)
            if res: results.append(res)
        else:
            print(f"     -> No Data / Error")
            
    # Urutkan pemenang
    winners = sorted(results, key=lambda x: x['score'], reverse=True)
    
    if not winners:
        send_telegram(f"⚠️ Report {target_date}: Tidak ada data/Market Sepi.")
        return

    # 4. REPORTING
    msg = f"💀 *BANDAR SNIPER REPORT*\n"
    msg += f"📅 Data: {target_date}\n"
    msg += f"🔍 Scanned: {len(target_stocks)} Most Active Stocks\n\n"
    
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
        msg += f"💰 Net: `{format_money(s['net_money'])}`\n"
        msg += f"🛒 Buy: *{b_name}* (Avg {s['avg_price']})\n"
        msg += f"📦 Sell: {s_name}\n"
        msg += f"📊 Posisi: {posisi}\n"
        msg += "----------------------------\n"
        
    send_telegram(msg)
    print("✅ Report Sent!")

if __name__ == "__main__":
    main()
