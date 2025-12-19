import requests
import os
import datetime
import time
import json

# --- CONFIGURATION ---
# Mengambil config dari env vars yang sudah disamarkan
TG_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TG_CHAT = os.environ.get("TELEGRAM_CHAT_ID")

# "Core" variables untuk menyembunyikan identitas provider data
API_KEY = os.environ.get("CORE_API_KEY")
API_URL = os.environ.get("CORE_API_URL") 
API_HOST = os.environ.get("CORE_API_HOST")

SOURCE_FILE = "watchlist.txt"

# Kamus Mapping (Tetap diperlukan untuk readability output)
ENTITY_MAP = {
    'YP': 'Mirae', 'PD': 'IndoPremier', 'XC': 'Ajaib', 'XL': 'SB-Invest', 
    'SQ': 'BCA', 'NI': 'BNI', 'KK': 'Phillip', 'CC': 'Mandiri', 
    'DR': 'RHB', 'OD': 'Danareksa', 'AZ': 'Sucor', 'MG': 'Semesta', 
    'BK': 'JP Morgan', 'AK': 'UBS', 'ZP': 'Maybank', 'KZ': 'CLSA', 
    'RX': 'Macquarie', 'BB': 'Verdhana', 'AI': 'UOB', 'YU': 'CGS', 
    'LG': 'Trimegah', 'RF': 'Buana', 'IF': 'Samuel', 'CP': 'Valbury', 
    'HP': 'Henan', 'YJ': 'Lautandhana'
}

# Kode partisipan ritel
RETAIL_IDS = ['YP', 'PD', 'XC', 'XL', 'KK', 'SQ', 'NI']

def load_targets():
    if not os.path.exists(SOURCE_FILE):
        return ["BBCA", "BBRI", "BMRI", "TLKM"]
    with open(SOURCE_FILE, 'r') as f:
        return list(set([line.strip().upper().replace(".JK", "") for line in f.readlines() if line.strip()]))

def get_time_window():
    """Menentukan window waktu analisis"""
    utc_now = datetime.datetime.utcnow()
    local_now = utc_now + datetime.timedelta(hours=7)
    
    # Logic: Jika run pagi (sebelum jam 10), ambil data kemarin
    if local_now.hour < 10:
        ref_date = local_now - datetime.timedelta(days=1)
    else:
        ref_date = local_now

    while ref_date.weekday() > 4: # Skip weekend
        ref_date -= datetime.timedelta(days=1)
    
    current_str = ref_date.strftime("%Y-%m-%d")
    
    # Window Long Term (90 hari)
    past_date = ref_date - datetime.timedelta(days=90)
    past_str = past_date.strftime("%Y-%m-%d")
    
    return current_str, past_str

def query_external_source(target_id, start_dt, end_dt):
    """
    Generic fetcher function.
    URL dan Host disembunyikan di Environment Variables.
    """
    if not API_URL or not API_KEY: return None

    # Construct endpoint dynamically
    # API_URL is hidden in secrets (e.g., https://exodus.stockbit.com/marketdetectors)
    endpoint = f"{API_URL}/{target_id}"
    
    params = {
        "from": start_dt,
        "to": end_dt,
        "transaction_type": "TRANSACTION_TYPE_NET",
        "market_board": "MARKET_BOARD_REGULER",
        "investor_type": "INVESTOR_TYPE_ALL",
        "limit": 20
    }
    
    # Headers dikonstruksi agar terlihat generik tapi valid
    headers = {
        'accept': 'application/json',
        'authorization': f'Bearer {API_KEY}',
        'user-agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko)',
        'origin': API_HOST,  # Hidden in secrets
        'referer': f"{API_HOST}/" # Hidden in secrets
    }

    try:
        time.sleep(0.8) # Jeda sopan
        res = requests.get(endpoint, headers=headers, params=params, timeout=10)
        
        if res.status_code == 200:
            payload = res.json()
            if 'data' in payload:
                return payload['data']
    except Exception:
        pass
    
    return None

