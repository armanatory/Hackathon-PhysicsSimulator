from tagmappings import tag_mappings

class PhysicalRegions:
    def __init__(self):
        self._max_physical_region = 106

    @property
    def cartridge(self) -> int:
        """
        cartridge
        Consists of volume entities [1]
        """
        return 100

    @property
    def boundary(self) -> int:
        """
        boundary
        Consists of surface entities [2, 8, 9]
        """
        return 101

    @property
    def inlet(self) -> int:
        """
        inlet
        Consists of surface entities [9]
        """
        return 102

    @property
    def outlet(self) -> int:
        """
        outlet
        Consists of surface entities [8]
        """
        return 103

    @property
    def ends(self) -> int:
        """
        ends
        Consists of surface entities [8, 9]
        """
        return 104

    @property
    def wall(self) -> int:
        """
        wall
        Consists of surface entities [2]
        """
        return 105

    @property
    def all(self) -> int:
        """
        All
        Consists of volume entities [1]
        """
        return 106

    def get_next_free(self, how_many = 1) -> int:
        self._max_physical_region += how_many
        return self._max_physical_region

    def get_region_data(self):
        """
        Returns the region data (dimensions, physical region numbers, entity tags)
        for every region in the simulation
        """
        return tag_mappings.map_region_data((
            [3, 2, 2, 2, 2, 2, 3],
            [100, 101, 102, 103, 104, 105, 106],
            [[1], [2, 8, 9], [9], [8], [8, 9], [2], [1]],
        ))


reg = PhysicalRegions()
