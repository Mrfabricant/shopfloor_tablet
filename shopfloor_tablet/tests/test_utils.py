import unittest

from shopfloor_tablet import utils


class TestParseQty(unittest.TestCase):
	def test_empty_is_zero(self):
		self.assertEqual(utils.parse_qty(None), 0.0)
		self.assertEqual(utils.parse_qty(""), 0.0)
		self.assertEqual(utils.parse_qty("  "), 0.0)

	def test_numbers(self):
		self.assertEqual(utils.parse_qty("12"), 12.0)
		self.assertEqual(utils.parse_qty(7), 7.0)
		self.assertEqual(utils.parse_qty("2,5"), 2.5)

	def test_rejects_bad_input(self):
		for bad in ("abc", "-1", -3, "nan", "inf", "1e999"):
			with self.assertRaises(utils.QtyError, msg=str(bad)):
				utils.parse_qty(bad)


class TestRemaining(unittest.TestCase):
	def test_scrap_uses_up_quantity(self):
		self.assertEqual(utils.remaining_qty(100, 40, 5), 55.0)

	def test_never_negative(self):
		self.assertEqual(utils.remaining_qty(10, 8, 5), 0.0)

	def test_float_noise(self):
		self.assertEqual(utils.remaining_qty(1, 0.1 + 0.2, 0), 0.7)


class TestCheckFinish(unittest.TestCase):
	def test_needs_a_quantity(self):
		with self.assertRaises(utils.QtyError):
			utils.check_finish(0, 0, "", 10)

	def test_scrap_needs_reason(self):
		with self.assertRaises(utils.QtyError):
			utils.check_finish(5, 1, "", 10)
		with self.assertRaises(utils.QtyError):
			utils.check_finish(5, 1, "   ", 10)
		utils.check_finish(5, 1, "Wire break", 10)

	def test_good_only_needs_no_reason(self):
		utils.check_finish(5, 0, None, 10)

	def test_over_quantity_blocked(self):
		with self.assertRaises(utils.QtyError) as ctx:
			utils.check_finish(8, 3, "Wire break", 10)
		self.assertIn("remaining", str(ctx.exception))

	def test_exact_remaining_allowed(self):
		utils.check_finish(7, 3, "Wire break", 10)
		utils.check_finish(10, 0, None, 10)

	def test_scrap_only_allowed(self):
		utils.check_finish(0, 2, "Wrong crimp", 10)


if __name__ == "__main__":
	unittest.main()
