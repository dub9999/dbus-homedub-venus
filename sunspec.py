# get access to packages of dbus-modbus-client
import sys
import os
import logging

#sys.path.insert(1, os.path.join(os.path.dirname(__file__), '/opt/victronenergy/dbus-modbus-client'))

import device
import probe
from register import *

# other additionnal import because of new read_data_regs
from copy import copy
import time
import traceback
from pymodbus.client.sync import *
from pymodbus.register_read_message import ReadHoldingRegistersResponse

log = logging.getLogger()

class SunspecDevice (device.EnergyMeter):
    def __init__(self, *args):
        super(SunspecDevice, self).__init__(*args)

    def read_data_regs(self, regs, d):
        now = time.time()
        
        if all(now - r.time < r.max_age for r in regs):
            return
        # changed 2 lines to manage sunspec map
        start = self.block_start
        count = self.block_length
        
        rr = self.modbus.read_holding_registers(start, count, unit=self.unit)

        latency = time.time() - now

        if not isinstance(rr, ReadHoldingRegistersResponse):
            log.error('Error reading registers %#04x-%#04x: %s',
                      start, start + count - 1, rr)
            raise Exception(rr)
        
        # following is all changed to fit with sunspec map
        # calculate and allocate the scale factors
        for group, reg in self.scale_factors.items():
            base = reg.base - start
            end = base + reg.count
            reg.decode(rr.registers[base:end])

        for reg in regs:
            if reg.base in self.sf_map:
                reg_group = self.sf_map[reg.base]
                reg_sign = self.scale_signs[reg_group]
                reg_sf = self.scale_factors[reg_group].value
                reg.scale = float(reg_sign / 10**(reg_sf))
            else:
                reg.scale = 1
            base = reg.base - start
            end = base + reg.count

            if now - reg.time > reg.max_age:
                if reg.decode(rr.registers[base:end]):
                    d[reg.name] = copy(reg) if reg.isvalid() else None
                reg.time = now

        return latency

    def get_ident(self):
        #return 'se_%s' % self.info['/Serial']
        return 'se_%s' % self.id

