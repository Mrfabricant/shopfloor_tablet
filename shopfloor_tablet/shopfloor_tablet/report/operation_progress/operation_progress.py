import frappe
from frappe import _
from frappe.utils import flt, get_datetime, now_datetime, time_diff_in_hours


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
		{"label": _("Oldest Open (hrs)"), "fieldname": "oldest_open_hours", "fieldtype": "Float", "precision": 1, "width": 110},
		{"label": _("Workers"), "fieldname": "workers", "fieldtype": "Data", "width": 260},
		{"label": _("Minutes"), "fieldname": "minutes", "fieldtype": "Float", "precision": 1, "width": 90},
	]


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

	rows = frappe.get_all(
		"Job Card Time Log",
		filters={"parenttype": "Job Card", "parentfield": "time_logs", "parent": ["in", [c.name for c in cards]]},
		fields=["parent", "employee", "from_time", "to_time", "time_in_mins", "completed_qty", "scrap_qty"],
		order_by="from_time asc",
		limit_page_length=0,
	)
	names = {
		e.name: e.employee_name
		for e in frappe.get_all(
			"Employee",
			filters={"name": ["in", list({r.employee for r in rows if r.employee})]},
			fields=["name", "employee_name"],
			limit_page_length=0,
		)
	}

	per_card = {}
	for r in rows:
		d = per_card.setdefault(
			r.parent,
			{"good": 0.0, "scrap": 0.0, "minutes": 0.0, "open": 0, "oldest": None, "workers": []},
		)
		worker = names.get(r.employee) or r.employee
		if worker and worker not in d["workers"]:
			d["workers"].append(worker)
		if r.to_time:
			d["good"] += flt(r.completed_qty)
			d["scrap"] += flt(r.scrap_qty)
			d["minutes"] += flt(r.time_in_mins)
		else:
			d["open"] += 1
			started = get_datetime(r.from_time)
			if d["oldest"] is None or started < d["oldest"]:
				d["oldest"] = started

	now = now_datetime()
	data = []
	for c in cards:
		d = per_card.get(c.name, {"good": 0.0, "scrap": 0.0, "minutes": 0.0, "open": 0, "oldest": None, "workers": []})
		remaining = max(flt(c.for_quantity) - d["good"] - d["scrap"], 0.0)
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
			}
		)
	return data
