import struct
from enum import Enum, auto

class Scaling(int, Enum):
    """What scaling factor needs to be applied to a register's value.

    Specified as a divisor instead, because python deals with rounding precision better that way.
    """

    UNIT = 1
    DECI = 10
    CENTI = 100
    MILLI = 1000


class Unit(str, Enum):
    """Measurement unit for the register value."""

    SCALAR = ''
    ENERGY_KWH = 'kwh'
    POWER_W = 'w'
    POWER_KW = 'kw'
    POWER_VA = 'va'
    FREQUENCY_HZ = 'hz'
    VOLTAGE_V = 'volts'
    CURRENT_A = 'amps'
    TEMPERATURE_C = 'temp_c'
    CHARGE_AH = 'ah'
    TIME_S = 'sec'
    TIME_M = 'min'


class Encoding(Enum):
    """Encoding of data register represents. Encoding is always big-endian."""

    BOOL = auto()
    BITFIELD = auto()
    HEX = auto()
    UINT8 = auto()
    DUINT8 = auto()         # double-uint8
    UINT16 = auto()
    INT16 = auto()
    UINT32_HIGH = auto()    # higher (MSB) address half
    UINT32_LOW = auto()     # lower (LSB) address half
    ASCII = auto()          # 2 ASCII characters
    TIME = auto()           # BCD-encoded time. 430 = 04:30
    POWER_FACTOR = auto()   # zero point at 10^4, scale factor 10^4

class Type(Enum):
    COUNTER = 'counter'
    GUAGE = 'guage'

class Metric:
    def __init__(self, name, value, unit, prom_type):
        self.name = name
        self.value = value
        self.unit = unit.value
        self.prom_type = prom_type

    def __lt__(self, other):
        return self.name < other.name

class ModbusRegisterConversion:
    def __init__(self, app):
        self.app = app

    def metric(self, register, register_store):
        rd = self.register_definition[register]
        if 'cont' in rd or 'unknown' in rd:
            # unknown registers do not have a known meaning
            # cont registers are part are combined into another metric
            return []

        name = rd['name']
        rtype = rd.get('type', Encoding.UINT16)
        scale = rd.get('scaling', Scaling.UNIT)
        unit = rd.get('unit', Unit.SCALAR)
        more = rd.get('more')
        writable = rd.get('write_safe', False)
        prom_type = rd.get('prometheus', 'guage')
        true_value = rd.get('true_value', 1)

        v = register_store[register]

        if rtype == Encoding.BOOL:
            # leave as-is but check for validity
            if v not in (0, true_value):
                raise RuntimeError(f'Encoding.BOOL value {v} unexpected for register {register} ("{name}")')
            # coerce to 0, 1
            if v == true_value:
                v = 1

        elif rtype == Encoding.BITFIELD:
            # leave as-is
            pass

        elif rtype == Encoding.HEX:
            v = f'{v:04x}'

        elif rtype == Encoding.UINT8:
            v = self._scaleValue(v, scale)

        elif rtype == Encoding.DUINT8:
            # there are 2 metrics packed in 16 bits.
            msb, lsb = divmod(v, 256)
            return [Metric(name, msb, unit, prom_type), Metric(rd['name2'], lsb, unit, prom_type)]

        elif rtype == Encoding.UINT16:
            v = self._scaleValue(v, scale)

        elif rtype == Encoding.INT16:
            # unsigned to signed
            v = struct.unpack('h', struct.pack('H', v))[0]
            v = self._scaleValue(v, scale)

        elif rtype == Encoding.UINT32_HIGH:
            if more is None:
                raise RuntimeError(f'Encoding.UINT32_HIGH missing "more" field for register {register} ("{name}")')

            if more != (register + 1):
                raise RuntimeError(f'Encoding.UINT32_HIGH "more" value {more} is not {register+1} field for register {register} ("{name}")')

            v = v<<16 | register_store[more]
            v = self._scaleValue(v, scale)

        elif rtype == Encoding.UINT32_LOW:
            raise RuntimeError(f'Encoding.UINT32_LOW defined for register {register} ("{name}")')

        elif rtype == Encoding.ASCII:
            v = []
            for part in [register] + more:
                register_store[part].to_bytes(2, byteorder='big').decode(encoding='ascii')

            v = ''.join(v)

        elif rtype == Encoding.TIME:
            pass
            # fix me

        elif rtype == Encoding.POWER_FACTOR:
            v =  (v - 10_000) / 10_000

        else:
            raise RuntimeError(f'Encoding {rtype} unsupported for register {register} ("{name}")')

        return [Metric(name, v, unit, prom_type)]

    def _scaleValue(self, v, scale):
        return v / scale

