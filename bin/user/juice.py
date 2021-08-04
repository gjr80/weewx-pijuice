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
this program.  If not, see http://www.gnu.org/licenses/.

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
import datetime
import errno
import json
import logging
import math
import os
import os.path
import pijuice
import socket
import time

# WeeWX imports
import weewx
import weeutil.logger
import weeutil.weeutil
import weewx.units
import weewx.wxformulas
from weewx.engine import StdService
from weewx.units import ValueTuple, convert, getStandardUnitType
import weeutil.rsyncupload
from weeutil.weeutil import to_bool, to_int, startOfDay, max_with_none, min_with_none

# get a logger object
log = logging.getLogger(__name__)

# version number of this script
PIJUICE_VERSION = '0.1.0'


# ============================================================================
#                               class PiJuiceService
# ============================================================================

class PiJuiceService(StdService):
    """Service that adds PiJuice UPS to loop packets.

    Description...
    """

    def __init__(self, engine, config_dict):
        # initialize my superclass
        super(PiJuiceService, self).__init__(engine, config_dict)

        # get our PiJuice config dictionary
        juice_config_dict = config_dict.get('PiJuice', {})

        # bind our self to the relevant WeeWX events
        self.bind(weewx.NEW_LOOP_PACKET, self.new_loop_packet)

    def new_loop_packet(self, event):
        """Obtain PiJuice data and add the data to the loop packet."""

        pass


# ============================================================================
#                               class PiJuice
# ============================================================================

class PiJuice(object):
    """Class to obtain data from a PiJuice UPS."""

    def __init__(self, bus=1, address=0x14):
        # get a PiJuice object
        self.pijuice = pijuice.PiJuice(bus, address)

    @property
    def status(self):
        return self.pijuice.status.GetStatus()

    @property
    def charge_level(self):
        return self.pijuice.GetChargeLevel()

    @property
    def fault_status(self):
        return self.pijuice.GetFaultStatus()

    @property
    def button_events(self):
        return self.pijuice.GetButtonEvents()

    @property
    def battery_temperature(self):
        return self.pijuice.GetBatteryTemperature()

    @property
    def battery_voltage(self):
        return self.pijuice.GetBatteryVoltage()

    @property
    def battery_current(self):
        return self.pijuice.GetBatteryCurrent()

    @property
    def io_voltage(self):
        return self.pijuice.GetIoVoltage()

    @property
    def io_current(self):
        return self.pijuice.GetIoCurrent()

    @property
    def led_state(self):
        return self.pijuice.GetLedState()

    @property
    def led_blink(self):
        return self.pijuice.GetLedBlink()

    @property
    def io_digital_input(self):
        return self.pijuice.GetIoDigitalInput()

    @property
    def io_analog_input(self):
        return self.pijuice.GetIoDigitalOutput()

    @property
    def io_pwm(self):
        return self.pijuice.GetIoPWM()


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
    import weecfg

    usage = """python -m user.juice --help
       python -m user.juice --version
       python -m user.juice --status [CONFIG_FILE|--config=CONFIG_FILE]
       python -m user.juice --charge [CONFIG_FILE|--config=CONFIG_FILE]
       python -m user.juice --fault_status [CONFIG_FILE|--config=CONFIG_FILE]
       python -m user.juice --batt_voltage [CONFIG_FILE|--config=CONFIG_FILE]
       python -m user.juice --batt_current [CONFIG_FILE|--config=CONFIG_FILE]
       
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
    parser.add_argument('--debug', dest='debug', type=int,
                        help='How much status to display, 0-1')
    parser.add_argument("--status", dest="status", action='store_true',
                        help="Display PiJuice status.")
    parser.add_argument("--charge", dest="charge", action='store_true',
                        help="Display PiJuice battery charge.")
    parser.add_argument("--fault-status", dest="fault_status", action='store_true',
                        help="Display PiJuice fault status.")
    parser.add_argument("--batt-voltage", dest="batt_voltage", action='store_true',
                        help="Display PiJuice battery voltage.")
    parser.add_argument("--batt-current", dest="batt_current", action='store_true',
                        help="Display PiJuice battery current.")
    parser.add_argument("--io-voltage", dest="io_voltage", action='store_true',
                        help="Display PiJuice IO voltage.")
    # parse the arguments
    args = parser.parse_args()

    # display the version number
    if args.version:
        print("pijuice service version: %s" % PIJUICE_VERSION)
        exit(0)

    if args.status:
        # display PiJuice status
        pijuice = PiJuice()
        # status = pijuice.status
        print()
        print("PiJuice status: %s" % (pijuice.status, ))
        exit(0)

    # run the notification email test
    if False:
        # get config_dict to use
        try:
            config_path, config_dict = weecfg.read_config(args.config_path,
                                                          args.config_pos)
            print("Using configuration file %s" % config_path)
        except IOError as e:
            exit("Unable to open configuration file '%s'" % e)
        # set weewx.debug as necessary
        if args.debug is not None:
            _debug = weeutil.weeutil.to_int(args.debug)
        else:
            _debug = weeutil.weeutil.to_int(config_dict.get('debug', 0))
        weewx.debug = _debug
        # inform the user if the debug level is 'higher' than 0
        if _debug > 0:
            print("debug level is '%d'" % _debug)
        # Now we can set up the user customized logging but we need to handle both
        # v3 and v4 logging. V4 logging is very easy but v3 logging requires us to
        # set up syslog and raise our log level based on weewx.debug
        try:
            # assume v 4 logging
            weeutil.logger.setup('weewx', config_dict)
        except AttributeError:
            # must be v3 logging, so first set the defaults for the system logger
            syslog.openlog('weewx', syslog.LOG_PID | syslog.LOG_CONS)
            # now raise the log level if required
            if weewx.debug > 0:
                syslog.setlogmask(syslog.LOG_UPTO(syslog.LOG_DEBUG))
        # we need an [AggregateNotification] stanza in weewx.conf so check its
        # existence and abort if missing
        if 'AggregateNotification' not in config_dict:
            exit("No [AggregateNotification] section in "
                 "the configuration file '%s'" % config_path)
    # if we made it here no option was selected so display our help
    parser.print_help()


if __name__ == '__main__':
    main()
