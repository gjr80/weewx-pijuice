"""
juice.py

A WeeWX service to obtain data from a locally connected PiJuice UPS HAT.

Copyright (C) 2021 Gary Roderick                    gjroderick<at>gmail.com

This program is free software: you can redistribute it and/or modify it under
the terms of the GNU General Public License as published by the Free Software
Foundation, either version 3 of the License, or (at your option) any later
version.

This program is distributed in the hope that it will be useful, but WITHOUT ANY
WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A
PARTICULAR PURPOSE.  See the GNU General Public License for more details.

You should have received a copy of the GNU General Public License along with
this program.  If not, see https://www.gnu.org/licenses/.

Version: 0.1.0                                        Date: 2 August 2021

  Revision History
    2 August 2021       v0.1.0
        - initial release


The PiJuice service augments loop packets with operating data from a locally
connected PiJuice UPS HAT. The PiJuice data can be stored in the WeeWX database
by modifying the in-use database schema to include the PiJuice data or,
alternatively, the included archive service can be used to store the PiJuice
data in a separate database.

The preferred method of installing the PiJuice service is using the WeeWX
wee_extension utility. Alternatively the service can be installed and
configured manually. Refer to the readme for detailed installation
instructions.


Abbreviated instructions for use:

1.  Download the latest PiJuice extension package from the PiJuice extension
releases page (https://github.com/gjr80/weewx-pijuice/releases).

2.  Install the PiJuice extension package using the WeeWX wee_extension utility:

    $ wee_extension --install=/var/tmp/pj-x.y.z.tar.gz

    where x.y.z is the extension package version number

3.  Restart WeeWX.

If the PiJuice is installed on the default bus/address WeeWX should augment
loop packets with PiJuice data. Archive records should also include accumulated
PiJuice data.

If the PiJuice is not installed on the default bus/address refer to the
Customisation stanza below or refer to the PiJuice extension Wiki.


Customisation

The operation of the PiJuice service can be customised via a number of config
options under the [PiJuice] stanza in weewx.conf. The following example
[PiJuice] stanza lists the available config options along with a short
explanatory text for each option.

[PiJuice]

    # PiJuice bus number. Integer, optional, default is 1.
    bus = 1

    # PiJuice address. Integer, optional, normally expressed as a two byte
    # hexadecimal number in the format 0xYZ, eg 0x14. Default is 0x14.
    address = 0x14

    # Minimum period in seconds between loop packets containing PiJuice data.
    # Loop packets will still be emitted at the rate set by the in use driver,
    # this setting only affects how often PiJuice data is emitted. Integer,
    # optional, default is 20.
    update_interval = 20

    # Mapping from PiJuice data fields to WeeWX fields. Available PiJuice data
    # fields are:
    #   batt_temp: battery temperature
    #   batt_charge: battery charge percentage
    #   batt_voltage: battery voltage
    #   batt_current: battery current
    #   io_voltage:
    #   io_current:
    #
    # The field map entries use the following format:
    #   WeeWX field name = PiJuice data field name
    # where:
    #   WeeWX field name is the the field name that will appear in the WeeWX
    #   loop packet
    #   PiJuice data field name is one of the available PiJuice data fields
    #
    # The [[field_map]] mapping replaces the default field map. The default
    # field map is represented by the following [[field_map]] stanza:
    [[field_map]]
        ups_temp = batt_temp
        ups_charge = batt_charge
        ups_voltage = batt_voltage
        ups_current = batt_current
        io_voltage = io_voltage
        io_current = io_current

    # Field map extensions are used to modify an existing field map. This can
    # be useful if only a small number of field map entries need to be changed.
    # A commented out example [[field_map_extensions]] stanza is included
    # below. The default field map extension is empty.
    # [[field_map_extensions]]
    #     my_field_name = batt_temp
    #     my_other_field_name = batt_charge

A config reload or a WeeWX restart must be completed if changes are made to
weewx.conf.


PiJuice archive service

The PiJuice archive service is installed but not enabled during installation of
the PiJuice service. To configure and enable the PiJuice archive service refer
to the PiJuice extension wiki.
"""

# python imports
import calendar
import datetime
import logging
import pijuice
import re
import time

# WeeWX imports
import weecfg
import weeutil.logger
import weewx
import weewx.engine
import weewx.units
from weeutil.weeutil import to_int

# setup logging, the Pijuice API operates under Python3 so we don't need to
# worry about supporting WeeWX v3 logging via syslog
log = logging.getLogger(__name__)


# version number of this script
pj_service_version = '0.1.0'

# define schema for the PiJuice archive table
pj_table = [('dateTime', 'INTEGER NOT NULL UNIQUE PRIMARY KEY'),
            ('usUnits', 'INTEGER NOT NULL'),
            ('interval', 'INTEGER NOT NULL'),
            ('ups_temp', 'REAL'),
            ('ups_charge', 'REAL'),
            ('ups_voltage', 'REAL'),
            ('ups_current', 'REAL'),
            ('io_voltage', 'REAL'),
            ('io_current', 'REAL')
            ]
pj_day_summaries = [(e[0], 'scalar') for e in pj_table if e[0] not in ('dateTime', 'usUnits', 'interval')]
pj_schema = {
    'table': pj_table,
    'day_summaries': pj_day_summaries
}

