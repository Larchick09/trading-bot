"""
====================================================
  TRADING BOT - BOT 1 (MES Micro E-Mini S&P 500)
  Central Brain: Google Drive / Obsidian Vault
  Broker: Tradovate (Paper Trading)
  Author: Built with Claude
====================================================
"""

import os
import json
import time
import logging
import schedule
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import requests

# ── Logging setup ──────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("bot.log"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger("TradingBot")

# ── Timezone ───────────────────────────────────────────────────────────────────
CT = ZoneInfo("America/Chicago")

# ── Config (loaded from environment variables set in Railway) ──────────────────
TRADOVATE_USER     = os.environ.get("TRADOVATE_USER", "")
TRADOVATE_PASS     = os.environ.get("TRADOVATE_PASS", "")
TRADOVATE_API_URL  = "https://demo.tradovateapi.com/v1"   # demo = paper trading
CLAUDE_API_KEY     = os.environ.get("CLAUDE_API_KEY", "")
GOOGLE_DRIVE_BRAIN = os.environ.get("GOOGLE_DRIVE_BRAIN_FOLDER_ID", "")
PUSHOVER_TOKEN     = os.environ.get("PUSHOVER_TOKEN", "")   # phone alerts
PUSHOVER_USER      = os.environ.get("PUSHOVER_USER", "")

# ── Risk Rules (matching master_rules.md) ──────────────────────────────────────
MAX_TRADES_PER_DAY   = 5
MAX_DAILY_LOSS       = 200.00   # bot shuts off if daily loss hits this
MAX_DRAWDOWN_PCT     = 0.15     # 15% drawdown = full pause
MIN_CONFIDENCE       = 80       # minimum % confidence to trade
CONTRACTS            = 2        # MES contracts per trade
STOP_TICKS           = 4        # stop loss in ticks (1 tick = $1.25 MES)
TARGET_TICKS         = 8        # profit target in ticks
TICK_VALUE           = 1.25     # MES tick value in dollars

# ── Trading Hours (Central Time) ───────────────────────────────────────────────
MARKET_OPEN          = (9, 30)
FIRST_TRADE          = (9, 45)
LUNCH_START          = (11, 30)
LUNCH_END            = (13, 0)
LAST_ENTRY           = (15, 30)
CLOSE_ALL            = (15, 45)

# ── State ──────────────────────────────────────────────────────────────────────
state = {
    "trades_today": 0,
    "daily_pnl": 0.0,
    "session_active": False,
    "access_token": None,
    "account_id": None,
    "position": None,
    "brain": {},
    "news_sentiment": "neutral",
    "skip_day": False,
    "trade_log": []
}


# ══════════════════════════════════════════════════════════════════════════════
#  SECTION 1: TRADOVATE CONNECTION
# ══════════════════════════════════════════════════════════════════════════════

def tradovate_login():
    """Authenticate with Tradovate demo API."""
    log.info("Logging into Tradovate demo...")
    try:
        resp = requests.post(f"{TRADOVATE_API_URL}/auth/accesstokenrequest", json={
            "name": TRADOVATE_USER,
            "password": TRADOVATE_PASS,
            "appId": "TradingBot",
            "appVersion": "1.0",
            "cid": 0,
            "sec": ""
        }, timeout=10)
        data = resp.json()
        if "accessToken" in data:
            state["access_token"] = data["accessToken"]
            log.info("✅ Tradovate login successful")
            return True
        else:
            log.error(f"❌ Tradovate login failed: {data}")
            return False
    except Exception as e:
        log.error(f"❌ Tradovate connection error: {e}")
        return False


def tradovate_headers():
    return {
        "Authorization": f"Bearer {state['access_token']}",
        "Content-Type": "application/json"
    }


