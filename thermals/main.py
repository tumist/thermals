import sys
import os, os.path
from time import monotonic_ns

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, GObject, GLib
import configparser

from thermals.plots import Plots
from thermals.hwmon import Hwmon
from thermals.utils import time_it

HWMON_READ_INTERVAL = 2000

class Config(configparser.ConfigParser):
    def __init__(self, *args, **kw):
        super().__init__(*args, **kw)
        os.makedirs(os.path.dirname(self.filepath()), exist_ok=True)
    def filepath(self):
        return os.path.join(GLib.get_user_config_dir(), "thermals", "thermals.ini")
    def read(self):
        super().read(self.filepath())
    def write(self):
        with open(self.filepath(), 'w') as configfile:
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
    @time_it("Initialize MainWindow")
    def __init__(self, application=None):
        super().__init__(application=application, title="Thermals")
        self.app = application

        self.config = Config()
        self.config.read()
        self.config['DEFAULT']['expanded'] = 'True'
        self.config['DEFAULT']['color'] = "rgb(127, 127, 127)"
        self.config['DEFAULT']['plot'] = 'True'
        # Makes sure the config is written when MainWindow is closed
        self.connect('close-request', lambda *args: self.config.write())

        # Restore window size
        try:
            width = self.config.getint('window', 'width')
            height = self.config.getint('window', 'height')
        except configparser.NoSectionError:
            width = 900
            height = 600
        self.set_default_size(width, height)
        # Save window size
        self.connect("notify::default-width", self.on_notify_default_size)
        self.connect("notify::default-height", self.on_notify_default_size)

        self.hwmon = Hwmon(self, self.config)
        if not self.hwmon.devices:
            self.show_hwmon_error_message()
            return
        self.plots = Plots(self, self.config, self.hwmon)

        self.plots.create_plots()
        
        self.app.get_style_manager()\
            .bind_property('dark', self.plots, 'darkStyle',
                           GObject.BindingFlags.SYNC_CREATE)
        
        hpane = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        hpane.set_start_child(Gtk.ScrolledWindow(
            child=self.hwmon, hscrollbar_policy=Gtk.PolicyType.NEVER))

        # hpane.append(self.plots)
        hpane.set_end_child(self.plots)
        hpane.set_shrink_start_child(False)
        self.set_child(hpane)

        # kickoff sensor update timer
        self.on_timer()
    
    def show_hwmon_error_message(self):
        cbox = Gtk.CenterBox()
        msg = Gtk.Label()
        msg.set_markup("Thermals could not find any hwmon devices under /sys/class/hwmon/")
        cbox.set_center_widget(msg)
        self.set_child(cbox)
    
    def on_notify_default_size(self, *args):
        w, h = self.get_default_size()
        self.config['window']['width'] = str(w)
        self.config['window']['height'] = str(h)

    def on_timer(self):
        GLib.timeout_add(HWMON_READ_INTERVAL, self.on_timer)
        self.hwmon.refresh()
        self.plots.refresh()
    
    def select_sensor(self, sensor):
        self.hwmon.select_sensor(sensor)

class MyApp(Adw.Application):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.win = None
        self.connect('activate', self.on_activate)

    def on_activate(self, app):
        if not self.win:
            self.win = MainWindow(application=app)
        self.win.present()

def main():
    app = MyApp(application_id="is.tum.Thermals")
    exit_status = app.run(None)
    sys.exit(exit_status)
