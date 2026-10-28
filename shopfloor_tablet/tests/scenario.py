"""End-to-end check of the tablet flow on a real site. Nothing is kept: everything is rolled back.

It creates its own Work Order (quantity 10) from the BOM of an existing Work Order, so the quantity
rules can be checked exactly. Run on a site that has erpnext + shopfloor_tablet installed and at
least one Work Order whose BOM has two or more operations:

	bench --site mark.local execute shopfloor_tablet.tests.scenario.run
	bench --site mark.local execute shopfloor_tablet.tests.scenario.run --kwargs "{'bom': 'BOM-X-001'}"

Optional kwargs: bom, employee_a, employee_b, worker_user (a user linked to employee_a, for the
own-name rule; default worker1@example.com), keep=True (do not roll back).
"""

import frappe
from frappe.utils import add_to_date, now_datetime

from shopfloor_tablet import api


class _Report:
	def __init__(self):
		self.passed = 0
		self.failed = []

	def check(self, name, ok, detail=""):
		if ok:
			self.passed += 1
			print(f"  PASS  {name}")
		else:
			self.failed.append(f"{name}: {detail}")
			print(f"  FAIL  {name}  {detail}")


def _expect_error(fn, *needles):
	"""Return (raised, message). Message is matched case-insensitively against any needle."""
	try:
		fn()
	except Exception as exc:  # noqa: BLE001 - any error is what we are probing for
		msg = frappe.as_unicode(str(exc))
		return (not needles) or any(n.lower() in msg.lower() for n in needles), msg
	return False, "no error was raised"


def _pick_bom(bom):
	if bom:
		return bom
	rows = frappe.db.sql(
		"""select wo.bom_no from `tabWork Order` wo
		where wo.docstatus = 1 and (select count(*) from `tabBOM Operation` bo where bo.parent = wo.bom_no) >= 2
		order by wo.creation desc limit 1"""
	)
	if not rows:
		frappe.throw("No Work Order with a BOM of two or more operations found.")
	return rows[0][0]


def _make_work_order(bom):
	b = frappe.get_doc("BOM", bom)
	src = frappe.get_all(
		"Work Order", filters={"bom_no": bom, "docstatus": 1}, fields=["fg_warehouse", "wip_warehouse"], limit=1
	)
	wo = frappe.get_doc(
		{
			"doctype": "Work Order",
			"production_item": b.item,
			"bom_no": bom,
			"qty": 10,
			"company": b.company,
			"skip_transfer": 1,
			"fg_warehouse": src[0].fg_warehouse if src else None,
			"wip_warehouse": src[0].wip_warehouse if src else None,
		}
	)
	wo.get_items_and_operations_from_bom()
	wo.insert(ignore_permissions=True)
	wo.submit()
	cards = frappe.get_all(
		"Job Card",
		filters={"work_order": wo.name, "is_corrective_job_card": 0},
		pluck="name",
		order_by="sequence_id asc",
	)
	return wo, cards


def _pick_employees(a, b):
	chosen = [x for x in (a, b) if x]
	if len(chosen) < 2:
		chosen += frappe.get_all(
			"Employee",
			filters={"status": "Active", "name": ["not in", chosen or [""]]},
			pluck="name",
			order_by="name asc",
			limit_page_length=2 - len(chosen),
		)
	if len(chosen) < 2:
		frappe.throw("Two active employees are needed.")
	return chosen[0], chosen[1]


def _card(name):
	return frappe.get_doc("Job Card", name)


def _entry(emp, card=None):
	return next((e for e in api._open_entries(emp) if not card or e["job_card"] == card), None)


def _wo_op_completed(work_order, operation):
	return frappe.db.get_value(
		"Work Order Operation", {"parent": work_order, "operation": operation}, "completed_qty"
	)