# PiJuice error messages with plain English meaning
pj_errors = {'NO_ERROR': 'No error',
             'COMMUNICATION_ERROR': 'Communication error',
             'DATA_CORRUPTED': 'Corrupt data',
             'WRITE_FAILED': 'Write failed',
             'BAD_ARGUMENT': 'Invalid argument',
             'INVALID_DUTY_CYCLE': 'Invalid duty cycle',
             'INVALID_SECOND': 'Invalid second',
             'INVALID_MINUTE': 'Invalid minute',
             'INVALID_HOUR': 'Invalid hour',
             'INVALID_WEEKDAY': 'Invalid week day',
             'INVALID_DAY': 'Invalid day',
             'INVALID_MONTH': 'Invalid month',
             'INVALID_YEAR': 'Invalid year',
             'INVALID_SUBSECOND': 'Invalid sub-second',
             'INVALID_MINUTE_PERIOD': 'Invalid minute period',
             'INVALID_DAY_OF_MONTH': 'Invalid day of month',
             'UNKNOWN_DATA': 'Unknown data',
             'INVALID_USB_MICRO_CURRENT_LIMIT': 'Invalid microUSB current limit',
             'INVALID_USB_MICRO_DPM': 'Invalid microUSB Dynamic Power Management (DPM) loop',
             'INVALID_CONFIG': 'Invalid configuration',
             'INVALID_PERIOD': 'Invalid period'
             }
# PiJuice status condition names with plain English equivalents
pj_status = {'isFault': 'Fault exists',
             'isButton': 'Button events exist',
             'battery': 'Battery',
             'powerInput': 'µUSB power input',
             'powerInput5vIo': '5V GPIO power input'
             }
# PiJuice states with plain English equivalents
pj_states = {'NORMAL': 'Normal',
             'PRESENT': 'Present',
             'NOT_PRESENT': 'Not present',
             'CHARGING_FROM_IN': 'Charging from µUSB power input',
             'CHARGING_FROM_5V_IO': 'Charging from 5V GPIO power input',
             'BAD': 'Bad',
             'WEAK': 'Weak'
             }
# PiJuice fault status names with plain English equivalents
pj_fault_status = {'button_power_off': 'Power off triggered by button press',
                   'forced_power_off': 'Forced power off caused by loss of energy',
                   'forced_sys_power_off': 'Forced system switch turn off caused by loss of energy',
                   'watchdog_reset': 'Watchdog reset',
                   'battery_profile_invalid': 'Battery profile is invalid',
                   'charging_temperature_fault': 'Battery charging temperature fault'
                   }
# PiJuice fault states with plain English equivalents
pj_fault_states = {'NORMAL': 'Normal',
                   'SUSPEND': 'Suspend',
                   'COOL': 'Cool',
                   'WARM': 'Warm'
                   }
# map class PiJuice properties to PiJuice fields
api_lookup = {'batt_temp': 'battery_temperature',
              'batt_charge': 'charge_level',
              'batt_voltage': 'battery_voltage',
              'batt_current': 'battery_current',
              'io_voltage': 'io_voltage',
              'io_current': 'io_current'
              }


# ============================================================================
#                               class PiJuiceService
# ============================================================================

