frappe.query_reports["Worker Time Entries"] = {
	filters: [
		{
			fieldname: "from_date",
			label: __("From Date"),
			fieldtype: "Date",
			default: frappe.datetime.add_days(frappe.datetime.get_today(), -7),
		},
		{
			fieldname: "to_date",
			label: __("To Date"),
			fieldtype: "Date",
			default: frappe.datetime.get_today(),
		},
		{ fieldname: "employee", label: __("Employee"), fieldtype: "Link", options: "Employee" },
		{ fieldname: "work_order", label: __("Work Order"), fieldtype: "Link", options: "Work Order" },
		{ fieldname: "operation", label: __("Operation"), fieldtype: "Link", options: "Operation" },
		{ fieldname: "machine", label: __("Machine"), fieldtype: "Link", options: "Workstation" },
		{
			fieldname: "entry_status",
			label: __("Entry"),
			fieldtype: "Select",
			options: "\nOpen\nFinished",
		},
		{
			fieldname: "entry_type",
			label: __("Entry Type"),
			fieldtype: "Select",
			options: "\nNormal\nReplacement",
		},
	],

	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (data && data.entry_status === "Open" && column.fieldname === "entry_status") {
			value = `<span style="color:#b45309;font-weight:700">${value}</span>`;
		}
		if (data && data.entry_type === "Replacement" && column.fieldname === "entry_type") {
			value = `<span style="color:#5a5fa8;font-weight:700">${value}</span>`;
		}
		return value;
	},
};
