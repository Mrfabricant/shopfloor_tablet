app_name = "shopfloor_tablet"
app_title = "Shopfloor Tablet"
app_publisher = "Sohail"
app_description = "Tab access for employees"
app_email = "sohail@novixcore.com"
app_license = "mit"

# Apps
# ------------------

# required_apps = []

# Each item in the list will be shown as an app in the apps page
# add_to_apps_screen = [
# 	{
# 		"name": "shopfloor_tablet",
# 		"logo": "/assets/shopfloor_tablet/logo.png",
# 		"title": "Shopfloor Tablet",
# 		"route": "/shopfloor_tablet",
# 		"has_permission": "shopfloor_tablet.api.permission.has_app_permission",
# 	}
# ]

# The dock, the rail down the left of the desk, is a document rather than a hook. Author it in
# Manage Dock on a developer-mode site and press Export to App, and it is written to
# `shopfloor_tablet/dock/shopfloor_tablet/shopfloor_tablet.json` for git to carry. An app that ships none has no
# rail: its sidebar gets a switcher in the header instead.
#
# A companion app, one that extends a host app rather than standing on its own, says so with
# `mount_on` on that same record, and its entries are appended to the host's rail. Mounting keeps
# the companion off the apps screen, so it takes precedence over any add_to_apps_screen above.

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/shopfloor_tablet/css/shopfloor_tablet.css"
# app_include_js = "/assets/shopfloor_tablet/js/shopfloor_tablet.js"

# include js, css files in header of web template
# web_include_css = "/assets/shopfloor_tablet/css/shopfloor_tablet.css"
# web_include_js = "/assets/shopfloor_tablet/js/shopfloor_tablet.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "shopfloor_tablet/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
# doctype_js = {"doctype" : "public/js/doctype.js"}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_kanban_js = {"doctype" : "public/js/doctype_kanban.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Svg Icons
# ------------------
# include app icons in desk
# app_include_icons = "shopfloor_tablet/public/icons.svg"

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
# 	"Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# automatically load and sync documents of this doctype from downstream apps
# importable_doctypes = [doctype_1]

# Jinja
# ----------

# add methods and filters to jinja environment
# jinja = {
# 	"methods": "shopfloor_tablet.utils.jinja_methods",
# 	"filters": "shopfloor_tablet.utils.jinja_filters"
# }

# Installation
# ------------

# before_install = "shopfloor_tablet.install.before_install"
# after_install = "shopfloor_tablet.install.after_install"

# Uninstallation
# ------------

# before_uninstall = "shopfloor_tablet.uninstall.before_uninstall"
# after_uninstall = "shopfloor_tablet.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "shopfloor_tablet.utils.before_app_install"
# after_app_install = "shopfloor_tablet.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "shopfloor_tablet.utils.before_app_uninstall"
# after_app_uninstall = "shopfloor_tablet.utils.after_app_uninstall"

# Build
# ------------------
# To hook into the build process

# after_build = "shopfloor_tablet.build.after_build"

# To hook into the build process of other apps
# The list of apps being built is passed as an argument

# after_app_build = "shopfloor_tablet.build.after_app_build"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "shopfloor_tablet.notifications.get_notification_config"

# Awesome Bar
# -----------
# Extra search results: list of dicts with label, description, route, index.
# route: ["List", "ToDo"], "/desk/docs/some/page", or "https://example.com"
# awesomebar_search = ["shopfloor_tablet.search.awesomebar_results"]

# Permissions
# -----------
# Permissions evaluated in scripted ways

# permission_query_conditions = {
# 	"Event": "frappe.desk.doctype.event.event.get_permission_query_conditions",
# }
#
# has_permission = {
# 	"Event": "frappe.desk.doctype.event.event.has_permission",
# }

# Document Events
# ---------------
# Hook on document methods and events

# doc_events = {
# 	"*": {
# 		"on_update": "method",
# 		"on_cancel": "method",
# 		"on_trash": "method"
# 	}
# }

# Scheduled Tasks
# ---------------

# scheduler_events = {
# 	"all": [
# 		"shopfloor_tablet.tasks.all"
# 	],
# 	"daily": [
# 		"shopfloor_tablet.tasks.daily"
# 	],
# 	"hourly": [
# 		"shopfloor_tablet.tasks.hourly"
# 	],
# 	"weekly": [
# 		"shopfloor_tablet.tasks.weekly"
# 	],
# 	"monthly": [
# 		"shopfloor_tablet.tasks.monthly"
# 	],
# }

# Testing
# -------

# before_tests = "shopfloor_tablet.install.before_tests"

# Extend DocType Class
# ------------------------------
#
# Specify custom mixins to extend the standard doctype controller.
# extend_doctype_class = {
# 	"Task": "shopfloor_tablet.custom.task.CustomTaskMixin"
# }

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
# 	"frappe.desk.doctype.event.event.get_events": "shopfloor_tablet.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "shopfloor_tablet.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["shopfloor_tablet.utils.before_request"]
# after_request = ["shopfloor_tablet.utils.after_request"]

# Job Events
# ----------
# before_job = ["shopfloor_tablet.utils.before_job"]
# after_job = ["shopfloor_tablet.utils.after_job"]

# User Data Protection
# --------------------

# user_data_fields = [
# 	{
# 		"doctype": "{doctype_1}",
# 		"filter_by": "{filter_by}",
# 		"redact_fields": ["{field_1}", "{field_2}"],
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_2}",
# 		"filter_by": "{filter_by}",
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_3}",
# 		"strict": False,
# 	},
# 	{
# 		"doctype": "{doctype_4}"
# 	}
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
# 	"shopfloor_tablet.auth.validate"
# ]

# Automatically update python controller files with type annotations for this app.
# export_python_type_annotations = True

# default_log_clearing_doctypes = {
# 	"Logging DocType Name": 30  # days to retain logs
# }

# Translation
# ------------
# List of apps whose translatable strings should be excluded from this app's translations.
# ignore_translatable_strings_from = []

