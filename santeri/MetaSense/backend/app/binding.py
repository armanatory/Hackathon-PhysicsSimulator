"""Binding scenario metadata, with no affinity or kinetics asserted."""

from dataclasses import dataclass

from .models import SampleInput


@dataclass(frozen=True)
class BindingScenario:
    receptor: str
    analyte: str
    assumed_surface_coverage: float


def scenario_from_input(sample: SampleInput) -> BindingScenario:
    """Carry the user's assumed occupancy into the toy model without deriving it."""
    return BindingScenario(
        receptor=sample.receptor,
        analyte=sample.analyte,
        assumed_surface_coverage=sample.surface_coverage,
    )
