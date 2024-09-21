from gi.repository import Gtk, GObject, Gio
import glob
from os.path import basename

from utils import Unit, readStrip
from sensor import Sensor

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
        def keepFd(path, func=lambda a: a):
            fd = open(path, 'r')
            def inner():
                fd.seek(0)
                return func(fd.readline())
            return inner
        def readGio(path, func=lambda a: a):
            uri = Gio.File.new_for_path(path)
            def inner():
                status, contents, etag_out = Gio.File.load_contents(uri)
                return func(contents.strip())
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
                         readGio("{}/{}_input".format(self.dir, temp), func=convertTemp),
                         self.config["{}:{}".format(self.name, temp)])
        
        for fan in glob.glob("fan[0-9]_input", root_dir=self.dir):
            name = fan.split('_')[0]
            yield Sensor(name,
                         readGio("{}/{}".format(self.dir, fan), func=int),
                         self.config["{}:{}".format(self.name, name)],
                         unit=Unit.RPM)
    
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
