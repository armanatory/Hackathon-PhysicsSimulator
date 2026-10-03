var = Variables()
mesh = Mesh()
fld = Fields()
df = DerivedFields()

# Load the mesh
mesh.mesh = qs.mesh()
mesh.mesh.setphysicalregions(*reg.get_region_data())
mesh.skin = reg.get_next_free()
mesh.mesh.selectskin(mesh.skin)
mesh.mesh.partition([[reg.xmin], [reg.ymin]], [[reg.xmax], [reg.ymax]], [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]], [[expr.period], [expr.period]], 2)
mesh.mesh.load("gmsh:simulation.msh", mesh.skin, 1, 1)

# Fundamental frequency
var.f = expr.frequency
var.step_index = 0.0

qs.setfundamentalfrequency(var.f)

# Electric field
fld.E = qs.field("hcurl", [2, 3])
fld.E.setorder(reg.domain, 2)

df.E = qs.parameter(3, 1)

# Electric field
df.E.addvalue(reg.domain, fld.E)

form = qs.formulation()

# Electromagnetic waves
form += qs.integral(reg.domain, 3, qs.predefinedemwave(qs.dof(fld.E), qs.tf(fld.E), par.mu(), 0, par.epsilon(), 0, par.sigma(), 0, "oo2"))

# Absorbing boundary interaction: Open entrance
form += qs.integral(reg.entrance, 3, qs.predefinedemboundaryadmittance(qs.dof(fld.E), qs.tf(fld.E), qs.sqrt(par.epsilon() * qs.inverse(par.mu())), 0.0))

# Absorbing boundary interaction: Open exit
form += qs.integral(reg.exit, 3, qs.predefinedemboundaryadmittance(qs.dof(fld.E), qs.tf(fld.E), qs.sqrt(par.epsilon() * qs.inverse(par.mu())), 0.0))

# Periodicity interaction: Zero phase x periodicity
form += qs.periodicitycondition(reg.xmin, reg.xmax, fld.E, [1.0, 0.0, 0.0], [expr.period], 1)

# Periodicity interaction: Zero phase y periodicity
form += qs.periodicitycondition(reg.ymin, reg.ymax, fld.E, [0.0, 1.0, 0.0], [expr.period], 1)

form.allsolve(relrestol=1e-09, maxnumit=1000, nltol=1e-05, maxnumnlit=1000, relaxvalue=-1)

