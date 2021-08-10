"""
juice.py

A WeeWX service to obtain data from a locally connected PiJuice HAT UPS.

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


(expand) A WeeWX service to obtain data from a PiJuice UPS.

Abbreviated instructions for use:

1.  Put this file in $BIN_ROOT/user.

2.  Add the following stanza to weewx.conf:

[PiJuice]

3.  Add the PiJuice service to the list of data services under
[Engines] [[WxEngine]] in weewx.conf:

[Engines]
    [[WxEngine]]
        data_services = ..., user.juice.PiJuice

4.  Restart WeeWX
"""

# python imports
import calendar
import datetime
import errno
import json
import logging
import pijuice
import time

# WeeWX imports
import weewx
import weeutil.logger
import weeutil.weeutil
import weewx.units
import weewx.wxformulas
from weewx.engine import StdService
from weewx.units import ValueTuple, convert, getStandardUnitType
from weeutil.weeutil import to_bool, to_int, startOfDay, max_with_none, min_with_none

# setup logging, the Pijuice API operates under Python3 so we don't need to
# worry about supporting WeeWX v3 logging via syslog
log = logging.getLogger(__name__)


def logdbg(msg):
    log.debug(msg)


def loginf(msg):
    log.info(msg)


def logerr(msg):
    log.error(msg)


# version number of this script
PIJUICE_VERSION = '0.1.0'