class PiJuiceService(weewx.engine.StdService):
    """Service that adds PiJuice UPS data to loop packets.

    The PiJuiceService interrogates a locally connected PiJuice UPS and adds
    various UPS parameters to loop packets. The service is bound the the
    NEW_LOOP_PACKET event and upon receipt of a new loop packet the PiJuice is
    interrogated via the PiJuice API. The API results are decoded, mapped as
    per the field map and the mapped fields added to the loop packet. As the
    PiJuice is connected directly to the Raspberry Pi there should be no delays
    in interrogating the PiJuice API that would otherwise block the WeeWX main
    loop.
    """

    # TODO. More convenient to place these constants further up the code tree?
    # default field map
    default_field_map = {
        'ups_temp': 'batt_temp',
        'ups_charge': 'batt_charge',
        'ups_voltage': 'batt_voltage',
        'ups_current': 'batt_current',
        'io_voltage': 'io_voltage',
        'io_current': 'io_current'
    }

    # default interval between PiJuice data updates
    default_update_interval = 20

    def __init__(self, engine, config_dict):
        # initialize my superclass
        super(PiJuiceService, self).__init__(engine, config_dict)

        # get our PiJuice config dictionary
        pj_config_dict = config_dict.get('PiJuice', {})

        # construct the field map, first obtain the field map, if it exists,
        # from our config
        field_map = pj_config_dict.get('field_map')
        # if we have no field map then use the default
        if field_map is None:
            # make a copy of the default field map as we may well make changes
            field_map = dict(PiJuiceService.default_field_map)
        # obtain any field map extensions from our config
        extensions = field_map.get('field_map_extensions', {})
        # If a user wishes to map a PiJuice field differently to that in the
        # default map they can include an entry in field_map_extensions, but if
        # we just update the field map dict with the field map extensions that
        # could leave two entries for that PiJuice field in the field map; the
        # original field map entry as well as the entry from the extended map.
        # So if we have field_map_extensions we need to first go through the
        # field map and delete any entries that map PiJuice fields that are
        # included in the field_map_extensions.

        # we only need process the field_map_extensions if we have any entries
        if len(extensions) > 0:
            # first make a copy of the field map because we cannot both iterate
            # over its contents and possibly change it
            field_map_copy = dict(field_map)
            # iterate over each key, value pair in the copy of the field map
            for k, v in field_map_copy.items():
                # if the 'value' (ie the PiJuice field) is in the field map
                # extensions we will be mapping that PiJuice field elsewhere so
                # pop that field map entry out of the field map so we don't end
                # up with multiple mappings for that field
                if v in extensions.values():
                    # pop the field map entry
                    _dummy = field_map.pop(k)
            # now we can update the field map with the extensions
            field_map.update(extensions)
        # we now have our final field map
        self.field_map = field_map

        # Create the set of API calls required to populate all PiJuice fields
        # used in the field map, we do this so that we only make those calls
        # that provide the data in which we are interested. We could use a set
        # comprehension to do this but we need to log any fields for which no
        # supporting API call exists.
        # first create any empty set to hold our API calls
        _api_calls = set()
        # iterate over the PiJuice fields for which we require data
        for field in self.field_map.values():
            # obtain the API call to be used for this field
            api_call = api_lookup.get(field)
            if api_call is not None:
                # we have an API call so add it to our set of API calls
                _api_calls.add(api_call)
            else:
                # we have not API call for this field, log it and continue
                log.warning("No API call found for PiJuice field '%s'. "
                            "Field '%s' will be ignored." % (field, field))
        # save our set of API calls
        self.api_calls = _api_calls
        # obtain the interval between PiJuice updates
        self.update_interval = to_int(pj_config_dict.get('update_interval',
                                                         PiJuiceService.default_update_interval))
        # property containing the time of last update, set to None to indicate
        # no last update
        self.last_update = None
        # get a PiJuice object so we can access the PiJuice API
        self.pj = PiJuiceApi(**pj_config_dict)
        # Exercise our PiJuice object so we know it is present and functioning.
        # Obtain the PiJuice status, if it contains an error field then we
        # can't go on. Log the error, tidy ourself up and return before binding
        # to any events. This effectively disables the PiJuice service.
        _status = self.pj.status
        if 'error' in _status:
            log.error("Error encountered loading PiJuiceService.")
            log.error("  PiJuice at bus '%d' address '0x%02X' returned error: '%s'" % (self.pj.bus,
                                                                                       self.pj.address,
                                                                                       _status['error']))
            self.pj = None
            return
        # we have a functioning PiJuice so bind our self to the NEW_LOOP_PACKET
        # event
        self.bind(weewx.NEW_LOOP_PACKET, self.new_loop_packet)

    def new_loop_packet(self, event):
        """Update the loop packet with PiJuice data.

        Obtain updated PiJuice data if the update interval has passed since the
        last update. Update the loop packet with the updated PiJuice data.
        """

        # obtain the current epoch timestamp
        now = int(time.time())
        # Is this the first update or has the update interval passed since the
        # last update. If so obtain updated data an update the loop packet
        # otherwise there is nothing to do.
        if self.last_update is None or self.last_update + self.update_interval <= now:
            # we need to update
            # first get updated PiJuice data
            pj_data = self.get_pj_data()
            # save the time of this update
            self.last_update = now
            # update the loop packet with the PiJuice data
            event.packet.update(pj_data)

    def get_pj_data(self):
        """Get updated PiJuice data via the PiJuice API.

        We only need data for the PiJuice fields included in the field map.
        Iterate over these fields and make the appropriate PiJuice API call to
        obtain the data for the PiJuice field concerned. Assemble the
        accumulated data in a dict, keyed by PiJuice field name, using WeeWX
        METRIC unit system units.

        Returns a dict, keyed by PiJuice field name containing the data for
        each field.
        """

        # initialise a dict to hold our PiJuice data
        pj_data = dict()
        # TODO. Need to make use of self.api_calls
        # iterate over the PiJuice fields used in the field map and obtain the
        # relevant date from the PiJuice API
        for field in self.field_map.values():
            # get the class piJuice property that will provide the data for the
            # field concerned
            fn = api_lookup.get(field)
            # if we have a property use it to get the current data, otherwise
            # skip the field and log the lack of a property
            if fn is not None:
                # we have a property, so get the data
                data = getattr(self.pj, fn)
                # update the PiJuice data dict with the data
                pj_data.update({field: data})
            else:
                # log the lack of a property and the skipping of the field
                log.debug("Skipping field '%s': "
                          "No API function found for PiJuice field '%s'" % (field, field))
        # return the accumulated data
        return pj_data


# ==============================================================================
#                            class PiJuiceArchive
# ==============================================================================