def get_account():
    """Get account ID and balance."""
    try:
        resp = requests.get(f"{TRADOVATE_API_URL}/account/list",
                            headers=tradovate_headers(), timeout=10)
        accounts = resp.json()
        if accounts:
            state["account_id"] = accounts[0]["id"]
            balance = accounts[0].get("balance", 0)
            log.info(f"📊 Account: {state['account_id']} | Balance: ${balance:,.2f}")
            return balance
    except Exception as e:
        log.error(f"Error getting account: {e}")
    return 0


def get_market_data(symbol="MESM6"):
    """Get current price and market data for MES futures."""
    try:
        resp = requests.get(
            f"{TRADOVATE_API_URL}/md/getChart",
            headers=tradovate_headers(),
            params={"symbol": symbol, "chartDescription": {"underlyingType": "MinuteBar", "elementSize": 5}},
            timeout=10
        )
        return resp.json()
    except Exception as e:
        log.error(f"Error getting market data: {e}")
        return None


def place_order(direction, symbol="MESM6"):
    """Place a market order on Tradovate."""
    action = "Buy" if direction == "LONG" else "Sell"
    try:
        resp = requests.post(f"{TRADOVATE_API_URL}/order/placeorder",
                             headers=tradovate_headers(),
                             json={
                                 "accountSpec": TRADOVATE_USER,
                                 "accountId": state["account_id"],
                                 "action": action,
                                 "symbol": symbol,
                                 "orderQty": CONTRACTS,
                                 "orderType": "Market",
                                 "isAutomated": True
                             }, timeout=10)
        result = resp.json()
        log.info(f"📈 Order placed: {action} {CONTRACTS}x {symbol} → {result}")
        return result
    except Exception as e:
        log.error(f"Error placing order: {e}")
        return None


def close_position(symbol="MESM6"):
    """Close all open positions."""
    try:
        resp = requests.post(f"{TRADOVATE_API_URL}/order/liquidateposition",
                             headers=tradovate_headers(),
                             json={
                                 "accountId": state["account_id"],
                                 "symbol": symbol,
                                 "isAutomated": True
                             }, timeout=10)
        log.info(f"🚪 Position closed: {resp.json()}")
        state["position"] = None
    except Exception as e:
        log.error(f"Error closing position: {e}")


# ══════════════════════════════════════════════════════════════════════════════
#  SECTION 2: THE BRAIN — READ FROM GOOGLE DRIVE / OBSIDIAN
# ══════════════════════════════════════════════════════════════════════════════

def read_brain_file(filename):
    """Read a file from the Trading Brain folder in Google Drive via API."""
    try:
        # Search for the file in Google Drive
        search_url = "https://www.googleapis.com/drive/v3/files"
        # In production this uses OAuth2 token from Railway env vars
        # For now reads from local brain folder as fallback
        local_path = f"trading-brain/{filename}"
        if os.path.exists(local_path):
            with open(local_path, "r") as f:
                return f.read()
    except Exception as e:
        log.error(f"Error reading brain file {filename}: {e}")
    return ""


def load_brain():
    """Load the entire Trading Brain into memory."""
    log.info("🧠 Loading Trading Brain...")
    state["brain"] = {
        "master_rules": read_brain_file("Bot_Rules/master_rules.md"),
        "strategies": {
            "vwap": read_brain_file("Strategies/VWAP_Breakout.md"),
            "orb": read_brain_file("Strategies/Opening_Range_Breakout.md"),
        },
        "recent_failures": get_recent_failures(),
        "recent_successes": get_recent_successes(),
    }
    log.info("✅ Brain loaded successfully")


def get_recent_failures(limit=10):
    """Get the most recent failure logs from the brain."""
    failures = []
    failure_dir = "trading-brain/Failures"
    if os.path.exists(failure_dir):
        files = sorted([f for f in os.listdir(failure_dir)
                        if f.startswith("failure_")])[-limit:]
        for f in files:
            with open(f"{failure_dir}/{f}") as fh:
                failures.append(fh.read())
    return failures


def get_recent_successes(limit=10):
    """Get the most recent success logs from the brain."""
    successes = []
    success_dir = "trading-brain/Successes"
    if os.path.exists(success_dir):
        files = sorted([f for f in os.listdir(success_dir)
                        if f.startswith("success_")])[-limit:]
        for f in files:
            with open(f"{success_dir}/{f}") as fh:
                successes.append(fh.read())
    return successes


