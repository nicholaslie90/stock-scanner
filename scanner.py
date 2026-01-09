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
    """Format angka milyaran/jutaan with NaN safety"""
    if math.isnan(v): return "0"
    
    if abs(v) >= 1_000_000_000: return f"{v/1_000_000_000:.1f}B"
    if abs(v) >= 1_000_000: return f"{v/1_000_000:.0f}M"
    return str(int(v))

def calc_trading_plan(high, low, close):
    """
    Calculate simple scalping pivot points based on daily range.
    Entry: Near the Low (Bottom 25% of range)
    Target: Near the High (Top 15% of range)
    Stop Loss: 2% below Low
    """
    daily_range = high - low
    if daily_range == 0: return close, close, close
    
    # Strategy: Buy on Retracement (Buy on Weakness)
    # Entry zone: Low + 20% of range
    entry_price = low + (daily_range * 0.20)
    
    # Target: High - 10% of range (Don't aim for exact top)
    target_price = high - (daily_range * 0.10)
    
    # Stop Loss: 2 ticks below low (approx 1-2%)
    stop_loss = low * 0.98
    
    return int(entry_price), int(target_price), int(stop_loss)

def analyze_market(tickers):
    print(f"⚡ Screening {len(tickers)} stocks via YFinance...")
    
    yf_tickers = [f"{t}.JK" for t in tickers]
    
    try:
        # Fetch '1mo' to calculate Average Volume accurately
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
                if f"{t}.JK" in df.columns.levels[0]:
                    data = df[f"{t}.JK"]
                else:
                    continue
            
            if data.empty or len(data) < 2: continue
            
            # --- EXTRACT DATA ---
            curr = data.iloc[-1]
            high = float(curr['High'])
            low = float(curr['Low'])
            close = float(curr['Close'])
            open_price = float(curr['Open'])
            vol = float(curr['Volume'])

            if math.isnan(close) or math.isnan(vol): continue
            if open_price == 0 or vol == 0 or high == low: continue

            # --- CALCULATE METRICS ---
            swing_pct = ((high - low) / low) * 100
            value_tx = close * vol
            
            hist_vol = data['Volume'].iloc[:-1] 
            avg_vol = hist_vol.mean() if len(hist_vol) > 0 else vol
            rvol = vol / avg_vol if avg_vol > 0 else 0

            # Position Score (0.0 = At Low, 1.0 = At High)
            range_price = high - low
            pos_score = (close - low) / range_price if range_price > 0 else 0.5
            
            # --- CALCULATE PLAN ---
            entry, target, sl = calc_trading_plan(high, low, close)

            # --- FILTERING ---
            if value_tx < 2_000_000_000: continue
            if swing_pct < 1.5 and rvol < 2.0: continue

            candidates.append({
                'id': t,
                'swing': swing_pct,
                'price': close,
                'high': high,
                'low': low,
                'value_tx': value_tx,
                'rvol': rvol,
                'change': ((close - open_price) / open_price) * 100,
                'pos_score': pos_score,
                'plan_entry': entry,
                'plan_target': target,
                'plan_sl': sl
            })
        except Exception: 
            continue
            
    # Sort: Scalp Score
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
    
    txt = f"⚡ *SCALPER + PLAN SCAN* ⚡\n"
    txt += f"⏱️ Time: {wib_time} WIB\n"
    txt += f"_Focus: Volatility & Low Position_\n\n"
    
    for s in results:
        icon = "⚪"
        if s['change'] > 0: icon = "🟢"
        elif s['change'] < 0: icon = "🔴"
        
        # --- POS INFO & HIGHLIGHT LOGIC ---
        is_dip = False
        pos_info = "Mid"
        
        # Highlight if position is at bottom 20% (Buy the Dip candidate)
        if s['pos_score'] <= 0.2: 
            pos_info = "💎 *LOW/DIP*"
            is_dip = True
        elif s['pos_score'] >= 0.8: 
            pos_info = "🔥 *Top*"
        
        rvol_icon = "🔈"
        if s['rvol'] > 1.5: rvol_icon = "🔊"
        if s['rvol'] > 3.0: rvol_icon = "📢 BOOM"

        # --- BUILDING MESSAGE ---
        # Add Special Header if it's a Dip Candidate
        if is_dip:
            txt += f"🚨 *POTENTIAL DIP BUY: {s['id']}* 🚨\n"
        else:
            txt += f"*{s['id']}* {icon} ({s['change']:+.1f}%)\n"
            
        txt += f"🌊 Swing: *{s['swing']:.1f}%* | Val: {format_val(s['value_tx'])}\n"
        txt += f"📊 Vol: *{s['rvol']:.1f}x* Avg {rvol_icon}\n"
        txt += f"📍 Pos: {pos_info} | Cur: {int(s['price'])}\n"
        
        # Add Plan Section
        txt += f"🎯 *Plan:* Buy <{s['plan_entry']} | TP {s['plan_target']} | SL {s['plan_sl']}\n"
        txt += "----------------------------\n"
        
    push_notification(txt)
    print("✅ Report Sent!")

if __name__ == "__main__":
    main()
