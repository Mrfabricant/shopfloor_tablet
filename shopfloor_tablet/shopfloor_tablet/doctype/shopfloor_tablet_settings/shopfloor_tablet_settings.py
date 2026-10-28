from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import frappe
from frappe import _
from frappe.model.document import Document

from shopfloor_tablet import utils


class ShopfloorTabletSettings(Document):
	def validate(self):
		try:
			ZoneInfo(self.break_timezone or "")
		except (ZoneInfoNotFoundError, ValueError):
			frappe.throw(_("{0} is not a valid time zone (example: Europe/Zagreb).").format(self.break_timezone))

		if utils.to_time(self.break_start) == utils.to_time(self.break_end):
			frappe.throw(_("Break End must be different from Break Start."))

		if self.replacement_operation and not frappe.db.get_value(
			"Operation", self.replacement_operation, "is_corrective_operation"
		):
			frappe.throw(
				_("Operation {0} must be marked as Corrective Operation.").format(
					frappe.bold(self.replacement_operation)
				)
			)
