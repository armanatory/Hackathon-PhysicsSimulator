import math
from functools import cache
from typing import cast
import quanscient as qs
from expressions import expr
from regions import reg

class EnteredEquivalentProperties:
    @cache
    def cp(self):
        """
        Heat capacity
        """
        return 1100.0

    @cache
    def epsilon(self):
        """
        Electric permittivity
        """
        return 1.0

    @cache
    def k(self):
        """
        Thermal conductivity
        """
        return 0.5

    @cache
    def rho(self):
        """
        Density
        """
        return 0.4881245722812952


class Materials:
    @property
    @cache
    def entered_equivalent_properties(self) -> EnteredEquivalentProperties:
        return EnteredEquivalentProperties()


mat = Materials()
