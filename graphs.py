from collections import deque, defaultdict
from itertools import islice, takewhile, dropwhile, count, batched

from gi.repository import Gtk, GObject

from utils import Unit

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
            c.set_dash([5, 10], 5)
            c.move_to(0, translate_y(line))
            c.show_text("{} {}".format(line, self.unit))
            c.line_to(w, translate_y(line))
            c.stroke()

        # Draw sensors
        c.set_dash([])
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