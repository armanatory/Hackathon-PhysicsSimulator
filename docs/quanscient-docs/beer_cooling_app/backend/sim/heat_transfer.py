"""
Beer Cooling Simulation Script

This script runs on the Allsolve cloud platform to simulate transient heat
transfer in a beer container being cooled.

Governing Equation:
    ρ * Cp * ∂T/∂t = ∇ · (k * ∇T)

Boundary Conditions:
    Submerged surfaces: q = h_submerged * (T - T_coolant)
    Exposed surfaces:   q = h_exposed * (T - T_coolant)

Material Properties:
    Beer:     ρ=1000 kg/m³, Cp=4184 J/(kg·K), k=1.2 W/(m·K)
    Aluminum: ρ=2700 kg/m³, Cp=900 J/(kg·K),  k=237 W/(m·K)
    Glass:    ρ=2500 kg/m³, Cp=840 J/(kg·K),  k=1.0 W/(m·K)
"""

import quanscient as qs
from utils import Mesh, Variables, Fields
from expressions import expr
from parameters import par
from regions import reg

# Initialize containers
var = Variables()
mesh = Mesh()
fld = Fields()

# ============================================================================
# MESH LOADING
# ============================================================================

mesh.mesh = qs.mesh()
mesh.mesh.setphysicalregions(*reg.get_region_data())
mesh.skin = reg.get_next_free()
mesh.mesh.selectskin(mesh.skin)
mesh.mesh.partition()
mesh.mesh.load("gmsh:simulation.msh", mesh.skin, 1, 1)

# ============================================================================
# FIELD DEFINITIONS
# ============================================================================

# Temperature field [K]
fld.T = qs.field("h1")
fld.T.setorder(reg.all_domain, 2)

# ============================================================================
# MATERIAL PROPERTIES
# ============================================================================

# Material properties are accessed via par module (pre-set from material definitions):
#   par.rho() - density [kg/m³]
#   par.cp()  - heat capacity [J/(kg·K)]
#   par.k()   - thermal conductivity [W/(m·K)]

# ============================================================================
# INITIAL CONDITION
# ============================================================================

# Set initial temperature throughout the domain
fld.T.setvalue(reg.all_domain, expr.T_initial)

# ============================================================================
# WEAK FORMULATION
# ============================================================================

form = qs.formulation()

# Transient heat diffusion: ρCp ∂T/∂t - ∇·(k∇T) = 0
# Using predefineddiffusion(dof, tf, alpha, beta) where:
#   alpha = k (thermal conductivity)
#   beta = ρCp (volumetric heat capacity)
form += qs.integral(
    reg.all_domain,
    qs.predefineddiffusion(qs.dof(fld.T), qs.tf(fld.T), par.k(), par.rho() * par.cp()),
)

# ============================================================================
# BOUNDARY CONDITIONS - CONVECTIVE HEAT FLUX
# ============================================================================

# Convective boundary condition: q = h * (T - T_ambient)
# In weak form: ∫ h * (T_coolant - T) * tf(T) dS
# Must use qs.dof(fld.T) for implicit treatment in the bilinear form
# Sign: (T_coolant - T) means heat LEAVES when T > T_coolant -> cooling effect

# Submerged surface (high convection - ice water contact)
form += qs.integral(
    reg.submerged_surface,
    expr.h_submerged * (expr.T_coolant - qs.dof(fld.T)) * qs.tf(fld.T),
)

# Exposed surface (low convection - air contact)
form += qs.integral(
    reg.exposed_surface,
    expr.h_exposed * (expr.T_coolant - qs.dof(fld.T)) * qs.tf(fld.T),
)

# ============================================================================
# TIME STEPPING
# ============================================================================

# Create implicit Euler timestepper for stability
timestepper = qs.impliciteuler(form, qs.vec(form))
timestepper.settolerance(1e-5)
timestepper.setverbosity(1)

# Simulation parameters from expressions
dt = float(expr.dt)  # Time step [s]
t_end = float(expr.t_end)  # End time [s]

# Output interval (every 10 seconds)
output_interval = 10.0

# ============================================================================
# TIME LOOP
# ============================================================================

step = 0
next_output_time = 0.0

if qs.getrank() == 0:
    print(f"Starting beer cooling simulation")
    print(f"  Initial temperature: {float(expr.T_initial) - 273.15:.1f}°C")
    print(f"  Coolant temperature: {float(expr.T_coolant) - 273.15:.1f}°C")
    print(f"  Simulation duration: {t_end:.0f}s")
    print(f"  Time step: {dt:.1f}s")

while qs.gettime() < t_end - 1e-8 * dt:
    # Advance one time step
    timestepper.allnext(relrestol=1e-6, maxnumit=100, timestep=dt)

    current_time = qs.gettime()

    # Output at regular intervals
    if current_time >= next_output_time - 1e-8:
        # Calculate average beer temperature (integration order 4)
        beer_volume = qs.allintegrate(reg.beer, 1, 4)
        T_integral = qs.allintegrate(reg.beer, fld.T, 4)
        T_avg = T_integral / beer_volume if beer_volume > 0 else float(expr.T_initial)

        # Calculate min/max temperatures (refinement 4, returns [value, x, y, z])
        T_min = fld.T.allmin(reg.beer, 4)[0]
        T_max = fld.T.allmax(reg.beer, 4)[0]

        # Convert to Celsius for output
        T_avg_C = T_avg - 273.15
        T_min_C = T_min - 273.15
        T_max_C = T_max - 273.15

        # Log progress
        if qs.getrank() == 0:
            print(
                f"  t={current_time:.0f}s: T_avg={T_avg_C:.2f}°C (min={T_min_C:.2f}°C, max={T_max_C:.2f}°C)"
            )

        # Output values for API retrieval
        qs.setoutputvalue("T_avg_beer", T_avg_C, current_time)
        qs.setoutputvalue("T_min_beer", T_min_C, current_time)
        qs.setoutputvalue("T_max_beer", T_max_C, current_time)

        # Note: VTU field output removed to avoid filesystem issues with many timesteps

        next_output_time += output_interval

    step += 1

# ============================================================================
# FINAL OUTPUT
# ============================================================================

# Final average temperature (integration order 4)
beer_volume = qs.allintegrate(reg.beer, 1, 4)
T_final = (
    qs.allintegrate(reg.beer, fld.T, 4) / beer_volume
    if beer_volume > 0
    else float(expr.T_initial)
)
T_final_C = T_final - 273.15

qs.setoutputvalue("final_temperature", T_final_C)
qs.setoutputvalue("total_time", qs.gettime())

if qs.getrank() == 0:
    print(f"\nSimulation complete!")
    print(f"  Final average beer temperature: {T_final_C:.2f}°C")
    print(f"  Total simulated time: {qs.gettime():.0f}s")
