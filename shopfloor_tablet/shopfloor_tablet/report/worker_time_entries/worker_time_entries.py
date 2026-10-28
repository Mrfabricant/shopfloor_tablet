import frappe
from frappe import _
from frappe.utils import flt, now_datetime

from shopfloor_tablet.settings import break_config, times_for


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
		{"label": _("Entry Type"), "fieldname": "entry_type", "fieldtype": "Data", "width": 100},
		{"label": _("Job Card"), "fieldname": "job_card", "fieldtype": "Link", "options": "Job Card", "width": 120},
		{"label": _("For Job Card"), "fieldname": "for_job_card", "fieldtype": "Link", "options": "Job Card", "width": 120},
		{"label": _("Machine"), "fieldname": "machine", "fieldtype": "Link", "options": "Workstation", "width": 110},
		{"label": _("Start"), "fieldname": "from_time", "fieldtype": "Datetime", "width": 150},
		{"label": _("End"), "fieldname": "to_time", "fieldtype": "Datetime", "width": 150},
		{"label": _("Minutes"), "fieldname": "minutes", "fieldtype": "Float", "precision": 1, "width": 90},
		{"label": _("Break Minutes"), "fieldname": "break_minutes", "fieldtype": "Float", "precision": 1, "width": 90},
		{"label": _("Net Minutes"), "fieldname": "net_minutes", "fieldtype": "Float", "precision": 1, "width": 90},
		{"label": _("Issue Reason"), "fieldname": "issue_reason", "fieldtype": "Data", "width": 140},
		{"label": _("Issue Minutes"), "fieldname": "issue_minutes", "fieldtype": "Float", "precision": 1, "width": 90},
		{"label": _("Productive Minutes"), "fieldname": "productive_minutes", "fieldtype": "Float", "precision": 1, "width": 110},
		{"label": _("Replacement Minutes (net)"), "fieldname": "replacement_minutes", "fieldtype": "Float", "precision": 1, "width": 130},
		{"label": _("Note"), "fieldname": "issue_note", "fieldtype": "Data", "width": 200},
		{"label": _("Good Qty"), "fieldname": "good", "fieldtype": "Float", "width": 90},
		{"label": _("Scrap Qty"), "fieldname": "scrap", "fieldtype": "Float", "width": 90},
		{"label": _("Scrap Reason"), "fieldname": "scrap_reason", "fieldtype": "Link", "options": "Scrap Reason", "width": 130},
		{"label": _("Replacement Reason"), "fieldname": "replacement_reason", "fieldtype": "Link", "options": "Scrap Reason", "width": 130},
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
		# replacement rows belong to the operation they were done for
		conditions.append(
			"(case when jc.is_corrective_job_card = 1 then ifnull(jc.for_operation, jc.operation)"
			" else jc.operation end) = %(operation)s"
		)
		values["operation"] = filters.operation
	if filters.get("machine"):
		conditions.append("ifnull(tl.workstation, jc.workstation) = %(machine)s")
		values["machine"] = filters.machine
	if filters.get("entry_status") == "Open":
		conditions.append("tl.to_time is null")
	elif filters.get("entry_status") == "Finished":
		conditions.append("tl.to_time is not null")
	if filters.get("entry_type") == "Normal":
		conditions.append("ifnull(jc.is_corrective_job_card, 0) = 0")
	elif filters.get("entry_type") == "Replacement":
		conditions.append("jc.is_corrective_job_card = 1")

	rows = frappe.db.sql(
		f"""
		select tl.employee, e.employee_name, jc.work_order, jc.production_item as item_code,
			jc.operation, jc.for_operation, jc.is_corrective_job_card, jc.for_job_card,
			jc.name as job_card, ifnull(tl.workstation, jc.workstation) as machine,
			tl.from_time, tl.to_time, tl.time_in_mins, tl.break_minutes, tl.net_minutes,
			tl.issue_reason, tl.issue_minutes, tl.issue_note, tl.completed_qty, tl.scrap_qty,
			tl.scrap_reason, tl.replacement_reason, tl.from_tablet, jc.status as job_card_status
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
	cfg = break_config()
	data = []
	for r in rows:
		finished = bool(r.to_time)
		replacement = bool(r.is_corrective_job_card)
		if finished:
			minutes, brk, net = flt(r.time_in_mins), flt(r.break_minutes), flt(r.net_minutes)
		else:
			# open entry: live values up to now
			minutes, brk, net = times_for(r.from_time, now, cfg=cfg)
		minutes, brk, net = flt(minutes, 1), flt(brk, 1), flt(net, 1)
		issue = min(flt(r.issue_minutes), net)
		data.append(
			{
				"employee": r.employee,
				"employee_name": r.employee_name,
				"work_order": r.work_order,
				"item_code": r.item_code,
				"operation": (r.for_operation or r.operation) if replacement else r.operation,
				"entry_type": "Replacement" if replacement else "Normal",
				"job_card": r.job_card,
				"for_job_card": r.for_job_card if replacement else None,
				"machine": r.machine,
				"from_time": r.from_time,
				"to_time": r.to_time,
				"minutes": minutes,
				"break_minutes": brk,
				"net_minutes": net,
				"issue_reason": r.issue_reason,
				"issue_minutes": issue,
				"productive_minutes": flt(max(net - issue, 0.0), 1),
				"replacement_minutes": net if replacement else 0.0,
				"issue_note": r.issue_note,
				"good": flt(r.completed_qty),
				"scrap": flt(r.scrap_qty),
				"scrap_reason": r.scrap_reason,
				"replacement_reason": r.replacement_reason,
				"entry_status": "Finished" if finished else "Open",
				"source": "Tablet" if r.from_tablet else "Desk",
				"job_card_status": r.job_card_status,
			}
		)
	return data
