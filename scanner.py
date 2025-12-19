import requests
import os
import datetime
import time
from tradingview_screener import Query, Column

# --- CONFIGURATION ---
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
GOAPI_KEY = os.environ.get("GOAPI_KEY")

# Daftar Broker Ritel (Untuk deteksi distribusi/buangan)
# Meskipun nama broker dinamis, kita tetap butuh list kode ritel untuk logic 'Paus vs Ritel'
RETAIL_CODES = ['YP', 'PD', 'XC', 'XL', 'SQ', 'KK', 'NI', 'CC', 'GR', 'DR']

# Global Variable untuk menyimpan Kamus Broker
BROKER_MAP = {}

def get_all_brokers():
    """
    Mengambil seluruh daftar kode & nama broker dari GoAPI.
    Endpoint: /stock/idx/brokers
    """
    print("📚 Mengunduh daftar nama broker terbaru...")
    url = "https://api.goapi.io/stock/idx/brokers"
    headers = {
        "X-API-KEY": GOAPI_KEY, 
        "Accept": "application/json"
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=10)
        data = response.json()
        
        if data.get('status') == 'success':
            results = data.get('data', [])
            # Format return GoAPI biasanya list of dict: [{'id': 'YP', 'name': 'MIRAE ASSET SEKURITAS INDONESIA'}, ...]
            # Kita ubah jadi Dictionary biar pencarian cepat: {'YP': 'MIRAE ASSET...', ...}
            broker_dict = {item['id']: item['name'] for item in results}
            print(f"✅ Berhasil memuat {len(broker_dict)} nama broker.")
            return broker_dict
        else:
            print("⚠️ Gagal memuat daftar broker (API Error). Menggunakan kode saja.")
            return {}
    except Exception as e:
        print(f"⚠️ Exception fetching brokers: {e}")
        return {}

def get_dynamic_universe():
    """TradingView Screener: Cari saham teramai hari ini"""
    print("🔄 Screening Top Volume via TradingView...")
    try:
        # Cari saham active (Volume & Value besar)
        qh = Query() \
            .select('name', 'close', 'volume', 'Value.Traded') \
            .set_markets('indonesia') \
            .where(
                Column('close') >= 60,              # Harga diatas 60 perak
                Column('Value.Traded') > 3000000000 # Transaksi > 3 Miliar
            ) \
            .order_by('volume', ascending=False) \
            .limit(20) # Top 20 Saham
            
        tickers = qh.get_scanner_data()
        clean_tickers = [row[1].replace("IDX:", "") for row in tickers]
        return clean_tickers

    except Exception as e:
        print(f"⚠️ TradingView Error: {e}")
        return ["BBRI", "BBCA", "BMRI", "ADRO", "TLKM", "ASII", "GOTO", "ANTM", "BRMS", "BUMI"]

def send_telegram_message(message):
    if not TELEGRAM_TOKEN or not CHAT_ID: return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    max_len = 4000
    for i in range(0, len(message), max_len):
        chunk = message[i:i+max_len]
        requests.post(url, json={"chat_id": CHAT_ID, "text": chunk, "parse_mode": "HTML", "disable_web_page_preview": True})

def get_broker_summary(ticker, date_str):
    url = f"https://api.goapi.io/stock/idx/{ticker}/broker_summary"
    headers = {"X-API-KEY": GOAPI_KEY, "Accept": "application/json", "User-Agent": "Bot/1.0"}
    params = {"date": date_str}
    
    try:
        time.sleep(0.25) # Rate limit safety
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

def clean_broker_name(code):
    """
    Ubah Kode jadi Nama Pendek yang enak dibaca.
    Contoh: 'YP' -> 'YP - MIRAE'
    """
    full_name = BROKER_MAP.get(code, "")
    
    # Pendekkan nama yang terlalu panjang biar muat di HP
    short_name = full_name.replace("SEKURITAS", "").replace("INDONESIA", "").replace("PT ", "").strip()
    
    # Ambil 1-2 kata pertama saja
    if len(short_name) > 15:
        short_name = " ".join(short_name.split()[:2])
        
    return f"{code} ({short_name})" if short_name else code

