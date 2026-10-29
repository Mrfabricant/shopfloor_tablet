// Same worker, no switching: a get_state asked before a write (start, finish, cancel, replacement
// start/finish) or before a newer get_state must not overwrite the screen when it answers late.
//
//   node --test shopfloor_tablet/tests/js/*.test.js
//   SFT_GUARD_OFF=1 node --test ...   (shows which of these depend on the guard)
"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const { makeEnv, flush, stateFor, activeFor } = require("./harness");

// starts the 30 s quiet refresh and returns its held request
function quietRefresh(app, take) {
	app.lastRefresh = Date.now() - 31000;
	app.tick();
	return take("get_state", "EMP-A");
}

async function withOps(op) {
	const env = makeEnv();
	env.app.pick_worker("EMP-A");
	env.take("get_state", "EMP-A").ok(stateFor("EMP-A", op));
	await flush();
	return env;
}

async function withActive(active) {
	const env = makeEnv();
	env.app.pick_worker("EMP-A");
	env.take("get_state", "EMP-A").ok(active || activeFor("EMP-A"));
	await flush();
	return env;
}

function submitFinish(app, values) {
	app.s.finishing = app.s.active[0];
	app.s.finishing.net_now = 60;
	app.finish_values = () =>
		Object.assign({ good: 1, scrap: 0, reason: "", issue: "", issue_minutes: 0, note: "", repl_reason: "" }, values);
	app.submit_finish();
}

const replActive = () => ({
	active: [
		{ row_name: "ROW-R", job_card: "JC-R", work_order: "WO-R", operation: "Replacement Work", entry_type: "Replacement", elapsed_seconds: 5 },
	],
});

test("1. refresh asked before START answers after it: the active job stays", async () => {
	const { app, htmlLog, take } = await withOps("Cut");
	const refresh = quietRefresh(app, take);

	app.select_op("JC-Cut");
	app.s.machine = "M1";
	app.start();
	take("start", "EMP-A").ok(activeFor("EMP-A"));
	await flush();
	assert.equal(app.s.active.length, 1);
	const loadedAt = app.s.loadedAt;
	const writes = htmlLog.length;

	refresh.ok(stateFor("EMP-A", "Cut")); // no active entry yet when it was asked
	await flush();
	assert.equal(app.s.active.length, 1, "the started job must not disappear");
	assert.equal(app.s.flash, "Started. The time is running.");
	assert.equal(app.s.loadedAt, loadedAt, "the timer base is not reset");
	assert.equal(htmlLog.length, writes, "nothing is rendered for the outdated answer");
});

test("1b. refresh answering while START is still in flight is not applied", async () => {
	const { app, take } = await withOps("Cut");
	const refresh = quietRefresh(app, take);
	app.select_op("JC-Cut");
	app.s.machine = "M1";
	app.start();
	const start = take("start", "EMP-A");

	refresh.ok({ ...stateFor("EMP-A", "Other") });
	await flush();
	assert.equal(app.s.operations[0].operation, "Cut");
	assert.equal(app.s.selected, "JC-Cut", "the selected operation is kept");

	start.ok(activeFor("EMP-A"));
	await flush();
	assert.equal(app.s.active.length, 1);
});

test("2. refresh asked before FINISH answers after it: the finished job does not come back", async () => {
	const { app, htmlLog, take } = await withActive();
	const refresh = quietRefresh(app, take);

	submitFinish(app);
	take("finish", "EMP-A").ok({ good: 1, scrap: 0, net_minutes: 5, remaining: 9 });
	await flush();
	take("get_state", "EMP-A").ok(stateFor("EMP-A", "Cut")); // the finish's own reload
	await flush();
	assert.equal(app.s.active.length, 0);
	const flash = app.s.flash;
	const writes = htmlLog.length;

	refresh.ok(activeFor("EMP-A"));
	await flush();
	assert.equal(app.s.active.length, 0, "the finished job must not reappear as active");
	assert.equal(app.s.flash, flash);
	assert.equal(htmlLog.length, writes);
});

test("2b. old refresh answering between FINISH and its own reload is dropped", async () => {
	const { app, take } = await withActive();
	const refresh = quietRefresh(app, take);

	submitFinish(app);
	take("finish", "EMP-A").ok({ good: 1, scrap: 0, net_minutes: 5, remaining: 9 });
	await flush();
	const reload = take("get_state", "EMP-A");
	refresh.ok(activeFor("EMP-A"));
	await flush();
	assert.equal(app.s.finishing, null);
	reload.ok(stateFor("EMP-A", "Cut"));
	await flush();
	assert.equal(app.s.active.length, 0);
});

test("3. refresh asked before cancel_start answers after it: the cancelled job does not come back", async () => {
	const { app, take } = await withActive();
	const refresh = quietRefresh(app, take);

	app.cancel_start("ROW-EMP-A");
	take("cancel_start", "EMP-A").ok({ active: [] });
	await flush();
	take("get_state", "EMP-A").ok(stateFor("EMP-A", "Cut"));
	await flush();
	assert.equal(app.s.active.length, 0);
	assert.equal(app.s.flash, "Start cancelled.");

	refresh.ok(activeFor("EMP-A"));
	await flush();
	assert.equal(app.s.active.length, 0, "the cancelled job must not reappear");
	assert.equal(app.s.flash, "Start cancelled.");
});

