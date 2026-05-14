"""
====================================================
  TRADING BOT - BOT 1
  Broker: Alpaca Paper Trading (FREE)
  Brain: Google Drive / Obsidian Vault
  Author: Built with Claude
====================================================
"""

import os
import json
import time
import logging
import schedule
from datetime import datetime
from zoneinfo import ZoneInfo
import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()]
)
log = logging.getLogger("TradingBot")

CT = ZoneInfo("America/Chicago")

ALPACA_API_KEY    = os.environ.get("ALPACA_API_KEY", "")
ALPACA_SECRET_KEY = os.environ.get("ALPACA_SECRET_KEY", "")
ALPACA_BASE_URL   = "https://paper-api.alpaca.markets/v2"
CLAUDE_API_KEY    = os.environ.get("CLAUDE_API_KEY", "")
PUSHOVER_TOKEN    = os.environ.get("PUSHOVER_TOKEN", "")
PUSHOVER_USER     = os.environ.get("PUSHOVER_USER", "")

MAX_TRADES_PER_DAY = 5
MAX_DAILY_LOSS     = 200.00
MIN_CONFIDENCE     = 80
SYMBOL             = "SPY"
QTY                = 2

state = {
    "trades_today": 0,
    "daily_pnl": 0.0,
    "position": None,
    "brain": {},
    "news_sentiment": "neutral",
    "news_score": 50,
    "skip_day": False,
    "trade_log": [],
    "connected": False
}

# ── Feature flags (set defaults, overridden by imports below) ────────────────
BRAIN_WRITER_AVAILABLE = False
MORNING_BRIEF_AVAILABLE = False


def alpaca_headers():
    return {
        "APCA-API-KEY-ID": ALPACA_API_KEY,
        "APCA-API-SECRET-KEY": ALPACA_SECRET_KEY,
        "Content-Type": "application/json"
    }


def alpaca_connect():
    log.info("Connecting to Alpaca paper trading...")
    try:
        resp = requests.get(f"{ALPACA_BASE_URL}/account",
                            headers=alpaca_headers(), timeout=10)
        if resp.status_code == 200:
            account = resp.json()
            balance = float(account.get("portfolio_value", 0))
            log.info(f"✅ Alpaca connected! Portfolio: ${balance:,.2f}")
            state["connected"] = True
            return True
        else:
            log.error(f"❌ Alpaca failed: {resp.status_code} {resp.text}")
            return False
    except Exception as e:
        log.error(f"❌ Alpaca error: {e}")
        return False


def get_current_price(symbol=SYMBOL):
    try:
        resp = requests.get(
            f"https://data.alpaca.markets/v2/stocks/{symbol}/quotes/latest",
            headers=alpaca_headers(), timeout=10
        )
        if resp.status_code == 200:
            data = resp.json()
            ask = data.get("quote", {}).get("ap", 0)
            bid = data.get("quote", {}).get("bp", 0)
            return (ask + bid) / 2 if ask and bid else 0
    except Exception as e:
        log.error(f"Price error: {e}")
    return 0


def place_order(direction, symbol=SYMBOL):
    side = "buy" if direction == "LONG" else "sell"
    try:
        resp = requests.post(
            f"{ALPACA_BASE_URL}/orders",
            headers=alpaca_headers(),
            json={
                "symbol": symbol,
                "qty": QTY,
                "side": side,
                "type": "market",
                "time_in_force": "day"
            }, timeout=10
        )
        if resp.status_code in [200, 201]:
            order = resp.json()
            log.info(f"✅ Order: {side.upper()} {QTY}x {symbol}")
            return order
        else:
            log.error(f"❌ Order failed: {resp.text}")
    except Exception as e:
        log.error(f"Order error: {e}")
    return None


