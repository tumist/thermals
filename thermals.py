import sys
from collections import deque, defaultdict
from itertools import islice, takewhile, dropwhile, count, batched
from statistics import mean
from time import monotonic_ns
from enum import Enum
import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, GObject, Gio, GLib, Gdk
import configparser
import glob
from os.path import basename

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

class Config(configparser.ConfigParser):
    filename = "thermals.ini"
    def read(self):
        super().read(self.filename)
    def write(self):
        with open(self.filename, 'w') as configfile:
            super().write(configfile)
    def __getitem__(self, section):
        if not self.has_section(section) and not section == "DEFAULT":
            self.add_section(section)
        section = super().__getitem__(section)
        # Monkeypatch a write method
        section.write = self.write
        return section

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
        value = self.get_value()
        self.value = value
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
    # def set_color(self, color: str):
    #     rgba = Gdk.RGBA()
    #     rgba.parse(color)
    #     self.set_color_rgba(rgba)

class HwmonDevice(Gtk.Expander):
    def __init__(self, dir, config):
        self.name = basename(dir)
        self.config = config
        self.config_section = self.config[self.name]
        self.config_section.write()
        super().__init__(label=self.name,
                         expanded=self.config_section.getboolean('expanded'),
                         halign=Gtk.Align.BASELINE)
        self.dir = dir

        self.connect('notify::expanded', self.on_expanded)

        # List Store
        store = Gio.ListStore(item_type=Sensor)
        for sensor in self.sensors():
            store.append(sensor)

        # Selection model
        ss = Gtk.NoSelection(model=store)

        # Column View
        self.view = Gtk.ColumnView.new(model=ss)

        # Function to setup factory for creating cell widgets
        def setup_factory(column_title, item_property, **kw):
            factory = Gtk.SignalListItemFactory()

            def factory_bind(_, item):
                if item_property == "name":
                    item.set_child(Gtk.Label(label=item.get_item().get_property(item_property), xalign=0))
                elif item_property == "valueStr":
                    label = Gtk.Label(label=item.get_item().get_property(item_property))
                    item.set_child(label)
                    item.get_item().bind_property("valueStr", item.get_child(), "label",
                                                  GObject.BindingFlags.SYNC_CREATE)
                elif item_property == "graph":
                    check = Gtk.CheckButton(active=item.get_item().graph)
                    colorDialog = Gtk.ColorDialog(with_alpha=False)
                    color = Gtk.ColorDialogButton(dialog=colorDialog, rgba=item.get_item().color)
                    color.connect("notify::rgba", lambda *a: item.get_item().set_color_rgba(color.get_rgba()))

                    box = Gtk.Box()
                    box.append(check)
                    box.append(color)
                    item.set_child(box)
                    item.get_item().bind_property("graph", check, "active",
                                                  GObject.BindingFlags.BIDIRECTIONAL)

            factory.connect('bind', factory_bind)
            column = Gtk.ColumnViewColumn(title=column_title, factory=factory, **kw)
            self.view.append_column(column)
        
        setup_factory("Name", "name", expand=True)
        setup_factory("Value", "valueStr")
        setup_factory("Graph", "graph")

        self.store = store
        self.set_child(self.view)
    
    def sensors(self):
        def readStrip(path):
            with open(path, 'r') as fd:
                return fd.readline().strip()
        def keepFd(path, func=lambda a: a):
            fd = open(path, 'r')
            def inner():
                fd.seek(0)
                return func(fd.readline())
            return inner
        def convertTemp(inp: str):
            return float(inp) / 1000.0
        def convertInt(inp: str):
            return int(inp) / 100


        for temp in glob.glob("temp[0-9]_input", root_dir=self.dir):
            temp = temp.split('_')[0]
            try:
                label = readStrip("{}/{}_label".format(self.dir, temp))
            except FileNotFoundError:
                label = temp
            yield Sensor(label,
                         keepFd("{}/{}_input".format(self.dir, temp), func=convertTemp),
                         self.config["{}:{}".format(self.name, temp)])
        
        for fan in glob.glob("fan[0-9]_input", root_dir=self.dir):
            name = fan.split('_')[0]
            yield Sensor(name,
                         keepFd("{}/{}".format(self.dir, fan), func=int),
                         self.config["{}:{}".format(self.name, name)],
                         unit=Unit.RPM)
    
    def refresh(self):
        for item in self.store:
            item.refresh()
    
    def on_expanded(self, *a):
        self.config_section['expanded'] = str(self.get_property('expanded'))
        self.config.write()

    def get_sensors(self, graph : bool | None = None, unit : int | None = None):
        for item in self.store:
            if graph != None and item.graph != graph:
                continue
            if unit != None and item.unit != unit:
                continue
            yield item

