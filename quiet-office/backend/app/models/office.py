"""Office layout and optimization models."""

from typing import List, Literal, Optional, Tuple

from pydantic import BaseModel, Field, model_validator

SPEED_OF_SOUND = 343.0  # m/s, air at 20 °C
AIR_DENSITY = 1.225  # kg/m³


class Point(BaseModel):
    """A position on the floor plan in metres. Origin is the top-left corner of the room."""

    x: float
    y: float


class Slot(BaseModel):
    """A place where one acoustic screen is allowed to stand."""

    id: int
    x: float = Field(description="Centre of the screen, metres")
    y: float = Field(description="Centre of the screen, metres")
    orientation: Literal["h", "v"] = Field(description="h runs along x, v runs along y")
    label: str = ""


class Office(BaseModel):
    """An open-plan office seen from above. The room is any simple polygon."""

    outline: List[Point] = Field(
        min_length=3,
        max_length=40,
        description="Room corners in order, metres. The last corner joins back to the first.",
    )
    source: Point = Field(description="Where the conversation happens")
    desks: List[Point] = Field(min_length=1, max_length=40)
    slots: List[Slot] = Field(min_length=1, max_length=40)

    @model_validator(mode="after")
    def _check_size(self) -> "Office":
        min_x, min_y, max_x, max_y = self.bounds
        if max_x - min_x < 1.0 or max_y - min_y < 1.0:
            raise ValueError("The room must be at least 1 m in each direction")
        if max_x - min_x > 60.0 or max_y - min_y > 60.0:
            raise ValueError("The room must be at most 60 m in each direction")
        if len({slot.id for slot in self.slots}) != len(self.slots):
            raise ValueError("Screen position ids must be unique")
        return self

    @property
    def bounds(self) -> Tuple[float, float, float, float]:
        """Bounding box of the room: (min_x, min_y, max_x, max_y)."""
        xs = [p.x for p in self.outline]
        ys = [p.y for p in self.outline]
        return min(xs), min(ys), max(xs), max(ys)


def default_office() -> Office:
    """The demo office: 16 desks in four clusters and a conversation at the coffee point."""
    desks = [
        Point(x=cx + dx, y=cy + dy)
        for cx, cy in [(5.0, 2.0), (10.5, 2.0), (4.4, 7.0), (10.5, 7.0)]
        for dx, dy in [(0.0, 0.0), (1.6, 0.0), (0.0, 1.4), (1.6, 1.4)]
    ]
    slots = [
        (3.4, 5.0, "v", "Directly in front of the coffee point"),
        (3.4, 3.2, "v", "Beside the coffee point, north side"),
        (3.4, 6.8, "v", "Beside the coffee point, south side"),
        (5.8, 4.4, "h", "Along the aisle edge of the near north desks"),
        (5.2, 5.9, "h", "Along the aisle edge of the near south desks"),
        (8.4, 2.7, "v", "Centre aisle, north end"),
        (8.4, 5.0, "v", "Centre aisle, middle"),
        (8.4, 7.7, "v", "Centre aisle, south end"),
        (11.3, 4.5, "h", "Along the aisle edge of the far north desks"),
        (11.3, 5.9, "h", "Along the aisle edge of the far south desks"),
        (9.6, 2.7, "v", "In front of the far north desks"),
        (9.6, 7.7, "v", "In front of the far south desks"),
    ]
    return Office(
        outline=[Point(x=0.0, y=0.0), Point(x=16.0, y=0.0), Point(x=16.0, y=10.0), Point(x=0.0, y=10.0)],
        source=Point(x=2.2, y=5.0),
        desks=desks,
        slots=[
            Slot(id=i, x=x, y=y, orientation=o, label=label)
            for i, (x, y, o, label) in enumerate(slots)
        ],
    )


class OptimizationParams(BaseModel):
    """What the user asks for: how many screens, and how to search."""

    office: Office = Field(default_factory=default_office)
    n_screens: int = Field(default=3, ge=1, le=3, description="Screens to place")
    screen_length_m: float = Field(default=1.8, gt=0.3, le=4.0)
    screen_thickness_m: float = Field(default=0.1, gt=0.02, le=0.5)
    frequencies_hz: List[float] = Field(
        default=[250.0, 500.0],
        min_length=1,
        max_length=4,
        description="Speech bands to simulate. Higher bands need a much finer mesh.",
    )
    strategy: Literal["greedy", "exhaustive"] = Field(
        default="greedy",
        description=(
            "greedy places one screen at a time and keeps the best (about 12+11+10 layouts); "
            "exhaustive tries every combination (220 layouts for 3 screens in 12 slots)"
        ),
    )


class LayoutResult(BaseModel):
    """One simulated layout."""

    slot_ids: List[int]
    desk_levels_db: List[float] = Field(description="Speech level at each desk, same order as office.desks")
    score: float = Field(description="Noise score relative to the untreated office (= 100)")


class OptimizationResponse(BaseModel):
    """Response when starting an optimization."""

    optimization_id: str
    status: str = "pending"
    message: str = "Optimization queued"


class OptimizationStatus(BaseModel):
    """Current status of a running optimization."""

    optimization_id: str
    status: str  # "pending", "running", "completed", "failed", "aborted"
    progress: float = Field(ge=0.0, le=100.0)
    message: Optional[str] = None
    layouts_done: int = 0
    layouts_total: int = 0
    best_score: Optional[float] = None
    project_url: Optional[str] = None


class OptimizationResults(BaseModel):
    """Complete results of an optimization."""

    optimization_id: str
    status: str
    baseline: LayoutResult
    best: LayoutResult
    layouts: List[LayoutResult] = Field(description="Every layout simulated, in the order tested")
    project_url: Optional[str] = None
    parameters: OptimizationParams


class Capabilities(BaseModel):
    """Whether this backend can run real Allsolve simulations right now."""

    sdk_installed: bool
    credentials_configured: bool
    host: str
