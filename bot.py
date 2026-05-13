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
    log.info("🧠 Loading Trading Brain...")
    state["brain"] = {
        "master_rules": read_brain_file("trading-brain/Bot_Rules/master_rules.md"),
        "vwap_strategy": read_brain_file("trading-brain/Strategies/VWAP_Breakout.md"),
        "orb_strategy": read_brain_file("trading-brain/Strategies/Opening_Range_Breakout.md"),
        "recent_failures": [],
        "recent_successes": [],
    }
    log.info("✅ Brain loaded")


def log_trade_to_brain(trade_data, outcome):
    # Add sentiment to trade data
    trade_data["news_sentiment"] = state["news_sentiment"]

    # Use brain writer for rich analysis if available
    if BRAIN_WRITER_AVAILABLE:
        analysis = write_trade_analysis(
            trade_data, outcome,
            state["news_sentiment"],
            state["news_score"]
        )
        if analysis:
            log.info(f"🧠 Brain analysis: {analysis.get('key_lesson', '')}")
            return

    # Fallback: simple logging
    now = datetime.now(CT)
    folder = "trading-brain/Successes" if outcome == "WIN" else "trading-brain/Failures"
    os.makedirs(folder, exist_ok=True)
    filename = f"{folder}/{'success' if outcome == 'WIN' else 'failure'}_{now.strftime('%Y%m%d_%H%M%S')}.md"
    icon = "✅" if outcome == "WIN" else "❌"
    simple_content = f"""# {icon} {outcome} — {now.strftime('%Y-%m-%d %H:%M CT')}
- Entry: ${trade_data.get('entry_price', 0):.2f} | Exit: ${trade_data.get('exit_price', 0):.2f}
- P&L: ${trade_data.get('pnl', 0):.2f} | Confidence: {trade_data.get('confidence', 0)}%
"""
    with open(filename, "w") as f:
        f.write(simple_content)
    log.info(f"🧠 Trade logged: {filename}")


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
                "model": "claude-sonnet-4-20250514",
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
    # Load past memories so the bot learns from history
    memory_context = ""
    if BRAIN_WRITER_AVAILABLE:
        memories = load_past_memories(limit=10)
        memory_context = build_memory_context(memories)

    prompt = f"""You are a trading analyst with memory of past trades. Score this signal.

SIGNAL:
- Symbol: {signal_data['symbol']}
- Direction: {signal_data['direction']}
- Strategy: {signal_data['strategy']}
- Price: ${signal_data['price']:.2f}
- RSI: {signal_data.get('rsi', 'N/A')}
- Volume ratio: {signal_data.get('volume_ratio', 'N/A')}x
- Time: {signal_data['time']}
- News sentiment: {state['news_sentiment']} ({state['news_score']}/100)

{memory_context}

Based on the signal AND your past trade memories above, score this trade.
If current conditions match a past failure rule, lower confidence significantly.
If current conditions match a past success rule, raise confidence.
Reference specific past rules in your reasoning.

Return ONLY this JSON:
{{
  "confidence": 75,
  "execute": false,
  "reasoning": "Explanation referencing past memories if relevant.",
  "lesson_if_loss": "What to learn if this loses."
}}

execute must be false if confidence < {MIN_CONFIDENCE}."""

    try:
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "Content-Type": "application/json",
                "x-api-key": CLAUDE_API_KEY,
                "anthropic-version": "2023-06-01"
            },
            json={
                "model": "claude-sonnet-4-20250514",
                "max_tokens": 200,
                "messages": [{"role": "user", "content": prompt}]
            }, timeout=30
        )
        resp_json = resp.json()
        if "content" not in resp_json:
            log.error(f"Confidence API error: {resp_json.get('error', {}).get('message', str(resp_json))}")
            return {"confidence": 0, "execute": False, "reasoning": "API error", "lesson_if_loss": ""}
        text = resp_json["content"][0]["text"]
        result = json.loads(text.replace("```json", "").replace("```", "").strip())
        confidence = result.get("confidence", 0)
        execute = result.get("execute", False) and confidence >= MIN_CONFIDENCE
        log.info(f"🧠 Brain: {confidence}% — {'✅ EXECUTE' if execute else '❌ SKIP'}")
        log.info(f"🧠 {result.get('reasoning', '')}")
        return {**result, "execute": execute}
    except Exception as e:
        log.error(f"Confidence error: {e}")
        return {"confidence": 0, "execute": False, "reasoning": "Error", "lesson_if_loss": ""}


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

        log.info(f"📊 TradingView: {recommendation} | RSI:{rsi:.1f} | "
                 f"Buy:{buy_signals} Sell:{sell_signals} | ADX:{adx:.1f}")

        strong_buy = (
            recommendation in ["STRONG_BUY", "BUY"] and
            buy_signals >= 10 and
            45 < rsi < 75 and
            macd > macd_signal_val and
            adx > 20
        )

        strong_sell = (
            recommendation in ["STRONG_SELL", "SELL"] and
            sell_signals >= 10 and
            25 < rsi < 55 and
            macd < macd_signal_val and
            adx > 20
        )

        if not (strong_buy or strong_sell):
            return None

        direction = "LONG" if strong_buy else "SHORT"
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
    log.info("🚪 END OF DAY")
    if state["position"]:
        close_position(state["position"]["symbol"])
    send_alert(f"📊 Day done! P&L: ${state['daily_pnl']:.2f} | Trades: {state['trades_today']}")
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
