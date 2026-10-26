frappe.query_reports["Operation Progress"] = {
	filters: [
		{ fieldname: "work_order", label: __("Work Order"), fieldtype: "Link", options: "Work Order" },
		{ fieldname: "operation", label: __("Operation"), fieldtype: "Link", options: "Operation" },
		{ fieldname: "item_code", label: __("Item"), fieldtype: "Link", options: "Item" },
		{
			fieldname: "scope",
			label: __("Job Cards"),
			fieldtype: "Select",
			options: "Not Submitted\nSubmitted\nAll",
			default: "Not Submitted",
		},
		{ fieldname: "only_open", label: __("Only with open entries"), fieldtype: "Check" },
		{
			fieldname: "stale_hours",
			label: __("Highlight open longer than (hours)"),
			fieldtype: "Float",
			default: 12,
		},
	],

	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		const limit = parseFloat(frappe.query_report.get_filter_value("stale_hours")) || 12;
		if (data && data.oldest_open_hours != null && data.oldest_open_hours >= limit) {
			if (["oldest_open_hours", "open_entries", "workers"].includes(column.fieldname)) {
				value = `<span style="color:#c0392b;font-weight:700">${value}</span>`;
			}
		}
		return value;
	},
};
