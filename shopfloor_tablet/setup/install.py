import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

WORKER_ROLE = "Shop Floor Worker"

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
