# Explicit homogeneous Darcy pressure and plug thermal surrogate.
# fld.v is the scalar pressure unknown (Pa), not electric potential.
form = qs.formulation()
form += qs.integral(reg.cartridge, 0.0005970149253731343*qs.grad(qs.dof(fld.v))*qs.grad(qs.tf(fld.v)))
form += qs.integral(reg.inlet, -2.547296455686091*qs.tf(fld.v))
form += qs.integral(reg.cartridge,
    0.5*qs.grad(qs.dof(fld.T))*qs.grad(qs.tf(fld.T))
    + 3.419344480489938*qs.compx(qs.grad(qs.dof(fld.T)))*qs.compx(qs.grad(qs.tf(fld.T)))
    + 1367.7377921959753*qs.compx(qs.grad(qs.dof(fld.T)))*qs.tf(fld.T)
    + 500.0*(qs.dof(fld.T)-293.15)*qs.tf(fld.T))
print("Homogeneous Darcy pressure + stabilized plug thermal benchmark")
