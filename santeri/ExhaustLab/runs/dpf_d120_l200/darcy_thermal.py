# Explicit homogeneous Darcy pressure and plug thermal surrogate.
# fld.v is the scalar pressure unknown (Pa), not electric potential.
form = qs.formulation()
form += qs.integral(reg.cartridge, 0.0005970149253731343*qs.grad(qs.dof(fld.v))*qs.grad(qs.tf(fld.v)))
form += qs.integral(reg.inlet, -4.528527032330829*qs.tf(fld.v))
form += qs.integral(reg.cartridge,
    0.5*qs.grad(qs.dof(fld.T))*qs.grad(qs.tf(fld.T))
    + 12.157669263964229*qs.compx(qs.grad(qs.dof(fld.T)))*qs.compx(qs.grad(qs.tf(fld.T)))
    + 2431.5338527928457*qs.compx(qs.grad(qs.dof(fld.T)))*qs.tf(fld.T)
    + 666.6666666666667*(qs.dof(fld.T)-293.15)*qs.tf(fld.T))
print("Homogeneous Darcy pressure + stabilized plug thermal benchmark")
