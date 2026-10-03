import json
import os

TagMap = dict[int, list[int]]
RegionData = tuple[list[int], list[int], list[list[int]]]


class TagMappings:
    """
    TagMappings helper functionality to map between geometry model tags and mesh tags. The tags
    can differ for example when using the mesh extrusion.
    """
    def __init__(self, tag_map_file: str) -> None:
        self._tag_map: tuple[TagMap, TagMap, TagMap, TagMap] = ({}, {}, {}, {})

        try:
            if not os.path.isfile(tag_map_file):
                return

            with open(tag_map_file) as f:
                data = json.load(f)

                for i, entity_type in enumerate(['points', 'curves', 'surfaces', 'volumes']):
                    for key in data[entity_type]:
                        self._tag_map[i][int(key)] = data[entity_type][key]

        except BaseException:
            raise RuntimeError("Error parsing tag mapping file")

    def map_tags(self, dim: int, geo_tags: list[int]) -> list[int]:
        """
        Maps from a list of tags in the geometry to the set of corresponding tags in the mesh.
        :param dim: the dimension (0, 1, 2 or 3, for point, curve, surface or volume, respectively)
        :param geo_tags: the list of geometry tags
        :return: the list of mesh tags corresponding to the geometry tags
        """
        mapped: list[int] = []

        for tag in geo_tags:
            mapping = self._tag_map[dim].get(tag, [tag])
            mapped.extend(mapping)

        return mapped

    def map_tag(self, dim: int, geo_tag: int) -> list[int]:
        """
        Maps from a tag in the geometry to the set of corresponding tags in the mesh.
        :param dim: the dimension (0, 1, 2 or 3, for point, curve, surface or volume, respectively)
        :param geo_tag: the geometry tag
        :return: the list of mesh tags corresponding to the geometry tag
        """
        return self.map_tags(dim, [geo_tag])

    def map_region_data(self, region_data: RegionData) -> RegionData:
        """
        Maps from the geometry tags in region data to the corresponding tags in the mesh. Returns the
        mapped region data. Region data contains three lists of equal length with dimensions, physical tags
        and lists of geometry tags, respectively.
        :param region_data: the region data containing dimension list, physical tag list and the list of geometry tags
        :return: the mapped region data
        """
        result: RegionData = (
            region_data[0],
            region_data[1],
            [],
        )

        for i, geo_tags in enumerate(region_data[2]):
            dim = region_data[0][i]
            result[2].append(self.map_tags(dim, geo_tags))

        return result


tag_mappings = TagMappings('simulation.tagmap.json')