class PiJuiceArchive(weewx.engine.StdService):
    """Service to store PiJuice data in a separate database.

     This service operates as a slimmed down archive service that stores
     PiJuice data in a separate database. the PiJuiceArchive service operates
     much the same as StdArchive but without the need to manage an accumulator
     and emit software archive records. PiJuiceArchive binds to the
     NEW_ARCHIVE_RECORD event and adds the relevant PiJuice fields from the
     archive record to the PiJuice database. the user can then use the PiJuice
     data in reports and plots by specifying the appropriate binding used by
     the PiJuice database.
    """

    def __init__(self, engine, config_dict):
        # initialise our superclass
        super(PiJuiceArchive, self).__init__(engine, config_dict)

        # log our version
        log.info("PiJuiceArchive version %s" % pj_service_version)
        # Extract our binding from the WeeWX-Saratoga section of the config file. If
        # it's missing, fill with a default.
        if 'PiJuice' in config_dict:
            self.data_binding = config_dict['PiJuice'].get('data_binding',
                                                           'pj_binding')
        else:
            self.data_binding = 'pj_binding'

        # extract the WeeWX binding for use when we check the need for backfill
        # from the WeeWX archive
        if 'StdArchive' in config_dict:
            self.data_binding_wx = config_dict['StdArchive'].get('data_binding',
                                                                 'wx_binding')
        else:
            self.data_binding_wx = 'wx_binding'

        # setup our database if needed
        self.setup_database()

        # set the unit groups for our obs
        weewx.units.obs_group_dict["ups_temp"] = "group_temperature"
        weewx.units.obs_group_dict["ups_charge"] = "group_percent"
        weewx.units.obs_group_dict["ups_voltage"] = "group_voltage"
        weewx.units.obs_group_dict["ups_current"] = "group_current"
        weewx.units.obs_group_dict["io_voltage"] = "group_voltage"
        weewx.units.obs_group_dict["io_current"] = "group_current"

        # bind ourselves to NEW_ARCHIVE_RECORD event
        self.bind(weewx.NEW_ARCHIVE_RECORD, self.new_archive_record)

    def new_archive_record(self, event):
        """Save data to the PiJuice archive.

        Use our db manager's addRecord method to save the relevant archive
        record data fields to the PiJuice archive.
        """

        # get our db manager
        dbmanager = self.engine.db_binder.get_manager(self.data_binding)
        # now add the record to the archive, this will also indirectly take
        # care of updating any daily summaries
        dbmanager.addRecord(event.record)

    def setup_database(self):
        """Setup the PiJuice database."""

        # obtain a db manager for the PiJuice database, this will create the
        # database if it doesn't exist
        dbmanager = self.engine.db_binder.get_manager(self.data_binding,
                                                      initialize=True)
        log.info("Using binding '%s' to database '%s'" % (self.data_binding,
                                                          dbmanager.database_name))

        # TODO. Is this correct, looks like a hangover from a more complex arrangement
#        # Check if we have any historical data to bring in from the WeeWX
#        # archive.
#        # first get a dbmanager for the WeeWX archive
#        dbmanager_wx = self.engine.db_binder.get_manager(self.data_binding_wx,
#                                                         initialize=False)
#
        # backfill the PiJuice daily summaries
        log.info("Starting backfill of '%s' daily summaries" % dbmanager.database_name)
        t1 = time.time()
#        nrecs, ndays = dbmanager_wx.backfill_day_summary()
        nrecs, ndays = dbmanager.backfill_day_summary()
        tdiff = time.time() - t1
        if nrecs:
            log.info("Processed %d records to backfill %d "
                     "daily summaries in %.2f seconds" % (nrecs,
                                                        ndays,
                                                        tdiff))
        else:
            log.info("Daily summaries up to date.")


# ============================================================================
#                              class PiJuiceApi
# ============================================================================

class PiJuiceApi(object):
    """Class to obtain data from a PiJuice UPS.

    Wrapper class to access the PiJuice API.

    The class requires a a bus number and address to access the PiJuice.

    Each PiJuice data point has been implemented as a class property with each
    property making the appropriate API call to obtain the relevant data. The
    property returns data in the applicable WeeWX METRIC unit system unit. If
    data is not available or an error code string returned then the property
    returns a dict with the error code string in field 'error'.
    """

    def __init__(self, bus=1, address=0x14, **kwargs):
        # Obtain the bus to be used, do some simple checking in case we were
        # passed a string. If we can't get an integer bus then raise the
        # exception
        try:
            _bus = int(bus, 0)
        except TypeError:
            # it could be we already have an integer
            try:
                _bus = int(bus)
            except (ValueError, TypeError) as e:
                raise Exception("Invalid bus '%s' specified. Exiting." % (bus,)) from e
        except Exception as e:
            raise Exception("Invalid bus '%s' specified. Exiting." % (bus,)) from e
        # obtain the address to be used, first try converting to an int
        # assuming an explicit base
        try:
            _address = int(address, 0)
        except TypeError:
            # it could be we already have an integer
            try:
                _address = int(address)
            except (ValueError, TypeError) as e:
                raise Exception("Invalid address '%s' specified. Exiting." % (address,)) from e
        except Exception as e:
            raise Exception("Invalid address '%s' specified. Exiting." % (address,)) from e
        self.bus = _bus
        self.address = _address
        pj = pijuice.PiJuice(self.bus, self.address)
        self.status_iface = pj.status
        self.rtc_alarm_iface = pj.rtcAlarm

    @staticmethod
    def get_data_or_error(resp):
        """Given a PiJuice API response extract valid data or an error.

        A PiJuice API response is a dict keyed as follows:
        'error': a string containing an error code string, mandatory.
        'data': the data returned by the API, optional. Only included if there is
                no error (ie 'error' == 'NO_ERROR')

        If the API response contains data return the data otherwise return the
        error code string in a dict keyed by 'error'.
        """

        return resp.get('data', {'error': resp.get('error')})

    @property
    def status(self):
        """Obtain the PiJuice status."""

        return self.get_data_or_error(self.status_iface.GetStatus())

    @property
    def charge_level(self):
        """Obtain the PiJuice battery charge level.

        Obtain the PiJuice battery charge level via the API. The API response
        'data' field is returned if it exists, otherwise a dict keyed by
        'error' and containing the error string is returned. The battery charge
        value is an integer percentage.
        """

        return self.get_data_or_error(self.status_iface.GetChargeLevel())

    @property
    def fault_status(self):
        return self.get_data_or_error(self.status_iface.GetFaultStatus())

    @property
    def button_events(self):
        return self.get_data_or_error(self.status_iface.GetButtonEvents())

    @property
    def battery_temperature(self):
        """Obtain the PiJuice battery temperature.

        Obtain the PiJuice battery temperature via the API. The API response
        'data' field contains the battery temperature in C. If this value
        exists it is returned, otherwise a dict keyed by 'error' and containing
        the error string is returned.
        """

        return self.get_data_or_error(self.status_iface.GetBatteryTemperature())

    @property
    def battery_voltage(self):
        """Obtain the PiJuice battery voltage.

        Obtain the PiJuice battery voltage via the API. The API response 'data'
        field contains the battery voltage in mV. If this value exists it is
        converted from mV to V and is returned, otherwise a dict keyed by
        'error' and containing the error string is returned.
        """

        v = self.status_iface.GetBatteryVoltage()
        if 'data' in v:
            v['data'] = v['data'] / 1000.0
        return self.get_data_or_error(v)

    @property
    def battery_current(self):
        """Obtain the PiJuice battery current.

        Obtain the PiJuice battery current via the API. The API response 'data'
        field contains the battery current in mA. If this value exists it is
        converted from mA to A and is returned, otherwise a dict keyed by
        'error' and containing the error string is returned.
        """

        a = self.status_iface.GetBatteryCurrent()
        if 'data' in a:
            a['data'] = a['data'] / 1000.0
        return self.get_data_or_error(a)

    @property
    def io_voltage(self):
        """Obtain the PiJuice IO voltage.

        Obtain the PiJuice IO voltage via the API. The API response 'data'
        field contains the IO voltage in mV. If this value exists it is
        converted from mV to V and is returned, otherwise a dict keyed by
        'error' and containing the error string is returned.
        """

        v = self.status_iface.GetIoVoltage()
        if 'data' in v:
            v['data'] = v['data'] / 1000.0
        return self.get_data_or_error(v)

    @property
    def io_current(self):
        """Obtain the PiJuice IO current.

        Obtain the PiJuice IO current via the API. The API response 'data'
        field contains the IO current in mA. If this value exists it is
        converted from mA to A and is returned, otherwise a dict keyed by
        'error' and containing the error string is returned.
        """

        a = self.status_iface.GetIoCurrent()
        if 'data' in a:
            a['data'] = a['data'] / 1000.0
        return self.get_data_or_error(a)

    @property
    def led_state(self):
        return self.get_data_or_error(self.status_iface.GetLedState())

    @property
    def led_blink(self):
        return self.get_data_or_error(self.status_iface.GetLedBlink())

    @property
    def io_digital_input(self):
        return self.get_data_or_error(self.status_iface.GetIoDigitalInput())

    @property
    def io_analog_input(self):
        return self.get_data_or_error(self.status_iface.GetIoDigitalOutput())

    @property
    def io_pwm(self):
        return self.get_data_or_error(self.status_iface.GetIoPWM())

    @property
    def rtc_time(self):
        return self.get_data_or_error(self.rtc_alarm_iface.GetTime())


