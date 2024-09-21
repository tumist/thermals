import sys
from time import monotonic_ns

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, GObject, Gio, GLib, Gdk
import configparser

from graphs import Graphs
from hwmon import Hwmon

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
