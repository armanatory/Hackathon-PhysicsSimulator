"""Download accelerator tests isolate all SDK and HTTP network boundaries."""
from __future__ import annotations

import io
import json
import subprocess
import sys
import tempfile
import threading
import unittest
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import h5py
import zstandard

CASE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(CASE))
from experiments import optimizer3d as engine


def hdf_bytes():
    output = io.BytesIO()
    with h5py.File(output, "w") as field:
        field.create_dataset("pressure", data=[1., 2., 3.])
    return output.getvalue()


class Response:
    def __init__(self, body, *, length=None, on_stream=lambda: None):
        self.body, self.on_stream = body, on_stream
        self.headers = {"Content-Length": str(len(body) if length is None else length)}

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def raise_for_status(self):
        pass

    def iter_content(self, chunk_size):
        self.on_stream()
        for offset in range(0, len(self.body), chunk_size):
            yield self.body[offset:offset+chunk_size]


class Session:
    def __init__(self, response):
        self.response, self.calls = response, []

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.response


class BundleTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.folder = self.root / "fields" / "basis"
        self.staging = self.root / ".prefetch-staging"
        self.data = hdf_bytes()

    def download(self, session, filename="Real_pressure.hdf"):
        return engine.download_field_bundle([(filename, "https://storage.invalid/signed-token")],
                                            self.folder, self.staging, lambda: session)

    def test_complete_plain_hdf_is_published_and_staging_cleaned(self):
        session = Session(Response(self.data))
        result = self.download(session)
        self.assertEqual(result, {"published_files": 1, "skipped_files": 0})
        self.assertEqual((self.folder / "Real_pressure.hdf").read_bytes(), self.data)
        self.assertEqual(list(self.staging.iterdir()), [])
        self.assertEqual(session.calls[0][1], {"stream": True, "timeout":
                         (engine.CONNECT_TIMEOUT_S, engine.TRANSFER_TIMEOUT_S)})

    def test_zstd_transport_decoded_using_sdk_handler_before_publication(self):
        compressed = zstandard.ZstdCompressor().compress(self.data)
        self.download(Session(Response(compressed)))
        self.assertEqual((self.folder / "Real_pressure.hdf").read_bytes(), self.data)
        with h5py.File(self.folder / "Real_pressure.hdf") as field:
            self.assertEqual(list(field["pressure"][:]), [1., 2., 3.])

    def test_existing_sdk_file_is_never_downloaded_or_overwritten(self):
        self.folder.mkdir(parents=True)
        original = self.folder / "Real_pressure.hdf"
        original.write_bytes(b"active-sdk-download")
        session = Session(Response(self.data))
        self.assertEqual(self.download(session), {"published_files": 0, "skipped_files": 1})
        self.assertEqual(original.read_bytes(), b"active-sdk-download")
        self.assertEqual(session.calls, [])

    def test_sdk_file_created_during_stream_wins_atomic_publication_race(self):
        def sdk_creates_file():
            self.folder.mkdir(parents=True)
            (self.folder / "Real_pressure.hdf").write_bytes(b"sdk-owned")
        result = self.download(Session(Response(self.data, on_stream=sdk_creates_file)))
        self.assertEqual(result, {"published_files": 0, "skipped_files": 1})
        self.assertEqual((self.folder / "Real_pressure.hdf").read_bytes(), b"sdk-owned")

    def test_interrupted_content_length_keeps_staging_and_publishes_nothing(self):
        with self.assertRaises(OSError):
            self.download(Session(Response(self.data, length=len(self.data)+17)))
        self.assertFalse(self.folder.exists())
        self.assertEqual(len(list(self.staging.glob("field-*/Real_pressure.hdf"))), 1)

    def test_invalid_or_invalid_zstd_hdf_is_not_published(self):
        for data in [b"not-hdf", zstandard.ZstdCompressor().compress(b"not-hdf")]:
            with self.subTest(data=data[:4]):
                with self.assertRaises(ValueError):
                    self.download(Session(Response(data)))
                self.assertFalse(self.folder.exists())


class ManifestTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.folder = Path(self.temporary.name)
        self.output = Mock()
        self.output.get_simulation_job_id.return_value = "job1"
        self.output.get_filenames_for_output_field.side_effect = lambda label, *_: [label+"_pressure.hdf"]
        self.simulation = Mock(id="sim1")
        self.simulation.get_output_data.return_value = self.output
        self.api = Mock()
        self.api.get_simulation_output_data_download_urls.return_value = [
            "https://storage.invalid/real", "https://storage.invalid/imag"]

    def manifest(self):
        with patch.object(engine, "get_api", return_value=nullcontext(self.api)), \
                patch.object(engine, "get_auth", return_value="test-auth"):
            return engine.download_field_manifest(self.simulation, "project1", self.folder)

    def test_serial_metadata_matches_sdk_download_api(self):
        result = self.manifest()
        self.assertEqual([entry[0] for entry in result], ["Real_pressure.hdf", "Imag_pressure.hdf"])
        self.api.get_simulation_output_data_download_urls.assert_called_once_with(
            authorization="test-auth", project_id="project1", simulation_id="sim1", job_id="job1",
            request_body=["Real_pressure.hdf", "Imag_pressure.hdf"])

    def test_present_components_do_not_read_sdk_metadata(self):
        for label in ("Real", "Imag"):
            (self.folder / (label+"_pressure.hdf")).write_bytes(b"sdk-owned")
        self.assertEqual(self.manifest(), [])
        self.simulation.get_output_data.assert_not_called()

    def test_manifest_rejects_traversal_and_incomplete_url_response(self):
        self.output.get_filenames_for_output_field.side_effect = lambda *_: ["../Real_pressure.hdf"]
        with self.assertRaises(ValueError):
            self.manifest()
        self.api.get_simulation_output_data_download_urls.assert_not_called()
        self.output.get_filenames_for_output_field.side_effect = lambda label, *_: [label+"_pressure.hdf"]
        self.api.get_simulation_output_data_download_urls.return_value = ["https://storage.invalid/real"]
        with self.assertRaises(ValueError):
            self.manifest()

    def test_manifest_rejects_insecure_urls(self):
        self.api.get_simulation_output_data_download_urls.return_value = ["http://storage.invalid/real"]*2
        with self.assertRaises(ValueError):
            self.manifest()


class CoordinatorTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.state = {"project_id": "project1", "runs": {
            f"basis{i}": {"simulation_id": f"sim{i}", "status": "PREPARED"} for i in range(8)}}
        self.state_path = self.root / "state.json"
        self.state_path.write_text(json.dumps(self.state), encoding="utf-8")
        self.simulations = [Mock(id=f"sim{i}") for i in range(8)]
        for simulation in self.simulations:
            simulation.get_status.return_value = engine.allsolve.Job.SUCCESS
            simulation.start.side_effect = AssertionError("Prefetch must never start a simulation")
        self.project = Mock(id="project1")
        self.project.get_simulations.return_value = self.simulations
        self.client = Mock()
        self.client.get_project.return_value = self.project

    def prefetch(self, manifest, bundle, progress=lambda _: None, workers=4):
        with patch.object(engine, "HERE", self.root), \
                patch.object(engine.allsolve, "Client", return_value=self.client), \
                patch.object(engine, "dotenv_values", return_value={}), \
                patch.object(engine, "download_field_manifest", side_effect=manifest), \
                patch.object(engine, "download_field_bundle", side_effect=bundle):
            return engine.prefetch_existing_fields(self.root, workers, progress)

    def test_four_independent_workers_and_serial_sdk_metadata_never_mutate_state(self):
        barrier = threading.Barrier(4, timeout=10)
        lock = threading.Lock()
        manifest_threads, worker_threads, manifest_order = [], set(), []
        active = peak = 0
        data = hdf_bytes()
        original_bundle = engine.download_field_bundle

        def manifest(simulation, *_):
            manifest_threads.append(threading.get_ident())
            manifest_order.append(simulation.id)
            return [("Real_pressure.hdf", "https://storage.invalid/signed-token")]

        def bundle(entries, folder, staging_root):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
                worker_threads.add(threading.get_ident())
            try:
                barrier.wait()
                return original_bundle(entries, folder, staging_root, lambda: Session(Response(data)))
            finally:
                with lock:
                    active -= 1

        state_before = self.state_path.read_bytes()
        result = self.prefetch(manifest, bundle)
        self.assertEqual(peak, 4)
        self.assertEqual(len(worker_threads), 4)
        self.assertEqual(set(manifest_threads), {threading.get_ident()})
        self.assertEqual(manifest_order, [f"sim{i}" for i in reversed(range(8))])
        self.assertEqual(result["completed_bases"], 8)
        self.assertEqual(result["published_files"], 8)
        self.assertEqual(result["cloud_jobs_started"], 0)
        self.assertEqual(self.state_path.read_bytes(), state_before)
        for simulation in self.simulations:
            simulation.start.assert_not_called()

    def test_verified_cache_and_non_success_jobs_are_skipped(self):
        folder = self.root / "fields" / "basis0"
        folder.mkdir(parents=True)
        (folder / "complex.npz").write_bytes(b"already-verified")
        self.state["runs"]["basis0"]["status"] = "SUCCESS"
        self.state_path.write_text(json.dumps(self.state), encoding="utf-8")
        self.simulations[1].get_status.return_value = engine.allsolve.Job.RUNNING
        manifest = Mock(return_value=[])
        bundle = Mock()
        result = self.prefetch(manifest, bundle)
        self.assertEqual(manifest.call_count, 6)
        bundle.assert_not_called()
        self.assertEqual(result["planned_bases"], 0)

    def test_sdk_cache_directory_exists_before_client_construction(self):
        state_before = self.state_path.read_bytes()
        def construct_client(**kwargs):
            sdk_cache = Path(kwargs["cache_base_dir"])
            self.assertEqual(sdk_cache, self.root / "prefetch-sdk-cache")
            self.assertTrue(sdk_cache.is_dir())
            return self.client
        with patch.object(engine, "HERE", self.root), \
                patch.object(engine.allsolve, "Client", side_effect=construct_client) as client, \
                patch.object(engine, "dotenv_values", return_value={}), \
                patch.object(engine, "download_field_manifest", return_value=[]):
            engine.prefetch_existing_fields(self.root)
        client.assert_called_once()
        self.assertEqual(self.state_path.read_bytes(), state_before)

    def test_failures_report_only_exception_type_never_signed_urls(self):
        events = []
        secret_url = "https://storage.invalid/?credential=DO-NOT-PERSIST"
        def bundle(*_):
            raise OSError(secret_url)
        result = self.prefetch(lambda *_: [("Real_pressure.hdf", secret_url)], bundle, events.append)
        self.assertEqual(result["failed_bases"], 8)
        self.assertNotIn(secret_url, json.dumps(events))
        self.assertTrue(all(event.get("error_type", "OSError") == "OSError" for event in events))

    def test_worker_limit_and_cache_boundary_fail_before_sdk_authentication(self):
        with patch.object(engine, "HERE", self.root), patch.object(engine.allsolve, "Client") as client:
            for workers in (0, 5, 1.5):
                with self.assertRaises(ValueError):
                    engine.prefetch_existing_fields(self.root, workers)
            with self.assertRaises(ValueError):
                engine.prefetch_existing_fields(self.root.parent)
            client.assert_not_called()


class CliTests(unittest.TestCase):
    def test_invalid_cache_or_worker_limit_exits_without_network_or_traceback(self):
        for cache, workers in ((engine.HERE, 5), (engine.HERE.parent.parent, 4)):
            with self.subTest(workers=workers):
                result = subprocess.run([sys.executable, str(Path(engine.__file__)),
                    "--prefetch-cache-dir", str(cache), "--download-workers", str(workers)],
                    capture_output=True, text=True, check=False, timeout=20)
                self.assertEqual(result.returncode, 1)
                self.assertEqual(json.loads(result.stdout), {"stage": "prefetch_failed",
                    "error_type": "ValueError", "cloud_jobs_started": 0})
                self.assertEqual(result.stderr, "")


if __name__ == "__main__":
    unittest.main()
