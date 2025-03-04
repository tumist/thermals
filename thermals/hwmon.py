
from gi.repository import Gtk, GObject, Gio, GLib
import glob
from os.path import basename
import os.path
from collections.abc import Iterator

from thermals.utils import Unit, readlineStrip, readGio, time_it, empty
from thermals.sensor import Sensor

def convertTemp(inp: str):
    return float(inp) / 1000.0

def convertWatt(inp: str):
    return float(inp) / 1000000.0

class Hwmon(Gtk.Box):
    def __init__(self, app, config):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.app = app
        self.config = config
        self.devices = []
        
        # TODO: Use regexp to catch more than 10 hwmon interfaces
        for dir in glob.glob("/sys/class/hwmon/hwmon[0-9]"):
            device = HwmonDevice(dir, config)
            device.app = self.app
            if empty(device.get_sensors()):
                print("Found no sensors in {}".format(dir))
                continue
            else:
                self.devices.append(device)
                self.append(device)
            
    @time_it("Hwmon refresh")
    def refresh(self):
        for sensor in self.get_sensors():
            sensor.refresh()

    def get_sensors(self, **kw):
        for dev in self.devices:
            for sensor in dev.get_sensors(**kw):
                yield sensor
    
    def select_sensor(self, sensor):
        for dev in self.devices:
            if dev.select_sensor(sensor):
                dev.grab_focus()

class HwmonDevice(Gtk.Expander):
    def __init__(self, dir, config):
        self.name = basename(dir)
        self.id = basename(dir)
        try:
            hwmon_name = readlineStrip(dir + "/name")
            self.name += " [" + hwmon_name + "]"
            self.id += ":" + hwmon_name
        except FileNotFoundError:
            pass

        self.config = config
        self.config_section = self.config[self.id]
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
        ss = Gtk.SingleSelection(autoselect=False, model=store, can_unselect=True)
        self.ss = ss

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
                elif item_property == "plot":
                    check = Gtk.CheckButton(active=item.get_item().plot)
                    colorDialog = Gtk.ColorDialog(with_alpha=False)
                    color = Gtk.ColorDialogButton(dialog=colorDialog, rgba=item.get_item().color)
                    color.connect("notify::rgba", lambda *a: item.get_item().set_color_rgba(color.get_rgba()))

                    box = Gtk.Box()
                    box.append(check)
                    box.append(color)
                    item.set_child(box)
                    item.get_item().bind_property("plot", check, "active",
                                                  GObject.BindingFlags.BIDIRECTIONAL)
                    item.get_item().connect("notify::plot", lambda *args: self.app.plots.recreate_plots())

            factory.connect('bind', factory_bind)
            column = Gtk.ColumnViewColumn(title=column_title, factory=factory, **kw)
            self.view.append_column(column)
        
        setup_factory("Name", "name", expand=True)
        setup_factory("Value", "valueStr")
        setup_factory("Plot", "plot")

        self.store = store
        self.set_child(self.view)
    
    def find_sensors(self) -> Iterator[Sensor]:
        """Scans /sys/class/hwmon"""

        for temp in glob.glob("temp[0-9]_input", root_dir=self.dir):
            name = temp.split('_')[0]
            cfg = self.config["{}:{}".format(self.id, name)]
            yield Temperature(self, name, cfg)
        
        for fan in glob.glob("fan[0-9]_input", root_dir=self.dir):
            name = fan.split('_')[0]
            cfg = self.config["{}:{}".format(self.id, name)]
            yield Fan(self, name, cfg)
        
        for pwm in glob.glob("pwm[0-9]", root_dir=self.dir):
            name = pwm
            cfg = self.config["{}:{}".format(self.id, name)]
            yield Pwm(self, name, cfg)
        
        for power in glob.glob("power[0-9]_average", root_dir=self.dir):
            name = power.split('_')[0]
            cfg = self.config["{}:{}".format(self.id, name)]
            yield Power(self, name, cfg)
    
    def select_sensor(self, sensor: Sensor):
        #print("Selecting sensor {}".format(sensor))
        for (i, s) in enumerate(self.store):
            if s == sensor:
                #print("Found sensor at position {}".format(i))
                #self.view.scroll_to(i, None, Gtk.ListScrollFlags.SELECT)
                self.set_expanded(True)
                self.ss.set_selected(i)
                #self.ss.grab_focus()
                return True
        self.ss.set_selected(Gtk.INVALID_LIST_POSITION)
    
    def on_expanded(self, *a):
        self.config_section['expanded'] = str(self.get_property('expanded'))
        self.config.write()

    def get_sensors(self, plot : bool | None = None, unit : int | None = None):
        """Return sensors using filters.
        
        No filters -> All sensors
        """
        for item in self.store:
            if plot != None and item.plot != plot:
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
            #label = readStrip(os.path.join(self.device.dir, self.measurement + "_label"))
            label = readGio(os.path.join(self.device.dir, self.measurement + "_label"))()
            self.name = label
        except (FileNotFoundError, GLib.GError):
            pass

    def get_value(self):
        # return convertTemp(readlineStrip(
        #     os.path.join(self.device.dir, self.measurement + "_input")))
        return readGio(os.path.join(self.device.dir, self.measurement + "_input"),
                       func = convertTemp)()
    
    def format(self):
        return "{:.1f}{}".format(self.value, Unit(self.unit))

class Fan(HwmonSensor):
    unit = Unit.RPM.value

    def get_value(self):
        # return int(readlineStrip(
        #     os.path.join(self.device.dir, self.measurement + "_input")))
        return readGio(os.path.join(self.device.dir, self.measurement + "_input"),
                       func = int)()
    
    def format(self):
        return "{} {}".format(self.value, Unit(self.unit))

class Pwm(HwmonSensor):
    unit = Unit.PWM.value
    def get_value(self):
        # return int(readlineStrip(
        #     os.path.join(self.device.dir, self.measurement)))
        return readGio(os.path.join(self.device.dir, self.measurement), func = int)()
    
    def format(self):
        return "{}{}".format(self.value, Unit(self.unit))

class Power(HwmonSensor):
    unit = Unit.WATT.value
    def get_value(self):
        # return convertWatt(readlineStrip(
        #     os.path.join(self.device.dir, self.measurement + "_average")
        # ))
        return readGio(os.path.join(self.device.dir, self.measurement + "_average"),
                       func = convertWatt)()
    def format(self):
        return "{}{}".format(self.value, Unit(self.unit))
