import requests
import os
import datetime
import time
import pandas as pd
import yfinance as yf
from tradingview_screener import Query, Column

# --- CONFIGURATION ---
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
GOAPI_KEY = os.environ.get("GOAPI_KEY")

# --- KAMUS BROKER ---
BROKER_MAP = {
    'YP': 'Mirae', 'PD': 'IndoPremier', 'CC': 'Mandiri', 'NI': 'BNI', 
    'XC': 'Ajaib', 'KK': 'Phillip', 'SQ': 'BCA', 'XL': 'Stockbit', 
    'GR': 'Panin', 'OD': 'Danareksa', 'AZ': 'Sucor', 'EP': 'MNC', 
    'DR': 'RHB', 'YJ': 'Lautandhana', 'CP': 'Valbury', 'HP': 'Henan Putihrai',
    'BK': 'JP Morgan', 'ZP': 'Maybank', 'AK': 'UBS', 'RX': 'Macquarie', 
    'KZ': 'CLSA', 'CS': 'Credit Suisse', 'DX': 'Bahana', 'BB': 'Verdhana', 
    'YU': 'CGS CIMB', 'LG': 'Trimegah', 'AI': 'UOB', 'MG': 'Semesta',
    'RF': 'Buana', 'IF': 'Samuel', 'DH': 'Sinarmas', 'XZ': 'Trimegah(R)'
}

RETAIL_CODES = ['YP', 'PD', 'XC', 'XL', 'SQ', 'KK', 'NI', 'CC', 'GR', 'DR', 'YJ']

def get_dynamic_universe():
    print("🔄 Screening Top Volume (TradingView)...")
    try:
        # Cari saham likuid & trending hari ini
        qh = Query() \
            .select('name', 'close', 'volume', 'Value.Traded') \
            .set_markets('indonesia') \
            .where(
                Column('close') >= 60,
                Column('Value.Traded') > 3000000000 # > 3 Miliar
            ) \
            .order_by('volume', ascending=False) \
            .limit(15) 
            
        raw_data = qh.get_scanner_data()
        
        target_data = raw_data[1] if isinstance(raw_data, tuple) else raw_data
        clean_tickers = []
        for row in target_data:
            ticker_raw = row[0] if isinstance(row[0], str) else row[1] 
            if "IDX:" in str(ticker_raw):
                clean_tickers.append(ticker_raw.replace("IDX:", ""))
        
        return clean_tickers
    except Exception as e:
        print(f"⚠️ TV Error: {e}")
        return ["BBRI", "BBCA", "BMRI", "ADRO", "TLKM", "ASII", "GOTO", "ANTM", "BRMS", "BUMI", "PANI"]

def get_3month_context(ticker):
    """
    Menghitung VWAP & Trend 3 Bulan terakhir menggunakan yfinance.
    Ini adalah proxy 'Average Price' Bandar selama 1 kuartal.
    """
    try:
        # Ambil data 3 bulan + sedikit buffer
        df = yf.download(f"{ticker}.JK", period="3mo", progress=False)
        if df.empty: return None

        # Handle MultiIndex column (yfinance baru)
        if isinstance(df.columns, pd.MultiIndex):
            close = df['Close'][f"{ticker}.JK"]
            volume = df['Volume'][f"{ticker}.JK"]
            high = df['High'][f"{ticker}.JK"]
            low = df['Low'][f"{ticker}.JK"]
        else:
            close = df['Close']
            volume = df['Volume']
            high = df['High']
            low = df['Low']

        # 1. Hitung VWAP 3 Bulan (Harga Rata-rata Tertimbang Volume)
        # Rumus: Sum(Price * Volume) / Sum(Volume)
        # Kita pakai (High+Low+Close)/3 sebagai Typical Price harian
        typical_price = (high + low + close) / 3
        vwap_3mo = (typical_price * volume).sum() / volume.sum()
        
        curr_price = close.iloc[-1]
        
        # 2. Status Posisi (Diskon / Premium)
        diff_pct = ((curr_price - vwap_3mo) / vwap_3mo) * 100
        
        position_status = "WAJAR"
        if diff_pct < -2.0: position_status = "DISKON (Undervalued)"
        elif diff_pct > 5.0: position_status = "MAHAL (Premium)"
        
        return {
            "vwap": int(vwap_3mo),
            "curr_price": int(curr_price),
            "diff_pct": diff_pct,
            "position": position_status
        }
    except Exception as e:
        print(f"   ⚠️ YF Context Error {ticker}: {e}")
        return None

def get_broker_summary(ticker, date_str):
    url = f"https://api.goapi.io/stock/idx/{ticker}/broker_summary"
    headers = {"X-API-KEY": GOAPI_KEY, "Accept": "application/json", "User-Agent": "Bot/3.0"}
    params = {"date": date_str}
    
    try:
        time.sleep(0.3) 
        response = requests.get(url, headers=headers, params=params, timeout=10)
        data = response.json()
        
        if data.get('status') != 'success' or not data.get('data'): return None
        summary = data['data']
        buyers = summary.get('top_buyers', [])
        sellers = summary.get('top_sellers', [])
        
        if not buyers or not sellers: return None
        return analyze_bandar(ticker, buyers, sellers)
    except Exception:
        return None