def close_position(symbol=SYMBOL):
    try:
        resp = requests.delete(
            f"{ALPACA_BASE_URL}/positions/{symbol}",
            headers=alpaca_headers(), timeout=10
        )
        if resp.status_code in [200, 204]:
            log.info(f"🚪 Position closed: {symbol}")
        state["position"] = None
    except Exception as e:
        log.error(f"Close error: {e}")


def read_brain_file(filepath):
    if os.path.exists(filepath):
        with open(filepath) as f:
            return f.read()
    return ""


def load_brain():
    """Load brain from Google Drive if configured, else local files."""
    log.info("🧠 Loading Trading Brain...")
    
    gdrive_folder = os.environ.get("GOOGLE_DRIVE_BRAIN_FOLDER_ID", "")
    
    if gdrive_folder:
        log.info("☁️  Loading brain from Google Drive...")
        _load_brain_from_gdrive(gdrive_folder)
    else:
        log.info("📁 Loading brain from local files...")
        _load_brain_local()
    
    log.info("✅ Brain loaded")


def _load_brain_from_gdrive(folder_id):
    """Load brain files directly from Google Drive API."""
    try:
        # Get access token from environment
        gdrive_token = os.environ.get("GDRIVE_TOKEN", "")
        
        headers = {}
        if gdrive_token:
            headers["Authorization"] = f"Bearer {gdrive_token}"
        
        # Map of what to load and where to store it
        file_map = {
            "master_rules.md": ("Bot_Rules", "master_rules"),
            "VWAP_Breakout.md": ("Strategies", "vwap_strategy"),
            "Opening_Range_Breakout.md": ("Strategies", "orb_strategy"),
        }
        
        brain = {
            "master_rules": "",
            "vwap_strategy": "",
            "orb_strategy": "",
            "aziz_rules": "",
            "recent_failures": [],
            "recent_successes": [],
        }
        
        # Search for each file in Google Drive
        for filename, (subfolder, brain_key) in file_map.items():
            try:
                # Search for the file
                search_url = "https://www.googleapis.com/drive/v3/files"
                resp = requests.get(search_url, headers=headers, params={
                    "q": f"name='{filename}' and '{folder_id}' in parents",
                    "fields": "files(id,name)"
                }, timeout=10)
                
                files = resp.json().get("files", [])
                if files:
                    file_id = files[0]["id"]
                    # Download file content
                    dl_url = f"https://www.googleapis.com/drive/v3/files/{file_id}"
                    dl_resp = requests.get(dl_url, headers=headers, 
                                          params={"alt": "media"}, timeout=10)
                    if dl_resp.status_code == 200:
                        brain[brain_key] = dl_resp.text
                        log.info(f"☁️  Loaded: {filename}")
            except Exception as e:
                log.warning(f"Could not load {filename} from Drive: {e}")
        
        # Try to load Aziz strategy
        try:
            resp = requests.get("https://www.googleapis.com/drive/v3/files", 
                headers=headers, params={
                    "q": f"name contains 'Aziz' and '{folder_id}' in parents",
                    "fields": "files(id,name)"
                }, timeout=10)
            files = resp.json().get("files", [])
            if files:
                file_id = files[0]["id"]
                dl_resp = requests.get(
                    f"https://www.googleapis.com/drive/v3/files/{file_id}",
                    headers=headers, params={"alt": "media"}, timeout=10)
                if dl_resp.status_code == 200:
                    brain["aziz_rules"] = dl_resp.text[:3000]
                    log.info("☁️  Loaded: Aziz strategy")
        except Exception as e:
            log.warning(f"Could not load Aziz strategy: {e}")
        
        state["brain"] = brain
        
    except Exception as e:
        log.error(f"Google Drive brain load failed: {e} — using local files")
        _load_brain_local()


def _load_brain_local():
    """Load brain from local files on Railway server."""
    state["brain"] = {
        "master_rules": read_brain_file("trading-brain/Bot_Rules/master_rules.md"),
        "vwap_strategy": read_brain_file("trading-brain/Strategies/VWAP_Breakout.md"),
        "orb_strategy": read_brain_file("trading-brain/Strategies/Opening_Range_Breakout.md"),
        "aziz_rules": "",
        "recent_failures": [],
        "recent_successes": [],
    }


