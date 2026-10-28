"""Server methods behind the Shopfloor Tablet page.

All data lives in standard ERPNext Job Card time-log rows. Workers only get access to these
methods (through the page); the methods write with elevated permission after checking the
caller's role, so workers never need desk access to Job Card or see any rates or prices.
"""

import functools

import frappe
from frappe import _
from frappe.utils import cint, flt, get_datetime, now_datetime, time_diff_in_seconds

from shopfloor_tablet import utils
from shopfloor_tablet.settings import break_config, get_settings, times_for

ALLOWED_ROLES = {"Shop Floor Worker", "Manufacturing User", "Manufacturing Manager", "System Manager"}

# These roles may record work under any employee's name
SUPERVISOR_ROLES = {"Manufacturing User", "Manufacturing Manager", "System Manager"}

# Work Orders in these states are not offered on the tablet
HIDDEN_WORK_ORDER_STATUS = {"Draft", "Stopped", "Closed", "Completed", "Cancelled"}

# Replacement work is also allowed on finished Work Orders. "Not Started" is included because a
# Work Order with skipped material transfer stays there until the first Manufacture entry.
REPLACEMENT_WORK_ORDER_STATUS = {"Not Started", "In Process", "Completed"}

CONFLICT_ERRORS = (frappe.QueryDeadlockError, frappe.TimestampMismatchError)
CONFLICT_TEXTS = ("Record has changed since last read", "Deadlock found")


# --------------------------------------------------------------------------- access / helpers
def _is_conflict(exc):
	return isinstance(exc, CONFLICT_ERRORS) or any(t in str(exc) for t in CONFLICT_TEXTS)


def _retry_on_conflict(fn):
	"""Two workers saving the same Job Card at the same moment make the database reject one of
	them. Roll back and try once more (the quantity checks then see the other worker's save);
	if it collides again, ask the worker to retry instead of showing a database error."""

	@functools.wraps(fn)
	def wrapper(*args, **kwargs):
		try:
			return fn(*args, **kwargs)
		except Exception as exc:
			if not _is_conflict(exc):
				raise
			frappe.logger("shopfloor_tablet").warning(f"{fn.__name__}: save conflict, retrying ({exc!r:.120})")
		frappe.db.rollback()
		try:
			return fn(*args, **kwargs)
		except Exception as exc:
			if not _is_conflict(exc):
				raise
		frappe.db.rollback()
		frappe.throw(_("Someone just saved this operation at the same moment. Please try again."))

	return wrapper


def _check_access():
	if frappe.session.user == "Guest" or not (set(frappe.get_roles()) & ALLOWED_ROLES):
		frappe.throw(_("You do not have access to the shopfloor tablet."), frappe.PermissionError)


def _own_employee():
	"""The active Employee linked to the logged-in user, or None (shared login)."""
	return frappe.db.get_value(
		"Employee",
		{"user_id": frappe.session.user, "status": "Active"},
		["name", "employee_name"],
		as_dict=True,
	)


def _own_name_only():
	"""A worker with their own login (no supervisor role) may only use their own name.
	Returns that Employee, or None when the user may pick anyone."""
	if set(frappe.get_roles()) & SUPERVISOR_ROLES:
		return None
	return _own_employee()


def _get_active_employee(employee, lock=False):
	if not employee:
		frappe.throw(_("Choose your name first."))

	own = _own_name_only()
	if own and employee != own.name:
		frappe.throw(_("You can only record work under your own name."), frappe.PermissionError)

	if lock:
		# serialises double taps / parallel requests of the same worker
		frappe.db.get_value("Employee", employee, "name", for_update=True)

	emp = frappe.db.get_value("Employee", employee, ["name", "employee_name", "status"], as_dict=True)
	if not emp:
		frappe.throw(_("Employee {0} was not found.").format(employee))
	if emp.status != "Active":
		frappe.throw(_("Employee {0} is not active.").format(emp.employee_name or emp.name))
	return emp