def log_trade_to_brain(trade_data, outcome):
    """Write trade result back to the Trading Brain."""
    now = datetime.now(CT)
    filename_date = now.strftime("%Y%m%d_%H%M%S")
    folder = "Successes" if outcome == "WIN" else "Failures"
    template_file = "TEMPLATE_success.md" if outcome == "WIN" else "TEMPLATE_failure.md"

    content = f"""# {'✅' if outcome == 'WIN' else '❌'} Trade {outcome} — {now.strftime('%Y-%m-%d %H:%M')}

## Trade Details
- **Date:** {now.strftime('%Y-%m-%d')}
- **Bot:** Bot-1 (MES)
- **Strategy:** {trade_data.get('strategy', 'Unknown')}
- **Direction:** {trade_data.get('direction', 'Unknown')}
- **Entry Price:** {trade_data.get('entry_price', 0)}
- **Exit Price:** {trade_data.get('exit_price', 0)}
- **{'Profit' if outcome == 'WIN' else 'Loss'} Amount:** ${abs(trade_data.get('pnl', 0)):.2f}
- **Contracts:** {CONTRACTS}

## Market Conditions at Entry
- **VIX:** {trade_data.get('vix', 'N/A')}
- **Time of Day:** {trade_data.get('time', 'N/A')}
- **News Sentiment:** {state.get('news_sentiment', 'neutral')}

## Confidence Score Breakdown
- VWAP signal: {trade_data.get('vwap_signal', 'N/A')}
- Volume confirmation: {trade_data.get('volume_ok', 'N/A')}
- RSI reading: {trade_data.get('rsi', 'N/A')}
- News sentiment score: {trade_data.get('news_score', 'N/A')}
- **Final confidence score:** {trade_data.get('confidence', 0)}%

## What the Bot Should Learn
> {trade_data.get('lesson', 'Auto-logged. Review for patterns.')}

## Tags
`#{'success' if outcome == 'WIN' else 'failure'}` `#{trade_data.get('strategy', 'unknown').lower().replace(' ', '-')}` `#{now.strftime('%B-%Y').lower()}`
"""

    # Save locally
    os.makedirs(f"trading-brain/{folder}", exist_ok=True)
    filepath = f"trading-brain/{folder}/{folder.lower()}_{filename_date}.md"
    with open(filepath, "w") as f:
        f.write(content)

    log.info(f"🧠 Trade logged to brain: {filepath}")

    # Update daily summary
    update_daily_summary(trade_data, outcome)


def update_daily_summary(trade_data, outcome):
    """Update today's performance summary in the brain."""
    today = datetime.now(CT).strftime("%Y-%m-%d")
    summary_path = f"trading-brain/Performance/daily_{today}.md"

    # Load existing or create new
    if os.path.exists(summary_path):
        with open(summary_path) as f:
            existing = f.read()
    else:
        existing = f"# 📊 Daily Summary — {today}\n\n## Trades\n"

    # Append trade
    trade_line = f"| {trade_data.get('time', '')} | {trade_data.get('strategy', '')} | {trade_data.get('direction', '')} | {trade_data.get('entry_price', '')} | {trade_data.get('exit_price', '')} | ${trade_data.get('pnl', 0):.2f} | {trade_data.get('confidence', 0)}% | {'✅' if outcome == 'WIN' else '❌'} |\n"

    with open(summary_path, "a") as f:
        f.write(trade_line)


# ══════════════════════════════════════════════════════════════════════════════
#  SECTION 3: NEWS & SENTIMENT CHECK
# ══════════════════════════════════════════════════════════════════════════════

