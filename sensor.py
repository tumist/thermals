from gi.repository import GObject, Gdk

from utils import Unit

class Sensor(GObject.Object):
    name = GObject.Property(type=str)
    #value = GObject.Property(type=float)
    valueStr = GObject.Property(type=str)
    graph = GObject.Property(type=bool, default=False)
    color = GObject.Property(type=Gdk.RGBA)
    unit = GObject.Property(type=int)

    def __init__(self, name, get_value, config, unit=None):
        super().__init__()
        self.name = name
        self.get_value = get_value
        self.config = config
        if unit:
            self.unit = unit.value

        self.color = Gdk.RGBA()
        self.color.parse(config['color'])
        self.graph = config.getboolean('graph')

        self.value = get_value()
        self.format_valueStr()

        self.connect('notify::graph', self.on_graph)
    
    def format_valueStr(self):
        if type(self.value) == float:
            self.valueStr = "{:.1f} {}".format(self.value, Unit(self.unit))
        else:
            self.valueStr = "{} {}".format(self.value, Unit(self.unit))
    
    def refresh(self):
        self.value = self.get_value()
        self.format_valueStr()
    
    def set_color_rgba(self, color: Gdk.RGBA):
        self.color = color
        self.config['color'] = color.to_string()
        self.config.write()
    
    def RGB_triple(self):
        return (self.color.red, self.color.green, self.color.blue)

    def on_graph(self, *a):
        self.config['graph'] = str(self.graph)
        self.config.write()