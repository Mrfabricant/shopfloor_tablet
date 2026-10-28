import datetime as dt
import unittest

from shopfloor_tablet import utils

ZG = "Europe/Zagreb"
BREAK = ("10:30:00", "11:00:00")


def t(s):
	return dt.datetime.fromisoformat(s)


def brk(start, end, system_tz=ZG, break_tz=ZG, window=BREAK):
	return utils.break_minutes(t(start), t(end), window[0], window[1], system_tz, break_tz)


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
	def test_scrap_does_not_use_up_quantity(self):
		# 10 planned, 7 good (and 2 scrap) -> 3 left
		self.assertEqual(utils.remaining_qty(10, 7), 3.0)

	def test_never_negative(self):
		self.assertEqual(utils.remaining_qty(10, 12), 0.0)

	def test_float_noise(self):
		self.assertEqual(utils.remaining_qty(1, 0.1 + 0.2), 0.7)


class TestCheckFinish(unittest.TestCase):
	def test_needs_a_quantity_or_issue(self):
		with self.assertRaises(utils.QtyError):
			utils.check_finish(0, 0, "", 10)
		with self.assertRaises(utils.QtyError):
			utils.check_finish(0, 0, "", 10, issue_reason="  ")

	def test_zero_quantity_with_issue_reason(self):
		utils.check_finish(0, 0, "", 10, issue_reason="Machine problem")
		utils.check_finish(0, 0, "", 0, issue_reason="Waiting for materials")

	def test_scrap_needs_reason(self):
		with self.assertRaises(utils.QtyError):
			utils.check_finish(5, 1, "", 10)
		with self.assertRaises(utils.QtyError):
			utils.check_finish(5, 1, "   ", 10)
		utils.check_finish(5, 1, "Wire break", 10)

	def test_good_only_needs_no_reason(self):
		utils.check_finish(5, 0, None, 10)

	def test_good_over_remaining_blocked(self):
		with self.assertRaises(utils.QtyError) as ctx:
			utils.check_finish(11, 0, None, 10)
		self.assertIn("remaining", str(ctx.exception))

	def test_scrap_has_no_upper_limit(self):
		utils.check_finish(10, 3, "Wire break", 10)
		utils.check_finish(0, 50, "Wire break", 3)

	def test_exact_remaining_allowed(self):
		utils.check_finish(10, 0, None, 10)

	def test_scrap_only_allowed(self):
		utils.check_finish(0, 2, "Wrong crimp", 10)


class TestCheckIssue(unittest.TestCase):
	def test_no_issue(self):
		utils.check_issue("", 0, 0)
		utils.check_issue(None, None, 10)

	def test_within_net(self):
		utils.check_issue("Machine setup", 15, 30)
		utils.check_issue("Machine setup", 30, 30)

	def test_over_net_refused(self):
		with self.assertRaises(utils.QtyError) as ctx:
			utils.check_issue("Machine problem", 31, 30)
		self.assertIn("break not included", str(ctx.exception))

	def test_negative_refused(self):
		with self.assertRaises(utils.QtyError):
			utils.check_issue("Other", -1, 30)

	def test_minutes_need_reason(self):
		with self.assertRaises(utils.QtyError):
			utils.check_issue("", 5, 30)

	def test_unknown_reason_refused(self):
		with self.assertRaises(utils.QtyError):
			utils.check_issue("Coffee", 0, 30)


class TestBreakMinutes(unittest.TestCase):
	def test_fully_inside(self):
		self.assertEqual(brk("2026-10-27 10:35:00", "2026-10-27 10:50:00"), 15.0)

	def test_overlap_at_start_of_break(self):
		self.assertEqual(brk("2026-10-27 09:00:00", "2026-10-27 10:40:00"), 10.0)

	def test_overlap_at_end_of_break(self):
		self.assertEqual(brk("2026-10-27 10:50:00", "2026-10-27 12:00:00"), 10.0)

	def test_spans_the_break(self):
		self.assertEqual(brk("2026-10-27 08:00:00", "2026-10-27 14:00:00"), 30.0)

	def test_outside(self):
		self.assertEqual(brk("2026-10-27 11:00:00", "2026-10-27 15:00:00"), 0.0)
		self.assertEqual(brk("2026-10-27 06:00:00", "2026-10-27 10:30:00"), 0.0)

	def test_over_midnight(self):
		# night shift 22:00 -> 12:00 next day touches only the next day's break
		self.assertEqual(brk("2026-10-27 22:00:00", "2026-10-28 12:00:00"), 30.0)
		self.assertEqual(brk("2026-10-27 22:00:00", "2026-10-28 06:00:00"), 0.0)

	def test_two_days(self):
		self.assertEqual(brk("2026-10-27 10:00:00", "2026-10-28 10:45:00"), 45.0)
		self.assertEqual(brk("2026-10-26 08:00:00", "2026-10-28 18:00:00"), 90.0)

	def test_dst_day_break_in_other_zone(self):
		# system clock in UTC, break 10:30-11:00 Zagreb time. Zagreb is UTC+1 on 28 March and
		# UTC+2 from 29 March 2026 (DST), so the break is 09:30 UTC one day, 08:30 UTC the next.
		self.assertEqual(brk("2026-03-28 09:30:00", "2026-03-28 10:00:00", system_tz="UTC"), 30.0)
		self.assertEqual(brk("2026-03-29 09:30:00", "2026-03-29 10:00:00", system_tz="UTC"), 0.0)
		self.assertEqual(brk("2026-03-29 08:30:00", "2026-03-29 09:00:00", system_tz="UTC"), 30.0)
		# autumn change (25 October 2026): back to UTC+1
		self.assertEqual(brk("2026-10-25 09:30:00", "2026-10-25 10:00:00", system_tz="UTC"), 30.0)

	def test_dst_night_in_same_zone(self):
		# entry over the spring-forward night: only the morning break counts
		self.assertEqual(brk("2026-03-28 22:00:00", "2026-03-29 12:00:00"), 30.0)

	def test_window_over_midnight(self):
		window = ("23:30:00", "00:15:00")
		self.assertEqual(brk("2026-10-27 23:00:00", "2026-10-28 01:00:00", window=window), 45.0)
		self.assertEqual(brk("2026-10-28 00:00:00", "2026-10-28 00:10:00", window=window), 10.0)

	def test_time_formats(self):
		start, end = t("2026-10-27 10:00:00"), t("2026-10-27 12:00:00")
		self.assertEqual(
			utils.break_minutes(start, end, dt.timedelta(hours=10, minutes=30), dt.time(11), ZG, ZG), 30.0
		)
		self.assertEqual(utils.break_minutes(start, end, "10:30", "11:00", ZG, ZG), 30.0)

	def test_missing_or_reversed(self):
		self.assertEqual(utils.break_minutes(None, t("2026-10-27 12:00:00"), *BREAK, ZG, ZG), 0.0)
		self.assertEqual(brk("2026-10-27 12:00:00", "2026-10-27 10:00:00"), 0.0)

	def test_net_minutes(self):
		self.assertEqual(utils.net_minutes(120, 30), 90.0)
		self.assertEqual(utils.net_minutes(10, 30), 0.0)
		self.assertEqual(utils.net_minutes(None, None), 0.0)


if __name__ == "__main__":
	unittest.main()
