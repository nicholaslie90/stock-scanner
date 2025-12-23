import requests
import os
import datetime
import time
import json
import yfinance as yf # Wajib ada untuk data harga real-time

# --- CONFIGURATION (OBFUSCATED) ---
TG_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TG_CHAT = os.environ.get("TELEGRAM_CHAT_ID")

API_KEY = os.environ.get("CORE_API_KEY")
API_URL = os.environ.get("CORE_API_URL") 
API_HOST = os.environ.get("CORE_API_HOST")

SOURCE_FILE = "watchlist.txt"
AUTH_ALERT_SENT = False

# --- CLASSIFICATION ---
AGENT_ALPHA = ['BK', 'AK', 'ZP', 'MG', 'BB', 'RX', 'KZ', 'CC', 'LG', 'YU', 'DX', 'CS', 'AI', 'CD', 'RF', 'AZ']
AGENT_BETA = ['YP', 'PD', 'XC', 'XL', 'KK', 'SQ', 'NI', 'GR', 'EP']

ENTITY_MAP = {
    'YP': 'Mirae', 'PD': 'IndoPremier', 'XC': 'Ajaib', 'XL': 'Stockbit', 'SQ': 'BCA', 'NI': 'BNI',
    'KK': 'Phillip', 'CC': 'Mandiri', 'DR': 'RHB', 'OD': 'Danareksa', 'AZ': 'Sucor', 'MG': 'Semesta',
    'BK': 'JP Morgan', 'AK': 'UBS', 'ZP': 'Maybank', 'KZ': 'CLSA', 'RX': 'Macquarie', 'BB': 'Verdhana',
    'AI': 'UOB', 'YU': 'CGS', 'LG': 'Trimegah', 'RF': 'Buana', 'IF': 'Samuel', 'CP': 'Valbury',
    'HP': 'Henan', 'YJ': 'Lautandhana'
}

def load_targets():
    if not os.path.exists(SOURCE_FILE): return []
    with open(SOURCE_FILE, 'r') as f:
        return list(set([line.strip().upper().replace(".JK", "") for line in f.readlines() if line.strip()]))

def push_notification(msg):
    if not TG_TOKEN or not TG_CHAT: return
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    for i in range(0, len(msg), 4000):
        try: requests.post(url, json={"chat_id": TG_CHAT, "text": msg[i:i+4000], "parse_mode": "Markdown"})
        except: pass

def get_scalper_candidates(tickers):
    """
    Fungsi Utama Scalper:
    Mengambil data Real-Time (High, Low, Current, Volume) via YFinance.
    Mengembalikan list saham yang diurutkan berdasarkan VOLATILITAS (Swing).
    """
    print(f"⚡ Screening {len(tickers)} stocks for Volatility & Volume...")
    
    yf_tickers = [f"{t}.JK" for t in tickers]
    try:
        # Download data hari ini (Intraday)
        df = yf.download(yf_tickers, period="1d", group_by='ticker', progress=False)
    except Exception as e:
        print(f"⚠️ YF Error: {e}")
        return []

    candidates = []
    
    for t in tickers:
        try:
            data = df[f"{t}.JK"]
            if data.empty: continue
            
            # Ambil candle terakhir (Realtime/Closing terakhir)
            high = float(data['High'].iloc[-1])
            low = float(data['Low'].iloc[-1])
            close = float(data['Close'].iloc[-1])
            open_price = float(data['Open'].iloc[-1])
            vol = float(data['Volume'].iloc[-1])
            
            # 1. Hitung Volatilitas (Swing Range dalam %)
            # Rumus: (High - Low) / Open
            if open_price == 0: continue
            swing_pct = ((high - low) / open_price) * 100
            
            # 2. Hitung Value Transaksi (Estimasi Kasar)
            value_tx = close * vol
            
            # Filter Awal: Hanya ambil yang swing > 1.5% dan Value > 1 Miliar (Biar liquid)
            if swing_pct > 1.5 and value_tx > 1_000_000_000:
                candidates.append({
                    'id': t,
                    'swing': swing_pct,
                    'price': close,
                    'high': high,
                    'low': low,
                    'volume': vol,
                    'value_tx': value_tx,
                    'change': ((close - open_price) / open_price) * 100
                })
        except: continue
        
    # URUTKAN BERDASARKAN SWING TERTINGGI (Most Volatile First)
    candidates.sort(key=lambda x: x['swing'], reverse=True)
    
    # Ambil Top 15 Paling Volatile untuk dicek Bandarnya
    return candidates[:15]

