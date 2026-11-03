#!/usr/bin/env python3
"""
Daily Bhagavad Gita message - sequential version.

- Sends verses IN ORDER: Chapter 1 Verse 1, then 1:2, 1:3 ... up to 18:78,
  then starts again from 1:1.
- Progress is stored in gita_progress.txt (only moves forward after a
  successful send, so a failed day is retried the next day).
- English meaning: uses the simplest/most accurate free translation first
  (Sivananda, then Gambirananda, then Purohit as last resort).
- OPTIONAL: set GEMINI_API_KEY (free key from aistudio.google.com) and the
  English meaning is rewritten in very simple everyday English. If the key is
  missing or the call fails, the original translation is sent.

SETUP
  pip install requests

ENVIRONMENT VARIABLES
  GITA_CHANNEL        telegram, whatsapp, twilio, none (comma-separated allowed)
  TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
  WHATSAPP_PHONE, WHATSAPP_APIKEY
  TWILIO_SID, TWILIO_TOKEN, TWILIO_FROM, TWILIO_TO
  GEMINI_API_KEY      optional, for simple-English rewriting
  GEMINI_MODEL        optional, default gemini-2.0-flash
  GITA_LOG            log file (default gita_log.csv)
  GITA_PROGRESS       progress file (default gita_progress.txt)
  GITA_START          optional, e.g. "1:1" - used only if no progress file yet
"""

import csv
import datetime
import os
import re
import sys
import time

import requests

LOG_PATH = os.getenv("GITA_LOG", "gita_log.csv")
PROGRESS_PATH = os.getenv("GITA_PROGRESS", "gita_progress.txt")
CHANNEL = os.getenv("GITA_CHANNEL", "none").lower()

API_URLS = [
    "https://vedicscriptures.github.io/slok/{ch}/{sl}",
    "https://bhagavadgitaapi.in/slok/{ch}/{sl}",
]

# Number of verses in each of the 18 chapters (701 in total)
CHAPTER_VERSES = [47, 72, 43, 42, 29, 47, 30, 28, 34,
                  42, 55, 20, 35, 27, 20, 24, 28, 78]

# (field name in API, key, label) in order of preference
HINDI_SOURCES = [("tej", "ht", "स्वामी तेजोमयानन्द"),
                 ("rams", "ht", "स्वामी रामसुखदास")]
ENGLISH_SOURCES = [("siva", "et", "Swami Sivananda"),
                   ("gambir", "et", "Swami Gambirananda"),
                   ("purohit", "et", "Shri Purohit Swami")]

LOG_FIELDS = ["date", "chapter", "verse", "sanskrit", "hindi_meaning",
              "english_meaning", "hindi_by", "english_by", "channel",
              "status", "favourite"]


# ------------------------------------------------------- order / progress
def parse_pair(text):
    ch, sl = text.strip().split(":")
    ch, sl = int(ch), int(sl)
    if not (1 <= ch <= 18 and 1 <= sl <= CHAPTER_VERSES[ch - 1]):
        raise ValueError(f"invalid verse {text}")
    return ch, sl


def load_next():
    """Return (chapter, verse) to send today."""
    if os.path.exists(PROGRESS_PATH):
        try:
            with open(PROGRESS_PATH, encoding="utf-8") as f:
                return parse_pair(f.read())
        except Exception:
            pass
    try:
        return parse_pair(os.getenv("GITA_START", "1:1"))
    except Exception:
        return 1, 1


def following(ch, sl):
    """The verse that comes after (ch, sl) in the Gita."""
    if sl < CHAPTER_VERSES[ch - 1]:
        return ch, sl + 1
    if ch < 18:
        return ch + 1, 1
    return 1, 1  # finished the whole Gita - start again


def save_progress(ch, sl):
    with open(PROGRESS_PATH, "w", encoding="utf-8") as f:
        f.write(f"{ch}:{sl}\n")


def append_log(row):
    is_new = not os.path.exists(LOG_PATH)
    with open(LOG_PATH, "a", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=LOG_FIELDS, extrasaction="ignore")
        if is_new:
            w.writeheader()
        w.writerow(row)


# ------------------------------------------------------------ verse logic
class VerseNotFound(Exception):
    pass


def fetch_verse(ch, sl):
    last_err = None
    for url in API_URLS:
        for attempt in range(3):
            try:
                r = requests.get(url.format(ch=ch, sl=sl), timeout=20)
                if r.status_code == 404:
                    last_err = VerseNotFound(f"{ch}:{sl} not found")
                    break  # try the mirror
                r.raise_for_status()
                return r.json()
            except Exception as e:
                last_err = e
                time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"Could not fetch {ch}:{sl} from any API: {last_err}")


def squash(text):
    return re.sub(r"\s+", " ", text).strip()


def strip_verse_number(text):
    """Remove leading '18.66', '।।18.66।।', '1.16-18' etc. from a translation."""
    return re.sub(r"^[\s।|]*\d+\.\d+(?:\s*[-–]\s*\d+)?[\s।|]*", "", text).strip()


