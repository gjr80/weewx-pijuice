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

    def __init__(self):
        pass
