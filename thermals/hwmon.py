
from gi.repository import Gtk, GObject, Gio, GLib, Pango
import glob
from os.path import basename
import os.path
from collections.abc import Iterator

from thermals.utils import Unit, readlineStrip, readGio, time_it, empty, reglob, monotonic_s
from thermals.sensor import Sensor
from thermals.curve import CurveHwmonWindow

def convertTemp(inp: str):
    return float(inp) / 1000.0

def convertWatt(inp: str):
    return float(inp) / 1000000.0

class Hwmon(Gtk.Box):
    def __init__(self, app):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.app = app
        self.devices = []

    def find_devices(self):
        for dir in reglob("/sys/class/hwmon/hwmon[0-9]+"):
            device = HwmonDevice(self.app, dir)
            if empty(device.get_sensors()):
                print("Found no sensors in {}".format(dir))
                continue
            else:
                self.devices.append(device)
                self.append(device)
            
    @time_it("Hwmon refresh")
    def refresh(self):
        for sensor in self.get_sensors():
            time_it("{} refresh".format(sensor))(sensor.refresh)()

    def get_sensors(self, **kw):
        for dev in self.devices:
            for sensor in dev.get_sensors(**kw):
                yield sensor
    
    def select_sensor(self, sensor):
        for dev in self.devices:
            if dev.select_sensor(sensor):
                dev.grab_focus()

class HwmonDevice(Gtk.Expander):
    def __init__(self, app, dir):
        self.app = app
        self.dir = dir
        # The `id` only becomes the device identifier for now.
        # It may be needed to have this a device path or something like that,
        # also a device might have multiple hwmon instances. TODO
        self.id = os.path.basename(os.readlink(dir + "/device"))
        self.name = readlineStrip(dir + "/name")
        self.hwmonInstance = os.path.basename(dir)

        self.config_section = self.app.config[self.id]
        self.config_section.write()
        super().__init__(expanded=self.config_section.getboolean('expanded'),
                         halign=Gtk.Align.BASELINE)
        
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        label_name = Gtk.Label(label=self.name, hexpand=True, halign=Gtk.Align.START)
        label_id = Gtk.Label(label="<small>{}</small>".format(self.hwmonInstance), halign=Gtk.Align.END, margin_end=10)
        label_id.set_use_markup(True)
        box.append(label_name)
        box.append(label_id)
        self.set_label_widget(box)

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
                    sensor = item.get_item()
                    if sensor.has_configuration():
                        box = Gtk.Box()
                        label = Gtk.Label(label=sensor.get_property(item_property),
                                          hexpand=True,
                                          xalign=0,
                                          ellipsize=Pango.EllipsizeMode.END)
                        cfg = Gtk.Button.new_from_icon_name("preferences-system")
                        cfg.connect('clicked', lambda *a: sensor.configure(app=self.app))
                        box.append(label)
                        box.append(cfg)
                        item.set_child(box)
                    else:
                        item.set_child(Gtk.Label(label=sensor.get_property(item_property),
                                                 xalign=0,
                                                 ellipsize=Pango.EllipsizeMode.END))
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
                    item.get_item().connect("notify::plot", lambda *args: self.app.win.plots.recreate_plots())

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

        for temp in reglob("temp[0-9]+_input$", root_dir=self.dir):
            name = temp.split('_')[0]
            cfg = self.app.config["{}:{}".format(self.id, name)]
            yield Temperature(self, name, cfg)
        
        for fan in reglob("fan[0-9]+_input$", root_dir=self.dir):
            name = fan.split('_')[0]
            cfg = self.app.config["{}:{}".format(self.id, name)]
            yield Fan(self, name, cfg)
        
        for pwm in reglob("pwm[0-9]+$", root_dir=self.dir):
            name = pwm
            cfg = self.app.config["{}:{}".format(self.id, name)]
            yield Pwm(self, name, cfg)
        
        for power in reglob("power[0-9]+_label$", root_dir=self.dir):
            name = power.split('_')[0]
            cfg = self.app.config["{}:{}".format(self.id, name)]
            yield Power(self, name, cfg)

        for energy in reglob("energy[0-9]+_label$", root_dir=self.dir):
            name = energy.split('_')[0]
            cfg = self.app.config["{}:{}".format(self.id, name)]
            yield Energy(self, name, cfg)

    
    def select_sensor(self, sensor: Sensor):
        for (i, s) in enumerate(self.store):
            if s == sensor:
                #self.view.scroll_to(i, None, Gtk.ListScrollFlags.SELECT)
                self.set_expanded(True)
                self.ss.set_selected(i)
                #self.ss.grab_focus()
                return True
        self.ss.set_selected(Gtk.INVALID_LIST_POSITION)
    
    def on_expanded(self, *a):
        self.config_section['expanded'] = str(self.get_property('expanded'))
        self.app.config.write()

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
        try:
            #label = readStrip(os.path.join(self.device.dir, self.measurement + "_label"))
            label = readGio(os.path.join(self.device.dir, self.measurement + "_label"))()
            self.name = label
        except (FileNotFoundError, GLib.GError):
            pass
    
    def format_valueStr(self):
        self.valueStr = Unit(self.unit).format_value(self.value)
    
    def has_configuration(self):
        return False

