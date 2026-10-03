# Cloud-only AFTER_FORMULATIONS_CREATED; built-in FORMULATIONS and SOLVE disabled.
# Harmonic 2 = sine, 3 = cosine. Exterior is homogeneous, nonmagnetic vacuum.
form = qs.formulation()
form += qs.integral(reg.domain, 3, qs.predefinedemwave(qs.dof(fld.E), qs.tf(fld.E), par.mu(), 0, par.epsilon(), 0, par.sigma(), 0, "oo2"))
for boundary in [reg.entrance, reg.exit]:
    form += qs.integral(boundary, 3, qs.predefinedemboundaryadmittance(qs.dof(fld.E), qs.tf(fld.E), qs.sqrt(par.epsilon()*qs.inverse(par.mu())), 0.0))
# Match mortar multiplier order to the second-order field trace.
# SDK periodicity interactions currently emit lagmultorder=0 unconditionally.
form += qs.periodicitycondition(reg.xmin, reg.xmax, fld.E, [1.0,0.0,0.0], [expr.period], 1, 2)
form += qs.periodicitycondition(reg.ymin, reg.ymax, fld.E, [0.0,1.0,0.0], [expr.period], 1, 2)
Y0 = (qs.getepsilon0() / qs.getmu0()) ** 0.5
Z0 = 1 / Y0
omega = 2 * qs.getpi() * expr.frequency

# The built-in absorbing boundary contributes +Y0 dt(E_t) dot test(E_t).
# Known incident field contributes -2 Y0 dt(Einc) dot test(E_t) on the LHS.
# dt(cn(1)) is unsupported by solver 484; write the exact derivative analytically.
# Known time-dependent forcing needs explicit FFT harmonic count in integral().
form += qs.integral(reg.entrance, 3, 2 * Y0 * expr.E0 * omega * qs.sn(1) * qs.compx(qs.tf(fld.E)))
form.allsolve(relrestol=1e-9, maxnumit=1000, nltol=1e-9, maxnumnlit=-1, relaxvalue=-1)
qs.setoutputfield("E sine", reg.domain, qs.harm(2, fld.E, 3), 2)
qs.setoutputfield("E cosine", reg.domain, qs.harm(3, fld.E, 3), 2)

# Evaluate derivatives in VOLUME before mapping them onto monitor surfaces.
# curl(E) = -mu dt(H), so H_cos=curl(E_sin)/(omega*mu), H_sin=-curl(E_cos)/(omega*mu).
curlE = qs.curl(fld.E)
# Solver 484 permits dt(field) but not dt(curl(field)); use explicit quadratures.
Hcos = qs.harm(2, curlE, 3) / (qs.getmu0() * omega)
Hsin = -qs.harm(3, curlE, 3) / (qs.getmu0() * omega)
Pspecified = expr.period**2 * Y0 * expr.E0**2 / 2
qs.setoutputvalue("specified_incident_power_W", Pspecified)
qs.setoutputvalue("slab_index", expr.n_slab)

def read_plane(label, surface, volume):
    def squared(value):
        return value*value
    Exs = qs.on(volume, qs.harm(2, qs.compx(fld.E), 3))
    Exc = qs.on(volume, qs.harm(3, qs.compx(fld.E), 3))
    Hys = qs.on(volume, qs.compy(Hsin))
    Hyc = qs.on(volume, qs.compy(Hcos))
    Eys = qs.on(volume, qs.harm(2, qs.compy(fld.E), 3))
    Eyc = qs.on(volume, qs.harm(3, qs.compy(fld.E), 3))
    Hxs = qs.on(volume, qs.compx(Hsin))
    Hxc = qs.on(volume, qs.compx(Hcos))
    xforward = (squared(Exc + Z0 * Hyc) + squared(Exs + Z0 * Hys)) * Y0 / 8
    xbackward = (squared(Exc - Z0 * Hyc) + squared(Exs - Z0 * Hys)) * Y0 / 8
    yforward = (squared(Eyc - Z0 * Hxc) + squared(Eys - Z0 * Hxs)) * Y0 / 8
    ybackward = (squared(Eyc + Z0 * Hxc) + squared(Eys + Z0 * Hxs)) * Y0 / 8
    forward = xforward + yforward
    backward = xbackward + ybackward
    pf = forward.allintegrate(surface, 6)
    pb = backward.allintegrate(surface, 6)
    qs.setoutputvalue(label + "_forward_power_W", pf)
    qs.setoutputvalue(label + "_backward_power_W", pb)
    qs.setoutputvalue(label + "_net_flux_W", pf-pb)
    # Total Poynting flux in +z; a consistency check on directional decomposition.
    poynting = (Exc*Hyc + Exs*Hys - Eyc*Hxc - Eys*Hxs)/2
    qs.setoutputvalue(label + "_poynting_flux_W", poynting.allintegrate(surface,6))
    qs.setoutputvalue(label + "_crosspolarized_power_W", (yforward+ybackward).allintegrate(surface,6))
    for name, field in [("Ex_cos", Exc), ("Ex_sin", Exs), ("Hy_cos", Hyc), ("Hy_sin", Hys)]:
        qs.setoutputvalue(label+"_"+name, field.allintegrate(surface, 6)/expr.period**2)
    return pf, pb

Pin, Pr = read_plane("entrance", reg.entrance, reg.air_left)
Pt, Pexitback = read_plane("exit", reg.exit, reg.air_right)
if Pin <= 0:
    raise RuntimeError("Nonpositive incident power; invalid optical readout")
qs.setoutputvalue("reflectance", Pr/Pin)
qs.setoutputvalue("transmittance", Pt/Pin)
qs.setoutputvalue("energy_residual", 1-(Pr+Pt)/Pin)
qs.setoutputvalue("incident_normalization_ratio", Pin/Pspecified)
qs.setoutputvalue("exit_backward_fraction", Pexitback/Pin)
