import frappe


def execute():
	"""Runs before doctypes/pages are synced, so the module and the role they refer to exist.

	Needed when this app is added to a site where the module or role are not there yet
	(for example the app folder was replaced after the scaffold was installed).
	"""
	if not frappe.db.exists("Module Def", "Shopfloor Tablet"):
		frappe.get_doc(
			{"doctype": "Module Def", "module_name": "Shopfloor Tablet", "app_name": "shopfloor_tablet"}
		).insert(ignore_permissions=True)

	from shopfloor_tablet.setup.install import ensure_role

	ensure_role()