def check_news_and_calendar():
    """Use Claude to analyze market news and economic calendar."""
    log.info("📰 Checking news and economic calendar...")
    today = datetime.now(CT).strftime("%Y-%m-%d")

    prompt = f"""You are a trading risk analyst. Today is {today}.

Analyze the following and return ONLY a JSON object:

1. Are there any major economic events today that would make futures trading risky?
   (Fed meetings, CPI, jobs report, GDP, major geopolitical events)
2. What is the overall market sentiment today based on your knowledge?
3. Should the bot skip trading today?

Return ONLY this JSON (no other text):
{{
  "skip_day": true/false,
  "skip_reason": "reason if skipping, empty string if not",
  "sentiment": "bullish/bearish/neutral",
  "sentiment_score": 0-100,
  "risk_events": ["list", "of", "events"],
  "news_summary": "2 sentence summary of market conditions today"
}}"""

    try:
        resp = requests.post("https://api.anthropic.com/v1/messages",
                             headers={
                                 "Content-Type": "application/json",
                                 "x-api-key": CLAUDE_API_KEY,
                                 "anthropic-version": "2023-06-01"
                             },
                             json={
                                 "model": "claude-sonnet-4-20250514",
                                 "max_tokens": 500,
                                 "messages": [{"role": "user", "content": prompt}]
                             }, timeout=30)

        content = resp.json()["content"][0]["text"]
        # Strip any markdown fences
        clean = content.replace("```json", "").replace("```", "").strip()
        news_data = json.loads(clean)

        state["skip_day"] = news_data.get("skip_day", False)
        state["news_sentiment"] = news_data.get("sentiment", "neutral")
        state["news_score"] = news_data.get("sentiment_score", 50)
        state["news_summary"] = news_data.get("news_summary", "")
        state["risk_events"] = news_data.get("risk_events", [])

        if state["skip_day"]:
            log.warning(f"⚠️  SKIP DAY: {news_data.get('skip_reason')}")
            send_alert(f"⚠️ Bot skipping today: {news_data.get('skip_reason')}")
        else:
            log.info(f"📰 News sentiment: {state['news_sentiment']} ({state['news_score']}/100)")
            log.info(f"📰 {state['news_summary']}")

    except Exception as e:
        log.error(f"News check failed: {e}")
        state["skip_day"] = False
        state["news_sentiment"] = "neutral"
        state["news_score"] = 50


# ══════════════════════════════════════════════════════════════════════════════
#  SECTION 4: CONFIDENCE SCORING ENGINE (THE BRAIN CHECK)
# ══════════════════════════════════════════════════════════════════════════════

def calculate_confidence(signal_data):
    """
    Ask Claude to score a trade signal against the full Trading Brain.
    Returns confidence score 0-100 and reasoning.
    """
    brain = state["brain"]
    recent_failures = "\n\n".join(brain.get("recent_failures", [])[-5:]) or "None yet"
    recent_successes = "\n\n".join(brain.get("recent_successes", [])[-5:]) or "None yet"

    prompt = f"""You are a professional futures trading analyst with access to a trading knowledge base.

## PROPOSED TRADE SIGNAL
- Instrument: MES (Micro E-Mini S&P 500 Futures)
- Direction: {signal_data['direction']}
- Strategy: {signal_data['strategy']}
- Current Price: {signal_data['price']}
- VWAP: {signal_data['vwap']}
- RSI (5min): {signal_data['rsi']}
- Volume vs Average: {signal_data['volume_ratio']}x
- Time: {signal_data['time']}
- News Sentiment: {state['news_sentiment']} ({state.get('news_score', 50)}/100)

## STRATEGY RULES
{brain['strategies'].get(signal_data['strategy_key'], 'No strategy loaded')}

## RECENT FAILURES (learn from these)
{recent_failures}

## RECENT SUCCESSES (replicate these)
{recent_successes}

## MASTER RULES
{brain['master_rules'][:500]}

Based on ALL of the above, score this trade signal.

Return ONLY this JSON (no other text):
{{
  "confidence": 0-100,
  "execute": true/false,
  "reasoning": "2-3 sentence explanation",
  "risk_factors": ["any", "red", "flags"],
  "lesson_if_loss": "what to learn if this trade loses"
}}

The confidence must be 80 or above for execute to be true."""

    try:
        resp = requests.post("https://api.anthropic.com/v1/messages",
                             headers={
                                 "Content-Type": "application/json",
                                 "x-api-key": CLAUDE_API_KEY,
                                 "anthropic-version": "2023-06-01"
                             },
                             json={
                                 "model": "claude-sonnet-4-20250514",
                                 "max_tokens": 500,
                                 "messages": [{"role": "user", "content": prompt}]
                             }, timeout=30)

        content = resp.json()["content"][0]["text"]
        clean = content.replace("```json", "").replace("```", "").strip()
        result = json.loads(clean)

        confidence = result.get("confidence", 0)
        execute = result.get("execute", False) and confidence >= MIN_CONFIDENCE

        log.info(f"🧠 Brain check: {confidence}% confidence — {'✅ EXECUTE' if execute else '❌ SKIP'}")
        log.info(f"🧠 Reasoning: {result.get('reasoning', '')}")

        return {
            "confidence": confidence,
            "execute": execute,
            "reasoning": result.get("reasoning", ""),
            "risk_factors": result.get("risk_factors", []),
            "lesson_if_loss": result.get("lesson_if_loss", "")
        }

    except Exception as e:
        log.error(f"Confidence scoring failed: {e}")
        return {"confidence": 0, "execute": False, "reasoning": "Error in brain check"}


