"""Turn solver pressures at the desks into levels and one comparable layout score."""

import math
from typing import List, Sequence

# Normal speech is about 60 dB at 1 m. The solver's source strength is arbitrary, so every
# pressure is expressed relative to the untreated office's pressure 1 m from the talker.
SPEECH_LEVEL_AT_1M_DB = 60.0
FLOOR_DB = 0.0


def level_db(pressure: float, reference_pressure_1m: float) -> float:
    """Speech level for one band, calibrated so the untreated 1 m point reads 60 dB."""
    if pressure <= 0 or reference_pressure_1m <= 0:
        return FLOOR_DB
    return max(FLOOR_DB, SPEECH_LEVEL_AT_1M_DB + 20.0 * math.log10(pressure / reference_pressure_1m))


def combine_bands(levels_db: Sequence[float]) -> float:
    """Energy average of the per-band levels at one desk."""
    energy = sum(10.0 ** (level / 10.0) for level in levels_db) / len(levels_db)
    return 10.0 * math.log10(energy)


def raw_score(desk_levels_db: Sequence[float]) -> float:
    """Average desk exposure plus a penalty for the worst desk.

    The penalty stops the search from making most desks quiet while leaving one person
    in a very bad spot.
    """
    pressures = [10.0 ** (level / 20.0) for level in desk_levels_db]
    return sum(pressures) / len(pressures) + 0.5 * max(pressures)


def relative_scores(raw: List[float], baseline_raw: float) -> List[float]:
    """Scores scaled so the untreated office is 100."""
    return [100.0 * value / baseline_raw for value in raw]