# ============================================================================
#                             class DirectPiJuice
# ============================================================================

class DirectPiJuice(object):
    """Class to interact with PiJuice service when run directly."""

    # datetime constructor arguments we need to filter from the RTC time
    dt_args = ['year', 'month', 'day', 'hour', 'minute', 'second']

    def __init__(self, args, service_dict):
        """Initialise a DirectPiJuice object."""

        # save the argparse arguments and service dict
        self.args = args
        self.service_dict = service_dict
        # override/set bus number to use if specified via command line
        if self.args.bus:
            self.service_dict['bus'] = self.args.bus
        # override/set address to use if specified via command line
        if self.args.address:
            self.service_dict['address'] = self.args.address
        # get a PiJuiceApi object so we can query the PiJuice API
        self.pj = PiJuiceApi(**service_dict)

    def process_options(self):
        """Call the appropriate method based on the argparse options."""

        if self.args.test_service:
            # run the service with simulator
            self.test_service()
        elif self.args.status:
            # get the PiJuice status
            self.get_status()
        elif self.args.fault:
            # get any PiJuice faults
            self.get_fault()
        elif self.args.battery:
            # get the PiJuice battery state
            self.get_battery()
        elif self.args.io:
            # get PiJuice input state
            self.get_io()
        elif self.args.rtc:
            # get PiJuice RTC setting
            self.get_rtc()
        elif self.args.map:
            self.display_field_map()
        else:
            # no argument was specified that we know about
            return
        exit(0)

    def test_service(self):
        """Test the PiJuice service.

        Uses a dummy engine/simulator to generate arbitrary loop packets for
        augmenting. Use a 10 second loop interval so we don't get too many bare
        packets.
        """

        log.info("Testing PiJuice service...")
        # Create a dummy config so we can stand up a dummy engine with a dummy
        # simulator emitting arbitrary loop packets. Include the PiJuice
        # service and StdPrint, StdPrint will take care of printing our loop
        # packets (no StdArchive so loop packets only, no archive records). We
        # include the WeeWX simulator as the driver though it is not actually
        # used other than to satisfy the WeeWX engine initialisation process
        # (we will manually emit a simple loop packet).
        config = {
            'Station': {
                'station_type': 'Simulator',
                'altitude': [0, 'meter'],
                'latitude': 0,
                'longitude': 0},
            'Simulator': {
                'driver': 'weewx.drivers.simulator',
                'mode': 'simulator'},
            'PiJuice': self.service_dict,
            'Engine': {
                'Services': {
                    'data_services': 'user.juice.PiJuiceService',
                    'report_services': 'weewx.engine.StdPrint'}}}
        # assign our dummyTemp field to a unit group so unit conversion works
        # properly
        weewx.units.obs_group_dict['dummyTemp'] = 'group_temperature'
        # wrap in a try..except in case there is an error
        engine = None
        try:
            # create a dummy engine
            engine = weewx.engine.StdEngine(config)
            # Our PiJuice service will have been instantiated by the engine
            # during its startup. Whilst access to the service is not normally
            # required we require access here so we can obtain some info about
            # the station we are using for this test. The engine does not
            # provide a ready means to access that PiJuice service so we can do
            # a bit of guessing and iterate over all of the engine's services
            # and select the one that has a 'pj' property. Unlikely to cause a
            # problem since there are only two services in the dummy engine.
            pj_svc = None
            for svc in engine.service_obj:
                if hasattr(svc, 'pj'):
                    pj_svc = svc
            if pj_svc is not None:
                # identify the PiJuice being used
                print()
                print("Interrogating PiJuice at bus '%d' address '0x%02X'" % (pj_svc.pj.bus,
                                                                              pj_svc.pj.address))
            print()
            if pj_svc.pj is None:
                print("Error encountered loading PiJuiceService.")
                print("  Perhaps the PiJuice is not installed or an incorrect bus or address was specified.")
                print("  Refer to the WeeWX log for details.")
                raise KeyboardInterrupt
            while True:
                # create an arbitrary loop packet, all it needs is a timestamp, a
                # defined unit system and a token obs
                packet = {'dateTime': int(time.time()),
                          'usUnits': weewx.US,
                          'dummyTemp': 96.3
                          }
                # send out a NEW_LOOP_PACKET event with the dummy loop packet
                # to trigger the PiJuice service to augment the loop packet
                engine.dispatchEvent(weewx.Event(weewx.NEW_LOOP_PACKET,
                                                 packet=packet,
                                                 origin='software'))
                # sleep for a bit to emulate the simulator
                time.sleep(10)
        except KeyboardInterrupt:
            msg = "PiJuice service testing complete"
            print()
            print(msg)
            log.info(msg)
        finally:
            if engine is not None:
                engine.shutDown()

    def get_status(self):
        """Display the PiJuice status."""

        # get the PiJuice status
        resp = self.pj.status
        print()
        print("PiJuice status:")
        # If the API encountered an error when obtaining the PiJuice status
        # there will be an 'error' field in the API response. If there was no
        # error display the PiJuice status. Otherwise display the error in
        # formatted text or as the raw error string.
        if 'error' not in resp:
            # iterate over the response fields
            for key, value in resp.items():
                # display the raw error string or a formatted version
                if self.args.raw:
                    # --raw was set so display the raw status string
                    print("%16s: %s" % (key, value))
                else:
                    # --raw was not set so display a formatted status string
                    print("%21s: %s" % (pj_status.get(key, key),
                                        pj_states.get(value, value)))
        else:
            # we have an error, display it
            print(self.display_error(resp['error']))
        return

    def get_fault(self):
        """Display the PiJuice fault status."""

        # get the fault status
        resp = self.pj.fault_status
        print()
        print("PiJuice fault status:")
        # If the API encountered an error when obtaining the PiJuice fault
        # status there will be an 'error' field in the API response. If there
        # was no error display the PiJuice fault status. Otherwise display the
        # error in formatted text or as the raw error string.
        if 'error' not in resp:
            # iterate over the response fields
            for key, value in resp.items():
                # display the raw error string or a formatted version
                if self.args.raw:
                    # --raw was set so display the raw fault status string
                    print("%28s: %s" % (key, value))
                else:
                    # --raw was not set so display a formatted fault status
                    # string
                    print("%56s: %s" % (pj_fault_status.get(key, key),
                                        pj_fault_states.get(value, value)))
        else:
            # we have an error, display it
            print(self.display_error(resp['error']))
        return

    def get_battery(self):
        """Display the PiJuice battery state.

        This a composite picture built from several API calls.
        """

        # get the battery charge level
        charge = self.pj.charge_level
        # get the battery voltage.
        voltage = self.pj.battery_voltage
        # get the battery current
        current = self.pj.battery_current
        # get the battery temperature
        temp = self.pj.battery_temperature
        # now display the accumulated data
        print()
        print("PiJuice battery state:")
        # charge could be an integer (%) or an error code, try formatting
        # as an integer but be prepared to catch an exception if this fails
        ch_error = None
        if not hasattr(charge, 'keys'):
            try:
                print("%12s: %d%%" % ('Charge', charge))
            except TypeError:
                # we couldn't format as an integer so format as a string
                print("%12s: %s" % ('Charge', charge))
        elif 'error' in charge:
            ch_error = self.display_error(charge['error'])
        # voltage could be an integer in mV or an error code, try
        # converting to V and formatting as a float but be prepared to
        # catch an exception if this fails
        v_error = None
        if not hasattr(voltage, 'keys'):
            try:
                print("%12s: %.3fV" % ('Voltage', voltage / 1000.0))
            except TypeError:
                # we couldn't convert to V and format as a float so format as a
                # string
                print("%12s: %s" % ('Voltage', voltage))
        elif 'error' in voltage:
            v_error = self.display_error(voltage['error'])
        # current could be an integer in mA or an error code, try
        # converting to A and formatting as a float but be prepared to
        # catch an exception if this fails
        c_error = None
        if not hasattr(current, 'keys'):
            try:
                print("%12s: %.3fA" % ('Current', current / 1000.0))
            except TypeError:
                # we couldn't convert to A and format as a float so format as a
                # string
                print("%12s: %s" % ('Current', current))
        elif 'error' in current:
            c_error = self.display_error(current['error'])
        # temperature could be an integer degrees C or an error code, try
        # formatting as an integer but be prepared to catch an exception if
        # this fails
        t_error = None
        if not hasattr(temp, 'keys'):
            try:
                print(u"%12s: %d\xb0C" % ('Temperature', temp))
            except TypeError:
                # we couldn't format as an integer so format as a string
                print("%12s: %s" % ('Temperature', temp))
        elif 'error' in temp:
            t_error = self.display_error(temp['error'])
        # now check if we had any errors and if so print them
        for st in [s for s in (ch_error, v_error, c_error, t_error) if s is not None]:
            print(st)
        return

    def get_io(self):
        """Display the PiJuice input state.

        This a composite picture built from several API calls.
        """

        # get the input voltage
        voltage = self.pj.io_voltage
        # get the input current
        current = self.pj.io_current
        # now display the accumulated data
        print()
        print("PiJuice input state:")
        # voltage could be an integer in mV or an error code, try
        # converting to V and formatting as a float but be prepared to
        # catch an exception if this fails
        v_error = None
        if not hasattr(voltage, 'keys'):
            try:
                print("%12s: %.3fV" % ('Voltage', voltage / 1000.0))
            except TypeError:
                # we couldn't convert to V and format as a float so format as a
                # string
                print("%12s: %s" % ('Voltage', voltage))
        elif 'error' in voltage:
            v_error = self.display_error(voltage['error'])
        # current could be an integer in mA or an error code, try
        # converting to A and formatting as a float but be prepared to
        # catch an exception if this fails
        c_error = None
        if not hasattr(current, 'keys'):
            try:
                print("%12s: %.3fA" % ('Current', current / 1000.0))
            except TypeError:
                # we couldn't convert to A and format as a float so format as a
                # string
                print("%12s: %s" % ('Current', current))
        elif 'error' in current:
            c_error = self.display_error(current['error'])
        # now check if we had any errors and if so print them
        for st in [s for s in (v_error, c_error) if s is not None]:
            print(st)
        return

    def get_rtc(self):
        """Display PiJuice RTC date-time."""

        # Get the RTC time. This will return a dict of date-time components
        # or an error message string.
        resp = self.pj.rtc_time
        print()
        # If the API encountered an error when obtaining the PiJuice fault
        # status there will be an 'error' field in the API response. If there
        # was no error display the PiJuice fault status. Otherwise display the
        # error in formatted text or as the raw error string.
        if 'error' not in resp:
            if self.args.raw:
                print("PiJuice RTC date-time (UTC):")
                # We only need print the returned date-time components, but we
                # could have an error message instead. Wrap in a try..except
                # statement and be prepared to catch the exception if we strike
                # an error message.
                try:
                    for key, value in resp.items():
                        print("%16s: %s" % (key, value))
                except AttributeError:
                    # utc_date_time was not a dict so likely just an error
                    # message. Print the error message as is.
                    print("PiJuice RTC date-time (UTC): %s" % resp)
            else:
                # We need to display the RTC time in a more human readable
                # format. We now have the components (hour, minute, etc) of the
                # RTC date-time albeit in UTC. We need to obtain a python
                # datetime object from this data so we can format the date-time
                # string as required and also convert to local time.

                # first filter from the RTC date-time data the fields that we
                # will use we need to construct a datetime object
                utc_dt_dict = {k: v for k, v in resp.items() if k in DirectPiJuice.dt_args}
                # construct our datetime object, remember this is in UTC
                utc_date_time_dt = datetime.datetime(**utc_dt_dict)
                # now we can convert to a timestamp representing the correct local
                # time
                date_time_ts = calendar.timegm(utc_date_time_dt.timetuple())
                # and a local time datetime object...
                date_time_dt = datetime.datetime.fromtimestamp(date_time_ts)
                # construct the formatted date-time string to use in our display
                # first UTC
                utc_date_time_str = utc_date_time_dt.strftime("%A %-d %B %Y %H:%M:%S")
                # now local time
                date_time_str = date_time_dt.strftime("%A %-d %B %Y %H:%M:%S")
                # and finally print the various date-time strings
                print("PiJuice RTC date-time:")
                print("%10s: %s (%s)" % ('GMT',
                                         utc_date_time_str,
                                         date_time_ts))
                print("%10s: %s" % ('Local', date_time_str))
        else:
            # we have an error, display it
            print(self.display_error(resp['error']))
        return

    @staticmethod
    def display_field_map():
        """Display the default field map."""

        # obtain a copy of the default field map, we need a copy so we can
        # augment it with the battery state map
        field_map = dict(PiJuiceService.default_field_map)
        print()
        print("PiJuice service default field map:")
        print("(format is WeeWX field name: PiJuice field name)")
        print()
        # obtain a list of naturally sorted dict keys
        keys_list = natural_sort_keys(field_map)
        # iterate over the sorted keys and print the key and item
        for key in keys_list:
            print("    %23s: %s" % (key, field_map[key]))

    def display_error(self, raw_error_string):
        """Display a PiJuice API error string.
        
        Simple routine to display a PiJuice API error string either as a raw 
        string as returned by the API or as a formatted string.
        """

        # are we displaying the raw error string or formatted text
        if self.args.raw:
            # --raw was set so display the raw error string
            return "Error: %s" % raw_error_string
        else:
            # --raw was not set so display the formatted error string
            return "Error: %s (%s)" % (pj_errors.get(raw_error_string),
                                       raw_error_string)


