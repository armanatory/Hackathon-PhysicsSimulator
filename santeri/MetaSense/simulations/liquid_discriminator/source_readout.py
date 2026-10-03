# Cloud-only AFTER_FORMULATIONS_CREATED; built-in FORMULATIONS and SOLVE disabled.
# Lossless, isotropic, nonmagnetic exterior media; normal-incidence +z, Ey (TE).
# Harmonic 2 = sine, 3 = cosine; complex phasor E_cos - i E_sin, exp(+i omega t).
# reg.liquid and reg.substrate must include the volume adjacent to each end face.

def _coherent_powers(means, admittance, area):
    """Zeroth Fourier mode powers from area-averaged transverse E/H quadratures."""
    impedance = 1.0 / admittance
    electric_x = complex(means["Ex_cos"], -means["Ex_sin"])
    electric_y = complex(means["Ey_cos"], -means["Ey_sin"])
    magnetic_x = complex(means["Hx_cos"], -means["Hx_sin"])
    magnetic_y = complex(means["Hy_cos"], -means["Hy_sin"])
    x_forward = (electric_x + impedance * magnetic_y) / 2.0
    x_backward = (electric_x - impedance * magnetic_y) / 2.0
    y_forward = (electric_y - impedance * magnetic_x) / 2.0
    y_backward = (electric_y + impedance * magnetic_x) / 2.0
    scale = area * admittance / 2.0
    pxf, pxb = scale * abs(x_forward)**2, scale * abs(x_backward)**2
    pyf, pyb = scale * abs(y_forward)**2, scale * abs(y_backward)**2
    return {
        "forward": pxf + pyf,
        "backward": pxb + pyb,
        "crosspolarized": pxf + pxb,  # Excitation is Ey; Ex is the cross channel.
        "x_forward": pxf, "x_backward": pxb,
        "y_forward": pyf, "y_backward": pyb,
    }


epsilon0 = qs.getepsilon0()
mu0 = qs.getmu0()
Yvacuum = (epsilon0 / mu0)**0.5
Ytop = expr.n_liquid * Yvacuum
Ybottom = expr.n_substrate * Yvacuum
omega = 2.0 * qs.getpi() * expr.frequency
area = expr.period_x * expr.period_y
if area <= 0 or Ytop <= 0 or Ybottom <= 0 or expr.frequency <= 0 or expr.wavelength <= 0 or expr.E0 == 0:
    raise RuntimeError("Invalid cell area, exterior index, optical frequency/wavelength, or source amplitude")
wavelength_from_frequency = 1.0 / ((epsilon0*mu0)**0.5 * expr.frequency)
cutoff_ratio = max(expr.n_liquid, expr.n_substrate) * max(expr.period_x, expr.period_y) / wavelength_from_frequency
if cutoff_ratio >= 1.0:
    raise RuntimeError("Nonzero exterior diffraction orders can propagate; this source requires subwavelength periods")

form = qs.formulation()
form += qs.integral(reg.domain, 3, qs.predefinedemwave(
    qs.dof(fld.E), qs.tf(fld.E), par.mu(), 0.0, par.epsilon(), 0.0,
    par.sigma(), 0.0, "oo2"))
# Evaluate material admittance in the adjacent homogeneous volume, not a boundary
# with ambiguous material assignment. Expected scalar values are checked below.
for boundary, volume in [(reg.entrance, reg.liquid), (reg.exit, reg.substrate)]:
    boundary_Y = qs.on(volume, qs.sqrt(par.epsilon() * qs.inverse(par.mu())))
    form += qs.integral(boundary, 3, qs.predefinedemboundaryadmittance(
        qs.dof(fld.E), qs.tf(fld.E), boundary_Y, 0.0))
form += qs.periodicitycondition(reg.xmin, reg.xmax, fld.E,
                               [1.0, 0.0, 0.0], [expr.period_x], 1.0, 2)
form += qs.periodicitycondition(reg.ymin, reg.ymax, fld.E,
                               [0.0, 1.0, 0.0], [expr.period_y], 1.0, 2)

