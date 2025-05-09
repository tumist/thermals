from itertools import takewhile, dropwhile, count, groupby

from gi.repository import Gtk, GObject

from thermals.utils import Unit, monotonic_s, time_it
from time import monotonic_ns
from thermals.sensor import Sensor

class Plots(Gtk.Box):
    timeSelections = [
        ("3 mins", 60 * 3),
        ("10 mins", 60 * 10),
        ("30 mins", 60 * 30),
        ("1 hour", 60 * 60),
        ("3 hours", 60 * 60 * 3),
        ("10 hours", 60 * 60 * 10)
    ]
    plotSeconds = GObject.Property(type=int, default=timeSelections[0][1])
    darkStyle = GObject.Property(type=bool, default=False)

    def __init__(self, app):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.app = app
        self.canvases = [] # populated with `self.create_plots`
        
        self.paned = MultiPaned(app.config['plot_pane'])

        timeSelector = Gtk.DropDown.new_from_strings([s for (s, _) in self.timeSelections])
        timeSelector.connect("notify::selected", self.on_time_selected)

        clearMinMax = Gtk.Button.new_with_label("Clear Min/Max")
        clearMinMax.connect('clicked', self.on_clear_min_max)

        self.append(self.paned)
        bottomBox = Gtk.Box(spacing=10)
        bottomBox.append(Gtk.Label(label="History:"))
        bottomBox.append(timeSelector)
        bottomBox.append(clearMinMax)
        self.append(bottomBox)
    
    def pxPerMeasurement(self):
        if not self.canvases:
            return
        pxPerMs = self.get_width() / (self.plotSeconds / self.canvases[0].history_resolution)
        print("{} pixels/measurement".format(round(pxPerMs, 1)))
        return pxPerMs
    
    def on_notify_default_size(self, *args):
        self.pxPerMeasurement()
    
    def clear_plots(self):
        self.remove(self.paned)
        self.paned = MultiPaned(self.app.config['plot_pane'])
        self.prepend(self.paned)
        self.canvases = []
    
    def create_plots(self):
        if hasattr(self, 'canvases') and self.canvases:
            print("WARNING: canvases is not empty")
        self.canvases = []
        plot_sensors = sorted(self.app.hwmon.get_sensors(plot=True), key=lambda s: s.unit)
        for unit, _ in groupby(plot_sensors, key=lambda s: s.unit):
            canvas = PlotCanvas(Unit(unit), self.app.hwmon, self.app)
            canvas.history = self.app.history
            canvas.app = self.app
            self.bind_property('plotSeconds', canvas, 'plotSeconds', GObject.BindingFlags.SYNC_CREATE)
            self.bind_property('darkStyle', canvas, 'darkStyle', GObject.BindingFlags.SYNC_CREATE)
            self.canvases.append(canvas)
            self.paned.append(canvas)

    def on_time_selected(self, dropdown, _):
        selected = dropdown.get_property("selected")
        self.plotSeconds = self.timeSelections[selected][1]
        for canvas in self.canvases:
            canvas.clear_min_max()
            canvas.do_draw()
        self._history_resolution = None # Will recalculate
    
    @time_it("Plots refresh")
    def refresh(self):
        for canvas in self.canvases:
            canvas.do_draw()

    def recreate_plots(self):
        self.clear_plots()
        self.create_plots()
    
    def on_clear_min_max(self, *args):
        for canvas in self.canvases:
            canvas.clear_min_max()
            canvas.scan_min_max(monotonic_s() - canvas.plotSeconds)
            canvas.do_draw()

class MultiPaned(Gtk.Paned):
    """
    A GTK4 Paned can only hold two widgets.
    This class organizes Paned-within-Paned recursively allowing for
    more widgets to be packed.
    It also remembers the Paneds position (in absolute pixel vales)
    """
    def __init__(self, config, widget=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, wide_handle=True, hexpand=True,
                         shrink_start_child=False, shrink_end_child=False)
        self.config = config

        self.connect("notify::position", self.on_position_changed)

        if widget is not None:
            self.set_start_child(widget)
            self.set_config_position()
    
    def append(self, widget):
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
            self.config[child.unit.name] = str(position)
    
    def set_config_position(self):
        widget = self.get_start_child()
        if widget is None:
            return
        pos = self.config.get(widget.unit.name, 100)
        self.set_position(int(pos))

# history helpers
def values(seq):
    for dq in seq:
        for b in dq:
            yield b.value

