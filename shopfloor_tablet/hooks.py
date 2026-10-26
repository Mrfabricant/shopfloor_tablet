app_name = "shopfloor_tablet"
app_title = "Shopfloor Tablet"
app_publisher = "Shopfloor Tablet"
app_description = "Simple tablet screen for workers to record start/finish time, good and scrap quantity on ERPNext Job Cards"
app_email = "info@example.com"
app_license = "unlicense"

required_apps = ["frappe", "erpnext"]

# Install / migrate
# -----------------
before_install = "shopfloor_tablet.setup.install.before_install"
after_install = "shopfloor_tablet.setup.install.after_install"
after_migrate = "shopfloor_tablet.setup.install.after_migrate"

# Job Card behaviour for tablet entries (see overrides/job_card.py):
#  - no machine-overlap rejection for tablet rows (several workers, same machine)
#  - no operation-sequence check for cards with tablet rows (parallel operations)
#  - scrap on the header = sum of per-entry scrap
#  - pending qty is set at submit so ERPNext's own quantity check passes
override_doctype_class = {
	"Job Card": "shopfloor_tablet.overrides.job_card.ShopfloorJobCard",
}