def _closed_good(doc, exclude_row=None):
	"""Good quantity of finished entries on a loaded Job Card (scrap does not use up quantity)."""
	return sum(flt(row.completed_qty) for row in doc.get("time_logs") or [] if row.to_time and row.name != exclude_row)


def _check_job_card_open(doc):
	if doc.docstatus != 0:
		frappe.throw(_("This Job Card is already submitted or cancelled."))
	if doc.is_corrective_job_card:
		frappe.throw(_("This is replacement work. Use Replacement work on the tablet."))
	if doc.is_subcontracted:
		frappe.throw(_("This operation cannot be recorded on the tablet."))
	if doc.is_paused:
		frappe.throw(_("This Job Card is On Hold. Ask your supervisor."))
	if doc.work_order:
		status = frappe.db.get_value("Work Order", doc.work_order, "status")
		if status in HIDDEN_WORK_ORDER_STATUS:
			frappe.throw(_("Work Order {0} is {1}.").format(doc.work_order, status))


def _progress(job_cards):
	"""{job_card: {good, scrap, open}} for finished/open tablet-visible entries."""
	if not job_cards:
		return {}

	rows = frappe.db.sql(
		"""
		select parent,
			sum(case when to_time is not null then ifnull(completed_qty, 0) else 0 end) as good,
			sum(case when to_time is not null then ifnull(scrap_qty, 0) else 0 end) as scrap,
			sum(case when to_time is null then 1 else 0 end) as open_count
		from `tabJob Card Time Log`
		where parenttype = 'Job Card' and parentfield = 'time_logs' and parent in %(names)s
		group by parent
		""",
		{"names": tuple(job_cards)},
		as_dict=True,
	)
	return {
		r.parent: {"good": flt(r.good), "scrap": flt(r.scrap), "open": cint(r.open_count)} for r in rows
	}


def _open_entries(employee):
	"""Unfinished entries of a worker on Job Cards that are not submitted."""
	rows = frappe.db.sql(
		"""
		select tl.name as row_name, tl.parent as job_card, tl.from_time, tl.workstation as machine,
			jc.work_order, jc.operation, jc.production_item, jc.item_name, jc.for_quantity,
			jc.workstation as default_machine, jc.stock_uom, jc.is_corrective_job_card,
			jc.for_operation, jc.for_job_card
		from `tabJob Card Time Log` tl
		inner join `tabJob Card` jc on jc.name = tl.parent
		where tl.parenttype = 'Job Card' and tl.parentfield = 'time_logs' and tl.employee = %(employee)s
			and tl.to_time is null and jc.docstatus = 0
		order by tl.from_time
		""",
		{"employee": employee},
		as_dict=True,
	)
	if not rows:
		return []

	progress = _progress({r.job_card for r in rows})
	now = now_datetime()
	cfg = break_config()
	entries = []
	for r in rows:
		p = progress.get(r.job_card, {})
		_mins, brk, net = times_for(r.from_time, now, cfg=cfg)
		replacement = bool(r.is_corrective_job_card)
		entries.append(
			{
				"row_name": r.row_name,
				"job_card": r.job_card,
				"entry_type": "Replacement" if replacement else "Normal",
				"for_job_card": r.for_job_card if replacement else None,
				"work_order": r.work_order,
				"operation": (r.for_operation or r.operation) if replacement else r.operation,
				"item_code": r.production_item,
				"item_name": r.item_name or r.production_item,
				"uom": r.stock_uom,
				"machine": r.machine or r.default_machine,
				"started_at": get_datetime(r.from_time).strftime("%H:%M"),
				"started_date": get_datetime(r.from_time).strftime("%Y-%m-%d"),
				"elapsed_seconds": max(int(time_diff_in_seconds(now, r.from_time)), 0),
				"break_minutes": brk,
				"net_minutes": net,
				"required": flt(r.for_quantity),
				"good": flt(p.get("good")),
				"scrap": flt(p.get("scrap")),
				"remaining": utils.remaining_qty(r.for_quantity, p.get("good")),
			}
		)
	return entries


