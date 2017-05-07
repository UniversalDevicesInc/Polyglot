#!/usr/bin/python
""" Phillips Hue Node Server for ISY """

from converters import id_2_addr
try:
    from httplib import BadStatusLine  # Python 2.x
except ImportError:
    from http.client import BadStatusLine  # Python 3.x
from polyglot.nodeserver_api import SimpleNodeServer, PolyglotConnector
from node_types import HubSettings, HueColorLight
import os
import phue
import socket


class HueNodeServer(SimpleNodeServer):
    """ Phillips Hue Node Server """

    hub = None
    hub_queried = False

    def setup(self):
        """ Initial node setup. """
        # define nodes for settings
        manifest = self.config.get('manifest', {})
        HubSettings(self, 'hub', 'Hue Hub', True, manifest)
        self.connect()
        self.update_config(self.hub_queried)

    def connect(self):
        """ Connect to Phillips Hue Hub """
        # pylint: disable=broad-except
        # get hub settings
        hub = self.get_node('hub')
        ip_addr = '{}.{}.{}.{}'.format(
            hub.get_driver('GV1')[0], hub.get_driver('GV2')[0],
            hub.get_driver('GV3')[0], hub.get_driver('GV4')[0])

        # try to authenticate with the hub
        try:
            self.hub = phue.Bridge(
                ip_addr, config_file_path=os.path.join(os.getcwd(), 'bridges'))
        except phue.PhueRegistrationException:
            self.poly.send_error('IP Address OK. Node Server not registered.')
            return False
        except Exception:
            self.poly.send_error('Cannot find hub at {}'.format(ip_addr))
            return False  # bad ip Addressse:
        else:
            # ensure hub is connectable
            api = self._get_api()

            if api:
                hub.set_driver('GV5', 1)
                hub.report_driver()
                return True
            else:
                self.hub = None
                return False

    def poll(self):
        """ Poll Hue for new lights/existing lights' statuses """
        if self.hub is None:
            return True

        api = self._get_api()
        if not api:
            return False
        lights = api['lights']

        manifest = self.config.get('manifest', {})

        for lamp_id, data in lights.items():
            address = id_2_addr(data['uniqueid'])
            name = data['name']
            lnode = self.get_node(address)
            if not lnode:
                lnode = HueColorLight(self, address, 
                                      name, lamp_id, 
                                      self.get_node('hub'), manifest)
            (color_x, color_y) = [round(val, 4)
                                  for val in data['state'].get('xy',[0.0,0.0])]
            brightness = round(data['state']['bri'] / 255. * 100., 4)
            brightness = brightness if data['state']['on'] else 0
            lnode.set_driver('GV1', color_x)
            lnode.set_driver('GV2', color_y)
            lnode.set_driver('ST', brightness)

        self.hub_queried = True
        return True

    def query_node(self, lkp_address):
        """ find specific node in api. """
        api = self._get_api()
        if not api:
            return False

        lights = api['lights']

        for data in lights.values():
            address = id_2_addr(data['uniqueid'])
            if address == lkp_address:
                (color_x, color_y) = [round(val, 4)
                                      for val in data['state'].get('xy',[0.0,0.0])]
                brightness = round(data['state']['bri'] / 255. * 100., 4)
                brightness = brightness if data['state']['on'] else 0
                return (color_x, color_y, brightness)

    def _get_api(self):
        """ get hue hub api data. """
        try:
            api = self.hub.get_api()
        except BadStatusLine:
            self.poly.send_error('Hue Bridge returned bad status line.')
            return False
        except phue.PhueRequestTimeout:
            self.poly.send_error('Timed out trying to connect to Hue Bridge.')
            return False
        except socket.error:
            self.poly.send_error("Can't contact Hue Bridge. " +
                                 "Network communication issue.")
            return False
        return api

    def long_poll(self):
        """ Save configuration every 30 seconds. """
        self.update_config(self.hub_queried)


def main():
    """ setup connection, node server, and nodes """
    poly = PolyglotConnector()
    nserver = HueNodeServer(poly)
    poly.connect()
    poly.wait_for_config()
    nserver.setup()
    nserver.run()


if __name__ == "__main__":
    main()
