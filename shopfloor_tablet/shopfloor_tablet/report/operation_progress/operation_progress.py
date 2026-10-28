import frappe
from frappe import _
from frappe.utils import flt, get_datetime, now_datetime, time_diff_in_hours

from shopfloor_tablet.settings import break_config, times_for


def execute(filters=None):
	filters = frappe._dict(filters or {})
	return get_columns(), get_data(filters)


def get_columns():
	return [
		{"label": _("Work Order"), "fieldname": "work_order", "fieldtype": "Link", "options": "Work Order", "width": 140},
		{"label": _("Item"), "fieldname": "item_code", "fieldtype": "Link", "options": "Item", "width": 130},
		{"label": _("Item Name"), "fieldname": "item_name", "fieldtype": "Data", "width": 160},
		{"label": _("Operation"), "fieldname": "operation", "fieldtype": "Link", "options": "Operation", "width": 130},
		{"label": _("Job Card"), "fieldname": "job_card", "fieldtype": "Link", "options": "Job Card", "width": 130},
		{"label": _("Machine"), "fieldname": "machine", "fieldtype": "Link", "options": "Workstation", "width": 120},
		{"label": _("Status"), "fieldname": "status", "fieldtype": "Data", "width": 120},
		{"label": _("Qty To Make"), "fieldname": "required", "fieldtype": "Float", "width": 100},
		{"label": _("Good Qty"), "fieldname": "good", "fieldtype": "Float", "width": 90},
		{"label": _("Scrap Qty"), "fieldname": "scrap", "fieldtype": "Float", "width": 90},
		{"label": _("Remaining"), "fieldname": "remaining", "fieldtype": "Float", "width": 90},
		{"label": _("Open Entries"), "fieldname": "open_entries", "fieldtype": "Int", "width": 90},
		{"label": _("Oldest Open (hrs)"), "fieldname": "oldest_open_hours", "fieldtype": "Float", "precision": 1, "width": 110, "disable_total": True},
		{"label": _("Workers"), "fieldname": "workers", "fieldtype": "Data", "width": 260},
		{"label": _("Minutes"), "fieldname": "minutes", "fieldtype": "Float", "precision": 1, "width": 90},
		{"label": _("Break Minutes"), "fieldname": "break_minutes", "fieldtype": "Float", "precision": 1, "width": 90},
		{"label": _("Net Minutes"), "fieldname": "net_minutes", "fieldtype": "Float", "precision": 1, "width": 90},
		{"label": _("Issue Minutes"), "fieldname": "issue_minutes", "fieldtype": "Float", "precision": 1, "width": 90},
		{"label": _("Productive Minutes"), "fieldname": "productive_minutes", "fieldtype": "Float", "precision": 1, "width": 110},
		{"label": _("Replacement Entries"), "fieldname": "replacement_entries", "fieldtype": "Int", "width": 100},
		{"label": _("Replacement Minutes (net)"), "fieldname": "replacement_minutes", "fieldtype": "Float", "precision": 1, "width": 130},
	]


def _empty():
	return {
		"good": 0.0,
		"scrap": 0.0,
		"minutes": 0.0,
		"break": 0.0,
		"net": 0.0,
		"issue": 0.0,
		"open": 0,
		"oldest": None,
		"workers": [],
		"repl_entries": 0,
		"repl_minutes": 0.0,
	}


def _row_times(r, now, cfg):
	"""(duration, break, net) of a time log; open entries get live values up to now."""
	if r.to_time:
		return flt(r.time_in_mins), flt(r.break_minutes), flt(r.net_minutes)
	return times_for(r.from_time, now, cfg=cfg)


