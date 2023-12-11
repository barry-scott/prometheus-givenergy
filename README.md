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

All holding metrics are prefixed with `givenergy_holding_`.
And all input metrics are prefixed with `givenergy_`.
The unit type of the metric is used to add a suffix.

| Unit | Suffix | Example |
|:-----|:-------|:--------|
| Scaler value | no suffix | givenergy_battery_num_cycles |
| kilo Watt Hours | _kwh | givenergy_grid_in_total_kwh |
| Watts | _w | givenergy_load_demand_w |
| VA | _va | givenergy_grid_apparent_va |
| Voltage | _volts | givenergy_holding_ac_high_in_volts |
| Current | _amps | givenergy_grid_port_amps |
| Amp Hours | _ah | givenergy_holding_battery_nominal_capacity_ah |
| Temperature C | _temp_c | givenergy_battery_temp_c |
| Frequency Hz | _hz | givenergy_ac1_hz |

## Installing on Fedora

 1. Install and configure Prometheus and Grafana
 1. sudo dnf copr enable barryascott/tools
 1. sudo dnf install python3-prometheus-givenergy

Use systemd service and timer units to run the command periodically
(or cron if you prefer).

Timer unit: `/etc/systemd/system/givenergy.timer`
```
[Unit]
Description=givenergy.timer

[Timer]
OnBootSec=60 seconds
OnUnitInactiveSec=30 seconds

[Install]
WantedBy=multi-user.target
```

Service unit: `/etc/systemd/system/givenergy.service`
```
[Unit]
Description=givenergy.service

[Service]
User=prometheus

Type=oneshot
TimeoutStartSec=0

ExecStartPre=/usr/bin/id
ExecStart=/usr/bin/prometheus-givenergy hf-a21.chelsea.private

[Install]
WantedBy=multi-user.target
```

Once the systemd unit files are in place:

 1. sudo systemctl daemon-reload
 1. sudo systemctl enable --now givenergy.timer
