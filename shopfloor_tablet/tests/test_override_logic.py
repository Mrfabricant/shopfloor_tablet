"""Logic tests for the Job Card override using stand-ins for frappe/erpnext.

They run anywhere (no bench). Inside a bench the real frappe is importable, so these are
skipped there; use tests/scenario.py against the real Job Card instead.
"""

import importlib
import sys
import types
import unittest

try:
	import frappe  # noqa: F401

	HAVE_FRAPPE = True
except ImportError:
	HAVE_FRAPPE = False


class Row:
	def __init__(self, **kw):
		self.__dict__.update(kw)

	def get(self, key, default=None):
		return self.__dict__.get(key, default)


def _install_stubs():
	frappe = types.ModuleType("frappe")

	class ThrowError(Exception):
		pass

	frappe._ = lambda s: s
	frappe.bold = lambda s: s

	def throw(msg, *a, **k):
		raise ThrowError(msg)

	frappe.throw = throw
	frappe.ThrowError = ThrowError

	utils = types.ModuleType("frappe.utils")
	utils.flt = lambda v, precision=None: round(float(v or 0), precision if precision is not None else 6)
	import datetime

	utils.get_datetime = lambda v: v if isinstance(v, datetime.datetime) else datetime.datetime.fromisoformat(str(v))
	frappe.utils = utils

	erp = types.ModuleType("erpnext")
	for name in (
		"erpnext.manufacturing",
		"erpnext.manufacturing.doctype",
		"erpnext.manufacturing.doctype.job_card",
	):
		sys.modules[name] = types.ModuleType(name)
	jc_mod = types.ModuleType("erpnext.manufacturing.doctype.job_card.job_card")

	class JobCard:
		calls = []

		def get(self, key, default=None):
			return getattr(self, key, default)

		def get_doc_before_save(self):
			return getattr(self, "_before", None)

		def precision(self, field):
			return 3

		def validate_overlap_in_time_log(self, d):
			self.calls.append("standard_overlap")

		def validate_employee_time_overlap(self, d):
			self.calls.append("employee_overlap")

		def set_process_loss(self):
			self.calls.append("standard_process_loss")

		def validate_sequence_id(self):
			self.calls.append("standard_sequence")

	jc_mod.JobCard = JobCard
	sys.modules.update(
		{
			"frappe": frappe,
			"frappe.utils": utils,
			"erpnext": erp,
			"erpnext.manufacturing.doctype.job_card.job_card": jc_mod,
		}
	)
	return jc_mod.JobCard


@unittest.skipIf(HAVE_FRAPPE, "real frappe present; covered by tests/scenario.py")
class TestShopfloorJobCardLogic(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		cls._saved = {k: sys.modules.get(k) for k in ("frappe", "frappe.utils", "erpnext")}
		cls.Base = _install_stubs()
		sys.modules.pop("shopfloor_tablet.overrides.job_card", None)
		cls.mod = importlib.import_module("shopfloor_tablet.overrides.job_card")

	@classmethod
	def tearDownClass(cls):
		sys.modules.pop("shopfloor_tablet.overrides.job_card", None)
		for k, v in cls._saved.items():
			if v is None:
				sys.modules.pop(k, None)
			else:
				sys.modules[k] = v

	def card(self, rows, for_quantity=100, completed=0, pending=0):
		c = self.mod.ShopfloorJobCard()
		self.Base.calls = []
		c.time_logs = rows
		c.name = "PO-JOB-1"
		c.for_quantity = for_quantity
		c.total_completed_qty = completed
		c.pending_qty = pending
		c.process_loss_qty = 0
		return c

	def test_tablet_rows_skip_machine_overlap_but_keep_employee_check(self):
		c = self.card([])
		c.validate_overlap_in_time_log(Row(from_tablet=1))
		self.assertEqual(self.Base.calls, ["employee_overlap"])

	def test_desk_rows_keep_standard_overlap(self):
		c = self.card([])
		c.validate_overlap_in_time_log(Row(from_tablet=0))
		self.assertEqual(self.Base.calls, ["standard_overlap"])

	def test_tablet_cards_skip_sequence_check(self):
		c = self.card([Row(from_tablet=1, to_time=None, completed_qty=0)])
		c.validate_sequence_id()
		self.assertNotIn("standard_sequence", self.Base.calls)

	def test_removing_last_tablet_row_still_skips_sequence_check(self):
		c = self.card([])
		before = self.card([Row(from_tablet=1, to_time=None, completed_qty=0)])
		c._before = before
		self.Base.calls = []
		c.validate_sequence_id()
		self.assertNotIn("standard_sequence", self.Base.calls)

	def test_desk_only_cards_keep_sequence_check(self):
		c = self.card([Row(from_tablet=0, to_time="2026-10-27 10:00:00", completed_qty=5)])
		c.validate_sequence_id()
		self.assertEqual(self.Base.calls, ["standard_sequence"])
		c = self.card([])
		c.validate_sequence_id()
		self.assertEqual(self.Base.calls, ["standard_sequence"])

	def test_scrap_is_sum_of_reported_scrap_not_unfinished_work(self):
		rows = [
			Row(from_tablet=1, to_time="2026-10-27 10:00:00", completed_qty=30, scrap_qty=2),
			Row(from_tablet=1, to_time="2026-10-27 11:00:00", completed_qty=20, scrap_qty=1),
		]
		c = self.card(rows, for_quantity=100, completed=50)
		c.set_process_loss()
		self.assertEqual(c.process_loss_qty, 3)
		self.assertNotIn("standard_process_loss", self.Base.calls)

	def test_cards_without_tablet_rows_use_standard_process_loss(self):
		c = self.card([Row(from_tablet=0, to_time="2026-10-27 10:00:00", completed_qty=5)])
		c.set_process_loss()
		self.assertEqual(self.Base.calls, ["standard_process_loss"])

	def test_submit_sets_pending_so_quantities_add_up(self):
		rows = [
			Row(from_tablet=1, from_time="2026-10-27 09:00:00", to_time="2026-10-27 10:00:00", employee="E1", completed_qty=30, scrap_qty=2),
			Row(from_tablet=1, from_time="2026-10-27 09:00:00", to_time="2026-10-27 11:00:00", employee="E2", completed_qty=20, scrap_qty=1),
		]
		c = self.card(rows, for_quantity=100, completed=50)
		c.before_submit()
		self.assertEqual(c.process_loss_qty, 3)
		self.assertEqual(c.pending_qty, 47)
		self.assertEqual(c.total_completed_qty + c.process_loss_qty + c.pending_qty, c.for_quantity)

	def test_submit_blocked_while_entry_open(self):
		rows = [
			Row(from_tablet=1, from_time="2026-10-27 09:00:00", to_time=None, employee="E1", completed_qty=0, scrap_qty=0),
		]
		c = self.card(rows)
		with self.assertRaises(sys.modules["frappe"].ThrowError):
			c.before_submit()

	def test_submit_leaves_non_tablet_cards_alone(self):
		rows = [Row(from_tablet=0, from_time="2026-10-27 09:00:00", to_time="2026-10-27 10:00:00", employee="E1", completed_qty=100)]
		c = self.card(rows, completed=100)
		c.before_submit()
		self.assertEqual(c.pending_qty, 0)


if __name__ == "__main__":
	unittest.main()
