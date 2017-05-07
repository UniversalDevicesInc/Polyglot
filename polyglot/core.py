''' The primary functionality for the Polyglot application '''
# [cython] from cpython.exc cimport PyErr_CheckSignals
import logging
import signal
import sys
import time

from polyglot.config_manager import ConfigManager
from polyglot.element_manager import ElementManager
from polyglot.nodeserver_manager import NodeServerManager
from polyglot.version import PGVERSION

_LOGGER = logging.getLogger(__name__)


class Polyglot(object):
    """
    Core class

    :param config_dir: Directory where configuration is stored

    :ivar config: Dictionary of current config
    """

    def __init__(self, config_dir):
        self.version = PGVERSION
        _LOGGER.info('Creating Polyglot, version %s', self.version)
        
        sys.modules['pglot'] = self
        # initialize components
        self.config = ConfigManager(config_dir)
        self.elements = ElementManager(self)
        self.nodeservers = NodeServerManager(self)
        self.running = False
        self.isy_version = self.config.get_isy_version()
        # handle SIGTERMs
        signal.signal(signal.SIGTERM, self.stop)

    def setup(self):
        """ Setup Polyglot to resume the last known state """
        _LOGGER.info('Starting Polyglot')
        self.elements.load()
        self.nodeservers.load()        

    def run(self):
        """ Run the Polyglot server """
        self.running = True
        try:
            while self.running:
                time.sleep(1)
                # [cython] PyErr_CheckSignals()
        except KeyboardInterrupt:
            self.stop()

    def stop(self, *args):
        """ Stops the Polyglot server """
        # pylint: disable=unused-argument
        self.update_config()
        self.running = False
        _LOGGER.info('Stopping Polyglot')
        self.nodeservers.unload()
        self.elements.unload()

    def update_config(self):
        """ Signal Polyglot to fetch updated configuration. """
        if not self.running:
            _LOGGER.info('Not saving configuration (shutting down or not yet running)')
            return
        _LOGGER.debug('Saving Configuration')
        config = {'nodeservers': self.nodeservers.config,
                  'elements': self.elements.config}
        self.config.update(config)

    def get_log(self):
        """ Read and return the log file contents. """
        fname = self.config.make_path('polyglot.log')
        return open(fname).read()
