"""Pure training math: unit conversion, estimated 1RM, analytics timeframes."""

from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

LBS_PER_KG = Decimal("2.20462262")
CENTS = Decimal("0.01")
TIMEFRAME_DAYS = {"1m": 30, "2m": 60, "3m": 90, "6m": 182, "year": 365}
TIMEFRAMES = [*TIMEFRAME_DAYS, "lifetime"]


def quantize(value, places=CENTS):
    if isinstance(value, float):
        value = repr(value)
    return Decimal(value).quantize(Decimal(places), rounding=ROUND_HALF_UP)


def to_lbs(weight, unit):
    weight = Decimal(weight)
    return quantize(weight if unit == "lbs" else weight * LBS_PER_KG)


def from_lbs(weight_lbs, unit):
    weight_lbs = Decimal(weight_lbs)
    return quantize(weight_lbs if unit == "lbs" else weight_lbs / LBS_PER_KG)


def epley_1rm(weight, reps):
    """Epley estimated one-rep max: ``weight * (1 + reps / 30)``."""
    return quantize(Decimal(weight) * (1 + Decimal(reps) / Decimal(30)))


def timeframe_start(timeframe, today, first_day=None):
    """First calendar day covered by ``timeframe`` (inclusive)."""
    if timeframe == "lifetime":
        return min(first_day, today) if first_day else today
    return today - timedelta(days=TIMEFRAME_DAYS[timeframe] - 1)