def _scrap_reasons():
	return frappe.get_all(
		"Scrap Reason", filters={"disabled": 0}, pluck="name", order_by="name asc", limit_page_length=0
	)


def _check_scrap_reason(reason):
	if not frappe.db.exists("Scrap Reason", {"name": reason, "disabled": 0}):
		frappe.throw(_("Reason {0} is not available.").format(reason))


def _load_own_open_row(employee, row_name):
	"""The worker's open row, on its Job Card loaded with a row lock."""
	job_card = _fetch_own_open_row(employee, row_name)
	doc = frappe.get_doc("Job Card", job_card, for_update=True)
	if doc.docstatus != 0:
		frappe.throw(_("This Job Card is already submitted or cancelled."))

	row = next((r for r in doc.time_logs if r.name == row_name), None)
	if not row or row.to_time:
		frappe.throw(_("This entry is already finished."))
	return doc, row


def _fetch_own_open_row(employee, row_name):
	row = frappe.db.get_value(
		"Job Card Time Log", row_name, ["parent", "parenttype", "parentfield", "employee"], as_dict=True
	)
	if not row or row.parenttype != "Job Card" or row.parentfield != "time_logs":
		frappe.throw(_("This entry no longer exists."))
	if row.employee != employee:
		frappe.throw(_("This entry belongs to another worker."))
	return row.parent


def _msg_qty_error(exc):
	frappe.throw(str(exc), title=_("Check the quantity"))


# --------------------------------------------------------------------------- read methods
@frappe.whitelist()
def get_context():
	"""Everything the page needs once: who is logged in, the worker list, machines, reasons."""
	_check_access()

	own = _own_employee()
	if own and not (set(frappe.get_roles()) & SUPERVISOR_ROLES):
		workers = [own]
	else:
		workers = frappe.get_all(
			"Employee",
			filters={"status": "Active"},
			fields=["name", "employee_name"],
			order_by="employee_name asc",
			limit_page_length=0,
		)
	return {
		"employee": own,
		"workers": workers,
		"machines": frappe.get_all(
			"Workstation",
			filters={"disabled": 0},
			pluck="name",
			order_by="name asc",
			limit_page_length=0,
		),
		"scrap_reasons": _scrap_reasons(),
		"issue_reasons": list(utils.ISSUE_REASONS),
		"replacement_enabled": bool(get_settings().replacement_operation),
	}


@frappe.whitelist()
def get_my_active(employee):
	_check_access()
	emp = _get_active_employee(employee)
	return _open_entries(emp.name)