# --- HIDDEN API HANDLERS (Sama seperti sebelumnya) ---

def trigger_auth_alert():
    global AUTH_ALERT_SENT
    if AUTH_ALERT_SENT: return
    msg = "⚠️ *SCALPER ALERT: API GATEWAY 401* ⚠️\nPlease rotate the `CORE_API_KEY`."
    push_notification(msg)
    AUTH_ALERT_SENT = True

def query_external_source(target_id):
    # Untuk Scalper, kita selalu minta data HARI INI (Intraday)
    # Jika market tutup, otomatis dapat closing hari ini
    utc_now = datetime.datetime.utcnow()
    wib_now = utc_now + datetime.timedelta(hours=7)
    
    # Simple Date Logic: Hari ini
    date_str = wib_now.strftime("%Y-%m-%d")
    
    if not API_URL or not API_KEY: return None
    global AUTH_ALERT_SENT
    if AUTH_ALERT_SENT: return None

    endpoint = f"{API_URL}/{target_id}"
    params = {
        "from": date_str, "to": date_str, # Intraday Range
        "transaction_type": "TRANSACTION_TYPE_NET",
        "market_board": "MARKET_BOARD_REGULER",
        "investor_type": "INVESTOR_TYPE_ALL",
        "limit": 20
    }
    headers = {
        'accept': 'application/json', 'authorization': f'Bearer {API_KEY}',
        'user-agent': 'Mozilla/5.0 (Macintosh)', 'origin': API_HOST, 'referer': f"{API_HOST}/"
    }

    try:
        time.sleep(0.3) # Fast request for scalping
        res = requests.get(endpoint, headers=headers, params=params, timeout=5)
        if res.status_code == 401:
            trigger_auth_alert()
            return None
        if res.status_code == 200:
            payload = res.json()
            if 'data' in payload: return payload['data']
    except: pass
    return None

def normalize_data(raw_data):
    if not raw_data: return []
    if isinstance(raw_data, list): return raw_data
    if isinstance(raw_data, dict):
        clean_list = []
        summary = raw_data.get('broker_summary', {})
        if not summary: return []
        for b in summary.get('brokers_buy', []):
            clean_list.append({'broker_code': b.get('netbs_broker_code'), 'value': float(b.get('bval', 0)), 'avg': float(b.get('netbs_buy_avg_price', 0))})
        for s in summary.get('brokers_sell', []):
            clean_list.append({'broker_code': s.get('netbs_broker_code'), 'value': -abs(float(s.get('sval', 0))), 'avg': float(s.get('netbs_sell_avg_price', 0))})
        return clean_list
    return []

def process_flow(raw_data):
    tx = normalize_data(raw_data)
    if not tx: return None

    alpha_net = 0; beta_net = 0
    top_buyer = {'id': '-', 'val': 0}; top_seller = {'id': '-', 'val': 0}
    
    sorted_val = sorted(tx, key=lambda x: abs(x['value']), reverse=True)
    if sorted_val:
        b = [x for x in sorted_val if x['value'] > 0]
        if b: top_buyer = {'id': b[0]['broker_code'], 'val': b[0]['value'], 'avg': b[0]['avg']}
        s = [x for x in sorted_val if x['value'] < 0]
        if s: top_seller = {'id': s[0]['broker_code'], 'val': abs(s[0]['value'])}

    for row in tx:
        c = row.get('broker_code'); v = row.get('value', 0)
        if c in AGENT_ALPHA: alpha_net += v
        elif c in AGENT_BETA: beta_net += v

    # Scoring Scalper (Lebih agresif)
    score = 0
    if alpha_net > 500_000_000: score += 3 # Smart Money Masuk
    if beta_net < -200_000_000: score += 2 # Ritel Buang Barang
    if top_buyer['id'] in AGENT_ALPHA: score += 2
    
    status = "NEUTRAL"
    if score >= 3: status = "BULLISH FLOW"
    elif score <= -2: status = "BEARISH FLOW"

    return {
        "status": status,
        "score": score,
        "alpha_net": alpha_net,
        "top_buy": top_buyer,
        "top_sell": top_seller
    }