class GivEnergyHoldingRegisterConversion(ModbusRegisterConversion):
    def __init__(self, app):
        super().__init__(app)

    register_definition = {
        0: {'name': 'device_type_code', 'type': Encoding.HEX},  # 0x[01235]xxx where 2=Inv?, 5==EMS
        1: {'name': 'inverter_module', 'type': Encoding.UINT32_HIGH, 'more': 2},
        2: {'cont': 'inverter_module'},
        3: {'name': 'num_mppt', 'name2': 'num_phases', 'type': Encoding.DUINT8},  # number of MPPTs and phases
        4: {'unknown': 'holding_reg004'},
        5: {'unknown': 'holding_reg005'},
        6: {'unknown': 'holding_reg006'},
        7: {'name': 'enable_ammeter', 'type': Encoding.BOOL},
        8: {'name': 'first_battery_serial_number', 'type': Encoding.ASCII, 'more': [9, 10, 11, 12]},
        9: {'cont': 'first_battery_serial_number'},
        10: {'cont': 'first_battery_serial_number'},
        11: {'cont': 'first_battery_serial_number'},
        12: {'cont': 'first_battery_serial_number'},
        13: {'name': 'inverter_serial_number', 'type': Encoding.ASCII, 'more': [14, 15, 16, 17]},
        14: {'cont': 'inverter_serial_number'},
        15: {'cont': 'inverter_serial_number'},
        16: {'cont': 'inverter_serial_number'},
        17: {'cont': 'inverter_serial_number'},
        18: {'name': 'first_battery_bms_firmware_version'},
        19: {'name': 'dsp_firmware_version'},
        20: {'name': 'enable_charge_target', 'type': Encoding.BOOL, 'write_safe': True},
        21: {'name': 'arm_firmware_version'},
        22: {'name': 'usb_device_inserted'},    # (0:none, 1:wifi, 2:disk)
        23: {'name': 'select_arm_chip', 'type': Encoding.BOOL},  # False: DSP selected
        24: {'name': 'variable_address'},
        25: {'name': 'variable_value', 'type': Encoding.INT16},
        26: {'name': 'p_grid_port_max_output', 'unit': Unit.POWER_W},  # Export limit
        27: {'name': 'battery_power_mode', 'write_safe': True},  # 0:export/max 1:demand/self-consumption
        28: {'name': 'enable_60hz_freq_mode', 'type': Encoding.BOOL},  # 0:50hz
        # battery calibration stages (0:off  1:start/discharge  2:set lower limit  3:charge
        # 4:set upper limit  5:balance  6:set full capacity  7:finish)
        29: {'name': 'soc_force_adjust'},
        30: {'name': 'inverter_modbus_address', 'type': Encoding.UINT8},  # default 0x11
        31: {'name': 'charge_slot_2_start', 'type': Encoding.TIME, 'write_safe': True},
        32: {'name': 'charge_slot_2_end', 'type': Encoding.TIME, 'write_safe': True},
        33: {'name': 'user_code'},
        34: {'name': 'modbus_version', 'scaling': Scaling.CENTI},  # inverter:1.40 EMS:3.40
        35: {'name': 'system_time_year', 'write_safe': True},
        36: {'name': 'system_time_month', 'write_safe': True},
        37: {'name': 'system_time_day', 'write_safe': True},
        38: {'name': 'system_time_hour', 'write_safe': True},
        39: {'name': 'system_time_minute', 'write_safe': True},
        40: {'name': 'system_time_second', 'write_safe': True},
        41: {'name': 'enable_drm_rj45_port', 'type': Encoding.BOOL},
        42: {'name': 'ct_adjust', 'type': Encoding.BITFIELD},  # bitfield? 1:negative/reverse polarity of blue CT clamp sensor
        43: {'name': 'charge_soc', 'name2': 'discharge_soc', 'type': Encoding.DUINT8},
        44: {'name': 'discharge_slot_2_start', 'type': Encoding.TIME, 'write_safe': True},
        45: {'name': 'discharge_slot_2_end', 'type': Encoding.TIME, 'write_safe': True},
        46: {'name': 'bms_chip_version'},   # different from 18, 101 seems the norm?
        47: {'name': 'meter_type'},         # 0:CT/EM418, 1:EM115
        48: {'name': 'reverse_115_meter_direct', 'type': Encoding.BOOL},
        49: {'name': 'reverse_418_meter_direct', 'type': Encoding.BOOL},
        # from beta remote control: Inverter Max Output Active Power Percent
        50: {'name': 'active_power_rate', 'scaling': Scaling.CENTI},
        51: {'name': 'reactive_power_rate', 'scaling': Scaling.CENTI},
        52: {'name': 'power_factor', 'type': Encoding.POWER_FACTOR},
        53: {'name': 'inverter_auto_restart_state', 'name2': 'inverter_enable_state', 'type': Encoding.DUINT8},  # MSB:auto-restart state, LSB:on/off
        54: {'name': 'battery_type'},   # 0:lead acid  1:lithium
        55: {'name': 'battery_nominal_capacity', 'unit': Unit.CHARGE_AH},
        56: {'name': 'discharge_slot_1_start', 'type': Encoding.TIME, 'write_safe': True},
        57: {'name': 'discharge_slot_1_end', 'type': Encoding.TIME, 'write_safe': True},
        58: {'name': 'enable_auto_judge_battery_type', 'type': Encoding.BOOL},
        59: {'name': 'enable_discharge', 'type': Encoding.BOOL, 'write_safe': True},
        60: {'name': 'pv_input_start', 'scaling': Scaling.DECI, 'unit': Unit.VOLTAGE_V},
        61: {'name': 'inverter_start_time', 'unit': Unit.TIME_S},
        62: {'name': 'inverter_restart_delay_time', 'unit': Unit.TIME_S},
        63: {'name': 'ac_low_out', 'scaling': Scaling.DECI, 'unit': Unit.VOLTAGE_V},
        64: {'name': 'ac_high_out', 'scaling': Scaling.DECI, 'unit': Unit.VOLTAGE_V},
        65: {'name': 'ac_low_out', 'scaling': Scaling.CENTI, 'unit': Unit.FREQUENCY_HZ},
        66: {'name': 'ac_high_out', 'scaling': Scaling.CENTI, 'unit': Unit.FREQUENCY_HZ},
        67: {'name': 'ac_low_out_time'},
        68: {'name': 'ac_high_out_time'},
        69: {'name': 'ac_low_out_time'},
        70: {'name': 'ac_high_out_time'},
        71: {'name': 'ac_low_in', 'scaling': Scaling.DECI, 'unit': Unit.VOLTAGE_V},
        72: {'name': 'ac_high_in', 'scaling': Scaling.DECI, 'unit': Unit.VOLTAGE_V},
        73: {'name': 'ac_low_in', 'scaling': Scaling.CENTI, 'unit': Unit.FREQUENCY_HZ},
        74: {'name': 'ac_high_in', 'scaling': Scaling.CENTI, 'unit': Unit.FREQUENCY_HZ},
        75: {'name': 'ac_low_in_time'},
        76: {'name': 'ac_high_in_time'},
        77: {'name': 'ac_low_in_time'},
        78: {'name': 'ac_high_in_time'},
        79: {'name': 'ac_low_c', 'scaling': Scaling.DECI, 'unit': Unit.VOLTAGE_V},
        80: {'name': 'ac_high_c', 'scaling': Scaling.DECI, 'unit': Unit.VOLTAGE_V},
        81: {'name': 'ac_low_c', 'scaling': Scaling.CENTI, 'unit': Unit.FREQUENCY_HZ},
        82: {'name': 'ac_high_c', 'scaling': Scaling.CENTI, 'unit': Unit.FREQUENCY_HZ},
        83: {'name': '10_min_protection', 'scaling': Scaling.DECI, 'unit': Unit.VOLTAGE_V},
        84: {'name': 'iso1'},
        85: {'name': 'iso2'},
        # protection events: ground fault circuit interrupter, DC injection
        86: {'name': 'gfci_1_i', 'unit': Unit.CURRENT_A, 'scaling': Scaling.MILLI},
        87: {'name': 'gfci_1_time'},
        88: {'name': 'gfci_2_i', 'unit': Unit.CURRENT_A, 'scaling': Scaling.MILLI},
        89: {'name': 'gfci_2_time'},
        90: {'name': 'dci_1_i', 'unit': Unit.CURRENT_A, 'scaling': Scaling.MILLI},
        91: {'name': 'dci_1_time'},
        92: {'name': 'dci_2_i', 'unit': Unit.CURRENT_A, 'scaling': Scaling.MILLI},
        93: {'name': 'dci_2_time'},
        94: {'name': 'charge_slot_1_start', 'type': Encoding.TIME, 'write_safe': True},
        95: {'name': 'charge_slot_1_end', 'type': Encoding.TIME, 'write_safe': True},
        96: {'name': 'enable_charge', 'type': Encoding.BOOL, 'write_safe': True},
        97: {'name': 'battery_under_protection_limit', 'scaling': Scaling.CENTI, 'unit': Unit.VOLTAGE_V},
        98: {'name': 'battery_over_protection_limit', 'scaling': Scaling.CENTI, 'unit': Unit.VOLTAGE_V},
        99: {'name': 'pv1_voltage_adjust', 'scaling': Scaling.DECI, 'unit': Unit.VOLTAGE_V},
        100: {'name': 'pv2_voltage_adjust', 'scaling': Scaling.DECI, 'unit': Unit.VOLTAGE_V},
        101: {'name': 'grid_r_voltage_adjust', 'scaling': Scaling.DECI, 'unit': Unit.VOLTAGE_V},
        102: {'name': 'grid_s_voltage_adjust', 'scaling': Scaling.DECI, 'unit': Unit.VOLTAGE_V},
        103: {'name': 'grid_t_voltage_adjust', 'scaling': Scaling.DECI, 'unit': Unit.VOLTAGE_V},
        104: {'name': 'grid_power_adjust', 'unit': Unit.POWER_W},
        105: {'name': 'battery_voltage_adjust', 'scaling': Scaling.DECI, 'unit': Unit.VOLTAGE_V},
        106: {'name': 'pv1_power_adjust', 'unit': Unit.POWER_W},
        107: {'name': 'pv2_power_adjust', 'unit': Unit.POWER_W},
        108: {'name': 'battery_low_force_charge_time', 'unit': Unit.TIME_M},
        109: {'name': 'enable_bms_read', 'type': Encoding.BOOL},
        110: {'name': 'battery_soc_reserve', 'scaling': Scaling.CENTI, 'write_safe': True},
        # in beta dashboard: Battery Charge & Discharge Power, but rendered as W (50%=2600W), don't set above this?
        111: {'name': 'battery_charge_limit', 'scaling': Scaling.CENTI, 'write_safe': True},
        112: {'name': 'battery_discharge_limit', 'scaling': Scaling.CENTI, 'write_safe': True},
        113: {'name': 'enable_buzzer', 'type': Encoding.BOOL},
        # in beta dashboard: Battery Cutoff % Limit
        114: {'name': 'battery_discharge_min_power_reserve', 'scaling': Scaling.CENTI, 'write_safe': True},
        115: {'name': 'island_check_continue'},
        116: {'name': 'charge_target_soc', 'scaling': Scaling.CENTI, 'write_safe': True},  # when ENABLE_CHARGE_TARGET is enabled
        117: {'name': 'charge_soc_stop_2', 'scaling': Scaling.CENTI},
        118: {'name': 'discharge_soc_stop_2', 'scaling': Scaling.CENTI},
        119: {'name': 'charge_soc_stop_1', 'scaling': Scaling.CENTI},
        120: {'name': 'discharge_soc_stop_1', 'scaling': Scaling.CENTI},
        121: {'name': 'local_command_test'},
        122: {'name': 'power_factor_function_model'},
        123: {'name': 'frequency_load_limit_rate'},
        124: {'name': 'enable_low_voltage_fault_ride_through', 'type': Encoding.BOOL},
        125: {'name': 'enable_frequency_derating', 'type': Encoding.BOOL},
        126: {'name': 'enable_above_6kw_system', 'type': Encoding.BOOL},
        127: {'name': 'start_system_auto_test', 'type': Encoding.BOOL},
        128: {'name': 'enable_spi', 'type': Encoding.BOOL},
        129: {'name': 'pf_cmd_memory_state'},
        # power factor limit line points: LP=load percentage, PF=power factor
        130: {'name': 'pf_limit_lp1_lp', 'scaling': Scaling.DECI},
        131: {'name': 'pf_limit_lp1_pf', 'type': Encoding.POWER_FACTOR},
        132: {'name': 'pf_limit_lp2_lp', 'scaling': Scaling.DECI},
        133: {'name': 'pf_limit_lp2_pf', 'type': Encoding.POWER_FACTOR},
        134: {'name': 'pf_limit_lp3_lp', 'scaling': Scaling.DECI},
        135: {'name': 'pf_limit_lp3_pf', 'type': Encoding.POWER_FACTOR},
        136: {'name': 'pf_limit_lp4_lp', 'scaling': Scaling.DECI},
        137: {'name': 'pf_limit_lp4_pf', 'type': Encoding.POWER_FACTOR},
        138: {'name': 'cei021_v1s'},
        139: {'name': 'cei021_v2s'},
        140: {'name': 'cei021_v1l'},
        141: {'name': 'cei021_v2l'},
        142: {'name': 'cei021_q_lock_in_power', 'scaling': Scaling.DECI},
        143: {'name': 'cei021_q_lock_out_power', 'scaling': Scaling.DECI},
        144: {'name': 'cei021_lock_in_grid_voltage', 'scaling': Scaling.DECI, 'unit': Unit.VOLTAGE_V},
        145: {'name': 'cei021_lock_out_grid_voltage', 'scaling': Scaling.DECI, 'unit': Unit.VOLTAGE_V},
        146: {'unknown': 'holding_reg146'},
        147: {'unknown': 'holding_reg147'},
        148: {'unknown': 'holding_reg148'},
        149: {'unknown': 'holding_reg149'},
        150: {'unknown': 'holding_reg150'},
        151: {'unknown': 'holding_reg151'},
        152: {'unknown': 'holding_reg152'},
        153: {'unknown': 'holding_reg153'},
        154: {'unknown': 'holding_reg154'},
        155: {'unknown': 'holding_reg155'},
        156: {'unknown': 'holding_reg156'},
        157: {'unknown': 'holding_reg157'},
        158: {'unknown': 'holding_reg158'},
        159: {'unknown': 'holding_reg159'},
        160: {'unknown': 'holding_reg160'},
        161: {'unknown': 'holding_reg161'},
        162: {'unknown': 'holding_reg162'},
        163: {'unknown': 'holding_reg163'},
        164: {'unknown': 'holding_reg164'},
        165: {'unknown': 'holding_reg165'},
        166: {'unknown': 'holding_reg166'},
        167: {'unknown': 'holding_reg167'},
        168: {'unknown': 'holding_reg168'},
        169: {'unknown': 'holding_reg169'},
        170: {'unknown': 'holding_reg170'},
        171: {'unknown': 'holding_reg171'},
        172: {'unknown': 'holding_reg172'},
        173: {'unknown': 'holding_reg173'},
        174: {'unknown': 'holding_reg174'},
        175: {'unknown': 'holding_reg175'},
        176: {'unknown': 'holding_reg176'},
        177: {'unknown': 'holding_reg177'},
        178: {'unknown': 'holding_reg178'},
        179: {'unknown': 'holding_reg179'},
        180: {'unknown': 'holding_reg180'},
        181: {'unknown': 'holding_reg181'},
        182: {'unknown': 'holding_reg182'},
        183: {'unknown': 'holding_reg183'},
        184: {'unknown': 'holding_reg184'},
        185: {'unknown': 'holding_reg185'},
        186: {'unknown': 'holding_reg186'},
        187: {'unknown': 'holding_reg187'},
        188: {'unknown': 'holding_reg188'},
        189: {'unknown': 'holding_reg189'},
        190: {'unknown': 'holding_reg190'},
        191: {'unknown': 'holding_reg191'},
        192: {'unknown': 'holding_reg192'},
        193: {'unknown': 'holding_reg193'},
        194: {'unknown': 'holding_reg194'},
        195: {'unknown': 'holding_reg195'},
        196: {'unknown': 'holding_reg196'},
        197: {'unknown': 'holding_reg197'},
        198: {'unknown': 'holding_reg198'},
        199: {'unknown': 'holding_reg199'},
        200: {'unknown': 'holding_reg200'},
        201: {'unknown': 'holding_reg201'},
        }


