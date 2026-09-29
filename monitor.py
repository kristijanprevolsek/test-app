"""Prati cijene proizvoda na webshopovima i javlja na Telegram kad su na akciji.

Za svaki proizvod iz config.json skine stranicu, izvuče cijenu (schema.org
JSON-LD, meta tagovi ili itemprop="price") i pošalje poruku kad:
  * cijena padne u odnosu na prošlu provjeru, ili
  * cijena bude jednaka ili ispod zadane "target_price".

Zadnje viđene cijene čuvaju se u state.json da ne dobivaš istu poruku svaki put.
Koristi samo standardnu Python biblioteku.
"""

import argparse
import html
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
CONFIG_FILE = BASE_DIR / "config.json"
STATE_FILE = BASE_DIR / "state.json"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


# --- Dohvat i parsiranje -----------------------------------------------------

def fetch(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept-Language": "hr-HR,hr;q=0.9,en;q=0.8",
    })
    with urllib.request.urlopen(req, timeout=30) as resp:
        charset = resp.headers.get_content_charset() or "utf-8"
        return resp.read().decode(charset, errors="replace")


def parse_price(value):
    """'12,99 €' / '1.299,00' / 12.99 -> 12.99"""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = re.sub(r"[^\d,.]", "", str(value))
    if not s:
        return None
    if "," in s and "." in s:
        # Zadnji separator je decimalni.
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def _walk_jsonld(node):
    """Vraća sve dict čvorove iz JSON-LD strukture (uključujući @graph)."""
    if isinstance(node, list):
        for item in node:
            yield from _walk_jsonld(item)
    elif isinstance(node, dict):
        yield node
        for key in ("@graph", "offers", "mainEntity"):
            if key in node:
                yield from _walk_jsonld(node[key])


def _price_from_offer(offer):
    for key in ("price", "lowPrice"):
        if key in offer:
            price = parse_price(offer[key])
            if price is not None:
                return price
    spec = offer.get("priceSpecification")
    if isinstance(spec, list):
        spec = spec[0] if spec else None
    if isinstance(spec, dict):
        return parse_price(spec.get("price"))
    return None


def price_from_jsonld(page):
    blocks = re.findall(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        page, re.S | re.I)
    for block in blocks:
        try:
            data = json.loads(html.unescape(block.strip()))
        except json.JSONDecodeError:
            continue
        for node in _walk_jsonld(data):
            types = node.get("@type")
            types = types if isinstance(types, list) else [types]
            if any(t in ("Offer", "AggregateOffer") for t in types):
                price = _price_from_offer(node)
                if price is not None:
                    return price
    return None


def price_from_meta(page):
    patterns = [
        r'<meta[^>]+(?:property|name)=["\'](?:product|og):price:amount["\'][^>]+content=["\']([^"\']+)',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:property|name)=["\'](?:product|og):price:amount',
        r'itemprop=["\']price["\'][^>]+content=["\']([^"\']+)',
        r'content=["\']([^"\']+)["\'][^>]+itemprop=["\']price["\']',
    ]
    for pattern in patterns:
        m = re.search(pattern, page, re.I)
        if m:
            price = parse_price(m.group(1))
            if price is not None:
                return price
    return None


def price_from_regex(page, pattern):
    m = re.search(pattern, page, re.S)
    return parse_price(m.group(1)) if m else None


def extract_price(page, product):
    """Ako proizvod ima vlastiti "price_regex", koristi njega, inače automatiku."""
    if product.get("price_regex"):
        return price_from_regex(page, product["price_regex"])
    return price_from_jsonld(page) or price_from_meta(page)


# --- Odluka o obavijesti ----------------------------------------------------

def check_product(product, price, state):
    """Vraća tekst obavijesti (ili None) i ažurira state za taj proizvod."""
    entry = state.setdefault(product["url"], {})
    last_price = entry.get("price")
    target = product.get("target_price")
    reasons = []

    if last_price is not None and price < last_price:
        reasons.append(f"pojeftinilo s {last_price:.2f} € na {price:.2f} €")

    if target is not None:
        if price <= target:
            if entry.get("notified_price") != price:
                reasons.append(f"cijena {price:.2f} € je ispod tvoje granice {target:.2f} €")
        else:
            entry.pop("notified_price", None)

    entry["price"] = price
    if not reasons:
        return None
    entry["notified_price"] = price
    return (
        f"🍼 <b>{html.escape(product['name'])}</b>\n"
        f"{html.escape(product.get('shop', ''))}\n"
        + "\n".join(f"• {r}" for r in reasons)
        + f"\n\n<a href=\"{html.escape(product['url'])}\">Otvori proizvod</a>"
    )


# --- Telegram ---------------------------------------------------------------

def send_telegram(text):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("[telegram] TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID nisu postavljeni, poruka:\n" + text)
        return
    data = urllib.parse.urlencode({
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": "true",
    }).encode()
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    with urllib.request.urlopen(url, data=data, timeout=30) as resp:
        resp.read()


# --- Main -------------------------------------------------------------------

def load_json(path, default):
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return default


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--test-telegram", action="store_true",
                        help="samo pošalji probnu poruku na Telegram")
    args = parser.parse_args()

    if args.test_telegram:
        send_telegram("✅ Pampers monitor radi i može ti slati poruke.")
        return 0

    products = load_json(CONFIG_FILE, {"products": []})["products"]
    state = load_json(STATE_FILE, {})
    errors = 0

    for product in products:
        try:
            price = extract_price(fetch(product["url"]), product)
        except Exception as exc:  # jedan pokvaren shop ne smije srušiti ostale
            print(f"[greška] {product['name']}: {exc}")
            errors += 1
            continue
        if price is None:
            print(f"[greška] {product['name']}: cijena nije pronađena na stranici")
            errors += 1
            continue

        print(f"{product['name']}: {price:.2f} €")
        message = check_product(product, price, state)
        if message:
            send_telegram(message)

    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n",
                          encoding="utf-8")
    # Ako nijedan proizvod nije uspio, vrati grešku da se vidi u GitHub Actions.
    return 1 if products and errors == len(products) else 0


if __name__ == "__main__":
    sys.exit(main())
