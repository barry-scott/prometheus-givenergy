# prometheus-givenergy
prometheus exporter for GivEnergy inverter metrics

prometheus-givenergy is inspired by givenergy-modbus module.
givenergy-modbus does not work with current version of pymodbus.

```
Usage: prometheus_givenergy <host> [--port=<port>] [--prom-file=<prom-file> [--version]
    <host> ip-address or hostname
    <port> default 8899
    <prom-file> default /var/lib/prometheus/node-exporter/givenergy.prom
```