@frappe.whitelist()
def list_open_operations(search=None, limit=200):
	"""Operations (draft Job Cards) that still have quantity left, with no prices."""
	_check_access()

	filters = {
		"docstatus": 0,
		"is_corrective_job_card": 0,
		"is_subcontracted": 0,
		"is_paused": 0,
		"work_order": ["is", "set"],
	}
	or_filters = None
	if search and search.strip():
		txt = f"%{search.strip()}%"
		or_filters = [
			["name", "like", txt],
			["work_order", "like", txt],
			["production_item", "like", txt],
			["item_name", "like", txt],
			["operation", "like", txt],
		]

	cards = frappe.get_all(
		"Job Card",
		filters=filters,
		or_filters=or_filters,
		fields=[
			"name",
			"work_order",
			"operation",
			"production_item",
			"item_name",
			"workstation",
			"for_quantity",
			"stock_uom",
			"sequence_id",
		],
		order_by="work_order asc, sequence_id asc, operation asc",
		limit_page_length=1000,
	)
	if not cards:
		return []

	wo_status = {
		r.name: r.status
		for r in frappe.get_all(
			"Work Order",
			filters={"name": ["in", list({c.work_order for c in cards})]},
			fields=["name", "status"],
			limit_page_length=0,
		)
	}
	cards = [c for c in cards if wo_status.get(c.work_order) not in HIDDEN_WORK_ORDER_STATUS]

	names = [c.name for c in cards]
	progress = _progress(names)

	working = {}
	if names:
		for r in frappe.db.sql(
			"""
			select tl.parent, ifnull(e.employee_name, tl.employee) as worker
			from `tabJob Card Time Log` tl
			left join `tabEmployee` e on e.name = tl.employee
			where tl.parenttype = 'Job Card' and tl.parentfield = 'time_logs' and tl.to_time is null and tl.parent in %(names)s
			order by tl.from_time
			""",
			{"names": tuple(names)},
			as_dict=True,
		):
			working.setdefault(r.parent, []).append(r.worker)

	out = []
	for c in cards:
		p = progress.get(c.name, {})
		remaining = utils.remaining_qty(c.for_quantity, p.get("good"))
		if remaining <= 0:
			continue
		out.append(
			{
				"job_card": c.name,
				"work_order": c.work_order,
				"operation": c.operation,
				"sequence_id": cint(c.sequence_id) or None,
				"item_code": c.production_item,
				"item_name": c.item_name or c.production_item,
				"uom": c.stock_uom,
				"machine": c.workstation,
				"required": flt(c.for_quantity),
				"good": flt(p.get("good")),
				"scrap": flt(p.get("scrap")),
				"remaining": remaining,
				"working_now": working.get(c.name, []),
			}
		)
		if len(out) >= cint(limit):
			break
	return out


@frappe.whitelist()
def get_state(employee, search=None):
	"""One round trip for the main screen: the worker's active entries and the open operations."""
	_check_access()
	emp = _get_active_employee(employee)
	active = _open_entries(emp.name)
	return {
		"active": active,
		# a worker with active work cannot start more, so skip the list
		"operations": [] if active else list_open_operations(search=search),
	}


@frappe.whitelist()
def get_entry_time(employee, row_name):
	"""Live duration / break / net minutes of the worker's open entry (the issue-minutes limit)."""
	_check_access()
	emp = _get_active_employee(employee)
	_fetch_own_open_row(emp.name, row_name)
	from_time = frappe.db.get_value("Job Card Time Log", row_name, "from_time")
	minutes, brk, net = times_for(from_time, now_datetime())
	return {"minutes": flt(minutes, 2), "break_minutes": flt(brk, 2), "net_minutes": flt(net, 2)}


# --------------------------------------------------------------------------- write methods
@frappe.whitelist(methods=["POST"])
@_retry_on_conflict
def start(employee, job_card, machine=None):
	"""Start work: add an open time-log row with the start time set automatically."""
	_check_access()
	emp = _get_active_employee(employee, lock=True)

	existing = _open_entries(emp.name)
	if existing:
		e = existing[0]
		frappe.throw(
			_("{0} already has active work on {1} ({2}). Finish it first.").format(
				emp.employee_name or emp.name, e["operation"], e["work_order"]
			)
		)

	doc = frappe.get_doc("Job Card", job_card, for_update=True)
	_check_job_card_open(doc)

	machine = machine or doc.workstation
	if not machine:
		frappe.throw(_("Choose a machine."))
	if not frappe.db.exists("Workstation", {"name": machine, "disabled": 0}):
		frappe.throw(_("Machine {0} is not available.").format(machine))

	good = _closed_good(doc)
	if utils.remaining_qty(doc.for_quantity, good, doc.precision("for_quantity")) <= 0:
		frappe.throw(_("Nothing is left to make on this operation."))

	doc.append(
		"time_logs",
		{
			"employee": emp.name,
			"from_time": now_datetime(),
			"completed_qty": 0,
			"scrap_qty": 0,
			"workstation": machine,
			"from_tablet": 1,
			"entry_type": "Normal",
		},
	)
	doc.save(ignore_permissions=True)

	return {"active": _open_entries(emp.name)}