def check_news_and_calendar():
    log.info("📰 Checking news and calendar...")
    today = datetime.now(CT).strftime("%Y-%m-%d")
    prompt = f"""You are a trading risk analyst. Today is {today}.
Are there major economic events today that make US stock trading risky?
Return ONLY this JSON:
{{
  "skip_day": false,
  "skip_reason": "",
  "sentiment": "neutral",
  "sentiment_score": 50,
  "news_summary": "Market conditions summary here."
}}"""
    try:
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "Content-Type": "application/json",
                "x-api-key": CLAUDE_API_KEY,
                "anthropic-version": "2023-06-01"
            },
            json={
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 300,
                "messages": [{"role": "user", "content": prompt}]
            }, timeout=30
        )
        resp_json = resp.json()
        if "content" not in resp_json:
            log.error(f"News API error: {resp_json.get('error', {}).get('message', str(resp_json))}")
            state["skip_day"] = False
            state["news_sentiment"] = "neutral"
            state["news_score"] = 50
            return
        text = resp_json["content"][0]["text"]
        data = json.loads(text.replace("```json", "").replace("```", "").strip())
        state["skip_day"] = data.get("skip_day", False)
        state["news_sentiment"] = data.get("sentiment", "neutral")
        state["news_score"] = data.get("sentiment_score", 50)
        if state["skip_day"]:
            log.warning(f"⚠️  SKIP DAY: {data.get('skip_reason')}")
        else:
            log.info(f"📰 Sentiment: {state['news_sentiment']} | {data.get('news_summary', '')}")
    except Exception as e:
        log.error(f"News error: {e}")
        state["skip_day"] = False
        state["news_sentiment"] = "neutral"
        state["news_score"] = 50


def calculate_confidence(signal_data):
    """Score a trade signal using Claude with structured output."""
    try:
        system_prompt = (
            "You are a trading analysis agent. "
            "You must ALWAYS respond with a JSON object and nothing else. "
            "No explanation before or after. No markdown. Pure JSON only. "
            'Format: {"confidence": 85, "execute": true, "reasoning": "brief reason", "lesson_if_loss": "brief lesson"} '
            "confidence is 0-100. execute is true only if confidence >= 80."
        )

        user_msg = (
            "Score this trade: "
            + signal_data.get('direction', 'LONG')
            + " SPY. RSI=" + str(round(signal_data.get('rsi', 50), 1))
            + " BuySignals=" + str(signal_data.get('buy_signals', 0))
            + "/16 ADX=" + str(round(signal_data.get('adx', 0), 1))
            + " News=" + state.get('news_sentiment', 'neutral')
            + ". Reply with JSON only."
        )

        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "Content-Type": "application/json",
                "x-api-key": CLAUDE_API_KEY,
                "anthropic-version": "2023-06-01"
            },
            json={
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 80,
                "system": system_prompt,
                "messages": [{"role": "user", "content": user_msg}]
            },
            timeout=15
        )

        resp_json = resp.json()
        if "content" not in resp_json:
            log.warning(f"API issue — fallback")
            return _fallback_confidence(signal_data)

        text = resp_json["content"][0]["text"].strip()
        
        # Extract JSON
        start = text.find("{")
        end = text.rfind("}") + 1
        if start == -1 or end == 0:
            return _fallback_confidence(signal_data)

        import re
        json_str = text[start:end]
        json_str = re.sub(r'[\n\r\t]', ' ', json_str)
        json_str = json_str.encode('ascii', 'ignore').decode('ascii')

        result = json.loads(json_str)
        confidence = int(result.get("confidence", 0))
        execute = confidence >= MIN_CONFIDENCE

        log.info(f"Brain: {confidence}% — {'EXECUTE' if execute else 'SKIP'}")
        return {**result, "execute": execute, "confidence": confidence}

    except Exception as e:
        log.warning(f"Confidence error: {e} — fallback")
        return _fallback_confidence(signal_data)


