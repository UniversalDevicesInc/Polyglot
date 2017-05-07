""" PulseDiagTest - a Node for testing and diagnostics """

from polyglot.nodeserver_api import Node
import xml.etree.ElementTree as ET
import time

# - { = } - { = } - { = } - { = } - { = } - { = } - { = } - { = } - { = } - #

class PulseDiagTest(Node):
    """ Pulse Node: Diagnostics and Testing """

    def __init__(self, *args, **kwargs):
        super(PulseDiagTest, self).__init__(*args, **kwargs)

        self._next_t = 0

        # Comms test idle/passed/failed
        self._test_run = self.get_driver('GV1')[0]
        if self._test_run < 1 or self._test_run > 3:
            self._test_run = 1

        # Test counter
        self._gv2 = self.get_driver('GV2')[0]

        # Statistics (computed) for display
        self._PtoI_ok      = 0    # GV3
        self._PtoI_retries = 0    # GV4
        self._PtoI_errors  = 0    # GV5
        self._PtoI_t_low   = 0.0  # GV6
        self._PtoI_t_avg   = 0.0  # GV7
        self._PtoI_t_high  = 0.0  # GV8
        self._PtoI_score   = 0    # ST

        # Signal that we are entitled to detailed statistics
        self.parent.poly._mk_cmd('manager', op='IAmManager')

        # Add callback to capture the statistics message
        self.parent.poly.listen('statistics', self.on_statistics)

    # Handle the status command (deprecated, but the ISY still sends it)
    def _st(self, **kwargs):
        return self.query()

    # Handle status queries
    def query(self):
        self.set_driver('ST',  self._PtoI_score,   report=False)
        self.set_driver('GV1', self._test_run,     report=False)
        self.set_driver('GV2', self._gv2,          report=False)
        self.set_driver('GV3', self._PtoI_ok,      report=False)
        self.set_driver('GV4', self._PtoI_retries, report=False)
        self.set_driver('GV5', self._PtoI_errors,  report=False)
        self.set_driver('GV6', self._PtoI_t_low,   report=False)
        self.set_driver('GV7', self._PtoI_t_avg,   report=False)
        self.set_driver('GV8', self._PtoI_t_high,  report=False)
        return self.report_driver()

    # Periodic polling - this is the "main loop", if you will
    def poll(self):

        # Deal with any outstanding REST requests first
        #self._find_var_response()

        # Is it time for an update?
        now = time.time();
        if now > self._next_t:
            self._next_t = now + self.check_interval
            self._test_run = 1
            self.parent.poly.request_stats()

        # And finish by Updating the status
        self.set_driver('GV1', self._test_run, report=True)
        return True

    # Test Query
    def _testquery(self, **kwargs):
        self._test_run = 2
        return self.set_driver('GV1', self._test_run, report=True)

    # Test Counter
    def _testcount(self, **kwargs):
        self._gv2 += 1
        return self.set_driver('GV2', self._gv2, report=True)

    # Clear/Reset Statistics
    def _clearstats(self, **kwargs):
        self._gv2 = 0
        self.set_driver('GV2', self._gv2, report=True)
        self._test_run = 1
        self.set_driver('GV1', self._test_run, report=True)
        self.parent.poly._mk_cmd('manager', op='ClearStatistics')
        return self.parent.poly.request_stats()

    # Update/Refresh Statistics immediately
    def _updatestats(self, **kwargs):
        return self.parent.poly.request_stats()

    # - { = } - { = } - { = } - { = } - { = } - { = } - { = } - { = } - #
    # Handle statistics data

    def on_statistics(self, **kwargs):
        self.smsg('**DEBUG: statistics: {}'.format(kwargs))

        # Fetch the Polyglot-to-ISY statistics
        PtoI = kwargs.get('to_isy', {})
        ntotal = PtoI.get('ntotal',0)
        self._PtoI_errors = PtoI.get('ertotal',0)
        self._PtoI_ok     = PtoI.get('oktotal',0)
        # retries - not counted in any totals
        self._PtoI_retries = PtoI.get('rtotal',0)
        # Note: times are in milliseconds, and saved as integers
        self._PtoI_t_low  = int(PtoI.get('etlow',0) * 1000.0)
        self._PtoI_t_high = int(PtoI.get('ethigh',0) * 1000.0)
        # Compute average time - take care not to divide by zero
        self._PtoI_t_avg = int(((PtoI.get('ettotal',0) * 1000.0) /
                               float(max(ntotal, 1))) + 0.5)

        # Come up with some sort of "score" for the connection
        score = 0.0
        total = ntotal + self._PtoI_retries
        if total > 0:
            score = float(self._PtoI_ok) / float(total)
        if self._PtoI_t_avg > 250:
            score = score / 2.0
        if self._PtoI_t_avg > 500:
            score = score / 2.0
        if self._PtoI_t_avg > 750:
            score = score / 2.0
        if self._PtoI_t_avg > 1000:
            score = 0.0
        self._PtoI_score = int((score * 100.0) + 0.5)

        # Log the statistics
        self.smsg('**INFO: statistics: relative health: {}%'.format(self._PtoI_score))
        self.smsg('**INFO: statistics, P2I: details: total={}, ok={}, errors={}, retries={}'
                  .format(ntotal, self._PtoI_ok, self._PtoI_errors, self._PtoI_retries))
        self.smsg('**INFO: statistics, P2I: times: low={}ms, high={}ms, average={}ms'
                  .format(self._PtoI_t_low, self._PtoI_t_high, self._PtoI_t_avg))

        # Finish up by saving the results (updates ISY as appropriate)
        self.set_driver('ST',  self._PtoI_score,   report=True)
        self.set_driver('GV3', self._PtoI_ok,      report=True)
        self.set_driver('GV4', self._PtoI_retries, report=True)
        self.set_driver('GV5', self._PtoI_errors,  report=True)
        self.set_driver('GV6', self._PtoI_t_low,   report=True)
        self.set_driver('GV7', self._PtoI_t_avg,   report=True)
        self.set_driver('GV8', self._PtoI_t_high,  report=True)

        return True

    # - { = } - { = } - { = } - { = } - { = } - { = } - { = } - { = } - #

# - { = } - { = } - { = } - { = } - { = } - { = } - { = } - { = } - { = } - #
# Node Data 

    check_interval = 62

    _drivers = {'ST':  [0, 51, int, False], # PCT = 0-100%
                'GV1': [0, 25, int, False], # UPF = Idle/Passed/Failed
                'GV2': [0, 56, int, False], # INT
                'GV3': [0, 56, int, False], # INT
                'GV4': [0, 56, int, False], # INT
                'GV5': [0, 56, int, False], # INT
                'GV6': [0, 56, int, False], # INT
                'GV7': [0, 56, int, False], # INT
                'GV8': [0, 56, int, False]} # INT

    _commands = {'ST':        _st,
                 'TESTQUERY': _testquery,
                 'TESTCOUNT': _testcount,
                 'CLRSTATS' : _clearstats,
                 'UPDTSTATS': _updatestats}

    node_def_id = 'PULSE_DIAG'

# - { = } - { = } - { = } - { = } - { = } - { = } - { = } - { = } - { = } - #
