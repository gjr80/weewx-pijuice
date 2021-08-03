# WeeWX PiJuice service #

A [WeeWX](http://weewx.com/ "WeeWX - Open source software for your weather station") service to obtain data from a [PiJuice HAT](https://uk.pi-supply.com/products/pijuice-standard) UPS connected to a Raspberry Pi running WeeWX.

## Description ##

The *PiJuice service* polls a local PiJuice UPS and obtains various UPS status data. WeeWX loop packets are augmented with the status data allwoing it to be stored in a WeeWX database and used in various WeeWX reports.
