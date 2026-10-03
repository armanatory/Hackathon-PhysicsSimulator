import math
import quanscient as qs

class Empty:
    pass

class Dynamic:
    def __getattr__(self, attr):
        if attr not in self.__dict__:
            self.__dict__[attr] = Empty()
        return self.__dict__[attr]

class Variables:
    pass

class Mesh:
    mesh: qs.mesh
    skin: int

class Fields:
    v: qs.field
    T: qs.field

class DerivedFields:
    E: qs.parameter

class Ports(Dynamic):
    pass

# Deprecated
class Consts(Variables):
    pass
