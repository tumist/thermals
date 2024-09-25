from gi.repository import Gtk, GObject, Gio
import glob # TODO: Use regexp
from os.path import basename
import os.path
from collections.abc import Iterator

from utils import Unit, readStrip, readGio
from sensor import Sensor

def convertTemp(inp: str):
    return float(inp) / 1000.0

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
        for sensor in self.get_sensors():
            sensor.refresh()

    def get_sensors(self, **kw):
        for dev in self.devices:
            for sensor in dev.get_sensors(**kw):
                yield sensor

class HwmonDevice(Gtk.Expander):
    def __init__(self, dir, config):
        self.name = basename(dir)
        try:
            hwmon_name = readStrip(dir + "/name")
            self.name += " [" + hwmon_name + "]"
        except FileNotFoundError:
            pass

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
        for sensor in self.find_sensors():
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
    
    def find_sensors(self) -> Iterator[Sensor]:
        """Scans /sys/class/hwmon"""

        for temp in glob.glob("temp[0-9]_input", root_dir=self.dir):
            name = temp.split('_')[0]
            cfg = self.config["{}:{}".format(self.name, name)]
            yield Temperature(self, name, cfg)
        
        for fan in glob.glob("fan[0-9]_input", root_dir=self.dir):
            name = fan.split('_')[0]
            cfg = self.config["{}:{}".format(self.name, name)]
            yield Fan(self, name, cfg)
    
    def on_expanded(self, *a):
        self.config_section['expanded'] = str(self.get_property('expanded'))
        self.config.write()

    def get_sensors(self, graph : bool | None = None, unit : int | None = None):
        """Return sensors using filters.
        
        No filters -> All sensors
        """
        for item in self.store:
            if graph != None and item.graph != graph:
                continue
            if unit != None and item.unit != unit:
                continue
            yield item

class HwmonSensor(Sensor):
    def __init__(self, device, measurement, config):
        self.device = device
        self.measurement = measurement
        super().__init__(measurement, config)
    
    def format_valueStr(self):
        self.valueStr = self.format()

class Temperature(HwmonSensor):
    unit = Unit.CELCIUS.value

    def __init__(self, *args):
        super().__init__(*args)
        try:
            label = readStrip(os.path.join(self.device.dir, self.measurement + "_label"))
            self.name = label
        except FileNotFoundError:
            pass

    def get_value(self):
        return convertTemp(readStrip(
            os.path.join(self.device.dir, self.measurement + "_input")))
    
    def format(self):
        return "{:.1f}{}".format(self.value, Unit(self.unit))

class Fan(HwmonSensor):
    unit = Unit.RPM.value

    def get_value(self):
        return int(readStrip(
            os.path.join(self.device.dir, self.measurement + "_input")))
    
    def format(self):
        return "{} {}".format(self.value, Unit(self.unit))