@frappe.whitelist(methods=["POST"])
@_retry_on_conflict
def finish(
	employee,
	row_name,
	good_qty=0,
	scrap_qty=0,
	scrap_reason=None,
	issue_reason=None,
	issue_minutes=None,
	issue_note=None,
):
	"""Finish the worker's own open entry: end time and duration are set automatically.

	Good may not exceed what is left; scrap has no upper limit (scrapped pieces are made again).
	Good = scrap = 0 is allowed only with an issue reason. Issue minutes are part of the entry's
	net working time (break excluded) and never change the recorded time."""
	_check_access()

	try:
		good = utils.parse_qty(good_qty, "Good quantity")
		scrap = utils.parse_qty(scrap_qty, "Scrap quantity")
		issue_mins = utils.parse_qty(issue_minutes, "Issue minutes")
	except utils.QtyError as exc:
		_msg_qty_error(exc)
	issue_reason = (issue_reason or "").strip()
	issue_note = (issue_note or "").strip()

	emp = _get_active_employee(employee, lock=True)
	# Row lock on the Job Card: two workers finishing at the same moment cannot both overbook it.
	doc, row = _load_own_open_row(emp.name, row_name)
	if doc.is_corrective_job_card:
		frappe.throw(_("This is replacement work. Finish it as replacement work."))

	precision = doc.precision("for_quantity")
	good_done = _closed_good(doc, exclude_row=row_name)
	remaining = utils.remaining_qty(doc.for_quantity, good_done, precision)

	end = now_datetime()
	_mins, _brk, net = times_for(row.from_time, end)
	try:
		utils.check_issue(issue_reason, issue_mins, net)
		utils.check_finish(good, scrap, scrap_reason, remaining, issue_reason, precision)
	except utils.QtyError as exc:
		_msg_qty_error(exc)

	if scrap > 0:
		_check_scrap_reason(scrap_reason)

	row.to_time = end
	row.completed_qty = good
	row.scrap_qty = scrap
	row.scrap_reason = scrap_reason if scrap > 0 else None
	row.issue_reason = issue_reason or None
	row.issue_minutes = issue_mins if issue_reason else 0
	row.issue_note = issue_note or None
	doc.save(ignore_permissions=True)

	good_done = _closed_good(doc)
	return {
		"job_card": doc.name,
		"minutes": flt(row.time_in_mins, 2),
		"net_minutes": flt(row.net_minutes, 2),
		"break_minutes": flt(row.break_minutes, 2),
		"good": good,
		"scrap": scrap,
		"remaining": utils.remaining_qty(doc.for_quantity, good_done, precision),
	}


@frappe.whitelist(methods=["POST"])
@_retry_on_conflict
def cancel_start(employee, row_name):
	"""Remove an entry that was started by mistake. Only while it is open and has no quantity."""
	_check_access()
	emp = _get_active_employee(employee, lock=True)
	job_card = _fetch_own_open_row(emp.name, row_name)

	doc = frappe.get_doc("Job Card", job_card, for_update=True)
	if doc.docstatus != 0:
		frappe.throw(_("This Job Card is already submitted or cancelled."))

	row = next((r for r in doc.time_logs if r.name == row_name), None)
	if not row:
		frappe.throw(_("This entry no longer exists."))
	if row.to_time or flt(row.completed_qty) or flt(row.get("scrap_qty")):
		frappe.throw(_("Only an open entry without quantity can be cancelled."))

	doc.remove(row)
	if not doc.time_logs and doc.is_corrective_job_card:
		# an empty replacement card the tablet made is not kept as clutter
		frappe.delete_doc("Job Card", doc.name, ignore_permissions=True, force=True)
		return {"active": _open_entries(emp.name)}

	if not doc.time_logs:
		doc.actual_start_date = None
		doc.actual_end_date = None
	doc.save(ignore_permissions=True)

	return {"active": _open_entries(emp.name)}