def _fallback_confidence(signal_data):
    """
    Calculate confidence from signal strength alone when Claude API fails.
    This ensures the bot still trades even if AI scoring is unavailable.
    """
    buy_signals = signal_data.get('buy_signals', 0)
    sell_signals = signal_data.get('sell_signals', 0)
    rsi = signal_data.get('rsi', 50)
    adx = signal_data.get('adx', 0)
    recommendation = signal_data.get('tv_recommendation', 'NEUTRAL')
    direction = signal_data.get('direction', 'LONG')

    # Base score from indicator consensus
    total = buy_signals + sell_signals
    if total == 0:
        return {"confidence": 0, "execute": False, "reasoning": "No signals", "lesson_if_loss": ""}

    if direction == "LONG":
        consensus = (buy_signals / total) * 100
    else:
        consensus = (sell_signals / total) * 100

    # Adjust for recommendation strength
    if recommendation == "STRONG_BUY" and direction == "LONG":
        consensus += 10
    elif recommendation == "STRONG_SELL" and direction == "SHORT":
        consensus += 10

    # Adjust for ADX (trend strength)
    if adx > 40:
        consensus += 8
    elif adx > 25:
        consensus += 4

    # Cap at 95
    confidence = min(int(consensus), 95)
    execute = confidence >= MIN_CONFIDENCE

    log.info(f"🧠 Fallback confidence: {confidence}% — {'✅ EXECUTE' if execute else '❌ SKIP'}")
    return {
        "confidence": confidence,
        "execute": execute,
        "reasoning": f"Fallback scoring: {buy_signals} buy signals, ADX {adx:.1f}",
        "lesson_if_loss": "Review signal quality"
    }


def get_tradingview_analysis(symbol=SYMBOL):
    """Get full TradingView technical analysis — professional grade signals."""
    try:
        from tradingview_ta import TA_Handler, Interval
        # Try multiple exchanges since SPY can appear on different ones
        for exchange in ["AMEX", "NYSE", "ARCA"]:
            try:
                handler = TA_Handler(
                    symbol=symbol,
                    screener="america",
                    exchange=exchange,
                    interval=Interval.INTERVAL_5_MINUTES
                )
                analysis = handler.get_analysis()
                close_price = analysis.indicators.get("close", 0)
                # SPY should be between $500-700, reject if way off
                if symbol == "SPY" and (close_price < 400 or close_price > 800):
                    log.warning(f"SPY price {close_price} looks wrong on {exchange}, trying next")
                    continue
                log.info(f"✅ TradingView connected via {exchange}")
                break
            except Exception:
                continue
        ind = analysis.indicators
        summary = analysis.summary
        return {
            "recommendation": summary.get("RECOMMENDATION", "NEUTRAL"),
            "buy_signals": summary.get("BUY", 0),
            "sell_signals": summary.get("SELL", 0),
            "neutral_signals": summary.get("NEUTRAL", 0),
            "rsi": ind.get("RSI", 50),
            "macd": ind.get("MACD.macd", 0),
            "macd_signal": ind.get("MACD.signal", 0),
            "ema20": ind.get("EMA20", 0),
            "ema50": ind.get("EMA50", 0),
            "vwap": ind.get("VWAP", 0),
            "bb_upper": ind.get("BB.upper", 0),
            "bb_lower": ind.get("BB.lower", 0),
            "volume": ind.get("volume", 0),
            "close": ind.get("close", 0),
            "adx": ind.get("ADX", 0),
            "stoch_k": ind.get("Stoch.K", 50),
        }
    except ImportError:
        log.warning("tradingview-ta not installed")
        return None
    except Exception as e:
        log.error(f"TradingView error: {e}")
        return None


