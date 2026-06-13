import unittest

from collector.extractor import extract_candidates
from collector.normalizer import normalize_tg_link


class ExtractorTests(unittest.TestCase):
    def test_normalize_public_link(self):
        link = normalize_tg_link("https://t.me/example_channel/123")
        self.assertFalse(link.rejected)
        self.assertEqual(link.url, "https://t.me/example_channel")
        self.assertEqual(link.username, "example_channel")

    def test_reject_private_invite(self):
        link = normalize_tg_link("https://t.me/+abcdefg")
        self.assertTrue(link.rejected)

    def test_extract_link(self):
        items = extract_candidates("推荐频道 https://t.me/example_channel 很不错")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].type_hint, "channel")


if __name__ == "__main__":
    unittest.main()
