from gi.repository import GObject, Gdk

from time import monotonic_ns

from thermals.utils import Unit, monotonic_s

class Sensor(GObject.Object):
    name = GObject.Property(type=str)
    #value = GObject.Property(type=int)
    valueStr = GObject.Property(type=str)
    time = GObject.Property(type=int)
    plot = GObject.Property(type=bool, default=False)
    color = GObject.Property(type=Gdk.RGBA)
    unit = GObject.Property(type=int)

    def __init__(self, name, config):
        super().__init__()
        self.name = name
        self.config = config

        self.color = Gdk.RGBA()
        self.color.parse(config['color'])
        self.plot = config.getboolean('plot')

        self.value = self.get_value()
        self.format_valueStr()

        self.connect('notify::plot', self.on_plot)
    
    def __repr__(self):
        return "Sensor {} {}{}".format(self.name, self.valueStr, self.unit)

    def get_value(self):
        raise NotImplementedError
    
    def format_valueStr(self):
        raise NotImplementedError
    
    def refresh(self):
        #t0 = monotonic_ns()
        self.value = self.get_value()
        self.time = monotonic_s()
        self.format_valueStr()
        #t1 = monotonic_ns()
        #print("Sensor {} refresh took {} ns".format(self.name, t1-t0))
    
    def set_color_rgba(self, color: Gdk.RGBA):
        self.color = color
        self.config['color'] = color.to_string()
        self.config.write()
    
    def RGB_triple(self):
        return (self.color.red, self.color.green, self.color.blue)

    def on_plot(self, *a):
        self.config['plot'] = str(self.plot)
        self.config.write()