def calculate_rsi(prices, period=14):
    if len(prices) < period + 1:
        return 50
    gains = [max(prices[i] - prices[i-1], 0) for i in range(1, len(prices))]
    losses = [max(prices[i-1] - prices[i], 0) for i in range(1, len(prices))]
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0:
        return 100
    return 100 - (100 / (1 + avg_gain / avg_loss))


def get_bars(symbol=SYMBOL, limit=50):
    try:
        resp = requests.get(
            f"https://data.alpaca.markets/v2/stocks/{symbol}/bars",
            headers=alpaca_headers(),
            params={"timeframe": "5Min", "limit": limit},
            timeout=10
        )
        if resp.status_code == 200:
            return resp.json().get("bars", [])
    except Exception as e:
        log.error(f"Bars error: {e}")
    return []


def check_signal():
    """Check for trading signal using TradingView analysis + Alpaca fallback."""
    now = datetime.now(CT)
    hour, minute = now.hour, now.minute

    if (hour, minute) < (9, 45):
        return None
    if (11, 30) <= (hour, minute) < (13, 0):
        return None
    if (hour, minute) > (15, 30):
        return None

    # Try TradingView first — much richer data
    tv = get_tradingview_analysis()

    if tv and tv["close"] > 0:
        current_price = tv["close"]
        rsi = tv["rsi"]
        vwap = tv["vwap"]
        recommendation = tv["recommendation"]
        buy_signals = tv["buy_signals"]
        sell_signals = tv["sell_signals"]
        macd = tv["macd"]
        macd_signal_val = tv["macd_signal"]
        adx = tv["adx"]

        # Detect ranging/choppy market — skip if ADX too low
        if adx < 20:
            log.info(f"📊 RANGING MARKET detected (ADX:{adx:.1f} < 20) — skipping all signals")
            log.info(f"📊 Choppy market: price bouncing sideways, breakouts unreliable")
            return None

        market_type = "TRENDING" if adx > 25 else "WEAK TREND"
        log.info(f"📊 TradingView: {recommendation} | RSI:{rsi:.1f} | "
                 f"Buy:{buy_signals} Sell:{sell_signals} | ADX:{adx:.1f} | {market_type}")

        strong_buy = (
            recommendation in ["STRONG_BUY", "BUY"] and
            buy_signals >= 10 and
            rsi > 45 and
            adx > 20
        )

        strong_sell = (
            recommendation in ["STRONG_SELL", "SELL"] and
            sell_signals >= 10 and
            rsi < 55 and
            adx > 20
        )

        if not (strong_buy or strong_sell):
            log.info(f"📊 No signal — Buy:{buy_signals} Sell:{sell_signals} RSI:{rsi:.1f} MACD:{'✅' if macd > macd_signal_val else '❌'} ADX:{adx:.1f}")
            return None

        direction = "LONG" if strong_buy else "SHORT"
        log.info(f"🔔 {'LONG' if strong_buy else 'SHORT'} signal @ ${current_price:.2f} | RSI:{rsi:.1f} | Buy:{buy_signals} Sell:{sell_signals}")
        return {
            "symbol": SYMBOL,
            "strategy": f"TradingView {recommendation}",
            "direction": direction,
            "price": current_price,
            "vwap": round(vwap, 2),
            "rsi": round(rsi, 1),
            "volume_ratio": round(tv["volume"] / 1000000, 2),
            "buy_signals": buy_signals,
            "sell_signals": sell_signals,
            "macd": round(macd, 4),
            "adx": round(adx, 1),
            "time": now.strftime("%H:%M CT"),
            "tv_recommendation": recommendation,
        }

    # Fallback: Alpaca VWAP crossover
    log.info("📊 TradingView unavailable — using Alpaca fallback")
    bars = get_bars()
    if len(bars) < 20:
        return None

    closes = [b["c"] for b in bars]
    volumes = [b["v"] for b in bars]
    current_price = closes[-1]
    total_vol = sum(volumes)
    vwap = sum(c * v for c, v in zip(closes, volumes)) / total_vol if total_vol > 0 else current_price
    rsi = calculate_rsi(closes)
    avg_vol = sum(volumes[:-1]) / len(volumes[:-1]) if len(volumes) > 1 else 1
    vol_ratio = volumes[-1] / avg_vol if avg_vol > 0 else 0
    prev_price = closes[-2] if len(closes) >= 2 else current_price
    crossed_above = prev_price < vwap and current_price > vwap
    crossed_below = prev_price > vwap and current_price < vwap
    if not (crossed_above or crossed_below):
        return None
    if vol_ratio < 1.3:
        return None
    direction = "LONG" if crossed_above else "SHORT"
    return {
        "symbol": SYMBOL,
        "strategy": "VWAP Breakout",
        "direction": direction,
        "price": current_price,
        "vwap": round(vwap, 2),
        "rsi": round(rsi, 1),
        "volume_ratio": round(vol_ratio, 2),
        "time": now.strftime("%H:%M CT"),
    }


