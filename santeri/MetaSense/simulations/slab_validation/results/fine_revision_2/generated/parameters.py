from functools import cache
import quanscient as qs
from expressions import expr
from materials import mat
from regions import reg

class Parameters:
    @cache
    def sigma(self) -> qs.parameter:
        """
        Electric conductivity
        """
        p = qs.parameter(1, 1)

        p.setvalue(reg.air, mat.vacuum_benchmark_exterior.sigma())
        p.setvalue(reg.slab, mat.assumed_lossless_slab.sigma())

        return p

    @cache
    def epsilon(self) -> qs.parameter:
        """
        Electric permittivity
        """
        p = qs.parameter(1, 1)

        p.setvalue(reg.air, mat.vacuum_benchmark_exterior.epsilon())
        p.setvalue(reg.slab, mat.assumed_lossless_slab.epsilon())

        return p

    @cache
    def mu(self) -> qs.parameter:
        """
        Magnetic permeability
        """
        p = qs.parameter(1, 1)

        p.setvalue(reg.air, mat.vacuum_benchmark_exterior.mu())
        p.setvalue(reg.slab, mat.assumed_lossless_slab.mu())

        return p


par = Parameters()
