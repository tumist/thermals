from collections import defaultdict, deque

from thermals.utils import time_it
from thermals.sensor import Sensor

class Measurement:
    time = None
    value = None
    sensor = None
    count = 1

    def create(sensor: Sensor):
        ms = Measurement()
        ms.time = sensor.time
        ms.value = sensor.value
        ms.sensor = sensor
        return ms
    
    def avg(self, value):
        self.value = (self.value * self.count) + value
        self.count += 1
        self.value /= self.count
        return self

    def __add__(self, other):
        return self.avg(other.value)

class History:
    resolutions = [1, 3, 10, 30]

    def __init__(self, app):
        self.app = app
        self.sensors = defaultdict(
            lambda: {res: deque([], 1024 * 2) for res in self.resolutions}
        )
    
    @time_it("historize_sensors")
    def historize_sensors(self):
        for sensor in self.app.hwmon.get_sensors():
            if sensor.value is None:
                continue
            for res in self.resolutions:
                measurement = Measurement.create(sensor)
                dq = self.sensors[sensor][res]
                # First and second measurements are always added.
                # For lower resolutions, we replace the tail but need the measurement
                # before the tail for time comparison
                if len(dq) in (0, 1):
                    dq.append(measurement)
                else:
                    if measurement.time - dq[-2].time <= res:
                        dq[-1] += measurement
                    else:
                        dq.append(measurement)