# ============================================================================
#                             Utility functions
# ============================================================================

def natural_sort_keys(source_dict):
    """Return a naturally sorted list of keys for a dict."""

    def atoi(text):
        return int(text) if text.isdigit() else text

    def natural_keys(text):
        """Natural key sort.

        Allows use of key=natural_keys to sort a list in human order, eg:
            alist.sort(key=natural_keys)

        http://nedbatchelder.com/blog/200712/human_sorting.html (See
        Toothy's implementation in the comments)
        """

        return [atoi(c) for c in re.split(r'(\d+)', text.lower())]

    # create a list of keys in the dict
    keys_list = list(source_dict.keys())
    # naturally sort the list of keys where, for example, xxxxx16 appears in the
    # correct order
    keys_list.sort(key=natural_keys)
    # return the sorted list
    return keys_list


# ============================================================================
#                                   main()
# ============================================================================

# To test the notification functions of the AggregateNotification service use
# one of the following commands (depending on your WeeWX install). For setup.py
# installs use:
#
#   $ PYTHONPATH=/home/weewx/bin python -m user.juice
#
# or for package installs use:
#
#   $ PYTHONPATH=/usr/share/weewx python -m user.juice
#
# The above commands will display details of available command line options.
#
# Note. Whilst this test may be run independently of WeeWX the service still
# requires WeeWX and it's dependencies be installed. Consequently, if
# WeeWX 4.0.0 or later is installed the driver must be run under the same
# Python version as WeeWX uses. This means that on some systems 'python' in the
# above commands may need to be changed to 'python2' or 'python3'.

