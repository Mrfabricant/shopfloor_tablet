# Shopfloor Tablet (ERPNext v16)

A simple, large-button screen for shared or personal tablets. Workers pick their name, start work
on an existing Work Order operation, and finish it with good and scrap quantity. Everything is
stored in standard ERPNext **Job Card time logs**; there is no separate transaction doctype.

Tested against: ERPNext 16.52.1 / Frappe 16.53.0 (code-reviewed against `version-16`; see TESTING.md for what has been run).

## What workers see
Open `/app/shopfloor-tablet` (bookmark it on the tablet).

1. **Name**: if the logged-in ERPNext user is linked to an Employee, that name is selected
   automatically. On a shared login a list of all active employees appears. A shared tablet returns
   to the name list after 90 seconds without touching it.
2. **Start**: tap an operation (grouped by Work Order, showing quantity left), check the machine
   (defaults to the operation's workstation, changeable) and press **START**. The start time is set
   automatically.
3. **Finish**: press **FINISH**, enter good quantity and scrap quantity (and a scrap reason if scrap
   is above zero). End time and duration are calculated automatically.
4. **Started by mistake?** "cancel" removes an entry that is still open and has no quantity.

No prices, rates or costs are shown anywhere on the tablet.

## Rules the server enforces
- Any number of workers can work on the same operation and machine at the same time; nothing is assigned in advance.
- One active entry per worker at a time.
- Finish only closes that worker's own entry. The rest of the quantity stays available to others.
- Good + scrap can never exceed the quantity still left on the operation (checked at the moment of
  Finish with a row lock, so two simultaneous finishes cannot both overbook).
- Scrap is stored separately and never counts as good output.
- A scrap reason (from the **Scrap Reason** list) is required whenever scrap is above zero.
- A Job Card with an open entry cannot be submitted.
- **Own name only:** a user whose login is linked to an Employee (Employee > User ID) and who has no
  supervisor role (Manufacturing User, Manufacturing Manager, System Manager) can only record work
  under that Employee. A shared login (not linked to any Employee) and supervisors can pick any name.
- **Two saves at the same moment:** when two workers start, finish or cancel on the same Job Card at
  exactly the same time, the database rejects one of them. The server rolls that one back and tries
  once more, so it is re-checked against the other worker's quantity. If it collides again the
  worker sees "Someone just saved this operation at the same moment. Please try again."

## What is added to ERPNext
| Item | Purpose |
|---|---|
| Custom fields on **Job Card Time Log**: `workstation` (Machine), `scrap_qty`, `scrap_reason`, `from_tablet` | Per-entry machine, scrap and source |
| Doctype **Scrap Reason** | Supervisor-maintained list (starter list is created on install) |
| Role **Shop Floor Worker** | Can open the tablet page only |
| Page **Shopfloor Tablet** | The worker screen |
| Reports **Operation Progress**, **Worker Time Entries** | Supervisor views in the desk |
| Job Card class override | See below |

### Job Card behaviour for tablet rows (`overrides/job_card.py`)
1. **Machine overlap:** ERPNext rejects a time row when another Job Card on the same workstation overlaps and the workstation capacity is used up. For tablet rows only that machine check is skipped (the "one employee cannot work twice at once" check stays).
2. **Scrap:** ERPNext sets process loss to *quantity - completed - pending* on every draft save, which would count unfinished work as scrap. For cards worked on the tablet, process loss = the scrap the workers reported.
3. **Operation sequence:** ERPNext v16 always fills a Sequence ID on Work Order operations; when the
   BOM sets none, it uses the BOM row order (1, 2, 3...). Standard ERPNext then blocks an operation
   until the previous operation's Job Card has submitted quantity. For Job Cards that have tablet
   entries this check is skipped (on every save, including submit), so workers can run operations in
   parallel. The save that removes the last tablet entry (a cancelled start) is skipped too.
   Cards with only desk entries keep the standard check.
4. **Submit:** the supervisor submits the Job Card. At submit, `pending_qty` is set to the quantity nobody worked on, so ERPNext's own rule *completed + scrap + pending = quantity* holds. Open entries block the submit.

If ERPNext changes these methods in a future version, re-test after upgrading.

## Supervisor workflow (desk)
- **Operation Progress** report: per Job Card - quantity, good, scrap, remaining, open entries, workers, minutes. Open entries older than the chosen hours (default 12) are shown in red.
- **Worker Time Entries** report: one row per worker entry - worker, machine, start, end, minutes, good, scrap, reason, tablet/desk.
- **Forgot to press Finish / wrong quantity:** open the Job Card, correct the time-log row (To Time, Completed Qty, Scrap Qty, Scrap Reason) and save. Duration is recalculated. Workers cannot edit finished entries on the tablet.
- **Submit** the Job Card when the work is reviewed. Supervisors need the **Manufacturing User**
  role for this (it carries the Work Order permission ERPNext checks at submit); Manufacturing
  Manager alone is not enough.

## Core configuration (done in ERPNext, not by this app)
- Items, BOMs **with operations** (each operation with a workstation), Operations, Workstations.
- Work Orders created and **submitted**: this creates the draft Job Cards the tablet works on.
- Employees: status Active. Set **User ID** on the Employee to enable auto-select for a worker's own login.
- Users: give tablet users the **Shop Floor Worker** role. For a shared tablet use one user that is not linked to an Employee. Supervisors: Manufacturing User (plus Manufacturing Manager if wanted).
- Material transfer: ERPNext needs materials transferred to WIP before a Job Card can be **submitted** (or "Skip Material Transfer" on the Work Order). Workers can record work before that.
- **Sequence ID**: filled by ERPNext from the BOM row order when left empty. The tablet skips the sequence check for cards that have tablet entries (see above).
- System time zone set correctly (start/end times use the server clock).

## Install (bench)
```bash
cd ~/frappe-bench
bench get-app /path/to/shopfloor_tablet      # or your git URL
bench --site <site> install-app shopfloor_tablet
bench --site <site> migrate
bench restart        # or restart `bench start`
```
Installing runs `after_install`/`after_migrate`, which create the role, the custom fields and the starter scrap reasons. Both are safe to repeat.

## Known limits
- Costing still uses ERPNext's own operation/workstation rate. The machine chosen by the worker is stored for traceability, not costing.
- Only draft, non-corrective, non-subcontracted Job Cards that are not On Hold are offered.
- English only. No PIN: on a shared login anyone can pick any name (agreed with the client). Personal logins are limited to their own name.
- Uninstalling the app leaves the custom fields on Job Card Time Log (delete them in Customize Form if wanted).

## Source layout
```
shopfloor_tablet/
  api.py                 whitelisted methods used by the page
  utils.py               pure quantity rules (unit-tested without a bench)
  overrides/job_card.py  Job Card class override
  setup/install.py       role, custom fields, starter scrap reasons
  patches/               pre-model-sync patch (module + role)
  shopfloor_tablet/      module: Scrap Reason doctype, page, two reports
  tests/                 unit tests + scenario.py (end-to-end on a real site)
```