def check_risk_limits():
    if state["trades_today"] >= MAX_TRADES_PER_DAY:
        log.warning(f"⛔ Max trades reached")
        return False
    if state["daily_pnl"] <= -MAX_DAILY_LOSS:
        log.warning(f"⛔ Daily loss limit hit")
        send_alert(f"⛔ Daily loss limit! P&L: ${state['daily_pnl']:.2f}")
        return False
    return True


def send_alert(message):
    if not PUSHOVER_TOKEN or not PUSHOVER_USER:
        log.info(f"📱 Alert: {message}")
        return
    try:
        requests.post("https://api.pushover.net/1/messages.json", data={
            "token": PUSHOVER_TOKEN,
            "user": PUSHOVER_USER,
            "message": message,
            "title": "🤖 Trading Bot"
        }, timeout=10)
    except Exception as e:
        log.error(f"Alert error: {e}")


def pre_market_routine():
    log.info("=" * 60)
    log.info("🌅 PRE-MARKET STARTING")
    state["trades_today"] = 0
    state["daily_pnl"] = 0.0
    state["skip_day"] = False
    state["trade_log"] = []
    load_brain()
    check_news_and_calendar()
    if not state["skip_day"]:
        send_alert(f"🌅 Bot ready! Sentiment: {state['news_sentiment']}. Trading 9:45 AM CT.")


def monitor_position():
    if not state["position"]:
        return
    current_price = get_current_price(state["position"]["symbol"])
    if not current_price:
        return

    pos = state["position"]
    direction = pos["direction"]
    hit_target = (direction == "LONG" and current_price >= pos["target_price"]) or \
                 (direction == "SHORT" and current_price <= pos["target_price"])
    hit_stop = (direction == "LONG" and current_price <= pos["stop_price"]) or \
               (direction == "SHORT" and current_price >= pos["stop_price"])

    if hit_target or hit_stop:
        outcome = "WIN" if hit_target else "LOSS"
        pnl = (current_price - pos["entry_price"]) * QTY
        if direction == "SHORT":
            pnl = -pnl
        state["daily_pnl"] += pnl

        log.info(f"{'✅ WIN' if hit_target else '❌ LOSS'} | P&L: ${pnl:.2f} | Daily: ${state['daily_pnl']:.2f}")
        send_alert(f"{'✅ WIN' if hit_target else '❌ LOSS'}: ${pnl:.2f} | Daily: ${state['daily_pnl']:.2f}")

        close_position(pos["symbol"])
        log_trade_to_brain({
            **pos,
            "exit_price": current_price,
            "pnl": pnl,
            "lesson": pos.get("lesson_if_loss", "") if outcome == "LOSS" else "Replicate this setup."
        }, outcome)


