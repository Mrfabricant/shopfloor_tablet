import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

WORKER_ROLE = "Shop Floor Worker"
SETTINGS = "Shopfloor Tablet Settings"
REPLACEMENT_OPERATION = "Replacement Work"

DEFAULT_SETTINGS = {
	"break_start": "10:30:00",
	"break_end": "11:00:00",
	"break_timezone": "Europe/Zagreb",
}

DEFAULT_SCRAP_REASONS = [
	"Wire break",
	"Wrong length",
	"Wrong crimp",
	"Damaged insulation",
	"Material defect",
	"Machine fault",
	"Operator error",
	"Other",
]

CUSTOM_FIELDS = {
	"Job Card Time Log": [
		{
			"fieldname": "workstation",
			"label": "Machine",
			"fieldtype": "Link",
			"options": "Workstation",
			"insert_after": "completed_qty",
		},
		{
			"fieldname": "scrap_qty",
			"label": "Scrap Qty",
			"fieldtype": "Float",
			"default": "0",
			"non_negative": 1,
			"in_list_view": 1,
			"insert_after": "workstation",
		},
		{
			"fieldname": "scrap_reason",
			"label": "Scrap Reason",
			"fieldtype": "Link",
			"options": "Scrap Reason",
			"depends_on": "eval:flt(doc.scrap_qty) > 0",
			"mandatory_depends_on": "eval:flt(doc.scrap_qty) > 0",
			"insert_after": "scrap_qty",
		},
		{
			"fieldname": "from_tablet",
			"label": "Entered On Tablet",
			"fieldtype": "Check",
			"read_only": 1,
			"no_copy": 1,
			"insert_after": "scrap_reason",
		},
		{
			"fieldname": "entry_type",
			"label": "Entry Type",
			"fieldtype": "Select",
			"options": "Normal\nReplacement",
			"default": "Normal",
			"read_only": 1,
			"description": "Replacement = time on a corrective Job Card (no good, no scrap)",
			"insert_after": "from_tablet",
		},
		{
			"fieldname": "replacement_reason",
			"label": "Replacement Reason",
			"fieldtype": "Link",
			"options": "Scrap Reason",
			"depends_on": "eval:doc.entry_type == 'Replacement'",
			"insert_after": "entry_type",
		},
		{
			"fieldname": "break_minutes",
			"label": "Break Minutes",
			"fieldtype": "Float",
			"read_only": 1,
			"no_copy": 1,
			"description": "Part of this entry inside the daily break (Shopfloor Tablet Settings)",
			"insert_after": "replacement_reason",
		},
		{
			"fieldname": "net_minutes",
			"label": "Net Working Minutes",
			"fieldtype": "Float",
			"read_only": 1,
			"no_copy": 1,
			"description": "Time In Mins minus Break Minutes",
			"insert_after": "break_minutes",
		},
		{
			"fieldname": "issue_reason",
			"label": "Issue Reason",
			"fieldtype": "Select",
			"options": "\nMachine setup\nMachine problem\nWaiting for materials\nOther",
			"insert_after": "net_minutes",
		},
		{
			"fieldname": "issue_minutes",
			"label": "Issue Minutes",
			"fieldtype": "Float",
			"non_negative": 1,
			"description": "Part of the net working minutes lost to the issue",
			"insert_after": "issue_reason",
		},
		{
			"fieldname": "issue_note",
			"label": "Note",
			"fieldtype": "Small Text",
			"insert_after": "issue_minutes",
		},
	]
}


def before_install():
	ensure_role()


def after_install():
	setup()


def after_migrate():
	setup()


def setup():
	ensure_role()
	create_custom_fields(CUSTOM_FIELDS, update=True)
	ensure_default_scrap_reasons()
	ensure_settings()
	frappe.db.commit()


def ensure_role():
	if frappe.db.exists("Role", WORKER_ROLE):
		return

	role = frappe.new_doc("Role")
	role.role_name = WORKER_ROLE
	role.desk_access = 1
	# keep the desk quiet for people who only use the tablet page
	for field in (
		"search_bar",
		"notifications",
		"list_sidebar",
		"bulk_actions",
		"view_switcher",
		"form_sidebar",
		"timeline",
		"dashboard",
	):
		if role.meta.has_field(field):
			role.set(field, 0)
	role.insert(ignore_permissions=True)


def ensure_default_scrap_reasons():
	"""Starter list, only when there are no scrap reasons at all. Supervisors maintain it afterwards."""
	if not frappe.db.exists("DocType", "Scrap Reason") or frappe.db.count("Scrap Reason"):
		return

	for reason in DEFAULT_SCRAP_REASONS:
		frappe.get_doc({"doctype": "Scrap Reason", "reason": reason}).insert(ignore_permissions=True)


def ensure_replacement_operation():
	"""Corrective Operation used for replacement work. Created once; kept corrective."""
	if not frappe.db.exists("Operation", REPLACEMENT_OPERATION):
		frappe.get_doc(
			{
				"doctype": "Operation",
				"name": REPLACEMENT_OPERATION,
				"is_corrective_operation": 1,
				"description": "Replacement work on the shopfloor tablet (corrective Job Card)",
			}
		).insert(ignore_permissions=True)
	elif not frappe.db.get_value("Operation", REPLACEMENT_OPERATION, "is_corrective_operation"):
		frappe.db.set_value("Operation", REPLACEMENT_OPERATION, "is_corrective_operation", 1)
	return REPLACEMENT_OPERATION


def ensure_settings():
	"""Fill empty settings with the defaults; values a supervisor changed are kept."""
	if not frappe.db.exists("DocType", SETTINGS):
		return

	operation = ensure_replacement_operation()
	doc = frappe.get_single(SETTINGS)
	changed = False
	for field, value in DEFAULT_SETTINGS.items():
		if not doc.get(field):
			doc.set(field, value)
			changed = True
	if not doc.replacement_operation:
		doc.replacement_operation = operation
		changed = True
	if changed or doc.is_new():
		doc.flags.ignore_permissions = True
		doc.save()