# --------------------------------------------------------------------------- replacement work
def _replacement_operation():
	op = get_settings().replacement_operation
	if not op or not frappe.db.get_value("Operation", op, "is_corrective_operation"):
		frappe.throw(_("Replacement work is not set up. Ask your supervisor (Shopfloor Tablet Settings)."))
	return op


def _check_replacement_work_order(work_order):
	status = frappe.db.get_value("Work Order", {"name": work_order, "docstatus": 1}, "status")
	if not status:
		frappe.throw(_("Work Order {0} was not found.").format(work_order))
	if status not in REPLACEMENT_WORK_ORDER_STATUS:
		frappe.throw(_("Work Order {0} is {1}. Replacement work is not possible.").format(work_order, status))


@frappe.whitelist()
def list_replacement_work_orders(search=None, limit=100):
	"""Submitted Work Orders (also completed ones) that have operations to do replacement work on."""
	_check_access()

	filters = {"docstatus": 1, "status": ["in", sorted(REPLACEMENT_WORK_ORDER_STATUS)]}
	or_filters = None
	if search and search.strip():
		txt = f"%{search.strip()}%"
		or_filters = [["name", "like", txt], ["production_item", "like", txt], ["item_name", "like", txt]]

	orders = frappe.get_all(
		"Work Order",
		filters=filters,
		or_filters=or_filters,
		fields=["name", "production_item", "item_name", "status", "qty", "stock_uom"],
		order_by="modified desc",
		limit_page_length=cint(limit) or 100,
	)
	if not orders:
		return []

	with_cards = set(
		frappe.get_all(
			"Job Card",
			filters={
				"work_order": ["in", [o.name for o in orders]],
				"docstatus": ["<", 2],
				"is_corrective_job_card": 0,
			},
			pluck="work_order",
			distinct=True,
			limit_page_length=0,
		)
	)
	return [
		{
			"work_order": o.name,
			"item_code": o.production_item,
			"item_name": o.item_name or o.production_item,
			"status": o.status,
			"qty": flt(o.qty),
			"uom": o.stock_uom,
		}
		for o in orders
		if o.name in with_cards
	]


@frappe.whitelist()
def list_replacement_operations(work_order):
	"""All operations (Job Cards) of a Work Order, also finished or submitted ones."""
	_check_access()
	_check_replacement_work_order(work_order)

	cards = frappe.get_all(
		"Job Card",
		filters={"work_order": work_order, "docstatus": ["<", 2], "is_corrective_job_card": 0},
		fields=[
			"name",
			"operation",
			"sequence_id",
			"workstation",
			"for_quantity",
			"total_completed_qty",
			"docstatus",
			"status",
			"production_item",
			"item_name",
			"stock_uom",
		],
		order_by="sequence_id asc, operation asc, name asc",
		limit_page_length=0,
	)
	progress = _progress([c.name for c in cards])
	return [
		{
			"job_card": c.name,
			"work_order": work_order,
			"operation": c.operation,
			"sequence_id": cint(c.sequence_id) or None,
			"machine": c.workstation,
			"item_name": c.item_name or c.production_item,
			"uom": c.stock_uom,
			"required": flt(c.for_quantity),
			"good": flt(c.total_completed_qty) if c.docstatus == 1 else flt(progress.get(c.name, {}).get("good")),
			"submitted": c.docstatus == 1,
			"status": c.status,
		}
		for c in cards
	]


def _draft_corrective_card(source, operation):
	"""The ONE draft corrective Job Card the tablet uses for a source Job Card, or None.
	A locking read, so it also sees a card another worker created a moment ago."""
	rows = frappe.db.sql(
		"""
		select name from `tabJob Card`
		where for_job_card = %s and is_corrective_job_card = 1 and docstatus = 0 and operation = %s
		order by creation asc limit 1
		for update
		""",
		(source, operation),
	)
	return rows[0][0] if rows else None


