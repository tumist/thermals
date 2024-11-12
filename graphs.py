from collections import deque, defaultdict
from itertools import islice, takewhile, dropwhile, count, batched, groupby

from gi.repository import Gtk, GObject

from utils import Unit, monotonic_s
from time import monotonic_ns
from hwmon import Sensor

class Graphs(Gtk.Box):
    timeSelections = [
        ("3 mins", 60 * 3),
        ("10 mins", 60 * 10),
        ("30 mins", 60 * 30),
        ("1 hour", 60 * 60),
        ("3 hours", 60 * 60 * 3),
    ]
    graphSeconds = GObject.Property(type=int, default=timeSelections[0][1])
    drawDark = GObject.Property(type=bool, default=False)
    history = defaultdict(lambda: deque([], 60 * 60 * 3))

    def __init__(self, config, hwmon):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.config = config
        self.hwmon = hwmon
        
        self.paned = MultiPaned(config['graph_pane'])

        timeselector = Gtk.DropDown.new_from_strings(
            [s for (s, _) in self.timeSelections]
        )
        timeselector.connect("notify::selected", self.on_time_selected)

        rescanMinMax = Gtk.Button.new_with_label("Rescan min/max")
        rescanMinMax.connect('clicked', self.on_rescan_min_max)

        self.append(self.paned)
        bottomBox = Gtk.Box(homogeneous=True)
        bottomBox.append(timeselector)
        bottomBox.append(rescanMinMax)
        self.append(bottomBox)
    
    def clear_graphs(self):
        self.remove(self.paned)
        self.paned = MultiPaned(self.config['graph_pane'])
        self.prepend(self.paned)
        self.canvases = []
    
    def create_graphs(self):
        if hasattr(self, 'canvases') and self.canvases:
            print("WARNING: canvases is not empty")
        self.canvases = []
        graph_sensors = sorted(self.hwmon.get_sensors(graph=True), key=lambda s: s.unit)
        for unit, sensors in groupby(graph_sensors, key=lambda s: s.unit):
            print("Creating canvas for {}".format(Unit(unit)))
            canvas = GraphCanvas(Unit(unit), self.hwmon)
            canvas.history = self.history
            canvas.app = self.app
            self.bind_property('graphSeconds', canvas, 'graphSeconds', GObject.BindingFlags.SYNC_CREATE)
            self.bind_property('drawDark', canvas, 'drawDark', GObject.BindingFlags.SYNC_CREATE)
            self.canvases.append(canvas)
            self.paned.append(canvas)

    def on_time_selected(self, dropdown, _):
        selected = dropdown.get_property("selected")
        self.graphSeconds = self.timeSelections[selected][1]
        for canvas in self.canvases:
            canvas.queue_draw()
    
    def refresh(self):
        self.historize_sensors()
        for canvas in self.canvases:
            canvas.queue_draw()
    
    def historize_sensors(self):
        for sensor in self.hwmon.get_sensors():
            self.history[sensor].append((sensor.time, sensor.value))
    
    def on_graph_change(self, *args):
        print("graph changed", *args)
    
    def on_rescan_min_max(self, *args):
        for canvas in self.canvases:
            canvas.scan_min_max(monotonic_s() - canvas.graphSeconds)

class MultiPaned(Gtk.Paned):
    def __init__(self, config, widget=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, wide_handle=True, hexpand=True)
        self.config = config

        self.connect("notify::position", self.on_position_changed)

        if widget is not None:
            self.set_start_child(widget)
            print("Initializing MultiPaned with widget {}".format(widget.unit.name))
            self.set_config_position()
    
    def append(self, widget):
        print("MultiPaned appending {}".format(widget.unit))
        if self.get_start_child() is None:
            self.set_start_child(widget)
            self.set_config_position()
        elif self.get_end_child() is None:
            self.set_end_child(MultiPaned(self.config, widget))
        else:
            self.get_end_child().append(widget)
    
    def on_position_changed(self, *args):
        child = self.get_start_child()
        position = self.get_position()
        if child:
            print("MultiPaned {} position changed {}".format(child.unit.name, position))
            self.config[child.unit.name] = str(position)
            self.config.write()
    
    def set_config_position(self):
        widget = self.get_start_child()
        if widget is None:
            return
        pos = self.config.get(widget.unit.name, 100)
        self.set_position(int(pos))

# history helpers
def values(seq):
    for dq in seq:
        for (t,v) in dq:
            yield v

