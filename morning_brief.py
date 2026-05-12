"""
====================================================
  MORNING BRIEF — Daily Pre-Market Intelligence
  Runs at 6:00 AM CT every trading day
  Scans news, scores sentiment, plans the day
  Sends summary to phone and saves to brain
====================================================
"""

import os
import json
import logging
import requests
from datetime import datetime, date
from zoneinfo import ZoneInfo

log = logging.getLogger("MorningBrief")
CT = ZoneInfo("America/Chicago")

CLAUDE_API_KEY = os.environ.get("CLAUDE_API_KEY", "")
PUSHOVER_TOKEN = os.environ.get("PUSHOVER_TOKEN", "")
PUSHOVER_USER  = os.environ.get("PUSHOVER_USER", "")
ALPACA_API_KEY    = os.environ.get("ALPACA_API_KEY", "")
ALPACA_SECRET_KEY = os.environ.get("ALPACA_SECRET_KEY", "")


def get_market_snapshot():
    """Get current market data from Alpaca."""
    try:
        headers = {
            "APCA-API-KEY-ID": ALPACA_API_KEY,
            "APCA-API-SECRET-KEY": ALPACA_SECRET_KEY
        }
        # Get SPY snapshot
        resp = requests.get(
            "https://data.alpaca.markets/v2/stocks/snapshots",
            headers=headers,
            params={"symbols": "SPY,QQQ,IWM,VIX"},
            timeout=10
        )
        if resp.status_code == 200:
            return resp.json()
    except Exception as e:
        log.error(f"Market snapshot error: {e}")
    return {}


def load_recent_performance():
    """Load recent trading performance from brain."""
    perf = {
        "recent_pnl": [],
        "win_rate": 0,
        "total_trades": 0,
        "consecutive_losses": 0
    }

    # Load confidence model for stats
    model_path = "trading-brain/Bot_Rules/confidence_model.json"
    if os.path.exists(model_path):
        with open(model_path) as f:
            model = json.load(f)
        total = model.get("total_trades", 0)
        wins = model.get("wins", 0)
        perf["win_rate"] = (wins / total * 100) if total > 0 else 0
        perf["total_trades"] = total

    # Load recent daily summaries
    perf_dir = "trading-brain/Performance"
    if os.path.exists(perf_dir):
        files = sorted([
            f for f in os.listdir(perf_dir)
            if f.startswith("daily_") and f.endswith(".md")
        ])[-5:]
        perf["recent_days"] = len(files)

    return perf


def load_recent_learnings():
    """Load the most recent rules the bot has learned."""
    rules = []
    master_path = "trading-brain/Bot_Rules/master_rules.md"
    if os.path.exists(master_path):
        with open(master_path) as f:
            content = f.read()
        # Extract auto-learned rules (lines with dates)
        for line in content.split("\n"):
            if line.startswith("- [20") and ("RULE:" in line or "✅" in line or "❌" in line):
                rules.append(line.strip())
    return rules[-10:]  # Last 10 learned rules


