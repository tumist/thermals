import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, GObject, GLib, Gio

from cairo import Matrix
from math import dist
import sys
import os
from itertools import takewhile, dropwhile, count
from thermals.utils import Unit, readlineStrip
from thermals.sensor import Sensor
import subprocess

class Curve(Gtk.DrawingArea):
    darkStyle = GObject.Property(type=bool, default=False)

    drawDots = True
    drawDotsRadius = 8

    drawHandles = True
    drawHandlesCurrent = None

    # These are updated as the DrawingArea changes in self.update_viewport_dimensions
    xw = lambda x: x
    wx = lambda w: w
    yh = lambda y: y
    hy = lambda h: h

    def __init__(self, x_range=(0,100), x_label="X", x_unit=None,
                       y_range=(0,255), y_label="Y", y_unit=None,
                       data=ModuleNotFoundError):
        super().__init__(hexpand=True, vexpand=True)

        self.x_label = x_label
        self.y_label = y_label
        self.x_range = x_range
        self.y_range = y_range
        if data is None:
            self.data = []
        else:
            self.data = data
        self.y_unit = y_unit
        self.x_unit = x_unit

        self.set_draw_func(self.draw, None)

        ctrl = Gtk.EventControllerMotion()
        ctrl.connect('motion', self.on_motion)
        self.add_controller(ctrl)

        drag = Gtk.GestureDrag()
        self.drag = drag
        drag.connect('drag_begin', self.drag_begin)
        self.add_controller(drag)
    
    @property
    def _fg_color(self):
        if self.darkStyle:
            return (0.3, 0.3, 0.3)
        else:
            return (0.8, 0.8, 0.8)
    
    @property
    def _bg_color(self):
        if self.darkStyle:
            return (0.1, 0.12, 0.12)
        else:
            return (0.964, 0.96, 0.913)
    
    def on_motion(self, _, w, h):
        hovering = self.point_at(w, h, self.drawDotsRadius)
        
        # Remove current handles if not hovering over a point
        if hovering is None:
            self.set_tooltip_text(None)
            if self.drawHandlesCurrent is None:
                return
            else:
                self.drawHandlesCurrent = None
                self.queue_draw()
                return
            
        # Draw handles when hovering over a point
        _, hovering = hovering
        if hovering != self.drawHandlesCurrent:
            self.drawHandlesCurrent = hovering
            self.set_tooltip_text("{}{} {}{}".format(hovering[0], self.x_unit, hovering[1], self.y_unit))
            self.queue_draw()

    def drag_begin(self, _, w, h):
        drag_point = self.point_at(w, h, self.drawDotsRadius)
        if drag_point:
            index = drag_point[0]

            def do_update(_, offset_w, offset_h):
                new_w = w + offset_w
                new_h = h + offset_h

                self.adjust_data(index, new_w, new_h)
                self.queue_draw()
            
            def do_end(_, end_x, end_y):
                self.drag.disconnect(update)
                self.drag.disconnect(end)
            
            end = self.drag.connect('drag_end', do_end)
            update = self.drag.connect('drag_update', do_update)
    
    def adjust_data(self, index, new_w, new_h):
        # Clamp values to viewport
        new_w = min(new_w, self.xw(self.x_range[1]))
        new_w = max(new_w, self.xw(self.x_range[0]))

        new_h = max(new_h, self.yh(self.y_range[1]))
        new_h = min(new_h, self.yh(self.y_range[0]))

        # Clamp to previous data point
        try:
            if index < 1:
                raise IndexError
            prev_point = self.data[index - 1]
            new_w = max(new_w, self.xw(prev_point[0]))
            new_h = min(new_h, self.yh(prev_point[1]))
        except IndexError:
            pass

        # Clamp to next data point
        try:
            next_point = self.data[index + 1]
            new_w = min(new_w, self.xw(next_point[0]))
            new_h = max(new_h, self.yh(next_point[1]))
        except IndexError:
            pass

        self.data[index] = (int(round(self.wx(new_w))), int(round(self.hy(new_h))))

    # def point_at_xy(self, x, y, r):
    #     return self.point_at(self.xw(x), self.yh(y), r)
    
    def point_at(self, w, h, r):
        """Return first point found at (w,h) within radius r"""
        for i, point in enumerate(self.data):
            pw = self.xw(point[0])
            ph = self.yh(point[1])

            if dist((pw,ph), (w, h)) <= r:
                return i, point
    
    def update_viewport_dimensions(self, width, height):
        """Creates co-ordinate system translation functions"""
        # w = x * width / self.x_range[1]
        self.xw = lambda x: x * width / self.x_range[1]
        # x = self.x_range[1] * w / width
        self.wx = lambda w: self.x_range[1] * w / width
        # h = height - (y * (height / self.y_range[1]))
        self.yh = lambda y: height - (y * (height / self.y_range[1]))
        # h = height - (y * (height / self.y_range[1]))
        # y * (height / self.y_range[1]) = height - h
        # y = (height - h) / (height / self.y_range[1])
        self.hy = lambda h: (height - h) / (height / self.y_range[1])
    
    def draw_y_lines(self, c, width, height):
        c.select_font_face("Sans")
        c.set_font_size(16)
        y_lines = list(takewhile(lambda v: v <= self.y_range[1], 
                    dropwhile(lambda v: v < self.y_range[0], 
                        count(0, self.y_unit.plot_lines()))))
        while len(y_lines) > 2 and height / len(y_lines) < 40:
            y_lines = y_lines[::2]
        for line in y_lines:
            c.set_source_rgb(*self._fg_color)
            c.set_line_width(1)
            c.set_dash([5, 10], 5)
            c.move_to(0, self.yh(line))
            c.show_text("{} {}".format(line, self.y_unit))
            c.line_to(width, self.yh(line))
            c.stroke()
        c.set_dash([])

    def draw_x_lines(self, c, width, height):
        c.select_font_face("Sans")
        c.set_font_size(16)
        x_lines = list(takewhile(lambda v: v <= self.x_range[1], 
                    dropwhile(lambda v: v < self.x_range[0], 
                        count(0, self.x_unit.plot_lines()))))
        while len(x_lines) > 2 and width / len(x_lines) < 40:
            x_lines = x_lines[::2]
        for line in x_lines:
            c.set_source_rgb(*self._fg_color)
            c.set_line_width(1)
            c.set_dash([5, 10], 5)
            c.move_to(self.xw(line), 0)
            c.line_to(self.xw(line), height)
            c.show_text("{} {}".format(line, self.x_unit))
            
            c.stroke()
        c.set_dash([])

    def draw(self, _, c, width, height, data):
        self.update_viewport_dimensions(width, height)

        c.set_source_rgb(*self._bg_color)
        c.paint()

        c.set_source_rgb(*self._fg_color)

        self.draw_x_lines(c, width, height)
        self.draw_y_lines(c, width, height)

        c.set_line_width(2)
        # Line from beginning (before first point)
        c.move_to(0, self.yh(self.data[0][1]))

        for point in self.data:
            c.line_to(self.xw(point[0]), self.yh(point[1]))
            c.stroke()
            
            if self.drawDots:
                c.arc(self.xw(point[0]), self.yh(point[1]), self.drawDotsRadius, 0, 6.3)
                c.fill()
            
            if self.drawHandles and self.drawHandlesCurrent == point:
                c.arc(self.xw(point[0]), self.yh(point[1]), self.drawDotsRadius * 1.25, 0, 6.3)

            c.move_to(self.xw(point[0]), self.yh(point[1]))

        # Line from last point to end
        c.line_to(self.xw(100), self.yh(self.data[-1][1]))
        c.stroke()