class Hwmon(Gtk.Box):
    def __init__(self, config):
        self.config = config
        super().__init__(orientation=Gtk.Orientation.VERTICAL)

        self.devices = []
        for dir in glob.glob("/sys/class/hwmon/hwmon[0-9]"):
            device = HwmonDevice(dir, config)
            self.devices.append(device)
            self.append(device)
    
    def refresh(self):
        for dev in self.devices:
            dev.refresh()

    def get_sensors(self, **kw):
        for dev in self.devices:
            for sensor in dev.get_sensors(**kw):
                yield sensor

class GraphCanvas(Gtk.DrawingArea):
    drawDark = GObject.Property(type=bool, default=False)
    graphSeconds = GObject.Property(type=int)

    def __init__(self, unit, sensors):
        super().__init__(hexpand=True, vexpand=True)
        self.unit = unit
        self.sensors = sensors

        self.set_draw_func(self.draw, None)

    def draw(self, area, c, w, h, data):
        if self.drawDark:
            bg_color = (0.1, 0.1, 0.1)
            fg_color = (0.2, 0.2, 0.2)
        else:
            bg_color = (0.964, 0.96, 0.913)
            fg_color = (0.8, 0.8, 0.8)

        # Fill background with a colour
        c.set_source_rgb(*bg_color)
        c.paint()

        sensors = list(self.sensors.get_sensors(graph=True, unit=self.unit.value))
        if not sensors:
            print("GraphCanvas {} has nothing to draw".format(self.unit))
            return

        #x_min = 0
        x_max = self.graphSeconds
        
        if self.unit == Unit.RPM:
            y_min = 0
        else:
            y_min = min([min(self.history[s]) for s in sensors])
        y_max = max([max(self.history[s]) for s in sensors])
        # Add 5% on max and min
        y_min -= (y_max-y_min)*0.05
        y_max += (y_max-y_min)*0.05

        if y_min == y_max:
            y_max += 1

        # Temp -> x 
        def translate_x(value: float) -> float:
            # 0 = w
            # grapSeconds = 0
            return w * (x_max - value) / (x_max)
        
        # Time index -> y
        def translate_y(value: float) -> float:
            return h * (1 - ((value - y_min) / (y_max - y_min)))

        # Draw background lines
        c.select_font_face("Sans")
        c.set_font_size(16)
        y_lines = list(takewhile(lambda v: v <= y_max, 
                    dropwhile(lambda v: v < y_min, 
                        count(0, self.unit.graph_lines()))))
        while h / len(y_lines) < 35:
            y_lines = y_lines[::2]
        for line in y_lines:
            c.set_source_rgb(*fg_color)
            c.set_line_width(1)
            c.move_to(0, translate_y(line))
            c.show_text("{} {}".format(line, self.unit))
            c.line_to(w, translate_y(line))
            c.stroke()

        # Draw sensors
        for sensor in sensors:
            history = list(islice(self.history[sensor], 0, x_max))
            hiter = enumerate(history)

            c.set_source_rgb(*sensor.RGB_triple())
            c.set_line_width(2)
            i0, v0 = next(hiter)
            
            c.move_to(translate_x(i0), translate_y(v0))
            for i, v in hiter:
                c.line_to(translate_x(i), translate_y(v))
            c.stroke()

