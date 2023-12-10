import sys
import os
import struct
from datetime import datetime
import socket

import pymodbus
import pymodbus.payload
import crccheck

from .register import GivEnergyHoldingRegisterConversion, GivEnergyInputRegisterConversion

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

        self.metrics = []

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

    def _transaction(self, s, request, label):
        header_size = struct.calcsize(GivEnergyRequest.FRAME_HEADER)

        msg = request.encode()
        self.debug(f'transaction: request {label} {msg!r}')
        self.debug(f'                     {label} {hex_string(msg, 4)}')

        s.sendall(msg)
        header = s.recv(header_size)

        self.debug(f'transaction {label} header {header!r}')
        tid, pid, size, uid, fid = struct.unpack(GivEnergyRequest.FRAME_HEADER, header)
        self.debug(f'transaction {label} header fields tid={tid:#06x}, pid={pid}, len={size}, uid={uid}, fid={fid}')

        # length includes the UID and FID that has already been read.
        size -= 2

        payload = b''
        while len(payload) < size:
            payload += s.recv(size-len(payload))

        self.debug(f'transaction {label} payload len={len(payload)} {hex_string(payload)}')
        response = GivEnergyResponse(self, payload)
        self.debug(f'transaction {label} {response.data_adapter_serial_number} {response.error}')
        if not response.error:
            for reg in range(request.base_register, request.base_register + request.register_count):
                self.debug(f'transaction {label} register {reg}: {response.register(reg):#06x} ({response.register(reg)})')

        return response

    def fetchMetrics(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.connect((self.host, self.port))

            converter = GivEnergyInputRegisterConversion(self)
            for base, count in [(0, 60), (60, 60), (180, 60)]:
                request = GivEnergyRequest(self, GivEnergyRequest.FUNC_READ_INPUT_REGISTERS, base_register=base, register_count=count)
                input_registers = self._transaction(s, request, 'input')

                for register in range(base, base + count):
                    self.metrics.extend(converter.metric(register, input_registers))

            converter = GivEnergyHoldingRegisterConversion(self)
            for base, count in [(0, 60), (60, 60), (120, 60)]:
                request = GivEnergyRequest(self, GivEnergyRequest.FUNC_READ_HOLDING_REGISTERS, base_register=base, register_count=count)
                holding_registers = self._transaction(s, request, 'holding')

                for register in range(base, base + count):
                    self.metrics.extend(converter.metric(register, holding_registers))

    def printMetrics(self, f):
        print(f'# prometheus_givenergy report {datetime.now()}', file=f)
        self.metrics.sort()
        for metric in self.metrics:
            if metric.unit == '':
                metric_name = f'givenergy_{metric.name}'
            else:
                metric_name = f'givenergy_{metric.name}_{metric.unit}'

            if type(metric.value) in (int, float):
                print(f'# TYPE {metric_name} {metric.prom_type}', file=f)
                print(f'{metric_name} {metric.value}', file=f)

            else:
                print(f'# COMMENT {metric_name} {metric.value}', file=f)

class GivEnergyRequest:
    data_adapter_serial_number = 'AB1234G567'  # must be 10 bytes long
    padding = 0x00000008
    slave_address = 0x32  # 0x11 is the inverter but the cloud systems interfere, 0x32+ are the batteries

    FUNC_READ_HOLDING_REGISTERS = 0x03
    FUNC_READ_INPUT_REGISTERS = 0x04
    # FUNC_WRITE_SINGLE_REGISTER = 0x06

    FRAME_HEADER = ">HHHBB"   # tid(w), pid(w), length(w), uid(b), fid(b)
    GIVENERGY_TID = 0x5959
    GIVENERGY_PID = 0x0001
    GIVENERGY_UID = 0x01
    GIVENERGY_FID = 0x02

    def __init__(self, app, function_code, base_register, register_count):
        self.app = app

        self.function_code = function_code
        assert self.function_code in (self.FUNC_READ_HOLDING_REGISTERS, self.FUNC_READ_INPUT_REGISTERS)
        self.base_register = base_register
        assert 0 <= self.base_register <= 255
        self.register_count = register_count
        assert 1 <= self.register_count <= (255-self.base_register)

    def encode(self):
        b = pymodbus.payload.BinaryPayloadBuilder(byteorder=pymodbus.constants.Endian.BIG)
        # givenergy payload
        b.add_8bit_uint(self.function_code)
        b.add_16bit_uint(self.base_register)
        b.add_16bit_uint(self.register_count)
        self.app.debug(f'GivEnergyRequest.encode b.build() {b.build()}')
        crc_bytes = b.encode()
        self.app.debug(f'GivEnergyRequest.encode crc_bytes {hex_string(crc_bytes)}')

        crc = crccheck.crc.CrcModbus().process(crc_bytes).final()
        self.app.debug(f'GivEnergyRequest.encode crc_bytes {crc:#06x}')

        b = pymodbus.payload.BinaryPayloadBuilder(byteorder=pymodbus.constants.Endian.BIG)
        assert len(self.data_adapter_serial_number) == 10
        b.add_string(self.data_adapter_serial_number)
        b.add_64bit_uint(self.padding)
        b.add_8bit_uint(self.slave_address)
        b.add_8bit_uint(self.function_code)
        # function data
        b.add_16bit_uint(self.base_register)
        b.add_16bit_uint(self.register_count)
        b.add_16bit_uint(crc)

        msg = b.encode()

        header = struct.pack(self.FRAME_HEADER,
            self.GIVENERGY_TID,
            self.GIVENERGY_PID,
            # length includes the UID and FID that are written as part of the header.
            len(msg) + 2,
            self.GIVENERGY_UID,
            self.GIVENERGY_FID)

        return header + msg

class GivEnergyResponse:
    def __init__(self, app, payload):
        self.app = app
        self._register = {}

        decoder = pymodbus.payload.BinaryPayloadDecoder(payload, byteorder=pymodbus.constants.Endian.BIG)
        self.data_adapter_serial_number = decoder.decode_string(10).decode("ascii")
        self.padding = decoder.decode_64bit_uint()
        self.slave_address = decoder.decode_8bit_uint()
        self.function_code = decoder.decode_8bit_uint()
        if self.function_code >= 0x80:
            self.error = True
            self.function_code &= 0x7F
        else:
            self.error = False

        # decode function data
        self.inverter_serial_number = decoder.decode_string(10).decode("ascii")
        self.base_register = decoder.decode_16bit_uint()
        self.register_count = decoder.decode_16bit_uint()
        if not self.error:
            for reg in range(self.base_register, self.base_register + self.register_count):
                self._register[reg] = decoder.decode_16bit_uint()

        self.check = decoder.decode_16bit_uint()

    def register(self, reg):
        return self._register[reg]

    def __getitem__(self, reg):
        return self._register[reg]

def hex_string(binary, grouping=2):
    bin_in_hex = binary.hex()
    return ' '.join([bin_in_hex[i:i+grouping] for i in range(0, len(bin_in_hex), grouping)])
