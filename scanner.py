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

# --- UNIVERSE SAHAM ---
STOCKS = [
    "BBCA", "BBRI", "BMRI", "BBNI", "BRIS", "ARTO", "BBTN", 
    "ADRO", "PTBA", "ITMG", "PGAS", "MEDC", "AKRA", 
    "ANTM", "INCO", "MDKA", "TINS", "NCKL", "MBMA", "AMMN", "BRMS", "PSAB",
    "TLKM", "EXCL", "ISAT", "TOWR", 
    "ASII", "UNTR", "GOTO", "BUKA", "EMTK", 
    "BSDE", "CTRA", "SMRA", "PANI", "ASRI", 
    "ICBP", "INDF", "MYOR", "UNVR", "KLBF", "CPIN", "JPFA", 
    "BREN", "TPIA", "BRPT", "CUAN", "DEWA", "BUMI", "ENRG", "DAAZ", "SRTG"
]

BROKER_MAP = {
    'YP': 'Mirae', 'PD': 'IndoPremier', 'CC': 'Mandiri', 'NI': 'BNI', 'XC': 'Ajaib', 
    'KK': 'Phillip', 'SQ': 'BCA', 'XL': 'Stockbit', 'GR': 'Panin', 'OD': 'Danareksa',
    'AZ': 'Sucor', 'EP': 'MNC', 'DR': 'RHB', 'YJ': 'Lautandhana', 'CP': 'Valbury', 
    'HP': 'Henan', 'BK': 'JP Morgan', 'ZP': 'Maybank', 'AK': 'UBS', 'RX': 'Macquarie', 
    'KZ': 'CLSA', 'CS': 'Credit Suisse', 'DX': 'Bahana', 'BB': 'Verdhana', 'YU': 'CGS', 
    'LG': 'Trimegah', 'AI': 'UOB', 'MG': 'Semesta', 'RF': 'Buana', 'IF': 'Samuel', 'DH': 'Sinarmas'
}
RETAIL_CODES = ['YP', 'PD', 'XC', 'XL', 'SQ', 'KK', 'NI', 'CC', 'GR', 'DR', 'EP']

def get_time_mode():
    utc_now = datetime.datetime.utcnow()
    wib_now = utc_now + datetime.timedelta(hours=7)
    
    if wib_now.hour < 12:
        date_target = wib_now - datetime.timedelta(days=1)
        while date_target.weekday() > 4: date_target -= datetime.timedelta(days=1)
        return "MORNING", date_target.strftime("%Y-%m-%d")
    else:
        date_target = wib_now
        while date_target.weekday() > 4: date_target -= datetime.timedelta(days=1)
        return "AFTERNOON", date_target.strftime("%Y-%m-%d")

def get_broker_flow(ticker, date_str):
    url = f"https://api.goapi.io/stock/idx/{ticker}/broker_summary"
    headers = {"X-API-KEY": GOAPI_KEY, "Accept": "application/json"}
    
    try:
        time.sleep(0.5) # Perpanjang delay biar API tidak ngambek (Rate Limit)
        res = requests.get(url, headers=headers, params={"date": date_str}, timeout=10)
        
        # DEBUG LOG: Lihat apa respon API sebenarnya
        if res.status_code != 200:
            print(f"   ⚠️ GoAPI Error {ticker}: {res.status_code}")
            return [], []

        data = res.json()
        if data.get('status') == 'success' and data.get('data'):
            d = data['data']
            return d.get('top_buyers', []), d.get('top_sellers', [])
        else:
            return [], []
            
    except Exception as e: 
        print(f"   ⚠️ Connection Error {ticker}: {e}")
        return [], []

def get_technicals(ticker):
    try:
        df = yf.download(f"{ticker}.JK", period="5d", progress=False)
        if df.empty: return None
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.droplevel(1)
        
        close = df['Close'].iloc[-1]
        prev_close = df['Close'].iloc[-2]
        change = ((close - prev_close)/prev_close)*100
        
        # VWAP Simple
        typ = (df['High'] + df['Low'] + df['Close']) / 3
        vwap = (typ * df['Volume']).sum() / df['Volume'].sum()
        
        return {"close": int(close), "change": change, "vwap": int(vwap)}
    except: return None