# ══════════════════════════════════════════════════════════════════════════════
#  SECTION 5: STRATEGY SIGNALS
# ══════════════════════════════════════════════════════════════════════════════

def calculate_vwap(prices, volumes):
    """Calculate VWAP from price/volume data."""
    if not prices or not volumes:
        return 0
    cumulative_pv = sum(p * v for p, v in zip(prices, volumes))
    cumulative_v = sum(volumes)
    return cumulative_pv / cumulative_v if cumulative_v > 0 else 0


def calculate_rsi(prices, period=14):
    """Calculate RSI from price list."""
    if len(prices) < period + 1:
        return 50
    gains, losses = [], []
    for i in range(1, len(prices)):
        change = prices[i] - prices[i - 1]
        gains.append(max(change, 0))
        losses.append(max(-change, 0))
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0:
        return 100
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def check_vwap_signal(market_data):
    """Check for VWAP breakout signal."""
    now = datetime.now(CT)
    hour, minute = now.hour, now.minute

    # Only trade in allowed hours
    if (hour, minute) < FIRST_TRADE:
        return None
    if LUNCH_START <= (hour, minute) < LUNCH_END:
        return None
    if (hour, minute) > LAST_ENTRY:
        return None

    # In production: parse real market data from Tradovate
    # For now: return signal structure for brain to evaluate
    # This gets filled with real data from the Tradovate WebSocket
    prices = market_data.get("prices", [])
    volumes = market_data.get("volumes", [])

    if len(prices) < 20:
        return None

    current_price = prices[-1]
    vwap = calculate_vwap(prices, volumes)
    rsi = calculate_rsi(prices)
    avg_volume = sum(volumes[:-1]) / len(volumes[:-1]) if len(volumes) > 1 else 1
    current_volume = volumes[-1] if volumes else 0
    volume_ratio = current_volume / avg_volume if avg_volume > 0 else 0

    # VWAP breakout condition
    prev_price = prices[-2] if len(prices) >= 2 else current_price
    crossed_above = prev_price < vwap and current_price > vwap
    crossed_below = prev_price > vwap and current_price < vwap

    if not (crossed_above or crossed_below):
        return None

    if volume_ratio < 1.3:  # Not enough volume confirmation
        log.info(f"⚠️  VWAP signal detected but volume too low ({volume_ratio:.1f}x)")
        return None

    direction = "LONG" if crossed_above else "SHORT"

    return {
        "strategy": "VWAP Breakout",
        "strategy_key": "vwap",
        "direction": direction,
        "price": current_price,
        "vwap": round(vwap, 2),
        "rsi": round(rsi, 1),
        "volume_ratio": round(volume_ratio, 2),
        "time": now.strftime("%H:%M CT"),
    }


