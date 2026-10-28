"""Tablet API over real HTTP, as real users, with real concurrent requests.

Unlike scenario.py this commits data (it goes through the web server), so every time-log row it
creates is removed again at the end through `cleanup` (run with bench execute).

Needs a running bench (`bench start`) and three users with the same password:
	worker1@example.com    Shop Floor Worker only, Employee > User ID set on WORKER_A
	shared@example.com     Shop Floor Worker only, not linked to an Employee
	supervisor@example.com Manufacturing User + Manufacturing Manager, not linked

	SFT_TEST_PASSWORD=... ~/mark-prod-v16/env/bin/python -m shopfloor_tablet.tests.http_checks \\
		--site mark.local --bench ~/mark-prod-v16 --fits PO-JOB00001 PO-JOB00002 --overbook PO-JOB00003 PO-JOB00004

--fits cards: two workers finish at the same moment with quantities that fit -> both must succeed.
--overbook cards: two workers finish at the same moment with too much good -> one succeeds, the
other is refused with a readable message. Never a raw database error, never more good than the card
quantity (scrap does not use up quantity).

Replacement work is checked as worker1 (Shop Floor Worker only) and with two workers starting at
the same moment on one operation: they must share ONE draft corrective Job Card.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import threading

WORKER_A = "HR-EMP-00001"  # linked to worker1@example.com
WORKER_B = "HR-EMP-00002"
WORKER_C = "HR-EMP-00003"

RAW_DB_ERROR = re.compile(r"record has changed|deadlock|QueryDeadlockError|pymysql|OperationalError|\(10\d\d,", re.I)
PRICE = re.compile(r"rate|cost|price|amount|valuation", re.I)


class Checks:
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


class Client:
	def __init__(self, base, host, user, password):
		import requests

		self.user = user
		self.base = base
		self.s = requests.Session()
		self.s.headers["Host"] = host
		r = self.s.post(f"{base}/api/method/login", data={"usr": user, "pwd": password})
		r.raise_for_status()
		# loading the desk creates the CSRF token the browser sends with every POST
		html = self.s.get(f"{base}/app/shopfloor-tablet").text
		tok = re.search(r"csrf_token\W+([0-9a-f]{20,})", html)
		if tok:
			self.s.headers["X-Frappe-CSRF-Token"] = tok.group(1)

	def get(self, path, **params):
		return self.s.get(self.base + path, params=params)

	def call(self, method, http="POST", **kw):
		url = f"{self.base}/api/method/shopfloor_tablet.api.{method}"
		r = self.s.post(url, data=kw) if http == "POST" else self.s.get(url, params=kw)
		try:
			body = r.json()
		except ValueError:
			body = {"raw": r.text[:300]}
		return r.status_code, body


def msg(body):
	out = []
	for m in json.loads(body.get("_server_messages") or "[]"):
		out.append(json.loads(m).get("message", ""))
	text = " ".join(out) or str(body.get("exception") or body.get("raw") or "")
	return re.sub(r"<[^>]+>", "", text)[:250]


def active_row(body):
	rows = (body.get("message") or {}).get("active") or []
	return rows[0]["row_name"] if rows else None


def run_together(*jobs):
	"""Fire the calls at the same moment from separate threads (separate HTTP connections)."""
	out = [None] * len(jobs)
	gate = threading.Barrier(len(jobs))

	def go(i, fn):
		gate.wait()
		out[i] = fn()

	threads = [threading.Thread(target=go, args=(i, fn)) for i, fn in enumerate(jobs)]
	for t in threads:
		t.start()
	for t in threads:
		t.join()
	return out


def card_totals(sup, job_card):
	r = sup.get(
		"/api/method/frappe.desk.query_report.run",
		report_name="Operation Progress",
		filters=json.dumps({"scope": "All"}),
	)
	rows = r.json()["message"]["result"]
	return next((x for x in rows if isinstance(x, dict) and x.get("job_card") == job_card), None)


def main():
	ap = argparse.ArgumentParser()
	ap.add_argument("--site", default="mark.local")
	ap.add_argument("--url", default="http://127.0.0.1:8000")
	ap.add_argument("--bench", default=os.path.expanduser("~/mark-prod-v16"))
	ap.add_argument("--fits", nargs="*", default=[])
	ap.add_argument("--overbook", nargs="*", default=[])
	ap.add_argument("--keep", action="store_true", help="do not remove the rows created")
	args = ap.parse_args()

	password = os.environ.get("SFT_TEST_PASSWORD")
	if not password:
		sys.exit("Set SFT_TEST_PASSWORD")

	c = Checks()
	created = []
	cards = args.fits + args.overbook
	jc = cards[0]

	def track(body):
		row = active_row(body)
		if row:
			created.append(row)
		return row

	w = Client(args.url, args.site, "worker1@example.com", password)
	sh = Client(args.url, args.site, "shared@example.com", password)
	sup = Client(args.url, args.site, "supervisor@example.com", password)

	try:
		print("worker1 (Shop Floor Worker, linked to", WORKER_A + ")")
		st, b = w.call("get_context")
		ctx = b.get("message") or {}
		c.check("own employee auto-selected", (ctx.get("employee") or {}).get("name") == WORKER_A, ctx.get("employee"))
		c.check("name list holds only the own name", [x["name"] for x in ctx.get("workers", [])] == [WORKER_A], ctx.get("workers"))
		c.check("page loads", w.get("/api/method/frappe.desk.desk_page.getpage", name="shopfloor-tablet").status_code == 200)
		c.check("no Job Card access over REST", w.get(f"/api/resource/Job Card/{jc}").status_code == 403)
		c.check("no supervisor report", w.get("/api/method/frappe.desk.query_report.run", report_name="Operation Progress").status_code == 403)
		st, b = w.call("start", http="GET", employee=WORKER_A, job_card=jc, machine="")
		c.check("start over GET refused", st != 200, st)

		print("own-name rule")
		st, b = w.call("get_state", employee=WORKER_B)
		c.check("worker1 get_state as B -> permission error", st == 403 and "own name" in msg(b), f"{st} {msg(b)}")
		st, b = w.call("start", employee=WORKER_B, job_card=jc)
		track(b)
		c.check("worker1 start as B -> permission error", st == 403 and "own name" in msg(b), f"{st} {msg(b)}")
		st, b = sh.call("start", employee=WORKER_B, job_card=jc)
		row_b = track(b)
		c.check("shared starts as B", st == 200 and row_b, msg(b))
		st, b = w.call("finish", employee=WORKER_B, row_name=row_b, good_qty=1)
		c.check("worker1 finish as B -> permission error", st == 403 and "own name" in msg(b), f"{st} {msg(b)}")
		st, b = sh.call("cancel_start", employee=WORKER_B, row_name=row_b)
		c.check("shared cancels B's start", st == 200, msg(b))
		st, b = sh.call("get_state", employee=WORKER_C)
		c.check("shared can use any employee (C)", st == 200, msg(b))
		st, b = sup.call("get_context")
		c.check("supervisor gets the full name list", len((b.get("message") or {}).get("workers", [])) >= 3, msg(b))
		st, b = sup.call("get_state", employee=WORKER_C)
		c.check("supervisor can use any employee (C)", st == 200, msg(b))

		print("start / finish flow")
		st, b = w.call("get_state", employee=WORKER_A)
		ops = {o["job_card"]: o for o in (b.get("message") or {}).get("operations", [])}
		c.check("all test cards offered (incl. later sequence)", all(x in ops for x in cards), list(ops))
		c.check("no price/rate/cost keys", not any(PRICE.search(k) for o in ops.values() for k in o), "")
		start_left = ops.get(jc, {}).get("remaining", 0)
		start_left_good = ops.get(jc, {}).get("good", 0)
		st, b = w.call("start", employee=WORKER_A, job_card=jc, machine="SFT-WS-CUT")
		row_a = track(b)
		c.check("worker1 starts own work", st == 200 and row_a, msg(b))
		st, b = sh.call("get_state", employee=WORKER_B)
		op = next((o for o in b["message"]["operations"] if o["job_card"] == jc), {})
		c.check("'Working now' shows worker1 to others", len(op.get("working_now", [])) == 1, op.get("working_now"))
		st, b = w.call("finish", employee=WORKER_A, row_name=row_a, good_qty=1, scrap_qty=1, scrap_reason="")
		c.check("scrap without reason refused", st != 200 and "reason" in msg(b).lower(), msg(b))
		st, b = w.call("finish", employee=WORKER_A, row_name=row_a, good_qty=start_left + 1)
		c.check("over remaining refused", st != 200 and "remaining" in msg(b).lower(), msg(b))
		st, b = w.call("finish", employee=WORKER_A, row_name=row_a, good_qty=0, scrap_qty=0)
		c.check("0 / 0 without issue reason refused", st != 200 and "issue reason" in msg(b).lower(), msg(b))
		st, b = w.call("finish", employee=WORKER_A, row_name=row_a, good_qty=1, issue_reason="Machine setup", issue_minutes=600)
		c.check("issue minutes above net time refused", st != 200 and "break not included" in msg(b).lower(), msg(b))
		st, b = w.call("get_entry_time", employee=WORKER_A, row_name=row_a)
		c.check("live entry time for the finish dialog", st == 200 and "net_minutes" in (b.get("message") or {}), msg(b))
		st, b = w.call("finish", employee=WORKER_A, row_name=row_a, good_qty=1, scrap_qty=start_left + 5, scrap_reason="Wire break")
		m = b.get("message") or {}
		c.check("valid finish; scrap above remaining allowed and not subtracted", st == 200 and m.get("remaining") == start_left - 1, f"{msg(b)} {m}")
		st, b = w.call("start", employee=WORKER_A, job_card=jc)
		row = track(b)
		st, b = w.call("finish", employee=WORKER_A, row_name=row, good_qty=0, scrap_qty=0, issue_reason="Waiting for materials", issue_note="http check")
		c.check("0 / 0 with an issue reason is saved", st == 200 and (b.get("message") or {}).get("good") == 0, msg(b))

		print("later operation (Sequence ID 2) as a worker")
		later = args.fits[1] if len(args.fits) > 1 else None
		if later:
			st, b = w.call("start", employee=WORKER_A, job_card=later)
			row = track(b)
			c.check(f"worker1 starts {later} before the earlier operation is submitted", st == 200 and row, msg(b))
			st, b = w.call("finish", employee=WORKER_A, row_name=row, good_qty=1)
			c.check(f"worker1 finishes {later}", st == 200, msg(b))

		print("replacement work")
		st, b = w.call("list_replacement_work_orders")
		wos = [x["work_order"] for x in (b.get("message") or [])]
		c.check("replacement work orders listed", st == 200 and wos, msg(b))
		st, b = w.call("list_replacement_operations", work_order=wos[0] if wos else "")
		ops_r = b.get("message") or []
		c.check("replacement operations listed, no prices", st == 200 and ops_r and not any(PRICE.search(k) for o in ops_r for k in o), msg(b))
		st, b = w.call("start_replacement", employee=WORKER_A, job_card=jc)
		row = track(b)
		active = (b.get("message") or {}).get("active") or [{}]
		c.check("worker1 (Shop Floor Worker only) starts replacement", st == 200 and active[0].get("entry_type") == "Replacement", msg(b))
		st, b = w.call("finish", employee=WORKER_A, row_name=row, good_qty=1)
		c.check("normal finish refused for replacement", st != 200 and "replacement" in msg(b).lower(), msg(b))
		st, b = w.call("finish_replacement", employee=WORKER_A, row_name=row, reason="Wire break", note="http check")
		c.check("worker1 finishes replacement", st == 200, msg(b))
		r1, r2 = run_together(
			lambda: sh.call("start_replacement", employee=WORKER_B, job_card=jc),
			lambda: sh.call("start_replacement", employee=WORKER_C, job_card=jc),
		)
		rows = [track(r1[1]), track(r2[1])]
		cards_r = {((x[1].get("message") or {}).get("job_card")) for x in (r1, r2)}
		c.check("two replacement starts at the same moment both succeed", r1[0] == r2[0] == 200, [msg(x[1]) for x in (r1, r2)])
		c.check("... and share ONE corrective Job Card", len(cards_r) == 1, cards_r)
		for emp, row in zip((WORKER_B, WORKER_C), rows):
			if row:
				sh.call("finish_replacement", employee=emp, row_name=row, reason="Other")
		after = card_totals(sup, jc)
		c.check("replacement adds no good / scrap to the source card", after and after["good"] == start_left_good + 1, after)

		print("collisions: two workers on one Job Card at the same moment")
		for card in args.fits + args.overbook:
			fits = card in args.fits
			before = card_totals(sup, card)
			left = before["remaining"]
			qty = max(int(left * 0.4), 1) if fits else int(left * 0.6) + 1
			r1, r2 = run_together(
				lambda: sh.call("start", employee=WORKER_B, job_card=card),
				lambda: sh.call("start", employee=WORKER_C, job_card=card),
			)
			rows = [track(r1[1]), track(r2[1])]
			starts_ok = all(st == 200 for st, _ in (r1, r2))
			c.check(f"{card}: two starts at the same moment both succeed", starts_ok, [msg(x[1]) for x in (r1, r2)])
			if not starts_ok:
				continue
			res = run_together(
				lambda: sh.call("finish", employee=WORKER_B, row_name=rows[0], good_qty=qty),
				lambda: sh.call("finish", employee=WORKER_C, row_name=rows[1], good_qty=qty),
			)
			texts = [msg(b) for _, b in res]
			codes = [st for st, _ in res]
			c.check(f"{card}: no raw database error / no 500", 500 not in codes and not any(RAW_DB_ERROR.search(t) for t in texts), f"{codes} {texts}")
			ok = codes.count(200)
			if fits:
				c.check(f"{card}: {qty}+{qty} of {left} -> both finishes saved", ok == 2, f"{codes} {texts}")
			else:
				refused = [t for st, t in zip(codes, texts) if st != 200]
				readable = all("remaining" in t.lower() or "same moment" in t.lower() for t in refused)
				c.check(f"{card}: {qty}+{qty} of {left} -> exactly one saved, other refused readably", ok == 1 and readable, f"{codes} {texts}")
			# the refused worker's entry is still open: cancel it like the worker would
			for (st, _), emp, row in zip(res, (WORKER_B, WORKER_C), rows):
				if st != 200:
					sh.call("cancel_start", employee=emp, row_name=row)
			after = card_totals(sup, card)
			c.check(
				f"{card}: good never above the card quantity",
				after["good"] <= after["required"] + 1e-9 and after["open_entries"] == before["open_entries"],
				after,
			)
	finally:
		if created and not args.keep:
			print(f"\ncleanup: removing {len(created)} test rows")
			cmd = ["bench", "--site", args.site, "execute", "shopfloor_tablet.tests.http_checks.cleanup",
				"--kwargs", repr({"rows": created})]
			out = subprocess.run(cmd, cwd=args.bench, capture_output=True, text=True)
			print("  " + (out.stdout.strip().splitlines() or [out.stderr.strip()[-300:]])[-1])

	print(f"\n{c.passed} checks passed, {len(c.failed)} failed")
	for f in c.failed:
		print("  FAILED:", f)
	sys.exit(1 if c.failed else 0)


def cleanup(rows):
	"""Remove the time-log rows this script created (bench execute). Only draft Job Cards."""
	import frappe

	frappe.set_user("Administrator")
	parents = set(frappe.get_all("Job Card Time Log", filters={"name": ["in", rows], "parentfield": "time_logs"}, pluck="parent"))
	for name in parents:
		doc = frappe.get_doc("Job Card", name)
		if doc.docstatus != 0:
			continue
		doc.set("time_logs", [r for r in doc.time_logs if r.name not in rows])
		if doc.is_corrective_job_card and not doc.time_logs:
			frappe.delete_doc("Job Card", name, ignore_permissions=True, force=True)
			continue
		employees = {r.employee for r in doc.time_logs}
		doc.set("employee", [e for e in doc.get("employee") if e.employee in employees])
		if not doc.time_logs:
			doc.actual_start_date = None
			doc.actual_end_date = None
		doc.save(ignore_permissions=True)
	frappe.db.commit()
	left = frappe.db.count("Job Card Time Log", {"name": ["in", rows]})
	print(f"removed rows from {len(parents)} Job Cards, {left} left")


if __name__ == "__main__":
	main()
