"""Explicit optical assumptions and bounded inputs for real cloud optimization."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictInput(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, str_strip_whitespace=True)


class LiquidInput(StrictInput):
    label: str = Field(min_length=1, max_length=80)
    n: float = Field(ge=1.0, le=1.8, strict=True)

    @model_validator(mode="after")
    def printable_label(self) -> "LiquidInput":
        if not self.label.isprintable():
            raise ValueError("Liquid labels must be printable text")
        return self


class NumericBounds(StrictInput):
    min: float = Field(strict=True)
    max: float = Field(strict=True)

    @model_validator(mode="after")
    def ordered(self) -> "NumericBounds":
        if self.min > self.max:
            raise ValueError("A lower bound must not exceed its upper bound")
        return self


class GratingBounds(StrictInput):
    period_nm: NumericBounds = Field(default_factory=lambda: NumericBounds(min=450, max=550))
    fill_factor: NumericBounds = Field(default_factory=lambda: NumericBounds(min=0.3, max=0.7))
    ridge_height_nm: NumericBounds = Field(default_factory=lambda: NumericBounds(min=80, max=220))

    @model_validator(mode="after")
    def supported_domain(self) -> "GratingBounds":
        for bounds, lower, upper, name in [
            (self.period_nm, 100, 1000, "period_nm"),
            (self.fill_factor, 0.05, 0.95, "fill_factor"),
            (self.ridge_height_nm, 20, 800, "ridge_height_nm"),
        ]:
            if bounds.min < lower or bounds.max > upper:
                raise ValueError(f"{name} bounds must be within {lower}..{upper}")
        return self


class DiscriminatorRequest(StrictInput):
    schema_version: Literal[1] = 1
    liquids: list[LiquidInput] = Field(
        default_factory=lambda: [
            LiquidInput(label="Water", n=1.33),
            LiquidInput(label="Glycerol–water", n=1.38),
        ],
        min_length=2,
        max_length=2,
    )
    wavelength_min_nm: float = Field(default=900, ge=800, le=1600, strict=True)
    wavelength_max_nm: float = Field(default=1100, ge=800, le=1600, strict=True)
    wavelength_samples: int = Field(default=11, ge=3, le=41, strict=True)
    geometry_bounds: GratingBounds = Field(default_factory=GratingBounds)
    film_thickness_nm: float = Field(default=100, ge=50, le=250, strict=True)
    minimum_feature_nm: float = Field(default=50, ge=20, le=100, strict=True)
    candidate_count: int = Field(default=24, ge=1, le=128, strict=True)
    max_parallel_cores: int = Field(default=64, ge=4, le=256, strict=True)
    seed: int = Field(default=42, ge=0, le=4_294_967_295, strict=True)
    objective: Literal["max_abs_reflectance_contrast"] = "max_abs_reflectance_contrast"

    @model_validator(mode="after")
    def feasible_search(self) -> "DiscriminatorRequest":
        a, b = self.liquids
        if a.label.casefold() == b.label.casefold():
            raise ValueError("Liquid labels must differ")
        if a.n == b.n:
            raise ValueError("The two explicit liquid refractive indices must differ")
        if self.wavelength_min_nm >= self.wavelength_max_nm:
            raise ValueError("wavelength_min_nm must be below wavelength_max_nm")
        geometry = self.geometry_bounds
        if geometry.period_nm.min * geometry.fill_factor.min + 1e-9 < self.minimum_feature_nm:
            raise ValueError("The narrowest ridge within the bounds is below minimum_feature_nm")
        if geometry.period_nm.min * (1 - geometry.fill_factor.max) + 1e-9 < self.minimum_feature_nm:
            raise ValueError("The narrowest gap within the bounds is below minimum_feature_nm")
        if geometry.ridge_height_nm.min < self.minimum_feature_nm:
            raise ValueError("The smallest ridge height is below minimum_feature_nm")
        if geometry.period_nm.max * max(a.n, b.n, 1.46) > 0.9 * self.wavelength_min_nm:
            raise ValueError("The period bounds violate the 0.9 subwavelength cutoff margin")
        return self