class GraphCanvas(Gtk.DrawingArea):
    drawDark = GObject.Property(type=bool, default=False)
    graphSeconds = GObject.Property(type=int)
    pointer = (None, None, None)
    app = None

    v_min = None
    v_max = None

    def __init__(self, unit, hwmon):
        super().__init__(hexpand=True, vexpand=True)
        self.unit = unit
        self.hwmon = hwmon

        ctrl = Gtk.EventControllerMotion()
        ctrl.connect('motion', self.on_motion)
        self.add_controller(ctrl)

        gesture = Gtk.GestureClick()
        gesture.connect('released', self.on_click_released)
        self.add_controller(gesture)

        self.set_draw_func(self.draw, None)
    
    def sensors(self) -> list[Sensor]:
        return list(self.hwmon.get_sensors(graph=True, unit=self.unit.value))

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

        # time window that we are graphing
        t_min = monotonic_s() - self.graphSeconds
        t_max = monotonic_s()
        
        if self.v_min is None or self.v_max is None:
            self.scan_min_max(t_min)
        v_min = self.v_min
        v_max = self.v_max

        # Add 5% on max and min
        v_min -= (v_max-v_min)*0.05
        v_max += (v_max-v_min)*0.05

        self.t_min = t_min
        self.t_max = t_max

        # Time -> Canvas x coord
        def translate_x(time: float) -> float:
            return w * ((time - t_min) / (t_max - t_min))
        
        # Sensor value -> Canvas y coord
        def translate_y(value: float) -> float:
            return h * (1 - ((value - v_min) / (v_max - v_min)))
        
        ns1 = monotonic_ns() # time setup

        # Draw background lines
        c.select_font_face("Sans")
        c.set_font_size(16)
        y_lines = list(takewhile(lambda v: v <= v_max, 
                    dropwhile(lambda v: v < v_min, 
                        count(0, self.unit.graph_lines()))))
        while len(y_lines) > 2 and h / len(y_lines) < 40:
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

        ns2 = monotonic_ns() # time background lines

        # Draw sensors
        c.set_line_width(2)
        lines_drawn = 0
        for sensor in self.sensors():
            #hiter = dropwhile(lambda h: h[0] < t_min, self.history[sensor])
            hiter = takewhile(lambda h: h[0] > t_min, reversed(self.history[sensor]))
            
            c.set_source_rgb(*sensor.RGB_triple())
            t0, v0 = next(hiter)

            if v0 < self.v_min:
                self.v_min = v0
            elif v0 > self.v_max:
                self.v_max = v0
        
            c.move_to(translate_x(t0), translate_y(v0))
            for (t, v) in hiter:
                c.line_to(translate_x(t), translate_y(v))
                lines_drawn += 1
            c.stroke()
        
        ns3 = monotonic_ns() # time graph lines

        print("Graph {} draw took {:1.2f}ms + {:1.2f}ms + {:1.2f}ms = {:1.2f}ms to draw ({} graph lines)"\
            .format(self.unit, (ns1-ns0)/1000000, (ns2-ns1)/1000000,(ns3-ns2)/1000000,
                               (ns3-ns0)/1000000, lines_drawn))
    
    def scan_min_max(self, t_min):
        sensors = self.sensors()
        if self.unit == Unit.RPM:
            self.v_min = 0
        else:
            self.v_min = min(values(
                [takewhile(lambda h: h[0] > t_min, reversed(self.history[s])) for s in sensors]
                ))
        self.v_max = max(values(
            [takewhile(lambda h: h[0] > t_min, reversed(self.history[s])) for s in sensors]
            ))
        if self.v_min >= self.v_max:
            # Add some space when there is no/one value
            # TODO: May be better to add some margin to graph lines instead
            self.v_max = self.v_min + 1
    
    def get_info_at_coord(self, x, y):
        ns0 = monotonic_ns()
        h = self.get_height()
        w = self.get_width()

        v = self.v_max - ((y/h) * (self.v_max - self.v_min))
        t = self.t_min + ((x/w) * (self.t_max - self.t_min))

        line_distances = []
        for sensor in self.sensors():
            hiter = dropwhile(lambda h: h[0] < t, self.history[sensor])
            try:
                (st, sv) = next(hiter)
                if abs(st-t) > 10:
                    continue
                line_distances.append((abs(v-sv), sensor, st, sv))
            except StopIteration:
                pass
        if not line_distances:
            return
        distance, sensor, time, value = sorted(line_distances, key=lambda a: a[0])[0]
        ns1 = monotonic_ns()
        #print("Motion calc took {:1.1}ms".format((ns1-ns0)/1000000))
        return sensor, time, value
        
    def on_motion(self, ctrl, x, y):
        info = self.get_info_at_coord(x, y)
        if info:
            sensor, time, value = info
            self.set_tooltip_text("{} {}{}".format(sensor.name, value, Unit(sensor.unit)))
            self.pointer = time, sensor, value
        else:
            self.set_tooltip_text(None)

    def on_click_released(self, gesture, click_n, x, y):
        print("Clicked {}".format(click_n, x, y))

        info = self.get_info_at_coord(x, y)
        if info and click_n == 1:
            sensor, time, value = info
            self.app.select_sensor(sensor)