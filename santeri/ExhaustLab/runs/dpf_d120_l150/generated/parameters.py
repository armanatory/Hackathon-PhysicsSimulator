from functools import cache
import quanscient as qs
from expressions import expr
from materials import mat
from regions import reg

class Parameters:
    @cache
    def epsilon(self) -> qs.parameter:
        """
        Electric permittivity
        """
        p = qs.parameter(1, 1)

        p.setvalue(reg.cartridge, mat.entered_equivalent_properties.epsilon())

        return p

    @cache
    def k(self) -> qs.parameter:
        """
        Thermal conductivity
        """
        p = qs.parameter(1, 1)

        p.setvalue(reg.cartridge, mat.entered_equivalent_properties.k())

        return p

    @cache
    def rho(self) -> qs.parameter:
        """
        Density
        """
        p = qs.parameter(1, 1)

        p.setvalue(reg.cartridge, mat.entered_equivalent_properties.rho())

        return p

    @cache
    def cp(self) -> qs.parameter:
        """
        Heat capacity
        """
        p = qs.parameter(1, 1)

        p.setvalue(reg.cartridge, mat.entered_equivalent_properties.cp())

        return p


par = Parameters()