class Graphs(Gtk.Box):
    timeSelections = [
        ("5 mins", 60 * 5),
        ("15 mins", 60 * 15),
        ("30 mins", 60 * 30),
        ("1 hour", 60 * 60),
        ("3 hours", 60 * 60 * 3)
    ]
    graphSeconds = GObject.Property(type=int, default=timeSelections[0][1])
    drawDark = GObject.Property(type=bool, default=False)

    def __init__(self, config, sensors):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.sensors = sensors
        self.history = defaultdict(lambda: deque([]))

        paned = Gtk.Paned(orientation=Gtk.Orientation.VERTICAL,
                          wide_handle=True)

        self.celcius = GraphCanvas(Unit.CELCIUS, self.sensors)
        self.celcius.sensors = sensors
        self.celcius.history = self.history
        self.bind_property('graphSeconds', self.celcius, 'graphSeconds', GObject.BindingFlags.SYNC_CREATE)
        self.bind_property('drawDark', self.celcius, 'drawDark', GObject.BindingFlags.SYNC_CREATE)
        paned.set_start_child(self.celcius)

        self.rpm = GraphCanvas(Unit.RPM, self.sensors)
        self.rpm.history = self.history
        self.bind_property('graphSeconds', self.rpm, 'graphSeconds', GObject.BindingFlags.SYNC_CREATE)
        self.bind_property('drawDark', self.rpm, 'drawDark', GObject.BindingFlags.SYNC_CREATE)
        paned.set_end_child(self.rpm)

        timeselector = Gtk.DropDown.new_from_strings(
            [s for (s, _) in self.timeSelections]
        )
        timeselector.connect("notify::selected", self.on_time_selected)

        self.append(paned)
        self.append(timeselector)

    def on_time_selected(self, dropdown, _):
        selected = dropdown.get_property("selected")
        self.graphSeconds = self.timeSelections[selected][1]
        self.celcius.queue_draw()
        self.rpm.queue_draw()
    
    def refresh(self):
        self.remember_sensors()
        self.celcius.queue_draw()
        self.rpm.queue_draw()
    
    def remember_sensors(self):
        for hwmon in self.sensors:
            for sensor in hwmon.store:
                self.history[sensor].insert(0, sensor.value)

class MainWindow(Gtk.ApplicationWindow):
    def __init__(self, application=None):
        super().__init__(application=application)
        self.app = application

        self.config = Config()
        self.config.read()
        self.config['DEFAULT']['expanded'] = 'True'
        self.config['DEFAULT']['color'] = "rgb(255, 255, 255)"
        self.config['DEFAULT']['graph'] = 'False'

        self.sensors = Hwmon(self.config)
        self.graph = Graphs(self.config, self.sensors)
        self.app.get_style_manager().bind_property('dark', self.graph, 'drawDark', GObject.BindingFlags.SYNC_CREATE)
        
        box = Gtk.Box()
        box.append(self.graph)
        box.append(Gtk.ScrolledWindow(child=self.sensors, hscrollbar_policy=Gtk.PolicyType.NEVER))
        self.set_child(box)
        self.set_default_size(900, 400)
        self.on_timer()

    def on_timer(self):
        GLib.timeout_add(1000, self.on_timer)
        t0 = monotonic_ns()
        self.sensors.refresh()
        t1 = monotonic_ns()
        self.graph.refresh()
        t2 = monotonic_ns()
        print("Sensor refresh took {0:1.0f}ms, Graph took {1:1.0f}ms"
              .format((t1-t0)/1000000, (t2-t1)/1000000))

class MyApp(Adw.Application):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.connect('activate', self.on_activate)

    def on_activate(self, app):
        self.win = MainWindow(application=app)
        self.win.present()

if __name__ == "__main__":
    app = MyApp(application_id="com.example.GtkApplication")
    app.run(sys.argv)
