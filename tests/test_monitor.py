import unittest
from pathlib import Path

import monitor

FIXTURES = Path(__file__).parent / "fixtures"


class ParsePriceTest(unittest.TestCase):
    def test_formats(self):
        self.assertEqual(monitor.parse_price("12,99 €"), 12.99)
        self.assertEqual(monitor.parse_price("1.299,00"), 1299.0)
        self.assertEqual(monitor.parse_price("1,299.00"), 1299.0)
        self.assertEqual(monitor.parse_price(9.5), 9.5)
        self.assertIsNone(monitor.parse_price("n/a"))


class ExtractPriceTest(unittest.TestCase):
    def test_jsonld_graph(self):
        page = (FIXTURES / "jsonld_graph.html").read_text()
        self.assertEqual(monitor.extract_price(page, {}), 14.49)

    def test_meta(self):
        page = (FIXTURES / "meta.html").read_text()
        self.assertEqual(monitor.extract_price(page, {}), 19.99)

    def test_custom_regex(self):
        page = '<span class="akcija">11,49 €</span>'
        product = {"price_regex": r'class="akcija">([\d,.]+)'}
        self.assertEqual(monitor.extract_price(page, product), 11.49)


class CheckProductTest(unittest.TestCase):
    product = {"name": "Pampers 4", "url": "https://x/p", "target_price": 15.0}

    def test_first_run_above_target_is_silent(self):
        state = {}
        self.assertIsNone(monitor.check_product(self.product, 20.0, state))
        self.assertEqual(state["https://x/p"]["price"], 20.0)

    def test_price_drop_notifies(self):
        state = {"https://x/p": {"price": 20.0}}
        msg = monitor.check_product(self.product, 18.0, state)
        self.assertIn("pojeftinilo", msg)

    def test_below_target_notifies_once(self):
        state = {}
        self.assertIsNotNone(monitor.check_product(self.product, 14.0, state))
        self.assertIsNone(monitor.check_product(self.product, 14.0, state))

    def test_target_resets_after_price_goes_up(self):
        state = {}
        monitor.check_product(self.product, 14.0, state)
        monitor.check_product(self.product, 20.0, state)
        self.assertIsNotNone(monitor.check_product(self.product, 14.0, state))


if __name__ == "__main__":
    unittest.main()