class GivEnergyInputRegisterConversion(ModbusRegisterConversion):
    def __init__(self, app):
        super().__init__(app)

    register_definition = {
        0: {'name': 'inverter_status'},  # 0:waiting 1:normal 2:warning 3:fault 4:flash/fw update
        1: {'name': 'pv1', 'scaling': Scaling.DECI, 'unit': Unit.VOLTAGE_V},
        2: {'name': 'pv2', 'scaling': Scaling.DECI, 'unit': Unit.VOLTAGE_V},
        3: {'name': 'p_bus', 'scaling': Scaling.DECI, 'unit': Unit.VOLTAGE_V},
        4: {'name': 'n_bus', 'scaling': Scaling.DECI, 'unit': Unit.VOLTAGE_V},
        5: {'name': 'ac1', 'scaling': Scaling.DECI, 'unit': Unit.VOLTAGE_V},
        6: {'name': 'battery_throughput_total', 'prometheus': 'counter', 'type': Encoding.UINT32_HIGH, 'scaling': Scaling.DECI, 'unit': Unit.ENERGY_KWH, 'more': 7},
        7: {'cont': 'battery_throughput_total'},
        8: {'name': 'pv1', 'scaling': Scaling.CENTI, 'unit': Unit.CURRENT_A},
        9: {'name': 'pv2', 'scaling': Scaling.CENTI, 'unit': Unit.CURRENT_A},
        10: {'name': 'ac1', 'scaling': Scaling.CENTI, 'unit': Unit.CURRENT_A},
        11: {'name': 'pv_total', 'prometheus': 'counter', 'type': Encoding.UINT32_HIGH, 'scaling': Scaling.DECI, 'unit': Unit.ENERGY_KWH, 'more': 12},
        12: {'cont': 'pv_total'},
        13: {'name': 'ac1', 'scaling': Scaling.CENTI, 'unit': Unit.FREQUENCY_HZ},
        14: {'name': 'charge_status'},      # 2?
        15: {'name': 'highbrigh_bus'},    # high voltage bus?
        16: {'name': 'inverter_out', 'type': Encoding.POWER_FACTOR},  # should be F_? seems to be hovering between 4800-5400
        17: {'name': 'pv1_day', 'scaling': Scaling.DECI, 'unit': Unit.ENERGY_KWH},
        18: {'name': 'pv1', 'unit': Unit.POWER_KW},
        19: {'name': 'pv2_day', 'scaling': Scaling.DECI, 'unit': Unit.ENERGY_KWH},
        20: {'name': 'pv2', 'unit': Unit.POWER_KW},
        21: {'name': 'grid_out_total', 'prometheus': 'counter', 'type': Encoding.UINT32_HIGH, 'scaling': Scaling.DECI, 'unit': Unit.ENERGY_KWH, 'more': 22},
        22: {'cont': 'grid_out_total'},
        23: {'name': 'solar_diverter', 'scaling': Scaling.DECI, 'unit': Unit.ENERGY_KWH},
        24: {'name': 'inverter_out', 'type': Encoding.INT16, 'unit': Unit.POWER_W},
        25: {'name': 'grid_out_day', 'scaling': Scaling.DECI, 'unit': Unit.ENERGY_KWH},
        26: {'name': 'grid_in_day', 'scaling': Scaling.DECI, 'unit': Unit.ENERGY_KWH},
        27: {'name': 'inverter_in_total', 'prometheus': 'counter', 'type': Encoding.UINT32_HIGH, 'scaling': Scaling.DECI, 'unit': Unit.ENERGY_KWH, 'more': 28},
        28: {'cont': 'inverter_in_total'},
        29: {'name': 'discharge_year', 'scaling': Scaling.DECI, 'unit': Unit.ENERGY_KWH},
        30: {'name': 'grid_out', 'type': Encoding.INT16, 'unit': Unit.POWER_W},
        31: {'name': 'eps_backup', 'unit': Unit.POWER_W},
        32: {'name': 'grid_in_total', 'prometheus': 'counter', 'type': Encoding.UINT32_HIGH, 'scaling': Scaling.DECI, 'unit': Unit.ENERGY_KWH, 'more': 33},
        33: {'cont': 'grid_in_total',},
        34: {'unknown': 'input_reg034'},
        35: {'name': 'inverter_in_day', 'scaling': Scaling.DECI, 'unit': Unit.ENERGY_KWH},
        36: {'name': 'battery_charge_day', 'scaling': Scaling.DECI, 'unit': Unit.ENERGY_KWH},
        37: {'name': 'battery_discharge_day', 'scaling': Scaling.DECI, 'unit': Unit.ENERGY_KWH},
        38: {'name': 'inverter_countdown', 'unit': Unit.TIME_S},
        39: {'name': 'fault_code_h', 'type': Encoding.BITFIELD},
        40: {'name': 'fault_code_l', 'type': Encoding.BITFIELD},
        41: {'name': 'inverter_heatsink', 'scaling': Scaling.DECI, 'unit': Unit.TEMPERATURE_C},
        42: {'name': 'load_demand', 'unit': Unit.POWER_W},
        43: {'name': 'grid_apparent', 'unit': Unit.POWER_VA},
        44: {'name': 'inverter_out_day', 'scaling': Scaling.DECI, 'unit': Unit.ENERGY_KWH},
        45: {'name': 'inverter_out_total', 'prometheus': 'counter', 'type': Encoding.UINT32_HIGH, 'scaling': Scaling.DECI, 'unit': Unit.ENERGY_KWH, 'more': 46},
        46: {'cont': 'inverter_out_total'},
        47: {'name': 'work_time_total', 'type': Encoding.UINT32_HIGH, 'unit': Unit.TIME_S, 'more': 48},
        48: {'cont': 'work_time_total'},
        49: {'name': 'system_mode'},  # 0:offline, 1:grid-tied
        50: {'name': 'battery', 'scaling': Scaling.CENTI, 'unit': Unit.VOLTAGE_V},
        51: {'name': 'battery', 'type': Encoding.INT16, 'scaling': Scaling.CENTI, 'unit': Unit.CURRENT_A},
        52: {'name': 'battery', 'type': Encoding.INT16, 'unit': Unit.POWER_W},
        53: {'name': 'eps_backup', 'scaling': Scaling.DECI, 'unit': Unit.VOLTAGE_V},
        54: {'name': 'eps_backup', 'scaling': Scaling.CENTI, 'unit': Unit.FREQUENCY_HZ},
        55: {'name': 'charger', 'scaling': Scaling.DECI, 'unit': Unit.TEMPERATURE_C},
        56: {'name': 'battery', 'scaling': Scaling.DECI, 'unit': Unit.TEMPERATURE_C},
        57: {'name': 'charger_warning_code'},
        58: {'name': 'grid_port', 'scaling': Scaling.CENTI, 'unit': Unit.CURRENT_A},
        59: {'name': 'battery_level', 'scaling': Scaling.CENTI},
        60: {'name': 'battery_cell_01', 'scaling': Scaling.MILLI, 'unit': Unit.VOLTAGE_V},
        61: {'name': 'battery_cell_02', 'scaling': Scaling.MILLI, 'unit': Unit.VOLTAGE_V},
        62: {'name': 'battery_cell_03', 'scaling': Scaling.MILLI, 'unit': Unit.VOLTAGE_V},
        63: {'name': 'battery_cell_04', 'scaling': Scaling.MILLI, 'unit': Unit.VOLTAGE_V},
        64: {'name': 'battery_cell_05', 'scaling': Scaling.MILLI, 'unit': Unit.VOLTAGE_V},
        65: {'name': 'battery_cell_06', 'scaling': Scaling.MILLI, 'unit': Unit.VOLTAGE_V},
        66: {'name': 'battery_cell_07', 'scaling': Scaling.MILLI, 'unit': Unit.VOLTAGE_V},
        67: {'name': 'battery_cell_08', 'scaling': Scaling.MILLI, 'unit': Unit.VOLTAGE_V},
        68: {'name': 'battery_cell_09', 'scaling': Scaling.MILLI, 'unit': Unit.VOLTAGE_V},
        69: {'name': 'battery_cell_10', 'scaling': Scaling.MILLI, 'unit': Unit.VOLTAGE_V},
        70: {'name': 'battery_cell_11', 'scaling': Scaling.MILLI, 'unit': Unit.VOLTAGE_V},
        71: {'name': 'battery_cell_12', 'scaling': Scaling.MILLI, 'unit': Unit.VOLTAGE_V},
        72: {'name': 'battery_cell_13', 'scaling': Scaling.MILLI, 'unit': Unit.VOLTAGE_V},
        73: {'name': 'battery_cell_14', 'scaling': Scaling.MILLI, 'unit': Unit.VOLTAGE_V},
        74: {'name': 'battery_cell_15', 'scaling': Scaling.MILLI, 'unit': Unit.VOLTAGE_V},
        75: {'name': 'battery_cell_16', 'scaling': Scaling.MILLI, 'unit': Unit.VOLTAGE_V},
        76: {'name': 'battery_cells_1', 'scaling': Scaling.DECI, 'unit': Unit.TEMPERATURE_C},
        77: {'name': 'battery_cells_2', 'scaling': Scaling.DECI, 'unit': Unit.TEMPERATURE_C},
        78: {'name': 'battery_cells_3', 'scaling': Scaling.DECI, 'unit': Unit.TEMPERATURE_C},
        79: {'name': 'battery_cells_4', 'scaling': Scaling.DECI, 'unit': Unit.TEMPERATURE_C},
        80: {'name': 'battery_cells_sum', 'scaling': Scaling.MILLI, 'unit': Unit.VOLTAGE_V},
        81: {'name': 'temp_bms_mos', 'scaling': Scaling.DECI, 'unit': Unit.TEMPERATURE_C},
        82: {'name': 'battery_out', 'type': Encoding.UINT32_HIGH, 'scaling': Scaling.MILLI, 'unit': Unit.VOLTAGE_V, 'more': 83},
        83: {'cont': 'battery_out'},
        84: {'name': 'battery_full_capacity', 'type': Encoding.UINT32_HIGH, 'scaling': Scaling.CENTI, 'unit': Unit.CHARGE_AH, 'more': 85},
        85: {'cont': 'battery_full_capacity', 'type': Encoding.UINT32_LOW, 'scaling': Scaling.CENTI, 'unit': Unit.CHARGE_AH},
        86: {'name': 'battery_design_capacity', 'type': Encoding.UINT32_HIGH, 'scaling': Scaling.CENTI, 'unit': Unit.CHARGE_AH, 'more': 87},
        87: {'cont': 'battery_design_capacity'},
        88: {'name': 'battery_remaining_capacity', 'type': Encoding.UINT32_HIGH, 'scaling': Scaling.CENTI, 'unit': Unit.CHARGE_AH, 'more': 89},
        89: {'cont': 'battery_remaining_capacity'},
        90: {'name': 'battery_status_1', 'name2': 'battery_status_2', 'type': Encoding.DUINT8},
        91: {'name': 'battery_status_3', 'name2': 'battery_status_4', 'type': Encoding.DUINT8},
        92: {'name': 'battery_status_5', 'name2': 'battery_status_6', 'type': Encoding.DUINT8},
        93: {'name': 'battery_status_7', 'name2': 'battery_status_8', 'type': Encoding.DUINT8},
        94: {'name': 'battery_warning_1', 'name2': 'battery_warning_2', 'type': Encoding.DUINT8},
        95: {'unknown': 'input_reg095'},
        96: {'name': 'battery_num_cycles'},
        97: {'name': 'battery_num_cells'},
        98: {'name': 'bms_firmware_version'},
        99: {'unknown': 'input_reg099'},
        100: {'name': 'battery_soc'},
        101: {'name': 'battery_design_capacity_2', 'type': Encoding.UINT32_HIGH, 'scaling': Scaling.CENTI, 'unit': Unit.CHARGE_AH, 'more': 102},
        102: {'cont': 'battery_design_capacity_2'},
        103: {'name': 'temp_battery_max', 'scaling': Scaling.DECI, 'unit': Unit.TEMPERATURE_C},
        104: {'name': 'temp_battery_min', 'scaling': Scaling.DECI, 'unit': Unit.TEMPERATURE_C},
        105: {'name': 'battery_discharge_total_2', 'scaling': Scaling.DECI, 'unit': Unit.ENERGY_KWH},
        106: {'name': 'battery_charge_total_2', 'scaling': Scaling.DECI, 'unit': Unit.ENERGY_KWH},
        107: {'unknown': 'input_reg107'},
        108: {'unknown': 'input_reg108'},
        109: {'unknown': 'input_reg109'},
        110: {'name': 'battery_serial_number', 'type': Encoding.ASCII, 'more': [111, 112, 113, 114]},
        111: {'cont': 'battery_serial_number'},
        112: {'cont': 'battery_serial_number'},
        113: {'cont': 'battery_serial_number'},
        114: {'cont': 'battery_serial_number'},
        115: {'name': 'usb_inserted', 'type': Encoding.BOOL, 'true_value': 0x08},  # 0x08 = true; 0x00 = false
        116: {'unknown': 'input_reg116'},
        117: {'unknown': 'input_reg117'},
        118: {'unknown': 'input_reg118'},
        119: {'unknown': 'input_reg119'},
        120: {'unknown': 'input_reg120'},
        121: {'unknown': 'input_reg121'},
        122: {'unknown': 'input_reg122'},
        123: {'unknown': 'input_reg123'},
        124: {'unknown': 'input_reg124'},
        125: {'unknown': 'input_reg125'},
        126: {'unknown': 'input_reg126'},
        127: {'unknown': 'input_reg127'},
        128: {'unknown': 'input_reg128'},
        129: {'unknown': 'input_reg129'},
        130: {'unknown': 'input_reg130'},
        131: {'unknown': 'input_reg131'},
        132: {'unknown': 'input_reg132'},
        133: {'unknown': 'input_reg133'},
        134: {'unknown': 'input_reg134'},
        135: {'unknown': 'input_reg135'},
        136: {'unknown': 'input_reg136'},
        137: {'unknown': 'input_reg137'},
        138: {'unknown': 'input_reg138'},
        139: {'unknown': 'input_reg139'},
        140: {'unknown': 'input_reg140'},
        141: {'unknown': 'input_reg141'},
        142: {'unknown': 'input_reg142'},
        143: {'unknown': 'input_reg143'},
        144: {'unknown': 'input_reg144'},
        145: {'unknown': 'input_reg145'},
        146: {'unknown': 'input_reg146'},
        147: {'unknown': 'input_reg147'},
        148: {'unknown': 'input_reg148'},
        149: {'unknown': 'input_reg149'},
        150: {'unknown': 'input_reg150'},
        151: {'unknown': 'input_reg151'},
        152: {'unknown': 'input_reg152'},
        153: {'unknown': 'input_reg153'},
        154: {'unknown': 'input_reg154'},
        155: {'unknown': 'input_reg155'},
        156: {'unknown': 'input_reg156'},
        157: {'unknown': 'input_reg157'},
        158: {'unknown': 'input_reg158'},
        159: {'unknown': 'input_reg159'},
        160: {'unknown': 'input_reg160'},
        161: {'unknown': 'input_reg161'},
        162: {'unknown': 'input_reg162'},
        163: {'unknown': 'input_reg163'},
        164: {'unknown': 'input_reg164'},
        165: {'unknown': 'input_reg165'},
        166: {'unknown': 'input_reg166'},
        167: {'unknown': 'input_reg167'},
        168: {'unknown': 'input_reg168'},
        169: {'unknown': 'input_reg169'},
        170: {'unknown': 'input_reg170'},
        171: {'unknown': 'input_reg171'},
        172: {'unknown': 'input_reg172'},
        173: {'unknown': 'input_reg173'},
        174: {'unknown': 'input_reg174'},
        175: {'unknown': 'input_reg175'},
        176: {'unknown': 'input_reg176'},
        177: {'unknown': 'input_reg177'},
        178: {'unknown': 'input_reg178'},
        179: {'unknown': 'input_reg179'},
        180: {'name': 'battery_discharge_total', 'scaling': Scaling.DECI, 'unit': Unit.ENERGY_KWH},
        181: {'name': 'battery_charge_total', 'scaling': Scaling.DECI, 'unit': Unit.ENERGY_KWH},
        182: {'name': 'battery_discharge_day_2', 'scaling': Scaling.DECI, 'unit': Unit.ENERGY_KWH},
        183: {'name': 'battery_charge_day_2', 'scaling': Scaling.DECI, 'unit': Unit.ENERGY_KWH},
        184: {'unknown': 'input_reg184'},
        185: {'unknown': 'input_reg185'},
        186: {'unknown': 'input_reg186'},
        187: {'unknown': 'input_reg187'},
        188: {'unknown': 'input_reg188'},
        189: {'unknown': 'input_reg189'},
        190: {'unknown': 'input_reg190'},
        191: {'unknown': 'input_reg191'},
        192: {'unknown': 'input_reg192'},
        193: {'unknown': 'input_reg193'},
        194: {'unknown': 'input_reg194'},
        195: {'unknown': 'input_reg195'},
        196: {'unknown': 'input_reg196'},
        197: {'unknown': 'input_reg197'},
        198: {'unknown': 'input_reg198'},
        199: {'unknown': 'input_reg199'},
        200: {'unknown': 'input_reg200'},
        201: {'name': 'remote_bms_restart', 'type': Encoding.BOOL},
        202: {'unknown': 'input_reg202'},
        203: {'unknown': 'input_reg203'},
        204: {'unknown': 'input_reg204'},
        205: {'unknown': 'input_reg205'},
        206: {'unknown': 'input_reg206'},
        207: {'unknown': 'input_reg207'},
        208: {'unknown': 'input_reg208'},
        209: {'unknown': 'input_reg209'},
        210: {'name': 'iso_fault_value', 'scaling': Scaling.DECI, 'unit': Unit.VOLTAGE_V},
        211: {'name': 'gfci_fault_value', 'unit': Unit.CURRENT_A, 'scaling': Scaling.MILLI},
        212: {'name': 'dci_fault_value', 'scaling': Scaling.CENTI, 'unit': Unit.CURRENT_A},
        213: {'name': 'pv_fault_value', 'scaling': Scaling.DECI, 'unit': Unit.VOLTAGE_V},
        214: {'name': 'ac_fault_value', 'scaling': Scaling.DECI, 'unit': Unit.VOLTAGE_V},
        215: {'name': 'av_fault_value', 'scaling': Scaling.CENTI, 'unit': Unit.FREQUENCY_HZ},
        216: {'name': 'temp_fault_value', 'scaling': Scaling.DECI, 'unit': Unit.TEMPERATURE_C},
        217: {'unknown': 'input_reg217'},
        218: {'unknown': 'input_reg218'},
        219: {'unknown': 'input_reg219'},
        220: {'unknown': 'input_reg220'},
        221: {'unknown': 'input_reg221'},
        222: {'unknown': 'input_reg222'},
        223: {'unknown': 'input_reg223'},
        224: {'unknown': 'input_reg224'},
        225: {'name': 'auto_test_process_or_auto_test_step', 'type': Encoding.BITFIELD},
        226: {'name': 'auto_test_result'},
        227: {'name': 'auto_test_stop_step'},
        228: {'unknown': 'input_reg228'},
        229: {'name': 'safety_v_f_limit', 'scaling': Scaling.DECI},
        230: {'name': 'safety_time_limit', 'unit': Unit.TIME_S, 'scaling': Scaling.MILLI},
        231: {'name': 'real_v_f_value', 'scaling': Scaling.DECI},
        232: {'name': 'test_value', 'scaling': Scaling.DECI},
        233: {'name': 'test_treat_value', 'scaling': Scaling.DECI},
        234: {'name': 'test_treat_time'},
        235: {'unknown': 'input_reg235'},
        236: {'unknown': 'input_reg236'},
        237: {'unknown': 'input_reg237'},
        238: {'unknown': 'input_reg238'},
        239: {'unknown': 'input_reg239'},
        240: {'name': 'ac1_m3', 'scaling': Scaling.DECI, 'unit': Unit.VOLTAGE_V},
        241: {'name': 'ac2_m3', 'scaling': Scaling.DECI, 'unit': Unit.VOLTAGE_V},
        242: {'name': 'ac3_m3', 'scaling': Scaling.DECI, 'unit': Unit.VOLTAGE_V},
        243: {'name': 'ac1_m3', 'scaling': Scaling.CENTI, 'unit': Unit.CURRENT_A},
        244: {'name': 'ac2_m3', 'scaling': Scaling.CENTI, 'unit': Unit.CURRENT_A},
        245: {'name': 'ac3_m3', 'scaling': Scaling.CENTI, 'unit': Unit.CURRENT_A},
        246: {'name': 'gfci_m3', 'scaling': Scaling.DECI, 'unit': Unit.CURRENT_A, 'scaling': Scaling.MILLI},
        247: {'unknown': 'input_reg247'},
        248: {'unknown': 'input_reg248'},
        249: {'unknown': 'input_reg249'},
        250: {'unknown': 'input_reg250'},
        251: {'unknown': 'input_reg251'},
        252: {'unknown': 'input_reg252'},
        253: {'unknown': 'input_reg253'},
        254: {'unknown': 'input_reg254'},
        255: {'unknown': 'input_reg255'},
        256: {'unknown': 'input_reg256'},
        257: {'unknown': 'input_reg257'},
        258: {'name': 'pv1_limit', 'type': Encoding.INT16, 'scaling': Scaling.DECI, 'unit': Unit.VOLTAGE_V},
        259: {'name': 'pv2_limit', 'type': Encoding.INT16, 'scaling': Scaling.DECI, 'unit': Unit.VOLTAGE_V},
        260: {'name': 'bus_limit', 'type': Encoding.INT16, 'scaling': Scaling.DECI, 'unit': Unit.VOLTAGE_V},
        261: {'name': 'n_bus_limit', 'type': Encoding.INT16, 'scaling': Scaling.DECI, 'unit': Unit.VOLTAGE_V},
        262: {'name': 'ac1_limit', 'type': Encoding.INT16, 'scaling': Scaling.DECI, 'unit': Unit.VOLTAGE_V},
        263: {'name': 'ac2_limit', 'type': Encoding.INT16, 'scaling': Scaling.DECI, 'unit': Unit.VOLTAGE_V},
        264: {'name': 'ac3_limit', 'type': Encoding.INT16, 'scaling': Scaling.DECI, 'unit': Unit.VOLTAGE_V},
        265: {'name': 'pv1_limit', 'type': Encoding.INT16, 'unit': Unit.CURRENT_A, 'scaling': Scaling.MILLI},
        266: {'name': 'pv2_limit', 'type': Encoding.INT16, 'unit': Unit.CURRENT_A, 'scaling': Scaling.MILLI},
        267: {'name': 'ac1_limit', 'type': Encoding.INT16, 'unit': Unit.CURRENT_A, 'scaling': Scaling.MILLI},
        268: {'name': 'ac2_limit', 'type': Encoding.INT16, 'unit': Unit.CURRENT_A, 'scaling': Scaling.MILLI},
        269: {'name': 'ac3_limit', 'type': Encoding.INT16, 'unit': Unit.CURRENT_A, 'scaling': Scaling.MILLI},
        270: {'name': 'ac1_limit', 'type': Encoding.INT16, 'scaling': Scaling.DECI, 'unit': Unit.POWER_W},
        271: {'name': 'ac2_limit', 'type': Encoding.INT16, 'scaling': Scaling.DECI, 'unit': Unit.POWER_W},
        272: {'name': 'ac3_limit', 'type': Encoding.INT16, 'scaling': Scaling.DECI, 'unit': Unit.POWER_W},
        273: {'name': 'dci_limit', 'type': Encoding.INT16, 'scaling': Scaling.DECI, 'unit': Unit.CURRENT_A, 'scaling': Scaling.MILLI},
        274: {'name': 'gfci_limit', 'type': Encoding.INT16, 'scaling': Scaling.DECI, 'unit': Unit.CURRENT_A, 'scaling': Scaling.MILLI},
        275: {'name': 'ac1_m3_limit', 'type': Encoding.INT16, 'scaling': Scaling.DECI, 'unit': Unit.VOLTAGE_V},
        276: {'name': 'ac2_m3_limit', 'type': Encoding.INT16, 'scaling': Scaling.DECI, 'unit': Unit.VOLTAGE_V},
        277: {'name': 'ac3_m3_limit', 'type': Encoding.INT16, 'scaling': Scaling.DECI, 'unit': Unit.VOLTAGE_V},
        278: {'name': 'ac1_m3_limit', 'type': Encoding.INT16, 'scaling': Scaling.CENTI, 'unit': Unit.CURRENT_A},
        279: {'name': 'ac2_m3_limit', 'type': Encoding.INT16, 'scaling': Scaling.CENTI, 'unit': Unit.CURRENT_A},
        280: {'name': 'ac3_m3_limit', 'type': Encoding.INT16, 'scaling': Scaling.CENTI, 'unit': Unit.CURRENT_A},
        281: {'name': 'gfci_m3_limit', 'type': Encoding.INT16, 'scaling': Scaling.DECI, 'unit': Unit.CURRENT_A, 'scaling': Scaling.MILLI},
        282: {'name': 'battery_limit', 'type': Encoding.INT16, 'scaling': Scaling.CENTI, 'unit': Unit.VOLTAGE_V},
        283: {'unknown': 'input_reg283'},
        284: {'unknown': 'input_reg284'},
        285: {'unknown': 'input_reg285'},
        286: {'unknown': 'input_reg286'},
        287: {'unknown': 'input_reg287'},
        288: {'unknown': 'input_reg288'},
        289: {'unknown': 'input_reg289'},
        290: {'unknown': 'input_reg290'},
        291: {'unknown': 'input_reg291'},
        292: {'unknown': 'input_reg292'},
        293: {'unknown': 'input_reg293'},
        294: {'unknown': 'input_reg294'},
        295: {'unknown': 'input_reg295'},
        296: {'unknown': 'input_reg296'},
        297: {'unknown': 'input_reg297'},
        298: {'unknown': 'input_reg298'},
        299: {'unknown': 'input_reg299'},
        300: {'unknown': 'input_reg300'},
        301: {'unknown': 'input_reg301'},
        }
