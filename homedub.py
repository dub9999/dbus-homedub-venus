#! /usr/bin/python3 -u

# This file is a copy of dbus-modbus-client
# other modules from this package have also been imported
# mdns and scan are not used because I have no need to scan the network

# the file sunspec is imported instead of other meter files normally imported by dbus-modbus-client
# it includes:
#   1 class named SunspecHub which can contain several devices having the same modbus address
#   1 class named SunspecInverter which addresses the block of registers corresponding to PV inverter data
#   1 class named SunspecMeter which addresses the block of registers corresponding to grid meter data
#   Both classes inherit from a class named SunspecDevice which contains a read_data_register method
#   Which allows to read the scale factors in the modbus table as defined in the Sunspec Protocol
# Classes are 100% identical

# Revision 16/03/2023
# Added a battery monitor to record the cumulated energy loaded in the battery and pulled from the battery
# get access to packages of dbus-modbus-client

# Revision 03/09/2023
# Added a function to interrupt the program when a file named 'kill' exists in the directory
# This function calls a method of the batteryMonitor to save the charge and discharde indexes
# and exit the glibloop

# get access to packages of dbus-modbus-client
import sys
import os
#sys.path.insert(1, os.path.join(os.path.dirname(__file__), '/opt/victronenergy/dbus-modbus-client'))

from argparse import ArgumentParser
import dbus
import dbus.mainloop.glib
import faulthandler

import pymodbus.constants
from settingsdevice import SettingsDevice
import signal
import time
import traceback
from vedbus import VeDbusService
from gi.repository import GLib

import device
#import mdns
import probe
#from scan import *
from utils import *
import watchdog

import sunspec
from batterymonitor import BatteryMonitor

import logging
log = logging.getLogger()

NAME = os.path.basename(__file__)
VERSION = "1.25"

__all__ = ['NAME', 'VERSION']

pymodbus.constants.Defaults.Timeout = 0.5

#MODBUS_TCP_PORT = 502
#MODBUS_TCP_UNIT = 1

MAX_ERRORS = 5 # was 5 in initial file
FAILED_INTERVAL = 10
#MDNS_CHECK_INTERVAL = 5
#MDNS_QUERY_INTERVAL = 60
#SCAN_INTERVAL = 600
UPDATE_INTERVAL = 250

if_blacklist = [
    'ap0',
]

# Adjust system time zone to CET because system time is normally set to UTC
# We do it everytime we launch the program to ensure time zone is set after firmware update
os.environ['TZ'] = 'Europe/Paris'
time.tzset()

