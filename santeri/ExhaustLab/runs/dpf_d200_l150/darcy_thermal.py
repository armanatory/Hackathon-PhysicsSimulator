# Explicit homogeneous Darcy pressure and plug thermal surrogate.
# fld.v is the scalar pressure unknown (Pa), not electric potential.
form = qs.formulation()
form += qs.integral(reg.cartridge, 0.0005970149253731343*qs.grad(qs.dof(fld.v))*qs.grad(qs.tf(fld.v)))
form += qs.integral(reg.inlet, -1.6302697316390982*qs.tf(fld.v))
form += qs.integral(reg.cartridge,
    0.5*qs.grad(qs.dof(fld.T))*qs.grad(qs.tf(fld.T))
    + 4.3767609350271215*qs.compx(qs.grad(qs.dof(fld.T)))*qs.compx(qs.grad(qs.tf(fld.T)))
    + 875.3521870054243*qs.compx(qs.grad(qs.dof(fld.T)))*qs.tf(fld.T)
    + 400.0*(qs.dof(fld.T)-293.15)*qs.tf(fld.T))
print("Homogeneous Darcy pressure + stabilized plug thermal benchmark")
