"""
This program is free software; you can redistribute it and/or modify it under
the terms of the GNU General Public License as published by the Free Software
Foundation; either version 2 of the License, or (at your option) any later
version.

This program is distributed in the hope that it will be useful, but WITHOUT ANY
WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A
PARTICULAR PURPOSE.  See the GNU General Public License for more details.

                         Installer for PiJuice Service

Version: 0.1.0                                        Date: xx August 2021

Revision History
    xx August 2021      v0.1.0
        -   initial implementation
"""

# python imports
import configobj
from distutils.version import StrictVersion
from setup import ExtensionInstaller

# import StringIO, use six.moves due to python2/python3 differences
from six.moves import StringIO

# WeeWX imports
import weewx


REQUIRED_VERSION = "4.0.0"
PJ_VERSION = "0.1.0"
# define our config as a multiline string so we can preserve comments
pj_config = """
[PiJuice]
    # This section is for the PiJuice service.

    # Interval in seconds between PiJuice updates, default is 20 seconds
    update_interval = 20
"""

# construct our config dict
pj_dict = configobj.ConfigObj(StringIO(pj_config))


def loader():
    return PjInstaller()


class PjInstaller(ExtensionInstaller):
    def __init__(self):
        if StrictVersion(weewx.__version__) < StrictVersion(REQUIRED_VERSION):
            msg = "%s requires WeeWX %s or greater, found %s" % (''.join(('PiJuice service ', PJ_VERSION)),
                                                                 REQUIRED_VERSION,
                                                                 weewx.__version__)
            raise weewx.UnsupportedFeature(msg)
        super(PjInstaller, self).__init__(
            version=PJ_VERSION,
            name='PiJuice',
            description='WeeWX service for PiJuice UPS HAT.',
            author="Gary Roderick",
            author_email="gjroderick<@>gmail.com",
            data_services=['user.juice.PiJuiceService'],
            config=pj_dict,
            files=[('bin/user', ['bin/user/juice.py'])]
        )
