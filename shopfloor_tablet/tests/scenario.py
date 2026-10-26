"""End-to-end check of the tablet flow on a real site. Nothing is kept: everything is rolled back.

Run on a site that has erpnext + shopfloor_tablet installed and at least one DRAFT Job Card
(a Work Order with operations, submitted) whose quantity is 5 or more:

	bench --site mark.local execute shopfloor_tablet.tests.scenario.run
	bench --site mark.local execute shopfloor_tablet.tests.scenario.run --kwargs "{'job_card': 'PO-JOB-00001'}"

Optional kwargs: employee_a, employee_b, other_job_card (a second draft Job Card on the SAME
workstation, to prove two workers can run the same machine on different orders), keep=True.
"""

import frappe

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


def _pick_job_card(name):
	if name:
		return frappe.get_doc("Job Card", name)
	rows = frappe.get_all(
		"Job Card",
		filters={
			"docstatus": 0,
			"is_corrective_job_card": 0,
			"is_subcontracted": 0,
			"is_paused": 0,
			"for_quantity": [">=", 5],
			"work_order": ["is", "set"],
		},
		pluck="name",
		order_by="creation desc",
		limit_page_length=1,
	)
	if not rows:
		frappe.throw("No draft Job Card with quantity >= 5 found. Create and submit a Work Order first.")
	return frappe.get_doc("Job Card", rows[0])


def _pick_employees(a, b, company):
	chosen = [x for x in (a, b) if x]
	if len(chosen) < 2:
		existing = frappe.get_all(
			"Employee",
			filters={"status": "Active", "name": ["not in", chosen or [""]]},
			pluck="name",
			limit_page_length=2 - len(chosen),
		)
		chosen += existing

	while len(chosen) < 2:
		emp = frappe.get_doc(
			{
				"doctype": "Employee",
				"first_name": f"SFT Test {len(chosen) + 1}",
				"gender": frappe.db.get_value("Gender", {}, "name") or "Male",
				"date_of_birth": "1990-01-01",
				"date_of_joining": "2020-01-01",
				"company": company,
				"status": "Active",
			}
		).insert(ignore_permissions=True)
		chosen.append(emp.name)
	return chosen[0], chosen[1]


def _card(name):
	return frappe.get_doc("Job Card", name)


def _entry(emp, card):
	return next((e for e in api._open_entries(emp) if e["job_card"] == card), None)


