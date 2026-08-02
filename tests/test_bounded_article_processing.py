import threading
import time
import unittest


class BoundedArticleProcessingTests(unittest.TestCase):
    def test_fetches_keep_input_order_and_never_exceed_three_workers(self):
        from services.bounded_article_processing import fetch_articles

        active = 0
        peak = 0
        guard = threading.Lock()

        def fetch(value):
            nonlocal active, peak
            with guard:
                active += 1
                peak = max(peak, active)
            time.sleep(0.02 if value != "a" else 0.04)
            with guard:
                active -= 1
            return value.upper()

        self.assertEqual(fetch_articles(["a", "b", "c", "d"], fetch), ["A", "B", "C", "D"])
        self.assertLessEqual(peak, 3)

    def test_analyses_share_the_two_slot_semaphore(self):
        from services.bounded_article_processing import analyze_articles

        active = 0
        peak = 0
        guard = threading.Lock()

        def analyze(value):
            nonlocal active, peak
            with guard:
                active += 1
                peak = max(peak, active)
            time.sleep(0.02)
            with guard:
                active -= 1
            return value.upper()

        result = analyze_articles(["a", "b", "c"], analyze, threading.BoundedSemaphore(2))

        self.assertEqual(result, ["A", "B", "C"])
        self.assertLessEqual(peak, 2)


if __name__ == "__main__":
    unittest.main()
