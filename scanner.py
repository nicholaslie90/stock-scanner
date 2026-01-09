import requests
import os
import datetime
import yfinance as yf
import math
import numpy as np

# --- CONFIGURATION ---
TG_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TG_CHAT = os.environ.get("TELEGRAM_CHAT_ID")
SOURCE_FILE = "watchlist.txt"

def load_targets():
    """Load stock list from watchlist.txt"""
    if not os.path.exists(SOURCE_FILE): return []
    with open(SOURCE_FILE, 'r') as f:
        # Clean text, upper case, remove .JK, remove duplicates
        return list(set([line.strip().upper().replace(".JK", "") for line in f.readlines() if line.strip()]))

def push_notification(msg):
    """Send message to Telegram"""
    if not TG_TOKEN or not TG_CHAT: return
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    for i in range(0, len(msg), 4000):
        try: 
            requests.post(url, json={"chat_id": TG_CHAT, "text": msg[i:i+4000], "parse_mode": "Markdown"})
        except Exception as e:
            print(f"Telegram Error: {e}")

def format_val(v):
    """Format Value to Billions (B) or Millions (M)"""
    if abs(v) >= 1_000_000_000: return f"{v/1_000_000_000:.1f}B"
    if abs(v) >= 1_000_000: return f"{v/1_000_000:.0f}M"
    return str(int(v))

def analyze_market(tickers):
    print(f"⚡ Screening {len(tickers)} stocks via YFinance...")
    
    yf_tickers = [f"{t}.JK" for t in tickers]
    
    try:
        # UPDATED: Fetch '1mo' (1 Month) instead of '1d' to calculate Average Volume
        df = yf.download(yf_tickers, period="1mo", group_by='ticker', progress=False, threads=True)
    except Exception as e:
        print(f"⚠️ YFinance Connection Error: {e}")
        return []

    candidates = []
    
    for t in tickers:
        try:
            # Handle YFinance MultiIndex structure
            if len(tickers) == 1:
                data = df
            else:
                # Use .xs or simple access depending on structure, robust fallback
                if f"{t}.JK" in df.columns.levels[0]:
                    data = df[f"{t}.JK"]
                else:
                    continue
            
            if data.empty or len(data) < 2: continue
            
            # --- EXTRACT DATA ---
            # Recent Candle (Today)
            curr = data.iloc[-1]
            high = float(curr['High'])
            low = float(curr['Low'])
            close = float(curr['Close'])
            open_price = float(curr['Open'])
            vol = float(curr['Volume'])
            
            # Skip Suspended/No Data
            if open_price == 0 or vol == 0 or high == low: continue

            # --- CALCULATE METRICS ---

            # 1. SWING (%)
            swing_pct = ((high - low) / low) * 100
            
            # 2. TRANSACTION VALUE (Approximation of Liquidity)
            # This is your main filter for "Frequency" capability. 
            # Low value (< 1B IDR) usually means low frequency.
            value_tx = close * vol
            
            # 3. RVOL (Relative Volume) - The "Frequency" Proxy
            # We take the average volume of the last 20 days (excluding today)
            # If history is short, take whatever is available
            hist_vol = data['Volume'].iloc[:-1] 
            avg_vol = hist_vol.mean() if len(hist_vol) > 0 else vol
            
            # RVOL Calculation
            # If RVOL > 1.0, it is trading more than usual.
            # If RVOL > 3.0, it is VERY active (High Frequency).
            rvol = vol / avg_vol if avg_vol > 0 else 0

            # 4. POSITION SCORE (0.0=Low, 1.0=High)
            range_price = high - low
            pos_score = (close - low) / range_price if range_price > 0 else 0.5
            
            # --- FILTERING ---
            
            # Filter A: Must have liquidity (Min 2 Billion IDR)
            # Scalping on < 2B is risky due to lack of order book depth (papan tipis)
            if value_tx < 2_000_000_000: continue
            
            # Filter B: Must have Volatility OR High RVOL
            # If swing is small, RVOL must be HUGE (accumulation phase)
            if swing_pct < 1.5 and rvol < 2.0: continue

            candidates.append({
                'id': t,
                'swing': swing_pct,
                'price': close,
                'high': high,
                'low': low,
                'value_tx': value_tx,
                'rvol': rvol,  # Added RVOL
                'change': ((close - open_price) / open_price) * 100,
                'pos_score': pos_score
            })
        except Exception: 
            continue
            
    # --- SORTING STRATEGY (The "Top Frequency" Logic) ---
    # We create a 'Scalp Score'
    # Score = Swing * RVOL * Log(Value)
    # This prioritizes stocks that are:
    # 1. Moving wide (Swing)
    # 2. Crowded/Busy (RVOL)
    # 3. Liquid (Value)
    
    candidates.sort(key=lambda x: (x['swing'] * x['rvol'] * math.log(x['value_tx'])), reverse=True)
    
    return candidates[:15]

def main():
    targets = load_targets()
    if not targets:
        print("❌ Watchlist empty or file not found.")
        return

    results = analyze_market(targets)
    
    if not results:
        print("⚠️ No stocks passed the scalper filter.")
        return

    # --- REPORTING ---
    wib_time = (datetime.datetime.utcnow() + datetime.timedelta(hours=7)).strftime('%H:%M')
    
    txt = f"⚡ *SCALPER HIGH FREQUENCY SCAN* ⚡\n"
    txt += f"⏱️ Time: {wib_time} WIB\n"
    txt += f"_Sort: Volatility x RVOL_\n\n"
    
    for s in results:
        icon = "⚪"
        if s['change'] > 0: icon = "🟢"
        elif s['change'] < 0: icon = "🔴"
        
        # Pos Info
        pos_info = "Mid"
        if s['pos_score'] >= 0.8: pos_info = "🔥 *Top*"
        elif s['pos_score'] <= 0.2: pos_info = "🔻 *Bot*"
        
        # RVOL Info
        # Show specific icon if volume is exploding
        rvol_icon = "🔈"
        if s['rvol'] > 1.5: rvol_icon = "🔊"
        if s['rvol'] > 3.0: rvol_icon = "📢 BOOM"

        txt += f"*{s['id']}* {icon} ({s['change']:+.1f}%)\n"
        txt += f"🌊 Swing: *{s['swing']:.1f}%* | Val: {format_val(s['value_tx'])}\n"
        txt += f"📊 Vol: *{s['rvol']:.1f}x* Avg {rvol_icon}\n"
        txt += f"📍 Pos: {pos_info} | {int(s['price'])}\n"
        txt += "----------------------------\n"
        
    push_notification(txt)
    print("✅ Report Sent!")

if __name__ == "__main__":
    main()
