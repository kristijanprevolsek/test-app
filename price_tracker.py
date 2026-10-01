"""Prati cijene proizvoda na webshopovima i šalje obavijest kad cijena padne ispod praga."""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
from pathlib import Path

import requests
import yaml
from bs4 import BeautifulSoup

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)

PRICE_RE = re.compile(r"\d[\d.,\s ]*")


def parse_price(text: str | float | int | None) -> float | None:
    """Pretvara tekst poput '19,99 €', '1.299,00 kn' ili '1,299.00' u float."""
    if text is None:
        return None
    if isinstance(text, (int, float)):
        return float(text)
    match = PRICE_RE.search(str(text))
    if not match:
        return None
    raw = re.sub(r"[\s ]", "", match.group()).rstrip(".,")
    if "," in raw and "." in raw:
        # Zadnji separator je decimalni, ostali su tisućice.
        if raw.rfind(",") > raw.rfind("."):
            raw = raw.replace(".", "").replace(",", ".")
        else:
            raw = raw.replace(",", "")
    elif "," in raw:
        whole, _, frac = raw.rpartition(",")
        raw = f"{whole.replace(',', '')}.{frac}" if len(frac) != 3 else raw.replace(",", "")
    elif raw.count(".") > 1 or (raw.count(".") == 1 and len(raw.rpartition(".")[2]) == 3):
        raw = raw.replace(".", "")
    try:
        return float(raw)
    except ValueError:
        return None


def _prices_from_jsonld(node) -> list:
    """Rekurzivno traži schema.org Offer cijene u JSON-LD strukturi."""
    found = []
    if isinstance(node, list):
        for item in node:
            found += _prices_from_jsonld(item)
    elif isinstance(node, dict):
        for key in ("price", "lowPrice"):
            if key in node and not isinstance(node[key], (dict, list)):
                found.append(node[key])
        for key in ("offers", "@graph", "priceSpecification"):
            if key in node:
                found += _prices_from_jsonld(node[key])
    return found


def extract_price(html: str, selector: str | None = None) -> float | None:
    soup = BeautifulSoup(html, "html.parser")

    if selector:
        el = soup.select_one(selector)
        if el is None:
            return None
        return parse_price(el.get("content") or el.get_text(" ", strip=True))

    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
        except (json.JSONDecodeError, TypeError):
            continue
        for candidate in _prices_from_jsonld(data):
            # schema.org propisuje točku kao decimalni separator.
            try:
                price = float(candidate)
            except (TypeError, ValueError):
                price = parse_price(candidate)
            if price is not None:
                return price

    for attrs in (
        {"property": "product:price:amount"},
        {"property": "og:price:amount"},
        {"itemprop": "price"},
    ):
        el = soup.find(attrs=attrs)
        if el is not None:
            price = parse_price(el.get("content") or el.get_text(" ", strip=True))
            if price is not None:
                return price
    return None


def find_promo(html: str, keywords: list[str]) -> str | None:
    """Vraća isječak vidljivog teksta oko prve pronađene ključne riječi (npr. '2+1')."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    text = " ".join(soup.get_text(" ").split())
    for keyword in keywords:
        # '2+1 gratis' pronalazi i '2 + 1 GRATIS'.
        pattern = r"\s*".join(re.escape(ch) for ch in keyword if not ch.isspace())
        match = re.search(rf"(?<!\d){pattern}(?!\d)", text, re.IGNORECASE)
        if match:
            start, end = max(match.start() - 40, 0), match.end() + 40
            return text[start:end].strip()
    return None


def fetch_html(url: str) -> str:
    resp = requests.get(
        url,
        headers={"User-Agent": USER_AGENT, "Accept-Language": "hr,en;q=0.8"},
        timeout=20,
    )
    resp.raise_for_status()
    return resp.text


def send_notification(notify_cfg: dict, title: str, message: str, url: str) -> None:
    topic = os.environ.get("NTFY_TOPIC") or notify_cfg.get("ntfy_topic")
    if not topic:
        print(f"[obavijest] {title}: {message}")
        return
    server = notify_cfg.get("ntfy_server", "https://ntfy.sh").rstrip("/")
    requests.post(
        f"{server}/{topic}",
        data=message.encode("utf-8"),
        headers={
            # HTTP zaglavlja moraju biti latin-1; ntfy podržava RFC 2047 za UTF-8.
            "Title": f"=?UTF-8?B?{base64.b64encode(title.encode()).decode()}?=",
            "Click": url,
            "Tags": "moneybag",
        },
        timeout=15,
    ).raise_for_status()


def load_state(path: Path) -> dict:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def run(config_path: Path, state_path: Path) -> int:
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    default_threshold = float(config.get("threshold", 20.0))
    default_promo = config.get("promo") or []
    notify_cfg = config.get("notify") or {}
    state = load_state(state_path)
    errors = 0

    for product in config.get("products", []):
        name, url = product.get("name", product["url"]), product["url"]
        threshold = float(product.get("threshold", default_threshold))
        promo_keywords = product.get("promo", default_promo)
        prev = state.get(url, {})
        try:
            html = fetch_html(url)
        except requests.RequestException as exc:
            print(f"GREŠKA  {name}: {exc}")
            errors += 1
            continue

        price = extract_price(html, product.get("selector"))
        if price is None:
            print(f"GREŠKA  {name}: cijena nije pronađena (probaj dodati 'selector')")
            errors += 1
            below = prev.get("below", False)
        else:
            below = price < threshold
            print(f"{'ISPOD ' if below else 'OK    '} {name}: {price:.2f} € (prag {threshold:.2f} €)")
            # Obavijest samo kad cijena prvi put padne ispod praga, ne pri svakom pokretanju.
            if below and not prev.get("below", False):
                send_notification(
                    notify_cfg,
                    f"Pad cijene: {name}",
                    f"Nova cijena {price:.2f} € (ispod {threshold:.2f} €)",
                    url,
                )

        promo = find_promo(html, promo_keywords) if promo_keywords else None
        if promo_keywords:
            print(f"{'AKCIJA ' if promo else 'BEZ AKCIJE'} {name}" + (f': "…{promo}…"' if promo else ""))
        # Kao i za cijenu: obavijest kad se akcija pojavi, ne pri svakom pokretanju.
        if promo and not prev.get("promo", False):
            price_text = f" Cijena {price:.2f} €." if price is not None else ""
            send_notification(notify_cfg, f"Akcija: {name}", f"Na stranici: \"{promo}\".{price_text}", url)

        state[url] = {"price": price if price is not None else prev.get("price"), "below": below, "promo": bool(promo)}

    state_path.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return 1 if errors and errors == len(config.get("products", [])) else 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="config.yaml", type=Path)
    parser.add_argument("--state", default="state.json", type=Path)
    args = parser.parse_args()
    sys.exit(run(args.config, args.state))


if __name__ == "__main__":
    main()
