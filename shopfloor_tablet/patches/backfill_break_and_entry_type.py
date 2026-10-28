import frappe

from shopfloor_tablet import utils


def execute():
	"""Fill entry_type, break_minutes and net_minutes on existing Job Card time logs.

	Patches run before after_migrate, so the fields and settings are created here first. Values
	are written directly: from_time, to_time and time_in_mins are not touched.
	"""
	from shopfloor_tablet.settings import break_config
	from shopfloor_tablet.setup.install import setup

	setup()
	frappe.clear_cache(doctype="Job Card Time Log")
	cfg = break_config()

	rows = frappe.db.sql(
		"""
		select tl.name, tl.from_time, tl.to_time, tl.time_in_mins, jc.is_corrective_job_card
		from `tabJob Card Time Log` tl
		inner join `tabJob Card` jc on jc.name = tl.parent
		where tl.parenttype = 'Job Card' and tl.parentfield = 'time_logs'
		""",
		as_dict=True,
	)
	for r in rows:
		values = {"entry_type": "Replacement" if r.is_corrective_job_card else "Normal"}
		if r.from_time and r.to_time:
			brk = utils.break_minutes(r.from_time, r.to_time, *cfg)
			values.update(break_minutes=brk, net_minutes=utils.net_minutes(r.time_in_mins, brk))
		frappe.db.set_value("Job Card Time Log", r.name, values, update_modified=False)