def clean_broker(code):
    name = BROKER_MAP.get(code, "")
    return f"{code}-{name}" if name else code

def analyze_bandar(ticker, buyers, sellers):
    buy_val = sum([float(x['value']) for x in buyers[:3]])
    sell_val = sum([float(x['value']) for x in sellers[:3]])
    net_money = buy_val - sell_val
    
    b1 = buyers[0]['code']
    s1 = sellers[0]['code']
    avg_price = int(float(buyers[0]['avg_price']))
    
    status = "Netral"
    score = 0
    
    if net_money > 0:
        status = "Akumulasi"
        score = 1
        if b1 not in RETAIL_CODES and s1 in RETAIL_CODES:
            status = "🔥 PAUS MASUK"
            score = 3
    elif net_money < 0:
        status = "Distribusi"
        score = -1
        if b1 in RETAIL_CODES:
            status = "⚠️ GUYUR RITEL" 
            score = -3
            
    return {
        "net_money": net_money,
        "score": score,
        "status": status,
        "buyer": clean_broker(b1),
        "seller": clean_broker(s1),
        "avg_daily": avg_price
    }

def format_money(val):
    val = float(val)
    if abs(val) >= 1_000_000_000: return f"{val/1_000_000_000:.1f} M"
    elif abs(val) >= 1_000_000: return f"{val/1_000_000:.0f} jt"
    return f"{val:.0f}"

def get_last_trading_day():
    d = datetime.date.today()
    while d.weekday() > 4: d -= datetime.timedelta(days=1)
    return d.strftime("%Y-%m-%d")

def send_telegram(message):
    if not TELEGRAM_TOKEN or not CHAT_ID: return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    max_len = 4000
    for i in range(0, len(message), max_len):
        requests.post(url, json={"chat_id": CHAT_ID, "text": message[i:i+max_len], "parse_mode": "HTML", "disable_web_page_preview": True})

def main():
    if not GOAPI_KEY:
        print("❌ GOAPI_KEY Missing")
        return

    # 1. Universe
    tickers = get_dynamic_universe()
    date_str = get_last_trading_day()
    print(f"🕵️ Analyzing {len(tickers)} stocks (3-Mo Context + Daily Flow)...")
    
    results = []
    
    for t in tickers:
        # A. Get Technical Context (3 Bulan)
        ctx = get_3month_context(t)
        
        # B. Get Broker Flow (Hari Ini)
        flow = get_broker_summary(t, date_str)
        
        if ctx and flow:
            # Gabungkan Data
            combined = {**ctx, **flow, "code": t}
            results.append(combined)
            
    # 2. Filtering Strategy
    # Kita cari saham yang: Net Buy Positif DAN (Diskon ATAU Baru Breakout Wajar)
    winners = sorted([x for x in results if x['net_money'] > 0], key=lambda x: x['net_money'], reverse=True)
    
    if not winners:
        send_telegram("⚠️ Market Sepi. Tidak ada sinyal kuat.")
        return

    # 3. Reporting
    msg = f"🦅 <b>SWING TRADER INSIGHT (3-Mo View)</b>\n"
    msg += f"📅 Data: {date_str}\n"
    msg += f"<i>VWAP 3 Bulan vs Arus Bandar Hari Ini</i>\n"
    msg += "="*25 + "\n\n"
    
    for s in winners[:10]:
        icon = "🟢"
        if s['score'] >= 3: icon = "🐳🔥"
        
        # Analisa Posisi
        pos_note = ""
        if "DISKON" in s['position']: 
            pos_note = "💎 <b>BEST BUY</b> (Undervalued)"
        elif "MAHAL" in s['position']:
            pos_note = "⚠️ <b>RAWAN</b> (Sudah Tinggi)"
        else:
            pos_note = "✅ <b>ON TRACK</b>"

        msg += f"<b>{s['code']}</b> {icon}\n"
        msg += f"💰 Net: <b>+{format_money(s['net_money'])}</b>\n"
        msg += f"📊 Posisi 3-Bulan: {s['position']}\n"
        msg += f"   • Harga Skrg: {s['curr_price']}\n"
        msg += f"   • Rata2 Pemain (3Mo): {s['vwap']}\n"
        msg += f"🛒 Aksi Hari Ini:\n"
        msg += f"   • {s['buyer']} akumulasi di avg {s['avg_daily']}\n"
        msg += f"   • {pos_note}\n"
        msg += "-"*20 + "\n"
        
    send_telegram(msg)
    print("Report Sent!")

if __name__ == "__main__":
    main()
