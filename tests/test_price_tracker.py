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


def test_run_notifies_only_once(tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        "threshold: 20\nnotify: {}\nproducts:\n"
        "  - {name: A, url: 'https://a'}\n  - {name: B, url: 'https://b'}\n"
    )
    state = tmp_path / "state.json"
    prices = {"https://a": 18.0, "https://b": 30.0}

    with mock.patch.object(pt, "fetch_price", lambda p: prices[p["url"]]), \
         mock.patch.object(pt, "send_notification") as notify:
        assert pt.run(cfg, state) == 0
        assert notify.call_count == 1
        assert "A" in notify.call_args.args[1]

        pt.run(cfg, state)  # cijena i dalje ispod praga -> bez nove obavijesti
        assert notify.call_count == 1

        prices["https://a"] = 25.0
        pt.run(cfg, state)  # vratila se iznad
        prices["https://a"] = 19.0
        pt.run(cfg, state)  # ponovno pala -> nova obavijest
        assert notify.call_count == 2

    assert json.loads(state.read_text())["https://a"] == {"price": 19.0, "below": True}
