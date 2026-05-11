"""
====================================================
  TRADING BRAIN — BOOK READER
  Drop any trading book PDF into Google Drive and
  this tool reads it, extracts all strategies,
  and loads them into your Trading Brain
====================================================
"""

import os
import json
import logging
import requests
import base64
from datetime import datetime
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger("BookReader")

CLAUDE_API_KEY = os.environ.get("CLAUDE_API_KEY", "")
BOOKS_FOLDER   = "trading-brain/Books"
STRATEGY_FOLDER = "trading-brain/Strategies"
NOTES_FOLDER   = "trading-brain/Book_Notes"

os.makedirs(BOOKS_FOLDER, exist_ok=True)
os.makedirs(STRATEGY_FOLDER, exist_ok=True)
os.makedirs(NOTES_FOLDER, exist_ok=True)


def read_pdf_as_base64(filepath):
    """Convert PDF to base64 for Claude to read."""
    with open(filepath, "rb") as f:
        return base64.standard_b64encode(f.read()).decode("utf-8")


def extract_strategies_from_book(pdf_path, book_title):
    """
    Send the book to Claude and extract all trading strategies,
    rules, tips, and insights into structured brain files.
    """
    log.info(f"📖 Reading: {book_title}")
    log.info("    Sending to Claude for analysis...")

    pdf_data = read_pdf_as_base64(pdf_path)

    prompt = """You are reading a trading book on behalf of a futures day trader.
Your job is to extract EVERYTHING useful from this book and organize it
into structured trading knowledge.

Extract and return ONLY a JSON object with this structure:

{
  "book_summary": "3-4 sentence overview of what this book teaches",
  "key_principles": ["list of the most important trading principles from the book"],
  "strategies": [
    {
      "name": "Strategy Name",
      "description": "What this strategy is and when to use it",
      "entry_conditions": ["condition 1", "condition 2"],
      "exit_conditions": ["when to exit", "stop loss rule"],
      "best_market_conditions": "when this works best",
      "avoid_when": "when NOT to use this",
      "instruments": "what markets this works on",
      "timeframe": "daily/intraday/5min etc"
    }
  ],
  "risk_management_rules": ["rule 1", "rule 2"],
  "failure_patterns": ["common mistakes the book warns against"],
  "success_patterns": ["conditions the book says lead to winning trades"],
  "psychology_tips": ["mental/emotional tips from the book"],
  "key_indicators": ["technical indicators the book recommends"],
  "quotes": ["2-3 most important quotes from the book"]
}

Be thorough — extract every strategy and rule you can find.
Return ONLY the JSON, no other text."""

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
                "max_tokens": 4000,
                "messages": [{
                    "role": "user",
                    "content": [
                        {
                            "type": "document",
                            "source": {
                                "type": "base64",
                                "media_type": "application/pdf",
                                "data": pdf_data
                            }
                        },
                        {
                            "type": "text",
                            "text": prompt
                        }
                    ]
                }]
            },
            timeout=120
        )

        content = resp.json()["content"][0]["text"]
        clean = content.replace("```json", "").replace("```", "").strip()
        data = json.loads(clean)
        log.info(f"✅ Extracted {len(data.get('strategies', []))} strategies from {book_title}")
        return data

    except Exception as e:
        log.error(f"❌ Failed to read book: {e}")
        return None


def save_strategy_to_brain(strategy, book_title, index):
    """Save an extracted strategy as a proper brain file."""
    safe_name = strategy['name'].replace(' ', '_').replace('/', '-')
    filename = f"{STRATEGY_FOLDER}/{safe_name}.md"

    content = f"""# 📈 Strategy: {strategy['name']}
*Source: {book_title}*
*Added to brain: {datetime.now().strftime('%Y-%m-%d')}*

---

## What Is It?
{strategy.get('description', 'No description provided')}

---

## Entry Conditions (ALL must be true)
{chr(10).join(f"- [ ] {c}" for c in strategy.get('entry_conditions', []))}

---

## Exit Conditions
{chr(10).join(f"- {c}" for c in strategy.get('exit_conditions', []))}

---

## Best Market Conditions
{strategy.get('best_market_conditions', 'Not specified')}

---

## When to AVOID This Strategy
{strategy.get('avoid_when', 'Not specified')}

---

## Instruments
{strategy.get('instruments', 'Not specified')}

---

## Timeframe
{strategy.get('timeframe', 'Not specified')}

---

## Failure Notes
*Auto-updated by bot after losses using this strategy*

---

## Success Notes
*Auto-updated by bot after wins using this strategy*

---

## Tags
`#strategy` `#book-sourced` `#{book_title.lower().replace(' ', '-')[:30]}`
"""

    with open(filename, "w") as f:
        f.write(content)

    log.info(f"   ✅ Saved strategy: {strategy['name']}")
    return filename


