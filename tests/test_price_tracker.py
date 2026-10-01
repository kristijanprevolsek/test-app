import json
from unittest import mock

import pytest

import price_tracker as pt


@pytest.mark.parametrize(
    "text, expected",
    [
        ("19,99 €", 19.99),
        ("1.299,00 €", 1299.0),
        ("€1,299.00", 1299.0),
        ("Cijena: 25 EUR", 25.0),
        ("20.000", 20000.0),
        ("12.5", 12.5),
        (18, 18.0),
        ("nema", None),
        (None, None),
    ],
)
def test_parse_price(text, expected):
    assert pt.parse_price(text) == expected


def test_extract_from_jsonld():
    html = """<script type="application/ld+json">
    {"@context":"https://schema.org","@type":"Product","name":"X",
     "offers":{"@type":"Offer","price":"17.49","priceCurrency":"EUR"}}</script>"""
    assert pt.extract_price(html) == 17.49


def test_extract_from_jsonld_graph():
    html = """<script type="application/ld+json">
    {"@graph":[{"@type":"WebPage"},{"@type":"Product","offers":[{"price":22}]}]}</script>"""
    assert pt.extract_price(html) == 22.0


def test_extract_from_meta():
    html = '<meta property="product:price:amount" content="19.90">'
    assert pt.extract_price(html) == 19.9


def test_extract_with_selector():
    html = '<div class="price"><span class="amount">14,99&nbsp;€</span></div>'
    assert pt.extract_price(html, ".price .amount") == 14.99
    assert pt.extract_price(html, ".missing") is None


def page(price, promo=""):
    return f'<meta property="product:price:amount" content="{price}"><p>{promo}</p>'


@pytest.mark.parametrize(
    "text",
    ["Akcija 2+1 gratis", "AKCIJA 2 + 1 GRATIS", "2+1"],
)
def test_find_promo_matches(text):
    assert pt.find_promo(page(10, text), ["2+1"]) is not None


@pytest.mark.parametrize(
    "html",
    [
        page(10, "Pakiranje 12+1 kom"),
        page(10, "Pakiranje 2+10 kom"),
        page(10) + '<script>var promo = "2+1";</script>',
        page(10, "Bez akcije"),
    ],
)
def test_find_promo_ignores(html):
    assert pt.find_promo(html, ["2+1"]) is None


def test_find_promo_returns_context():
    snippet = pt.find_promo(page(10, "Samo ovaj tjedan: akcija 2+1 gratis na pelene"), ["2+1 gratis"])
    assert "akcija 2+1 gratis na pelene" in snippet


def write_config(tmp_path, extra=""):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        "threshold: 20\nnotify: {}\n" + extra + "products:\n"
        "  - {name: A, url: 'https://a'}\n  - {name: B, url: 'https://b'}\n"
    )
    return cfg


def test_run_notifies_only_once(tmp_path):
    cfg = write_config(tmp_path)
    state = tmp_path / "state.json"
    pages = {"https://a": page(18), "https://b": page(30)}

    with mock.patch.object(pt, "fetch_html", lambda url: pages[url]), \
         mock.patch.object(pt, "send_notification") as notify:
        assert pt.run(cfg, state) == 0
        assert notify.call_count == 1
        assert "A" in notify.call_args.args[1]

        pt.run(cfg, state)  # cijena i dalje ispod praga -> bez nove obavijesti
        assert notify.call_count == 1

        pages["https://a"] = page(25)
        pt.run(cfg, state)  # vratila se iznad
        pages["https://a"] = page(19)
        pt.run(cfg, state)  # ponovno pala -> nova obavijest
        assert notify.call_count == 2

    assert json.loads(state.read_text())["https://a"] == {"price": 19.0, "below": True, "promo": False}


def test_run_notifies_on_promo_once(tmp_path):
    cfg = write_config(tmp_path, 'promo: ["2+1"]\n')
    state = tmp_path / "state.json"
    pages = {"https://a": page(25), "https://b": page(30)}

    with mock.patch.object(pt, "fetch_html", lambda url: pages[url]), \
         mock.patch.object(pt, "send_notification") as notify:
        pt.run(cfg, state)
        assert notify.call_count == 0

        pages["https://b"] = page(30, "Akcija 2+1 gratis")
        pt.run(cfg, state)
        assert notify.call_count == 1
        title, message = notify.call_args.args[1:3]
        assert title == "Akcija: B"
        assert "2+1 gratis" in message and "30.00 €" in message

        pt.run(cfg, state)  # akcija i dalje traje -> bez nove obavijesti
        assert notify.call_count == 1

    assert json.loads(state.read_text())["https://b"]["promo"] is True


def test_run_checks_promo_when_price_missing(tmp_path):
    cfg = write_config(tmp_path, 'promo: ["2+1"]\n')
    state = tmp_path / "state.json"
    pages = {"https://a": "<p>Akcija 2+1</p>", "https://b": page(30)}

    with mock.patch.object(pt, "fetch_html", lambda url: pages[url]), \
         mock.patch.object(pt, "send_notification") as notify:
        pt.run(cfg, state)
    assert notify.call_count == 1
    assert notify.call_args.args[1] == "Akcija: A"
