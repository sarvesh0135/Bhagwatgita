#!/usr/bin/env python3
"""
Daily Bhagavad Gita message - 100% FREE version (no AI, no paid API).

Verses and Hindi/English meanings come from the free public Bhagavad Gita API
(vedicscriptures). The script picks a well-known verse you haven't received yet,
sends it to Telegram, and logs it to gita_log.csv.

SETUP
  pip install requests

ENVIRONMENT VARIABLES
  GITA_CHANNEL        one or more of: telegram, whatsapp, twilio, none
                      separate with commas to send to several, e.g. "telegram,whatsapp"
                      (default: none = dry run, prints only)

  # telegram (free)
  TELEGRAM_BOT_TOKEN  from @BotFather
  TELEGRAM_CHAT_ID    your numeric chat id (from @userinfobot)

  # whatsapp (free, via the CallMeBot service, sends to YOUR own number)
  WHATSAPP_PHONE      your number in international format, e.g. +919876543210
  WHATSAPP_APIKEY     key you receive from CallMeBot (see callmebot.com)

  # if GITA_CHANNEL=twilio (paid, optional)
  TWILIO_SID, TWILIO_TOKEN, TWILIO_FROM, TWILIO_TO

  # optional
  GITA_LOG            path of the log file (default: gita_log.csv)
"""

import csv
import datetime
import os
import random
import re
import sys
import time

import requests

LOG_PATH = os.getenv("GITA_LOG", "gita_log.csv")
CHANNEL = os.getenv("GITA_CHANNEL", "none").lower()

# Main API first, mirror second
API_URLS = [
    "https://vedicscriptures.github.io/slok/{ch}/{sl}",
    "https://bhagavadgitaapi.in/slok/{ch}/{sl}",
]

# (field name in API, translator label) in order of preference
HINDI_SOURCES = [("tej", "ht", "स्वामी तेजोमयानन्द"),
                 ("rams", "ht", "स्वामी रामसुखदास")]
ENGLISH_SOURCES = [("purohit", "et", "Shri Purohit Swami"),
                   ("siva", "et", "Swami Sivananda"),
                   ("gambir", "et", "Swami Gambirananda")]

# Well-known, uplifting verses (chapter, verse) in mixed-theme order.
FAMOUS = [
    (2, 47), (6, 5), (2, 14), (12, 13), (18, 66), (3, 21), (2, 62), (4, 7),
    (2, 20), (6, 35), (18, 46), (2, 48), (9, 22), (3, 19), (2, 70), (4, 18),
    (12, 15), (6, 17), (2, 22), (18, 58), (5, 18), (4, 39), (2, 38), (6, 6),
    (9, 26), (3, 27), (2, 56), (18, 63), (4, 8), (12, 14), (2, 13), (6, 26),
    (18, 61), (3, 35), (2, 63), (5, 10), (2, 27), (9, 27), (6, 47), (4, 38),
    (2, 71), (18, 78), (12, 18), (2, 50), (6, 30), (7, 14), (2, 66), (5, 29),
    (3, 30), (9, 34), (10, 20), (2, 40), (2, 16), (6, 40), (18, 47), (2, 23),
    (12, 8), (15, 15), (4, 34), (2, 17), (3, 16), (6, 7), (2, 55), (6, 10),
    (13, 28), (2, 31), (6, 16), (4, 36), (5, 21), (2, 58), (3, 8), (2, 69),
    (6, 32), (4, 24), (2, 37), (5, 20), (6, 8), (9, 29), (2, 64), (6, 19),
    (4, 11), (7, 7), (8, 7), (18, 65),
]

LOG_FIELDS = ["date", "chapter", "verse", "sanskrit", "hindi_meaning",
              "english_meaning", "hindi_by", "english_by", "channel",
              "status", "favourite"]


# ---------------------------------------------------------------- logging
def load_sent():
    """Return list of 'chapter:verse' that were successfully sent (oldest first)."""
    if not os.path.exists(LOG_PATH):
        return []
    sent = []
    with open(LOG_PATH, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            if row.get("status", "").startswith("sent"):
                sent.append(f"{row['chapter']}:{row['verse']}")
    return sent


def append_log(row):
    is_new = not os.path.exists(LOG_PATH)
    with open(LOG_PATH, "a", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=LOG_FIELDS, extrasaction="ignore")
        if is_new:
            w.writeheader()
        w.writerow(row)


# ------------------------------------------------------------ verse logic
def pick_verse(today, sent):
    unsent = [v for v in FAMOUS if f"{v[0]}:{v[1]}" not in sent]
    if unsent:
        return random.Random(today).choice(unsent)
    # Everything sent once: start a new cycle with the verse sent longest ago
    last_index = {}
    for i, key in enumerate(sent):
        last_index[key] = i
    return min(FAMOUS, key=lambda v: last_index.get(f"{v[0]}:{v[1]}", -1))


def fetch_verse(ch, sl):
    last_err = None
    for url in API_URLS:
        for attempt in range(3):
            try:
                r = requests.get(url.format(ch=ch, sl=sl), timeout=20)
                r.raise_for_status()
                return r.json()
            except Exception as e:
                last_err = e
                time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"Could not fetch {ch}:{sl} from any API: {last_err}")


def squash(text):
    return re.sub(r"\s+", " ", text).strip()


def first_available(data, sources):
    for name, field, label in sources:
        value = (data.get(name) or {}).get(field)
        if value and value.strip():
            return squash(value), label
    raise ValueError("No translation available")


def build_message(ch, sl, data):
    sanskrit = "\n".join(line.strip() for line in data["slok"].splitlines() if line.strip())
    hindi, hindi_by = first_available(data, HINDI_SOURCES)
    english, english_by = first_available(data, ENGLISH_SOURCES)

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
    """Free WhatsApp message to your own number via CallMeBot."""
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
    sent = load_sent()

    ch, sl = pick_verse(today, sent)
    data = fetch_verse(ch, sl)
    text, sanskrit, hindi, english, hindi_by, english_by = build_message(ch, sl, data)

    channels = [c.strip() for c in CHANNEL.split(",") if c.strip()]
    if not channels or channels == ["none"]:
        print("---- DRY RUN (GITA_CHANNEL=none, nothing sent or logged) ----")
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
