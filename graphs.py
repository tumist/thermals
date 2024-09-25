from collections import deque, defaultdict
from itertools import islice, takewhile, dropwhile, count, batched

from gi.repository import Gtk, GObject

from utils import Unit, monotonic_s
from time import monotonic_ns

class Graphs(Gtk.Box):
    timeSelections = [
        ("1 min", 60),
        ("5 mins", 60 * 5),
        ("15 mins", 60 * 15),
        ("30 mins", 60 * 30),
        ("1 hour", 60 * 60),
        ("3 hours", 60 * 60 * 3)
    ]
    graphSeconds = GObject.Property(type=int, default=timeSelections[0][1])
    drawDark = GObject.Property(type=bool, default=False)
    history = defaultdict(lambda: deque([], 60 * 60 * 2))

    def __init__(self, config, sensors):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.sensors = sensors

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
        self.historize_sensors()
        self.celcius.queue_draw()
        self.rpm.queue_draw()
    
    def historize_sensors(self):
        for sensor in self.sensors.get_sensors():
            self.history[sensor].append((sensor.time, sensor.value))

# history helpers
def values(seq):
    for dq in seq:
        for (t,v) in dq:
            yield v

class GraphCanvas(Gtk.DrawingArea):
    drawDark = GObject.Property(type=bool, default=False)
    graphSeconds = GObject.Property(type=int)
    pointer = (None, None, None)

    def __init__(self, unit, sensors):
        super().__init__(hexpand=True, vexpand=True)
        self.unit = unit
        self.sensors = sensors

        ctrl = Gtk.EventControllerMotion()
        ctrl.connect('motion', self.on_motion)
        self.add_controller(ctrl)

        self.set_draw_func(self.draw, None)

    def draw(self, area, c, w, h, data):
        ns0 = monotonic_ns()

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
            print("GraphCanvas {} has no sensors to draw".format(self.unit))
            return

        t_min = monotonic_s() - self.graphSeconds
        t_max = monotonic_s()
        
        if self.unit == Unit.RPM:
            v_min = 0
        else:
            v_min = min(values(
                [dropwhile(lambda h: h[0] < t_min, self.history[s]) for s in sensors]
                ))
        v_max = max(values(
            [dropwhile(lambda h: h[0] < t_min, self.history[s]) for s in sensors]
            ))

        # Add 5% on max and min
        v_min -= (v_max-v_min)*0.05
        v_max += (v_max-v_min)*0.05

        ns1 = monotonic_ns()

        if v_min == v_max:
            v_max += 1

        self.t_min = t_min
        self.t_max = t_max
        self.v_min = v_min
        self.v_max = v_max

        # Time -> x coord
        def translate_x(time: float) -> float:
            return w * ((time - t_min) / (t_max - t_min))
        
        # Sensor value -> y coord
        def translate_y(value: float) -> float:
            return h * (1 - ((value - v_min) / (v_max - v_min)))

        # Draw background lines
        c.select_font_face("Sans")
        c.set_font_size(16)
        y_lines = list(takewhile(lambda v: v <= v_max, 
                    dropwhile(lambda v: v < v_min, 
                        count(0, self.unit.graph_lines()))))
        while y_lines and h / len(y_lines) < 40:
            y_lines = y_lines[::2]
        for line in y_lines:
            c.set_source_rgb(*fg_color)
            c.set_line_width(1)
            c.set_dash([5, 10], 5)
            c.move_to(0, translate_y(line))
            c.show_text("{} {}".format(line, self.unit))
            c.line_to(w, translate_y(line))
            c.stroke()
        c.set_dash([])

        ns2 = monotonic_ns()

        # Draw sensors
        c.set_line_width(2)
        for sensor in sensors:
            #hiter = dropwhile(lambda h: h[0] < t_min, self.history[sensor])
            hiter = takewhile(lambda h: h[0] > t_min, reversed(self.history[sensor]))

            c.set_source_rgb(*sensor.RGB_triple())
            t0, v0 = next(hiter)
            
            c.move_to(translate_x(t0), translate_y(v0))
            for (t, v) in hiter:
                c.line_to(translate_x(t), translate_y(v))
            c.stroke()
        
        ns3 = monotonic_ns()
        print("Graph {} draw took {:1.1f}ms + {:1.1f}ms + {:1.1f}ms = {:1.1f}ms to draw"\
            .format(self.unit, (ns1-ns0)/1000000, (ns2-ns1)/1000000,(ns3-ns2)/1000000,
                               (ns3-ns0)/1000000))
        
    def on_motion(self, ctrl, x, y):
        ns0 = monotonic_ns()
        h = self.get_height()
        w = self.get_width()

        v = self.v_max - ((y/h) * (self.v_max - self.v_min))
        t = self.t_min + ((x/w) * (self.t_max - self.t_min))

        # print(f"motion t:{t} v:{v}")
        # return

        line_distances = []
        for sensor in self.sensors.get_sensors(graph=True, unit=self.unit.value):
            hiter = dropwhile(lambda h: h[0] < t, self.history[sensor])
            try:
                (st, sv) = next(hiter)
                #print(sensor, st, sv)
                line_distances.append((abs(v-sv), sensor, st, sv))
            except StopIteration:
                pass
        if not line_distances:
            return
        distance, sensor, time, value = sorted(line_distances, key=lambda a: a[0])[0]
        self.set_tooltip_text("{} {}{}".format(sensor.name, value, Unit(sensor.unit)))
        self.pointer = time, sensor, value
        ns1 = monotonic_ns()
        print("Motion calc took {:1.1}ms".format((ns1-ns0)/1000000))




