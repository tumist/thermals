from gi.repository import Gio
from enum import Enum
from time import monotonic_ns

class Unit(Enum):
    CELCIUS = 0
    RPM = 1
    PWM = 2

    def __str__(self):
        match self:
            case Unit.CELCIUS: return "°C"
            case Unit.RPM: return "RPM"
            case Unit.PWM: return ""

    def graph_lines(self) -> int:
        match self:
            case Unit.RPM: return 250
            case Unit.CELCIUS: return 10
            case Unit.PWM: return 10

def readStrip(path: str) -> str:
    with open(path, 'r') as fd:
        return fd.readline().strip()

def monotonic_s() -> int:
    return monotonic_ns() // 1000000000

def readGio(path, func=lambda x: x):
    uri = Gio.File.new_for_path(path)
    def inner():
        status, contents, etag_out = Gio.File.load_contents(uri)
        return func(contents.strip())
    return inner