class SunspecMeter(SunspecDevice):
    productid = 203
    productname = 'Solaredge Sunspec Meter'
    min_timeout = 0.5
    
    def __init__(self, *args):
        super(SunspecMeter, self).__init__(*args)
        self.id=203
        self.role='grid'
        self.info_regs = [
            Reg_text( 40163, 8, '/FirmwareVersion'),
            Reg_text( 40171, 16, '/Serial'),
       ]

    def device_init(self):
        #print(os.path.abspath(__file__), '>entering SunspecMeter.device_init')
        self.read_info()
        #print(os.path.abspath(__file__), '>in SunspecMeter.device_init, read_info() completed ')

        self.block_start=40190    #1st register to read for data_registers
        self.block_length=105     #Number of registers to read for data_registers (include scale factors)
        #print(os.path.abspath(__file__), 'in SunspecMeter.device_init', self.map_start, self.map_count)
        '''
        Ancienne définition des data_regs
        self.data_regs=[
            Reg_s16( 40190, '/Ac/Current', 1, '%.1f A'),
            Reg_s16( 40191, '/Ac/L1/Current', 1, '%.1f A'),
            Reg_s16( 40192, '/Ac/L2/Current', 1, '%.1f A'),
            Reg_s16( 40193, '/Ac/L3/Current', 1, '%.1f A'),
            Reg_s16( 40195, '/Ac/Voltage', 1, '%.1f V'),
            Reg_s16( 40196, '/Ac/L1/Voltage', 1, '%.1f V'),
            Reg_s16( 40197, '/Ac/L2/Voltage', 1, '%.1f V'),
            Reg_s16( 40198, '/Ac/L3/Voltage', 1, '%.1f V'),
            Reg_s16( 40204, '/Ac/Frequency', 1, '%.1f Hz'),
            Reg_s16( 40206, '/Ac/Power', 1, '%.1f W'),
            Reg_s16( 40207, '/Ac/L1/Power', 1, '%.1f W'),
            Reg_s16( 40208, '/Ac/L2/Power', 1, '%.1f W'),
            Reg_s16( 40209, '/Ac/L3/Power', 1, '%.1f W'),
            Reg_u32b( 40226, '/Ac/Energy/Forward', 1, '%.1f kWh'),
            Reg_u32b( 40234, '/Ac/Energy/Reverse', 1, '%.1f kWh'),
        ]
        '''
        # 2023-09-18
        # nouvelle définition des dataregs pour fonctionnement monophasé
        # inversion Forward et Reverse car faux dans version initiale
        self.data_regs=[
            Reg_s16( 40190, '/Ac/Current', 1, '%.1f A'),
            Reg_s16( 40191, '/Ac/L1/Current', 1, '%.1f A'),
            Reg_s16( 40195, '/Ac/Voltage', 1, '%.1f V'),
            Reg_s16( 40196, '/Ac/L1/Voltage', 1, '%.1f V'),
            Reg_s16( 40204, '/Ac/Frequency', 1, '%.1f Hz'),
            Reg_s16( 40206, '/Ac/Power', 1, '%.1f W'),
            Reg_s16( 40207, '/Ac/L1/Power', 1, '%.1f W'),
            Reg_u32b( 40226, '/Ac/Energy/Reverse', 1, '%.1f kWh'),
            Reg_u32b( 40234, '/Ac/Energy/Forward', 1, '%.1f kWh'),
            Reg_u32b( 40234, '/Ac/L1/Energy/Forward', 1, '%.1f kWh'),
        ]

        self.scale_factors={
            'Current' : Reg_s16( 40194),
            'Voltage' : Reg_s16( 40203),
            'Frequency' : Reg_s16( 40205),
            'Power' : Reg_s16( 40210),
            'Energy' : Reg_s16( 40242),
        }

        self.scale_signs={
            'Current' : 1,
            'Voltage' : 1,
            'Frequency' : 1,
            'Power' : -1,
            'Energy' : 1000,
        }

        self.sf_map={
            40190 : 'Current',
            40191 : 'Current',
            40192 : 'Current',
            40193 : 'Current',
            40195 : 'Voltage',
            40196 : 'Voltage',
            40197 : 'Voltage',
            40198 : 'Voltage',
            40204 : 'Frequency',
            40206 : 'Power',
            40207 : 'Power',
            40208 : 'Power',
            40209 : 'Power',
            40226 : 'Energy',
            40234 : 'Energy',
        }
        #print(os.path.abspath(__file__), '>SunspecMeter.device_init completed')

class SunspecInverter(SunspecDevice):
    productid = 101
    productname = 'Solaredge Sunspec Inverter'
    min_timeout = 0.5
    
    def __init__(self, *args):
        super(SunspecInverter, self).__init__(*args)
        self.id=101
        self.role='pvinverter'
        self.pos_item = 0 # 0=AC input 1;1=AC output;2=AC input 2
        self.info_regs = [
            Reg_text( 40044, 8, '/FirmwareVersion'),
            Reg_text( 40052, 16, '/Serial'),
        ]

    def device_init(self):
        #print(os.path.abspath(__file__), '>entering SunspecInverter.device_init')
        self.read_info()
        #print(os.path.abspath(__file__), '>in SunspecInverter.device_init, read_info() completed ')
        self.block_start=40071    #1st register to read for data_registers
        self.block_length=39      #Number of registers to read for data_registers (include scale factors)
        #print(os.path.abspath(__file__), 'in SunspecInverter.device_init', self.map_start, self.map_count)
        #Table de données dans le format Sunspec
        self.data_regs=[
            Reg_u16( 40071, '/Ac/Current', 1, '%.1f A'),
            Reg_s16( 40071, '/Ac/L1/Current', 1, '%.1f A'),
            Reg_u16( 40076, '/Ac/Voltage', 1, '%.1f V'),
            Reg_s16( 40076, '/Ac/L1/Voltage', 1, '%.1f V'),
            Reg_u16( 40085, '/Ac/Frequency', 1, '%.1f Hz'),
            Reg_s16( 40083, '/Ac/Power', 1, '%.1f W'),
            Reg_s16( 40083, '/Ac/L1/Power', 1, '%.1f W'),
            Reg_u32b( 40093, '/Ac/Energy/Forward', 1, '%.1f kWh'),
            Reg_u32b( 40093, '/Ac/L1/Energy/Forward', 1, '%.1f kWh'),
            Reg_u16( 40107, '/Status'),
        ]

        self.scale_factors={
            'Current' : Reg_s16( 40075),
            'Voltage' : Reg_s16( 40082),
            'Frequency' : Reg_s16( 40086),
            'Power' : Reg_s16( 40084),
            'Energy' : Reg_s16( 40095),
        }

        self.scale_signs={
            'Current' : 1,
            'Voltage' : 1,
            'Frequency' : 1,
            'Power' : 1,
            'Energy' : 1000,
        }

        self.sf_map={
            40071 : 'Current',
            40076 : 'Voltage',
            40085 : 'Frequency',
            40083 : 'Power',
            40093 : 'Energy',
        }
        #print(os.path.abspath(__file__), '>SunspecInverter.device_init completed')

