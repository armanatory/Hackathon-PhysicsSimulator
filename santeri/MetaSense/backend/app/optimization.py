"""Explicitly synthetic design ranking; physical inverse design remains unspecified."""

from collections.abc import Iterable

from .models import DesignInput
from .optics import toy_parameters


def rank_toy_designs(candidates: Iterable[DesignInput]) -> list[DesignInput]:
    """Sort candidates by toy shift coefficient for interface prototyping only."""
    return sorted(candidates, key=lambda design: toy_parameters(design)[1], reverse=True)


def optimize_allsolve_design() -> None:
    """Reserved for a verified solver workflow and detailed acceptance criteria."""
    raise NotImplementedError("Allsolve optical inverse design has not been implemented")