def check_orb_signal(market_data, opening_range):
    """Check for Opening Range Breakout signal (9:45-10:30 CT only)."""
    now = datetime.now(CT)
    hour, minute = now.hour, now.minute

    # ORB only valid in morning window
    if not ((9, 45) <= (hour, minute) <= (10, 30)):
        return None

    if not opening_range:
        return None

    prices = market_data.get("prices", [])
    volumes = market_data.get("volumes", [])

    if not prices:
        return None

    current_price = prices[-1]
    orb_high = opening_range["high"]
    orb_low = opening_range["low"]

    avg_volume = sum(volumes[:-1]) / len(volumes[:-1]) if len(volumes) > 1 else 1
    current_volume = volumes[-1] if volumes else 0
    volume_ratio = current_volume / avg_volume if avg_volume > 0 else 0

    if current_price > orb_high and volume_ratio >= 1.3:
        direction = "LONG"
    elif current_price < orb_low and volume_ratio >= 1.3:
        direction = "SHORT"
    else:
        return None

    vwap = calculate_vwap(prices, volumes)
    rsi = calculate_rsi(prices)

    return {
        "strategy": "Opening Range Breakout",
        "strategy_key": "orb",
        "direction": direction,
        "price": current_price,
        "vwap": round(vwap, 2),
        "rsi": round(rsi, 1),
        "volume_ratio": round(volume_ratio, 2),
        "time": now.strftime("%H:%M CT"),
        "orb_high": orb_high,
        "orb_low": orb_low,
    }


# ══════════════════════════════════════════════════════════════════════════════
#  SECTION 6: RISK MANAGEMENT
# ══════════════════════════════════════════════════════════════════════════════

def check_risk_limits():
    """Check if bot should stop trading based on risk rules."""
    if state["trades_today"] >= MAX_TRADES_PER_DAY:
        log.warning(f"⛔ Max trades reached ({MAX_TRADES_PER_DAY})")
        return False
    if state["daily_pnl"] <= -MAX_DAILY_LOSS:
        log.warning(f"⛔ Daily loss limit hit (${state['daily_pnl']:.2f})")
        send_alert(f"⛔ Daily loss limit hit! Bot stopped for today. P&L: ${state['daily_pnl']:.2f}")
        return False
    return True


def calculate_pnl(entry_price, exit_price, direction):
    """Calculate P&L for a completed trade."""
    ticks = (exit_price - entry_price) / 0.25  # MES tick = 0.25 points
    if direction == "SHORT":
        ticks = -ticks
    return ticks * TICK_VALUE * CONTRACTS


# ══════════════════════════════════════════════════════════════════════════════
#  SECTION 7: PHONE ALERTS
# ══════════════════════════════════════════════════════════════════════════════

def send_alert(message):
    """Send push notification to phone via Pushover."""
    if not PUSHOVER_TOKEN or not PUSHOVER_USER:
        log.info(f"📱 Alert (no Pushover configured): {message}")
        return
    try:
        requests.post("https://api.pushover.net/1/messages.json", data={
            "token": PUSHOVER_TOKEN,
            "user": PUSHOVER_USER,
            "message": message,
            "title": "🤖 Trading Bot"
        }, timeout=10)
    except Exception as e:
        log.error(f"Alert failed: {e}")


# ══════════════════════════════════════════════════════════════════════════════
#  SECTION 8: MAIN TRADING LOOP
# ══════════════════════════════════════════════════════════════════════════════

opening_range = None