def analyze_bandar(ticker, buyers, sellers):
    # Hitung Net Money Flow (Top 3)
    buy_val = sum([float(x['value']) for x in buyers[:3]])
    sell_val = sum([float(x['value']) for x in sellers[:3]])
    net_money = buy_val - sell_val
    
    buyer_1_code = buyers[0]['code']
    seller_1_code = sellers[0]['code']
    avg_price = int(float(buyers[0]['avg_price']))
    
    status = "Netral"
    score = 0
    
    # Logic Bandarmology
    if net_money > 0:
        status = "Akumulasi"
        score = 1
        # Jika Top Buyer BUKAN Ritel & Top Seller ADALAH Ritel
        if buyer_1_code not in RETAIL_CODES and seller_1_code in RETAIL_CODES:
            status = "🔥 PAUS MASUK"
            score = 3
            
    elif net_money < 0:
        status = "Distribusi"
        score = -1
        # Jika Top Buyer ADALAH Ritel (Ritel nampung barang bandar)
        if buyer_1_code in RETAIL_CODES:
            status = "⚠️ DUMP KE RITEL" 
            score = -3
            
    return {
        "code": ticker,
        "net_money": net_money,
        "score": score,
        "status": status,
        "top_buyer_display": clean_broker_name(buyer_1_code),
        "top_seller_display": clean_broker_name(seller_1_code),
        "avg_price": avg_price
    }

def format_money(val):
    val = float(val)
    if abs(val) >= 1_000_000_000: return f"{val/1_000_000_000:.1f} M"
    elif abs(val) >= 1_000_000: return f"{val/1_000_000:.0f} jt"
    return f"{val:.0f}"

def get_last_trading_day():
    d = datetime.date.today()
    # Jika run hari Sabtu/Minggu, mundur ke Jumat
    while d.weekday() > 4: d -= datetime.timedelta(days=1)
    return d.strftime("%Y-%m-%d")

def main():
    if not GOAPI_KEY:
        print("❌ GOAPI_KEY Belum diset!")
        return

    # 1. FETCH DATA BROKER (Isi kamus dulu)
    global BROKER_MAP
    BROKER_MAP = get_all_brokers()
    
    # 2. GENERATE WATCHLIST DINAMIS
    tickers = get_dynamic_universe()
    
    date_str = get_last_trading_day()
    print(f"🕵️ Scanning {len(tickers)} saham teramai tanggal {date_str}...")
    
    results = []
    for t in tickers:
        data = get_broker_summary(t, date_str)
        if data: results.append(data)
        
    # 3. FILTERING (Hanya tampilkan yang Net Buy Positif / Akumulasi)
    winners = sorted([x for x in results if x['net_money'] > 0], key=lambda x: x['net_money'], reverse=True)
    
    if not winners:
        send_telegram_message("⚠️ Tidak ada akumulasi signifikan di Top Volume hari ini.")
        return

    # 4. REPORTING
    msg = f"📡 <b>SMART BANDAR DETECTOR</b>\n"
    msg += f"📅 {date_str} | Generated by GitHub Actions\n"
    msg += "="*25 + "\n\n"
    
    # Tampilkan Top 10
    for s in winners[:10]:
        icon = "🟢"
        if s['score'] >= 3: icon = "🐳🔥"
        
        msg += f"<b>{s['code']}</b> {icon}\n"
        msg += f"💰 Net Money: <b>+{format_money(s['net_money'])}</b>\n"
        msg += f"🛒 Buyer: <b>{s['top_buyer_display']}</b>\n"
        msg += f"   Avg: {s['avg_price']}\n"
        msg += f"📦 Seller: {s['top_seller_display']}\n"
        msg += f"📊 {s['status']}\n"
        msg += "-"*20 + "\n"
        
    send_telegram_message(msg)
    print("Report Sent!")

if __name__ == "__main__":
    main()
