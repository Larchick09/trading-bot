"""
====================================================
  BRAIN WRITER — Deep Learning Engine
  Writes rich causal analysis after every trade
  Reads past memories to build genuine understanding
  Syncs everything back to Google Drive
====================================================
"""

import os
import json
import logging
import requests
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path

log = logging.getLogger("BrainWriter")
CT = ZoneInfo("America/Chicago")
CLAUDE_API_KEY    = os.environ.get("CLAUDE_API_KEY", "")
GDRIVE_API_KEY    = os.environ.get("GDRIVE_TOKEN", "")
GDRIVE_FOLDER_ID  = os.environ.get("GOOGLE_DRIVE_BRAIN_FOLDER_ID", "")


# ══════════════════════════════════════════════════════════════════════════════
#  SECTION 1: DEEP TRADE ANALYSIS
#  After every trade, Claude builds genuine causal understanding
# ══════════════════════════════════════════════════════════════════════════════

def write_trade_analysis(trade_data, outcome, news_sentiment, news_score):
    """
    Claude writes a rich causal analysis of why the trade won or lost.
    Not just what happened — but WHY it happened at a market mechanics level.
    This is what builds genuine understanding over time.
    """
    now = datetime.now(CT)

    prompt = f"""You are a professional quantitative trading analyst reviewing a completed trade.
Your job is to write a DEEP CAUSAL ANALYSIS — not just what happened, but WHY it happened
at a market mechanics level. Future trades will read this to genuinely understand the market.

TRADE DATA:
- Outcome: {outcome}
- Strategy: {trade_data.get('strategy', 'VWAP Breakout')}
- Symbol: {trade_data.get('symbol', 'SPY')}
- Direction: {trade_data.get('direction', 'LONG')}
- Entry: ${trade_data.get('entry_price', 0):.2f}
- Exit: ${trade_data.get('exit_price', 0):.2f}
- P&L: ${trade_data.get('pnl', 0):.2f}
- Confidence at entry: {trade_data.get('confidence', 0)}%
- RSI at entry: {trade_data.get('rsi', 'N/A')}
- Volume ratio: {trade_data.get('volume_ratio', 'N/A')}x
- Time of day: {trade_data.get('time', 'N/A')}
- News sentiment: {news_sentiment} ({news_score}/100)

Return ONLY this JSON (no markdown, no extra text):
{{
  "causal_analysis": "Write 4-5 sentences explaining the MARKET MECHANICS behind why this trade {'succeeded' if outcome == 'WIN' else 'failed'}. Go deep: what were institutional players doing? What does the RSI level indicate about buyer/seller exhaustion? What does volume at this level mean? Why did the VWAP crossover {'hold' if outcome == 'WIN' else 'fail'}? Reference the specific numbers.",

  "what_market_was_telling_us": "Write 2-3 sentences on what the market was signaling BEFORE entry that the bot should recognize next time. What were the early warning signs of {'success' if outcome == 'WIN' else 'failure'}?",

  "key_rule": "ONE specific rule in IF-THEN format. Example: IF RSI > 68 AND sentiment < 45 AND time is afternoon THEN skip — exhaustion trap not breakout. Be specific with numbers.",

  "condition_fingerprint": {{
    "rsi_zone": "low/neutral/high/overbought",
    "volume_quality": "weak/moderate/strong/exceptional",
    "time_session": "pre-market/early-morning/mid-morning/lunch/afternoon/late",
    "sentiment_zone": "bearish/neutral/bullish",
    "outcome": "{outcome}"
  }},

  "confidence_model_update": {{
    "conditions_that_caused_this": ["list", "of", "specific", "conditions"],
    "adjust_confidence_by": -15,
    "when_to_apply": "description of when to apply this adjustment"
  }},

  "pattern_name": "Give this pattern a memorable name like 'Morning Exhaustion Trap' or 'High Volume Breakout'"
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
                "max_tokens": 800,
                "messages": [{"role": "user", "content": prompt}]
            },
            timeout=45
        )
        text = resp.json()["content"][0]["text"]
        analysis = json.loads(text.replace("```json", "").replace("```", "").strip())

        # Save memory file
        filepath = _save_deep_memory(trade_data, outcome, analysis, now)

        # Update master rules
        _update_master_rules_deep(analysis, outcome, now)

        # Update confidence model
        _update_confidence_model(analysis, outcome, now)

        # Sync to Google Drive
        _sync_file_to_gdrive(filepath)

        log.info(f"🧠 Deep analysis written: {analysis.get('pattern_name', 'Unknown pattern')}")
        log.info(f"🧠 Rule learned: {analysis.get('key_rule', '')}")
        return analysis

    except Exception as e:
        log.error(f"Brain write error: {e}")
        return None


def _save_deep_memory(trade_data, outcome, analysis, now):
    """Save the full deep memory with causal analysis."""
    folder = "trading-brain/Successes" if outcome == "WIN" else "trading-brain/Failures"
    os.makedirs(folder, exist_ok=True)

    pattern_name = analysis.get("pattern_name", "Unknown Pattern")
    safe_pattern = pattern_name.replace(" ", "_").replace("/", "-")
    filename = f"{folder}/{'success' if outcome == 'WIN' else 'failure'}_{now.strftime('%Y%m%d_%H%M%S')}_{safe_pattern}.md"
    icon = "✅" if outcome == "WIN" else "❌"

    # Build fingerprint display
    fp = analysis.get("condition_fingerprint", {})
    fingerprint = f"RSI: {fp.get('rsi_zone', 'N/A')} | Volume: {fp.get('volume_quality', 'N/A')} | Time: {fp.get('time_session', 'N/A')} | Sentiment: {fp.get('sentiment_zone', 'N/A')}"

    content = f"""# {icon} {outcome} — {pattern_name}
