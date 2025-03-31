#!/usr/bin/env python
# vim: ts=2 sw=2 et

# import normal packages
import platform 
import logging
import logging.handlers
import sys
import os
import sys
if sys.version_info.major == 2:
    import gobject
else:
    from gi.repository import GLib as gobject
import sys
import time
import requests # for http GET
import configparser # for config/ini file

# our own packages from victron
sys.path.insert(1, os.path.join(os.path.dirname(__file__), '/opt/victronenergy/dbus-systemcalc-py/ext/velib_python'))
from vedbus import VeDbusService


class DbusHomeWizzardEnergyP1Service:
    def __init__(self, paths, productname='HomeWizard Energy P1', connection='HomeWizard Energy P1 HTTP JSOn service'):
        config = self._getConfig()
        deviceinstance = int(config['DEFAULT']['DeviceInstance'])
        customname = config['DEFAULT']['CustomName']
        role = config['DEFAULT']['Role']

        allowed_roles = ['pvinverter', 'grid']
        if role in allowed_roles:
            servicename = 'com.victronenergy.' + role
        else:
            logging.error("Configured Role: %s is not in the allowed list", role)
            exit()

        if role == 'pvinverter':
            productid = 0xA144
        else:
            productid = 45069

        self._dbusservice = VeDbusService("{}.http_{:02d}".format(servicename, deviceinstance))
        self._paths = paths

        self._dbusservice.add_path('/Mgmt/ProcessName', __file__)
        self._dbusservice.add_path('/Mgmt/ProcessVersion', 'Unknown version, and running on Python ' + platform.python_version())
        self._dbusservice.add_path('/Mgmt/Connection', connection)
    
        # Create the mandatory objects
        self._dbusservice.add_path('/DeviceInstance', deviceinstance)
        self._dbusservice.add_path('/ProductId', productid)
        self._dbusservice.add_path('/DeviceType', 345) # found on https://www.sascha-curth.de/projekte/005_Color_Control_GX.html#experiment - should be an ET340 Engerie Meter
        self._dbusservice.add_path('/ProductName', productname)
        self._dbusservice.add_path('/CustomName', customname)
        self._dbusservice.add_path('/Latency', None)
        self._dbusservice.add_path('/FirmwareVersion', 0.2)
        self._dbusservice.add_path('/HardwareVersion', 0)
        self._dbusservice.add_path('/Connected', 1)
        self._dbusservice.add_path('/Role', role)
        self._dbusservice.add_path('/Position', self._getP1Position()) # normaly only needed for pvinverter
        self._dbusservice.add_path('/Serial', self._getP1Serial())
        self._dbusservice.add_path('/UpdateIndex', 0)
        
        # add path values to dbus
        for path, settings in self._paths.items():
            self._dbusservice.add_path(
                path, settings['initial'], gettextcallback=settings['textformat'], writeable=True, onchangecallback=self._handlechangedvalue)
    
        # last update
        self._lastUpdate = 0
    
        # add _update function 'timer'
        gobject.timeout_add(500, self._update) # pause 500ms before the next request
        
        # add _signOfLife 'timer' to get feedback in log every 5minutes
        gobject.timeout_add(self._getSignOfLifeInterval() * 60 * 1000, self._signOfLife)
    
    def _getP1Serial(self):
        meter_data = self._getP1Data()  
        
        if not meter_data['unique_id']:
            logging.error("Response does not contain 'unique_id' attribute")
            raise ValueError("Response does not contain 'unique_id' attribute")
        
        serial = meter_data['unique_id']
        return serial

    def _getConfig(self):
        if not hasattr(self, '_config'):
            self._config = configparser.ConfigParser()
            self._config.read("%s/config.ini" % (os.path.dirname(os.path.realpath(__file__))))
        return self._config
 
    def _getSignOfLifeInterval(self):
        config = self._getConfig()
        value = config['DEFAULT']['SignOfLifeLog']
        
        if not value: 
            value = 0
        
        return int(value)

    def _getP1Position(self):
        config = self._getConfig()
        value = config['DEFAULT']['Position']
        
        if not value: 
            value = 0
        
        return int(value)

    def _getP1StatusUrl(self):
        config = self._getConfig()
        accessType = config['DEFAULT']['AccessType']
        
        if accessType == 'OnPremise': 
            URL = "http://%s/api/v1/data" % (config['ONPREMISE']['Host'])
        else:
            raise ValueError("AccessType %s is not supported" % (config['DEFAULT']['AccessType']))
        
        return URL
  
    def _getP1Data(self):
        URL = self._getP1StatusUrl()
        meter_r = requests.get(url=URL, timeout=5)
        
        # check for response
        if not meter_r:
            raise ConnectionError("No response from HomeWizard Energy - %s" % (URL))
        
        meter_data = meter_r.json()     
        
        # check for Json
        if not meter_data:
            raise ValueError("Converting response to JSON failed")
        
        return meter_data
  
    def _signOfLife(self):
        logging.info("--- Start: sign of life ---")
        logging.info("Last _update() call: %s" % (self._lastUpdate))
        logging.info("Last '/Ac/Power': %s" % (self._dbusservice['/Ac/Power']))
        logging.info("--- End: sign of life ---")
        return True
 
    def _update(self):   
        try:
            # get data from HW P1
            meter_data = self._getP1Data()
            config = self._getConfig()
            phases = config['DEFAULT']['Phases']

            if phases == '1':
                # send data to DBus for 1 pahse system
                self._dbusservice['/Ac/Power'] = meter_data['active_power_w']
                self._dbusservice['/Ac/L1/Voltage'] = meter_data['active_voltage_l1_v']
                self._dbusservice['/Ac/L1/Current'] = meter_data['active_current_l1_a']
                self._dbusservice['/Ac/L1/Power'] = meter_data['active_power_l1_w']
                self._dbusservice['/Ac/Energy/Forward'] = (meter_data['total_power_import_kwh']/1000)
                self._dbusservice['/Ac/Energy/Reverse'] = (meter_data['total_power_export_kwh']/1000)
                self._dbusservice['/Ac/L1/Energy/Forward'] = (meter_data['total_power_import_kwh']/1000)
                self._dbusservice['/Ac/L1/Energy/Reverse'] = (meter_data['total_power_export_kwh']/1000) 
            if phases == '3':
                # send data to DBus for 3 pahse system
                self._dbusservice['/Ac/Power'] = meter_data['active_power_w']
                self._dbusservice['/Ac/L1/Voltage'] = meter_data['active_voltage_l1_v']
                self._dbusservice['/Ac/L2/Voltage'] = meter_data['active_voltage_l2_v']
                self._dbusservice['/Ac/L3/Voltage'] = meter_data['active_voltage_l3_v']
                self._dbusservice['/Ac/L1/Current'] = meter_data['active_current_l1_a']
                self._dbusservice['/Ac/L2/Current'] = meter_data['active_current_l2_a']
                self._dbusservice['/Ac/L3/Current'] = meter_data['active_current_l3_a']
                self._dbusservice['/Ac/L1/Power'] = meter_data['active_power_l1_w']
                self._dbusservice['/Ac/L2/Power'] = meter_data['active_power_l2_w']
                self._dbusservice['/Ac/L3/Power'] = meter_data['active_power_l3_w']
                self._dbusservice['/Ac/Energy/Forward'] = (meter_data['total_power_import_kwh'] / 1000)
                self._dbusservice['/Ac/Energy/Reverse'] = (meter_data['total_power_export_kwh'] / 1000)

            # logging
            logging.debug("House Consumption (/Ac/Power): %s" % (self._dbusservice['/Ac/Power']))
            logging.debug("House Forward (/Ac/Energy/Forward): %s" % (self._dbusservice['/Ac/Energy/Forward']))
            logging.debug("House Reverse (/Ac/Energy/Reverse): %s" % (self._dbusservice['/Ac/Energy/Reverse']))
            logging.debug("---")
            
            # increment UpdateIndex - to show that new data is available and wrap
            self._dbusservice['/UpdateIndex'] = (self._dbusservice['/UpdateIndex'] + 1) % 256

            # update lastupdate vars
            self._lastUpdate = time.time()
        except (ValueError, requests.exceptions.ConnectionError, requests.exceptions.Timeout, ConnectionError) as e:
            logging.critical('Error getting data from HW P1 - check network or HW P1 status. Setting power values to 0. Details: %s', e, exc_info=e)       
            self._dbusservice['/Ac/L1/Power'] = 0                                       
            self._dbusservice['/Ac/L2/Power'] = 0                                       
            self._dbusservice['/Ac/L3/Power'] = 0
            self._dbusservice['/Ac/Power'] = 0
            self._dbusservice['/UpdateIndex'] = (self._dbusservice['/UpdateIndex'] + 1) % 256        
        except Exception as e:
            logging.critical('Error at %s', '_update', exc_info=e)
        
        # return true, otherwise add_timeout will be removed from GObject - see docs http://library.isr.ist.utl.pt/docs/pygtk2reference/gobject-functions.html#function-gobject--timeout-add
        return True
    
    def _handlechangedvalue(self, path, value):
        logging.debug("someone else updated %s to %s" % (path, value))
        return True # accept the change


