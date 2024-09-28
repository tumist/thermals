import sys
from time import monotonic_ns

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, GObject, GLib
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
        if not self.has_section(section) and \
           not section == "DEFAULT":
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

        self.hwmon = Hwmon(self.config)
        self.graph = Graphs(self.config, self.hwmon)

        self.graph.create_graphs()
        
        self.app.get_style_manager()\
            .bind_property('dark', self.graph, 'drawDark',
                           GObject.BindingFlags.SYNC_CREATE)
        
        box = Gtk.Box()
        box.append(self.graph)
        box.append(Gtk.ScrolledWindow(
            child=self.hwmon, hscrollbar_policy=Gtk.PolicyType.NEVER))
        self.set_child(box)
        self.set_default_size(900, 400)
        self.on_timer()

        #GLib.timeout_add(10000, self.on_foo)

    def on_timer(self):
        GLib.timeout_add(2000, self.on_timer)
        t0 = monotonic_ns()
        self.hwmon.refresh()
        t1 = monotonic_ns()
        self.graph.refresh()
        print("Sensor refresh took {:1.1f}ms".format((t1-t0)/1000000))
    
    def on_foo(self):
        print("Clearing graphs")
        self.graph.clear_graphs()
        #self.graph.create_graphs()


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