*{now.strftime('%Y-%m-%d %H:%M CT')}*

---

## Trade Details
| Field | Value |
|-------|-------|
| Strategy | {trade_data.get('strategy', 'N/A')} |
| Direction | {trade_data.get('direction', 'N/A')} |
| Entry | ${trade_data.get('entry_price', 0):.2f} |
| Exit | ${trade_data.get('exit_price', 0):.2f} |
| P&L | ${trade_data.get('pnl', 0):.2f} |
| Confidence | {trade_data.get('confidence', 0)}% |
| RSI | {trade_data.get('rsi', 'N/A')} |
| Volume | {trade_data.get('volume_ratio', 'N/A')}x |
| Time | {trade_data.get('time', 'N/A')} |
| Sentiment | {trade_data.get('news_sentiment', 'N/A')} |

---

## Why It {'Succeeded' if outcome == 'WIN' else 'Failed'} — Causal Analysis
{analysis.get('causal_analysis', 'No analysis available.')}

---

## What the Market Was Telling Us
{analysis.get('what_market_was_telling_us', 'No market reading available.')}

---

## Rule Learned
> **{analysis.get('key_rule', 'No rule extracted.')}**

---

## Condition Fingerprint
`{fingerprint}`

---

## Confidence Model Update
- **Adjust by:** {analysis.get('confidence_model_update', {}).get('adjust_confidence_by', 0):+d}%
- **When:** {analysis.get('confidence_model_update', {}).get('when_to_apply', 'N/A')}
- **Conditions:** {', '.join(analysis.get('confidence_model_update', {}).get('conditions_that_caused_this', []))}

---

## Bot Instructions
- **Replicate:** {'✅ Yes' if outcome == 'WIN' else '❌ No'}
- **Avoid:** {'✅ Yes' if outcome == 'LOSS' else '❌ No'}

