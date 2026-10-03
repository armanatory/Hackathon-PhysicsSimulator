"""Public API schemas. Values in surrogate mode are scenario inputs, not measurements."""

from typing import Literal

from pydantic import BaseModel, Field, model_validator


Mode = Literal["surrogate_demo", "allsolve"]


class SampleInput(BaseModel):
    receptor: str = Field(default="streptavidin", min_length=1, max_length=120)
    analyte: str = Field(default="biotin", min_length=1, max_length=120)
    surface_coverage: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Assumed fractional coverage for a synthetic scenario; not inferred from molecular coordinates or binding constants.",
    )


class DesignInput(BaseModel):
    period_nm: float = Field(default=600.0, ge=400.0, le=1000.0)
    pillar_diameter_nm: float = Field(default=250.0, ge=50.0, le=900.0)
    pillar_height_nm: float = Field(default=300.0, ge=50.0, le=1000.0)

    @model_validator(mode="after")
    def validate_geometry(self) -> "DesignInput":
        if self.pillar_diameter_nm >= self.period_nm:
            raise ValueError("pillar_diameter_nm must be smaller than period_nm")
        return self


class DetectorInput(BaseModel):
    noise_std_fraction: float = Field(default=0.01, ge=0.0, le=0.2)


class JobRequest(BaseModel):
    mode: Mode = "surrogate_demo"
    sample: SampleInput = Field(default_factory=SampleInput)
    design: DesignInput = Field(default_factory=DesignInput)
    detector: DetectorInput = Field(default_factory=DetectorInput)
    seed: int = Field(default=0, ge=0, le=4_294_967_295)


class SyntheticResult(BaseModel):
    label: Literal["synthetic_surrogate_demo"] = "synthetic_surrogate_demo"
    wavelength_nm: list[float]
    unbound_response: list[float]
    bound_response: list[float]
    noisy_bound_response: list[float]
    resonance_shift_nm: float
    estimated_surface_coverage: float
    assumed_surface_coverage: float
    units: Literal["arbitrary normalized response"] = "arbitrary normalized response"
    disclaimer: str = (
        "Synthetic toy-model output only. It is not an Allsolve result, an experimental spectrum, "
        "or a validated optical/binding prediction. Optical properties are not inferred from molecular coordinates."
    )


class JobRecord(BaseModel):
    id: str
    status: Literal["completed"] = "completed"
    mode: Literal["surrogate_demo"] = "surrogate_demo"
    result: SyntheticResult