def get_data(filters):
	job_card_filters = {"docstatus": ["<", 2], "is_corrective_job_card": 0}
	scope = filters.get("scope") or "Not Submitted"
	if scope == "Not Submitted":
		job_card_filters["docstatus"] = 0
	elif scope == "Submitted":
		job_card_filters["docstatus"] = 1

	for key, field in (("work_order", "work_order"), ("operation", "operation"), ("item_code", "production_item")):
		if filters.get(key):
			job_card_filters[field] = filters.get(key)

	cards = frappe.get_all(
		"Job Card",
		filters=job_card_filters,
		fields=[
			"name",
			"work_order",
			"operation",
			"production_item",
			"item_name",
			"workstation",
			"status",
			"for_quantity",
			"docstatus",
		],
		order_by="work_order asc, sequence_id asc, operation asc",
		limit_page_length=0,
	)
	if not cards:
		return []

	names = [c.name for c in cards]
	log_fields = [
		"parent",
		"employee",
		"from_time",
		"to_time",
		"time_in_mins",
		"completed_qty",
		"scrap_qty",
		"break_minutes",
		"net_minutes",
		"issue_minutes",
	]
	rows = frappe.get_all(
		"Job Card Time Log",
		filters={"parenttype": "Job Card", "parentfield": "time_logs", "parent": ["in", names]},
		fields=log_fields,
		order_by="from_time asc",
		limit_page_length=0,
	)

	# replacement work: time logs of corrective Job Cards made for these cards
	corrective = dict(
		frappe.get_all(
			"Job Card",
			filters={"is_corrective_job_card": 1, "docstatus": ["<", 2], "for_job_card": ["in", names]},
			fields=["name", "for_job_card"],
			as_list=True,
			limit_page_length=0,
		)
	)
	repl_rows = []
	if corrective:
		repl_rows = frappe.get_all(
			"Job Card Time Log",
			filters={"parenttype": "Job Card", "parentfield": "time_logs", "parent": ["in", list(corrective)]},
			fields=log_fields,
			limit_page_length=0,
		)

	names_by_emp = {
		e.name: e.employee_name
		for e in frappe.get_all(
			"Employee",
			filters={"name": ["in", list({r.employee for r in rows + repl_rows if r.employee})]},
			fields=["name", "employee_name"],
			limit_page_length=0,
		)
	}

	now = now_datetime()
	cfg = break_config()
	per_card = {}
	for r in rows:
		d = per_card.setdefault(r.parent, _empty())
		worker = names_by_emp.get(r.employee) or r.employee
		if worker and worker not in d["workers"]:
			d["workers"].append(worker)
		if not r.from_time:
			continue
		mins, brk, net = _row_times(r, now, cfg)
		d["minutes"] += mins
		d["break"] += brk
		d["net"] += net
		if r.to_time:
			d["good"] += flt(r.completed_qty)
			d["scrap"] += flt(r.scrap_qty)
			d["issue"] += min(flt(r.issue_minutes), net)
		else:
			d["open"] += 1
			started = get_datetime(r.from_time)
			if d["oldest"] is None or started < d["oldest"]:
				d["oldest"] = started

	for r in repl_rows:
		d = per_card.setdefault(corrective[r.parent], _empty())
		d["repl_entries"] += 1
		if r.from_time:
			d["repl_minutes"] += _row_times(r, now, cfg)[2]

	data = []
	for c in cards:
		d = per_card.get(c.name) or _empty()
		remaining = max(flt(c.for_quantity) - d["good"], 0.0)
		if filters.get("only_open") and not d["open"]:
			continue
		data.append(
			{
				"work_order": c.work_order,
				"item_code": c.production_item,
				"item_name": c.item_name,
				"operation": c.operation,
				"job_card": c.name,
				"machine": c.workstation,
				"status": c.status,
				"required": flt(c.for_quantity),
				"good": d["good"],
				"scrap": d["scrap"],
				"remaining": remaining,
				"open_entries": d["open"],
				"oldest_open_hours": flt(time_diff_in_hours(now, d["oldest"]), 1) if d["oldest"] else None,
				"workers": ", ".join(d["workers"]),
				"minutes": d["minutes"],
				"break_minutes": d["break"],
				"net_minutes": d["net"],
				"issue_minutes": d["issue"],
				"productive_minutes": max(d["net"] - d["issue"], 0.0),
				"replacement_entries": d["repl_entries"],
				"replacement_minutes": d["repl_minutes"],
			}
		)
	return data