class PlotCanvas(Gtk.Box):
    darkStyle = GObject.Property(type=bool, default=False)
    plotSeconds = GObject.Property(type=int)
    _history_resolution = 1
    
    #_pointer = (None, None, None)

    # These are the mins and max of values in this plot, updated by
    # `draw` or `scan_min_max`.
    # However, although the values are historized on every timer and
    # a redraw is queued, it is not necessarily drawn and therefor not
    # guaranteed to be updated by `draw`. That's why there still is a
    # "Clear Min/Max" button on the interface, which rescans the history.
    _value_min = None
    _value_max = None
    # Margin added to the minimum and maximum so the line
    # isn't drawn right on the edge.
    _viewport_margin = 0.025

    _time_min = None
    _time_max = None

    def __init__(self, unit, hwmon, app):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.unit = unit
        self.hwmon = hwmon
        self.app = app

        self.title = Gtk.Label()
        self.format_title()
        self.canvas = Gtk.DrawingArea(hexpand=True, vexpand=True)

        ctrl = Gtk.EventControllerMotion()
        ctrl.connect('motion', self.on_motion)
        self.canvas.add_controller(ctrl)

        gesture = Gtk.GestureClick()
        gesture.connect('released', self.on_click_released)
        self.canvas.add_controller(gesture)

        self.canvas.set_draw_func(self.draw, None)

        self.append(self.title)
        self.append(self.canvas)
    
    def format_title(self):
        if self._value_min is None or self._value_max is None:
            self.title.set_markup("<b>{}</b>".format(self.unit.title()))
        else:
            self.title.set_markup("<b>{}</b>  Min: {} {} Max: {} {}".format(
                self.unit.title(), self._value_min, str(self.unit),
                self._value_max, str(self.unit)))
    
    def do_draw(self):
        self._history_resolution = None
        self.canvas.queue_draw()
    
    def sensors(self) -> list[Sensor]:
        return list(self.hwmon.get_sensors(plot=True, unit=self.unit.value))
    
    @property
    def history_resolution(self):
        if self._history_resolution is not None:
            return self._history_resolution
        else:
            for res in self.history.resolutions:
                pxPerMs = self.get_width() / (self.plotSeconds / res)
                if pxPerMs < 1.5:
                    continue
                #print("History resolution selected: {} {}px/ms".format(res, pxPerMs))
                self._history_resolution = res
                return res
            self._history_resolution = self.history.resolutions[-1]
            return self._history_resolution
            
    def data(self, sensor):
        return self.history.sensors[sensor][self.history_resolution]

    def draw(self, area, c, w, h, data):
        if self.darkStyle:
            bg_color = (0.1, 0.12, 0.12)
            fg_color = (0.3, 0.3, 0.3)
        else:
            bg_color = (0.964, 0.96, 0.913)
            fg_color = (0.8, 0.8, 0.8)
        # Fill background with a colour
        c.set_source_rgb(*bg_color)
        c.paint()

        # time window that we are plotting
        t_min = monotonic_s() - self.plotSeconds
        t_max = monotonic_s()
        self._time_min = t_min
        self._time_max = t_max

        # The value range that we are plotting. Then add _
        if self._value_min is None or self._value_max is None:
            self.scan_min_max(t_min)
        v_min = self._value_min - (self._value_max - self._value_min) * self._viewport_margin
        v_max = self._value_max + (self._value_max - self._value_min) * self._viewport_margin

        # Time -> Canvas x coord
        def translate_x(time: float) -> float:
            return w * ((time - t_min) / (t_max - t_min))
        
        # Sensor value -> Canvas y coord
        def translate_y(value: float) -> float:
            return h * (1 - ((value - v_min) / (v_max - v_min)))
        
        # Draw background lines
        c.select_font_face("Sans")
        c.set_font_size(16)
        y_lines = list(takewhile(lambda v: v <= v_max, 
                    dropwhile(lambda v: v < v_min, 
                        count(0, self.unit.plot_lines()))))
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

        # Draw sensors
        c.set_line_width(2)
        lines_drawn = 0
        for sensor in self.sensors():
            hiter = takewhile(lambda h: h.time > t_min, reversed(self.data(sensor)))
            
            c.set_source_rgb(*sensor.RGB_triple())
            try:
                b = next(hiter)
                v0 = b.value
                t0 = b.time
            except StopIteration:
                continue

            if v0 < self._value_min:
                self._value_min = v0
            if v0 > self._value_max:
                self._value_max = v0
        
            c.move_to(translate_x(t0), translate_y(v0))
            for b in hiter:
                t = b.time
                v = b.value
                c.line_to(translate_x(t), translate_y(v))
                lines_drawn += 1
            c.stroke()
        self.format_title()
    
    def clear_min_max(self):
        self._value_min = None
        self._value_max = None
        self.format_title()

    def scan_min_max(self, t_min):
        sensors = self.sensors()
        if self.unit == Unit.RPM:
            self._value_min = 0
        else:
            self._value_min = min(values(
                [takewhile(lambda h: h.time >= t_min, reversed(self.data(s))) for s in sensors]
                ))
        self._value_max = max(values(
            [takewhile(lambda h: h.time >= t_min, reversed(self.data(s))) for s in sensors]
            ))
        if self._value_min >= self._value_max:
            # Add some space when there is no/one value
            # TODO: May be better to add some margin to plot lines instead
            self._value_max = self._value_min + 1
    
    @time_it("Coord to Sensor value")
    def get_info_at_coord(self, x, y):
        h = self.canvas.get_height()
        w = self.canvas.get_width()

        v_min = self._value_min - (self._value_max-self._value_min) * self._viewport_margin
        v_max = self._value_max + (self._value_max-self._value_min) * self._viewport_margin

        v = v_max - ((y/h) * (v_max - v_min))
        t = self._time_min + ((x/w) * (self._time_max - self._time_min))

        line_distances = []
        for sensor in self.sensors():
            hiter = dropwhile(lambda h: h.time < t, self.data(sensor))
            try:
                b = next(hiter)
                st = b.time
                sv = b.value
                if abs(st-t) > 10:
                    continue
                line_distances.append((abs(v-sv), sensor, st, sv))
            except StopIteration:
                pass
        if not line_distances:
            return (None, None, None)
        (distance, sensor, time, value) = sorted(line_distances, key=lambda a: a[0])[0]
        return sensor, time, value
        
    def on_motion(self, ctrl, x, y):
        (sensor, time, value) = self.get_info_at_coord(x, y)
        if sensor:
            self.set_tooltip_text("{} {}{}".format(sensor.name, value, Unit(sensor.unit)))
            self._pointer = (time, sensor, value)
        else:
            self.set_tooltip_text(None)

    def on_click_released(self, gesture, n_press, x, y):
        if n_press != 1:
            # `n_press` is "number of presses with this release" which will increase
            # for each press, so we ignore subsequent presses here
            return
        (sensor, time, value) = self.get_info_at_coord(x, y)
        if sensor:
            self.app.select_sensor(sensor)