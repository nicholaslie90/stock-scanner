import yfinance as yf
import requests
import os
import pandas as pd
import numpy as np

# --- CONFIGURATION ---
WATCHLIST_FILE = "watchlist.txt"
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# Filter Likuiditas (Agar tidak terjebak di saham 'kuburan')
MIN_DAILY_VALUE = 1_000_000_000  # Minimal transaksi 1 Miliar per hari

def get_tickers_from_file():
    if not os.path.exists(WATCHLIST_FILE):
        return ["BBRI.JK", "BBCA.JK", "BMRI.JK", "BBNI.JK", "TLKM.JK", "ASII.JK", "ADRO.JK", "UNTR.JK"]
    
    with open(WATCHLIST_FILE, 'r') as f:
        codes = [line.strip().upper() for line in f.readlines() if line.strip()]
    
    tickers = [f"{code}.JK" if not code.endswith(".JK") else code for code in codes]
    return tickers

def send_telegram_message(message):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("Telegram Credentials not set.")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message, "parse_mode": "HTML", "disable_web_page_preview": True}
    requests.post(url, json=payload)

def analyze_smart_money_behavior(df):
    """
    Analisa VSA (Volume Spread Analysis) untuk mendeteksi jejak Bandar
    tanpa data broker summary.
    """
    # Ambil data terakhir
    curr = df.iloc[-1]
    prev = df.iloc[-2]
    
    # 1. Analisa Trend Jangka Pendek (MA20)
    ma20 = df['Close'].rolling(window=20).mean().iloc[-1]
    trend = "UPTREND" if curr['Close'] > ma20 else "DOWNTREND"
    
    # 2. Relative Volume (RVOL)
    # Apakah volume hari ini meledak dibanding rata-rata 20 hari?
    avg_vol_20 = df['Volume'].iloc[-21:-1].mean() # Exclude hari ini untuk rata-rata
    rvol = curr['Volume'] / avg_vol_20 if avg_vol_20 > 0 else 0
    
    # 3. Price Spread Analysis (Rentang Candle)
    # Spread = High - Low.
    spread = curr['High'] - curr['Low']
    avg_spread = (df['High'] - df['Low']).rolling(window=20).mean().iloc[-1]
    spread_ratio = spread / avg_spread if avg_spread > 0 else 0
    
    # 4. Posisi Close (Buying Pressure)
    # Dimana posisi close dalam candle? (0 = di Low, 1 = di High)
    if spread > 0:
        close_position = (curr['Close'] - curr['Low']) / spread
    else:
        close_position = 0.5

    # --- INTEPRETASI BANDARMOLOGY (VSA LOGIC) ---
    signal = "NEUTRAL"
    desc = "Menunggu Konfirmasi"
    
    # CASE A: ABSORPTION / AKUMULASI
    # Harga tidak banyak gerak (Spread Kecil), tapi Volume Besar (RVOL Tinggi)
    # Artinya ada yang menampung semua guyuran jual (Siap-siap terbang)
    if rvol > 1.5 and spread_ratio < 0.8 and close_position > 0.4:
        signal = "POTENSI AKUMULASI (ABSORPTION)"
        desc = "Volume besar tapi harga dijaga stabil. Bandar sedang menampung barang."

    # CASE B: MARKUP / PUMP
    # Harga naik, Spread Lebar, Volume Besar, Close dekat High
    elif curr['Close'] > prev['Close'] and rvol > 1.2 and spread_ratio > 1.0 and close_position > 0.7:
        signal = "STRONG MARKUP (POWER BUY)"
        desc = "Harga didorong naik dengan volume meyakinkan."

    # CASE C: SUPPLY ENTERING / DISTRIBUSI
    # Harga naik/turun, Volume Hancur Besar, tapi Close di tengah atau bawah (Ekor Atas Panjang)
    elif rvol > 1.5 and close_position < 0.4:
        signal = "DISTRIBUSI / SELLING PRESSURE"
        desc = "Volume besar tapi harga gagal tutup di atas. Hati-hati guyuran."

    # CASE D: NO DEMAND
    # Harga turun, Volume kering (Kecil)
    elif curr['Close'] < prev['Close'] and rvol < 0.7:
        signal = "KOREKSI WAJAR (NO SUPPLY)"
        desc = "Harga turun karena tidak ada yang beli, bukan karena buangan bandar."

    # Hitung Support Resistance Dinamis (Pivot)
    pivot = (curr['High'] + curr['Low'] + curr['Close']) / 3
    s1 = (2 * pivot) - curr['High']
    r1 = (2 * pivot) - curr['Low']

    return {
        "price": int(curr['Close']),
        "change_pct": ((curr['Close'] - prev['Close']) / prev['Close']) * 100,
        "vol_val": curr['Volume'] * curr['Close'], # Estimasi Value
        "rvol": rvol,
        "signal": signal,
        "desc": desc,
        "trend": trend,
        "support": int(s1),
        "resistance": int(r1)
    }

def run_screener():
    tickers = get_tickers_from_file()
    print(f"Scanning {len(tickers)} stocks...")
    
    try:
        # Ambil data agak panjang untuk hitung MA dan Avg Volume
        data = yf.download(tickers, period="3mo", group_by='ticker', progress=False, threads=True)
    except Exception as e:
        print(f"Error: {e}")
        return []

    results = []
    
    # Helper untuk akses data multi-index atau single-index
    if len(tickers) == 1:
        iterator = [(tickers[0], data)]
    else:
        iterator = [(t, data[t]) for t in tickers if t in data.columns.levels[0]]

    for ticker, df in iterator:
        try:
            df = df.dropna()
            if len(df) < 30: continue
            
            # Filter Likuiditas Value Harian
            avg_value = (df['Close'] * df['Volume']).tail(5).mean()
            if avg_value < MIN_DAILY_VALUE: continue 

            analysis = analyze_smart_money_behavior(df)
            analysis['code'] = ticker.replace(".JK", "")
            
            # Hanya ambil yang ada sinyal menarik (Filter Neutral)
            if analysis['signal'] != "NEUTRAL":
                results.append(analysis)
                
        except Exception:
            continue

    # Sorting berdasarkan RVOL tertinggi (Dimana ada gula/volume, disitu ada semut/bandar)
    return sorted(results, key=lambda x: x['rvol'], reverse=True)[:10]

def format_message(stocks):
    if not stocks:
        return "⚠️ Tidak ada sinyal Smart Money yang signifikan hari ini."
    
    msg = "🕵️‍♂️ <b>VSA BANDAR DETECTOR (No-API)</b>\n"
    msg += f"📅 {pd.Timestamp.now().strftime('%d %b %Y')}\n"
    msg += "<i>Screening anomali volume & spread harga</i>\n\n"
    
    for s in stocks:
        icon = "🟢" if "AKUMULASI" in s['signal'] or "MARKUP" in s['signal'] else "🔴"
        
        msg += f"<b>{s['code']}</b> ({s['change_pct']:+.2f}%) {icon}\n"
        msg += f"Harga: {s['price']}\n"
        msg += f"📊 <b>Signal: {s['signal']}</b>\n"
        msg += f"ℹ️ <i>{s['desc']}</i>\n"
        msg += f"📈 RVOL: {s['rvol']:.1f}x (Rata2 Vol)\n"
        msg += f"🎯 Plan: Buy dekat {s['support']}, TP {s['resistance']}\n"
        msg += "------------------------------\n"
        
    return msg

if __name__ == "__main__":
    found_stocks = run_screener()
    telegram_msg = format_message(found_stocks)
    send_telegram_message(telegram_msg)
    print("Done.")
