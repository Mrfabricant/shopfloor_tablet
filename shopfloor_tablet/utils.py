"""Pure helpers (no frappe import) so they can be unit-tested anywhere."""

import math


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


def remaining_qty(for_quantity, good_done, scrap_done, precision=3):
	"""Quantity still open on an operation. Good and scrap both use up quantity."""
	left = round_qty(float(for_quantity or 0) - float(good_done or 0) - float(scrap_done or 0), precision)
	return max(left, 0.0)


def check_finish(good, scrap, scrap_reason, remaining, precision=3):
	"""Rules for pressing Finish. Raises QtyError with a message the worker can act on."""
	good = round_qty(good, precision)
	scrap = round_qty(scrap, precision)

	if good <= 0 and scrap <= 0:
		raise QtyError("Enter the good quantity or the scrap quantity.")

	if scrap > 0 and not (scrap_reason or "").strip():
		raise QtyError("Choose a scrap reason.")

	if round_qty(good + scrap, precision) > round_qty(remaining, precision):
		raise QtyError(
			f"Good ({_fmt(good)}) plus scrap ({_fmt(scrap)}) is more than the "
			f"remaining quantity ({_fmt(remaining)}) on this operation."
		)


def _fmt(value):
	text = f"{value:.3f}".rstrip("0").rstrip(".")
	return text or "0"
