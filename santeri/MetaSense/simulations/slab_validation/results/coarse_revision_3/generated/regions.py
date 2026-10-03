from tagmappings import tag_mappings

class PhysicalRegions:
    def __init__(self):
        self._max_physical_region = 111

    @property
    def air_left(self) -> int:
        """
        air_left
        Consists of volume entities [1]
        """
        return 100

    @property
    def slab(self) -> int:
        """
        slab
        Consists of volume entities [28]
        """
        return 101

    @property
    def air_right(self) -> int:
        """
        air_right
        Consists of volume entities [55]
        """
        return 102

    @property
    def domain(self) -> int:
        """
        domain
        Consists of volume entities [1, 28, 55]
        """
        return 103

    @property
    def entrance(self) -> int:
        """
        entrance
        Consists of surface entities [26]
        """
        return 104

    @property
    def exit(self) -> int:
        """
        exit
        Consists of surface entities [81]
        """
        return 105

    @property
    def xmin(self) -> int:
        """
        xmin
        Consists of surface entities [2, 29, 56]
        """
        return 106

    @property
    def xmax(self) -> int:
        """
        xmax
        Consists of surface entities [11, 38, 65]
        """
        return 107

    @property
    def ymin(self) -> int:
        """
        ymin
        Consists of surface entities [20, 47, 74]
        """
        return 108

    @property
    def ymax(self) -> int:
        """
        ymax
        Consists of surface entities [23, 50, 77]
        """
        return 109

    @property
    def air(self) -> int:
        """
        air
        Consists of volume entities [1, 55]
        """
        return 110

    @property
    def all(self) -> int:
        """
        All
        Consists of volume entities [1, 28, 55]
        """
        return 111

    def get_next_free(self, how_many = 1) -> int:
        self._max_physical_region += how_many
        return self._max_physical_region

    def get_region_data(self):
        """
        Returns the region data (dimensions, physical region numbers, entity tags)
        for every region in the simulation
        """
        return tag_mappings.map_region_data((
            [3, 3, 3, 3, 2, 2, 2, 2, 2, 2, 3, 3],
            [100, 101, 102, 103, 104, 105, 106, 107, 108, 109, 110, 111],
            [[1], [28], [55], [1, 28, 55], [26], [81], [2, 29, 56], [11, 38, 65], [20, 47, 74], [23, 50, 77], [1, 55], [1, 28, 55]],
        ))


reg = PhysicalRegions()
