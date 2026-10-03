import math
from functools import cache
import quanscient as qs

class Expressions:
    @qs.cachedproperty
    def wavelength(self) -> float:
        """
        Vacuum wavelength, m
        """
        return 1e-06

    @qs.cachedproperty
    def period(self) -> float:
        """
        Lateral period, m
        """
        return 5e-07

    @qs.cachedproperty
    def thickness(self) -> float:
        """
        Slab thickness, m
        """
        return 1.6666666666666665e-07

    @qs.cachedproperty
    def clearance(self) -> float:
        """
        Air on either side, m
        """
        return 5e-07

    @qs.cachedproperty
    def n_slab(self) -> float:
        """
        Assumed real lossless index; n=1 control
        """
        return 1.5

    @qs.cachedproperty
    def frequency(self) -> float:
        """
        Hz
        """
        return 2.99792458e+08 / self.wavelength

    @qs.cachedproperty
    def E0(self) -> float:
        """
        Incident peak x-polarized field, V/m
        """
        return 1.0


expr = Expressions()