class CurveHwmonWindow(Gtk.ApplicationWindow):
    def __init__(self, sensor, application=None, path=None, title=None):
        super().__init__(application=application, title=title or "Curve")
        self.set_default_size(900, 600)
        self.path = os.path.join(sensor.device.dir, sensor.measurement)
        self.sensor = sensor

        data = self.read_data_points()
        self._original_data = data.copy()
        # While Curve stores `data`, this stores tempSelected index
        self.tempSelected = self.read_temp_selected()
        self._original_temp_selected = None

        self.curve = Curve(data=data, y_unit=Unit.PWM, x_unit=Unit.CELCIUS)
        if application:
            application.get_style_manager()\
                .bind_property('dark', self.curve, 'darkStyle',
                            GObject.BindingFlags.SYNC_CREATE)

        applyBtn = Gtk.Button.new_with_label("Apply")
        applyBtn.connect('clicked', self.write_data_points)

        restoreBtn = Gtk.Button.new_with_label("Restore")
        restoreBtn.connect('clicked', self.restore_original_data)

        tempModel = Gio.ListStore(item_type=Sensor)
        tempFactory = Gtk.SignalListItemFactory()
        tempFactory.connect("setup", lambda _, list_item: list_item.set_child(Gtk.Label()))
        tempFactory.connect("bind", lambda _, list_item: list_item.get_child().set_text(list_item.get_item().name))
        tempSelect = Gtk.DropDown(model=tempModel, factory=tempFactory)
        self.tempSelect = tempSelect
        tempSelect.set_sensitive(False)
        for index, sensor in enumerate(sensor.device.get_sensors()):
            if sensor.measurement.startswith("temp"):
                tempModel.append(sensor)
                if sensor.measurement == "temp{}".format(self.tempSelected):
                    print("Found current temp_sel index {}: {}".format(index, sensor))
                    self._original_temp_selected = index
                    tempSelect.set_sensitive(True)
                    tempSelect.set_selected(index)
        tempSelect.connect("notify::selected-item", self.on_select_temp)

        self.box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
                        #  margin_bottom=10, margin_top=10, margin_start=10, margin_end=10)
        self.box.append(self.curve)

        bottomBox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        bottomBox.append(Gtk.Label(label="Monitor temperature:"))
        bottomBox.append(tempSelect)
        bottomBox.append(restoreBtn)
        bottomBox.append(applyBtn)

        self.box.append(bottomBox)
        self.set_child(self.box)
        self.curve.queue_draw()
    
    def read_data_points(self):
        path = self.path or sys.argv[1]
        data = []
        for i in range(1,6):
            temp = readlineStrip("{}_auto_point{}_temp".format(path, i))
            pwm = readlineStrip("{}_auto_point{}_pwm".format(path, i))
            data.append((int(temp) // 1000, int(pwm)))
        return data
    
    def write_data_points(self, *args, **kw):
        path = self.path or sys.argv[1]
        data = self.curve.data
        commands = []
        for i in range(0,5):
            temp = "echo {:0.0f}000 > {}_auto_point{}_temp".format(data[i][0], path, i+1)
            pwm = "echo {:0.0f} > {}_auto_point{}_pwm".format(data[i][1], path, i+1)
            print(temp)
            commands.append(temp)
            print(pwm)
            commands.append(pwm)
        if self.tempSelected != None:
            commands.append("echo {} > {}_temp_sel".format(self.tempSelected, path))
        script = " && ".join(commands)
        print(script)
        print(subprocess.run(["pkexec", "sh", "-c", script]))
    
    def read_temp_selected(self):
        try:
            return int(readlineStrip(self.path + "_temp_sel"))
        except:
            return None

    def restore_original_data(self, *args):
        if not self._original_data:
            return
        self.curve.data = self._original_data.copy()
        self.curve.queue_draw()
        if self._original_temp_selected:
            self.tempSelect.set_selected(self._original_temp_selected)
    
    def on_select_temp(self, dropdown, _):
        item = dropdown.get_selected_item()
        print("tempSel dropdown selected {}".format(dropdown.get_selected_item().measurement))
        index = int(item.measurement[4:])
        self.tempSelected = index


# For stand-alone runs
# 
class CurveApp(Adw.Application):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.win = None
        self.connect('activate', self.on_activate)
        if len(sys.argv) == 2:
            self.windowCls = CurveHwmonWindow
        else:
            self.windowCls = CurveWindow

    def on_activate(self, app):
        if not self.win:
            self.win = self.windowCls(application=app)
        self.win.present()

class CurveWindow(Gtk.ApplicationWindow):
    def __init__(self, application=None):
        super().__init__(application=application, title="Curve")
        self.set_default_size(900, 600)
        self.curve = Curve(data=[(10,10), (30, 20), (50, 60), (80, 230)], y_unit=Unit.PWM, x_unit=Unit.CELCIUS)
        self.box = Gtk.Box()
        self.box.append(self.curve)
        self.set_child(self.box)
        self.curve.queue_draw()


if __name__ == "__main__":
    CurveApp().run(None)