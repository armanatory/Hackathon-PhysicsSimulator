"""Simulation parameter models."""

from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field


class ContainerShape(str, Enum):
    """Available container shapes for simulation."""

    CAN = "can"  # Standard 330ml beer can
    BOTTLE = "bottle"  # 500ml beer bottle
    PINT = "pint"  # Pint glass (568ml)


class CoolingMethod(str, Enum):
    """Available cooling methods with different heat transfer coefficients."""

    ICE_WATER = "ice_water"  # h=600 W/(m²·K), T=0°C
    REFRIGERATOR = "refrigerator"  # h=10 W/(m²·K), T=4°C
    FREEZER = "freezer"  # h=15 W/(m²·K), T=-18°C
    SALT_ICE = "salt_ice"  # h=800 W/(m²·K), T=-5°C


# Container geometry specifications (radius_m, height_m, wall_thickness_m)
CONTAINER_SPECS = {
    ContainerShape.CAN: {
        "radius": 0.033,  # 33mm radius
        "height": 0.122,  # 122mm height
        "wall_thickness": 0.002,  # 2mm aluminum (thicker for easier meshing)
        "volume_ml": 330,
    },
    ContainerShape.BOTTLE: {
        "radius": 0.035,  # 35mm radius
        "height": 0.230,  # 230mm height
        "wall_thickness": 0.003,  # 3mm glass
        "volume_ml": 500,
    },
    ContainerShape.PINT: {
        "radius": 0.042,  # 42mm radius (average)
        "height": 0.150,  # 150mm height
        "wall_thickness": 0.004,  # 4mm glass
        "volume_ml": 568,
    },
}

# Cooling method specifications
COOLING_SPECS = {
    CoolingMethod.ICE_WATER: {
        "h_submerged": 600.0,  # W/(m²·K)
        "h_exposed": 10.0,  # W/(m²·K)
        "coolant_temp_celsius": 0.0,
    },
    CoolingMethod.REFRIGERATOR: {
        "h_submerged": 10.0,  # Air convection
        "h_exposed": 10.0,
        "coolant_temp_celsius": 4.0,
    },
    CoolingMethod.FREEZER: {
        "h_submerged": 15.0,  # Slightly higher due to fan
        "h_exposed": 15.0,
        "coolant_temp_celsius": -18.0,
    },
    CoolingMethod.SALT_ICE: {
        "h_submerged": 800.0,  # Enhanced convection
        "h_exposed": 10.0,
        "coolant_temp_celsius": -5.0,
    },
}


class SimulationParams(BaseModel):
    """Parameters for a beer cooling simulation."""

    container_shape: ContainerShape = Field(
        default=ContainerShape.CAN,
        description="Shape of the beer container",
    )
    cooling_method: CoolingMethod = Field(
        default=CoolingMethod.ICE_WATER,
        description="Cooling method to use",
    )
    initial_temp_celsius: float = Field(
        default=20.0,
        ge=-20.0,
        le=50.0,
        description="Initial beer temperature in Celsius",
    )
    target_temp_celsius: float = Field(
        default=4.0,
        ge=-20.0,
        le=30.0,
        description="Target drinking temperature in Celsius",
    )
    immersion_level: float = Field(
        default=0.8,
        ge=0.0,
        le=1.0,
        description="Fraction of container submerged (0.0-1.0)",
    )
    simulation_duration_minutes: int = Field(
        default=30,
        ge=1,
        le=120,
        description="Total simulation time in minutes",
    )

    def get_container_specs(self) -> dict:
        """Get the geometry specifications for the selected container."""
        return CONTAINER_SPECS[self.container_shape]

    def get_cooling_specs(self) -> dict:
        """Get the cooling specifications for the selected method."""
        return COOLING_SPECS[self.cooling_method]


class SimulationResponse(BaseModel):
    """Response when starting a simulation."""

    simulation_id: str
    project_id: str
    status: str = "started"
    message: str = "Simulation started successfully"


class SimulationStatus(BaseModel):
    """Current status of a running simulation."""

    simulation_id: str
    status: str  # "pending", "running", "completed", "failed"
    progress: float = Field(ge=0.0, le=100.0)  # Percentage
    current_time_seconds: Optional[float] = None
    current_temperature_celsius: Optional[float] = None
    message: Optional[str] = None


class TemperaturePoint(BaseModel):
    """A single temperature measurement at a point in time."""

    time_seconds: float
    temperature_celsius: float


class SimulationResults(BaseModel):
    """Complete results of a simulation."""

    simulation_id: str
    status: str
    temperature_history: List[TemperaturePoint]
    time_to_target_seconds: Optional[float] = None
    final_temperature_celsius: float
    total_simulation_time_seconds: float
    parameters: SimulationParams
