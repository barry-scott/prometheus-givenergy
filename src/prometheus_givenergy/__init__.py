#
#   prometheus_givenergy
#
import sys
import os
from datetime import datetime


VERSION = '1.0.0'

# default port on GivEnergy inverter
DEFAULT_PORT = 8899
# Use the default for node exporter on Fedora
DEFAULT_PROM_FILE = '/var/lib/prometheus/node-exporter/givenergy.prom'

class PrometheusGivEnergy:
    def __init__(self, host, port=DEFAULT_PORT, prom_file=DEFAULT_PROM_FILE, debug=False):
        self.host = host
        self.port = port
        self.prom_file = prom_file
        self._debug = debug

        self.metrics = {}

        self.debug(f'PrometheusGivEnergy: host={host} port={port}')

    def debug(self, msg):
        if self._debug:
            print(f'Debug: {msg}', file=sys.stderr)

    def report(self):
        tmp_prom_file = self.prom_file + '.tmp'
        try:
            with open(tmp_prom_file, 'w') as f:
                self.fetchMetrics()
                self.printMetrics(f)

            os.rename(tmp_prom_file, self.prom_file)

        except IOError as e:
            print(f'prometheus_givenergy {e!s}')

    def fetchMetrics(self):
        pass

    def printMetrics(self, f):
        print(f'# prometheus_givenergy report {datetime.now()}', file=f)
