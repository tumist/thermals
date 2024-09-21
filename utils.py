from enum import Enum

class Unit(Enum):
    CELCIUS = 0
    RPM = 1

    def __str__(self):
        match self:
            case Unit.CELCIUS: return "°C"
            case Unit.RPM: return "RPM"

    def graph_lines(self):
        match self:
            case Unit.RPM: return 250
            case Unit.CELCIUS: return 10

def readStrip(path):
    with open(path, 'r') as fd:
        return fd.readline().strip()
