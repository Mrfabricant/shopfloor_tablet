# Test brief (for Claude Code or a human)

Status 2026-10-28 (after the break / scrap / replacement / issue / worker-switch changes): steps 1,
3, 3b and 4 have been run on `mark.local` and pass. Step 5a (HTTP checks) was updated but **not run**
(needs the test users' password). The browser click-through in step 5b has not been run.

Site: `mark.local` in `~/mark-prod-v16` (WSL distro `erpnext16`), ERPNext 16.52.1, Frappe 16.53.0.

## 1. Install and migrate
```bash
cd ~/mark-prod-v16
bench --site mark.local migrate
bench --site mark.local clear-cache
```
Verify (and report any failure with the full traceback):
- `Custom Field` rows exist for `Job Card Time Log`: `workstation`, `scrap_qty`, `scrap_reason`, `from_tablet`,
  `entry_type`, `replacement_reason`, `break_minutes`, `net_minutes`, `issue_reason`, `issue_minutes`, `issue_note`.
- `Shopfloor Tablet Settings`: break 10:30:00-11:00:00, Europe/Zagreb, Replacement Operation "Replacement Work"
  (an Operation with `is_corrective_operation = 1`). Existing time logs have `entry_type` and break/net minutes.
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
(`test_override_logic` skips itself when frappe is importable; run it with a plain `python3` outside the
bench env: `python3 -m unittest shopfloor_tablet.tests.test_utils shopfloor_tablet.tests.test_override_logic`.)

## 3b. Page script (Node, no browser)
```bash
cd ~/mark-prod-v16/apps/shopfloor_tablet
node --check shopfloor_tablet/shopfloor_tablet/page/shopfloor_tablet/shopfloor_tablet.js
node --test shopfloor_tablet/tests/js/*.test.js
```
Loads the real page script with a stub frappe/jQuery and delays answers for worker A while worker B is
selected (get_state, start, finish, cancel_start, the 30 s refresh, idle return, logout).

## 4. End-to-end scenario (rolls back, keeps no data)
```bash
cd ~/mark-prod-v16
bench --site mark.local execute shopfloor_tablet.tests.scenario.run
```
It creates its own Work Order (qty 10, skip material transfer) from the BOM of an existing Work Order
and covers: finish rules, 7 good + 2 scrap -> 3 left, 0/0 with an issue reason, issue minutes above net
refused, break/net on tablet and desk rows, submit with 10 good / 2 scrap (pending 0, process loss 0,
Work Order operation 10), replacement work (one shared corrective card, no good/scrap, submits,
source quantities unchanged, empty card deleted on cancel), both reports, and the own-name rule as
`worker1@example.com`. Every line should say PASS (2026-10-28: 55 passed, 0 failed).
Pay special attention to:
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
- Progress bar shows good + left against planned; scrap appears separately ("Scrap 2 (made again)").
- Finish dialog: "Working time without break" is shown; issue minutes above it are refused; 0 / 0 only with an issue.
- Replacement work tab: Work Order -> operation (also completed ones) -> machine -> START REPLACEMENT; the active
  card says "Replacement work"; Finish asks only for a reason and a note.
- Shared tablet: pick worker A, immediately Change worker -> B: nothing of A appears on B's screen.
- No prices/rates visible anywhere on the page or in the network responses.
- Reports render without errors; an open entry older than 12 h (set `from_time` back in the DB) shows red.
- Supervisor (Manufacturing Manager): open a Job Card, edit a tablet row's To Time / quantities, save, submit.

## 6. Report
List what passed, what you fixed (with diffs), and anything still doubtful.
