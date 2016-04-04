#!/usr/bin/python
""" Kodi Node Server for ISY """

from polyglot.nodeserver_api import SimpleNodeServer, PolyglotConnector
from node_types import KodiDiscovery, Kodi
import hashlib


def id_2_addr(udn):
    ''' convert udn id to isy address '''
    hasher = hashlib.md5()
    hasher.update(udn)
    return hasher.hexdigest()[0:14]


class KodiNodeServer(SimpleNodeServer):
    """ Kodi Node Server """

    def setup(self):
        """ Initial node setup. """
        # define nodes for settings
        manifest = self.config.get('manifest', {})
        KodiDiscovery(self, 'disco', 'Kodi Discovery', True, manifest)
        self.nodes['disco'].discover()
        self.update_config()

    def found_kodi(self, ip_addr, udn, name):
        ''' register new or old kodi instance '''
        isy_addr = id_2_addr(udn)

        lnode = self.get_node(isy_addr)
        if not lnode:
            manifest = self.config.get('manifest', {})
            Kodi(self, isy_addr, name, ip_addr, self.get_node('disco'), manifest)

        else:
            self.nodes[isy_addr].set_ip(ip_addr)

    def poll(self):
        """ Poll Kodi for updates """
        for isy_addr, node in self.nodes.items():
            if isy_addr != 'disco':
                node.query(force_report=False)

        return True

    def long_poll(self):
        """ Save configuration every 30 seconds. """
        self.nodes['disco'].discover()
        self.update_config()


def main():
    """ setup connection, node server, and nodes """
    poly = PolyglotConnector()
    nserver = KodiNodeServer(poly)
    poly.connect()
    poly.wait_for_config()
    nserver.setup()
    nserver.run()


if __name__ == "__main__":
    main()
