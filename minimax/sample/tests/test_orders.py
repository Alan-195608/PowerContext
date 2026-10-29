import unittest

from orders import list_orders


class TargetTests(unittest.TestCase):
    def setUp(self):
        self.orders = [
            {"id": 1, "status": "pending"},
            {"id": 2, "status": "paid"},
            {"id": 3, "status": "cancelled"},
            {"id": 4, "status": "paid"},
            {"id": 5},
        ]

    def test_each_status(self):
        for status, ids in [("pending", [1]), ("paid", [2, 4]), ("cancelled", [3])]:
            with self.subTest(status=status):
                self.assertEqual([o["id"] for o in list_orders(self.orders, status)], ids)

    def test_invalid_status(self):
        for status in ["", "unknown", "PAID", 0, False, [], {}]:
            with self.subTest(status=status):
                with self.assertRaisesRegex(ValueError, "status"):
                    list_orders(self.orders, status)

    def test_empty_still_validates(self):
        with self.assertRaisesRegex(ValueError, "status"):
            list_orders([], "unknown")

    def test_filter_returns_copies(self):
        result = list_orders(self.orders, "paid")
        self.assertEqual([o["id"] for o in result], [2, 4])
        result[0]["id"] = 99
        self.assertEqual(self.orders[1]["id"], 2)


class RegressionTests(unittest.TestCase):
    def test_no_filter_preserves_everything(self):
        orders = [{"id": 2}, {"id": 1, "status": "paid"}]
        self.assertEqual(list_orders(orders), orders)
        self.assertEqual(list_orders(orders, None), orders)

    def test_shallow_copies(self):
        orders = [{"id": 1, "status": "paid"}]
        result = list_orders(orders)
        self.assertIsNot(result, orders)
        self.assertIsNot(result[0], orders[0])
        result[0]["id"] = 9
        self.assertEqual(orders[0]["id"], 1)

    def test_empty_valid(self):
        self.assertEqual(list_orders([]), [])
        self.assertEqual(list_orders([], "paid"), [])


if __name__ == "__main__":
    unittest.main()