def getLogLevel():
    config = configparser.ConfigParser()
    config.read("%s/config.ini" % (os.path.dirname(os.path.realpath(__file__))))
    logLevelString = config['DEFAULT']['LogLevel']
    
    if logLevelString:
        level = logging.getLevelName(logLevelString)
    else:
        level = logging.INFO
        
    return level


def main():
    # configure logging
    logging.basicConfig(format='%(asctime)s,%(msecs)d %(name)s %(levelname)s %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        level=getLogLevel(),
        handlers=[
            logging.FileHandler("%s/current.log" % (os.path.dirname(os.path.realpath(__file__)))),
            logging.StreamHandler()
        ])
 
    try:
        logging.info("Start")
    
        from dbus.mainloop.glib import DBusGMainLoop
        # Have a mainloop, so we can send/receive asynchronous calls to and from dbus
        DBusGMainLoop(set_as_default=True)
        
        # formatting 
        _kwh = lambda p, v: (str(round(v, 2)) + ' kWh')
        _a = lambda p, v: (str(round(v, 1)) + ' A')
        _w = lambda p, v: (str(round(v, 1)) + ' W')
        _v = lambda p, v: (str(round(v, 1)) + ' V')   
        
        # start our main-service
        pvac_output = DbusHomeWizzardEnergyP1Service(
            paths={
                '/Ac/Energy/Forward': {'initial': 0, 'textformat': _kwh}, # energy bought from the grid
                '/Ac/Energy/Reverse': {'initial': 0, 'textformat': _kwh}, # energy sold to the grid
                '/Ac/Power': {'initial': 0, 'textformat': _w},
                
                '/Ac/Current': {'initial': 0, 'textformat': _a},
                '/Ac/Voltage': {'initial': 0, 'textformat': _v},
                
                '/Ac/L1/Voltage': {'initial': 0, 'textformat': _v},
                '/Ac/L2/Voltage': {'initial': 0, 'textformat': _v},
                '/Ac/L3/Voltage': {'initial': 0, 'textformat': _v},
                '/Ac/L1/Current': {'initial': 0, 'textformat': _a},
                '/Ac/L2/Current': {'initial': 0, 'textformat': _a},
                '/Ac/L3/Current': {'initial': 0, 'textformat': _a},
                '/Ac/L1/Power': {'initial': 0, 'textformat': _w},
                '/Ac/L2/Power': {'initial': 0, 'textformat': _w},
                '/Ac/L3/Power': {'initial': 0, 'textformat': _w},
            })
        logging.info('Connected to dbus, and switching over to gobject.MainLoop() (= event based)')
        mainloop = gobject.MainLoop()
        mainloop.run()            
    except (ValueError, requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
        logging.critical('Error in main type %s', str(e))
    except Exception as e:
        logging.critical('Error at %s', 'main', exc_info=e)
        
if __name__ == "__main__":
    main()
