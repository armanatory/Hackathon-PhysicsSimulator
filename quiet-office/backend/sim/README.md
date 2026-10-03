# Simulation scripts

Empty on purpose for now.

The beer-cooling sample uploads a hand-written solver script from this folder. QuietOffice v1
does not need one: the acoustic physics, boundary conditions and outputs are all defined
through the SDK in [`app/allsolve/project_builder.py`](../app/allsolve/project_builder.py),
and Allsolve generates the solver script.

If we later need something the SDK cannot express (for example writing the pressure field on a
regular grid for the heat map), the custom script goes here.