# PiJuice error messages with plain English meaning
PIJUICE_ERRORS = {'NO_ERROR': 'No error',
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
PIJUICE_STATUS = {'isFault': 'Fault exists',
                  'isButton': 'Button events exist',
                  'battery': 'Battery',
                  'powerInput': 'µUSB power input',
                  'powerInput5vIo': '5V GPIO power input'
                  }
PIJUICE_STATES = {'NORMAL': 'Normal',
                  'PRESENT': 'Present',
                  'NOT_PRESENT': 'Not present',
                  'CHARGING_FROM_IN': 'Charging from µUSB power input',
                  'CHARGING_FROM_5V_IO': 'Charging from 5V GPIO power input',
                  'BAD': 'Bad',
                  'WEAK': 'Weak'
                  }
PIJUICE_FAULT_STATUS = {'button_power_off': 'Power off triggered by button press',
                        'forced_power_off': 'Forced power off caused by loss of energy',
                        'forced_sys_power_off': 'Forced system switch turn off caused by loss of energy',
                        'watchdog_reset': 'Watchdog reset',
                        'battery_profile_invalid': 'Battery profile is invalid',
                        'charging_temperature_fault': 'Battery charging temperature fault'
                        }
PIJUICE_FAULT_STATES = {'NORMAL': 'Normal',
                        'SUSPEND': 'Suspend',
                        'COOL': 'Cool',
                        'WARM': 'Warm'
                        }
API_LOOKUP = {'batt_temp': {'layer': 'status',
                            'cmd': 'GetBatteryTemperature'
                            },
              'batt_charge': {'layer': 'status',
                              'cmd': 'GetChargeLevel'
                              },
              'batt_voltage': {'layer': 'status',
                               'cmd': 'GetBatteryVoltage'
                               },
              'batt_current': {'layer': 'status',
                               'cmd': 'GetBatteryCurrent'
                               },
              'io_voltage': {'layer': 'status',
                             'cmd': 'GetIoVoltage'
                             },
              'iso_current': {'layer': 'status',
                              'cmd': 'GetIoCurrent'
                              }
              }


# ============================================================================
#                               class PiJuiceService
# ============================================================================

class PiJuiceService(StdService):
    """Service that adds PiJuice UPS to loop packets.

    Description...
    """

    default_field_map = {
        'ups_temp': 'batt_temp',
        'ups_charge': 'batt_charge',
        'ups_voltage': 'batt_voltage',
        'ups_current': 'batt_current',
        'io_voltage': 'io_voltage',
        'io_current': 'iso_current'
    }

    def __init__(self, engine, config_dict):
        # initialize my superclass
        super(PiJuiceService, self).__init__(engine, config_dict)

        # get our PiJuice config dictionary
        pj_config_dict = config_dict.get('PiJuice', {})

        # construct the field map, first obtain the field map from our config
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
        # leaves two entries for that PiJuice field in the field map; the
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
                # up with multiple mappings for that PiJuice field
                if v in extensions.values():
                    # pop the field map entry
                    _dummy = field_map.pop(k)
            # now we can update the field map with the extensions
            field_map.update(extensions)
        # we now have our final field map
        self.field_map = field_map
        self.get_pj_data()

        # bind our self to the relevant WeeWX events
        self.bind(weewx.NEW_LOOP_PACKET, self.new_loop_packet)

    def new_loop_packet(self, event):
        """Obtain PiJuice data and add the data to the loop packet."""

        pass

    def get_pj_data(self):
        """Get the required data via the PiJuice API."""

        api_calls = {API_LOOKUP[a] for a in self.field_map.values()}
        loginf("api_calls=%s" % (api_calls,))


# ============================================================================
#                              Utility Functions
# ============================================================================

def get_data_or_error(d):
    """Given a PiJuice API response extract valid data or an error.

    A PiJuice API response is a dict keyed as follows:
    'error': a string containing an error code string, mandatory.
    'data': the data returned by the API, optional. Only included if there is
            no error (ie 'error' == 'NO_ERROR')

    If the API response contains data return the data otherwise the error code
    string is returned.
    """

    return d.get('data', d['error'])


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
    import pijuice

    usage = """python -m user.juice --help
       python -m user.juice --version
       python -m user.juice --get-status [CONFIG_FILE|--config=CONFIG_FILE]
       python -m user.juice --get-faults [CONFIG_FILE|--config=CONFIG_FILE]
       python -m user.juice --get-battery [CONFIG_FILE|--config=CONFIG_FILE]
       python -m user.juice --get-input [CONFIG_FILE|--config=CONFIG_FILE]
       python -m user.juice --get-time [CONFIG_FILE|--config=CONFIG_FILE]
       
    Arguments:

       CONFIG_FILE: Path and file name of the WeeWX configuration file to be used. 
                    Default is weewx.conf."""
    description = 'Test the pijuice service.'
    epilog = """You must ensure the WeeWX modules are in your PYTHONPATH. For example:

PYTHONPATH=/home/weewx/bin python -m user.juice --help
"""
    # datetime constuctor arguments we need to filter from the RTC time
    DT_ARGS = ['year', 'month', 'day', 'hour', 'minute', 'second']
    # args that require the PiJuice be interrogated
    PJ_ARGS = ['status', 'battery', 'fault', 'io', 'rtc']

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
    parser.add_argument('--debug', dest='debug', type=int,
                        help='How much status to display, 0-1')
    parser.add_argument('--raw', dest='raw', action='store_true', default=False,
                        help='How much status to display, 0-1')
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
    # parse the arguments
    args = parser.parse_args()

    # display the version number
    if args.version:
        print("pijuice service version: %s" % PIJUICE_VERSION)
        exit(0)

    # args that require the PiJuice be interrogated
    if any(getattr(args, x) for x in PJ_ARGS):
        # we will need to interrogate the PiJuice so get a PiJuice object
        pj = pijuice.PiJuice()
        if args.status:
            # display PiJuice status
            # get a status object so we may use the status API
            status = pj.status
            # get the PiJuice status
            resp = status.GetStatus()
            print()
            print("PiJuice status:")
            if 'error' in resp and resp['error'] == 'NO_ERROR' and 'data' in resp:
                for key, value in resp['data'].items():
                    if args.raw:
                        print("%16s: %s" % (key, value))
                    else:
                        print("%21s: %s" % (PIJUICE_STATUS.get(key, key),
                                            PIJUICE_STATES.get(value, value)))
            else:
                if args.raw:
                    print("Error: %s" % resp['error'])
                else:
                    print("Error: %s (%s)" % (PIJUICE_ERRORS.get(resp['error']),
                                              resp['error']))
            exit(0)

        elif args.fault:
            # display PiJuice fault status
            # get a status object so we may use the status API
            status = pj.status
            # get the fault status
            resp = status.GetFaultStatus()
            print()
            print("PiJuice fault status:")
            if 'error' in resp and resp['error'] == 'NO_ERROR' and 'data' in resp:
                for key, value in resp['data'].items():
                    if args.raw:
                        print("%28s: %s" % (key, value))
                    else:
                        print("%56s: %s" % (PIJUICE_FAULT_STATUS.get(key, key),
                                            PIJUICE_FAULT_STATES.get(value, value)))
            else:
                if args.raw:
                    print("Error: %s" % resp['error'])
                else:
                    print("Error: %s (%s)" % (PIJUICE_ERRORS.get(resp['error']),
                                              resp['error']))
            exit(0)

        elif args.battery:
            # display PiJuice battery state, this a composite picture built
            # from several API calls
            # get a status object so we may use the status API
            status = pj.status
            # get the battery charge level
            charge = get_data_or_error(status.GetChargeLevel())
            # get the battery voltage.
            voltage = get_data_or_error(status.GetBatteryVoltage())
            # get the battery current
            current = get_data_or_error(status.GetBatteryCurrent())
            # get the battery temperature
            temp = get_data_or_error(status.GetBatteryTemperature())
            # now display the accumulated data
            print()
            print("PiJuice battery state:")
            # charge could be an integer (%) or an error code, try formatting
            # as an integer but be prepared to catch an exception if this fails
            try:
                print("%12s: %d%%" % ('Charge', charge))
            except TypeError:
                # we couldn't format as an integer so format as a string
                print("%12s: %s" % ('Charge', charge))
            # voltage could be an integer in mV or an error code, try
            # converting to V and formatting as a float but be prepared to
            # catch an exception if this fails
            try:
                print("%12s: %.3fV" % ('Voltage', voltage / 1000.0))
            except TypeError:
                # we couldn't convert to V and format as a float so format as a
                # string
                print("%12s: %s" % ('Voltage', voltage))
            # current could be an integer in mA or an error code, try
            # converting to A and formatting as a float but be prepared to
            # catch an exception if this fails
            try:
                print("%12s: %.3fA" % ('Current', current / 1000.0))
            except TypeError:
                # we couldn't convert to A and format as a float so format as a
                # string
                print("%12s: %s" % ('Current', current))
            # temperature could be an integer degrees C or an error code, try
            # formatting as an integer but be prepared to catch an exception if
            # this fails
            try:
                print(u"%12s: %d\xb0C" % ('Temperature', temp))
            except TypeError:
                # we couldn't format as an integer so format as a string
                print("%12s: %s" % ('Temperature', temp))
            exit(0)
        elif args.io:
            # display PiJuice input state, this a composite picture built from
            # several API calls
            # get a status object so we may use the status API
            status = pj.status
            # get the input voltage
            voltage = get_data_or_error(status.GetIoVoltage())
            # get the input current
            current = get_data_or_error(status.GetIoCurrent())
            # now display the accumulated data
            print()
            print("PiJuice input state:")
            # voltage could be an integer in mV or an error code, try
            # converting to V and formatting as a float but be prepared to
            # catch an exception if this fails
            try:
                print("%12s: %.3fV" % ('Voltage', voltage / 1000.0))
            except TypeError:
                # we couldn't convert to V and format as a float so format as a
                # string
                print("%12s: %s" % ('Voltage', voltage))
            # current could be an integer in mA or an error code, try
            # converting to A and formatting as a float but be prepared to
            # catch an exception if this fails
            try:
                print("%12s: %.3fA" % ('Current', current / 1000.0))
            except TypeError:
                # we couldn't convert to A and format as a float so format as a
                # string
                print("%12s: %s" % ('Current', current))
            exit(0)
        elif args.rtc:
            # display PiJuice RTC time
            # get an RTC alarm object so we may use the status API
            rtc = pj.rtcAlarm
            # Get the RTC time. This will return a dict of date-time components
            # or an error message string.
            utc_date_time = get_data_or_error(rtc.GetTime())
            # now display the accumulated data
            print()
            if args.raw:
                print("PiJuice RTC date-time (UTC):")
                # We only need print the returned date-time components, but we
                # could have an error message instead. Wrap in a try..except
                # statement and be prepared to catch the exception if we strike
                # an error message.
                try:
                    for key, value in utc_date_time.items():
                        print("%16s: %s" % (key, value))
                except AttributeError:
                    # utc_date_time was not a dict so likely just an error
                    # message. Print the error message as is.
                    print("PiJuice RTC date-time (UTC): %s" % utc_date_time)
            else:
                # We need to display the RTC time in a more human readable
                # format. We now have the components (hour, minute, etc) of the
                # RTC date-time albeit in UTC. We need to obtain a python
                # datetime object from this data so we can format the date-time
                # string as required and also convert to local time.

                # first filter from the RTC date-time data the fields that we
                # will use we need to construct a datetime object
                utc_dt_dict = {k: v for k, v in utc_date_time.items() if k in DT_ARGS}
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
            exit(0)
    # if we made it here no option was selected so display our help
    parser.print_help()


if __name__ == '__main__':
    main()
