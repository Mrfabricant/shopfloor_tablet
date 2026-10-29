// Shared harness for the page tests: loads the real page script with a stub frappe and a
// chainable jQuery stand-in; every frappe.call is held until the test resolves it.
//
// SFT_GUARD_OFF=1 disables the same-worker outdated-answer guard (state_current) to show which
// tests depend on it; the worker-switch generation guard stays on.
"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const PAGE_JS = path.join(
	__dirname,
	"../../shopfloor_tablet/page/shopfloor_tablet/shopfloor_tablet.js"
);

function makeEnv() {
	const htmlLog = []; // every .html(...) / .text(...) write, in order
	const pending = []; // held frappe.call requests

	// jQuery stand-in: every method returns the same chainable object
	const handler = {
		get(target, prop) {
			if (prop === "length") return 0;
			if (prop === "then") return undefined;
			if (prop === "is") return () => true;
			if (prop === "val" || prop === "attr" || prop === "data") return () => undefined;
			if (prop === "prop") return () => false;
			if (prop === "html" || prop === "text") {
				return (v) => {
					if (v === undefined) return "";
					htmlLog.push(String(v));
					return proxy;
				};
			}
			return () => proxy;
		},
	};
	const proxy = new Proxy(function () {}, handler);
	const $ = () => proxy;

	const frappe = {
		pages: { "shopfloor-tablet": {} },
		utils: { escape_html: (s) => String(s) },
		ui: { make_app_page: () => ({ main: {} }) },
		confirm: (msg, yes) => yes(),
		app: { logout() {}, redirect_to_login() {} },
		call(opts) {
			pending.push({
				method: opts.method.replace("shopfloor_tablet.api.", ""),
				args: opts.args,
				ok: (message) => opts.callback({ message }),
				fail: (text) =>
					opts.error({ _server_messages: JSON.stringify([JSON.stringify({ message: text })]) }),
			});
		},
	};

	const ctx = {
		frappe,
		$,
		CSS: { escape: (s) => s },
		console,
		Date,
		Promise,
		JSON,
		Math,
		Number,
		String,
		Object,
		Error,
		setTimeout: () => 0, // timers are driven by hand
		clearTimeout: () => {},
		setInterval: () => 0,
	};
	vm.createContext(ctx);
	vm.runInContext(fs.readFileSync(PAGE_JS, "utf8"), ctx);

	const wrapper = {};
	frappe.pages["shopfloor-tablet"].on_page_load(wrapper);
	const app = wrapper.sft;
	app.s.ready = true;
	if (process.env.SFT_GUARD_OFF) app.state_current = () => true;
	app.s.workers = [
		{ name: "EMP-A", employee_name: "Worker A" },
		{ name: "EMP-B", employee_name: "Worker B" },
	];

	const take = (method, employee) => {
		const i = pending.findIndex((p) => p.method === method && (!employee || p.args.employee === employee));
		assert.ok(i >= 0, `no pending ${method} for ${employee}; have ${pending.map((p) => p.method + ":" + p.args.employee)}`);
		return pending.splice(i, 1)[0];
	};
	return { app, frappe, htmlLog, pending, take };
}

const flush = () => new Promise((r) => setImmediate(r));

const stateFor = (emp, op) => ({
	active: [],
	operations: [{ job_card: `JC-${op}`, work_order: `WO-${op}`, operation: op, item_name: op, required: 10, good: 0, scrap: 0, remaining: 10 }],
	_emp: emp,
});
const activeFor = (emp) => ({
	active: [{ row_name: `ROW-${emp}`, job_card: "JC-X", work_order: "WO-X", operation: "Cut", elapsed_seconds: 999, required: 10, remaining: 10 }],
});

module.exports = { makeEnv, flush, stateFor, activeFor };
