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


class NoiseSource(Point):
    """Something that makes noise: a conversation, a printer, a coffee machine."""

    level_db: float = Field(default=60.0, ge=30.0, le=100.0, description="Level 1 m away. Normal speech is about 60 dB.")
    label: str = ""


ZONE_SAMPLE_STEP_M = 0.8


class QuietZone(BaseModel):
    """A rectangular area that should be quiet, such as a focus area or a meeting corner."""

    x: float = Field(description="Smallest x of the rectangle, metres")
    y: float = Field(description="Smallest y of the rectangle, metres")
    width: float = Field(gt=0.2, le=60.0)
    height: float = Field(gt=0.2, le=60.0)
    label: str = ""

    def sample_points(self) -> List[Point]:
        """Listening points spread evenly over the zone, about one every 0.8 m."""
        nx = max(1, round(self.width / ZONE_SAMPLE_STEP_M))
        ny = max(1, round(self.height / ZONE_SAMPLE_STEP_M))
        return [
            Point(x=self.x + (i + 0.5) * self.width / nx, y=self.y + (j + 0.5) * self.height / ny)
            for j in range(ny)
            for i in range(nx)
        ]


class Office(BaseModel):
    """An open-plan office seen from above. The room is any simple polygon."""

    outline: List[Point] = Field(
        min_length=3,
        max_length=40,
        description="Room corners in order, metres. The last corner joins back to the first.",
    )
    ceiling_height_m: float = Field(default=2.7, ge=2.0, le=6.0, description="Floor to ceiling")
    sources: List[NoiseSource] = Field(min_length=1, max_length=6, description="Where the noise comes from")
    desks: List[Point] = Field(default_factory=list, max_length=40, description="Single listening points")
    quiet_zones: List[QuietZone] = Field(default_factory=list, max_length=10, description="Areas that should be quiet")
    slots: List[Slot] = Field(min_length=1, max_length=60)

    @model_validator(mode="after")
    def _check_size(self) -> "Office":
        min_x, min_y, max_x, max_y = self.bounds
        if max_x - min_x < 1.0 or max_y - min_y < 1.0:
            raise ValueError("The room must be at least 1 m in each direction")
        if max_x - min_x > 60.0 or max_y - min_y > 60.0:
            raise ValueError("The room must be at most 60 m in each direction")
        if len({slot.id for slot in self.slots}) != len(self.slots):
            raise ValueError("Screen position ids must be unique")
        if not self.desks and not self.quiet_zones:
            raise ValueError("Add at least one desk or one quiet zone to listen at")
        if len(self.receivers()) > 150:
            raise ValueError("Too many listening points: make the quiet zones smaller or fewer")
        return self

    def receivers(self) -> List[Point]:
        """Every point the sound is read at: the desks first, then each quiet zone's points."""
        points = list(self.desks)
        for zone in self.quiet_zones:
            points.extend(zone.sample_points())
        return points

    def objective_indices(self) -> List[int]:
        """Which of receivers() the search minimises the noise at.

        The quiet zones when there are any: they are the places the user asked to keep quiet.
        Desks are then still reported, but do not steer the search. Without zones, the desks.
        """
        n_desks, n_all = len(self.desks), len(self.receivers())
        return list(range(n_desks, n_all)) if n_all > n_desks else list(range(n_desks))

    def zone_ranges(self) -> List[Tuple[int, int]]:
        """For each quiet zone, where its points sit in receivers(): (start, end)."""
        ranges, start = [], len(self.desks)
        for zone in self.quiet_zones:
            count = len(zone.sample_points())
            ranges.append((start, start + count))
            start += count
        return ranges

    def contains(self, x: float, y: float) -> bool:
        """Whether a point is inside the room outline (even-odd rule)."""
        inside, n = False, len(self.outline)
        for i in range(n):
            a, b = self.outline[i], self.outline[i - 1]
            if (a.y > y) != (b.y > y) and x < (b.x - a.x) * (y - a.y) / (b.y - a.y) + a.x:
                inside = not inside
        return inside

    def reference_point(self, index: int) -> Point:
        """A point 1 m from source `index`, inside the room and clear of the other sources.

        The level there, with no screens, is what the source's level_db is defined as.
        """
        source = self.sources[index]
        others = [s for i, s in enumerate(self.sources) if i != index]
        for dx, dy in [(1, 0), (-1, 0), (0, 1), (0, -1), (0.707, 0.707), (-0.707, 0.707), (0.707, -0.707), (-0.707, -0.707)]:
            x, y = source.x + dx, source.y + dy
            if self.contains(x, y) and all((o.x - x) ** 2 + (o.y - y) ** 2 > 0.25 for o in others):
                return Point(x=x, y=y)
        return Point(x=source.x + 1.0, y=source.y)

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
        sources=[NoiseSource(x=2.2, y=5.0, level_db=60.0, label="Conversation")],
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
    screen_height_m: float = Field(
        default=1.6,
        ge=0.8,
        le=6.0,
        description="Panel height. A desk divider is about 1.2 m, a tall partition 2 m. Only used in 3D.",
    )
    screen_absorbing: bool = Field(
        default=False,
        description="True: the panel faces absorb sound. False: they reflect it. Only used in 3D.",
    )
    parallel_jobs: int = Field(
        default=1,
        ge=1,
        le=8,
        description=(
            "How many sweeps each round of layouts is split into. Allsolve already runs every step "
            "of one sweep on its own machine, and measured runs were slower when split, so 1 is best. "
            "Not used by the fast search."
        ),
    )
    model: Literal["2d", "3d"] = Field(
        default="3d",
        description=(
            "3d includes ceiling height and sound passing over the panels, and is far more "
            "expensive. 2d is a top-down slice where every panel is floor-to-ceiling."
        ),
    )
    source_height_m: float = Field(default=1.5, ge=0.5, le=2.2, description="Talker mouth height (standing)")
    ear_height_m: float = Field(default=1.2, ge=0.5, le=2.2, description="Listener ear height (seated)")
    frequencies_hz: List[float] = Field(
        default=[250.0, 500.0],
        min_length=1,
        max_length=4,
        description="Speech bands to simulate. Higher bands need a much finer mesh.",
    )
    strategy: Literal["greedy", "exhaustive", "fast"] = Field(
        default="greedy",
        description=(
            "greedy places one screen at a time and keeps the best (about 12+11+10 layouts); "
            "exhaustive tries every combination (220 layouts for 3 screens in 12 slots); "
            "fast simulates as many of candidate_layouts as fit time_budget_s, all at once"
        ),
    )
    candidate_layouts: List[List[int]] = Field(
        default_factory=list,
        max_length=3000,
        description=(
            "For the fast search: layouts (slot ids, one per screen) worth simulating, most promising "
            "first. The browser ranks every combination with its quick estimate. Empty: an even "
            "spread over all combinations."
        ),
    )
    fixed_mesh: bool = Field(
        default=True,
        description=(
            "Fast search only. True: every candidate position is drawn into one mesh and a screen is "
            "switched on by making its rectangle very heavy, so nothing is meshed per layout. "
            "False: each layout cuts its screens out of the air and gets its own mesh."
        ),
    )
    time_budget_s: float = Field(default=30.0, ge=15.0, le=300.0, description="Wall time the fast search aims for")


