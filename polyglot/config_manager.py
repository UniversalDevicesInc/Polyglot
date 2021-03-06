''' The configuration management module for Polyglot '''

import base64
from collections import defaultdict
import copy
import json
import shutil
import logging
import os
import stat
import time

_LOGGER = logging.getLogger(__name__)


class ConfigManager(defaultdict):
    """
    Configuration Manager class

    :param config_dir: The configuration directory to use
    """

    def __init__(self, config_dir):
        super(ConfigManager, self).__init__(dict)
        self._dir = config_dir
        self._file = os.path.join(self._dir, 'configuration.json')
        self._filetmp = os.path.join(self._dir, 'configuration.json.tmp')
        self._writing = False
        self.read()

    def __del__(self):
        """ Update configuration file before erasing configuration """
        self.write()

    def encode(self):
        """ Encode passwords and return an encoded copy """
        encoded = copy.deepcopy(dict(self))
        encoded['elements']['http']['password'] = \
            base64.b64encode(encoded['elements']['http']['password'])
        encoded['elements']['isy']['password'] = \
            base64.b64encode(encoded['elements']['isy']['password'])
        return encoded

    def decode(self, encoded):
        """ Decode passwords and return decoded """
        try:
            encoded['elements']['http']['password'] = \
                base64.b64decode(encoded['elements']['http']['password'])
            encoded['elements']['isy']['password'] = \
                base64.b64decode(encoded['elements']['isy']['password'])
        except TypeError:
            pass
        return encoded

    def update(self, *args, **kwargs):
        """ Update the configuration with values in dictionary """
        existing_config = copy.deepcopy(dict(self))
        super(ConfigManager, self).update(*args, **kwargs)
        updated_config = copy.deepcopy(dict(self))
        if self.sort_keys(existing_config) == self.sort_keys(updated_config):
            _LOGGER.debug('Config files match no need to write to config file.')
        else:
            _LOGGER.info('Config file changes detected, updating config file.')
            self.write()

    def get_isy_version(self):
        config = copy.deepcopy(dict(self))
        try:
            return self.get_from_config(config, ['elements', 'isy', 'version'])
        except KeyError:
            return

    def get_from_config(self, config_dict, element):
        return reduce(lambda d, k: d[k], element, config_dict)
            
    def sort_keys(self, obj):
        if isinstance(obj, dict):
            return sorted((k, self.sort_keys(v)) for k, v in obj.items())
        if isinstance(obj, list):
            return sorted(self.sort_keys(x) for x in obj)
        else:
            return obj
            
    def read(self):
        """ Reads configuration file """
        if os.path.isfile(self._file):
            encoded = json.load(open(self._file, 'r'))
            decoded = self.decode(encoded)
            _LOGGER.debug('Read configuration file')
            self.update(decoded)

    def write(self):
        """ Writes configuration file """
        # wait for file to unlock. Timeout after 5 seconds
        for _ in range(5):
            if not self._writing:
                self._writing = True
                break
            time.sleep(1)
        else:
            _LOGGER.error('Could not write to configuration file. It is busy.')
            return

        # dump JSON to config file and unlock
        encoded = self.encode()
        json.dump(encoded, open(self._filetmp, 'w'), sort_keys=True, indent=4,
                  separators=(',', ': '))
        os.chmod(self._filetmp, stat.S_IRUSR | stat.S_IWUSR)
        try:
            shutil.move(self._filetmp, self._file)
            _LOGGER.debug('Config file succesfully updated.')
        except shutil.Error as e:
            _LOGGER.error('Failed to move temp config file to original error: ' + str(e))
            
        self._writing = False
        _LOGGER.debug('Wrote configuration file')

    def make_path(self, *args):
        """ make a path to a file in the config directory """
        return os.path.join(self._dir, *args)

    def nodeserver_sandbox(self, url_base):
        """ make and return a sandbox directory for a node server. """
        sandbox = self.make_path(url_base)

        if not os.path.isdir(sandbox):
            os.mkdir(sandbox)

        return sandbox
