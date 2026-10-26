import frappe
from frappe import _
from frappe.utils import flt, get_datetime, now_datetime, time_diff_in_hours


def execute(filters=None):
	filters = frappe._dict(filters or {})
	return get_columns(), get_data(filters)


def get_columns():
	return [
		{"label": _("Employee"), "fieldname": "employee", "fieldtype": "Link", "options": "Employee", "width": 110},
		{"label": _("Worker"), "fieldname": "employee_name", "fieldtype": "Data", "width": 150},
		{"label": _("Work Order"), "fieldname": "work_order", "fieldtype": "Link", "options": "Work Order", "width": 130},
		{"label": _("Item"), "fieldname": "item_code", "fieldtype": "Link", "options": "Item", "width": 120},
		{"label": _("Operation"), "fieldname": "operation", "fieldtype": "Link", "options": "Operation", "width": 120},
		{"label": _("Job Card"), "fieldname": "job_card", "fieldtype": "Link", "options": "Job Card", "width": 120},
		{"label": _("Machine"), "fieldname": "machine", "fieldtype": "Link", "options": "Workstation", "width": 110},
		{"label": _("Start"), "fieldname": "from_time", "fieldtype": "Datetime", "width": 150},
		{"label": _("End"), "fieldname": "to_time", "fieldtype": "Datetime", "width": 150},
		{"label": _("Minutes"), "fieldname": "minutes", "fieldtype": "Float", "precision": 1, "width": 90},
		{"label": _("Good Qty"), "fieldname": "good", "fieldtype": "Float", "width": 90},
		{"label": _("Scrap Qty"), "fieldname": "scrap", "fieldtype": "Float", "width": 90},
		{"label": _("Scrap Reason"), "fieldname": "scrap_reason", "fieldtype": "Link", "options": "Scrap Reason", "width": 130},
		{"label": _("Entry"), "fieldname": "entry_status", "fieldtype": "Data", "width": 80},
		{"label": _("Source"), "fieldname": "source", "fieldtype": "Data", "width": 70},
		{"label": _("Job Card Status"), "fieldname": "job_card_status", "fieldtype": "Data", "width": 120},
	]


def get_data(filters):
	conditions = ["jc.docstatus < 2"]
	values = {}

	if filters.get("from_date"):
		conditions.append("date(tl.from_time) >= %(from_date)s")
		values["from_date"] = filters.from_date
	if filters.get("to_date"):
		conditions.append("date(tl.from_time) <= %(to_date)s")
		values["to_date"] = filters.to_date
	if filters.get("employee"):
		conditions.append("tl.employee = %(employee)s")
		values["employee"] = filters.employee
	if filters.get("work_order"):
		conditions.append("jc.work_order = %(work_order)s")
		values["work_order"] = filters.work_order
	if filters.get("operation"):
		conditions.append("jc.operation = %(operation)s")
		values["operation"] = filters.operation
	if filters.get("machine"):
		conditions.append("ifnull(tl.workstation, jc.workstation) = %(machine)s")
		values["machine"] = filters.machine
	if filters.get("entry_status") == "Open":
		conditions.append("tl.to_time is null")
	elif filters.get("entry_status") == "Finished":
		conditions.append("tl.to_time is not null")

	rows = frappe.db.sql(
		f"""
		select tl.employee, e.employee_name, jc.work_order, jc.production_item as item_code,
			jc.operation, jc.name as job_card, ifnull(tl.workstation, jc.workstation) as machine,
			tl.from_time, tl.to_time, tl.time_in_mins, tl.completed_qty, tl.scrap_qty,
			tl.scrap_reason, tl.from_tablet, jc.status as job_card_status
		from `tabJob Card Time Log` tl
		inner join `tabJob Card` jc on jc.name = tl.parent
		left join `tabEmployee` e on e.name = tl.employee
		where tl.parenttype = 'Job Card' and tl.parentfield = 'time_logs' and {" and ".join(conditions)}
		order by tl.from_time desc
		""",  # noqa: S608 - conditions are fixed strings, values are bound parameters
		values,
		as_dict=True,
	)

	now = now_datetime()
	data = []
	for r in rows:
		finished = bool(r.to_time)
		minutes = (
			flt(r.time_in_mins)
			if finished
			else flt(time_diff_in_hours(now, get_datetime(r.from_time)) * 60, 1)
		)
		data.append(
			{
				"employee": r.employee,
				"employee_name": r.employee_name,
				"work_order": r.work_order,
				"item_code": r.item_code,
				"operation": r.operation,
				"job_card": r.job_card,
				"machine": r.machine,
				"from_time": r.from_time,
				"to_time": r.to_time,
				"minutes": minutes,
				"good": flt(r.completed_qty),
				"scrap": flt(r.scrap_qty),
				"scrap_reason": r.scrap_reason,
				"entry_status": "Finished" if finished else "Open",
				"source": "Tablet" if r.from_tablet else "Desk",
				"job_card_status": r.job_card_status,
			}
		)
	return data