def run(bom=None, employee_a=None, employee_b=None, worker_user="worker1@example.com", keep=False):
	frappe.set_user("Administrator")
	r = _Report()
	a, b = _pick_employees(employee_a, employee_b)
	reason = frappe.db.get_value("Scrap Reason", {"disabled": 0}, "name")

	try:
		wo, cards = _make_work_order(_pick_bom(bom))
		r.check("test Work Order has Job Cards for two operations", len(cards) >= 2, cards)
		jc, jc2 = cards[0], cards[1]
		op1 = _card(jc).operation
		print(f"\nWork Order {wo.name} | {jc} ({op1}) | {jc2} | workers A={a} B={b}\n")

		other = frappe.get_all(
			"Job Card",
			filters={
				"docstatus": 0,
				"is_corrective_job_card": 0,
				"is_paused": 0,
				"workstation": _card(jc).workstation,
				"work_order": ["!=", wo.name],
			},
			pluck="name",
			limit_page_length=1,
		)
		if other:
			print(f"0. Same machine, different Job Cards ({jc}, {other[0]}), at the same time")
			api.start(a, jc)
			api.start(b, other[0])
			# A finishes first, then B: B's time overlaps A's on the same machine. Standard ERPNext
			# raises an overlap error for this when the workstation capacity is 1.
			api.finish(a, _entry(a, jc)["row_name"], 0, 0, "", "Other")
			ok, msg = _expect_error(lambda: api.finish(b, _entry(b, other[0])["row_name"], 0, 0, "", "Other"))
			r.check("B can finish although the machine was used at the same time", not ok, msg)
		else:
			print("  SKIP  no other draft Job Card on the same workstation")

		print("1. Start: two workers on the same operation and machine")
		api.start(a, jc)
		api.start(b, jc)
		ea, eb = _entry(a, jc), _entry(b, jc)
		r.check("both workers have an open entry", bool(ea and eb))
		row = frappe.get_doc("Job Card Time Log", ea["row_name"])
		r.check("row is a Normal tablet row with a machine", row.from_tablet and row.workstation and row.entry_type == "Normal")
		ok, msg = _expect_error(lambda: api.start(a, jc), "already has active work")
		r.check("one active entry per worker", ok, msg)

		print("2. Finish rules")
		ok, msg = _expect_error(lambda: api.finish(a, ea["row_name"], 0, 0, ""), "issue reason")
		r.check("no quantity and no issue reason is refused", ok, msg)
		ok, msg = _expect_error(lambda: api.finish(a, ea["row_name"], 1, 1, ""), "scrap reason")
		r.check("scrap without a reason is refused", ok, msg)
		ok, msg = _expect_error(lambda: api.finish(a, ea["row_name"], 11, 0, ""), "remaining")
		r.check("good above the remaining quantity is refused", ok, msg)
		ok, msg = _expect_error(lambda: api.finish(b, ea["row_name"], 1, 0, ""), "another worker")
		r.check("a worker cannot finish someone else's entry", ok, msg)
		ok, msg = _expect_error(
			lambda: api.finish(a, ea["row_name"], 1, 0, "", "Machine setup", 5), "break not included"
		)
		r.check("issue minutes above the net working time are refused", ok, msg)
		ok, msg = _expect_error(lambda: api.finish(a, ea["row_name"], 1, 0, "", "", 1), "issue reason")
		r.check("issue minutes without an issue reason are refused", ok, msg)
		ok, msg = _expect_error(lambda: api.finish(a, ea["row_name"], 1, 0, "", "Lunch"), "unknown issue")
		r.check("an unknown issue reason is refused", ok, msg)

		print("3. 7 good + 2 scrap, then the remaining 3 good (scrap does not reduce remaining)")
		res = api.finish(a, ea["row_name"], 7, 2, reason, "Machine problem", 0, "blade dull")
		r.check("A finished 7 good + 2 scrap", res["good"] == 7 and res["scrap"] == 2, str(res))
		r.check("remaining = 10 - 7 good = 3", res["remaining"] == 3, str(res))
		ops = {o["job_card"]: o for o in api.list_open_operations()}
		r.check("list shows 3 left, scrap 2 separately", ops.get(jc, {}).get("remaining") == 3 and ops[jc]["scrap"] == 2, str(ops.get(jc)))
		ok, msg = _expect_error(lambda: api.finish(b, eb["row_name"], 4, 0, ""), "remaining")
		r.check("B cannot finish 4 good when 3 are left", ok, msg)
		res_b = api.finish(b, eb["row_name"], 0, 0, "", "Waiting for materials", 0, "no wire")
		r.check("B finishes with 0 / 0 and an issue reason", res_b["good"] == 0 and res_b["remaining"] == 3, str(res_b))
		ok, msg = _expect_error(lambda: api.finish(b, eb["row_name"], 1, 0, ""), "already finished")
		r.check("a finished entry cannot be finished twice", ok, msg)
		api.start(a, jc)
		res = api.finish(a, _entry(a, jc)["row_name"], 3, 0, "")
		r.check("A finishes the last 3 good -> 0 left", res["remaining"] == 0, str(res))
		r.check("operation is no longer offered", jc not in {o["job_card"] for o in api.list_open_operations()})
		ok, msg = _expect_error(lambda: api.start(a, jc), "nothing is left")
		r.check("no start on an operation with nothing left", ok, msg)

		print("4. What is stored")
		d = _card(jc)
		rows = [x for x in d.time_logs if x.from_tablet]
		zero = next((x for x in rows if x.employee == b), None)
		first = next((x for x in rows if x.completed_qty == 7), None)
		r.check("issue reason / minutes / note stored", first and first.issue_reason == "Machine problem" and first.issue_note == "blade dull")
		r.check("zero-quantity row stored with its time and issue", zero and zero.to_time and zero.issue_reason == "Waiting for materials" and not zero.completed_qty)
		r.check("break and net minutes on every finished row", all(x.net_minutes is not None and x.break_minutes is not None for x in rows))
		r.check("net = duration - break", all(abs(x.net_minutes - max(x.time_in_mins - x.break_minutes, 0)) < 0.01 for x in rows))
		r.check("total good = 10 (scrap is not good)", d.total_completed_qty == 10, d.total_completed_qty)
		r.check("header process loss = 0 (scrap lives in the rows)", d.process_loss_qty == 0, d.process_loss_qty)

		print("5. Desk edit: break and net are calculated for desk rows too")
		d2 = _card(jc)  # a desk-only row on a later operation would hit ERPNext's sequence check
		day = add_to_date(now_datetime(), days=-3).date()
		d2.append("time_logs", {"employee": b, "from_time": f"{day} 10:00:00", "to_time": f"{day} 12:00:00", "completed_qty": 0})
		d2.save()
		desk = next(x for x in d2.time_logs if not x.from_tablet and x.employee == b)
		r.check("desk row 10:00-12:00 -> break 30, net 90", (round(desk.break_minutes), round(desk.net_minutes)) == (30, 90), (desk.break_minutes, desk.net_minutes))
		r.check("recorded times untouched", str(desk.from_time).startswith(f"{day} 10:00") and round(desk.time_in_mins) == 120, (desk.from_time, desk.time_in_mins))
		d2.remove(desk)
		d2.save()

		print("6. Submit: 10 good, 2 scrap")
		d = _card(jc)
		try:
			d.submit()
			d.reload()
			r.check("Job Card submitted", d.docstatus == 1)
			r.check("pending 0, process loss 0, completed 10", (d.pending_qty, d.process_loss_qty, d.total_completed_qty) == (0, 0, 10), (d.pending_qty, d.process_loss_qty, d.total_completed_qty))
			r.check("zero-quantity row kept at submit", any(x.employee == b and not x.completed_qty and x.issue_reason for x in d.time_logs))
			r.check("Work Order operation shows 10", _wo_op_completed(wo.name, op1) == 10, _wo_op_completed(wo.name, op1))
		except Exception as exc:  # noqa: BLE001
			r.check("Job Card submitted", False, frappe.as_unicode(str(exc))[:300])

		print("7. Replacement work on the completed operation")
		api.start_replacement(a, jc)
		api.start_replacement(b, jc)
		ra, rb = _entry(a), _entry(b)
		r.check("both workers run replacement work", ra and rb and ra["entry_type"] == rb["entry_type"] == "Replacement", (ra, rb))
		r.check("ONE draft corrective card for the source card", ra["job_card"] == rb["job_card"], (ra["job_card"], rb["job_card"]))
		corr = _card(ra["job_card"])
		r.check(
			"corrective card: for_job_card, for_operation, qty 0, no items",
			corr.is_corrective_job_card and corr.for_job_card == jc and corr.for_operation == op1 and corr.for_quantity == 0 and not corr.items,
			(corr.for_job_card, corr.for_operation, corr.for_quantity, len(corr.items)),
		)
		r.check("active entry shows the source operation", ra["operation"] == op1, ra["operation"])
		ok, msg = _expect_error(lambda: api.finish(a, ra["row_name"], 1, 0, ""), "replacement")
		r.check("normal Finish is refused for replacement work", ok, msg)
		ok, msg = _expect_error(lambda: api.finish_replacement(a, ra["row_name"], ""), "reason")
		r.check("replacement Finish needs a reason", ok, msg)
		res = api.finish_replacement(a, ra["row_name"], reason, "re-crimped 2 pieces")
		r.check("replacement finished (time only)", "net_minutes" in res, str(res))
		api.cancel_start(b, rb["row_name"])
		r.check("B's replacement start cancelled; card kept for A's row", frappe.db.exists("Job Card", corr.name))
		corr.reload()
		row = corr.time_logs[0]
		r.check("replacement row: no good, no scrap, reason + note", (row.completed_qty, row.scrap_qty, row.replacement_reason, row.issue_note, row.entry_type) == (0, 0, reason, "re-crimped 2 pieces", "Replacement"))
		r.check("source card quantities unchanged", _card(jc).total_completed_qty == 10 and _wo_op_completed(wo.name, op1) == 10)
		try:
			corr.submit()
			r.check("corrective card submits under ERPNext's rules", corr.docstatus == 1)
		except Exception as exc:  # noqa: BLE001
			r.check("corrective card submits under ERPNext's rules", False, frappe.as_unicode(str(exc))[:300])
		r.check("after submit the source operation still shows 10", _wo_op_completed(wo.name, op1) == 10, _wo_op_completed(wo.name, op1))
		api.start_replacement(a, jc)
		r.check("a new draft corrective card after the first was submitted", _entry(a)["job_card"] != corr.name)
		api.cancel_start(a, _entry(a)["row_name"])
		api.start_replacement(a, jc2)
		empty = _entry(a)["job_card"]
		api.cancel_start(a, _entry(a)["row_name"])
		r.check("cancelling the only entry deletes the empty corrective card", not frappe.db.exists("Job Card", empty))

		print("8. Reports")
		from shopfloor_tablet.shopfloor_tablet.report.operation_progress import operation_progress
		from shopfloor_tablet.shopfloor_tablet.report.worker_time_entries import worker_time_entries

		_, data = operation_progress.execute({"work_order": wo.name, "scope": "All"})
		p = next((x for x in data if x["job_card"] == jc), {})
		r.check("Operation Progress: good 10, scrap 2, remaining 0", (p.get("good"), p.get("scrap"), p.get("remaining")) == (10, 2, 0), p)
		r.check("Operation Progress: replacement entries counted", p.get("replacement_entries") == 1, p.get("replacement_entries"))
		r.check("Operation Progress: productive = net - issue", abs(p["productive_minutes"] - max(p["net_minutes"] - p["issue_minutes"], 0)) < 1e-6)
		r.check("Operation Progress: no corrective card as a row", all(not frappe.db.get_value("Job Card", x["job_card"], "is_corrective_job_card") for x in data))
		_, rows = worker_time_entries.execute({"work_order": wo.name})
		types = {x["entry_type"] for x in rows}
		r.check("Worker Time Entries: Normal and Replacement rows", types == {"Normal", "Replacement"}, types)
		rep = next(x for x in rows if x["entry_type"] == "Replacement")
		r.check("replacement row shows the source operation and minutes", rep["operation"] == op1 and rep["replacement_minutes"] == rep["net_minutes"], rep)
		_, only = worker_time_entries.execute({"work_order": wo.name, "operation": op1, "entry_type": "Replacement"})
		r.check("filter by operation + entry type finds the replacement row", len(only) == 1, len(only))

		print("9. Own-name rule")
		if frappe.db.get_value("Employee", {"user_id": worker_user, "status": "Active"}) == a:
			frappe.set_user(worker_user)
			try:
				ok, msg = _expect_error(lambda: api.get_state(b), "own name")
				r.check(f"{worker_user} cannot use another worker's name", ok, msg)
				ok, msg = _expect_error(lambda: api.start_replacement(b, jc), "own name")
				r.check(f"{worker_user} cannot start replacement as another worker", ok, msg)
			finally:
				frappe.set_user("Administrator")
		else:
			print(f"  SKIP  {worker_user} is not linked to {a}")

	finally:
		if not keep:
			frappe.db.rollback()
			print("\n(rolled back: nothing was saved)")

	print(f"\n{r.passed} checks passed, {len(r.failed)} failed")
	for f in r.failed:
		print("  FAILED:", f)
	return {"passed": r.passed, "failed": r.failed}