"""
def percent(path, val):
    return '%d%%' % val
"""
class Client(object):
    def __init__(self, name):
        self.name = name
        self.devices = []
        self.failed = []
        self.failed_time = 0
        self.scanner = None
        self.scan_time = time.time()
        self.auto_scan = False
        self.err_exit = False
        self.keep_failed = True
        self.svc = None
        self.watchdog = watchdog.Watchdog()
        self.keep_frozen = False
        self.battery_monitor = None
    """
    def start_scan(self, full=False):
        if self.scanner:
            return

        log.info('Starting background scan')

        s = self.new_scanner(full)

        if s.start():
            self.scanner = s

    def stop_scan(self):
        if self.scanner:
            self.scanner.stop()

    def scan_update(self):
        devices = self.scanner.get_devices()

        for d in devices:
            if d in self.devices:
                d.destroy()
                continue

            try:
                d.init(self.dbusconn)
                d.nosave = False
                self.devices.append(d)
            except:
                log.info('Error initialising %s, skipping', d)
                traceback.print_exc()

        self.save_devices()

    def scan_complete(self):
        self.scan_time = time.time()

        if not self.devices and self.err_exit:
            os._exit(1)

    def set_scan(self, path, val):
        if val:
            self.start_scan()
        else:
            self.stop_scan()

        return True
    """
    def exit_program (self):
        # to stop the program when needed
        # save the battery monitor values
        # delete the file named 'kill'
        # exit the program
        log.info('Program terminated on request')
        log.info('----------------------------------------------------------------------------')
        try:
            self.battery_monitor.save()
        except:
            log.error('Exception in saving battery_monitor', exc_info=True)
        os.remove('/data/home/root/venus.dbus-homedub/kill')
        os._exit(1)

    def update_device(self, dev):
        try:
            # Normally there is no update method in the class of the Device
            # So the method update of the parent (EnergyMeter) is called
            # We create an update method in the class SunspecDevice to allow
            # management of multiple devices
            dev.update()
            dev.err_count = 0

        except:
            dev.err_count += 1
            if dev.err_count == MAX_ERRORS:
                log.debug('Error in executing update_devices')
                log.debug('List of devices before error %s', self.devices)
                log.debug('Device %s failed', dev)
                if self.err_exit:
                    os._exit(1)
                log.debug('List of failed before error %s', self.failed)
                if not dev.nosave:
                    self.failed.append(str(dev))
                log.debug('List of failed after error %s', self.failed)
                if dev.sunspec_devices:
                    log.debug('List of sunspec_devices before error %s', dev.sunspec_devices)
                    for sd in dev.sunspec_devices:
                        log.debug('Deleting Sunspec_device %s at %s', sd.model, sd)
                        sd.destroy()
                    dev.sunspec_devices.clear()
                    log.debug('List of sunspec_devices after error %s', dev.sunspec_devices)
                self.devices.remove(dev)
                log.debug('List of devices after error %s', self.devices)
                dev.destroy()

    def probe_devices(self, devlist, nosave=False):
        # devlist: list of devices to probe
        # each item like [method, ip, port, unit]
        #print(os.path.abspath(__file__), '>Entering Client.probe_devices')
        # only probe devices that have not been probed yet
        devs = set(devlist) - set(self.devices)
        log.debug('Devices to probe %s', devs)
        #print ('devs: ', devs)
        # probe if the device can be contacted and correspond to a known type of device
        # devs = list of recognized devices, 
        # each entry is an instance of the class corresponding to the type of device found
        #   if a device is found a log is made in debug mode
        # failed = list of non recognized devices, each item like [method, ip, port, unit]
        devs, failed = probe.probe(devs)
        log.debug('Probed devices: devs %s | failed %s', devs, failed)
        #print ('devs: ', devs, 'failed: ', failed)
        # initialize all devices that have been found
        for d in devs:
            try:
                # Normally there is no init method in the class of the Device
                # So the method init of the parent (EnergyMeter) is called
                # We create an init method in the class SunspecDevice to allow
                # management of multiple devices
                #print(os.path.abspath(__file__), '>In Client.probe_devices, self.dbusconn', self.dbusconn)0
                log.debug('List of sunspec_devices %s', d.sunspec_devices)
                d.init(self.dbusconn)
                #print(os.path.abspath(__file__), '>In Client.probe_devices, d.init completed')
                d.nosave = nosave
                #print(os.path.abspath(__file__), '>In Client.probe_devices, d.nosave set')
                self.devices.append(d)
                #print(os.path.abspath(__file__), '>In Client.probe_devices, d ajouté à self.devices')
                log.debug('List of devices %s', self.devices)
                if d.sunspec_devices:
                    log.debug('List of sunspec_devices %s', d.sunspec_devices)
                    for sd in d.sunspec_devices:
                        log.debug('Sunspec_device %s active at %s', sd.model, sd)
                #raise TypeError
            except:
                #traceback.print_exc() #rajouté pour débugger
                log.debug('Error in executing probe_devices')
                log.debug('List of devices before error %s', self.devices)
                log.debug('Device %s failed', d)
                if self.err_exit:
                    os._exit(1)
                log.debug('List of failed before error %s', failed)
                failed.append(str(d))
                log.debug('List of failed after error %s', failed)
                if d.sunspec_devices:
                    log.debug('List of sunspec_devices before error %s', d.sunspec_devices)
                    for sd in d.sunspec_devices:
                        log.debug('Deleting Sunspec_device %s at %s', sd.model, sd)
                        sd.destroy()
                    d.sunspec_devices.clear()
                    log.debug('List of sunspec_devices after error %s', d.sunspec_devices)
                self.devices.remove(d)
                log.debug('List of devices after error %s', self.devices)
                d.destroy()
                log.debug('Treatment of error completed successfully, waiting ...')
        #print(os.path.abspath(__file__), '>In Client.probe_devices')
        #print(os.path.abspath(__file__), 'self.devices, failed: ', self.devices, failed)
        return failed

    def save_devices(self):
        devs = filter(lambda d: not d.nosave, self.devices)
        devstr = ','.join(sorted(list(map(str, devs)) + self.failed))
        if devstr != self.settings['devices']:
            self.settings['devices'] = devstr

    def update_devlist(self, old, new):
        # old and new are lists of devices to be compared
        # each list contain items like [method, ip, port, unit]
        #print(os.path.abspath(__file__), '>Entering Client.update_devlist')
        old = set(old.split(','))
        new = set(new.split(','))
        cur = set(self.devices) #List of devices that have already been probed
        rem = old - new         #List of devices that have been removed
        # remove devices that have been deleted from the list of probed devices
        for d in rem & cur:
            dd = self.devices.pop(self.devices.index(d))
            dd.destroy()
        # probe all new devices and save them
        # for devices that are successfully probed, 
        #   the instance of the probed device class is added to self.devices
        # devices that are not probed are returned in the self.failed
        self.failed = self.probe_devices(new);
        self.save_devices()

    def setting_changed(self, name, old, new):
        if name == 'devices':
            self.update_devlist(old, new)
            return

    def init(self, force_scan):
        #print(os.path.abspath(__file__), '>Entering Client.init')
        settings_path = '/Settings/ModbusClient/' + self.name
        SETTINGS = {
            'devices':  [settings_path + '/Devices', '', 0, 0],
            'autoscan': [settings_path + '/AutoScan', self.auto_scan, 0, 1],
        }

        self.dbusconn = private_bus()
        log.debug('Waiting for localsettings')
        #Check if path exist and retrieve all devices shown under path /Devices
        self.settings = SettingsDevice(self.dbusconn, SETTINGS,
                                       self.setting_changed, timeout=10)
        #Check if all devices shown under path /Devices are proben
        self.update_devlist('', self.settings['devices'])
        
        if not self.keep_failed:
            self.failed = []
        """
        scan = force_scan

        if not self.devices or self.failed:
            if self.settings['autoscan']:
                scan = True

        if scan:
            self.start_scan(force_scan)
        """

        # ajout du 16/03/2023 pour batteryMonitor
        try:
            self.battery_monitor = BatteryMonitor(self.dbusconn)
            self.battery_monitor.init()
        except:
            log.info('Exception in creating battery_monitor', exc_info=True)

        self.watchdog.start()
        log.info('Initialisation completed')
        
    def update(self):
        """
        if self.scanner:
            if self.svc:
                self.svc['/Scan'] = self.scanner.running
                self.svc['/ScanProgress'] = \
                    100 * self.scanner.done / self.scanner.total

            self.scan_update()

            if not self.scanner.running:
                self.scan_complete()
                self.scanner = None
                if self.svc:
                    self.svc['/ScanProgress'] = None
        """
        for d in self.devices:
            self.update_device(d)
        
        if self.failed:
            now = time.time()

            if now - self.failed_time > FAILED_INTERVAL:
                self.failed = self.probe_devices(self.failed)
                self.failed_time = now
            """
            if self.settings['autoscan']:
                if now - self.scan_time > SCAN_INTERVAL:
                    self.start_scan()
            """
        try:
            self.battery_monitor.update()
        except:
           log.debug('Exception in updating battery_monitor', exc_info=True)

        self.watchdog.update()
        
    def update_timer(self):
        try:
            self.update()
        except:
            log.error('Uncaught exception in update', exc_info=True)
            #traceback.print_exc()
        
        # to stop the program when needed
        # if a file named 'kill' exists in the directory
        if os.path.isfile('/data/home/root/venus.dbus-homedub/kill'):
            self.exit_program()
        return True

