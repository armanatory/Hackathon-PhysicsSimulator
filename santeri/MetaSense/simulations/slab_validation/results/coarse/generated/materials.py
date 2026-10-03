import math
from functools import cache
from typing import cast
import quanscient as qs
from expressions import expr
from regions import reg

class AssumedLosslessSlab:
    @cache
    def epsilon(self):
        """
        Electric permittivity
        """
        return expr.n_slab * expr.n_slab * qs.getepsilon0()

    @cache
    def mu(self):
        """
        Magnetic permeability
        """
        return qs.getmu0()

    @cache
    def sigma(self):
        """
        Electric conductivity
        """
        return 0.0


class VacuumBenchmarkExterior:
    @cache
    def epsilon(self):
        """
        Electric permittivity
        """
        return qs.getepsilon0()

    @cache
    def mu(self):
        """
        Magnetic permeability
        """
        return qs.getmu0()

    @cache
    def sigma(self):
        """
        Electric conductivity
        """
        return 0.0


class Materials:
    @property
    @cache
    def assumed_lossless_slab(self) -> AssumedLosslessSlab:
        return AssumedLosslessSlab()

    @property
    @cache
    def vacuum_benchmark_exterior(self) -> VacuumBenchmarkExterior:
        return VacuumBenchmarkExterior()


mat = Materials()
