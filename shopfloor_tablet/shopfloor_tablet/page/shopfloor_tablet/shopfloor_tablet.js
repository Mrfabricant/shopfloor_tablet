(function () {
	const PAGE = "shopfloor-tablet";
	const API = "shopfloor_tablet.api.";
	const IDLE_SECONDS = 90; // shared tablet: go back to the name list after this much inactivity
	const REFRESH_SECONDS = 30;

	const esc = (v) => frappe.utils.escape_html(v == null ? "" : String(v));

	const fmt = (n) => {
		const v = parseFloat(Number(n || 0).toFixed(3));
		return String(v);
	};

	const pad = (n) => String(n).padStart(2, "0");
	const clock = (secs) => {
		secs = Math.max(0, Math.floor(secs));
		return `${pad(Math.floor(secs / 3600))}:${pad(Math.floor((secs % 3600) / 60))}:${pad(secs % 60)}`;
	};

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
			};
			this.lastActivity = Date.now();
			this.lastRefresh = Date.now();
			this.searchTimer = null;

			this.bind();
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

			this.$root.on("change", "[data-role=machine]", function () {
				me.s.machine = $(this).val();
			});

			this.$root.on("input", "[data-role=good], [data-role=scrap]", () => this.update_finish_hint());
		}

		act(action, $el) {
			switch (action) {
				case "pick-worker":
					return this.pick_worker($el.attr("data-emp"));
				case "change-worker":
					return this.show_picker();
				case "select-op":
					return this.select_op($el.attr("data-jc"));
				case "start":
					return this.start();
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
				this.s.employee = null;
				this.s.selected = null;
				this.s.search = "";
				this.s.flash = "";
				this.s.error = "";
				this.render_picker();
				return;
			}

			// quiet refresh so other workers' progress shows up
			if (
				this.s.employee &&
				!modal_open &&
				!this.s.busy &&
				(Date.now() - this.lastRefresh) / 1000 > REFRESH_SECONDS
			) {
				this.load_state(true);
			}
		}

		async load_state(quiet) {
			if (!this.s.employee) return;
			this.lastRefresh = Date.now();
			try {
				const st = await this.call("get_state", {
					employee: this.s.employee.name,
					search: this.s.search || "",
				});
				this.s.active = st.active || [];
				this.s.operations = st.operations || [];
				this.s.loadedAt = Date.now();
				if (this.s.selected && !this.s.operations.find((o) => o.job_card === this.s.selected)) {
					this.s.selected = null;
				}
				if (quiet && this.$root.find(".sft-ops").length && !this.s.active.length) {
					this.render_ops();
					this.render_startbar();
				} else {
					this.render_main();
				}
			} catch (e) {
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

		pick_worker(name) {
			const w = this.s.workers.find((x) => x.name === name);
			if (!w) return;
			this.s.employee = w;
			this.s.selected = null;
			this.s.search = "";
			this.s.flash = "";
			this.s.error = "";
			this.render_loading();
			this.load_state(false);
		}

		show_picker() {
			this.s.employee = null;
			this.s.selected = null;
			this.s.flash = "";
			this.s.error = "";
			this.render_picker();
		}

		render_main() {
			const emp = this.s.employee;
			if (!emp) return this.render_picker();

			let body = "";
			if (this.s.active.length) {
				body = this.s.active.map((a) => this.active_card(a)).join("");
			} else {
				body = `
					<div class="sft-title">Start work</div>
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
				this.render_ops();
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

		active_card(a) {
			return `
				<div class="sft-card sft-active">
					<div class="sft-active-label">Working now</div>
					<div class="sft-op-title">${esc(a.operation)}</div>
					<div class="sft-op-sub">${esc(a.item_name)} &middot; ${esc(a.work_order)}</div>
					<div class="sft-op-sub">Machine: ${esc(a.machine || "-")} &middot; started ${esc(a.started_at)}</div>
					<div class="sft-timer" data-elapsed="${a.elapsed_seconds}">${clock(a.elapsed_seconds)}</div>
					<div class="sft-op-sub">Left on this operation: <b>${fmt(a.remaining)}</b> ${esc(a.uom || "")}</div>
					<button class="sft-btn sft-btn-finish" data-action="finish-open" data-row="${esc(a.row_name)}">FINISH</button>
					<button class="sft-btn sft-btn-link" data-action="cancel-start" data-row="${esc(a.row_name)}">Started by mistake - cancel</button>
				</div>`;
		}

		render_ops() {
			const $ops = this.$root.find(".sft-ops");
			if (!$ops.length) return;

			if (!this.s.operations.length) {
				$ops.html('<div class="sft-empty">No open operations. Work orders are created in ERPNext.</div>');
				return;
			}

			let html = "";
			let lastWo = null;
			for (const o of this.s.operations) {
				if (o.work_order !== lastWo) {
					lastWo = o.work_order;
					html += `<div class="sft-group">${esc(o.work_order)} &middot; ${esc(o.item_name)}</div>`;
				}
				const sel = this.s.selected === o.job_card ? " sft-selected" : "";
				const working = (o.working_now || []).length
					? `<div class="sft-op-sub sft-working">Working now: ${esc(o.working_now.join(", "))}</div>`
					: "";
				html += `
					<div class="sft-card sft-op${sel}" data-action="select-op" data-jc="${esc(o.job_card)}">
						<div class="sft-op-main">
							<div class="sft-op-title">${esc(o.operation)}</div>
							<div class="sft-op-sub">Machine: ${esc(o.machine || "-")}</div>
							${working}
						</div>
						<div class="sft-op-qty">
							<div class="sft-qty-big">${fmt(o.remaining)}</div>
							<div class="sft-op-sub">left of ${fmt(o.required)} ${esc(o.uom || "")}</div>
						</div>
					</div>`;
			}
			$ops.html(html);
		}

		select_op(jc) {
			const op = this.s.operations.find((o) => o.job_card === jc);
			if (!op) return;
			this.s.selected = jc;
			this.s.machine = op.machine || "";
			this.s.error = "";
			this.$root.find(".sft-op").removeClass("sft-selected");
			this.$root.find(`.sft-op[data-jc="${CSS.escape(jc)}"]`).addClass("sft-selected");
			this.render_banner();
			this.render_startbar();
		}

		render_startbar() {
			const $bar = this.$root.find(".sft-startbar");
			if (!$bar.length) return;

			const op = this.s.operations.find((o) => o.job_card === this.s.selected);
			if (!op) {
				$bar.empty();
				return;
			}

			const machines = this.s.machines.slice();
			if (op.machine && !machines.includes(op.machine)) machines.unshift(op.machine);
			const options = ['<option value="">Choose machine</option>']
				.concat(
					machines.map(
						(m) => `<option value="${esc(m)}"${m === this.s.machine ? " selected" : ""}>${esc(m)}</option>`
					)
				)
				.join("");

			$bar.html(`
				<div class="sft-startbar-info">
					<b>${esc(op.operation)}</b> &middot; ${esc(op.work_order)}
				</div>
				<label class="sft-label">Machine</label>
				<select class="sft-input sft-select" data-role="machine">${options}</select>
				<button class="sft-btn sft-btn-start" data-action="start">START</button>
			`);
		}

		// ------------------------------------------------------------ actions
		async run(fn) {
			if (this.s.busy) return;
			this.s.busy = true;
			this.$root.addClass("sft-busy");
			try {
				await fn();
			} finally {
				this.s.busy = false;
				this.$root.removeClass("sft-busy");
			}
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
					const r = await this.call("start", {
						employee: this.s.employee.name,
						job_card: op.job_card,
						machine: this.s.machine,
					});
					this.s.active = r.active || [];
					this.s.selected = null;
					this.s.loadedAt = Date.now();
					this.s.error = "";
					this.s.flash = "Started. The time is running.";
					this.render_main();
				} catch (e) {
					this.s.error = e.message;
					this.render_banner();
					this.load_state(true);
				}
			});
		}

		cancel_start(row) {
			frappe.confirm("Cancel this start? Nothing will be recorded.", () =>
				this.run(async () => {
					try {
						const r = await this.call("cancel_start", {
							employee: this.s.employee.name,
							row_name: row,
						});
						this.s.active = r.active || [];
						this.s.flash = "Start cancelled.";
						this.s.error = "";
						await this.load_state(false);
					} catch (e) {
						this.s.error = e.message;
						this.render_banner();
					}
				})
			);
		}

		open_finish(row) {
			const a = this.s.active.find((x) => x.row_name === row);
			if (!a) return;
			this.s.finishing = a;

			const reasons = ['<option value="">Choose reason</option>']
				.concat(this.s.reasons.map((r) => `<option value="${esc(r)}">${esc(r)}</option>`))
				.join("");

			this.$root.find(".sft-modal").remove();
			this.$root.append(`
				<div class="sft-modal">
					<div class="sft-modal-box">
						<div class="sft-title">Finish work</div>
						<div class="sft-op-title">${esc(a.operation)}</div>
						<div class="sft-op-sub">${esc(a.item_name)} &middot; ${esc(a.work_order)}</div>
						<div class="sft-op-sub">Left on this operation: <b>${fmt(a.remaining)}</b> ${esc(a.uom || "")}</div>

						<label class="sft-label">Good quantity</label>
						<input class="sft-input sft-qtyinput" data-role="good" type="number" inputmode="decimal"
							min="0" step="any" placeholder="0">
						<button class="sft-btn sft-btn-ghost sft-small" data-action="all-remaining">All remaining is good</button>

						<label class="sft-label">Scrap quantity</label>
						<input class="sft-input sft-qtyinput" data-role="scrap" type="number" inputmode="decimal"
							min="0" step="any" placeholder="0">

						<div class="sft-reason sft-hidden">
							<label class="sft-label">Scrap reason</label>
							<select class="sft-input sft-select" data-role="reason">${reasons}</select>
						</div>

						<div class="sft-hint"></div>
						<div class="sft-modal-error"></div>

						<div class="sft-modal-buttons">
							<button class="sft-btn sft-btn-ghost" data-action="modal-close">Back</button>
							<button class="sft-btn sft-btn-finish" data-action="modal-submit">FINISH</button>
						</div>
					</div>
				</div>`);
			this.$root.find("[data-role=good]").trigger("focus");
		}

		close_finish() {
			this.s.finishing = null;
			this.$root.find(".sft-modal").remove();
		}

		fill_all_remaining() {
			if (!this.s.finishing) return;
			this.$root.find("[data-role=good]").val(fmt(this.s.finishing.remaining));
			this.$root.find("[data-role=scrap]").val("");
			this.update_finish_hint();
		}

		finish_values() {
			const num = (sel) => {
				const v = parseFloat(String(this.$root.find(sel).val() || "").replace(",", "."));
				return isNaN(v) ? 0 : v;
			};
			return {
				good: num("[data-role=good]"),
				scrap: num("[data-role=scrap]"),
				reason: this.$root.find("[data-role=reason]").val() || "",
			};
		}

		update_finish_hint() {
			const a = this.s.finishing;
			if (!a) return;
			const v = this.finish_values();
			this.$root.find(".sft-reason").toggleClass("sft-hidden", !(v.scrap > 0));
			const total = Math.round((v.good + v.scrap) * 1000) / 1000;
			const left = Math.round((a.remaining - total) * 1000) / 1000;
			const $h = this.$root.find(".sft-hint");
			if (left < 0) {
				$h.addClass("sft-hint-bad").text(`More than the ${fmt(a.remaining)} left on this operation.`);
			} else {
				$h.removeClass("sft-hint-bad").text(`After this: ${fmt(left)} left.`);
			}
		}

		submit_finish() {
			const a = this.s.finishing;
			if (!a) return;
			const v = this.finish_values();
			const $err = this.$root.find(".sft-modal-error");
			$err.text("");

			if (v.good < 0 || v.scrap < 0) return $err.text("Quantities cannot be negative.");
			if (v.good <= 0 && v.scrap <= 0) return $err.text("Enter the good quantity or the scrap quantity.");
			if (v.scrap > 0 && !v.reason) return $err.text("Choose a scrap reason.");
			if (Math.round((v.good + v.scrap) * 1000) > Math.round(a.remaining * 1000)) {
				return $err.text(`More than the ${fmt(a.remaining)} left on this operation.`);
			}

			return this.run(async () => {
				try {
					const r = await this.call("finish", {
						employee: this.s.employee.name,
						row_name: a.row_name,
						good_qty: v.good,
						scrap_qty: v.scrap,
						scrap_reason: v.scrap > 0 ? v.reason : "",
					});
					this.close_finish();
					this.s.error = "";
					this.s.flash =
						`Saved: good ${fmt(r.good)}, scrap ${fmt(r.scrap)}, ` +
						`${fmt(r.minutes)} min. ${fmt(r.remaining)} left on the operation.`;
					await this.load_state(false);
				} catch (e) {
					$err.text(e.message);
				}
			});
		}
	}
})();
