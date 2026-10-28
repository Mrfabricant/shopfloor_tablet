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
   is above zero). End time and duration are calculated automatically. Optionally (under "Problem
   during this work?") choose an issue (Machine setup, Machine problem, Waiting for materials, Other),
   the minutes lost and a note. The dialog shows the entry's working time without the break, which
   is the most the issue minutes can be.
4. **Nothing made?** Finishing with good 0 and scrap 0 is allowed only when an issue is chosen. The
   time is kept and the row is stored normally.
5. **Started by mistake?** "cancel" removes an entry that is still open and has no quantity.
6. **Replacement work** (second tab): time spent redoing work on an earlier operation, also one that
   is already completed or submitted. Pick the Work Order, then the operation, the machine, and press
   **START REPLACEMENT**. Finish records the time, a reason (from the Scrap Reason list) and an
   optional note. It never counts as good or scrap.

No prices, rates or costs are shown anywhere on the tablet.

## Rules the server enforces
- Any number of workers can work on the same operation and machine at the same time; nothing is assigned in advance.
- One active entry per worker at a time.
- Finish only closes that worker's own entry. The rest of the quantity stays available to others.
- **Remaining = planned (Qty To Make) - good pieces of finished entries.** Scrap does not reduce it:
  scrapped pieces still have to be made (10 planned, 7 good, 2 scrap -> 3 left).
- Good can never exceed the quantity still left on the operation (checked at the moment of Finish
  with a row lock, so two simultaneous finishes cannot both overbook). Scrap has no upper limit.
- Scrap is stored separately (per entry) and never counts as good output.
- Issue minutes must be between 0 and the entry's net working minutes (break excluded). They never
  change the recorded time.
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
| Custom fields on **Job Card Time Log**: `entry_type` (Normal / Replacement), `replacement_reason`, `break_minutes`, `net_minutes` (read-only), `issue_reason`, `issue_minutes`, `issue_note` | Replacement work, break analysis, issues |
| Doctype **Scrap Reason** | Supervisor-maintained list (starter list is created on install); also the replacement reasons |
| Single doctype **Shopfloor Tablet Settings** | Break start/end (default 10:30-11:00), break time zone (default Europe/Zagreb), replacement operation. System Manager / Manufacturing Manager can edit |
| Operation **Replacement Work** (`is_corrective_operation = 1`) | Operation of the corrective Job Cards for replacement work |
| Role **Shop Floor Worker** | Can open the tablet page only |
| Page **Shopfloor Tablet** | The worker screen |
| Reports **Operation Progress**, **Worker Time Entries** | Supervisor views in the desk |
| Job Card class override | See below |

### Job Card behaviour for tablet rows (`overrides/job_card.py`)
1. **Machine overlap:** ERPNext rejects a time row when another Job Card on the same workstation overlaps and the workstation capacity is used up. For tablet rows only that machine check is skipped (the "one employee cannot work twice at once" check stays).
2. **Scrap:** ERPNext sets process loss to *quantity - completed - pending* on every draft save, which would count unfinished work as scrap. For cards worked on the tablet the header `process_loss_qty` is **0**: scrap lives in the time-log rows (`scrap_qty`, `scrap_reason`) and in the reports, because scrapped pieces are made again.
3. **Operation sequence:** ERPNext v16 always fills a Sequence ID on Work Order operations; when the
   BOM sets none, it uses the BOM row order (1, 2, 3...). Standard ERPNext then blocks an operation
   until the previous operation's Job Card has submitted quantity. For Job Cards that have tablet
   entries this check is skipped (on every save, including submit), so workers can run operations in
   parallel. The save that removes the last tablet entry (a cancelled start) is skipped too.
   Cards with only desk entries keep the standard check.
4. **Submit:** the supervisor submits the Job Card. At submit, `process_loss_qty = 0` and `pending_qty = for_quantity - total_completed_qty`, so ERPNext's own rule *completed + process loss + pending = quantity* holds. Example: 10 planned, 7 good + 2 scrap, then 3 more good -> 10 good, 2 scrap: the card submits with pending 0 and the Work Order operation shows 10 completed. Open entries block the submit.
5. **Break and net minutes (all rows, tablet and desk edits):** on every save, for each finished row the part of the entry that falls in the daily break is stored in `break_minutes` and `time_in_mins - break_minutes` (never below 0) in `net_minutes`. Timestamps are taken as system-time-zone wall clock, converted to the break time zone, and intersected with that day's break window for every calendar day the entry touches (DST, entries over midnight and multi-day entries are handled). `from_time`, `to_time` and ERPNext's `time_in_mins` are never changed. Existing rows were filled by a patch. `entry_type` is set from the card (corrective card = Replacement). Issue minutes above the net minutes are refused, also for desk edits.

### Scrap and material consumption
Because scrap is not process loss, the Work Order operation only shows good pieces, and the
Manufacture stock entry consumes raw material per BOM for the good quantity. Material that went
into scrapped pieces is **not** consumed automatically. If it must be booked, the supervisor adds it
to the Manufacture entry (extra raw material quantity) or books a Material Issue / scrap entry; the
Worker Time Entries and Operation Progress reports show the scrap quantity per operation and reason.

### Replacement work (ERPNext corrective Job Card)
- Uses ERPNext's own `make_corrective_job_card`: the card has `is_corrective_job_card = 1`,
  `for_job_card` = the operation's Job Card, `for_operation` = its operation, operation = the
  **Replacement Operation** from the settings. ERPNext excludes corrective cards from every
  operation/Work Order quantity, from the sequence check and from the material-transfer check.
- One draft corrective card per source Job Card is created or reused (the source card is row-locked,
  so two workers starting at the same moment get the same card). Several workers add rows to it.
  When the last entry on an empty corrective card is cancelled, the card is deleted.
- Allowed Work Order status: **Not Started, In Process, Completed** (Not Started is included
  because a Work Order with skipped material transfer stays there until the first Manufacture
  entry). Stopped, Closed and Cancelled Work Orders are refused (ERPNext also refuses changes to
  cards of Stopped/Closed orders). Source cards may be draft or submitted.
- **How the corrective card submits without touching the source quantities:** ERPNext would require
  *completed + loss + pending = quantity* and its own example fills the corrective rows with the
  source quantity. The tablet instead sets the corrective card's **Qty To Make to 0** and clears its
  items: replacement makes no pieces, so 0 = 0 holds at submit, rows carry no good and no scrap,
  and nothing is added to the source operation or the Work Order. Material for replacement work is
  not planned on this card (book it on the Manufacture entry or a Material Issue if needed).
- ERPNext's `make_corrective_job_card` checks the caller's Job Card read/create permission, which
  workers do not have. After the tablet's own role and own-name checks, the mapping alone runs as
  Administrator and the card is inserted as the worker.
- **Costing:** Manufacturing Settings > "Add Corrective Operation Cost in Finished Good Valuation"
  is left as it is. When it is on, ERPNext adds *time x hour rate* of submitted corrective cards to
  the Work Order's operating cost (hour rate is copied from the source card); when it is off,
  corrective cards add no cost. The app does not change this setting.

If ERPNext changes these methods in a future version, re-test after upgrading.

## Supervisor workflow (desk)
- **Operation Progress** report: per Job Card - quantity, good, scrap, remaining (planned - good), open entries, workers, minutes, break minutes, net minutes, issue minutes, productive minutes (net - issue), replacement entries and replacement minutes (net). Open entries are included with live values up to now. A total row sums the columns. Open entries older than the chosen hours (default 12) are shown in red.
- **Worker Time Entries** report: one row per worker entry - worker, operation (for replacement: the operation it was done for), entry type, Job Card / For Job Card, machine, start, end, minutes, break, net, issue reason, issue minutes, productive minutes, replacement minutes, note, good, scrap, reasons, tablet/desk. Open entries show live values. Filter by entry type.
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
- **Shopfloor Tablet Settings**: check the break window and time zone. The Replacement Operation is
  created and filled on install.
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
Installing runs `after_install`/`after_migrate`, which create the role, the custom fields, the starter scrap reasons, the Replacement Work operation and the settings (empty values only). All of it is safe to repeat. The patch `backfill_break_and_entry_type` fills break/net minutes and entry type on existing rows once.

## Known limits
- Costing still uses ERPNext's own operation/workstation rate. The machine chosen by the worker is stored for traceability, not costing.
- Only draft, non-corrective, non-subcontracted Job Cards that are not On Hold are offered for normal work.
- Break minutes are for analysis only. Costing and ERPNext's `time_in_mins` still use the full recorded time.
- Switching workers on a shared tablet: answers to requests made for the previous worker (including the 30 s refresh) are discarded, so they cannot show up for the next worker.
- English only. No PIN: on a shared login anyone can pick any name (agreed with the client). Personal logins are limited to their own name.
- Uninstalling the app leaves the custom fields on Job Card Time Log (delete them in Customize Form if wanted).

## Source layout
```
shopfloor_tablet/
  api.py                 whitelisted methods used by the page
  utils.py               pure quantity, issue and break-time rules (unit-tested without a bench)
  settings.py            Shopfloor Tablet Settings + break/net minutes for an entry
  overrides/job_card.py  Job Card class override
  setup/install.py       role, custom fields, starter scrap reasons
  patches/               pre-model-sync patch (module + role)
  shopfloor_tablet/      module: Scrap Reason doctype, page, two reports
  tests/                 unit tests, js/ (Node harness for the page), scenario.py (end-to-end on a
                         real site), http_checks.py (real users over HTTP)
```