def analyze_stock(ticker, date_str):
    # 1. Fetch Data
    buyers, sellers = get_broker_flow(ticker, date_str)
    tech = get_technicals(ticker)
    
    # 2. Safety Check: Kalau Technical Gagal, Skip. 
    # (Kalau Bandar gagal gpp, kita masih punya harga)
    if not tech: 
        print(f"   ⚠️ Skip {ticker}: No YFinance Data")
        return None

    # 3. Process Bandarmology (Jika Ada)
    net_money = 0
    top_buy = "-"
    top_sell = "-"
    avg_bandar = tech['vwap'] # Default fallback ke VWAP Technical
    
    has_bandar_data = False
    
    if buyers and sellers:
        has_bandar_data = True
        buy_val = sum([float(x['value']) for x in buyers[:3]])
        sell_val = sum([float(x['value']) for x in sellers[:3]])
        net_money = buy_val - sell_val
        top_buy = buyers[0]['code']
        top_sell = sellers[0]['code']
        avg_bandar = int(float(buyers[0]['avg_price']))
    
    # 4. SCORING & REASONING
    reasoning = []
    score = 0
    
    # Logic: Score naik jika Akumulasi, Score turun jika Distribusi
    if has_bandar_data:
        if net_money > 1_000_000_000:
            score += 3
            if top_buy not in RETAIL_CODES:
                reasoning.append(f"🐳 **PAUS MASUK:** Institusi ({top_buy}) Akumulasi.")
                score += 1
            else:
                reasoning.append("✅ **AKUMULASI:** Net Buy Positif.")
        elif net_money < -1_000_000_000:
            score -= 3
            reasoning.append("⚠️ **DISTRIBUSI:** Tekanan Jual Tinggi.")
    else:
        reasoning.append("ℹ️ Data Bandar N/A (Analisa Teknikal Saja)")

    # Logic: Harga vs Support (Avg Bandar/VWAP)
    # Jika harga dekat Avg Bandar/VWAP (range +/- 2%), itu support kuat
    diff = ((tech['close'] - avg_bandar) / avg_bandar) * 100
    
    if -2 <= diff <= 2:
        score += 2
        reasoning.append(f"💎 **BEST ENTRY:** Harga di area Avg Modal ({avg_bandar}).")
    elif diff < -2:
        score += 1
        reasoning.append("📉 **DISKON:** Di bawah harga wajar.")
    elif diff > 5:
        score -= 1
        reasoning.append("🚀 **PREMIUM:** Harga sudah lari.")

    # Jika score 0, beri sedikit nilai berdasarkan Trend Harga
    if score == 0 and tech['change'] > 0: score = 1
        
    buyer_name = BROKER_MAP.get(top_buy, top_buy)
    
    return {
        "code": ticker,
        "score": score,
        "net_money": net_money,
        "close": tech['close'],
        "change": tech['change'],
        "avg_ref": avg_bandar, # Bisa Avg Bandar atau VWAP
        "buyer": f"{top_buy}-{buyer_name}",
        "reasoning": reasoning
    }

def format_money(val):
    if val == 0: return "N/A"
    v = abs(val)
    if v >= 1_000_000_000: return f"{val/1_000_000_000:.1f}M"
    return f"{val/1_000_000:.0f}jt"

def send_telegram(message):
    if not TELEGRAM_TOKEN or not CHAT_ID: 
        print("❌ Telegram Token Missing")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    for i in range(0, len(message), 4000):
        requests.post(url, json={"chat_id": CHAT_ID, "text": message[i:i+4000], "parse_mode": "Markdown"})

def main():
    mode, date_str = get_time_mode()
    print(f"🚀 RUNNING: {mode} | Target Data: {date_str}")
    
    results = []
    for i, t in enumerate(STOCKS):
        if i % 5 == 0: print(f"Processing {t}...")
        res = analyze_stock(t, date_str)
        if res: results.append(res)
        
    # Urutkan dari Score Tertinggi
    results.sort(key=lambda x: x['score'], reverse=True)
    
    # SAFETY NET: Jika hasil kosong, jangan bilang libur.
    if not results:
        print("❌ CRITICAL: No results generated. Check API/Connection.")
        return

    # REPORTING
    if mode == "MORNING":
        msg = f"☕ *MORNING BRIEFING: {date_str}*\n"
        msg += f"_Top Picks untuk Trading Hari Ini_\n\n"
        
        # Ambil Top 7
        for s in results[:7]:
            icon = "🔥" if s['score'] >= 4 else "✅"
            reasons = "\n".join([f"  • {r}" for r in s['reasoning']])
            
            msg += f"*{s['code']}* ({s['change']:+.1f}%) {icon}\n"
            msg += f"💰 Net: `{format_money(s['net_money'])}`\n"
            msg += f"🎯 Support: *{s['avg_ref']}*\n"
            msg += f"{reasons}\n"
            msg += "----------------------------\n"
    else:
        msg = f"🌇 *MARKET WRAP: {date_str}*\n"
        # ... logic sore (sama seperti sebelumnya) ...
        for s in results[:5]:
            msg += f"*{s['code']}*: Score {s['score']} | Net {format_money(s['net_money'])}\n"

    send_telegram(msg)
    print("✅ Telegram Sent!")

if __name__ == "__main__":
    main()
