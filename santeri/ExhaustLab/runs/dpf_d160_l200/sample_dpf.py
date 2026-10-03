import numpy as np
area = qs.expression(1).integrate(reg.inlet, 6)
outarea = qs.expression(1).integrate(reg.outlet, 6)
volume = qs.expression(1).integrate(reg.cartridge, 6)
pin = qs.expression(fld.v).integrate(reg.inlet, 6)/area
pout = qs.expression(fld.v).integrate(reg.outlet, 6)/outarea
u = -0.0005970149253731343*qs.grad(fld.v)
qin = qs.on(reg.cartridge,qs.compx(u)).integrate(reg.inlet, 6)
qout = qs.on(reg.cartridge,qs.compx(u)).integrate(reg.outlet, 6)
tin = qs.expression(fld.T).integrate(reg.inlet, 6)/area
tout = qs.expression(fld.T).integrate(reg.outlet, 6)/outarea
loss = (500.0*(qs.expression(fld.T)-293.15)).integrate(reg.cartridge, 6)
diffin = qs.on(reg.cartridge,-7.338688960979876*qs.compx(qs.grad(fld.T))).integrate(reg.inlet, 6)
diffout = qs.on(reg.cartridge,-7.338688960979876*qs.compx(qs.grad(fld.T))).integrate(reg.outlet, 6)
for label, value in dict(inlet_area_m2=area,outlet_area_m2=outarea,volume_m3=volume,
    inlet_pressure_pa=pin,outlet_pressure_pa=pout,pressure_drop_pa=pin-pout,
    inlet_flux_m3_s=qin,outlet_flux_m3_s=qout,inlet_temperature_k=tin,outlet_temperature_k=tout,
    heat_loss_w=loss,inlet_axial_diffusion_w=diffin,outlet_axial_diffusion_w=diffout).items():
    qs.setoutputvalue(label,float(value))
points = [[float(x),float(r*np.cos(theta)),float(r*np.sin(theta))]
    for x in np.linspace(0,0.2,31)
    for r in (0.,0.036000000000000004,0.07200000000000001)
    for theta in np.linspace(0,2*np.pi,8,endpoint=False)]
xyz = [v for point in points for v in point]
qs.setoutputvalue('sample_xyz_m',xyz)
qs.setoutputvalue('sample_pressure_pa',qs.allinterpolate(reg.cartridge,qs.expression(fld.v),xyz))
qs.setoutputvalue('sample_temperature_k',qs.allinterpolate(reg.cartridge,qs.expression(fld.T),xyz))
qs.setoutputvalue('sample_axial_velocity_m_s',qs.allinterpolate(reg.cartridge,qs.compx(u),xyz))