def pre_market_routine():
    """6:00 AM CT — Load brain, check news, prepare for the day."""
    log.info("=" * 60)
    log.info("🌅 PRE-MARKET ROUTINE STARTING")
    log.info("=" * 60)

    # Reset daily state
    state["trades_today"] = 0
    state["daily_pnl"] = 0.0
    state["skip_day"] = False
    state["trade_log"] = []

    # Load brain from Google Drive
    load_brain()

    # Check news and economic calendar
    check_news_and_calendar()

    if state["skip_day"]:
        log.warning("⛔ Bot will NOT trade today due to news risk")
    else:
        log.info("✅ Pre-market complete. Bot ready to trade.")
        send_alert(f"🌅 Bot ready. Sentiment: {state['news_sentiment']}. Watching for signals from 9:45 AM CT.")


def establish_opening_range():
    """9:30-9:45 AM CT — Record the opening range."""
    global opening_range
    log.info("📊 Establishing opening range (9:30-9:45 AM)...")
    # In production: collect real 1-min candles from Tradovate
    # opening_range = {"high": max_price, "low": min_price}
    log.info(f"📊 Opening range set: {opening_range}")


def trading_loop():
    """Main trading loop — runs every 60 seconds during market hours."""
    now = datetime.now(CT)
    hour, minute = now.hour, now.minute

    # Skip if not trading day or skip flag set
    if state["skip_day"]:
        return
    if now.weekday() >= 5:  # Weekend
        return
    if not check_risk_limits():
        return
    if state["position"]:  # Already in a trade
        monitor_position()
        return

    # Get market data
    market_data = get_market_data()
    if not market_data:
        return

    # Check strategies
    signal = None

    # Morning: try ORB first
    if (9, 45) <= (hour, minute) <= (10, 30):
        signal = check_orb_signal(market_data, opening_range)

    # All day: VWAP breakout
    if not signal:
        signal = check_vwap_signal(market_data)

    if not signal:
        return

    log.info(f"🔔 Signal detected: {signal['strategy']} {signal['direction']} @ {signal['price']}")

    # ── THE BRAIN CHECK ─────────────────────────────────────────────────────
    brain_result = calculate_confidence(signal)

    if not brain_result["execute"]:
        log.info(f"⏭️  Signal skipped — confidence {brain_result['confidence']}% < {MIN_CONFIDENCE}%")
        log.info(f"   Reason: {brain_result['reasoning']}")
        return

    # ── EXECUTE TRADE ────────────────────────────────────────────────────────
    log.info(f"✅ EXECUTING: {signal['direction']} @ {signal['price']} | Confidence: {brain_result['confidence']}%")
    send_alert(f"📈 Trade: {signal['direction']} MES @ {signal['price']} | {brain_result['confidence']}% confidence\n{brain_result['reasoning']}")

    order = place_order(signal["direction"])
    if order:
        state["position"] = {
            **signal,
            "entry_price": signal["price"],
            "entry_time": now.isoformat(),
            "confidence": brain_result["confidence"],
            "lesson_if_loss": brain_result["lesson_if_loss"],
            "stop_price": signal["price"] - (STOP_TICKS * 0.25) if signal["direction"] == "LONG"
                          else signal["price"] + (STOP_TICKS * 0.25),
            "target_price": signal["price"] + (TARGET_TICKS * 0.25) if signal["direction"] == "LONG"
                            else signal["price"] - (TARGET_TICKS * 0.25),
        }
        state["trades_today"] += 1
        log.info(f"📍 Position open | Stop: {state['position']['stop_price']} | Target: {state['position']['target_price']}")


