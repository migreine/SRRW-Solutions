"""Organiser constraints workbook loader (data/challenge2_operational_constraints.xlsx).

rules_of_play: "Use the limits in this workbook. Any limit you change must be stated in your demo."
docs/constraints.md maps every workbook limit to where it is used and lists our deviations.

Shared DATA only (no rule logic): the scenario builder, the rules engine and the independent
reviewer all read the same values from here, so engine and reviewer cannot drift apart. The
workbook is read once (lru_cache). Every value is tagged source "assumed" with NOTE: the organisers
label the airport limits SYNTHETIC planning limits, and none of the values are measured.

- airport_capacity (header on row 3): per-airport active_runways, gates, max_runway_ops_per_hour,
  min_turnaround_min, spare_gates_at_any_time. Unlisted airports get DEFAULT_SIZE_CLASS's row.
  Arrival capacity = max_runway_ops_per_hour * ARRIVAL_SHARE (assumed 50/50 arrivals/departures;
  the column is read as an airport-wide total: 90 ops/h over 4 runways at a large hub).
- wake_separation: (leader, follower) -> NM; any pair not listed -> the "Any other pair" value.
- fuel_and_crew: numbers parsed from the value text (final reserve 30 min, contingency 5%, spare
  fuel on arrival 45 min, crew max duty 13 h, ground shift 8 h at 1.5x overtime, gate notice 20 min).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import pandas as pd

from src.schemas import Tagged

WORKBOOK = Path(__file__).resolve().parents[1] / "data" / "challenge2_operational_constraints.xlsx"
SOURCE = "assumed"
NOTE = "organiser workbook (synthetic planning limit)"
CITATION = "organiser workbook"
# Assumed: max_runway_ops_per_hour counts arrivals AND departures; half are arrivals.
ARRIVAL_SHARE = 0.5
# Assumed default for an airport the workbook does not list: the smallest class (most conservative).
DEFAULT_SIZE_CLASS = "Non-hub"

# Builder/engine wake codes -> workbook category names.
_CATEGORY = {"J": "Super", "SUPER": "Super", "H": "Heavy", "L": "Large", "S": "Small"}


@dataclass(frozen=True)
class AirportLimits:
    iata: str
    size_class: str
    active_runways: int
    gates: int
    max_runway_ops_per_hour: int
    min_turnaround_min: int
    spare_gates: int
    listed: bool  # False: default row for an airport the workbook does not list

    @property
    def arrival_capacity_per_hour(self) -> float:
        return self.max_runway_ops_per_hour * ARRIVAL_SHARE

    def tagged(self, field: str) -> Tagged:
        value = self.arrival_capacity_per_hour if field == "arrival_capacity_per_hour" else getattr(self, field)
        where = self.iata if self.listed else f"{self.iata} not listed, {DEFAULT_SIZE_CLASS} default"
        return Tagged(value=value, source=SOURCE, note=f"{NOTE}: {field} ({where})")


def _number(text) -> float:
    m = re.search(r"\d[\d,]*(?:\.\d+)?", str(text))
    if not m:
        raise ValueError(f"no number in workbook value {text!r}")
    return float(m.group(0).replace(",", ""))


def _category(name) -> str:
    return str(name).split("(")[0].strip().capitalize()


@lru_cache(maxsize=1)
def load() -> dict:
    """Read the four sheets once. Raises if a sheet, column or fuel/crew row is missing."""
    sheets = pd.read_excel(WORKBOOK, sheet_name=None, header=None)

    cap = pd.read_excel(WORKBOOK, sheet_name="airport_capacity", header=2).dropna(subset=["IATA_CODE"])
    airports = {}
    for r in cap.itertuples(index=False):
        airports[str(r.IATA_CODE)] = AirportLimits(
            iata=str(r.IATA_CODE), size_class=str(r.size_class), active_runways=int(r.active_runways),
            gates=int(r.gates), max_runway_ops_per_hour=int(r.max_runway_ops_per_hour),
            min_turnaround_min=int(r.min_turnaround_min), spare_gates=int(r.spare_gates_at_any_time),
            listed=True,
        )
    proto = next(a for a in airports.values() if a.size_class == DEFAULT_SIZE_CLASS)

    wake, other = {}, None
    for leader, follower, nm, *_ in sheets["wake_separation"].iloc[3:].itertuples(index=False):
        if pd.isna(leader):
            continue
        if str(leader).lower().startswith("any other"):
            other = float(nm)
        else:
            wake[(_category(leader), _category(follower))] = float(nm)
    if other is None:
        raise ValueError("wake_separation: no 'Any other pair' row")

    fc = {str(r[0]).strip().lower(): str(r[1]) for r in sheets["fuel_and_crew"].iloc[1:].itertuples(index=False)}
    shift = fc["ground crew shift"]
    fuel_crew = {
        "final_reserve_min": _number(fc["final fuel reserve"]),
        "contingency_fraction": _number(fc["contingency fuel"]) / 100,
        "holding_burn_narrowbody_kg_h": _number(fc["holding fuel burn (narrowbody)"]),
        "holding_burn_widebody_kg_h": _number(fc["holding fuel burn (widebody)"]),
        "spare_fuel_on_arrival_min": _number(fc["assumed spare fuel on arrival"]),
        "crew_max_duty_min": _number(fc["flight crew max duty"]) * 60,
        "ground_shift_min": _number(shift) * 60,
        "ground_overtime_multiplier": float(re.search(r"(\d+(?:\.\d+)?)x", shift).group(1)),
        "gate_change_notice_min": _number(fc["gate change notice"]),
    }
    rules = {str(t).strip(): str(d) for t, d in sheets["rules_of_play"].iloc[1:].itertuples(index=False)}
    return {"airports": airports, "default": proto, "wake": wake, "wake_other_nm": other,
            "fuel_crew": fuel_crew, "rules_of_play": rules}


def airport(iata: str) -> AirportLimits:
    """Per-airport limits; an unlisted airport gets the DEFAULT_SIZE_CLASS row (listed=False)."""
    wb = load()
    hit = wb["airports"].get(str(iata))
    if hit is not None:
        return hit
    d = wb["default"]
    return AirportLimits(str(iata), d.size_class, d.active_runways, d.gates, d.max_runway_ops_per_hour,
                         d.min_turnaround_min, d.spare_gates, listed=False)


def wake_sep_nm(leader: str, follower: str) -> float:
    """Workbook separation in NM. Accepts codes (H/L/S/J) or names; unlisted pair -> 'Any other pair'."""
    wb = load()
    lead = _CATEGORY.get(str(leader).strip().upper(), _category(leader))
    foll = _CATEGORY.get(str(follower).strip().upper(), _category(follower))
    return wb["wake"].get((lead, foll), wb["wake_other_nm"])


def fuel_crew(key: str) -> float:
    return load()["fuel_crew"][key]
