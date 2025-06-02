import sys
import os
import re
from gi.repository import Gio
from enum import Enum
from time import monotonic_ns
from collections.abc import Iterator


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
    
    def round(self, value):
        match self:
            case Unit.RPM: return round(value)
            case Unit.CELCIUS: return round(value, 1)
            case Unit.PWM: return round(value)
            case Unit.WATT:
                if value < 100: return round(value, 1)
                else: return round(value)

    def format_value(self, value):
        if self == Unit.PWM:
            return "{}%".format(round(value/2.55))
        elif self == Unit.CELCIUS:
            return "{}{}".format(self.round(value), self)
        else:
            return "{} {}".format(self.round(value), self)

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

def empty(gen: Iterator) -> bool:
    try:
        next(gen)
        return False
    except StopIteration:
        return True

def reglob(path, root_dir=None):
    if root_dir is None and path[0] == '/':
        dir, exp = path.rsplit('/', 1)
    else:
        dir = root_dir
        exp = path
    regexp = re.compile(exp)
    for file in os.listdir(dir):
        if re.match(regexp, file):
            if root_dir is None:
                yield os.path.join(dir, file)
            else:
                yield file