class LayoutResult(BaseModel):
    """One simulated layout."""

    slot_ids: List[int]
    desk_levels_db: List[float] = Field(description="Noise level at each desk, same order as office.desks")
    zone_levels_db: List[float] = Field(
        default_factory=list,
        description="Average noise level over each quiet zone, same order as office.quiet_zones",
    )
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
    log_size: int = Field(default=0, description="Entries in the run log so far; fetch them from /log")


class OptimizationResults(BaseModel):
    """Complete results of an optimization."""

    optimization_id: str
    status: str
    baseline: LayoutResult
    best: LayoutResult
    layouts: List[LayoutResult] = Field(description="Every layout simulated, in the order tested")
    project_url: Optional[str] = None
    parameters: OptimizationParams
    evidence: Optional[dict] = Field(
        default=None,
        description="What ties the result to Allsolve: project, jobs, and the raw pressures the solver returned",
    )


class Capabilities(BaseModel):
    """Whether this backend can run real Allsolve simulations right now."""

    sdk_installed: bool
    credentials_configured: bool
    host: str
    ai_configured: bool = Field(default=False, description="An OpenAI key is set, so runs can be explained in plain language")


class ExplainRequest(BaseModel):
    """Ask for a plain-language explanation of what is on screen."""

    optimization_id: Optional[str] = Field(default=None, description="An Allsolve run, so its log is included")
    context: dict = Field(description="The office, settings and result to explain")


class ExplainResponse(BaseModel):
    text: str
    model: str