def trading_loop():
    now = datetime.now(CT)
    if now.weekday() >= 5:
        return
    if state["skip_day"]:
        return
    if not check_risk_limits():
        return
    if state["position"]:
        monitor_position()
        return

    signal = check_signal()
    if not signal:
        return

    log.info(f"🔔 Signal: {signal['strategy']} {signal['direction']} @ ${signal['price']:.2f}")

    brain_result = calculate_confidence(signal)
    if not brain_result["execute"]:
        log.info(f"⏭️  Skipped — {brain_result['confidence']}% confidence")
        return

    log.info(f"✅ EXECUTING: {signal['direction']} {signal['symbol']} @ ${signal['price']:.2f} | {brain_result['confidence']}%")
    send_alert(f"📈 Trade: {signal['direction']} {signal['symbol']} @ ${signal['price']:.2f} | {brain_result['confidence']}% confidence")

    order = place_order(signal["direction"], signal["symbol"])
    if order:
        offset = signal["price"] * 0.002
        state["position"] = {
            **signal,
            "entry_price": signal["price"],
            "confidence": brain_result["confidence"],
            "lesson_if_loss": brain_result.get("lesson_if_loss", ""),
            "stop_price": signal["price"] - offset if signal["direction"] == "LONG" else signal["price"] + offset,
            "target_price": signal["price"] + offset * 2 if signal["direction"] == "LONG" else signal["price"] - offset * 2,
        }
        state["trades_today"] += 1


def end_of_day():
    log.info("🚪 END OF DAY — Closing all positions")
    
    # Close tracked position
    if state["position"]:
        symbol = state["position"]["symbol"]
        log.info(f"Closing tracked position: {symbol}")
        close_position(symbol)
    
    # Also force-close any open positions on Alpaca directly
    try:
        resp = requests.delete(
            f"{ALPACA_BASE_URL}/positions",
            headers=alpaca_headers(),
            timeout=10
        )
        if resp.status_code in [200, 204, 207]:
            log.info("✅ All Alpaca positions closed")
        else:
            log.warning(f"Position close response: {resp.status_code}")
    except Exception as e:
        log.error(f"Error closing all positions: {e}")

    summary = f"📊 Day done! P&L: ${state['daily_pnl']:.2f} | Trades: {state['trades_today']}"
    send_alert(summary)
    log.info(summary)
    log.info("=" * 60)


def run_bot():
    log.info("🤖 TRADING BOT STARTING UP")
    log.info(f"   Broker: Alpaca Paper Trading")
    log.info(f"   Symbol: {SYMBOL}")
    log.info(f"   Min confidence: {MIN_CONFIDENCE}%")
    log.info(f"   Max daily loss: ${MAX_DAILY_LOSS}")

    alpaca_connect()
    load_brain()

    for day in ["monday", "tuesday", "wednesday", "thursday", "friday"]:
        getattr(schedule.every(), day).at("06:00").do(pre_market_routine)
        getattr(schedule.every(), day).at("15:45").do(end_of_day)

    schedule.every(60).seconds.do(trading_loop)

    log.info("✅ Scheduler running. Bot is live 24/7!")
    send_alert("🤖 Trading Bot LIVE on Railway!")

    while True:
        schedule.run_pending()
        time.sleep(1)


if __name__ == "__main__":
    run_bot()


# ── Brain Writer Integration ─────────────────────────────────────────────────
try:
    from brain_writer import write_trade_analysis, load_past_memories, build_memory_context
    BRAIN_WRITER_AVAILABLE = True
    log.info("✅ Brain writer loaded")
except ImportError:
    BRAIN_WRITER_AVAILABLE = False
    log.warning("⚠️  Brain writer not available")

# ── Morning Brief Integration ─────────────────────────────────────────────────
try:
    from morning_brief import run_morning_brief, get_todays_brief
    MORNING_BRIEF_AVAILABLE = True
    log.info("✅ Morning brief loaded")
except ImportError:
    MORNING_BRIEF_AVAILABLE = False
    log.warning("⚠️  Morning brief not available")
