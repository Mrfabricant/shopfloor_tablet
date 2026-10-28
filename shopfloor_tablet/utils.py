"""Pure helpers (no frappe import) so they can be unit-tested anywhere."""

import datetime
import math
from zoneinfo import ZoneInfo

ISSUE_REASONS = ("Machine setup", "Machine problem", "Waiting for materials", "Other")


class QtyError(ValueError):
	"""A quantity entered on the tablet is not acceptable. The message is shown to the worker."""


def parse_qty(value, label="Quantity"):
	"""Turn tablet input into a non-negative float. Empty means zero."""
	if value is None or (isinstance(value, str) and not value.strip()):
		return 0.0
	try:
		qty = float(str(value).strip().replace(",", "."))
	except (TypeError, ValueError):
		raise QtyError(f"{label} must be a number.") from None
	if math.isnan(qty) or math.isinf(qty):
		raise QtyError(f"{label} must be a number.")
	if qty < 0:
		raise QtyError(f"{label} cannot be negative.")
	return qty


def round_qty(value, precision=3):
	return round(float(value or 0) + 0.0, precision)


def remaining_qty(for_quantity, good_done, precision=3):
	"""Quantity still open on an operation: planned minus good pieces. Scrap does not use it up,
	the scrapped pieces still have to be made."""
	left = round_qty(float(for_quantity or 0) - float(good_done or 0), precision)
	return max(left, 0.0)


def check_finish(good, scrap, scrap_reason, remaining, issue_reason=None, precision=3):
	"""Rules for pressing Finish. Raises QtyError with a message the worker can act on."""
	good = round_qty(good, precision)
	scrap = round_qty(scrap, precision)

	if good <= 0 and scrap <= 0 and not (issue_reason or "").strip():
		raise QtyError("Enter the good quantity or the scrap quantity, or choose an issue reason.")

	if scrap > 0 and not (scrap_reason or "").strip():
		raise QtyError("Choose a scrap reason.")

	if good > round_qty(remaining, precision):
		raise QtyError(
			f"Good quantity ({_fmt(good)}) is more than the remaining quantity "
			f"({_fmt(remaining)}) on this operation."
		)


def check_issue(issue_reason, issue_minutes, net_minutes):
	"""Issue minutes are part of the net working time (break excluded), never more."""
	issue_reason = (issue_reason or "").strip()
	if issue_reason and issue_reason not in ISSUE_REASONS:
		raise QtyError(f"Unknown issue reason {issue_reason}.")

	minutes = round_qty(issue_minutes, 2)
	if minutes < 0:
		raise QtyError("Issue minutes cannot be negative.")
	if minutes > 0 and not issue_reason:
		raise QtyError("Choose an issue reason for the issue minutes.")
	if minutes > round_qty(net_minutes, 2):
		raise QtyError(
			f"Issue minutes ({_fmt(minutes)}) cannot be more than the working time of this entry "
			f"({_fmt(round_qty(net_minutes, 1))} min, break not included)."
		)


# --------------------------------------------------------------------------- break time
def to_time(value):
	"""datetime.time from a time, a timedelta (how frappe returns Time fields) or "HH:MM[:SS]"."""
	if value is None or value == "":
		return None
	if isinstance(value, datetime.time):
		return value
	if isinstance(value, datetime.timedelta):
		secs = int(value.total_seconds()) % 86400
		return datetime.time(secs // 3600, (secs % 3600) // 60, secs % 60)
	parts = [int(float(p)) for p in str(value).strip().split(":")]
	parts += [0] * (3 - len(parts))
	return datetime.time(parts[0], parts[1], parts[2])


def break_minutes(start, end, break_start, break_end, system_tz, break_tz):
	"""Minutes of the daily break window that fall inside [start, end].

	``start``/``end`` are naive datetimes in ``system_tz`` (how frappe stores them). The break
	window is a wall-clock time in ``break_tz`` and is applied to every calendar day the entry
	touches there. All comparisons happen in UTC, so DST days and entries over midnight are exact.
	A window whose end is not after its start runs over midnight into the next day.
	"""
	bs, be = to_time(break_start), to_time(break_end)
	if not (start and end and bs and be) or bs == be:
		return 0.0

	sys_zone, brk_zone = ZoneInfo(system_tz or "UTC"), ZoneInfo(break_tz or system_tz or "UTC")
	utc = datetime.UTC
	s = start.replace(tzinfo=sys_zone).astimezone(utc)
	e = end.replace(tzinfo=sys_zone).astimezone(utc)
	if e <= s:
		return 0.0

	overnight = be <= bs
	# a window starting the day before can still reach into the first day
	day = s.astimezone(brk_zone).date() - datetime.timedelta(days=1 if overnight else 0)
	last = e.astimezone(brk_zone).date()
	total = 0.0
	while day <= last:
		w_start = datetime.datetime.combine(day, bs, tzinfo=brk_zone).astimezone(utc)
		end_day = day + datetime.timedelta(days=1) if overnight else day
		w_end = datetime.datetime.combine(end_day, be, tzinfo=brk_zone).astimezone(utc)
		overlap = (min(e, w_end) - max(s, w_start)).total_seconds()
		if overlap > 0:
			total += overlap
		day += datetime.timedelta(days=1)
	return round(total / 60.0, 3)


def net_minutes(time_in_mins, brk):
	"""Working minutes without the break, never below zero."""
	return max(round(float(time_in_mins or 0) - float(brk or 0), 3), 0.0)


def _fmt(value):
	text = f"{value:.3f}".rstrip("0").rstrip(".")
	return text or "0"