def process_metrics(raw_data):
    if not raw_data: return None

    inflow_group = []
    outflow_group = []
    
    for row in raw_data:
        agent_id = row.get('broker_code')
        net_val = float(row.get('value', 0))
        avg_price = float(row.get('average_price', 0))
        
        node = {'id': agent_id, 'val': abs(net_val), 'avg': avg_price}
        
        if net_val > 0:
            inflow_group.append(node)
        elif net_val < 0:
            outflow_group.append(node)
            
    inflow_group.sort(key=lambda x: x['val'], reverse=True)
    outflow_group.sort(key=lambda x: x['val'], reverse=True)
    
    # Kalkulasi Top 3 Strength
    top3_in = sum([x['val'] for x in inflow_group[:3]])
    top3_out = sum([x['val'] for x in outflow_group[:3]])
    
    net_total = top3_in - top3_out
    
    signal_type = "NEUTRAL"
    if top3_in > top3_out * 1.15:
        signal_type = "INFLOW" # Pengganti istilah Akumulasi
    elif top3_out > top3_in * 1.15:
        signal_type = "OUTFLOW" # Pengganti istilah Distribusi
        
    return {
        "signal": signal_type,
        "net_val": net_total,
        "lead_in": inflow_group[0]['id'] if inflow_group else "-",
        "lead_in_avg": int(inflow_group[0]['avg']) if inflow_group else 0,
        "lead_out": outflow_group[0]['id'] if outflow_group else "-",
        "top3_in_ids": [x['id'] for x in inflow_group[:3]],
        "top3_out_ids": [x['id'] for x in outflow_group[:3]]
    }

def format_val(v):
    if abs(v) >= 1_000_000_000: return f"{v/1_000_000_000:.1f}B" # B for Billion
    if abs(v) >= 1_000_000: return f"{v/1_000_000:.0f}M" # M for Million
    return str(int(v))

def resolve_name(code):
    return f"{code}-{ENTITY_MAP.get(code, '')}"

def push_notification(msg):
    if not TG_TOKEN or not TG_CHAT: return
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    for i in range(0, len(msg), 4000):
        requests.post(url, json={"chat_id": TG_CHAT, "text": msg[i:i+4000], "parse_mode": "Markdown"})

def main():
    if not API_KEY: return # Silent exit

    curr_dt, long_dt = get_time_window()
    targets = load_targets()
    
    output_buffer = []

    for item in targets:
        # 1. Short Term Check
        st_data = query_external_source(item, curr_dt, curr_dt)
        st_res = process_metrics(st_data)
        
        # 2. Long Term Check
        lt_data = query_external_source(item, long_dt, curr_dt)
        lt_res = process_metrics(lt_data)
        
        if st_res and lt_res:
            # Scoring Logic (Obfuscated)
            rank = 0
            if st_res['signal'] == 'INFLOW': rank += 1
            if lt_res['signal'] == 'INFLOW': rank += 1
            if st_res['lead_in'] not in RETAIL_IDS: rank += 1
            
            output_buffer.append({
                "id": item,
                "rank": rank,
                "st": st_res,
                "lt": lt_res
            })

    # Sort by rank
    output_buffer.sort(key=lambda x: x['rank'], reverse=True)
    
    if not output_buffer: return

    # Construct Message
    txt = f"📊 *MARKET FLOW INSIGHT* 📊\n"
    txt += f"📅 Ref: {curr_dt}\n\n"
    
    for obj in output_buffer:
        s = obj['st']
        l = obj['lt']
        
        marker = "⚪"
        if s['signal'] == 'INFLOW': marker = "🟢"
        if s['signal'] == 'OUTFLOW': marker = "🔴"
        if obj['rank'] >= 3: marker = "🔥" # Strong Signal
        
        in_agent = resolve_name(s['lead_in'])
        out_agent = resolve_name(s['lead_out'])
        
        trend_dir = "Up" if l['signal'] == 'INFLOW' else "Down"
        
        txt += f"*{obj['id']}* {marker}\n"
        txt += f"💠 *Flow:* {s['signal']} (Net: {format_val(s['net_val'])})\n"
        txt += f"   Buy: {in_agent} @ {s['lead_in_avg']}\n"
        txt += f"   Sell: {out_agent}\n"
        txt += f"📈 *Trend:* {trend_dir}\n"
        txt += "----------------------------\n"
        
    push_notification(txt)

if __name__ == "__main__":
    main()
