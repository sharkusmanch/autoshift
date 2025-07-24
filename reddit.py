import requests
import feedparser
import re
import dateparser
from datetime import datetime

# Reddit RSS feed for the subreddit
RSS_URL = "https://www.reddit.com/r/Borderlandsshiftcodes/.rss"

# Regex patterns for SHiFT codes and expiration mentions
CODE_PATTERN = re.compile(r'([A-Z0-9]{5}-[A-Z0-9]{5}-[A-Z0-9]{5}-[A-Z0-9]{5}-[A-Z0-9]{5})')
DATE_PATTERN = re.compile(
    r'(?:exp(?:ires|iration)?|valid until|until)\s*[-:]*\s*([^\n<]+)',
    re.IGNORECASE
)

def fetch_rss_feed(url):
    headers = {"User-Agent": "ShiftCodeChecker/1.0"}
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    return feedparser.parse(response.text)

def parse_post(entry):
    summary = entry.get("summary", "")
    codes = CODE_PATTERN.findall(summary)
    date_match = DATE_PATTERN.search(summary)

    expiration_date = None
    if date_match:
        parsed_date = dateparser.parse(date_match.group(1), settings={"RETURN_AS_TIMEZONE_AWARE": False})
        if parsed_date:
            expiration_date = parsed_date

    return codes, expiration_date

def get_valid_codes():
    feed = fetch_rss_feed(RSS_URL)
    now = datetime.utcnow()
    valid_codes = []

    for entry in feed.entries:
        codes, exp_date = parse_post(entry)
        if codes:
            if exp_date is None or exp_date >= now:
                valid_codes.extend(codes)

    return list(set(valid_codes))  # Remove duplicates

def get_valid_codes_with_expirations():
    feed = fetch_rss_feed(RSS_URL)
    now = datetime.utcnow()
    valid_codes = []

    for entry in feed.entries:
        codes, exp_date = parse_post(entry)
        if codes:
            if exp_date is None or exp_date >= now:
                for code in codes:
                    valid_codes.append((code, exp_date))
    return valid_codes  # List of (code, expiration_date) tuples

if __name__ == "__main__":
    feed = fetch_rss_feed(RSS_URL)
    now = datetime.utcnow()
    seen_codes = set()
    for entry in feed.entries:
        codes, exp_date = parse_post(entry)
        for code in codes:
            if code in seen_codes:
                continue
            seen_codes.add(code)
            if exp_date is None or exp_date >= now:
                print(code)