# Entrance outward normal is -z. Residual: +Ytop dt(Et) - 2Ytop dt(Einc).
# For Einc_y=E0*cos(omega*t), the known source is +2Ytop E0 omega sin(omega*t).
# Solver 484 requires explicit FFT count and rejects dt(cn(1)).
form += qs.integral(reg.entrance, 3,
                    2.0 * Ytop * expr.E0 * omega * qs.sn(1) * qs.compy(qs.tf(fld.E)))
form.allsolve(relrestol=1e-9, maxnumit=1000, nltol=1e-9,
              maxnumnlit=-1, relaxvalue=-1)
if expr.write_fields:
    qs.setoutputfield("E sine", reg.domain, qs.harm(2, fld.E, 3), 2)
    qs.setoutputfield("E cosine", reg.domain, qs.harm(3, fld.E, 3), 2)

# curl(E)=-mu*dt(H). dt(curl(E)) is unsupported; extract its quadratures directly.
curlE = qs.curl(fld.E)
Hcos = qs.harm(2, curlE, 3) / (mu0 * omega)
Hsin = -qs.harm(3, curlE, 3) / (mu0 * omega)
Pspecified = area * Ytop * expr.E0**2 / 2.0
qs.setoutputvalue("specified_incident_power_W", Pspecified)
qs.setoutputvalue("candidate_id", expr.candidate_id)
qs.setoutputvalue("input_index", expr.input_index)
qs.setoutputvalue("wavelength_nm", expr.wavelength * 1e9)
qs.setoutputvalue("wavelength_frequency_ratio", wavelength_from_frequency/expr.wavelength)
qs.setoutputvalue("n_liquid", expr.n_liquid)
qs.setoutputvalue("n_sin", expr.n_sin)
qs.setoutputvalue("n_substrate", expr.n_substrate)
qs.setoutputvalue("period_nm", expr.period_x * 1e9)
qs.setoutputvalue("period_y_nm", expr.period_y * 1e9)
qs.setoutputvalue("fill_factor", expr.fill_factor)
qs.setoutputvalue("ridge_height_nm", expr.ridge_height * 1e9)
qs.setoutputvalue("film_thickness_nm", expr.film_thickness * 1e9)
qs.setoutputvalue("exterior_diffraction_cutoff_ratio", cutoff_ratio)