test("4a. get_state asked before START REPLACEMENT answers after it", async () => {
	const { app, take } = await withOps("Cut");
	const refresh = quietRefresh(app, take);

	app.s.mode = "replacement";
	app.s.repl.work_order = "WO-R";
	app.s.repl.ops = [{ job_card: "JC-R", work_order: "WO-R", operation: "Cut", item_name: "x" }];
	app.s.repl.selected = "JC-R";
	app.s.machine = "M1";
	app.start_replacement();
	take("start_replacement", "EMP-A").ok(replActive());
	await flush();
	assert.equal(app.s.active[0].entry_type, "Replacement");

	refresh.ok(stateFor("EMP-A", "Cut"));
	await flush();
	assert.equal(app.s.active.length, 1, "the replacement entry must not disappear");
	assert.equal(app.s.active[0].entry_type, "Replacement");
});

test("4b. refresh asked before FINISH of replacement work answers after it", async () => {
	const { app, take } = await withActive(replActive());
	const refresh = quietRefresh(app, take);

	submitFinish(app, { repl_reason: "Damaged" });
	take("finish_replacement", "EMP-A").ok({ net_minutes: 3 });
	await flush();
	take("get_state", "EMP-A").ok(stateFor("EMP-A", "Cut"));
	await flush();
	assert.equal(app.s.active.length, 0);

	refresh.ok(replActive());
	await flush();
	assert.equal(app.s.active.length, 0, "the finished replacement must not reappear");
	assert.match(app.s.flash, /Replacement work saved/);
});

test("5. two overlapping refreshes answering out of order never go backwards", async () => {
	const { app, take } = await withOps("Cut");
	const older = quietRefresh(app, take);
	app.s.search = "new";
	app.load_state(true); // search typed: a newer get_state
	const newer = take("get_state", "EMP-A");

	newer.ok(stateFor("EMP-A", "New"));
	await flush();
	assert.equal(app.s.operations[0].operation, "New");

	older.ok(stateFor("EMP-A", "Old"));
	await flush();
	assert.equal(app.s.operations[0].operation, "New", "the older answer must not replace the newer one");
});

test("5b. the older refresh answering first is dropped too (a newer one was asked)", async () => {
	const { app, take } = await withOps("Cut");
	const older = quietRefresh(app, take);
	app.load_state(true);
	const newer = take("get_state", "EMP-A");

	older.ok(stateFor("EMP-A", "Old"));
	await flush();
	assert.equal(app.s.operations[0].operation, "Cut");
	newer.ok(stateFor("EMP-A", "New"));
	await flush();
	assert.equal(app.s.operations[0].operation, "New");
});

test("6. refresh answering while the Finish dialog is open does not re-render over it", async () => {
	const { app, htmlLog, take } = await withActive();
	const refresh = quietRefresh(app, take);

	app.open_finish("ROW-EMP-A");
	const entry = app.s.finishing;
	assert.ok(entry);
	const loadedAt = app.s.loadedAt;
	const writes = htmlLog.length;

	refresh.ok({ active: [{ ...activeFor("EMP-A").active[0], elapsed_seconds: 5000, remaining: 3 }] });
	await flush();
	assert.equal(app.s.finishing, entry, "the dialog keeps its entry");
	assert.equal(app.s.active[0], entry);
	assert.equal(app.s.active[0].remaining, 10);
	assert.equal(app.s.loadedAt, loadedAt);
	assert.equal(htmlLog.length, writes, "nothing is rendered over the dialog");

	// once the dialog is closed the next refresh is applied again
	app.close_finish();
	quietRefresh(app, take).ok({ active: [{ ...activeFor("EMP-A").active[0], remaining: 3 }] });
	await flush();
	assert.equal(app.s.active[0].remaining, 3);
});

test("7. without races every answer is applied", async () => {
	const { app, take } = await withOps("Cut");
	quietRefresh(app, take).ok(stateFor("EMP-A", "Bend"));
	await flush();
	assert.equal(app.s.operations[0].operation, "Bend");

	app.select_op("JC-Bend");
	app.s.machine = "M1";
	app.start();
	take("start", "EMP-A").ok(activeFor("EMP-A"));
	await flush();
	assert.equal(app.s.active.length, 1);
	assert.equal(app.s.busy, false);

	quietRefresh(app, take).ok({ active: [{ ...activeFor("EMP-A").active[0], remaining: 4 }] });
	await flush();
	assert.equal(app.s.active[0].remaining, 4, "a refresh after the start is applied");

	submitFinish(app);
	take("finish", "EMP-A").ok({ good: 1, scrap: 0, net_minutes: 5, remaining: 3 });
	await flush();
	take("get_state", "EMP-A").ok(stateFor("EMP-A", "Bend"));
	await flush();
	assert.equal(app.s.active.length, 0);
	assert.match(app.s.flash, /^Saved: good 1/);

	// an error from the current load still shows (the stub jQuery turns the text into the fallback)
	app.load_state(false);
	take("get_state", "EMP-A").fail("Server down.");
	await flush();
	assert.ok(app.s.error, "the error banner is set");
});