def format_val(v):
    if abs(v) >= 1_000_000_000: return f"{v/1_000_000_000:.1f}B"
    if abs(v) >= 1_000_000: return f"{v/1_000_000:.0f}M"
    return str(int(v))

def resolve_name(code): return f"{code}-{ENTITY_MAP.get(code, '')}"

def main():
    if not API_KEY: return
    
    targets = load_targets()
    # 1. SCAN VOLATILITY DULU (YFINANCE)
    candidates = get_scalper_candidates(targets)
    
    if not candidates:
        print("⚠️ No volatile stocks found.")
        return

    report_buffer = []
    print(f"🚀 Analyzing Flows for top {len(candidates)} volatile stocks...")

    for stock in candidates:
        if AUTH_ALERT_SENT: break
        
        # 2. CEK BANDAR FLOW (HIDDEN API)
        # Kita hanya cek saham yang volatilitasnya tinggi
        print(f"   Checking flow for {stock['id']} (Swing: {stock['swing']:.1f}%)")
        flow = process_flow(query_external_source(stock['id']))
        
        # Gabungkan data Price Action + Bandar Flow
        stock_data = {**stock, "flow": flow}
        report_buffer.append(stock_data)

    if not report_buffer: return

    # Sort Final: Prioritas Bullish Flow dengan Swing Tinggi
    # Logic: Kalau flow Bullish, taruh atas. Kalau Netral tapi Swing tinggi, taruh tengah.
    report_buffer.sort(key=lambda x: (x['flow']['score'] if x['flow'] else -10, x['swing']), reverse=True)

    # REPORT GENERATION
    txt = f"⚡ *SCALPER VOLATILITY SCAN* ⚡\n"
    txt += f"⏱️ Time: {datetime.datetime.now().strftime('%H:%M WIB')}\n"
    txt += f"_Most Volatile & Liquid Today_\n\n"
    
    for s in report_buffer:
        f = s['flow']
        
        # Icon Ticker
        icon = "⚪"
        if s['change'] > 0: icon = "🟢"
        if s['change'] < 0: icon = "🔴"
        
        # Status Flow
        flow_stat = "❓ No Data"
        alpha_str = "0"
        buyer_str = "-"
        if f:
            if f['score'] >= 3: flow_stat = "🐳 *BIG ACCUM*"
            elif f['score'] >= 1: flow_stat = "✅ Mod. Accum"
            elif f['score'] <= -2: flow_stat = "⚠️ DISTRIB"
            else: flow_stat = "⚖️ Neutral"
            
            alpha_str = format_val(f['alpha_net'])
            buyer_str = f"{resolve_name(f['top_buy']['id'])} @{int(f['top_buy']['avg'])}"

        # Hitung jarak harga sekarang ke High (Potensi Profit Sisa)
        upside_left = ((s['high'] - s['price']) / s['price']) * 100
        
        txt += f"*{s['id']}* {icon} (Chg: {s['change']:+.1f}%)\n"
        txt += f"🌊 *Swing: {s['swing']:.1f}%* (Vol: {format_val(s['value_tx'])})\n"
        txt += f"📊 Flow: {flow_stat} (Alpha: {alpha_str})\n"
        txt += f"🛒 Lead: {buyer_str}\n"
        txt += f"📏 Range: {int(s['low'])} - {int(s['high'])}\n"
        txt += f"🎯 Curr: {int(s['price'])}\n"
        txt += "----------------------------\n"
        
    push_notification(txt)
    print("✅ Scalper Report Sent!")

if __name__ == "__main__":
    main()
