"""Allsolve simulation runner for beer cooling simulations."""

import os
import io
import re
import logging
from typing import Optional, Callable, Awaitable, Union
from pathlib import Path

from ..config import get_settings
from ..models.simulation_params import SimulationParams, TemperaturePoint
from .project_config import generate_project_config

# Configure logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Import allsolve conditionally to allow testing without SDK
try:
    import allsolve

    ALLSOLVE_AVAILABLE = True
    logger.info("✅ Allsolve SDK imported successfully")
except ImportError as e:
    ALLSOLVE_AVAILABLE = False
    allsolve = None
    logger.warning(f"⚠️ Allsolve SDK not available: {e}")


class SimulationRunner:
    """
    Manages the lifecycle of an Allsolve beer cooling simulation.

    This class handles:
    - SDK initialization
    - Project creation from parameters
    - Geometry processing and mesh generation
    - Simulation execution
    - Results retrieval
    """

    def __init__(self):
        self._initialized = False
        self._project = None
        self._simulation = None
        self._mesh = None

    def initialize(self) -> None:
        """Initialize the Allsolve SDK with credentials."""
        if not ALLSOLVE_AVAILABLE:
            logger.error("❌ Allsolve SDK is not installed!")
            raise RuntimeError("Allsolve SDK is not installed")

        if self._initialized:
            logger.debug("SDK already initialized")
            return

        settings = get_settings()
        logger.info(f"🔧 Initializing Allsolve SDK...")
        logger.info(f"   Host: {settings.qs_host}")
        logger.info(f"   API Key configured: {'✅ Yes' if settings.qs_access_key else '❌ No'}")

        if not settings.qs_access_key or not settings.qs_secret_key:
            logger.error("❌ Allsolve API credentials not configured!")
            raise RuntimeError(
                "Allsolve API credentials not set. Set QS_ACCESS_KEY and QS_SECRET_KEY environment variables."
            )

        allsolve.setup(
            api_key=settings.qs_access_key,
            api_secret=settings.qs_secret_key,
            host=settings.qs_host,
        )
        logger.info("✅ Allsolve SDK initialized successfully")
        self._initialized = True

    def run_simulation_sync(
        self,
        params: SimulationParams,
        on_progress: Optional[Callable[[str, float], None]] = None,
    ) -> dict:
        """
        Synchronous version of simulation runner for thread pool execution.

        Args:
            params: Simulation parameters from the user
            on_progress: Optional sync callback for progress updates (status, percentage)

        Returns:
            Dictionary with simulation results
        """

        def update_progress(status: str, progress: float) -> None:
            """Helper to safely call progress callback."""
            if on_progress:
                on_progress(status, progress)

        logger.info("=" * 60)
        logger.info("🍺 STARTING BEER COOLING SIMULATION (SYNC/THREADED)")
        logger.info("=" * 60)
        logger.info(f"   Container: {params.container_shape}")
        logger.info(f"   Cooling method: {params.cooling_method}")
        logger.info(f"   Initial temp: {params.initial_temp_celsius}°C")
        logger.info(f"   Target temp: {params.target_temp_celsius}°C")
        logger.info(f"   Immersion: {params.immersion_level * 100:.0f}%")
        logger.info(f"   Duration: {params.simulation_duration_minutes} min")

        self.initialize()

        try:
            # Generate project configuration
            update_progress("Generating project configuration...", 5)

            logger.info("📝 Generating project configuration...")
            config = generate_project_config(params)
            logger.debug(
                f"   Config generated with {len(config.get('geometries', []))} geometries"
            )

            # Import project
            update_progress("Creating project in Allsolve...", 10)

            logger.info("☁️ Creating project in Quanscient Allsolve cloud...")
            self._project = allsolve.import_project(config)
            logger.info(f"✅ Project created: ID={self._project.id}")

            # Wait for geometry processing
            update_progress("Processing geometry...", 20)

            logger.info("📐 Processing geometry...")
            geometries = self._project.get_geometry()
            if geometries:
                logger.info(f"   Found {len(geometries)} geometries")
                for geom in geometries:
                    logger.info(f"   Waiting for geometry '{geom.name}' to process...")
                    while geom.is_running(refresh_delay_s=1):
                        pass
                    logger.info(f"   ✅ Geometry '{geom.name}' processed")
            else:
                logger.warning("   ⚠️ No geometries found in project")

            # Get mesh
            update_progress("Waiting for mesh...", 30)

            logger.info("🔺 Waiting for mesh to complete...")
            meshes = self._project.get_meshes()
            if meshes:
                self._mesh = meshes[0]
                logger.info(f"   Found mesh (ID={self._mesh.id})")

                while self._mesh.is_running(refresh_delay_s=2):
                    update_progress("Meshing in progress...", 40)
                    self._mesh.print_new_loglines()

                logger.info("   ✅ Mesh generation complete")
            else:
                logger.warning("   ⚠️ No meshes found in project")

            # Create simulation
            update_progress("Setting up simulation...", 50)

            logger.info("⚙️ Setting up simulation...")
            existing_sims = self._project.get_simulations()
            self._simulation = existing_sims[0] if existing_sims else None

            if not self._simulation:
                logger.info("   Creating new simulation...")
                self._simulation = allsolve.Simulation.create(
                    name="Beer Cooling Heat Transfer",
                    description="Transient thermal simulation",
                    max_run_time_minutes=15,
                    solver_mode=allsolve.SolverMode.DIRECT,
                    mesh_id=self._mesh.id if self._mesh else None,
                    project_id=self._project.id,
                )
                logger.info(f"   ✅ Simulation created: ID={self._simulation.id}")
            else:
                logger.info(f"   Using existing simulation: ID={self._simulation.id}")

            # Configure runtime
            logger.info("   Configuring runtime...")
            self._simulation.set_runtime(
                allsolve.Runtime(
                    node_type=allsolve.CPU.CORES_3_10GB_FAST_START,
                    node_count=1,
                )
            )

            # Set simulation script
            script_path = (
                Path(__file__).parent.parent.parent / "sim" / "heat_transfer.py"
            )
            logger.info(f"   Setting simulation script: {script_path}")
            self._simulation.set_scripts(
                [
                    allsolve.Script(
                        filepath=str(script_path),
                        is_main=True,
                    ),
                ]
            )

            self._simulation.mesh_id = self._mesh.id if self._mesh else None
            self._simulation.save()
            logger.info("   ✅ Simulation configuration saved")

            # Start simulation
            update_progress("Running simulation...", 60)

            logger.info("🚀 STARTING SIMULATION ON QUANSCIENT ALLSOLVE CLOUD...")
            logger.info(f"   Simulation ID: {self._simulation.id}")
            logger.info(f"   Project ID: {self._project.id}")
            self._simulation.start()
            logger.info("   Simulation started, waiting for completion...")

            # Poll for completion and parse logs for progress
            total_time = params.simulation_duration_minutes * 60.0
            current_sim_time = 0.0
            time_pattern = re.compile(r"t=(\d+(?:\.\d+)?)s:")

            while self._simulation.is_running(refresh_delay_s=3):
                # Capture log lines to parse time steps
                log_buffer = io.StringIO()
                self._simulation.print_new_loglines(log_buffer)
                log_output = log_buffer.getvalue()

                if log_output:
                    for line in log_output.strip().split("\n"):
                        if line.strip():
                            logger.info(f"   [SIM] {line}")

                    matches = time_pattern.findall(log_output)
                    if matches:
                        current_sim_time = max(float(t) for t in matches)

                if total_time > 0:
                    sim_progress = (current_sim_time / total_time) * 35
                    progress = min(60 + sim_progress, 95)
                else:
                    progress = 60

                time_str = f"{current_sim_time:.0f}s / {total_time:.0f}s"
                update_progress(f"Simulating... {time_str}", progress)

            logger.info("   ✅ Simulation completed!")
            logger.info(f"   Final status: {self._simulation.get_status()}")

            # Get results
            update_progress("Retrieving results...", 98)

            logger.info("📊 Retrieving results...")
            results = self._get_results(params)
            logger.info(
                f"   ✅ Got {len(results.get('temperature_history', []))} data points"
            )

            update_progress("Complete!", 100)

            logger.info("=" * 60)
            logger.info("🎉 SIMULATION COMPLETE!")
            logger.info("=" * 60)

            return results

        except Exception as e:
            logger.error(f"❌ Simulation failed: {e}")
            if self._project:
                try:
                    self._project.delete()
                except Exception:
                    pass
            raise e

    async def create_and_run_simulation(
        self,
        params: SimulationParams,
        on_progress: Optional[Callable[[str, float], Awaitable[None]]] = None,
    ) -> dict:
        """
        Create and run a complete beer cooling simulation.

        Args:
            params: Simulation parameters from the user
            on_progress: Optional async callback for progress updates (status, percentage)

        Returns:
            Dictionary with simulation results
        """

        async def update_progress(status: str, progress: float) -> None:
            """Helper to safely call progress callback."""
            if on_progress:
                await on_progress(status, progress)

        logger.info("=" * 60)
        logger.info("🍺 STARTING BEER COOLING SIMULATION (REAL ALLSOLVE)")
        logger.info("=" * 60)
        logger.info(f"   Container: {params.container_shape}")
        logger.info(f"   Cooling method: {params.cooling_method}")
        logger.info(f"   Initial temp: {params.initial_temp_celsius}°C")
        logger.info(f"   Target temp: {params.target_temp_celsius}°C")
        logger.info(f"   Immersion: {params.immersion_level * 100:.0f}%")
        logger.info(f"   Duration: {params.simulation_duration_minutes} min")

        self.initialize()

        try:
            # Generate project configuration
            await update_progress("Generating project configuration...", 5)

            logger.info("📝 Generating project configuration...")
            config = generate_project_config(params)
            logger.debug(
                f"   Config generated with {len(config.get('geometries', []))} geometries"
            )

            # Import project (creates geometry, regions, materials, mesh config)
            await update_progress("Creating project in Allsolve...", 10)

            logger.info("☁️ Creating project in Quanscient Allsolve cloud...")
            self._project = allsolve.import_project(config)
            logger.info(f"✅ Project created: ID={self._project.id}")

            # Wait for geometry processing
            await update_progress("Processing geometry...", 20)

            logger.info("📐 Processing geometry...")
            geometries = self._project.get_geometry()
            if geometries:
                logger.info(f"   Found {len(geometries)} geometries")
                for geom in geometries:
                    logger.info(f"   Waiting for geometry '{geom.name}' to process...")
                    while geom.is_running(refresh_delay_s=2):
                        pass  # is_running handles the sleep internally
                    logger.info(f"   ✅ Geometry '{geom.name}' processed")
            else:
                logger.warning("   ⚠️ No geometries found in project")

            # Get mesh (import_project already starts meshing)
            await update_progress("Waiting for mesh...", 30)

            logger.info("🔺 Waiting for mesh to complete...")
            meshes = self._project.get_meshes()
            if meshes:
                self._mesh = meshes[0]
                logger.info(f"   Found mesh (ID={self._mesh.id})")

                # Wait for mesh to complete (import_project already started it)
                while self._mesh.is_running(refresh_delay_s=2):
                    await update_progress("Meshing in progress...", 40)
                    self._mesh.print_new_loglines()

                logger.info("   ✅ Mesh generation complete")
            else:
                logger.warning("   ⚠️ No meshes found in project")

            # Create simulation
            await update_progress("Setting up simulation...", 50)

            logger.info("⚙️ Setting up simulation...")
            existing_sims = self._project.get_simulations()
            self._simulation = existing_sims[0] if existing_sims else None

            if not self._simulation:
                logger.info("   Creating new simulation...")
                self._simulation = allsolve.Simulation.create(
                    name="Beer Cooling Heat Transfer",
                    description="Transient thermal simulation",
                    max_run_time_minutes=15,  # Fast start nodes max 15 min
                    solver_mode=allsolve.SolverMode.DIRECT,
                    mesh_id=self._mesh.id if self._mesh else None,
                    project_id=self._project.id,
                )
                logger.info(f"   ✅ Simulation created: ID={self._simulation.id}")
            else:
                logger.info(f"   Using existing simulation: ID={self._simulation.id}")

            # Configure simulation runtime (fast starting nodes)
            logger.info("   Configuring runtime (fast start - 3 cores, 10GB)...")
            self._simulation.set_runtime(
                allsolve.Runtime(
                    node_type=allsolve.CPU.CORES_3_10GB_FAST_START,
                    node_count=1,
                )
            )

            # Set simulation script
            script_path = (
                Path(__file__).parent.parent.parent / "sim" / "heat_transfer.py"
            )
            logger.info(f"   Setting simulation script: {script_path}")
            self._simulation.set_scripts(
                [
                    allsolve.Script(
                        filepath=str(script_path),
                        is_main=True,
                    ),
                ]
            )

            self._simulation.mesh_id = self._mesh.id if self._mesh else None
            self._simulation.save()
            logger.info("   ✅ Simulation configuration saved")

            # Start simulation
            await update_progress("Running simulation...", 60)

            logger.info("🚀 STARTING SIMULATION ON QUANSCIENT ALLSOLVE CLOUD...")
            logger.info(f"   Simulation ID: {self._simulation.id}")
            logger.info(f"   Project ID: {self._project.id}")
            self._simulation.start()
            logger.info("   Simulation started, waiting for completion...")

            # Poll for completion and parse logs for progress
            total_time = params.simulation_duration_minutes * 60.0
            current_sim_time = 0.0
            time_pattern = re.compile(r"t=(\d+(?:\.\d+)?)s:")

            while self._simulation.is_running(refresh_delay_s=3):
                # Capture log lines to parse time steps
                log_buffer = io.StringIO()
                self._simulation.print_new_loglines(log_buffer)
                log_output = log_buffer.getvalue()

                if log_output:
                    # Print logs to our logger
                    for line in log_output.strip().split("\n"):
                        if line.strip():
                            logger.info(f"   [SIM] {line}")

                    # Parse for time steps (e.g., "t=1600s:")
                    matches = time_pattern.findall(log_output)
                    if matches:
                        # Get the latest time from logs
                        current_sim_time = max(float(t) for t in matches)

                # Calculate progress: 60% for setup, 40% for simulation
                if total_time > 0:
                    sim_progress = (current_sim_time / total_time) * 35  # 35% for sim
                    progress = min(60 + sim_progress, 95)
                else:
                    progress = 60

                time_str = f"{current_sim_time:.0f}s / {total_time:.0f}s"
                await update_progress(f"Simulating... {time_str}", progress)

            logger.info("   ✅ Simulation completed!")
            logger.info(f"   Final status: {self._simulation.get_status()}")

            # Get results
            await update_progress("Retrieving results...", 98)

            logger.info("📊 Retrieving results...")
            results = self._get_results(params)
            logger.info(
                f"   ✅ Got {len(results.get('temperature_history', []))} data points"
            )

            await update_progress("Complete!", 100)

            logger.info("=" * 60)
            logger.info("🎉 SIMULATION COMPLETE!")
            logger.info("=" * 60)

            return results

        except Exception as e:
            # Clean up on error
            if self._project:
                try:
                    self._project.delete()
                except Exception:
                    pass
            raise e

    def _get_results(self, params: SimulationParams) -> dict:
        """Extract results from completed simulation."""
        if not self._simulation:
            raise RuntimeError("No simulation to get results from")

        # Get output data
        output_data = self._simulation.get_output_data(refresh=True)

        # Parse temperature history
        temperature_history = []
        time_to_target = None

        # Get simulation status first
        status = self._simulation.get_status()
        logger.info(f"   Simulation status: {status}")

        if status != allsolve.Job.SUCCESS:
            # Print any error logs
            self._simulation.print_new_loglines()
            raise RuntimeError(f"Simulation failed with status: {status}")

        # Get temperature values from output
        # Output is indexed by timestep first: {"0": {"T_avg_beer": val, ...}, "10": {...}, ...}
        output_values = self._simulation.get_output_values(refresh=True)
        logger.info(f"   Output steps available: {list(output_values.keys())}")

        # Parse temperature history from step-indexed data
        for step_key, step_values in output_values.items():
            if step_key == "nostep":
                continue  # Skip non-transient outputs

            if "T_avg_beer" not in step_values:
                logger.warning(f"   Step {step_key} missing T_avg_beer, skipping")
                continue

            # Step key is the time in seconds (as string)
            try:
                time_s = float(step_key)
            except ValueError:
                logger.warning(f"   Invalid step key: {step_key}, skipping")
                continue

            temp_c = step_values["T_avg_beer"]
            # Handle case where value is a list (e.g., [19.9] instead of 19.9)
            if isinstance(temp_c, list):
                temp_c = temp_c[0] if temp_c else 0.0
            temp_c = float(temp_c)

            temperature_history.append(
                TemperaturePoint(
                    time_seconds=time_s,
                    temperature_celsius=temp_c,  # Already in Celsius
                )
            )

            # Check if we've reached target temperature
            if time_to_target is None and temp_c <= params.target_temp_celsius:
                time_to_target = time_s

        # Sort by time (step keys may not be in order)
        temperature_history.sort(key=lambda x: x.time_seconds)
        logger.info(f"   Got {len(temperature_history)} temperature points")

        if not temperature_history:
            raise RuntimeError(
                f"No temperature data found in simulation outputs. "
                f"Available steps: {list(output_values.keys())}"
            )

        final_temp = (
            temperature_history[-1].temperature_celsius
            if temperature_history
            else params.initial_temp_celsius
        )

        return {
            "simulation_id": self._simulation.id,
            "project_id": self._project.id if self._project else None,
            "status": self._simulation.get_status(),
            "temperature_history": [t.model_dump() for t in temperature_history],
            "time_to_target_seconds": time_to_target,
            "final_temperature_celsius": final_temp,
            "total_simulation_time_seconds": params.simulation_duration_minutes * 60,
            "parameters": params.model_dump(),
        }

    def abort(self) -> bool:
        """Abort all running jobs (geometry, mesh, simulation)."""
        aborted = False

        # Try to abort simulation
        if self._simulation:
            try:
                logger.info("🛑 Aborting simulation...")
                self._simulation.abort()
                aborted = True
                logger.info("   Simulation aborted")
            except Exception as e:
                logger.warning(f"   Failed to abort simulation: {e}")

        # Try to abort mesh
        if self._mesh:
            try:
                logger.info("🛑 Aborting mesh...")
                self._mesh.abort()
                aborted = True
                logger.info("   Mesh aborted")
            except Exception as e:
                logger.warning(f"   Failed to abort mesh: {e}")

        # Try to abort geometry processing
        if self._project:
            try:
                geometries = self._project.get_geometry()
                if geometries:
                    for geom in geometries:
                        try:
                            logger.info(f"🛑 Aborting geometry '{geom.name}'...")
                            geom.abort()
                            aborted = True
                            logger.info(f"   Geometry '{geom.name}' aborted")
                        except Exception as e:
                            logger.warning(
                                f"   Failed to abort geometry '{geom.name}': {e}"
                            )
            except Exception as e:
                logger.warning(f"   Failed to get geometries for abort: {e}")

        return aborted

    def cleanup(self) -> None:
        """Clean up simulation resources."""
        if self._project:
            try:
                self._project.delete()
            except Exception:
                pass
            self._project = None
            self._simulation = None
            self._mesh = None
