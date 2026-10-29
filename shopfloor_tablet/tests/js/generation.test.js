// Switching workers while requests are in flight: late answers for the previous worker must not
// change state, banners or the timer.
//
//   node --test shopfloor_tablet/tests/js/*.test.js
"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const { makeEnv, flush, stateFor, activeFor } = require("./harness");

test("late get_state for worker A is dropped after B is selected", async () => {
	const { app, htmlLog, take } = makeEnv();
	app.pick_worker("EMP-A");
	const reqA = take("get_state", "EMP-A"); // A's answer is delayed
	app.pick_worker("EMP-B");
	take("get_state", "EMP-B").ok(stateFor("EMP-B", "Crimp"));
	await flush();
	assert.equal(app.s.employee.name, "EMP-B");
	assert.equal(app.s.operations[0].operation, "Crimp");
	const writes = htmlLog.length;

	reqA.ok({ ...activeFor("EMP-A"), operations: stateFor("EMP-A", "Cut").operations });
	await flush();
	assert.equal(app.s.operations[0].operation, "Crimp", "A's operations must not replace B's");
	assert.equal(app.s.active.length, 0, "A's active entry must not appear for B");
	assert.equal(htmlLog.length, writes, "nothing is rendered for the stale answer");
});

test("late error for worker A shows no banner for B", async () => {
	const { app, take } = makeEnv();
	app.pick_worker("EMP-A");
	const reqA = take("get_state", "EMP-A");
	app.pick_worker("EMP-B");
	take("get_state", "EMP-B").ok(stateFor("EMP-B", "Crimp"));
	await flush();
	reqA.fail("Employee A is not active.");
	await flush();
	assert.equal(app.s.error, "");
});

test("late start for worker A changes nothing after Change worker + B", async () => {
	const { app, take } = makeEnv();
	app.pick_worker("EMP-A");
	take("get_state", "EMP-A").ok(stateFor("EMP-A", "Cut"));
	await flush();
	app.select_op("JC-Cut");
	app.s.machine = "M1";
	app.start();
	const startA = take("start", "EMP-A");
	assert.equal(app.s.busy, true);

	app.show_picker(); // Change worker
	assert.equal(app.s.busy, false, "the next worker is not blocked by A's request");
	app.pick_worker("EMP-B");
	take("get_state", "EMP-B").ok(stateFor("EMP-B", "Crimp"));
	await flush();
	const loadedAt = app.s.loadedAt;

	startA.ok(activeFor("EMP-A"));
	await flush();
	assert.equal(app.s.active.length, 0);
	assert.equal(app.s.flash, "");
	assert.equal(app.s.loadedAt, loadedAt, "the timer base is not reset by A's answer");
	assert.equal(app.s.employee.name, "EMP-B");
});

test("finish and cancel answers for A are dropped after switching", async () => {
	const { app, take } = makeEnv();
	app.pick_worker("EMP-A");
	take("get_state", "EMP-A").ok(activeFor("EMP-A"));
	await flush();

	app.s.finishing = app.s.active[0];
	app.s.finishing.net_now = 60;
	app.finish_values = () => ({ good: 1, scrap: 0, reason: "", issue: "", issue_minutes: 0, note: "", repl_reason: "" });
	app.submit_finish();
	const finA = take("finish", "EMP-A");

	app.pick_worker("EMP-B");
	take("get_state", "EMP-B").ok(stateFor("EMP-B", "Crimp"));
	await flush();

	finA.ok({ good: 1, scrap: 0, net_minutes: 5, remaining: 9 });
	await flush();
	assert.equal(app.s.flash, "", "no 'Saved' banner for A on B's screen");

	app.cancel_start("ROW-B"); // B has no entry; the request is just for the guard
	const cancelB = take("cancel_start", "EMP-B");
	app.show_picker();
	cancelB.ok({ active: activeFor("EMP-B").active });
	await flush();
	assert.equal(app.s.employee, null);
	assert.equal(app.s.active.length, 0);
	assert.equal(app.s.flash, "");
});

test("quiet 30 s refresh for A is dropped after idle return and B", async () => {
	const { app, take } = makeEnv();
	app.pick_worker("EMP-A");
	take("get_state", "EMP-A").ok(stateFor("EMP-A", "Cut"));
	await flush();

	app.lastRefresh = Date.now() - 31000;
	app.tick(); // starts the quiet refresh
	const refreshA = take("get_state", "EMP-A");

	app.lastActivity = Date.now() - 91000;
	app.tick(); // shared tablet idle: back to the name list
	assert.equal(app.s.employee, null);
	app.pick_worker("EMP-B");
	take("get_state", "EMP-B").ok(stateFor("EMP-B", "Crimp"));
	await flush();

	refreshA.ok(activeFor("EMP-A"));
	await flush();
	assert.equal(app.s.active.length, 0);
	assert.equal(app.s.operations[0].operation, "Crimp");
});

test("same worker picked again: the old answer is still dropped (generation)", async () => {
	const { app, take } = makeEnv();
	app.pick_worker("EMP-A");
	const first = take("get_state", "EMP-A");
	app.show_picker();
	app.pick_worker("EMP-A");
	const second = take("get_state", "EMP-A");
	second.ok(stateFor("EMP-A", "New"));
	await flush();
	first.ok(stateFor("EMP-A", "Old"));
	await flush();
	assert.equal(app.s.operations[0].operation, "New");
});

test("logout starts a new generation", async () => {
	const { app, frappe, take } = makeEnv();
	app.pick_worker("EMP-A");
	const reqA = take("get_state", "EMP-A");
	frappe.app.logout();
	reqA.ok(activeFor("EMP-A"));
	await flush();
	assert.equal(app.s.active.length, 0);
});

test("current answers are applied", async () => {
	const { app, take } = makeEnv();
	app.pick_worker("EMP-A");
	take("get_state", "EMP-A").ok(activeFor("EMP-A"));
	await flush();
	assert.equal(app.s.active.length, 1);
	assert.equal(app.s.active[0].row_name, "ROW-EMP-A");
});
