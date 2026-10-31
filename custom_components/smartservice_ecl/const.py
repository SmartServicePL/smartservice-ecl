"""Constants of Smart Service ECL."""

from __future__ import annotations

from datetime import timedelta

DOMAIN = "smartservice_ecl"
CONF_UNIT = "unit"
DEFAULT_PORT = 502
DEFAULT_UNIT = 1
# Danfoss closes an idle Modbus/TCP connection after about 75 s; a read every
# 30 s keeps the one connection open (VI.LG.V5.02, p. 10).
SCAN_INTERVAL = timedelta(seconds=30)
# Settings, the heat curve, the meter's setup: once an hour.
SLOW_INTERVAL = timedelta(hours=1)
MANUFACTURER = "Danfoss"
# Operator 31.10: the integration and the device are "Danfoss ECL310".
DEVICE_NAME = "Danfoss ECL310"
