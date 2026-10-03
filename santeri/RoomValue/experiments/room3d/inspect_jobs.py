"""Read-only cloud status and diagnostics for saved 3D jobs."""
from run_room3d import HERE, STATE, allsolve, client, read_json
import os

os.chdir(HERE)
state = read_json(STATE)
connection = client()
project = connection.get_project(state["project_id"])
for name, saved in state["runs"].items():
    sim = allsolve.Simulation.get(saved["simulation_id"], project_id=project.id)
    status = sim.get_status()
    print(name, sim.id, status, flush=True)
    if status != allsolve.Job.SUCCESS:
        print("reason", sim.get_status_reason(), flush=True)
        sim.print_new_loglines()