def save_book_notes(data, book_title):
    """Save full book notes and insights to the brain."""
    safe_title = book_title.replace(' ', '_').replace('/', '-')
    filename = f"{NOTES_FOLDER}/{safe_title}_notes.md"

    # Format key sections
    principles = "\n".join(f"- {p}" for p in data.get('key_principles', []))
    risk_rules  = "\n".join(f"- {r}" for r in data.get('risk_management_rules', []))
    failures    = "\n".join(f"- {f}" for f in data.get('failure_patterns', []))
    successes   = "\n".join(f"- {s}" for s in data.get('success_patterns', []))
    psych       = "\n".join(f"- {p}" for p in data.get('psychology_tips', []))
    indicators  = "\n".join(f"- {i}" for i in data.get('key_indicators', []))
    quotes      = "\n\n".join(f'> "{q}"' for q in data.get('quotes', []))
    strategies  = "\n".join(f"- {s['name']}" for s in data.get('strategies', []))

    content = f"""# 📚 Book Notes: {book_title}
*Read and processed by Trading Brain AI*
*Date added: {datetime.now().strftime('%Y-%m-%d')}*

---

## Book Summary
{data.get('book_summary', 'No summary available')}

---

## Key Principles
{principles}

---

## Strategies Extracted ({len(data.get('strategies', []))})
{strategies}
*(Each saved as individual strategy file in Strategies/ folder)*

---

## Risk Management Rules
{risk_rules}

---

## Common Failure Patterns (What the Book Warns Against)
{failures}

---

## Success Patterns (What the Book Says Works)
{successes}

---

## Trading Psychology Tips
{psych}

---

## Key Technical Indicators Mentioned
{indicators}

---

## Notable Quotes
{quotes}

---

## How the Bot Uses This Book
Every strategy extracted above is now a file in the Strategies/ folder.
Before every trade, the bot reads ALL strategy files including these.
The failure patterns above are added to the confidence scoring engine.
The success patterns boost confidence scores when conditions match.

*This book is now part of the Trading Brain forever.*
"""

    with open(filename, "w") as f:
        f.write(content)

    log.info(f"📝 Book notes saved: {filename}")
    return filename


def update_master_rules_with_book(data, book_title):
    """Add the book's risk rules to master_rules.md."""
    master_rules_path = "trading-brain/Bot_Rules/master_rules.md"

    if not os.path.exists(master_rules_path):
        return

    with open(master_rules_path, "r") as f:
        existing = f.read()

    # Add book's failure patterns to known failure patterns section
    new_failures = "\n".join(
        f"- [{book_title[:20]}] {f}"
        for f in data.get('failure_patterns', [])[:5]
    )
    new_successes = "\n".join(
        f"- [{book_title[:20]}] {s}"
        for s in data.get('success_patterns', [])[:5]
    )

    addition = f"""
## 📚 From: {book_title}
*Auto-extracted {datetime.now().strftime('%Y-%m-%d')}*

### Additional Failure Patterns
{new_failures}

### Additional Success Patterns
{new_successes}
"""

    with open(master_rules_path, "a") as f:
        f.write(addition)

    log.info(f"✅ Master rules updated with insights from {book_title}")


def process_book(pdf_path, book_title=None):
    """
    Main function — process a trading book PDF completely.
    Extracts strategies, saves to brain, updates rules.
    """
    if not book_title:
        book_title = Path(pdf_path).stem.replace('_', ' ').replace('-', ' ').title()

    log.info("=" * 60)
    log.info(f"📚 PROCESSING BOOK: {book_title}")
    log.info("=" * 60)

    # Step 1: Extract everything from the book
    data = extract_strategies_from_book(pdf_path, book_title)
    if not data:
        log.error("Failed to process book")
        return False

    # Step 2: Save each strategy as its own brain file
    strategy_files = []
    for i, strategy in enumerate(data.get('strategies', [])):
        filepath = save_strategy_to_brain(strategy, book_title, i)
        strategy_files.append(filepath)

    # Step 3: Save full book notes
    notes_file = save_book_notes(data, book_title)

    # Step 4: Update master rules with key insights
    update_master_rules_with_book(data, book_title)

    # Step 5: Summary
    log.info("=" * 60)
    log.info(f"✅ BOOK PROCESSING COMPLETE: {book_title}")
    log.info(f"   Strategies extracted: {len(strategy_files)}")
    log.info(f"   Key principles: {len(data.get('key_principles', []))}")
    log.info(f"   Risk rules added: {len(data.get('risk_management_rules', []))}")
    log.info(f"   Notes saved to: {notes_file}")
    log.info(f"   Brain is now smarter. All bots updated.")
    log.info("=" * 60)

    return True


def scan_for_new_books():
    """
    Scan the Books folder for any PDFs that haven't been
    processed yet. Run this to batch process multiple books.
    """
    books_dir = "trading-brain/Books"
    processed_dir = "trading-brain/Books/processed"
    os.makedirs(processed_dir, exist_ok=True)

    pdf_files = list(Path(books_dir).glob("*.pdf"))

    if not pdf_files:
        log.info("No new books found in trading-brain/Books/")
        log.info("Drop a trading book PDF there to process it!")
        return

    log.info(f"Found {len(pdf_files)} book(s) to process")

    for pdf_path in pdf_files:
        success = process_book(str(pdf_path))
        if success:
            # Move to processed folder so we don't re-read it
            processed_path = f"{processed_dir}/{pdf_path.name}"
            pdf_path.rename(processed_path)
            log.info(f"📁 Moved to processed: {pdf_path.name}")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        # Process a specific book: python book_reader.py "mybook.pdf" "Book Title"
        pdf_file = sys.argv[1]
        title = sys.argv[2] if len(sys.argv) > 2 else None
        process_book(pdf_file, title)
    else:
        # Scan for any new books in the Books folder
        scan_for_new_books()