*Auto-generated by Trading Brain Deep Analysis — {now.strftime('%Y-%m-%d %H:%M CT')}*
"""

    with open(filename, "w") as f:
        f.write(content)
    log.info(f"💾 Deep memory saved: {filename}")
    return filename


def _update_master_rules_deep(analysis, outcome, now):
    """Add learned rule to master_rules.md."""
    master_path = "trading-brain/Bot_Rules/master_rules.md"
    if not os.path.exists(master_path):
        return

    rule = analysis.get("key_rule", "")
    pattern = analysis.get("pattern_name", "Unknown")
    if not rule:
        return

    icon = "✅" if outcome == "WIN" else "❌"
    addition = f"\n- [{now.strftime('%Y-%m-%d')}] {icon} **{pattern}**: {rule}\n"

    with open(master_path, "r") as f:
        content = f.read()

    if outcome == "LOSS" and "## 🚫 Known Failure Patterns" in content:
        content = content.replace(
            "## 🚫 Known Failure Patterns",
            f"## 🚫 Known Failure Patterns{addition}"
        )
    elif outcome == "WIN" and "## ✅ Known Success Patterns" in content:
        content = content.replace(
            "## ✅ Known Success Patterns",
            f"## ✅ Known Success Patterns{addition}"
        )
    else:
        content += f"\n## Auto-Learned Rules\n{addition}"

    with open(master_path, "w") as f:
        f.write(content)

    # Sync master rules to Google Drive
    _sync_file_to_gdrive(master_path)
    log.info(f"📝 Master rules updated: {pattern}")


def _update_confidence_model(analysis, outcome, now):
    """
    Maintain a running confidence model JSON file.
    This is the bot's internal scoring weights — updated after every trade.
    Over time this becomes a genuine probability model.
    """
    model_path = "trading-brain/Bot_Rules/confidence_model.json"

    # Load existing model
    if os.path.exists(model_path):
        with open(model_path) as f:
            model = json.load(f)
    else:
        model = {
            "total_trades": 0,
            "wins": 0,
            "losses": 0,
            "patterns": {},
            "condition_weights": {
                "rsi_overbought_penalty": -15,
                "rsi_oversold_penalty": -10,
                "high_volume_bonus": +8,
                "low_volume_penalty": -12,
                "bullish_sentiment_bonus": +5,
                "bearish_sentiment_penalty": -8,
                "morning_session_bonus": +6,
                "afternoon_penalty": -5,
                "lunch_penalty": -20
            },
            "learned_rules": [],
            "last_updated": ""
        }

    # Update model
    model["total_trades"] += 1
    if outcome == "WIN":
        model["wins"] += 1
    else:
        model["losses"] += 1

    # Add pattern to model
    pattern = analysis.get("pattern_name", "Unknown")
    if pattern not in model["patterns"]:
        model["patterns"][pattern] = {"wins": 0, "losses": 0, "occurrences": 0}
    model["patterns"][pattern]["occurrences"] += 1
    if outcome == "WIN":
        model["patterns"][pattern]["wins"] += 1
    else:
        model["patterns"][pattern]["losses"] += 1

    # Add learned rule
    rule = analysis.get("key_rule", "")
    if rule and rule not in model["learned_rules"]:
        model["learned_rules"].append(rule)

    # Update condition weights based on what caused this outcome
    cm_update = analysis.get("confidence_model_update", {})
    adjustment = cm_update.get("adjust_confidence_by", 0)
    conditions = cm_update.get("conditions_that_caused_this", [])

    model["last_updated"] = now.isoformat()

    # Save model
    with open(model_path, "w") as f:
        json.dump(model, f, indent=2)

    # Sync to Google Drive
    _sync_file_to_gdrive(model_path)

    win_rate = (model["wins"] / model["total_trades"] * 100) if model["total_trades"] > 0 else 0
    log.info(f"📊 Confidence model updated | Win rate: {win_rate:.1f}% ({model['total_trades']} trades)")


# ══════════════════════════════════════════════════════════════════════════════
#  SECTION 2: MEMORY LOADING
#  Load past memories with genuine understanding for pre-trade decisions
# ══════════════════════════════════════════════════════════════════════════════

def load_past_memories(limit=15):
    """Load recent trade memories with full causal analysis."""
    memories = {
        "failures": [],
        "successes": [],
        "failure_rules": [],
        "success_rules": [],
        "confidence_model": {},
        "win_rate": 0
    }

    # Load confidence model
    model_path = "trading-brain/Bot_Rules/confidence_model.json"
    if os.path.exists(model_path):
        with open(model_path) as f:
            model = json.load(f)
        memories["confidence_model"] = model
        total = model.get("total_trades", 0)
        wins = model.get("wins", 0)
        memories["win_rate"] = (wins / total * 100) if total > 0 else 0
        memories["failure_rules"] = model.get("learned_rules", [])[-10:]

    # Load failure files
    failure_dir = "trading-brain/Failures"
    if os.path.exists(failure_dir):
        files = sorted([
            f for f in os.listdir(failure_dir)
            if f.endswith(".md") and not f.startswith("TEMPLATE")
        ])[-limit:]
        for fname in files:
            parsed = _parse_deep_memory(f"{failure_dir}/{fname}")
            if parsed:
                memories["failures"].append(parsed)

    # Load success files
    success_dir = "trading-brain/Successes"
    if os.path.exists(success_dir):
        files = sorted([
            f for f in os.listdir(success_dir)
            if f.endswith(".md") and not f.startswith("TEMPLATE")
        ])[-limit:]
        for fname in files:
            parsed = _parse_deep_memory(f"{success_dir}/{fname}")
            if parsed:
                memories["successes"].append(parsed)
                if parsed.get("rule"):
                    memories["success_rules"].append(parsed["rule"])

    total_f = len(memories["failures"])
    total_s = len(memories["successes"])
    log.info(f"🧠 Loaded {total_f} failure memories, {total_s} success memories")
    return memories


def _parse_deep_memory(filepath):
    """Parse a deep memory markdown file into structured data."""
    try:
        with open(filepath) as f:
            content = f.read()

        result = {}

        # Extract causal analysis
        if "## Why It" in content and "---" in content:
            start_marker = "## Why It Succeeded" if "Succeeded" in content else "## Why It Failed"
            if start_marker in content:
                start = content.index(start_marker) + len(start_marker) + 1
                end = content.index("\n---", start) if "\n---" in content[start:] else start + 600
                result["causal_analysis"] = content[start:end].strip()

        # Extract rule
        if "## Rule Learned" in content:
            start = content.index("## Rule Learned") + len("## Rule Learned\n> **")
            if "**" in content[start:]:
                end = content.index("**", start)
                result["rule"] = content[start:end].strip()

        # Extract pattern name from title
        lines = content.split("\n")
        if lines and lines[0].startswith("# "):
            title = lines[0].replace("# ✅", "").replace("# ❌", "").strip()
            if "—" in title:
                result["pattern_name"] = title.split("—")[1].strip()

        return result if result else None
    except Exception:
        return None


def build_memory_context(memories):
    """
    Build a rich context string the confidence scorer uses
    to make genuinely informed decisions referencing past trades.
    """
    context_parts = []

    # Overall performance stats
    win_rate = memories.get("win_rate", 0)
    model = memories.get("confidence_model", {})
    total = model.get("total_trades", 0)

    if total > 0:
        context_parts.append(
            f"## YOUR TRADING HISTORY ({total} trades, {win_rate:.1f}% win rate)\n"
        )

    # Rules learned from past losses — MUST follow these
    failure_rules = memories.get("failure_rules", [])
    if failure_rules:
        context_parts.append("## RULES LEARNED FROM PAST LOSSES — CHECK THESE FIRST:")
        for i, rule in enumerate(failure_rules[-8:], 1):
            context_parts.append(f"{i}. {rule}")
        context_parts.append("")

    # Rules from past wins — try to replicate these
    success_rules = memories.get("success_rules", [])
    if success_rules:
        context_parts.append("## PATTERNS FROM PAST WINS — REPLICATE THESE:")
        for i, rule in enumerate(success_rules[-5:], 1):
            context_parts.append(f"{i}. {rule}")
        context_parts.append("")

    # Recent failure causal analysis
    failures = memories.get("failures", [])
    if failures:
        context_parts.append("## RECENT FAILURE ANALYSIS (understand WHY these failed):")
        for mem in failures[-4:]:
            pattern = mem.get("pattern_name", "Unknown")
            analysis = mem.get("causal_analysis", "")[:300]
            context_parts.append(f"**{pattern}**: {analysis}")
        context_parts.append("")

    # Recent success causal analysis
    successes = memories.get("successes", [])
    if successes:
        context_parts.append("## RECENT SUCCESS ANALYSIS (understand WHY these worked):")
        for mem in successes[-3:]:
            pattern = mem.get("pattern_name", "Unknown")
            analysis = mem.get("causal_analysis", "")[:300]
            context_parts.append(f"**{pattern}**: {analysis}")
        context_parts.append("")

    # Known patterns from confidence model
    patterns = model.get("patterns", {})
    if patterns:
        context_parts.append("## PATTERN WIN RATES (from your actual trading history):")
        for name, stats in list(patterns.items())[-6:]:
            total_p = stats.get("occurrences", 0)
            wins_p = stats.get("wins", 0)
            rate = (wins_p / total_p * 100) if total_p > 0 else 0
            context_parts.append(f"- {name}: {rate:.0f}% win rate ({total_p} trades)")
        context_parts.append("")

    if not context_parts:
        return "No past trade memories yet. This is one of the first trades — proceed with base strategy rules only."

    context_parts.append(
        "IMPORTANT: Reference specific past patterns and rules in your confidence reasoning. "
        "If current conditions match a failure pattern, lower confidence significantly. "
        "If conditions match a success pattern, raise confidence. Be specific."
    )

    return "\n".join(context_parts)


# ══════════════════════════════════════════════════════════════════════════════
#  SECTION 3: GOOGLE DRIVE SYNC
#  Every brain file syncs back to Google Drive automatically
# ══════════════════════════════════════════════════════════════════════════════

def _sync_file_to_gdrive(local_path):
    """
    Upload a local brain file back to Google Drive.
    This keeps your Obsidian vault updated with everything the bot learns.
    Uses the Google Drive API with the connected token.
    """
    if not GDRIVE_FOLDER_ID:
        log.info(f"📁 [No Drive sync configured] Would sync: {local_path}")
        return False

    try:
        filename = os.path.basename(local_path)
        with open(local_path, "rb") as f:
            file_content = f.read()

        # Check if file already exists in Drive
        search_url = "https://www.googleapis.com/drive/v3/files"
        headers = {"Authorization": f"Bearer {GDRIVE_API_KEY}"}

        search_resp = requests.get(search_url, headers=headers, params={
            "q": f"name='{filename}' and '{GDRIVE_FOLDER_ID}' in parents",
            "fields": "files(id, name)"
        }, timeout=10)

        existing = search_resp.json().get("files", [])

        if existing:
            # Update existing file
            file_id = existing[0]["id"]
            upload_url = f"https://www.googleapis.com/upload/drive/v3/files/{file_id}"
            resp = requests.patch(upload_url, headers={
                **headers, "Content-Type": "text/plain"
            }, data=file_content, params={"uploadType": "media"}, timeout=15)
        else:
            # Create new file
            upload_url = "https://www.googleapis.com/upload/drive/v3/files"
            metadata = json.dumps({
                "name": filename,
                "parents": [GDRIVE_FOLDER_ID]
            })
            resp = requests.post(upload_url, headers={
                **headers,
                "Content-Type": "multipart/related; boundary=boundary"
            }, data=(
                f"--boundary\r\nContent-Type: application/json\r\n\r\n{metadata}\r\n"
                f"--boundary\r\nContent-Type: text/plain\r\n\r\n"
            ).encode() + file_content + b"\r\n--boundary--",
            params={"uploadType": "multipart"}, timeout=15)

        if resp.status_code in [200, 201]:
            log.info(f"☁️  Synced to Drive: {filename}")
            return True
        else:
            log.warning(f"Drive sync warning: {resp.status_code}")
            return False

    except Exception as e:
        log.warning(f"Drive sync skipped: {e}")
        return False


def sync_all_brain_files():
    """Sync all brain files to Google Drive at startup."""
    if not GDRIVE_FOLDER_ID:
        return

    log.info("☁️  Syncing all brain files to Google Drive...")
    brain_dir = "trading-brain"
    synced = 0

    for root, dirs, files in os.walk(brain_dir):
        for fname in files:
            if fname.endswith(".md") or fname.endswith(".json"):
                filepath = os.path.join(root, fname)
                if _sync_file_to_gdrive(filepath):
                    synced += 1

    log.info(f"☁️  Synced {synced} brain files to Google Drive")
