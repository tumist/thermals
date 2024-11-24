import sys
from gi.repository import Gio
from enum import Enum
from time import monotonic_ns

class Unit(Enum):
    CELCIUS = 0
    RPM = 1
    PWM = 2
    WATT = 3

    def __str__(self):
        match self:
            case Unit.CELCIUS: return "°C"
            case Unit.RPM: return "RPM"
            case Unit.PWM: return ""
            case Unit.WATT: return "W"

    def title(self) -> str:
        match self:
            case Unit.CELCIUS: return "Celcius"
            case Unit.RPM: return "RPM"
            case Unit.PWM: return "PWM"
            case Unit.WATT: return "Watt"

    def plot_lines(self) -> int:
        match self:
            case Unit.RPM: return 250
            case Unit.CELCIUS: return 10
            case Unit.PWM: return 10
            case Unit.WATT: return 10

def readlineStrip(path: str) -> str:
    with open(path, 'r') as fd:
        return fd.readline().strip()

def monotonic_s() -> int:
    return monotonic_ns() // 1000000000

def readGio(path, func = lambda x: x, decode = 'utf-8'):
    uri = Gio.File.new_for_path(path)
    def inner():
        status, contents, etag_out = Gio.File.load_contents(uri)
        if decode:
            contents = contents.decode(decode)
        return func(contents.strip())
    return inner

def time_it(explain):
    def wrap(f):
        def inner(*args, **kw):
            ns0 = monotonic_ns()
            ret = f(*args, **kw)
            ns1 = monotonic_ns()
            print("{} took {:1.2f}ms".format(explain, (ns1-ns0)/1000000))
            return ret
        
        if "--time-it" in sys.argv:
            return inner
        else:
            return f
    return wrap