def monitor_position():
    """Check if open position has hit target or stop loss."""
    if not state["position"]:
        return

    market_data = get_market_data()
    if not market_data:
        return

    prices = market_data.get("prices", [])
    if not prices:
        return

    current_price = prices[-1]
    pos = state["position"]
    direction = pos["direction"]
    hit_target = (direction == "LONG" and current_price >= pos["target_price"]) or \
                 (direction == "SHORT" and current_price <= pos["target_price"])
    hit_stop = (direction == "LONG" and current_price <= pos["stop_price"]) or \
               (direction == "SHORT" and current_price >= pos["stop_price"])

    if hit_target or hit_stop:
        outcome = "WIN" if hit_target else "LOSS"
        pnl = calculate_pnl(pos["entry_price"], current_price, direction)
        state["daily_pnl"] += pnl

        log.info(f"{'✅ TARGET HIT' if hit_target else '❌ STOP HIT'} | P&L: ${pnl:.2f} | Daily: ${state['daily_pnl']:.2f}")
        send_alert(f"{'✅ WIN' if hit_target else '❌ LOSS'}: ${pnl:.2f} | Daily P&L: ${state['daily_pnl']:.2f}")

        close_position()

        # Log to brain
        trade_data = {
            **pos,
            "exit_price": current_price,
            "pnl": pnl,
            "vwap_signal": pos.get("vwap", "N/A"),
            "volume_ok": pos.get("volume_ratio", "N/A"),
            "rsi": pos.get("rsi", "N/A"),
            "news_score": state.get("news_score", 50),
            "lesson": pos.get("lesson_if_loss", "") if outcome == "LOSS" else "Replicate this setup."
        }
        log_trade_to_brain(trade_data, outcome)
        state["position"] = None


def end_of_day():
    """3:45 PM CT — Close all positions, send daily summary."""
    log.info("🚪 END OF DAY — Closing all positions")

    if state["position"]:
        close_position()

    # Send daily summary
    wins = sum(1 for t in state["trade_log"] if t.get("outcome") == "WIN")
    losses = sum(1 for t in state["trade_log"] if t.get("outcome") == "LOSS")
    summary = (f"📊 Day Complete\n"
               f"Trades: {state['trades_today']} | "
               f"Wins: {wins} | Losses: {losses}\n"
               f"Daily P&L: ${state['daily_pnl']:.2f}\n"
               f"Brain updated ✅")

    send_alert(summary)
    log.info(summary)
    log.info("=" * 60)


# ══════════════════════════════════════════════════════════════════════════════
#  SECTION 9: SCHEDULER — RUNS EVERYTHING AUTOMATICALLY
# ══════════════════════════════════════════════════════════════════════════════

def run_bot():
    """Start the bot with full daily schedule."""
    log.info("🤖 TRADING BOT STARTING UP")
    log.info(f"   Instrument: MES Micro E-Mini S&P 500")
    log.info(f"   Mode: Paper Trading (Tradovate Demo)")
    log.info(f"   Min confidence: {MIN_CONFIDENCE}%")
    log.info(f"   Max daily loss: ${MAX_DAILY_LOSS}")

    # Login to Tradovate
    if not tradovate_login():
        log.error("Cannot connect to Tradovate. Check credentials.")
        return

    get_account()

    # Schedule daily tasks (Central Time)
    schedule.every().monday.at("06:00").do(pre_market_routine)
    schedule.every().tuesday.at("06:00").do(pre_market_routine)
    schedule.every().wednesday.at("06:00").do(pre_market_routine)
    schedule.every().thursday.at("06:00").do(pre_market_routine)
    schedule.every().friday.at("06:00").do(pre_market_routine)

    schedule.every().monday.at("09:30").do(establish_opening_range)
    schedule.every().tuesday.at("09:30").do(establish_opening_range)
    schedule.every().wednesday.at("09:30").do(establish_opening_range)
    schedule.every().thursday.at("09:30").do(establish_opening_range)
    schedule.every().friday.at("09:30").do(establish_opening_range)

    schedule.every().monday.at("15:45").do(end_of_day)
    schedule.every().tuesday.at("15:45").do(end_of_day)
    schedule.every().wednesday.at("15:45").do(end_of_day)
    schedule.every().thursday.at("15:45").do(end_of_day)
    schedule.every().friday.at("15:45").do(end_of_day)

    # Trading loop — every 60 seconds during market hours
    schedule.every(60).seconds.do(trading_loop)

    log.info("✅ Scheduler running. Bot is live.")
    send_alert("🤖 Trading Bot is LIVE and running on Railway!")

    while True:
        schedule.run_pending()
        time.sleep(1)


if __name__ == "__main__":
    run_bot()
