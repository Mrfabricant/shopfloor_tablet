"""Shopfloor Tablet Settings and the break-time calculation that depends on them."""

import frappe
from frappe.utils import get_datetime, get_system_timezone

from shopfloor_tablet import utils

SETTINGS = "Shopfloor Tablet Settings"


def get_settings():
	return frappe.get_cached_doc(SETTINGS)


def break_config():
	"""(break_start, break_end, system time zone, break time zone) for utils.break_minutes."""
	s = get_settings()
	return (s.break_start, s.break_end, get_system_timezone(), s.break_timezone)


def times_for(from_time, to_time, time_in_mins=None, cfg=None):
	"""(duration, break, net) in minutes for an entry; ``to_time`` may be "now" for open entries."""
	if not (from_time and to_time):
		return 0.0, 0.0, 0.0
	start, end = get_datetime(from_time), get_datetime(to_time)
	if time_in_mins is None:
		time_in_mins = max((end - start).total_seconds() / 60.0, 0.0)
	brk = utils.break_minutes(start, end, *(cfg or break_config()))
	return float(time_in_mins), brk, utils.net_minutes(time_in_mins, brk)
