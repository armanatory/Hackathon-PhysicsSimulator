"""Small in-memory job registry for the local hackathon scaffold."""

from threading import Lock
from uuid import uuid4

from .binding import scenario_from_input
from .detector import add_synthetic_noise
from .inference import estimate_toy_coverage
from .models import JobRecord, JobRequest, SyntheticResult
from .optics import simulate_toy_spectra


class JobManager:
    def __init__(self) -> None:
        self._jobs: dict[str, JobRecord] = {}
        self._lock = Lock()

    def create_surrogate_job(self, request: JobRequest) -> JobRecord:
        scenario = scenario_from_input(request.sample)
        spectrum = simulate_toy_spectra(request.design, scenario.assumed_surface_coverage)
        noisy = add_synthetic_noise(
            spectrum.bound_response, request.detector.noise_std_fraction, request.seed
        )
        inferred = estimate_toy_coverage(
            spectrum.wavelength_nm,
            noisy,
            spectrum.baseline_center_nm,
            spectrum.sensitivity_nm_per_coverage,
            spectrum.linewidth_nm,
        )
        result = SyntheticResult(
            wavelength_nm=spectrum.wavelength_nm.tolist(),
            unbound_response=spectrum.unbound_response.tolist(),
            bound_response=spectrum.bound_response.tolist(),
            noisy_bound_response=noisy.tolist(),
            resonance_shift_nm=(
                spectrum.sensitivity_nm_per_coverage * scenario.assumed_surface_coverage
            ),
            estimated_surface_coverage=inferred,
            assumed_surface_coverage=scenario.assumed_surface_coverage,
        )
        job = JobRecord(id=str(uuid4()), result=result)
        with self._lock:
            self._jobs[job.id] = job
        return job

    def get(self, job_id: str) -> JobRecord | None:
        with self._lock:
            return self._jobs.get(job_id)


job_manager = JobManager()
