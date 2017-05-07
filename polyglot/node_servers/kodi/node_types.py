""" Node classes used by the Kodi Node Server. """

import re
from polyglot.nodeserver_api import Node
import requests
import xmltodict
from netdisco.discovery import NetworkDiscovery
import jsonrpc_requests
import xml

KODI_STATUS = {(None,   None):       1,
               (False,  None):       2,
               (True,  'video'):     3,
               (False, 'video'):     4,
               (True,  'music'):     5,
               (True,  'audio'):     5,
               (False, 'music'):     6,
               (False, 'audio'):     6,
               (True,  'picture'):   7,
               (True,  'pictures'):  7,
               (False, 'picture'):   8,
               (False, 'pictures'):  8}


def myint(value):
    """ round and convert to int """
    return int(round(float(value)))


def myfloat(value, prec=4):
    """ round and return float """
    return round(float(value), prec)


class KodiDiscovery(Node):
    """ Node that discovers Kodi instances on the network. """

    def __init__(self, *args, **kwargs):
        super(KodiDiscovery, self).__init__(*args, **kwargs)
        self._netdisco = NetworkDiscovery()

    def _st(self, **kwargs):
        # No status to return for this node...
        return True

    def discover(self, **_):
        """ Discover Kodi on Network """
        dlna_clients = self._netdisco.get_info('DLNA')

        for client in dlna_clients:
            try:
                response = requests.get(client, timeout=30)

            except requests.exceptions.ConnectionError:
                self.parent.poly.send_error(
                    'Error fetching DLNA data for: {}'.format(client))
                continue

            except requests.Timeout:
                self.parent.poly.send_error(
                    'Timeout fetching DLNA data for: {}'.format(client))
                continue

            try:
                dlna_info = xmltodict.parse(response.text)
            except xml.parsers.expat.ExpatError:
                self.parent.poly.send_error(
                    'Error parsing DLNA data for: {}'.format(client))
                continue

            if dlna_info['root']['device']['modelName'] in ['Kodi', 'XBMC']:
                addr = dlna_info['root']['device']['presentationURL']
                udn = dlna_info['root']['device']['UDN']
                name = dlna_info['root']['device']['friendlyName']
                name = re.sub('[^A-Za-z0-9 ]+', '', name)
                self.parent.found_kodi(addr, udn, name)

        return True

    _commands = {'NETDISCO': discover,
                 'ST' : _st}
    node_def_id = 'KODIDISCO'


class Kodi(Node):
    """ Node representing Kodi/XBMC """

    def __init__(self, parent, address, name, ip_addr, primary, manifest=None):
        super(Kodi, self).__init__(parent, address, name, primary, manifest)
        self.ip_addr = None
        self.server = None
        self.set_ip(ip_addr)
        self._last_err = False

    def set_ip(self, ip_addr):
        """ Update the IP Address """
        self.ip_addr = ip_addr + 'jsonrpc'
        self.server = jsonrpc_requests.Server(self.ip_addr)

    def query(self, force_report=True, **kwargs):
        """ command called by ISY to query the node. """
        # Poll Kodi
        players = self._get_players()
        if players is None:
            playing = None
            player = None

        # Parse response
        if players is not None and len(players) > 0:
            properties = self.server.Player.GetProperties(
                players[0]['playerid'],
                ['time', 'totaltime', 'speed'])

            playing = properties['speed'] > 0
            player = players[0]['type']

        elif players is not None:
            playing = False
            player = None

        # Lookup status ID
        # [TODO] MJW: This is fragile! Replace with pattern matching instead.
        status = KODI_STATUS[(playing, player)]
        self.set_driver('ST', status, report=not force_report)
        if force_report:
            self.report_driver()
        return True

    def _get_players(self):
        """ Get Players from Kodi """
        try:
            players = self.server.Player.GetActivePlayers()
        except jsonrpc_requests.TransportError as err:
            if not self._last_err:
                self.parent.poly.send_error('Could not contact Kodi {}'
                                            .format(self.ip_addr))
                self.parent.poly.send_error(repr(err))
                self._last_err = True
            return None
        self._last_err = False
        return players

    def _play_pause(self, play_pause):
        """ send play or pause command to Kodi """
        players = self._get_players()
        if players is None or len(players) == 0:
            return False

        self.server.Player.PlayPause(players[0]['playerid'], play_pause)
        self.query()
        return True

    def _play(self, **_):
        """ send play to kodi """
        return self._play_pause(True)

    def _pause(self, **_):
        """ send pause to kodi """
        return self._play_pause(False)

    def _stop(self, **_):
        """ send stop to kodi """
        players = self._get_players()
        if players is None or len(players) == 0:
            return False

        self.server.Player.Stop(players[0]['playerid'])
        self.query()
        return True

    def _prev_next(self, direction):
        """ send previous or next to kodi """
        players = self._get_players()
        if players is None or len(players) == 0:
            return False

        self.server.Player.GoTo(players[0]['playerid'], direction)
        self.query()
        return True

    def _prev(self, **_):
        """ send previous to kodi """
        return self._prev_next('previous')

    def _next(self, **_):
        """ send next to kodi """
        return self._prev_next('next')

    def _st(self, **_):
        self.query()
        return True

    _drivers = {'ST': [0, 25, myint]}
    """ Driver Details:
        ST: 1 - Off
            2 - Idle
            3 - Playing Movie
            4 - Paused Movie
            5 - Playing Music
            6 - Paused Music
    """
    _commands = {'PLAY': _play, 'PAUSE': _pause, 'STOP': _stop, 'PREV': _prev,
                 'NEXT': _next, 'ST': _st}
    node_def_id = 'KODI'

    _last_err = False