def main():
    """This section is used to test the notification functions of the
    AggregateNotification service. It uses a modified xtype that is guaranteed
    to trigger a notification.

    You will need a valid weewx.conf configuration file with an
    [AggregateNotification] stanza that has been set up as described at the top
    of this file.
    """

    import argparse

    usage = """python -m user.juice --help
       python -m user.juice --version
       python -m user.juice --get-status [CONFIG_FILE|--config=CONFIG_FILE]
       python -m user.juice --get-faults [CONFIG_FILE|--config=CONFIG_FILE]
       python -m user.juice --get-battery [CONFIG_FILE|--config=CONFIG_FILE]
       python -m user.juice --get-input [CONFIG_FILE|--config=CONFIG_FILE]
       python -m user.juice --get-time [CONFIG_FILE|--config=CONFIG_FILE]
       python -m user.juice --default-map [CONFIG_FILE|--config=CONFIG_FILE]
       
    Arguments:

       CONFIG_FILE: Path and file name of the WeeWX configuration file to be used. 
                    Default is weewx.conf."""
    description = 'Test the pijuice service.'
    epilog = """You must ensure the WeeWX modules are in your PYTHONPATH. For example:

PYTHONPATH=/home/weewx/bin python -m user.juice --help
"""

    # create a command line parser
    parser = argparse.ArgumentParser(usage=usage,
                                     description=description,
                                     epilog=epilog,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--version', dest='version', action='store_true',
                        help='display pijuice service version number')
    parser.add_argument("--config", dest="config_path", metavar="CONFIG_FILE",
                        help="Use configuration file CONFIG_FILE.")
    parser.add_argument("config_pos", nargs='?', help=argparse.SUPPRESS),
    parser.add_argument("--test-service", dest="test_service", action='store_true',
                        help="Test the pijuice service.")
    parser.add_argument("--get-status", dest="status", action='store_true',
                        help="Display PiJuice status.")
    parser.add_argument("--get-faults", dest="fault", action='store_true',
                        help="Display PiJuice fault status.")
    parser.add_argument("--get-battery", dest="battery", action='store_true',
                        help="Display PiJuice battery state.")
    parser.add_argument("--get-input", dest="io", action='store_true',
                        help="Display PiJuice input state.")
    parser.add_argument("--get-time", dest="rtc", action='store_true',
                        help="Display PiJuice RTC time.")
    parser.add_argument('--default-map', dest='map', action='store_true',
                        help='Display the default field map')
    parser.add_argument('--bus', dest='bus', type=int,
                        help='Bus on which PiJuice is located, 0-1')
    parser.add_argument('--address', dest='address',
                        help='Address used by PiJuice.')
    parser.add_argument('--debug', dest='debug', type=int,
                        help='How much status to display, 0-1')
    parser.add_argument('--raw', dest='raw', action='store_true', default=False,
                        help='How much status to display, 0-1')
    # parse the arguments
    args = parser.parse_args()

    # display the version number
    if args.version:
        print("pijuice service version: %s" % pj_service_version)
        exit(0)

    # get config_dict to use
    config_path, config_dict = weecfg.read_config(args.config_path)
    print("Using configuration file %s" % config_path)
    service_dict = config_dict.get('PiJuice', {})

    # set weewx.debug as necessary
    if args.debug is not None:
        _debug = to_int(args.debug)
    else:
        _debug = to_int(config_dict.get('debug', 0))
    weewx.debug = _debug
    # inform the user if the debug level is 'higher' than 0
    if _debug > 0:
        print("debug level is '%d'" % _debug)

    # Set up the user customized logging, we can only run under Python v3 so
    # that means WeeWX v4 hence no need to worry about WeeWX v3 logging
    weeutil.logger.setup('weewx', config_dict)

    # get a DirectPiJuice object
    direct_pj = DirectPiJuice(args, service_dict)
    # now let the DirectPiJuice object process the options
    direct_pj.process_options()
    # if we made it here no option was selected so display our help
    parser.print_help()


if __name__ == '__main__':
    main()
