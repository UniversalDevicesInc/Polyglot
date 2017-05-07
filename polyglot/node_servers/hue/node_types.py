""" Node classes used by the Hue Node Server. """

from converters import RGB_2_xy, color_xy, color_names
from functools import partial
import json
from polyglot.nodeserver_api import Node
import urllib2


def myint(value):
    """ round and convert to int """
    return int(round(float(value)))


def myfloat(value, prec=4):
    """ round and return float """
    return round(float(value), prec)


class HubSettings(Node):
    """ Node that contains the Hub connection settings """

    def __init__(self, *args, **kwargs):
        super(HubSettings, self).__init__(*args, **kwargs)
        # discover bridge if one is not set
        if sum([self.get_driver(driver)[0]
                for driver in ('GV1', 'GV2', 'GV3', 'GV4')]) == 0:
            self.discover()

    def discover(self):
        """ Discover Hue Bridge on Network """
        response = urllib2.urlopen('https://www.meethue.com/api/nupnp')
        data = json.load(response)

        if len(data) > 0:
            ip_addr = data[0]['internalipaddress'].split('.')

            for ind, driver in enumerate(('GV1', 'GV2', 'GV3', 'GV4')):
                self.set_driver(driver, ip_addr[ind])

    def _set_ip(self, field=None, **kwargs):
        """ Set Hub IP Address """
        for arg_name, driver_name in (('GV1.uom56', 'GV1'),
                                      ('GV2.uom56', 'GV2'),
                                      ('GV3.uom56', 'GV3'),
                                      ('GV4.uom56', 'GV4')):
            if arg_name == field:
                val = kwargs.get('value')
            else:
                val = kwargs.get(arg_name, None)
            if val:
                self.set_driver(driver_name, int(val), 56)
        return True

    def _connect(self, **kwargs):
        """ connect to bridge """
        # pylint: disable=unused-argument
        return self.parent.connect()

    def _st(self, **kwargs):
        """ handle status command """
        # pylint: disable=unused-argument
        return self.report_driver()

    _drivers = {'GV1': [0, 56, int], 'GV2': [0, 56, int],
                'GV3': [0, 56, int], 'GV4': [0, 56, int],
                'GV5': [0, 2, int]}
    """ Driver Details:
    GV1: IP Address Part 1
    GV2: IP Address Part 2
    GV3: IP Address Part 3
    GV4: IP Address Part 4
    GV5: Connected
    """
    _commands = {'SET_IP': _set_ip,
                 'SET_IP_1': partial(_set_ip, field="GV1.uom56"),
                 'SET_IP_2': partial(_set_ip, field="GV2.uom56"),
                 'SET_IP_3': partial(_set_ip, field="GV3.uom56"),
                 'SET_IP_4': partial(_set_ip, field="GV4.uom56"),
                 'ST' : _st,
                 'CONNECT': _connect}
    node_def_id = 'HUB'


class HueColorLight(Node):
    """ Node representing Hue Color Light """

    def __init__(self, parent, address, name, lamp_id, primary, manifest=None):
        super(HueColorLight, self).__init__(parent, address, name, primary, manifest)
        self.lamp_id = int(lamp_id)

    def query(self):
        """ command called by ISY to query the node. """
        updates = self.parent.query_node(self.address)
        if updates:
            self.set_driver('GV1', updates[0], report=False)
            self.set_driver('GV2', updates[1], report=False)
            self.set_driver('ST', updates[2], report=False)
        # This is an explicit query - always report
        self.report_driver()
        return True

    def _st(self, **kwargs):
        """ handle status command """
        # pylint: disable=unused-argument
        # Query the Hue bulb's status
        updates = self.parent.query_node(self.address)
        # If anything has changed, update the in-memory state
        if updates:
            self.set_driver('GV1', updates[0], report=False)
            self.set_driver('GV2', updates[1], report=False)
            self.set_driver('ST', updates[2], report=False)
        # This is the status (ST) command - always report
        self.report_driver()
        return True

    def _set_brightness(self, value=None, **kwargs):
        """ set node brightness """
        # pylint: disable=unused-argument
        if value is not None:
            value = int(value / 100. * 255)
            if value > 0:
                command = {'on': True, 'bri': value}
            else:
                command = {'on': False}
        else:
            command = {'on': True}
        return self._send_command(command)

    def _on(self, **kwargs):
        """ turn light on """
        status = kwargs.get("value")
        return self._set_brightness(value=status)

    def _off(self, **kwargs):
        """ turn light off """
        # pylint: disable=unused-argument
        return self._set_brightness(value=0)

    def _set_color_rgb(self, **kwargs):
        """ set light RGB color """
        color_r = kwargs.get('R.uom56', 0)
        color_g = kwargs.get('G.uom56', 0)
        color_b = kwargs.get('B.uom56', 0)
        (color_x, color_y) = RGB_2_xy(color_r, color_g, color_b)
        command = {'xy': [color_x, color_y], 'on': True}
        return self._send_command(command)

    def _set_color_xy(self, **kwargs):
        """ set light XY color """
        color_x = kwargs.get('X.uom56', 0)
        color_y = kwargs.get('Y.uom56', 0)
        command = {'xy': [color_x, color_y], 'on': True}
        return self._send_command(command)

    def _set_color(self, value=None, **_):
        """ set color from index """
        ind = int(value) - 1

        if ind >= len(color_names):
            return False

        cname = color_names[int(value) - 1]
        color = color_xy(cname)
        return self._set_color_xy(
            **{'X.uom56': color[0], 'Y.uom56': color[1]})

    def _send_command(self, command):
        """ generic method to send command to light """
        responses = self.parent.hub.set_light(self.lamp_id, command)
        return all(
            [list(resp.keys())[0] == 'success' for resp in responses[0]])

    _drivers = {'GV1': [0, 56, myfloat], 'GV2': [0, 56, myfloat],
                'ST': [0, 51, myint]}
    """ Driver Details:
    GV1: Color X
    GV2: Color Y
    ST: Status / Brightness
    """
    _commands = {'DON': _on, 'DOF': _off,
                 'ST' : _st,
                 'SET_COLOR_RGB': _set_color_rgb,
                 'SET_COLOR_XY': _set_color_xy,
                 'SET_COLOR': _set_color}
    node_def_id = 'COLOR_LIGHT'