def first_available(data, sources):
    for name, field, label in sources:
        value = (data.get(name) or {}).get(field)
        if value and value.strip():
            cleaned = strip_verse_number(squash(value))
            if cleaned:
                return cleaned, label
    raise ValueError("No translation available")


def simplify_english(text):
    """Optional: rewrite in very simple English using the free Gemini API."""
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        return text
    model = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
    prompt = (
        "Rewrite this Bhagavad Gita translation in very simple, everyday "
        "English that a school student can understand. Keep the exact meaning. "
        "Do not add ideas, examples or commentary. Use short sentences. "
        "No old words like thee, thou, shalt. Reply with only the rewritten "
        "text.\n\n" + text
    )
    try:
        r = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            params={"key": key},
            json={"contents": [{"parts": [{"text": prompt}]}]},
            timeout=40)
        r.raise_for_status()
        out = r.json()["candidates"][0]["content"]["parts"][0]["text"]
        out = squash(out)
        return out if out else text
    except Exception as e:
        print(f"Simplify step skipped: {e}", file=sys.stderr)
        return text


def build_message(ch, sl, data):
    sanskrit = "\n".join(line.strip() for line in data["slok"].splitlines()
                         if line.strip())
    hindi, hindi_by = first_available(data, HINDI_SOURCES)
    english, english_by = first_available(data, ENGLISH_SOURCES)
    english = simplify_english(english)

    text = (
        "🌅 शुभ प्रभात!\n"
        f"📖 गीता अध्याय {ch}, श्लोक {sl}\n\n"
        f"{sanskrit}\n\n"
        f"🇮🇳 अर्थ: {hindi}\n\n"
        f"🇬🇧 Meaning: {english}\n\n"
        f"— {hindi_by} | {english_by}"
    )
    return text, sanskrit, hindi, english, hindi_by, english_by


# ---------------------------------------------------------------- sending
def send_telegram(text):
    token, chat_id = os.environ["TELEGRAM_BOT_TOKEN"], os.environ["TELEGRAM_CHAT_ID"]
    r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                      json={"chat_id": chat_id, "text": text}, timeout=30)
    r.raise_for_status()


def send_whatsapp(text):
    r = requests.get(
        "https://api.callmebot.com/whatsapp.php",
        params={"phone": os.environ["WHATSAPP_PHONE"],
                "text": text,
                "apikey": os.environ["WHATSAPP_APIKEY"]},
        timeout=60)
    r.raise_for_status()
    if "error" in r.text.lower():
        raise RuntimeError(r.text[:200])


def send_twilio(text):
    sid, token = os.environ["TWILIO_SID"], os.environ["TWILIO_TOKEN"]
    r = requests.post(
        f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json",
        data={"From": os.environ["TWILIO_FROM"],
              "To": os.environ["TWILIO_TO"],
              "Body": text},
        auth=(sid, token), timeout=30)
    r.raise_for_status()


# ------------------------------------------------------------------- main
def main():
    today = datetime.date.today().isoformat()
    ch, sl = load_next()

    # If a verse doesn't exist in the API, skip to the next one (max 3 tries)
    for _ in range(3):
        try:
            data = fetch_verse(ch, sl)
            break
        except RuntimeError as e:
            if "not found" in str(e) and CHANNEL != "none":
                print(f"Skipping {ch}:{sl}: {e}", file=sys.stderr)
                ch, sl = following(ch, sl)
                continue
            raise
    else:
        raise RuntimeError("Too many missing verses in a row")

    text, sanskrit, hindi, english, hindi_by, english_by = build_message(ch, sl, data)

    channels = [c.strip() for c in CHANNEL.split(",") if c.strip()]
    if not channels or channels == ["none"]:
        print("---- DRY RUN (GITA_CHANNEL=none, nothing sent, progress not moved) ----")
        print(text)
        return

    senders = {"telegram": send_telegram, "whatsapp": send_whatsapp,
               "twilio": send_twilio}
    ok, errors = [], []
    for name in channels:
        try:
            if name not in senders:
                raise ValueError("unknown channel")
            senders[name](text)
            ok.append(name)
        except Exception as e:
            errors.append(f"{name}: {e}")
            print(f"Send failed ({name}): {e}", file=sys.stderr)

    if ok:
        status = "sent" + (f" (failed: {'; '.join(errors)})" if errors else "")
        # Move forward only after a successful send
        save_progress(*following(ch, sl))
    else:
        status = f"failed: {'; '.join(errors)}"

    append_log({
        "date": today, "chapter": ch, "verse": sl, "sanskrit": sanskrit,
        "hindi_meaning": hindi, "english_meaning": english,
        "hindi_by": hindi_by, "english_by": english_by,
        "channel": CHANNEL, "status": status, "favourite": "",
    })
    print(f"{today}  {ch}:{sl}  [{status}]")
    if status.startswith("failed"):
        sys.exit(1)


if __name__ == "__main__":
    main()
