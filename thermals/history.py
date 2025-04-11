from collections import defaultdict, deque

from thermals.utils import time_it

class History(defaultdict):
    def __init__(self, app):
        super().__init__(lambda: deque([], 60 * 60 * 3))
        self.app = app
    
    @time_it("historize_sensors")
    def historize_sensors(self):
        for sensor in self.app.hwmon.get_sensors():
            self[sensor].append((sensor.time, sensor.value))