class SunspecHub(device.ModbusDevice):
    def __init__(self, *args):
        #print(os.path.abspath(__file__), '>Entering SunspecHub.__init__')
        super(SunspecHub, self).__init__(*args)
        self.sunspec_devices=[]
        self.dev_id_regs=[
            Reg_u16( 40069),
            Reg_u16( 40188),
        ]
        self.sunspec_blocks = {
            101:{'model' : 'SE3000H-RW000BNN4', 'handler' : SunspecInverter},
            203:{'model' : 'WND-3Y-400-MB', 'handler' : SunspecMeter},
        }

    def probe_sunspec(self, reg):
        rr = self.modbus.read_holding_registers(reg.base, reg.count, unit=self.unit)

        """
        if not isinstance(rr, ReadHoldingRegistersResponse):
            log.debug('%s: %s', modbus, rr)
            return None
        """
        if not isinstance(rr, ReadHoldingRegistersResponse):
            log.error('Error reading register %#04x: %s', reg.base, rr)
            raise Exception(rr)

        reg.decode(rr.registers)

        if not reg.value in self.sunspec_blocks:
            log.error('unknown sunspec block id: %s', reg.value)
            raise Exception(rr)
            #return None
        m = self.sunspec_blocks[reg.value]
        """
        print(os.path.abspath(__file__), '>In SunspecHub.probe, m: ', m)
        print(os.path.abspath(__file__), '>In SunspecHub.probe, probed device: ', 
            m['handler'](self.modbus, self.unit, m['model']))
        """
        return m['handler'](self.modbus, self.unit, m['model'])

    def init(self, dbus):
        for reg in self.dev_id_regs:
            d = self.probe_sunspec(reg)
            #print(os.path.abspath(__file__), '>In SunspecHub.init, probed device: ', d.model)
            if not d:
                #print(os.path.abspath(__file__), '>In SunspecHub.init, device not probed')
                continue
            log.debug('Found %s at %s', d.model, d)
            d.method = self.method
            d.latency = self.latency

            #print(os.path.abspath(__file__), '>In SunspecHub.init, probed device: ', d)
            d.init(dbus)
            self.sunspec_devices.append(d)
            #print(os.path.abspath(__file__), '>In SunspecHub.init, self.sunspec_devices', self.sunspec_devices)
            #print(os.path.abspath(__file__), '>In SunspecHub.init, SunspecHub.init() completed')


    def update(self):
        for dev in self.sunspec_devices:
            dev.update()

models = {
    0x53756e53: {
        'model':    'Sunspec Model Map',
        'handler':  SunspecHub,
    },
}

probe.add_handler(probe.ModelRegister(Reg_u32b(40000), models,
                                      methods=['tcp'],
                                      units=[1]))