class Temperature(HwmonSensor):
    unit = Unit.CELCIUS.value

    def get_value(self):
        # return convertTemp(readlineStrip(
        #     os.path.join(self.device.dir, self.measurement + "_input")))
        return readGio(os.path.join(self.device.dir, self.measurement + "_input"),
                       func = convertTemp)()

class Fan(HwmonSensor):
    unit = Unit.RPM.value

    def get_value(self):
        # return int(readlineStrip(
        #     os.path.join(self.device.dir, self.measurement + "_input")))
        return readGio(os.path.join(self.device.dir, self.measurement + "_input"),
                       func = int)()

class Pwm(HwmonSensor):
    unit = Unit.PWM.value
    def get_value(self):
        # return int(readlineStrip(
        #     os.path.join(self.device.dir, self.measurement)))
        return readGio(os.path.join(self.device.dir, self.measurement), func = int)()
    
    def has_configuration(self):
        full_path = os.path.join(self.device.dir, self.measurement)
        path_enable = full_path + "_enable"
        return os.path.exists(full_path + "_auto_point1_pwm") and \
               os.path.exists(path_enable) and \
               readGio(path_enable)() == "5"

    def configure(self, app=None):
        win = CurveHwmonWindow(self,
            application = app,
            title = "{} {}".format(self.device.name, self.measurement))
        win.present()


class Power(HwmonSensor):
    unit = Unit.WATT.value
    def get_value(self):
        # return convertWatt(readlineStrip(
        #     os.path.join(self.device.dir, self.measurement + "_average")
        # ))
        if os.path.exists(os.path.join(self.device.dir, self.measurement + "_average")):
            return readGio(os.path.join(self.device.dir, self.measurement + "_average"), func = convertWatt)()
        else:
            return readGio(os.path.join(self.device.dir, self.measurement + "_input"), func = convertWatt)()

class Energy(HwmonSensor):
    # Energy reads energy counters in Joules.
    # `get_value` converts it to Watts and therefor needs the previous value.
    unit = Unit.WATT.value
    previous_joules = None
    # time = None # set when `refresh`ed

    def get_value(self):
        current_joules = readGio(
            os.path.join(self.device.dir, self.measurement + "_input"),
            func = convertWatt)()

        if not self.previous_joules or not self.time:
            self.previous_joules = current_joules
            return
        
        dt = monotonic_s() - self.time
        if dt <= 0:
            return
        difference = current_joules - self.previous_joules
        if difference < 0:
            # Counter has wrapped around, and we don't have a value.
            # Maybe someone can fix this.
            return
        self.previous_joules = current_joules
        return difference / dt
