#!/usr/bin/python
""" Pulse - a heartbeat node server for Polyglot. """

from polyglot.nodeserver_api import NodeServer, SimpleNodeServer, Node
from polyglot.nodeserver_api import PolyglotConnector
from polyglot.nodeserver_api import NS_API_VERSION

from diagtst_node import PulseDiagTest

import time

# - { = } - { = } - { = } - { = } - { = } - { = } - { = } - { = } - { = } - #

class PulseMain(Node):
    """ Primary node, containing the seconds-since-epoch time value """

    def __init__(self, *args, **kwargs):
        super(PulseMain, self).__init__(*args, **kwargs)
        self._next_beat_t = 0

    def _st(self, **kwargs):
        return self.set_driver('ST', time.time(), report=True)

    def query(self):
        self.set_driver('ST', time.time(), report=False)
        return self.report_driver()

    def poll(self):
        now = time.time()
        if now > self._next_beat_t:
            self._next_beat_t = now + 60
            self.set_driver('ST', now, report=True)
            self.report_isycmd('DON')
            #self.parent.poly.report_command(self.address, 'DON')
        return True

    _drivers = {'ST':  [0, 56, int, False]}
    _sends = {'DON': [None, None, None]}
    _commands = {'ST': _st}
    node_def_id = 'PULSE_MAIN'

# - { = } - { = } - { = } - { = } - { = } - { = } - { = } - { = } - { = } - #

class PulseNodeServer(SimpleNodeServer):
    """ SimpleNodeServer-style node server to provide a heartbeat """

    def setup(self):
        manifest = self.config.get('manifest', {})
        # Register the primary node
        PulseMain(self, 'pulse', 'Pulse Heartbeat and Time', True, manifest)
        primary = self.get_node('pulse')
        # Now add the base secondary nodes
        PulseDiagTest(self, 'pulsediagtest', 'Pulse Diagnostics and Test',
                      primary, manifest)
        # Update the config file to reflect our current state
        self.update_config()

    def poll(self):
        # call each node's poll() method
        for n in self.nodes:
            self.nodes[n].poll()
        return True

    def long_poll(self):
        self.update_config()
        return True

# - { = } - { = } - { = } - { = } - { = } - { = } - { = } - { = } - { = } - #

if __name__ == "__main__":
    poly = PolyglotConnector()
    nserver = PulseNodeServer(poly)
    poly.connect()
    poly.wait_for_config()
    nserver.setup()
    nserver.run()
