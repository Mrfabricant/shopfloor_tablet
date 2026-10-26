# Test brief (for Claude Code or a human)

Steps 1-4 and the HTTP part of step 5 have been run on `mark.local` (2026-10-27) and pass. The
browser click-through in step 5 has not been run yet.

Site: `mark.local` in `~/mark-prod-v16` (WSL distro `erpnext16`), ERPNext 16.52.1, Frappe 16.53.0.

## 1. Install and migrate
```bash
cd ~/mark-prod-v16
bench --site mark.local migrate
bench --site mark.local clear-cache
```
Verify (and report any failure with the full traceback):
- `Custom Field` rows exist for `Job Card Time Log`: `workstation`, `scrap_qty`, `scrap_reason`, `from_tablet`.
- `Role` "Shop Floor Worker", `DocType` "Scrap Reason" with 8 starter records, `Page` "shopfloor-tablet",
  `Report` "Operation Progress" and "Worker Time Entries".
- `frappe.get_hooks("override_doctype_class")` resolves, and `frappe.get_doc("Job Card", <any>)` is a `ShopfloorJobCard`.
- `bench --site mark.local console`: `from shopfloor_tablet.api import get_context; get_context()` works as Administrator.

## 2. Sample data (if the site has none)
One finished item, one raw material, 2 Workstations (production capacity 1), 2 Operations, a BOM
"With Operations" (leave Sequence ID empty), a Work Order for qty 10 (use the option to skip
material transfer, or transfer materials), submit it. Check that draft Job Cards were created.

## 3. Unit tests
```bash
cd ~/mark-prod-v16/apps/shopfloor_tablet
python -m unittest shopfloor_tablet.tests.test_utils -v
```
(`test_override_logic` skips itself when frappe is importable.)

## 4. End-to-end scenario (rolls back, keeps no data)
```bash
cd ~/mark-prod-v16
bench --site mark.local execute shopfloor_tablet.tests.scenario.run
# with a second Job Card on the SAME workstation (proves two workers can use one machine on different orders):
bench --site mark.local execute shopfloor_tablet.tests.scenario.run --kwargs "{'other_job_card': 'PO-JOB-0000X'}"
```
Every line should say PASS. For each FAIL decide whether the app or the scenario is wrong and fix it.
Pay special attention to:
- the finish-time machine-overlap check (step 0) - standard ERPNext should reject it, the app must not;
- header `process_loss_qty` after saves, and `pending_qty` after submit (step 10);
- whether `frappe.get_doc(..., for_update=True)` + `save(ignore_permissions=True)` works for a user that only has the Shop Floor Worker role (repeat a start/finish as such a user via the UI, step 5).

## 5a. HTTP checks as real users, with real concurrent requests (commits data, then removes its rows)
Needs `bench start` running and the users below (same password for all three, plus
`supervisor@example.com` with Manufacturing User + Manufacturing Manager, not linked to an Employee).
```bash
cd ~/mark-prod-v16/apps/shopfloor_tablet
SFT_TEST_PASSWORD=... ../../env/bin/python -m shopfloor_tablet.tests.http_checks --site mark.local \
	--fits PO-JOB00001 PO-JOB00002 --overbook PO-JOB00003 PO-JOB00004
```
`--fits`/`--overbook` take draft Job Cards (the second `--fits` card should be a later operation of the
same Work Order). Save collisions that were retried are logged in `sites/mark.local/logs/shopfloor_tablet.log`.

## 5b. UI (Claude in Chrome or manual) at `/app/shopfloor-tablet`
- Create user `worker1@example.com` (role: Shop Floor Worker only) linked to Employee A; and `shared@example.com`
  (same role, linked to no Employee).
- worker1: name auto-selected; start -> timer runs; reload page -> still active; Finish with scrap but no reason -> blocked;
  Finish over remaining -> blocked; valid Finish -> green message and the operation shows less remaining.
- shared: name list appears; search works; pick a name; leave 90 s idle -> back to the name list.
- Two browsers: worker A and worker B start the same operation; both finish; quantities add up; the card shows
  "Working now" for the other worker.
- No prices/rates visible anywhere on the page or in the network responses.
- Reports render without errors; an open entry older than 12 h (set `from_time` back in the DB) shows red.
- Supervisor (Manufacturing Manager): open a Job Card, edit a tablet row's To Time / quantities, save, submit.

## 6. Report
List what passed, what you fixed (with diffs), and anything still doubtful.
