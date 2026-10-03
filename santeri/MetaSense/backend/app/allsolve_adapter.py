"""Guardrail until a verified optical solver workflow is specified."""

from .config import AllsolveConfig


class AllsolvePhysicsNotImplemented(NotImplementedError):
    pass


def start_allsolve_job(config: AllsolveConfig) -> None:
    config.validate()
    raise AllsolvePhysicsNotImplemented(
        "Allsolve optical simulation is pending verified geometry, materials, excitation, "
        "boundary conditions, meshing, and output definitions"
    )