def read_plane(label, surface, volume, admittance):
    impedance = 1.0 / admittance
    components = {}
    for name, component in [("Ex", qs.compx), ("Ey", qs.compy)]:
        components[name + "_cos"] = qs.on(volume, qs.harm(3, component(fld.E), 3))
        components[name + "_sin"] = qs.on(volume, qs.harm(2, component(fld.E), 3))
    for name, component in [("Hx", qs.compx), ("Hy", qs.compy)]:
        # qs.on ensures curl is differentiated in the 3D volume before sampling.
        components[name + "_cos"] = qs.on(volume, component(Hcos))
        components[name + "_sin"] = qs.on(volume, component(Hsin))
    means = {name: value.allintegrate(surface, 6) / area
             for name, value in components.items()}
    for name, value in means.items():
        qs.setoutputvalue(label + "_" + name, value)
    coherent = _coherent_powers(means, admittance, area)
    for name in ("forward", "backward", "crosspolarized"):
        qs.setoutputvalue(label + "_" + name + "_power_W", coherent[name])
    qs.setoutputvalue(label + "_net_flux_W", coherent["forward"] - coherent["backward"])

    def squared(value):
        return value * value
    Exc, Exs = components["Ex_cos"], components["Ex_sin"]
    Eyc, Eys = components["Ey_cos"], components["Ey_sin"]
    Hxc, Hxs = components["Hx_cos"], components["Hx_sin"]
    Hyc, Hys = components["Hy_cos"], components["Hy_sin"]
    xforward = (squared(Exc + impedance*Hyc) + squared(Exs + impedance*Hys)) * admittance / 8.0
    xbackward = (squared(Exc - impedance*Hyc) + squared(Exs - impedance*Hys)) * admittance / 8.0
    yforward = (squared(Eyc - impedance*Hxc) + squared(Eys - impedance*Hxs)) * admittance / 8.0
    ybackward = (squared(Eyc + impedance*Hxc) + squared(Eys + impedance*Hxs)) * admittance / 8.0
    local_forward = (xforward + yforward).allintegrate(surface, 6)
    local_backward = (xbackward + ybackward).allintegrate(surface, 6)
    poynting = ((Exc*Hyc + Exs*Hys - Eyc*Hxc - Eys*Hxs) / 2.0).allintegrate(surface, 6)
    qs.setoutputvalue(label + "_local_forward_power_W", local_forward)
    qs.setoutputvalue(label + "_local_backward_power_W", local_backward)
    qs.setoutputvalue(label + "_local_crosspolarized_power_W", (xforward+xbackward).allintegrate(surface, 6))
    qs.setoutputvalue(label + "_poynting_flux_W", poynting)
    qs.setoutputvalue(label + "_local_directional_flux_W", local_forward-local_backward)
    qs.setoutputvalue(label + "_local_flux_identity_error_W", local_forward-local_backward-poynting)
    qs.setoutputvalue(label + "_local_flux_identity_error_fraction", (local_forward-local_backward-poynting)/Pspecified)
    # Excess includes evanescent transverse content and numerical trace variation.
    qs.setoutputvalue(label + "_forward_excess_power_W", local_forward-coherent["forward"])
    qs.setoutputvalue(label + "_backward_excess_power_W", local_backward-coherent["backward"])
    qs.setoutputvalue(label + "_coherent_local_flux_difference_W",
                      poynting-coherent["forward"]+coherent["backward"])
    qs.setoutputvalue(label + "_coherent_local_flux_difference_fraction",
                      (poynting-coherent["forward"]+coherent["backward"])/Pspecified)
    qs.setoutputvalue(label + "_forward_excess_fraction", (local_forward-coherent["forward"])/Pspecified)
    qs.setoutputvalue(label + "_backward_excess_fraction", (local_backward-coherent["backward"])/Pspecified)
    material_Y = qs.on(volume, qs.sqrt(par.epsilon()*qs.inverse(par.mu())))
    measured_Y = material_Y.allintegrate(surface, 6) / area
    qs.setoutputvalue(label + "_material_admittance_S", measured_Y)
    qs.setoutputvalue(label + "_material_admittance_ratio", measured_Y/admittance)
    return coherent, local_forward, local_backward


entrance, local_Pin, local_Pr = read_plane("entrance", reg.entrance, reg.liquid, Ytop)
exit_plane, local_Pt, local_Pexitback = read_plane("exit", reg.exit, reg.substrate, Ybottom)
Pin, Pr = entrance["forward"], entrance["backward"]
Pt, Pexitback = exit_plane["forward"], exit_plane["backward"]
if Pin <= 0 or Pspecified <= 0 or local_Pin <= 0:
    raise RuntimeError("Nonpositive incident power; invalid optical readout")
qs.setoutputvalue("reflectance", Pr/Pin)
qs.setoutputvalue("transmittance", Pt/Pin)
qs.setoutputvalue("coherent_reflectance", Pr/Pin)
qs.setoutputvalue("coherent_transmittance", Pt/Pin)
qs.setoutputvalue("energy_residual", 1.0-(Pr+Pt)/Pin)
qs.setoutputvalue("incident_normalization_ratio", Pin/Pspecified)
qs.setoutputvalue("exit_backward_fraction", Pexitback/Pin)
qs.setoutputvalue("entrance_crosspolarized_fraction", entrance["crosspolarized"]/Pin)
qs.setoutputvalue("exit_crosspolarized_fraction", exit_plane["crosspolarized"]/Pin)
qs.setoutputvalue("local_reflectance", local_Pr/local_Pin)
qs.setoutputvalue("local_transmittance", local_Pt/local_Pin)
qs.setoutputvalue("local_energy_residual", 1.0-(local_Pr+local_Pt)/local_Pin)
