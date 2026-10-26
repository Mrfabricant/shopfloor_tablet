import frappe
from frappe import _
from frappe.utils import flt, get_datetime
from erpnext.manufacturing.doctype.job_card.job_card import JobCard


class ShopfloorJobCard(JobCard):
	"""Job Card with four small adjustments for rows entered on the shopfloor tablet.

	Rows created by the tablet carry ``from_tablet = 1``. Everything else about the Job Card
	(costing, Work Order update, status) stays standard ERPNext.
	"""

	def _tablet_rows(self):
		return [row for row in (self.get("time_logs") or []) if row.get("from_tablet")]

	def _had_tablet_rows(self):
		"""The stored version of this card (before the current save) has tablet rows."""
		before = self.get_doc_before_save()
		return bool(before and any(row.get("from_tablet") for row in (before.get("time_logs") or [])))

	# 1. Machine overlap -------------------------------------------------------------
	def validate_overlap_in_time_log(self, d):
		"""Several workers must be able to run at the same time, also on the same machine.

		ERPNext rejects a time row when another Job Card on the same workstation overlaps it and
		the workstation capacity is used up. For tablet rows only that machine check is skipped;
		the check that one employee cannot work twice at the same time stays on.
		"""
		if d.get("from_tablet"):
			self.validate_employee_time_overlap(d)
			return

		super().validate_overlap_in_time_log(d)

	# 1b. Operation sequence ----------------------------------------------------------
	def validate_sequence_id(self):
		"""ERPNext v16 always fills Sequence IDs (from the BOM row order when none are set), so
		every later operation would be blocked until the previous Job Card is submitted. Workers
		run operations in parallel, so cards with tablet entries skip the sequence check.

		"Had" counts too: cancelling the last tablet entry on a later operation must not be blocked
		by the check that the entry itself was exempt from."""
		if self._tablet_rows() or self._had_tablet_rows():
			return

		super().validate_sequence_id()

	# 2. Scrap -----------------------------------------------------------------------
	def set_process_loss(self):
		"""ERPNext sets process loss to "quantity - completed - pending" on every draft save,
		which would count work that is simply not done yet as scrap. For cards worked on the tablet
		the process loss is the scrap the workers actually reported."""
		if not self._tablet_rows():
			return super().set_process_loss()

		self.process_loss_qty = flt(
			sum(flt(row.get("scrap_qty")) for row in self.get("time_logs")),
			self.precision("process_loss_qty"),
		)

	# 3. Submit ----------------------------------------------------------------------
	def before_submit(self):
		parent_hook = getattr(super(), "before_submit", None)
		if parent_hook:
			parent_hook()

		if not self._tablet_rows():
			return

		open_rows = [row for row in self.get("time_logs") if not row.to_time]
		if open_rows:
			names = ", ".join(sorted({frappe.bold(row.employee) for row in open_rows}))
			started = min(get_datetime(row.from_time) for row in open_rows)
			frappe.throw(
				_(
					"Job Card {0} still has an open entry ({1}, started {2}). "
					"Finish or cancel it before submitting."
				).format(frappe.bold(self.name), names, started.strftime("%Y-%m-%d %H:%M")),
				title=_("Open entries"),
			)

		# ERPNext requires completed + process loss + pending == quantity at submit.
		# Quantity nobody worked on goes to "pending" (carried to a new Job Card), not to scrap.
		precision = self.precision("pending_qty")
		self.process_loss_qty = flt(
			sum(flt(row.get("scrap_qty")) for row in self.get("time_logs")), precision
		)
		self.pending_qty = max(
			flt(
				flt(self.for_quantity) - flt(self.total_completed_qty) - flt(self.process_loss_qty),
				precision,
			),
			0.0,
		)