def run(job_card=None, employee_a=None, employee_b=None, other_job_card=None, keep=False):
	frappe.set_user("Administrator")
	r = _Report()
	doc = _pick_job_card(job_card)
	jc = doc.name
	qty = float(doc.for_quantity)
	a, b = _pick_employees(employee_a, employee_b, doc.company)
	good_a = float(int(qty * 0.4)) or 1.0
	scrap_a = 1.0
	good_b = float(int(qty * 0.3)) or 1.0

	print(f"\nJob Card {jc} | WO {doc.work_order} | op {doc.operation} | qty {qty} | machine {doc.workstation}")
	print(f"Workers: A={a}  B={b}\n")

	try:
		pre_used = 0.0
		if other_job_card:
			print("0. Same machine, different Job Cards, at the same time")
			other = _card(other_job_card)
			r.check("other Job Card is on the same workstation", other.workstation == doc.workstation,
				f"{other.workstation} vs {doc.workstation}")
			api.start(a, jc)
			api.start(b, other_job_card)
			r.check("both workers are running at once", bool(_entry(a, jc) and _entry(b, other_job_card)))
			# A finishes first, then B: B's time overlaps A's on the same machine. Standard ERPNext
			# raises an overlap error for this when the workstation capacity is 1.
			api.finish(a, _entry(a, jc)["row_name"], 1, 0, "")
			pre_used = 1.0
			ok, msg = _expect_error(lambda: api.finish(b, _entry(b, other_job_card)["row_name"], 1, 0, ""))
			r.check("B can finish although the machine was used at the same time", not ok, msg)

		print("1. Start: two workers on the same operation and machine")
		api.start(a, jc)
		api.start(b, jc)
		ea, eb = _entry(a, jc), _entry(b, jc)
		r.check("worker A has an open entry", bool(ea))
		r.check("worker B has an open entry (same operation, same machine)", bool(eb))
		row = frappe.get_doc("Job Card Time Log", ea["row_name"]) if ea else None
		r.check("row is marked from_tablet and has a machine", bool(row and row.from_tablet and row.workstation))
		r.check("start time was set automatically", bool(row and row.from_time and not row.to_time))

		print("2. One active entry per worker")
		ok, msg = _expect_error(lambda: api.start(a, jc), "already has active work")
		r.check("A cannot start a second entry", ok, msg)

		print("4. Finish rules")
		ok, msg = _expect_error(lambda: api.finish(a, ea["row_name"], 0, 0, ""), "enter the good")
		r.check("finish with no quantity is refused", ok, msg)
		ok, msg = _expect_error(lambda: api.finish(a, ea["row_name"], 1, 1, ""), "scrap reason")
		r.check("scrap without a reason is refused", ok, msg)
		ok, msg = _expect_error(lambda: api.finish(a, ea["row_name"], qty, 1, "Other"), "remaining")
		r.check("more than the remaining quantity is refused", ok, msg)
		ok, msg = _expect_error(lambda: api.finish(b, ea["row_name"], 1, 0, ""), "another worker")
		r.check("a worker cannot finish someone else's entry", ok, msg)

		reason = frappe.db.get_value("Scrap Reason", {"disabled": 0}, "name")
		r.check("a Scrap Reason exists", bool(reason), "install did not create the starter reasons")

		print("5. Workers finish their own entries")
		res_a = api.finish(a, ea["row_name"], good_a, scrap_a, reason)
		r.check("A finished", res_a["good"] == good_a and res_a["scrap"] == scrap_a, str(res_a))
		r.check(
			"remaining reflects good + scrap",
			abs(res_a["remaining"] - (qty - pre_used - good_a - scrap_a)) < 1e-6,
			str(res_a),
		)
		ok, msg = _expect_error(lambda: api.finish(b, eb["row_name"], qty, 0, ""), "remaining")
		r.check("B cannot overbook what A already used", ok, msg)
		res_b = api.finish(b, eb["row_name"], good_b, 0, "")
		r.check("B finished", res_b["good"] == good_b, str(res_b))
		ok, msg = _expect_error(lambda: api.finish(b, eb["row_name"], 1, 0, ""), "already finished")
		r.check("a finished entry cannot be finished twice", ok, msg)

		print("6. Everything is stored separately on the Job Card")
		d = _card(jc)
		mine = {}
		for x in d.time_logs:
			if x.from_tablet:
				mine[x.employee] = x  # last row per worker = the one from this run
		r.check("A's row: good/scrap/reason/end time", bool(
			mine.get(a) and mine[a].completed_qty == good_a and mine[a].scrap_qty == scrap_a
			and mine[a].scrap_reason == reason and mine[a].to_time), str(mine.get(a) and mine[a].as_dict()))
		r.check("B's row: good/no scrap/end time", bool(
			mine.get(b) and mine[b].completed_qty == good_b and not mine[b].scrap_qty and mine[b].to_time))
		r.check("duration calculated on both rows", all(x.time_in_mins is not None for x in mine.values()))
		r.check("total good = all workers' good (scrap not counted as good)",
			abs(d.total_completed_qty - (pre_used + good_a + good_b)) < 1e-6, str(d.total_completed_qty))
		r.check("header scrap = reported scrap, not unfinished quantity",
			abs(d.process_loss_qty - scrap_a) < 1e-6, str(d.process_loss_qty))
		r.check("draft Job Card is Work In Progress", d.status == "Work In Progress", d.status)

		left = qty - pre_used - good_a - good_b - scrap_a
		print("7. Open-operations list")
		ops = {o["job_card"]: o for o in api.list_open_operations()}
		r.check("operation still listed with the right remaining quantity",
			jc in ops and abs(ops[jc]["remaining"] - left) < 1e-6, str(ops.get(jc)))

		print("7b. Later operation (Sequence ID) while the earlier one is not submitted")
		later = frappe.get_all(
			"Job Card",
			filters={
				"work_order": doc.work_order,
				"docstatus": 0,
				"is_corrective_job_card": 0,
				"sequence_id": [">", doc.sequence_id or 0],
			},
			pluck="name",
			order_by="sequence_id asc",
			limit_page_length=1,
		)
		if later:
			try:
				api.start(a, later[0])
				api.cancel_start(a, _entry(a, later[0])["row_name"])
				r.check(f"start by mistake on {later[0]} can be cancelled", _entry(a, later[0]) is None)
				api.start(a, later[0])
				res = api.finish(a, _entry(a, later[0])["row_name"], 1, 0, "")
				r.check(f"worker can start and finish {later[0]} (later sequence)", res["good"] == 1, str(res))
			except Exception as exc:  # noqa: BLE001
				r.check(f"worker can start and finish {later[0]} (later sequence)", False, str(exc)[:200])
		else:
			print("  SKIP  no later-sequence Job Card on this Work Order")

		print("8. Start by mistake, then cancel")
		api.start(a, jc)
		r.check("A has a new open entry", bool(_entry(a, jc)))

		print("9. Submit is blocked while an entry is open")
		ok, msg = _expect_error(lambda: _card(jc).submit(), "open entry")
		r.check("submit refused with an open entry", ok, msg)

		api.cancel_start(a, _entry(a, jc)["row_name"])
		r.check("cancelled entry is gone", _entry(a, jc) is None)
		ok, msg = _expect_error(lambda: api.cancel_start(b, "no-such-row"), "no longer exists")
		r.check("cancel of a missing entry is refused", ok, msg)

		print("10. Submit with the remaining quantity left over")
		d = _card(jc)
		try:
			d.submit()
			d.reload()
			r.check("submitted by a supervisor", d.docstatus == 1)
			r.check("pending qty = quantity nobody worked on",
				abs(d.pending_qty - left) < 1e-6, str(d.pending_qty))
			r.check("completed + scrap + pending = quantity",
				abs(d.total_completed_qty + d.process_loss_qty + d.pending_qty - qty) < 1e-6)
		except Exception as exc:  # noqa: BLE001
			print(f"  NOTE  submit stopped by ERPNext: {frappe.as_unicode(str(exc))[:300]}")
			print("        (usually material transfer / operation sequence: see README 'Core configuration')")

	finally:
		if not keep:
			frappe.db.rollback()
			print("\n(rolled back: nothing was saved)")

	print(f"\n{r.passed} checks passed, {len(r.failed)} failed")
	for f in r.failed:
		print("  FAILED:", f)
	return {"passed": r.passed, "failed": r.failed}