class NetClient(Client):
    def __init__(self, proto):
        Client.__init__(self, proto)
        self.proto = proto
    """
    def new_scanner(self, full):
        return NetScanner(self.proto, MODBUS_TCP_PORT, MODBUS_TCP_UNIT,
                          if_blacklist)
    """
    def init(self, *args):
        #print(os.path.abspath(__file__), '>Entering NetClient.init')
        super(NetClient, self).init(*args)
        """
        svcname = 'com.victronenergy.modbusclient.%s' % self.name
        self.svc = VeDbusService(svcname, self.dbusconn)
        self.svc.add_path('/Scan', False, writeable=True,
                          onchangecallback=self.set_scan)
        self.svc.add_path('/ScanProgress', None, gettextcallback=percent)
        
        self.mdns = mdns.MDNS()
        self.mdns.start()
        self.mdns_check_time = 0
        self.mdns_query_time = 0
        """
    def update(self):
        super(NetClient, self).update()
        """
        now = time.time()
        
        if now - self.mdns_query_time > MDNS_QUERY_INTERVAL:
            self.mdns_query_time = now
            self.mdns.req()

        if now - self.mdns_check_time > MDNS_CHECK_INTERVAL:
            self.mdns_check_time = now
            maddr = self.mdns.get_devices()
            if maddr:
                units = probe.get_units('tcp')
                d = []
                for a in maddr:
                    d += ['tcp:%s:%s:%d' % (a[0], a[1], u) for u in units]
                self.probe_devices(d, nosave=True)
        """
        return True

def main():
    parser = ArgumentParser(add_help=True)
    parser.add_argument('-d', '--debug', help='enable debug logging',
                        action='store_true')
    parser.add_argument('-f', '--force-scan', action='store_true')
    parser.add_argument('-x', '--exit', action='store_true',
                        help='exit on error')

    args = parser.parse_args()
    
    logging.basicConfig(
        filename='/data/home/root/venus.dbus-homedub/sunspec.log', 
        format='%(asctime)s: %(levelname)-8s %(message)s', 
        datefmt="%Y-%m-%d %H:%M:%S", 
        level=logging.INFO)
    """
    logging.basicConfig(filename='sunspec.log', format='%(levelname)-8s %(message)s',
                        level=(logging.DEBUG if args.debug else logging.INFO))
    """
    log.info('----------------------------------------------------------------------------')
    log.info('Program started')
    logging.getLogger('pymodbus.client.sync').setLevel(logging.CRITICAL)
    
    signal.signal(signal.SIGINT, lambda s, f: os._exit(1))
    faulthandler.register(signal.SIGUSR1)
    
    dbus.mainloop.glib.threads_init()
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    mainloop = GLib.MainLoop()
    
    #print(os.path.abspath(__file__), '>creating NetClient(tcp)')
    client = NetClient('tcp')

    client.err_exit = args.exit

    #print(os.path.abspath(__file__), '>calling client.init')
    client.init(args.force_scan)
    #print(os.path.abspath(__file__), '>client.init completed')
    
    #print(os.path.abspath(__file__), '>calling client.update_timer on interval', UPDATE_INTERVAL)

    GLib.timeout_add(UPDATE_INTERVAL, client.update_timer)
    mainloop.run()
    

if __name__ == '__main__':
    main()