def generate_morning_brief():
    """
    Claude generates a comprehensive morning brief covering:
    - Market conditions and sentiment
    - Economic events today
    - Strategy recommendations
    - Risk assessment
    - Specific things to watch
    """
    now = datetime.now(CT)
    today = now.strftime("%A, %B %d, %Y")
    day_of_week = now.strftime("%A")

    # Load brain context
    perf = load_recent_performance()
    recent_rules = load_recent_learnings()
    rules_text = "\n".join(recent_rules) if recent_rules else "No rules learned yet — early days"

    prompt = f"""You are a professional trading analyst preparing a morning brief for an AI trading bot.
Today is {today}.

The bot trades SPY (S&P 500 ETF) using VWAP breakout and momentum strategies.
It only trades when confidence >= 80%.

RECENT BOT PERFORMANCE:
- Total trades: {perf['total_trades']}
- Win rate: {perf['win_rate']:.1f}%

RULES THE BOT HAS LEARNED:
{rules_text}

Generate a comprehensive morning brief. Return ONLY this JSON:
{{
  "market_sentiment": "bullish/bearish/neutral/mixed",
  "sentiment_score": 0-100,
  "skip_today": false,
  "skip_reason": "",

  "pre_market_summary": "2-3 sentences on overnight futures, Asian/European markets, and pre-market SPY direction",

  "key_events_today": [
    {{"time": "8:30 AM CT", "event": "Event name", "impact": "high/medium/low", "trading_implication": "what this means for our bot"}}
  ],

  "sector_focus": "Which S&P sectors are strongest/weakest today and why",

  "strategy_for_today": "Which strategy to prioritize today (VWAP Breakout vs Opening Range Breakout) and why",

  "best_trading_windows": ["10:00-11:30 AM", "2:00-3:00 PM"],

  "risk_factors": ["list of specific risks to watch today"],

  "confidence_adjustments": {{
    "morning_session": "+5% — momentum expected",
    "afternoon_session": "-10% — caution after Fed speaker at 2PM"
  }},

  "vix_assessment": "Current VIX environment and what it means for position sizing",

  "one_thing_to_watch": "The single most important thing to monitor today",

  "bot_instructions": "Specific instructions for the bot today in plain English",

  "brief_headline": "One punchy sentence summarizing today's trading environment"
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
                "max_tokens": 1000,
                "messages": [{"role": "user", "content": prompt}]
            },
            timeout=45
        )
        text = resp.json()["content"][0]["text"]
        brief = json.loads(text.replace("```json", "").replace("```", "").strip())
        log.info(f"📰 Morning brief generated: {brief.get('brief_headline', '')}")
        return brief

    except Exception as e:
        log.error(f"Morning brief generation error: {e}")
        return None


def save_brief_to_brain(brief, now):
    """Save the morning brief to the Trading Brain."""
    today = now.strftime("%Y-%m-%d")
    os.makedirs("trading-brain/Performance", exist_ok=True)
    filepath = f"trading-brain/Performance/morning_brief_{today}.md"

    # Format key events
    events = brief.get("key_events_today", [])
    events_text = "\n".join(
        f"- **{e.get('time', 'TBD')}** — {e.get('event', '')} "
        f"[{e.get('impact', 'medium').upper()} IMPACT] "
        f"→ {e.get('trading_implication', '')}"
        for e in events
    ) or "No major events today"

    # Format risk factors
    risks = brief.get("risk_factors", [])
    risks_text = "\n".join(f"- {r}" for r in risks) or "- No major risks identified"

    # Format confidence adjustments
    conf_adj = brief.get("confidence_adjustments", {})
    conf_text = "\n".join(f"- {k}: {v}" for k, v in conf_adj.items()) or "- No adjustments"

    content = f"""# 📰 Morning Brief — {now.strftime('%A, %B %d, %Y')}
*Generated at {now.strftime('%I:%M %p CT')} by Trading Brain AI*

---

## Today's Headline
> **{brief.get('brief_headline', 'Market analysis pending')}**

---

## Market Sentiment
**Overall:** {brief.get('market_sentiment', 'neutral').upper()} ({brief.get('sentiment_score', 50)}/100)
{'⚠️ **SKIP DAY:** ' + brief.get('skip_reason', '') if brief.get('skip_today') else '✅ **TRADING TODAY**'}

{brief.get('pre_market_summary', '')}

---

## Key Events Today
{events_text}

---

## Sector Focus
{brief.get('sector_focus', 'No sector data available')}

---

## Strategy for Today
**Primary Strategy:** {brief.get('strategy_for_today', 'VWAP Breakout')}

**Best Trading Windows:**
{chr(10).join(f'- {w}' for w in brief.get('best_trading_windows', ['10:00-11:30 AM CT']))}

---

## Confidence Adjustments Today
{conf_text}

---

## Risk Factors
{risks_text}

---

## VIX Assessment
{brief.get('vix_assessment', 'VIX data pending')}

---

## One Thing to Watch
⚡ **{brief.get('one_thing_to_watch', 'Monitor pre-market volume')}**

---

## Bot Instructions for Today
{brief.get('bot_instructions', 'Follow standard strategy rules')}

