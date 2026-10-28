(function () {
	const PAGE = "shopfloor-tablet";
	const API = "shopfloor_tablet.api.";
	const IDLE_SECONDS = 90; // shared tablet: go back to the name list after this much inactivity
	const REFRESH_SECONDS = 30;
	const ACCENTS = 6; // number of Work Order colours (sft-acc-0 .. sft-acc-5 in the CSS)
	const MAX_MACHINE_CHIPS = 6; // more machines than this: dropdown instead of buttons

	const esc = (v) => frappe.utils.escape_html(v == null ? "" : String(v));

	const fmt = (n) => {
		const v = parseFloat(Number(n || 0).toFixed(3));
		return String(v);
	};

	const mins = (n) => `${Math.floor(Number(n || 0))} min`;

	const pad = (n) => String(n).padStart(2, "0");
	const clock = (secs) => {
		secs = Math.max(0, Math.floor(secs));
		return `${pad(Math.floor(secs / 3600))}:${pad(Math.floor((secs % 3600) / 60))}:${pad(secs % 60)}`;
	};

	// A response for a worker who is no longer on screen. Callers ignore it silently.
	class Stale extends Error {
		constructor() {
			super("stale response");
			this.stale = true;
		}
	}
	const is_stale = (e) => !!(e && e.stale);

	const ICON_MACHINE = `<svg class="sft-icon" viewBox="0 0 24 24" aria-hidden="true"><path fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" d="M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/></svg>`;
	const ICON_TICK = `<svg class="sft-icon" viewBox="0 0 24 24" aria-hidden="true"><path fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" d="M5 12.5l4.5 4.5L19 7.5"/></svg>`;

	frappe.pages[PAGE].on_page_load = function (wrapper) {
		const page = frappe.ui.make_app_page({
			parent: wrapper,
			title: "Shopfloor",
			single_column: true,
		});
		$(wrapper).addClass("sft-wrapper");
		wrapper.sft = new ShopfloorTablet(page, wrapper);
	};

	class ShopfloorTablet {
		constructor(page, wrapper) {
			this.page = page;
			this.wrapper = wrapper;
			this.$root = $('<div class="sft-root"></div>').appendTo(page.main);
			this.s = {
				ready: false,
				ownEmployee: null,
				employee: null,
				workers: [],
				machines: [],
				reasons: [],
				issueReasons: [],
				replacementEnabled: false,
				active: [],
				operations: [],
				search: "",
				selected: null,
				machine: "",
				busy: false,
				flash: "",
				error: "",
				loadedAt: Date.now(),
				finishing: null,
				mode: "normal", // "normal" | "replacement"
				repl: { search: "", orders: [], work_order: null, ops: [], selected: null },
			};
			// Every request remembers the generation and the worker it was made for. Switching
			// worker (or logging out) starts a new generation, so late answers are dropped.
			this.gen = 0;
			// Work Order -> colour index. Kept for the session so a Work Order keeps its colour
			// across refreshes and on the active-work card.
			this.accents = {};
			this.nextAccent = 0;
			this.lastActivity = Date.now();
			this.lastRefresh = Date.now();
			this.searchTimer = null;

			this.bind();
			this.watch_logout();
			$(wrapper).on("show", () => this.on_show());
			setTimeout(() => this.on_show(), 0);
			setInterval(() => this.tick(), 1000);
		}

		// ------------------------------------------------------------ plumbing
		call(method, args) {
			return new Promise((resolve, reject) => {
				frappe.call({
					method: API + method,
					args: args || {},
					type: "POST",
					silent: true,
					callback: (r) => resolve(r.message),
					error: (r) => reject(new Error(this.error_text(r))),
				});
			});
		}

		// A call made for the current worker. Rejects with Stale when the worker changed meanwhile.
		request(method, args) {
			const gen = this.gen;
			const emp = this.s.employee ? this.s.employee.name : null;
			const current = () =>
				gen === this.gen && emp === (this.s.employee ? this.s.employee.name : null);
			return this.call(method, Object.assign({ employee: emp }, args || {})).then(
				(data) => {
					if (!current()) throw new Stale();
					return data;
				},
				(err) => {
					throw current() ? err : new Stale();
				}
			);
		}

		new_generation() {
			this.gen++;
			this.s.busy = false;
			this.$root.removeClass("sft-busy");
			clearTimeout(this.searchTimer);
		}

		watch_logout() {
			const app = frappe.app;
			if (!app || app.__sft_wrapped) return;
			app.__sft_wrapped = true;
			for (const fn of ["logout", "redirect_to_login"]) {
				const orig = app[fn];
				if (typeof orig !== "function") continue;
				app[fn] = (...a) => {
					this.new_generation();
					return orig.apply(app, a);
				};
			}
		}

		error_text(r) {
			let msg = "";
			try {
				if (r && r._server_messages) {
					msg = JSON.parse(r._server_messages)
						.map((m) => (typeof m === "string" ? JSON.parse(m) : m).message)
						.join(" ");
				}
			} catch (e) {
				msg = "";
			}
			if (!msg && r && r.exception) {
				msg = String(r.exception).split(":").slice(1).join(":").trim();
			}
			msg = $("<div>").html(msg).text().trim();
			return msg || "Something went wrong. Please try again.";
		}

		accent(work_order) {
			if (!(work_order in this.accents)) {
				this.accents[work_order] = this.nextAccent++ % ACCENTS;
			}
			return `sft-acc-${this.accents[work_order]}`;
		}

		bind() {
			const me = this;
			this.$root.on("pointerdown keydown", () => (this.lastActivity = Date.now()));

			this.$root.on("click", "[data-action]", function (e) {
				const $el = $(this);
				const action = $el.data("action");
				if ($el.prop("disabled")) return;
				me.act(action, $el, e);
			});

			this.$root.on("input", "[data-role=worker-search]", function () {
				const txt = $(this).val().toLowerCase().trim();
				me.$root.find(".sft-tile").each(function () {
					const hit = !txt || String($(this).data("name")).toLowerCase().includes(txt);
					$(this).toggleClass("sft-hidden", !hit);
				});
			});

			this.$root.on("input", "[data-role=op-search]", function () {
				me.s.search = $(this).val();
				clearTimeout(me.searchTimer);
				me.searchTimer = setTimeout(() => me.load_state(true), 350);
			});

			this.$root.on("input", "[data-role=wo-search]", function () {
				me.s.repl.search = $(this).val();
				clearTimeout(me.searchTimer);
				me.searchTimer = setTimeout(() => me.load_replacement_orders(), 350);
			});

			this.$root.on("change", "[data-role=machine]", function () {
				me.s.machine = $(this).val();
				me.render_summary();
			});

			this.$root.on("input change", "[data-role=good], [data-role=scrap], [data-role=issue-reason]", () =>
				this.update_finish_hint()
			);
		}

		act(action, $el) {
			switch (action) {
				case "pick-worker":
					return this.pick_worker($el.attr("data-emp"));
				case "change-worker":
					return this.show_picker();
				case "mode":
					return this.set_mode($el.attr("data-mode"));
				case "select-op":
					return this.select_op($el.attr("data-jc"));
				case "pick-wo":
					return this.pick_replacement_wo($el.attr("data-wo"));
				case "repl-back":
					return this.pick_replacement_wo(null);
				case "select-repl-op":
					return this.select_repl_op($el.attr("data-jc"));
				case "pick-machine":
					return this.pick_machine($el.attr("data-machine"));
				case "start":
					return this.start();
				case "start-replacement":
					return this.start_replacement();
				case "finish-open":
					return this.open_finish($el.attr("data-row"));
				case "cancel-start":
					return this.cancel_start($el.attr("data-row"));
				case "modal-close":
					return this.close_finish();
				case "modal-submit":
					return this.submit_finish();
				case "all-remaining":
					return this.fill_all_remaining();
				case "dismiss":
					this.s.error = "";
					this.s.flash = "";
					return this.render_banner();
			}
		}

		// ------------------------------------------------------------ lifecycle
		async on_show() {
			if (this.starting) return;
			this.starting = true;
			try {
				if (!this.s.ready) {
					this.render_loading();
					const ctx = await this.call("get_context");
					this.s.workers = ctx.workers || [];
					this.s.machines = ctx.machines || [];
					this.s.reasons = ctx.scrap_reasons || [];
					this.s.issueReasons = ctx.issue_reasons || [];
					this.s.replacementEnabled = !!ctx.replacement_enabled;
					this.s.ownEmployee = ctx.employee || null;
					this.s.ready = true;
					if (this.s.ownEmployee) {
						this.s.employee = this.s.ownEmployee;
					}
				}
				if (this.s.employee) {
					await this.load_state(false);
				} else {
					this.render_picker();
				}
			} catch (e) {
				this.$root.html(
					`<div class="sft-error-page">${esc(e.message)}<br><br>
					<button class="sft-btn sft-btn-primary" onclick="location.reload()">Reload</button></div>`
				);
			} finally {
				this.starting = false;
			}
		}

		tick() {
			if (!this.$root.is(":visible")) return;

			// running timer of the active entry
			const el = this.$root.find(".sft-timer");
			if (el.length && this.s.active.length) {
				const extra = (Date.now() - this.s.loadedAt) / 1000;
				el.each((i, node) => {
					const base = Number($(node).data("elapsed")) || 0;
					$(node).text(clock(base + extra));
				});
			}

			const idle = (Date.now() - this.lastActivity) / 1000;
			const modal_open = !!this.s.finishing;

			// shared tablet (login not linked to one employee): back to the name list
			if (!this.s.ownEmployee && this.s.employee && !modal_open && idle > IDLE_SECONDS) {
				this.show_picker();
				return;
			}

			// quiet refresh so other workers' progress shows up
			if (
				this.s.employee &&
				!modal_open &&
				!this.s.busy &&
				(Date.now() - this.lastRefresh) / 1000 > REFRESH_SECONDS
			) {
				this.refresh();
			}
		}

		refresh() {
			if (!this.s.active.length && this.s.mode === "replacement") {
				this.lastRefresh = Date.now();
				return this.s.repl.work_order ? this.load_replacement_ops(true) : this.load_replacement_orders(true);
			}
			return this.load_state(true);
		}

		async load_state(quiet) {
			if (!this.s.employee) return;
			this.lastRefresh = Date.now();
			try {
				const st = await this.request("get_state", { search: this.s.search || "" });
				this.s.active = st.active || [];
				this.s.operations = st.operations || [];
				this.s.loadedAt = Date.now();
				if (this.s.selected && !this.s.operations.find((o) => o.job_card === this.s.selected)) {
					this.s.selected = null;
				}
				if (this.s.active.length) this.s.mode = "normal";
				if (quiet && this.$root.find(".sft-ops").length && !this.s.active.length) {
					this.render_ops();
					this.render_startbar();
				} else {
					this.render_main();
				}
			} catch (e) {
				if (is_stale(e)) return;
				if (!quiet) {
					this.s.error = e.message;
					this.render_main();
				}
			}
		}

		// ------------------------------------------------------------ views
		render_loading() {
			this.$root.html('<div class="sft-loading">Loading...</div>');
		}

		render_picker() {
			const tiles = this.s.workers
				.map(
					(w) => `<button class="sft-tile" data-action="pick-worker" data-emp="${esc(w.name)}"
						data-name="${esc(w.employee_name || w.name)}">${esc(w.employee_name || w.name)}</button>`
				)
				.join("");
			this.$root.html(`
				<div class="sft-title">Who is working?</div>
				<input class="sft-input sft-search" data-role="worker-search" type="search"
					placeholder="Type to find your name" autocomplete="off">
				<div class="sft-tiles">${tiles || '<div class="sft-empty">No active employees found.</div>'}</div>
			`);
		}

		reset_worker_view() {
			this.s.selected = null;
			this.s.search = "";
			this.s.flash = "";
			this.s.error = "";
			this.s.active = [];
			this.s.operations = [];
			this.s.finishing = null;
			this.s.mode = "normal";
			this.s.repl = { search: "", orders: [], work_order: null, ops: [], selected: null };
		}

		pick_worker(name) {
			const w = this.s.workers.find((x) => x.name === name);
			if (!w) return;
			this.new_generation();
			this.s.employee = w;
			this.reset_worker_view();
			this.render_loading();
			this.load_state(false);
		}

		show_picker() {
			this.new_generation();
			this.s.employee = null;
			this.reset_worker_view();
			this.render_picker();
		}

		render_main() {
			const emp = this.s.employee;
			if (!emp) return this.render_picker();

			let body = "";
			if (this.s.active.length) {
				body = this.s.active.map((a) => this.active_card(a)).join("");
			} else {
				const tabs = this.s.replacementEnabled
					? `<div class="sft-tabs" role="tablist">
						<button class="sft-tab${this.s.mode === "normal" ? " sft-on" : ""}" data-action="mode" data-mode="normal">Start work</button>
						<button class="sft-tab sft-tab-repl${this.s.mode === "replacement" ? " sft-on" : ""}" data-action="mode" data-mode="replacement">Replacement work</button>
					</div>`
					: `<div class="sft-title">Start work</div>`;
				body =
					this.s.mode === "replacement"
						? `${tabs}<div class="sft-repl"></div><div class="sft-startbar"></div>`
						: `${tabs}
						<input class="sft-input sft-search" data-role="op-search" type="search"
							placeholder="Search work order, item or operation" autocomplete="off"
							value="${esc(this.s.search)}">
						<div class="sft-ops"></div>
						<div class="sft-startbar"></div>`;
			}

			this.$root.html(`
				<div class="sft-topbar">
					<div class="sft-who">${esc(emp.employee_name || emp.name)}</div>
					<button class="sft-btn sft-btn-ghost" data-action="change-worker">Change worker</button>
				</div>
				<div class="sft-banner"></div>
				${body}
			`);
			this.render_banner();
			if (!this.s.active.length) {
				if (this.s.mode === "replacement") {
					this.render_replacement();
				} else {
					this.render_ops();
				}
				this.render_startbar();
			}
		}

		render_banner() {
			const $b = this.$root.find(".sft-banner");
			let html = "";
			if (this.s.error) {
				html = `<div class="sft-msg sft-msg-error" data-action="dismiss">${esc(this.s.error)}</div>`;
			} else if (this.s.flash) {
				html = `<div class="sft-msg sft-msg-ok" data-action="dismiss">${esc(this.s.flash)}</div>`;
			}
			$b.html(html);
		}

		machine_chip(machine) {
			return `<span class="sft-chip sft-chip-machine">${ICON_MACHINE}${esc(machine || "-")}</span>`;
		}

		// good and left against planned; scrap is shown on its own (it does not use up quantity)
		progress(o) {
			const req = Number(o.required) || 0;
			const pct = (v) => (req > 0 ? Math.max(0, Math.min(100, (Number(v || 0) / req) * 100)) : 0);
			const scrap = Number(o.scrap) || 0;
			return `
				<div class="sft-progress" role="img"
					aria-label="good ${fmt(o.good)}, left ${fmt(o.remaining)} of ${fmt(req)}">
					<span class="sft-bar-good" style="width:${pct(o.good)}%"></span>
				</div>
				<div class="sft-progress-legend">
					<span><i class="sft-dot sft-dot-good"></i>Good ${fmt(o.good)}</span>
					<span><i class="sft-dot sft-dot-left"></i>Left ${fmt(o.remaining)}</span>
					${scrap > 0 ? `<span class="sft-scrap-note"><i class="sft-dot sft-dot-scrap"></i>Scrap ${fmt(scrap)} (made again)</span>` : ""}
				</div>`;
		}

		active_card(a) {
			const repl = a.entry_type === "Replacement";
			const head = `
				<div class="sft-active-head">
					<span class="sft-live-dot"></span>
					<span class="sft-active-label">${repl ? "Replacement work" : "Working now"}</span>
					<span class="sft-active-wo">${esc(a.work_order)}</span>
				</div>`;
			const qty = repl
				? `<div class="sft-active-left">Replacement work records time only: no good, no scrap.</div>`
				: `${this.progress(a)}
					<div class="sft-active-left">Left on this operation: <b>${fmt(a.remaining)}</b> of ${fmt(a.required)} ${esc(a.uom || "")}</div>`;
			return `
				<div class="sft-card sft-active ${repl ? "sft-active-repl " : ""}${this.accent(a.work_order)}">
					${head}
					<div class="sft-op-title">${repl ? "Replacement: " : ""}${esc(a.operation)}</div>
					<div class="sft-active-item">${esc(a.item_name)}</div>
					<div class="sft-chips">
						${this.machine_chip(a.machine)}
						<span class="sft-chip">Started ${esc(a.started_at)}</span>
					</div>
					<div class="sft-timer" data-elapsed="${a.elapsed_seconds}">${clock(a.elapsed_seconds)}</div>
					${qty}
					<button class="sft-btn sft-btn-finish" data-action="finish-open" data-row="${esc(a.row_name)}">FINISH</button>
					<button class="sft-btn sft-btn-link" data-action="cancel-start" data-row="${esc(a.row_name)}">Started by mistake - cancel</button>
				</div>`;
		}

		render_ops() {
			const $ops = this.$root.find(".sft-ops");
			if (!$ops.length) return;

			$ops.toggleClass("sft-has-selection", !!this.s.selected);

			if (!this.s.operations.length) {
				$ops.html('<div class="sft-empty">No open operations. Work orders are created in ERPNext.</div>');
				return;
			}

			// operations arrive sorted by Work Order, then sequence: group them into blocks
			const blocks = [];
			for (const o of this.s.operations) {
				let b = blocks[blocks.length - 1];
				if (!b || b.work_order !== o.work_order) {
					b = { work_order: o.work_order, item_name: o.item_name, ops: [] };
					blocks.push(b);
				}
				b.ops.push(o);
			}

			$ops.html(blocks.map((b) => this.wo_block(b)).join(""));
		}

		wo_block(b) {
			const n = b.ops.length;
			const cards = b.ops
				.map((o, i) => {
					const sel = this.s.selected === o.job_card ? " sft-selected" : "";
					const working = (o.working_now || []).length
						? `<div class="sft-working">Working now:
							${o.working_now.map((w) => `<span class="sft-chip sft-chip-worker">${esc(w)}</span>`).join("")}</div>`
						: "";
					return `
						<div class="sft-card sft-op${sel}" data-action="select-op" data-jc="${esc(o.job_card)}">
							<div class="sft-step">${o.sequence_id || i + 1}</div>
							<div class="sft-op-main">
								<div class="sft-op-title">${esc(o.operation)}</div>
								<div class="sft-chips">${this.machine_chip(o.machine)}</div>
								${this.progress(o)}
								${working}
							</div>
							<div class="sft-op-qty">
								<div class="sft-qty-big">${fmt(o.remaining)}</div>
								<div class="sft-op-sub">left of ${fmt(o.required)} ${esc(o.uom || "")}</div>
							</div>
							<div class="sft-tick">${ICON_TICK}</div>
						</div>`;
				})
				.join("");
			return `
				<section class="sft-wo ${this.accent(b.work_order)}">
					<div class="sft-wo-head">
						<div class="sft-wo-no">${esc(b.work_order)}</div>
						<div class="sft-wo-item">${esc(b.item_name)}</div>
						<div class="sft-wo-count">${n} ${n === 1 ? "operation" : "operations"} open</div>
					</div>
					${cards}
				</section>`;
		}

		select_op(jc) {
			const op = this.s.operations.find((o) => o.job_card === jc);
			if (!op) return;
			this.s.selected = jc;
			this.s.machine = op.machine || "";
			this.s.error = "";
			this.$root.find(".sft-ops").addClass("sft-has-selection");
			this.$root.find(".sft-op").removeClass("sft-selected");
			this.$root.find(`.sft-op[data-jc="${CSS.escape(jc)}"]`).addClass("sft-selected");
			this.render_banner();
			this.render_startbar();
		}

		pick_machine(machine) {
			this.s.machine = machine || "";
			this.$root.find(".sft-machine-btn").each(function () {
				$(this).toggleClass("sft-on", $(this).attr("data-machine") === machine);
			});
			this.render_summary();
		}

		machine_options(op) {
			const machines = this.s.machines.slice();
			if (op.machine && !machines.includes(op.machine)) machines.unshift(op.machine);
			return machines;
		}

		// the operation the start bar is for, in the current mode
		chosen_op() {
			if (this.s.mode === "replacement") {
				return this.s.repl.ops.find((o) => o.job_card === this.s.repl.selected);
			}
			return this.s.operations.find((o) => o.job_card === this.s.selected);
		}

		render_startbar() {
			const $bar = this.$root.find(".sft-startbar");
			if (!$bar.length) return;

			const op = this.chosen_op();
			if (!op) {
				$bar.empty();
				return;
			}
			const repl = this.s.mode === "replacement";

			const machines = this.machine_options(op);
			let picker;
			if (machines.length <= MAX_MACHINE_CHIPS) {
				picker = `<div class="sft-machine-grid">${machines
					.map(
						(m) => `<button class="sft-machine-btn${m === this.s.machine ? " sft-on" : ""}"
							data-action="pick-machine" data-machine="${esc(m)}">
							<span class="sft-machine-row">${ICON_MACHINE}<span class="sft-machine-name">${esc(m)}</span>
								<span class="sft-machine-check">${ICON_TICK}</span></span>
							${m === op.machine ? '<span class="sft-default">Default</span>' : ""}
						</button>`
					)
					.join("")}</div>`;
			} else {
				const options = ['<option value="">Choose machine</option>']
					.concat(
						machines.map(
							(m) =>
								`<option value="${esc(m)}"${m === this.s.machine ? " selected" : ""}>${esc(m)}${
									m === op.machine ? " (default)" : ""
								}</option>`
						)
					)
					.join("");
				picker = `<select class="sft-input sft-select" data-role="machine">${options}</select>`;
			}

			$bar.attr("class", `sft-startbar ${repl ? "sft-startbar-repl " : ""}${this.accent(op.work_order)}`).html(`
				<div class="sft-label">Machine</div>
				${picker}
				<div class="sft-summary"></div>
				${
					repl
						? '<button class="sft-btn sft-btn-start sft-btn-repl" data-action="start-replacement">START REPLACEMENT</button>'
						: '<button class="sft-btn sft-btn-start" data-action="start">START</button>'
				}
			`);
			this.render_summary();
		}

		render_summary() {
			const op = this.chosen_op();
			if (!op) return;
			const machine = this.s.machine
				? esc(this.s.machine)
				: '<span class="sft-summary-missing">choose a machine</span>';
			const prefix = this.s.mode === "replacement" ? "Replacement work &middot; " : "";
			this.$root
				.find(".sft-summary")
				.html(
					`${prefix}<b>${esc(op.work_order)}</b> &middot; ${esc(op.item_name)} &middot; <b>${esc(op.operation)}</b> &middot; ${machine}`
				);
		}

		// ------------------------------------------------------------ replacement mode
		set_mode(mode) {
			if (mode === this.s.mode) return;
			this.s.mode = mode === "replacement" ? "replacement" : "normal";
			this.s.selected = null;
			this.s.repl.selected = null;
			this.s.error = "";
			this.s.flash = "";
			this.render_main();
			if (this.s.mode === "replacement" && !this.s.repl.work_order) this.load_replacement_orders();
			if (this.s.mode === "normal") this.load_state(true);
		}

		async load_replacement_orders(quiet) {
			if (!this.s.employee) return;
			try {
				this.s.repl.orders = await this.request("list_replacement_work_orders", {
					search: this.s.repl.search || "",
				});
				this.render_replacement();
			} catch (e) {
				if (is_stale(e) || quiet) return;
				this.s.error = e.message;
				this.render_banner();
			}
		}

		async load_replacement_ops(quiet) {
			const wo = this.s.repl.work_order;
			if (!this.s.employee || !wo) return;
			try {
				const ops = await this.request("list_replacement_operations", { work_order: wo });
				if (this.s.repl.work_order !== wo) return;
				this.s.repl.ops = ops || [];
				if (this.s.repl.selected && !this.s.repl.ops.find((o) => o.job_card === this.s.repl.selected)) {
					this.s.repl.selected = null;
				}
				this.render_replacement();
				this.render_startbar();
			} catch (e) {
				if (is_stale(e) || quiet) return;
				this.s.error = e.message;
				this.render_banner();
			}
		}

		pick_replacement_wo(wo) {
			this.s.repl.work_order = wo || null;
			this.s.repl.ops = [];
			this.s.repl.selected = null;
			this.render_replacement();
			this.render_startbar();
			if (wo) this.load_replacement_ops();
			else this.load_replacement_orders();
		}

		render_replacement() {
			const $r = this.$root.find(".sft-repl");
			if (!$r.length) return;
			const r = this.s.repl;

			if (!r.work_order) {
				const list = r.orders.length
					? r.orders
							.map(
								(o) => `
						<div class="sft-card sft-wo-pick ${this.accent(o.work_order)}" data-action="pick-wo" data-wo="${esc(o.work_order)}">
							<div class="sft-wo-no">${esc(o.work_order)}</div>
							<div class="sft-wo-item">${esc(o.item_name)}</div>
							<div class="sft-chips"><span class="sft-chip">${esc(o.status)}</span>
								<span class="sft-chip">${fmt(o.qty)} ${esc(o.uom || "")}</span></div>
						</div>`
							)
							.join("")
					: '<div class="sft-empty">No work orders found.</div>';
				$r.html(`
					<div class="sft-repl-help">Time spent redoing work on an earlier operation. It does not count as good or scrap.</div>
					<input class="sft-input sft-search" data-role="wo-search" type="search"
						placeholder="Search work order or item" autocomplete="off" value="${esc(r.search)}">
					<div class="sft-label">1. Choose the work order</div>
					${list}`);
				return;
			}

			const ops = r.ops.length
				? r.ops
						.map((o, i) => {
							const sel = r.selected === o.job_card ? " sft-selected" : "";
							return `
						<div class="sft-card sft-op${sel}" data-action="select-repl-op" data-jc="${esc(o.job_card)}">
							<div class="sft-step">${o.sequence_id || i + 1}</div>
							<div class="sft-op-main">
								<div class="sft-op-title">${esc(o.operation)}</div>
								<div class="sft-chips">${this.machine_chip(o.machine)}
									<span class="sft-chip">${o.submitted ? "Completed" : esc(o.status || "Open")}</span></div>
							</div>
							<div class="sft-op-qty">
								<div class="sft-qty-big">${fmt(o.good)}</div>
								<div class="sft-op-sub">good of ${fmt(o.required)} ${esc(o.uom || "")}</div>
							</div>
							<div class="sft-tick">${ICON_TICK}</div>
						</div>`;
						})
						.join("")
				: '<div class="sft-empty">Loading operations...</div>';
			$r.html(`
				<div class="sft-repl-wo ${this.accent(r.work_order)}">
					<div><div class="sft-wo-no">${esc(r.work_order)}</div>
						<div class="sft-wo-item">${esc((r.orders.find((o) => o.work_order === r.work_order) || {}).item_name || "")}</div></div>
					<button class="sft-btn sft-btn-ghost" data-action="repl-back">Other work order</button>
				</div>
				<div class="sft-label">2. Choose the operation to redo</div>
				<div class="sft-ops${r.selected ? " sft-has-selection" : ""}">${ops}</div>`);
		}

		select_repl_op(jc) {
			const op = this.s.repl.ops.find((o) => o.job_card === jc);
			if (!op) return;
			this.s.repl.selected = jc;
			this.s.machine = op.machine || "";
			this.s.error = "";
			this.render_banner();
			this.render_replacement();
			this.render_startbar();
		}

		// ------------------------------------------------------------ actions
		async run(fn) {
			if (this.s.busy) return;
			const gen = this.gen;
			this.s.busy = true;
			this.$root.addClass("sft-busy");
			try {
				await fn();
			} finally {
				// a newer generation already reset the busy state
				if (gen === this.gen) {
					this.s.busy = false;
					this.$root.removeClass("sft-busy");
				}
			}
		}

		after_start(r, flash) {
			this.s.active = r.active || [];
			this.s.selected = null;
			this.s.repl.selected = null;
			this.s.mode = "normal";
			this.s.loadedAt = Date.now();
			this.s.error = "";
			this.s.flash = flash;
			this.render_main();
		}

		start() {
			const op = this.s.operations.find((o) => o.job_card === this.s.selected);
			if (!op) return;
			if (!this.s.machine) {
				this.s.error = "Choose a machine.";
				return this.render_banner();
			}
			return this.run(async () => {
				try {
					const r = await this.request("start", { job_card: op.job_card, machine: this.s.machine });
					this.after_start(r, "Started. The time is running.");
				} catch (e) {
					if (is_stale(e)) return;
					this.s.error = e.message;
					this.render_banner();
					this.load_state(true);
				}
			});
		}

		start_replacement() {
			const op = this.chosen_op();
			if (!op || this.s.mode !== "replacement") return;
			if (!this.s.machine) {
				this.s.error = "Choose a machine.";
				return this.render_banner();
			}
			return this.run(async () => {
				try {
					const r = await this.request("start_replacement", {
						job_card: op.job_card,
						machine: this.s.machine,
					});
					this.after_start(r, "Replacement work started. The time is running.");
				} catch (e) {
					if (is_stale(e)) return;
					this.s.error = e.message;
					this.render_banner();
				}
			});
		}

		cancel_start(row) {
			frappe.confirm("Cancel this start? Nothing will be recorded.", () =>
				this.run(async () => {
					try {
						const r = await this.request("cancel_start", { row_name: row });
						this.s.active = r.active || [];
						this.s.flash = "Start cancelled.";
						this.s.error = "";
						await this.load_state(false);
					} catch (e) {
						if (is_stale(e)) return;
						this.s.error = e.message;
						this.render_banner();
					}
				})
			);
		}

		options(list, blank) {
			return [`<option value="">${esc(blank)}</option>`]
				.concat(list.map((r) => `<option value="${esc(r)}">${esc(r)}</option>`))
				.join("");
		}

		open_finish(row) {
			const a = this.s.active.find((x) => x.row_name === row);
			if (!a) return;
			this.s.finishing = a;
			const repl = a.entry_type === "Replacement";
			// net working time so far: refreshed from the server below
			a.net_now = Number(a.net_minutes || 0) + (Date.now() - this.s.loadedAt) / 60000;

			const qty_fields = repl
				? `<label class="sft-label">Reason for the replacement</label>
					<select class="sft-input sft-select" data-role="repl-reason">${this.options(this.s.reasons, "Choose reason")}</select>
					<label class="sft-label">Note (optional)</label>
					<textarea class="sft-input sft-note" data-role="note" rows="2" maxlength="500"></textarea>`
				: `<label class="sft-label">Good quantity</label>
					<input class="sft-input sft-qtyinput" data-role="good" type="number" inputmode="decimal"
						min="0" step="any" placeholder="0">
					<button class="sft-btn sft-btn-ghost sft-small" data-action="all-remaining">All remaining is good</button>

					<label class="sft-label">Scrap quantity</label>
					<input class="sft-input sft-qtyinput sft-qty-scrap" data-role="scrap" type="number" inputmode="decimal"
						min="0" step="any" placeholder="0">

					<div class="sft-reason sft-hidden">
						<label class="sft-label">Scrap reason</label>
						<select class="sft-input sft-select" data-role="reason">${this.options(this.s.reasons, "Choose reason")}</select>
					</div>

					<div class="sft-hint"></div>

					<details class="sft-issue">
						<summary>Problem during this work? (optional)</summary>
						<label class="sft-label">Issue</label>
						<select class="sft-input sft-select" data-role="issue-reason">${this.options(this.s.issueReasons, "No issue")}</select>
						<label class="sft-label">Minutes lost (optional, at most <span class="sft-net-max">${mins(a.net_now)}</span>)</label>
						<input class="sft-input" data-role="issue-minutes" type="number" inputmode="decimal" min="0" step="any" placeholder="0">
						<label class="sft-label">Note (optional)</label>
						<textarea class="sft-input sft-note" data-role="note" rows="2" maxlength="500"></textarea>
					</details>`;

			this.$root.find(".sft-modal").remove();
			this.$root.append(`
				<div class="sft-modal">
					<div class="sft-modal-box ${repl ? "sft-modal-repl " : ""}${this.accent(a.work_order)}">
						<div class="sft-title">${repl ? "Finish replacement work" : "Finish work"}</div>
						<div class="sft-modal-summary">
							<div class="sft-op-title">${esc(a.operation)}</div>
							<div class="sft-op-sub"><b>${esc(a.work_order)}</b> &middot; ${esc(a.item_name)}</div>
							<div class="sft-chips">${this.machine_chip(a.machine)}</div>
							<div class="sft-modal-left">Working time without break: <b class="sft-net-now">${mins(a.net_now)}</b></div>
							${repl ? "" : `<div class="sft-modal-left">Left on this operation: <b>${fmt(a.remaining)}</b> ${esc(a.uom || "")}</div>`}
						</div>

						${qty_fields}

						<div class="sft-modal-error"></div>

						<div class="sft-modal-buttons">
							<button class="sft-btn sft-btn-ghost" data-action="modal-close">Back</button>
							<button class="sft-btn sft-btn-finish" data-action="modal-submit">FINISH</button>
						</div>
					</div>
				</div>`);
			this.$root.find(repl ? "[data-role=repl-reason]" : "[data-role=good]").trigger("focus");
			this.load_entry_time(a);
		}

		async load_entry_time(a) {
			try {
				const t = await this.request("get_entry_time", { row_name: a.row_name });
				if (this.s.finishing !== a) return;
				a.net_now = Number(t.net_minutes) || 0;
				this.$root.find(".sft-net-now, .sft-net-max").text(mins(a.net_now));
			} catch (e) {
				// the estimate stays; the server checks the limit at Finish anyway
			}
		}

		close_finish() {
			this.s.finishing = null;
			this.$root.find(".sft-modal").remove();
		}

		fill_all_remaining() {
			if (!this.s.finishing) return;
			this.$root.find("[data-role=good]").val(fmt(this.s.finishing.remaining));
			this.update_finish_hint();
		}

		finish_values() {
			const num = (sel) => {
				const v = parseFloat(String(this.$root.find(sel).val() || "").replace(",", "."));
				return isNaN(v) ? 0 : v;
			};
			const txt = (sel) => String(this.$root.find(sel).val() || "").trim();
			return {
				good: num("[data-role=good]"),
				scrap: num("[data-role=scrap]"),
				reason: txt("[data-role=reason]"),
				issue: txt("[data-role=issue-reason]"),
				issue_minutes: num("[data-role=issue-minutes]"),
				note: txt("[data-role=note]"),
				repl_reason: txt("[data-role=repl-reason]"),
			};
		}

		update_finish_hint() {
			const a = this.s.finishing;
			if (!a || a.entry_type === "Replacement") return;
			const v = this.finish_values();
			this.$root.find(".sft-reason").toggleClass("sft-hidden", !(v.scrap > 0));
			const left = Math.round((a.remaining - v.good) * 1000) / 1000;
			const $h = this.$root.find(".sft-hint");
			if (left < 0) {
				$h.addClass("sft-hint-bad").text(`Good is more than the ${fmt(a.remaining)} left on this operation.`);
			} else {
				$h.removeClass("sft-hint-bad").text(`After this: ${fmt(left)} left.`);
			}
		}

		finish_error(v, a) {
			if (a.entry_type === "Replacement") {
				return v.repl_reason ? "" : "Choose a reason for the replacement work.";
			}
			if (v.good < 0 || v.scrap < 0 || v.issue_minutes < 0) return "Numbers cannot be negative.";
			if (v.good <= 0 && v.scrap <= 0 && !v.issue) {
				return "Enter the good quantity or the scrap quantity, or choose an issue reason.";
			}
			if (v.scrap > 0 && !v.reason) return "Choose a scrap reason.";
			if (Math.round(v.good * 1000) > Math.round(a.remaining * 1000)) {
				return `Good is more than the ${fmt(a.remaining)} left on this operation.`;
			}
			if (v.issue_minutes > 0 && !v.issue) return "Choose an issue reason for the minutes lost.";
			if (v.issue_minutes > Math.ceil(a.net_now || 0)) {
				return `Minutes lost cannot be more than the working time (${mins(a.net_now)}).`;
			}
			return "";
		}

		submit_finish() {
			const a = this.s.finishing;
			if (!a) return;
			const v = this.finish_values();
			const $err = this.$root.find(".sft-modal-error");
			const problem = this.finish_error(v, a);
			$err.text(problem);
			if (problem) return;

			const repl = a.entry_type === "Replacement";
			return this.run(async () => {
				try {
					let flash;
					if (repl) {
						const r = await this.request("finish_replacement", {
							row_name: a.row_name,
							reason: v.repl_reason,
							note: v.note,
						});
						flash = `Replacement work saved: ${fmt(r.net_minutes)} min without break.`;
					} else {
						const r = await this.request("finish", {
							row_name: a.row_name,
							good_qty: v.good,
							scrap_qty: v.scrap,
							scrap_reason: v.scrap > 0 ? v.reason : "",
							issue_reason: v.issue,
							issue_minutes: v.issue ? v.issue_minutes : 0,
							issue_note: v.note,
						});
						flash =
							`Saved: good ${fmt(r.good)}, scrap ${fmt(r.scrap)}, ` +
							`${fmt(r.net_minutes)} min without break. ${fmt(r.remaining)} left on the operation.`;
					}
					this.close_finish();
					this.s.error = "";
					this.s.flash = flash;
					await this.load_state(false);
				} catch (e) {
					if (is_stale(e)) return;
					$err.text(e.message);
				}
			});
		}
	}

	// exposed for the Node test harness (tests/js/generation.test.js)
	frappe.pages[PAGE].ShopfloorTablet = ShopfloorTablet;
})();