def _new_corrective_card(source, operation, for_operation):
	"""ERPNext's own make_corrective_job_card. It checks the caller's Job Card read/create
	permission, which workers do not have; the caller's tablet rights were checked already, so the
	mapping runs as Administrator and the card is inserted as the worker."""
	from erpnext.manufacturing.doctype.job_card.job_card import make_corrective_job_card

	user = frappe.session.user
	frappe.session.user = "Administrator"
	try:
		doc = make_corrective_job_card(source, operation=operation, for_operation=for_operation)
	finally:
		frappe.session.user = user

	# Replacement work makes no pieces: with quantity 0 ERPNext's rule
	# "completed + process loss + pending = quantity" holds at submit (0 = 0) and the card adds
	# nothing to the quantities of the source operation or the Work Order. Material for the
	# replacement is not planned on this card.
	doc.for_quantity = 0
	doc.set("items", [])
	doc.flags.ignore_permissions = True
	return doc


@frappe.whitelist(methods=["POST"])
@_retry_on_conflict
def start_replacement(employee, job_card, machine=None):
	"""Start replacement work for an operation (source Job Card), on its draft corrective card."""
	_check_access()
	emp = _get_active_employee(employee, lock=True)

	existing = _open_entries(emp.name)
	if existing:
		e = existing[0]
		frappe.throw(
			_("{0} already has active work on {1} ({2}). Finish it first.").format(
				emp.employee_name or emp.name, e["operation"], e["work_order"]
			)
		)

	operation = _replacement_operation()

	# lock the source card: two workers starting replacement on it get one corrective card
	src = frappe.db.sql(
		"""select name, docstatus, is_corrective_job_card, work_order, operation, workstation
		from `tabJob Card` where name = %s for update""",
		job_card,
		as_dict=True,
	)
	src = src[0] if src else None
	if not src or src.docstatus == 2 or src.is_corrective_job_card or not src.work_order:
		frappe.throw(_("This operation cannot get replacement work."))
	_check_replacement_work_order(src.work_order)

	machine = machine or src.workstation
	if not machine:
		frappe.throw(_("Choose a machine."))
	if not frappe.db.exists("Workstation", {"name": machine, "disabled": 0}):
		frappe.throw(_("Machine {0} is not available.").format(machine))

	row = {
		"employee": emp.name,
		"from_time": now_datetime(),
		"completed_qty": 0,
		"scrap_qty": 0,
		"workstation": machine,
		"from_tablet": 1,
		"entry_type": "Replacement",
	}
	name = _draft_corrective_card(src.name, operation)
	if name:
		doc = frappe.get_doc("Job Card", name, for_update=True)
		doc.append("time_logs", row)
		doc.save(ignore_permissions=True)
	else:
		doc = _new_corrective_card(src.name, operation, src.operation)
		doc.append("time_logs", row)
		doc.insert()

	return {"active": _open_entries(emp.name), "job_card": doc.name}


@frappe.whitelist(methods=["POST"])
@_retry_on_conflict
def finish_replacement(employee, row_name, reason=None, note=None):
	"""Finish replacement work: time, reason and note only. No good, no scrap."""
	_check_access()
	reason = (reason or "").strip()
	note = (note or "").strip()
	if not reason:
		frappe.throw(_("Choose a reason for the replacement work."), title=_("Check the entry"))

	emp = _get_active_employee(employee, lock=True)
	doc, row = _load_own_open_row(emp.name, row_name)
	if not doc.is_corrective_job_card:
		frappe.throw(_("This is not replacement work."))
	_check_scrap_reason(reason)

	row.to_time = now_datetime()
	row.completed_qty = 0
	row.scrap_qty = 0
	row.replacement_reason = reason
	row.issue_note = note or None
	doc.save(ignore_permissions=True)

	return {
		"job_card": doc.name,
		"minutes": flt(row.time_in_mins, 2),
		"net_minutes": flt(row.net_minutes, 2),
		"break_minutes": flt(row.break_minutes, 2),
	}