---
*Auto-generated by Morning Brief AI — {now.strftime('%Y-%m-%d %H:%M CT')}*
"""

    with open(filepath, "w") as f:
        f.write(content)

    log.info(f"💾 Morning brief saved: {filepath}")
    return filepath


def send_morning_alert(brief):
    """Send condensed morning brief to phone via Pushover."""
    if not PUSHOVER_TOKEN or not PUSHOVER_USER:
        log.info("📱 Morning brief (no Pushover): " + brief.get('brief_headline', ''))
        return

    sentiment = brief.get('market_sentiment', 'neutral')
    score = brief.get('sentiment_score', 50)
    skip = brief.get('skip_today', False)

    # Sentiment emoji
    if score >= 70:
        emoji = "🟢"
    elif score >= 45:
        emoji = "🟡"
    else:
        emoji = "🔴"

    # Build message
    if skip:
        message = (
            f"⚠️ SKIPPING TODAY\n"
            f"{brief.get('skip_reason', 'Risk too high')}\n\n"
            f"Bot is standing down. See you tomorrow."
        )
    else:
        events = brief.get("key_events_today", [])
        high_impact = [e for e in events if e.get("impact") == "high"]
        events_line = f"⚡ Watch: {high_impact[0]['event']}" if high_impact else "No major events"

        windows = brief.get("best_trading_windows", ["10:00-11:30 AM"])
        watch = brief.get("one_thing_to_watch", "")

        message = (
            f"{emoji} {sentiment.upper()} ({score}/100)\n"
            f"{brief.get('brief_headline', '')}\n\n"
            f"📅 {events_line}\n"
            f"⏰ Best windows: {', '.join(windows[:2])}\n"
            f"👁 {watch}\n\n"
            f"Bot trading from 9:45 AM CT ✅"
        )

    try:
        requests.post("https://api.pushover.net/1/messages.json", data={
            "token": PUSHOVER_TOKEN,
            "user": PUSHOVER_USER,
            "message": message,
            "title": f"🌅 Morning Brief — {datetime.now(CT).strftime('%b %d')}",
            "priority": 0
        }, timeout=10)
        log.info("📱 Morning brief sent to phone")
    except Exception as e:
        log.error(f"Alert error: {e}")


def run_morning_brief():
    """
    Main function — called at 6:00 AM CT every trading day.
    Generates, saves, and sends the morning brief.
    Returns the brief data for the main bot to use.
    """
    now = datetime.now(CT)
    log.info("=" * 60)
    log.info(f"🌅 MORNING BRIEF — {now.strftime('%A %B %d, %Y')}")
    log.info("=" * 60)

    # Generate brief
    brief = generate_morning_brief()
    if not brief:
        log.error("Failed to generate morning brief")
        return {"skip_today": False, "sentiment_score": 50, "market_sentiment": "neutral"}

    # Save to brain
    filepath = save_brief_to_brain(brief, now)

    # Send to phone
    send_morning_alert(brief)

    # Log key info
    log.info(f"📰 Sentiment: {brief.get('market_sentiment')} ({brief.get('sentiment_score')}/100)")
    log.info(f"📰 Headline: {brief.get('brief_headline')}")
    if brief.get('skip_today'):
        log.warning(f"⚠️  SKIP DAY: {brief.get('skip_reason')}")
    else:
        log.info(f"✅ Trading today — strategy: {brief.get('strategy_for_today', '')[:60]}")

    return brief


def get_todays_brief():
    """
    Load today's morning brief if already generated,
    or generate it now if not available.
    Used by the main bot to read today's instructions.
    """
    today = datetime.now(CT).strftime("%Y-%m-%d")
    filepath = f"trading-brain/Performance/morning_brief_{today}.md"

    if os.path.exists(filepath):
        log.info("📰 Today's brief already exists — loading")
        # Parse key fields from saved brief
        with open(filepath) as f:
            content = f.read()
        # Extract sentiment score
        score = 50
        skip = "⚠️ **SKIP DAY:**" in content
        sentiment = "neutral"
        if "BULLISH" in content:
            sentiment = "bullish"
            score = 70
        elif "BEARISH" in content:
            sentiment = "bearish"
            score = 30
        return {
            "skip_today": skip,
            "sentiment_score": score,
            "market_sentiment": sentiment,
            "loaded_from_file": True
        }
    else:
        log.info("📰 No brief yet — generating now")
        return run_morning_brief()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s")
    run_morning_brief()
