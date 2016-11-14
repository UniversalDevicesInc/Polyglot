"""
This library consists of four classes and one function to assist with node
server development. The classes :class:`polyglot.nodeserver_api.NodeServer` and
:class:`polyglot.nodeserver_api.SimpleNodeServer` and basic structures for
creating a node server. The class :class:`polyglot.nodeserver_api.Node` is
used as an abstract class to crate custom nodes for node servers.  The class
:class:`polyglot.nodeserver_api.PolyglotConnector` is a bottom level
implementation of the API used to communicate between Polyglot and your
node server. Finally, included in this library is a method decorator,
:meth:`polyglot.nodeserver_api.auto_request_report`, that wraps functions and
methods to automatically handle report requests from the ISY.

.. decorator: PolyglotConnector
"""
from collections import defaultdict, OrderedDict
import copy
from functools import wraps
import json
import logging
import logging.handlers
from polyglot.utils import AsyncFileReader, Empty, LockQueue
import sys
import os
import threading
import time
import traceback
import xml.etree.ElementTree as ET

# Updated for YAML nodeserver config file (E.42) - for backwards compat
YAML = True
try:
    import yaml
except ImportError as e:
    YAML = False

# Increment this version number each time a breaking change is made to
# anything that the nodeserver API exposes to a node server.  This makes
# it possible for the author of a node server to write code that can
# support multiple possibly-incompatible Polyglot servers.  This is
# important because node servers will often be distributed independently
# of Polyglot, and the authors of the node servers may have little to
# no control over what version of Polyglot the end user is running.
NS_API_VERSION = 1

_POLYGLOT_CONNECTION = None
OUTPUT_DELAY = 0

def auto_request_report(fun):
    """
    Python decorator to automate request reporting. Decorated functions must
    return a boolean value indicating their success or failure. It the
    argument *request_id* is passed to the decorated function, a response will
    be sent to the ISY. This decorator is implemented in the SimpleNodeServer.
    """
    @wraps(fun)
    def auto_request_report_wrapper(*args, **kwargs):
        """
        Handler function wrapper to automatically report request status to ISY
        """
        request_id = kwargs.get('request_id', None)
        success = fun(*args, **kwargs)

        if request_id and _POLYGLOT_CONNECTION is not None:
            _POLYGLOT_CONNECTION.report_request_status(request_id,
                                                       bool(success))
        return success
    return auto_request_report_wrapper


class Node(object):
    """
    Abstract class for representing a node in a node server.

    :param parent: The node server that controls the node
    :type parent: polyglot.nodeserver_api.NodeServer
    :param str address: The address of the node in the ISY without the node
                        server ID prefix
    :param str name: The name of the node
    :param primary: The primary node for the device this node belongs to, 
                        or True if it's the primary.
    :type primary: polyglot.nodeserver_api.Node or True if this node is the primary.
    :param manifest: The node manifest saved by the node server
    :type manifest: dict or None

    .. document private methods
    .. autoattribute:: _drivers
    .. autoattribute:: _commands
    """

    def __init__(self, parent, address, name, primary=True, manifest=None):
        """ update driver values from manifest """
        self.parent = parent
        self.logger = self.parent.poly.logger
        self.address = address
        self.primary = primary
        self._drivers = copy.deepcopy(self._drivers)
        manifest = manifest.get(address, {}) if manifest else {}
        new_node = manifest == {}
        if not hasattr(parent,'_is_node_server'):
            raise RuntimeError('Error: node "%s", parent "%s" is not a NodeServer.'
                               % (name, parent))
        self.added = manifest.get('added', False)
        self.enabled = manifest.get('enabled', False)
        self.name = manifest.get('name', name)
        self.probe_t = 0
        drivers = manifest.get('drivers', {})
        for key, value in self._drivers.items():
            self._drivers[key][0] = drivers.get(key, value[0])

        self.smsg(
            '**INFO: Node initialized: addr="{}" name="{}" added={} enabled={}'
            .format(self.address, self.name, self.added, self.enabled))

        self.add_node()


    def smsg(self, str):
        """
        Logs/sends a diagnostic/debug, informative, or error message.
        Individual node servers can override this method if they desire to
        redirect or filter these messages.
        """
        self.parent.smsg(str)

    def run_cmd(self, command, **kwargs):
        """
        Runs one of the node's commands.

        :param str command: The name of the command
        :param dict kwargs: The parameters specified by the ISY in the
                            incoming request. See the ISY Node Server
                            documentation for more information.
        :returns boolean: Indicates success or failure of command
        """
        if command in self._commands:
            fun = self._commands[command]
            success = fun(self, **kwargs)
            return success
        return False

    def set_driver(self, driver, value, uom=None, report=True):
        """
        Updates the value of one of the node's drivers. This will pass the
        given value through the driver's formatter before assignment.

        :param str driver: The name of the driver
        :param value: The new value for the driver
        :param uom: The given values unit of measurement. This should
                    correspond to the UOM IDs used by the ISY. Refer to the ISY
                    documentation for more information.
        :type uom: int or None
        :param boolean report: Indicates if the value change should be reported
                               to the ISY. If False, the value is changed
                               silently.
        :returns boolean: Indicates success or failure to set new value
        """
        # pylint: disable=unused-argument
        if driver in self._drivers:
            clean_value = self._drivers[driver][2](value)
            if clean_value != self._drivers[driver][0]:
                self._drivers[driver][0] = clean_value
                if report:
                    self.report_driver(driver)
            return True
        return False

    def report_driver(self, driver=None):
        """
        Reports a driver's current value to ISY

        :param driver: The name of the driver to report. If None, all drivers
                       are reported.
        :type driver: str or None
        :returns boolean: Indicates success or failure to report driver value
        """
        if driver is None:
            drivers = self._drivers.keys()
        else:
            drivers = [driver]

        for driver in drivers:
            self.parent.poly.report_status(
                self.address, driver, self._drivers[driver][0],
                self._drivers[driver][1])
        return True

    def get_driver(self, driver=None):
        """
        Gets a driver's value

        :param driver: The driver to return the value for
        :type driver: str or None
        :returns: The current value of the driver
        """
        if driver is not None:
            return self._drivers[driver]
        else:
            return self._drivers

    def query(self):
        """
        Abstractly queries the node. This method should generally be
        overwritten in development.

        :returns boolean: Indicates success or failure of node query
        """
        self.report_driver()
        return True

    def add_node(self):
        """
        Adds node to the ISY

        :returns boolean: Indicates success or failure of node addition
        """
        if (int(len(self.address)) > 14):
            self.smsg(
                '**ERROR: name too long (>14), will fail when adding on ISY): "{}"'
                .format(self.address))
        self.smsg('**DEBUG: node "%s": parent="%s"' % (self.name,self.parent))
        self.parent.add_node(self)
        self.report_driver()
        return True

    @property
    def manifest(self):
        """
        The node's manifest entry. Indicates the current value of each of the
        drivers. This is called by the node server to create the full manifest.

        :type: dict
        """
        manifest = {'name': self.name,
                    'added': self.added,
                    'enabled': self.enabled,
                    'node_def_id': self.node_def_id,
                    'drivers': {}}

        for key, val in self._drivers.items():
            manifest['drivers'][key] = val[0]

        return manifest


    _drivers = {}
    """
    The drivers controlled by this node. This is a dictionary of lists. The
    key's are the driver names as defined by the ISY documentation. Each list
    contains three values: the initial value, the UOM identifier, and a
    function that will properly format the value before assignment.

    *Insteon Dimmer Example:*

    .. code-block:: python

        _drivers = {
            'ST': [0, 51, int],
            'OL': [100, 51, int],
            'RR': [0, 32, int]
        }

    """

    _commands = {}
    """
    A dictionary of the commands that the node can perform. The keys of this
    dictionary are the names of the command. The values are functions that must
    be defined in the node object that perform the necessary actions and return
    a boolean indicating the success or failure of the command.
    """

    node_def_id = ''
    """ The node's definition ID defined in the node server's profile """


class NodeServer(object):
    """
    It is generally desireable to not be required to bind to each event. For
    this reason, the NodeServer abstract class is available. This class should
    be abstracted. It binds appropriate handlers to the API events and contains
    a suitable run loop. It should serve as a basic structure for any node
    server.

    :param poly: The connected Polyglot connection
    :type poly: polyglot.nodeserver_api.PolyglotConnector
    :param int optional shortpoll: The seconds between poll events
    :param int optional longpoll: The second between longpoll events
    """
    # pylint: disable=unused-argument

    poly = None
    """
    The Polyglot Connection

    :type: polyglot.nodeserver_api.PolyglotConnector
    """

    def __init__(self, poly, shortpoll=1, longpoll=30):
        # create/store properties
        self.poly = poly
        self.config = {}
        self.running = False
        self.shortpoll = shortpoll
        self.longpoll = longpoll
        self.logger = None
        self._is_node_server = True
        self._seq = 1000
        self._seq_lock = threading.Lock()
        self._seq_cb = {}

        # bind callbacks to events
        poly.listen('config', self.on_config)
        poly.listen('install', self.on_install)
        poly.listen('query', self.on_query)
        poly.listen('status', self.on_status)
        poly.listen('add_all', self.on_add_all)
        poly.listen('added', self.on_added)
        poly.listen('removed', self.on_removed)
        poly.listen('renamed', self.on_renamed)
        poly.listen('enabled', self.on_enabled)
        poly.listen('disabled', self.on_disabled)
        poly.listen('cmd', self.on_cmd)
        poly.listen('exit', self.on_exit)
        poly.listen('result', self.on_result)

    def setup(self):
        """
        Setup the node server.  All node servers must override this method and 
        call it thru super.
        Currently it only sets up the reference for the logger.
        """
        self.logger = self.poly.logger
        
    def smsg(self, str):
        """
        Logs/sends a diagnostic/debug, informative, or error message.
        Individual node servers can override this method if they desire to
        redirect or filter these messages.
        """
        self.poly.send_error(str)

    def on_config(self, **data):
        """
        Received configuration data from Polyglot

        :param dict data: Configuration data
        :returns bool: True on success
        """
        self.config = data
        return True

    def on_install(self, profile_number):
        """
        Received install command from ISY

        :param int profile_number: Noder Server's profile number
        :returns bool: True on success
        """
        # pylint: disable=no-self-use
        return False

    def on_query(self, node_address, request_id=None):
        """
        Received query command from ISY

        :param str node_address: The address of the node to act on
        :param str optional request_id: Status request id
        :returns bool: True on success
        """
        # pylint: disable=no-self-use
        return False

    def on_status(self, node_address, request_id=None):
        """
        Received status command from ISY

        :param str node_address: The address of the node to act on
        :param str optional request_id: Status request id
        :returns bool: True on success
        """
        # pylint: disable=no-self-use
        return False

    def on_add_all(self, request_id=None):
        """
        Received add all command from ISY

        :param str optional request_id: Status request id
        :returns bool: True on success
        """
        # pylint: disable=no-self-use
        return False

    def on_added(self, node_address, node_def_id, primary_node_address, name):
        """
        Received node added report from ISY

        :param str node_address: The address of the node to act on
        :param str node_def_id: The node definition id
        :param str primary_node_address: The node server's primary node address
        :param str name: The node's friendly name
        :param str optional request_id: Status request id
        :returns bool: True on success
        """
        # pylint: disable=no-self-use
        return False

    def on_removed(self, node_address):
        """
        Received node removed report from ISY

        :param str node_address: The address of the node to act on
        :returns bool: True on success
        """
        # pylint: disable=no-self-use
        return False

    def on_renamed(self, node_address, name):
        """
        Received node renamed report from ISY

        :param str node_address: The address of the node to act on
        :param str name: The node's friendly name
        :returns bool: True on success
        """
        # pylint: disable=no-self-use
        return False

    def on_enabled(self, node_address):
        """
        Received node enabled report from ISY

        :param str node_address: The address of the node to act on
        :returns bool: True on success
        """
        # pylint: disable=no-self-use
        return False

    def on_disabled(self, node_address):
        """
        Received node disabled report from ISY

        :param str node_address: The address of the node to act on
        :returns bool: True on success
        """
        # pylint: disable=no-self-use
        return False

    def on_cmd(self, node_address, command, value=None, uom=None,
               request_id=None, **kwargs):
        """
        Received run command from ISY

        :param str node_address: The address of the node to act on
        :param str command: The command to run
        :param optional value: The value of the command's unnamed parameter
        :param optional uom: The units of measurement for the unnamed parameter
        :param str optional request_id: Status request id
        :param optional <pN>.<uomN>: The value of parameter pN with units uomN
        :returns bool: True on success
        """
        # pylint: disable=no-self-use
        return False

    def on_exit(self, *args, **kwargs):
        """
        Polyglot has triggered a clean shutdown. Generally, this method does
        not need to be orwritten.

        :returns bool: True on success
        """
        self.running = False
        return True

    def on_result(self, seq, status_code, elapsed, text=None):
        """
        Handles a result message, which contains the result from a REST API
        call to the ISY.  The result message is uniquely identified by the
        seq id, and will always contain at least the numeric status.
        """
        if seq not in self._seq_cb:
            self.smsg('**ERROR: on_result: missing callback for seq={}'.format(seq))
            return False
        func, args = self._seq_cb.pop(seq)
        return func(seq=seq, status_code=status_code, elapsed=elapsed, text=text, **args)

    def register_result_cb(self, func, **kwargs):
        """
        Registers a callback function to handle a result.
        Returns the unique sequence ID to be passed to the function whose
        result is to be handled by the registered callback.

        """
        self._seq_lock.acquire()
        try:
            self._seq += 1
            s = self._seq
        finally:
            self._seq_lock.release()
        self._seq_cb[s] = [func, kwargs]
        return s

    def add_node(self, node_address, node_def_id, node_primary_addr,
                 node_name, callback=None, timeout=None, **kwargs):
        """
        Add this node to the polyglot

        :returns bool: True on success
        """
        seq = None
        if callback:
            seq = self.register_result_cb(callback, **kwargs)
        self.poly.add_node(node_address, node_def_id, node_primary_addr,
                           node_name, timeout, seq)
        return True

    def restcall(self, api, callback=None, timeout=None, **kwargs):
        """
        Sends an asynchronous REST API call to the ISY.
        Returns the unique seq id (that can be used to match up the result
        later on after the REST call completes).
        """
        if callback:
            seq = self.register_result_cb(callback, **kwargs)
        self.poly.restcall(api, timeout, seq)
        return seq

    def tock(self):
        """ Called every few seconds for internal housekeeping. """
        # pylint: disable=no-self-use
        pass

    def poll(self):
        """ Called every shortpoll seconds to allow for updating nodes. """
        # pylint: disable=no-self-use
        pass

    def long_poll(self):
        """ Called every longpoll seconds for less important polling. """
        # pylint: disable=no-self-use
        pass
        
    def run(self):
        """
        Run the Node Server. Exit when triggered. Generally, this method should
        not be overwritten.
        """
        self.running = True
        self.poly.connect()
        scounter = 0
        lcounter = 0
        tcounter = 0
        try:
            while self.running:
                time.sleep(1)
                scounter += 1
                lcounter += 1
                tcounter += 1

                if scounter >= self.shortpoll:
                    self.poll()
                    scounter = 0

                if lcounter >= self.longpoll:
                    self.long_poll()
                    lcounter = 0

                if tcounter >= 7:
                    self.tock()
                    tcounter = 0

        except KeyboardInterrupt:
            self.on_exit()

        self.poly.exit()


class SimpleNodeServer(NodeServer):
    """
    Simple Node Server with basic functionality built-in. This class inherits
    from :class:`polyglot.nodeserver_api.NodeServer` and is the best starting
    point when developing a new node server. This class implements the idea of
    manifests which are dictionaries that contain the relevant information
    about all of the nodes. The manifest gets sent to Polyglot to be saved as
    part of the configuration. This allows the node server to automatically
    recall its last known values when it is restarted.

    .. decorated
    """

    _rest_response = {}

    nodes = OrderedDict()
    """
    Nodes registered with this node server.  All nodes are automatically added
    by the add_node method.  The keys are the node IDs while the values are 
    instances of :class:`polyglot.nodeserver_api.Node`. Classes inheriting
    can access this directly, but the prefered method is by using get_node or
    exist_node methods.
    """
    @auto_request_report
    def add_node(self, node):
        """
        Add node to the Polyglot and the nodes dictionary.

        :param node: The node to add
        :type node: polyglot.nodeserver_api.Node
        :returns boolean: Indicates success or failure of node addition
        """
        na = node.address
        if na not in self.nodes:
            self.nodes[na] = node
        if not self.nodes[na].added:
            # By default the primary_address is its own address...
            primary_addr = na
            # ...unless a node was passed in as the primary.
            if node.primary is not True:
                # A primary node must be its own primary because ISY only
                # supports one level deep.
                if not node.primary.primary is True:
                    raise RuntimeError('Error: node "%s", primary "%s" is not primary.'
                                       % (node.name, node.primary.name))
                primary_addr = node.primary.address
            self.smsg('**DEBUG: add_node: na="{}", id="{}", pa="{}", nm="{}"'
                      .format(na, node.node_def_id, primary_addr, node.name))
            super(SimpleNodeServer, self).add_node(na, node.node_def_id,
                                                   primary_addr, node.name,
                                                   self._add_node_cb, None,
                                                   na=na)
        return True

    def tock(self):
        all_nodes = list(self.nodes.keys())
        if len(all_nodes) > 0:
            t = int(time.time())
            next_t = t + 600 + (7 * self.poly.profile)
            for node in self.nodes.values():
                next_t += 7
                if node.probe_t < t:
                    # Request the check - sends rest api call
                    self.request_node_probe(node.address)
                    # Mark node for next check
                    node.probe_t = next_t
        # [TODO] extend probe for unknown nodes
        return True

    def request_node_probe(self, node_address, timeout=None):
        pfx = str(self.poly.profile).zfill(3)
        full_addr = 'n{}_{}'.format(pfx, node_address)
        api = 'nodes/' + full_addr
        self.smsg('**DEBUG: request_node_probe: na="{}" fa="{}" api="{}"'
                  .format(node_address, full_addr, api))
        return super(SimpleNodeServer, self).restcall(
            api, self.node_probe_response, timeout, na=node_address)

    def node_probe_response(self, status_code, text, na, **kwargs):

        self.smsg('**DEBUG: probe: st={} na="{}" text: {}'
                  .format(status_code, na, text))

        if na in self.nodes:
            node = self.nodes[na]
        else:
            self.smsg('**ERROR: probe: node "{}" does not exist'.format(na))
            # No action practical for this problem
            return False

        if status_code != 200:
            self.smsg('**WARNING: probe: status code: {}'.format(status_code))
            if status_code == 404 and node.added:
                self.smsg('**WARNING: probe: na="{}": state mismatch'.format(na))
                self.smsg('**WARNING: probe: ISY does not think this node exists')
                self.smsg('**WARNING: probe: Correcting local node state')
                node.enabled = False
                node.added = False
            return True

        # Parse the XML response text from the ISY
        try:
            root = ET.fromstring(text)
        except ET.ParseError:
            self.smsg('**ERROR: probe: Unable to parse ISY response: {}'
                      .format(text))
            # No action practical for this problem
            return False

        # Find the root node element
        n = root.find('node')
        if n is None:
            self.smsg('**ERROR: probe: missing node element in response: {}'
                      .format(text))
            # No action practical for this problem
            return False

        # Extract all the other fields we're interested in
        n_def_id = n.attrib.get('nodeDefId', None)
        n_flag = n.attrib.get('flag', '0')
        n_addr = n.findtext('address')
        n_name = n.findtext('name')
        n_pnode = n.findtext('pnode')
        n_enabled = (n.findtext('enabled', 'false') == 'true')
        self.smsg('**INFO: probe: fa={} pfa={} id={} fl={} en={} nm="{}"'
                  .format(n_addr, n_pnode, n_def_id, n_flag,
                          n_enabled, n_name))

        # Check that the fields match our node

        pfx = str(self.poly.profile).zfill(3)
        full_addr = 'n{}_{}'.format(pfx, node.address)
        if full_addr != n_addr:
            self.smsg('**ERROR: probe: expected na="{}", response is for na="{}"'
                      .format(full_addr, n_addr))
            # No action practical for this problem
            return False

        if node.node_def_id != n_def_id:
            self.smsg('**ERROR: probe: expected id="{}", response is for id="{}"'
                      .format(node.node_def_id, n_def_id))
            self.smsg('**ERROR: probe: setting local node state to "not added"')
            node.enabled = False
            node.added = False
            return True

        if node.primary is not True:
            primary_addr = node.primary.address
        else:
            primary_addr = node.address
        full_paddr = 'n{}_{}'.format(pfx, primary_addr)
        if full_paddr != n_pnode:
            self.smsg('**ERROR: probe: node parent mismatch, local: "{}" ISY: "{}"'
                      .format(full_paddr, n_pnode))
            self.smsg('**ERROR: probe: setting local node state to "not added"')
            node.enabled = False
            node.added = False
            return True

        if not node.added:
            self.smsg('**WARNING: probe: node state mismatch - node is added on ISY')
            self.smsg('**WARNING: probe: correcting local node state')
            node.added = True

        if node.name != n_name:
            self.smsg('**WARNING: probe: node name mismatch, local: "{}" ISY: "{}"'
                      .format(node.name, n_name))
            self.smsg('**WARNING: probe: correcting local node name')
            node.name = n_name;

        if node.enabled != n_enabled:
            self.smsg('**WARNING: probe: node enable mismatch, local:"{}" ISY:"{}"'
                      .format(node.enabled, n_enabled))
            self.smsg('**WARNING: probe: correcting local node state')
            node.enabled = n_enabled;

        return True

    def restcall(self, api, timeout=None):
        self.smsg('**DEBUG: restcall: api="{}"'.format(api))
        return super(SimpleNodeServer, self).restcall(
            api, self._save_rest_response, timeout)

    def get_rest_response(self, seq):
        return self._rest_response.pop(seq, None)

    def _save_rest_response(self, **kwargs):
        seq = kwargs['seq']
        self._rest_response[seq] = kwargs
        return True

    def _add_node_cb(self, na, status_code, **kwargs):
        if int(status_code) == 200:
            if na in self.nodes:
                self.nodes[na].added = True
                self.smsg(
                    '**INFO: node "{}": node successfully added on ISY'
                    .format(na))
                return True
            else:
                self.smsg(
                    '**ERROR: node "{}": node added on ISY, but no longer exists.'
                    .format(na))
        else:
            self.smsg(
                '**ERROR: node "{}": node add REST call to ISY failed: {}'
                .format(na, status_code))
        return False

    def _enable_node(self, address):
        # Ensure the addressed node is enabled, and if the state changes
        # then force the configuration file update to record same
        if not self.nodes[address].enabled:
            self.nodes[address].enabled = True
            self.smsg('**INFO: node "{}" enabled'.format(address))
            self.update_config()
            self.probe_t = 0

    def _disable_node(self, address):
        # Ensure the addressed node is disabled - as above
        if self.nodes[address].enabled:
            self.nodes[address].enabled = False
            self.smsg('**INFO: node "{}" disabled'.format(address))
            self.update_config()
            self.probe_t = 0

    def get_node(self, address):
        """
        Get a node by its address.

        :param str address: The node address
        :returns polyglot.nodeserver_api.Node: If found, otherwise False
        """
        if address in self.nodes:
            return self.nodes[address]
        return False

    def exist_node(self, address):
        """
        Check if a node exists by its address.

        :param str address: The node address
        :returns bool: True if the node exists
        """
        if address in self.nodes:
            return True
        return False

    def update_config(self, replace_manifest=False):
        """
        Updates the configuration with new node manifests and sends
        the configuration to Polyglot to be saved.

        :param boolean replace_manifest: replace or merge existing manifest
        """
        if replace_manifest:
            output = OrderedDict()
        else:
            output = self.config.get('manifest', OrderedDict())
        for node_addr, node in self.nodes.items():
            output[node.address] = node.manifest
        self.config['manifest'] = output
        self.poly.send_config(self.config)

    def on_enabled(self, node_address):
        """
        Received node enabled report from ISY

        :param str node_address: The address of the node to act on
        :returns bool: True on success
        """
        self._enable_node(node_address)
        return True

    def on_disabled(self, node_address):
        """
        Received node disabled report from ISY

        :param str node_address: The address of the node to act on
        :returns bool: True on success
        """
        self._disable_node(node_address)
        return True

    @auto_request_report
    def on_query(self, node_address, request_id=None):
        """
        Queries each node and reports all control values to the ISY. Also
        responds to report requests if necessary.

        :param str node_address: The address of the node to act on
        :param str optional request_id: Status request id
        :returns bool: True on success
        """
        if node_address in self.nodes:
            self._enable_node(node_address)
            return self.nodes[node_address].query()
        elif node_address == "0":
            return all([node.query() for node in self.nodes.values()])
        else:
            self.smsg('**ERROR: on_query: node "{}" does not exist'
                      .format(node_address))
        return False

    @auto_request_report
    def on_status(self, node_address, request_id=None):
        """
        Reports the requested node's control values to the ISY without forcing
        a query. Also sends requests reponses when necessary.

        :param str node_address: The address of the node to act on
        :param str optional request_id: Status request id
        :returns bool: True on success
        """
        if node_address in self.nodes:
            self._enable_node(node_address)
            return self.nodes[node_address].report_driver()
        elif node_address == "0":
            return all([node.report_driver() for node in self.nodes.values()])
        else:
            self.smsg('**ERROR: on_status: node "{}" does not exist'
                      .format(node_address))
        return False

    @auto_request_report
    def on_add_all(self, request_id=None):
        """
        Adds all nodes to the ISY. Also sends requests reponses when necessary.

        :param str optional request_id: Status request id
        :returns bool: True on success
        """
        all_nodes = list(self.nodes.keys())
        if len(all_nodes) > 0:
            for node in self.nodes.values():
                node.add_node()
        return True

    def on_added(self, node_address, node_def_id, primary_node_address, name):
        """
        Internally indicates that the specified node has been added to the ISY.

        :param str node_address: The address of the node to act on
        :param str node_def_id: The node definition id
        :param str primary_node_address: The node server's primary node address
        :param str name: The node's friendly name
        :param str optional request_id: Status request id
        :returns bool: True on success
        """
        if node_address in self.nodes:
            self.nodes[node_address].added = True
            self.nodes[node_address].enabled = True
            self.nodes[node_address].name = name
            return True
        self.smsg('**ERROR: on_added: node "{}" does not exist'
                  .format(node_address))
        return False

    def on_removed(self, node_address):
        """
        Internally indicates that a node has been removed from the ISY.

        :param str node_address: The address of the node to act on
        :returns bool: True on success
        """
        if node_address in self.nodes:
            self.nodes[node_address].added = False
            self.nodes[node_address].enabled = False
            return True
        self.smsg('**WARNING: on_removed: node "{}" does not exist'
                  .format(node_address))
        return False

    def on_renamed(self, node_address, name):
        """
        Changes the node name internally to match the ISY.

        :param str node_address: The address of the node to act on
        :param str name: The node's friendly name
        :returns bool: True on success
        """
        if node_address in self.nodes:
            orig_name = self.nodes[node_address].name
            self.nodes[node_address].name = name
            self.smsg('**INFO: node "{}" renamed from "{}" to "{}"'
                      .format(node_address, orig_name, name))
            self._enable_node(node_address)
            return True
        self.smsg('**ERROR: on_renamed: node "{}" does not exist'
                  .format(node_address))
        return False

    @auto_request_report
    def on_cmd(self, node_address, command, value=None, uom=None,
               request_id=None, **kwargs):
        """
        Runs the specified command on the specified node. Also sends requests
        reponses when necessary.

        :param str node_address: The address of the node to act on
        :param str command: The command to run
        :param optional value: The value of the command's unnamed parameter
        :param optional uom: The units of measurement for the unnamed parameter
        :param str optional request_id: Status request id
        :param optional <pN>.<uomN>: The value of parameter pN with units uomN
        :returns bool: True on success
        """
        if node_address in self.nodes:
            self._enable_node(node_address)
            return self.nodes[node_address].run_cmd(
                command, value=value, cmd=command, uom=uom, **kwargs)
        self.smsg('**ERROR: on_cmd: node "{}" does not exist for command "{}"'
                  .format(node_address, command))
        return False

    def on_exit(self, *args, **kwargs):
        """
        Triggers a clean shut down of the node server by saving the manifest,
        clearing the IO, and stopping.

        :returns bool: True on success
        """
        # save manifest
        self.update_config()

        # cleanly close
        self.running = False
        return True


class PolyglotConnector(object):
    """
    Polyglot API implementation. Connects to Polyglot and handles node server
    IO.

    :raises: RuntimeError

    .. decorated
    """
    # pylint: disable=too-many-instance-attributes

    commands = ['config', 'install', 'query', 'status', 'add_all', 'added',
                'removed', 'renamed', 'enabled', 'disabled', 'cmd', 'ping',
                'exit', 'params', 'result']
    """ Commands that may be invoked by Polyglot """
    logger = None                
    """ 
    logger is initialized after the node server wait_for_config completes
    by the setup_log method and the log file is located in the node servers
    sandbox.
    Once wait_for_config is complete, you can call
    `poly.logger.info('This variable is set to %s', variable)`
    """
       
    def __init__(self):
        # make singleton
        # pylint: disable=global-statement
        global _POLYGLOT_CONNECTION
        if _POLYGLOT_CONNECTION is not None:
            raise RuntimeError('PolyglotConnector may only be created once.')

        # setup properties
        self._outq = LockQueue()
        self._errq = LockQueue()
        self._handlers = defaultdict(list)
        self._threads = {}
        self._started = time.time()
        self._got_config = False
        self.params = False
        self.isyver = False
        self.sandbox = False
        self.configfile = None
        self.path = None
        self.nodeserver_config = None
        self.name = False
        self.apiver = False
        self.profile = None

        # listen for important events
        self.listen('ping', self.pong)
        self.listen('config', self._recv_config)
        self.listen('params', self.get_params)

        # setup logging - redirect warnings and errors to stderr
        fmt = '%(name)s: %(message)s'
        handler = logging.StreamHandler(sys.stderr)
        handler.setLevel(logging.WARNING)
        handler.setFormatter(logging.Formatter(fmt))

        # store connection globally in module
        _POLYGLOT_CONNECTION = self

    @property
    def uptime(self):
        """
        The number of sections the connection with Polyglot has been alive

        :type: float
        """
        return time.time() - self._started

    # manage connection
    @property
    def connected(self):
        """
        Indicates if the object is connected to Polyglot. Can be set to control
        connection with Polyglot.

        :type: boolean
        """
        return self._threads.get('stdout') \
            and self._threads['stdout'].isAlive()

    @connected.setter
    def connected(self, val):
        """ Setter that connects object to Polyglot """
        if val:
            self.connect()
        else:
            self.disconnect()

    def connect(self):
        """ Connects to Polyglot if not currently connected """
        if not self.connected:
            self._outq.locked = False
            self._errq.locked = False
            self._threads = {}
            self._threads['stdin'] = AsyncFileReader(sys.stdin,
                                                     self._parse_cmd)
            self._threads['stdout'] = threading.Thread(target=self._send_out)
            self._threads['stdout'].daemon = True
            self._threads['stderr'] = threading.Thread(target=self._send_err)
            self._threads['stderr'].daemon = True
            for _, thread in self._threads.items():
                thread.start()

    def disconnect(self):
        """
        Disconnects from Polyglot. Blocks the thread until IO stream is clear
        """
        if self.connected:
            self._outq.locked = True
            self._errq.locked = True
            self._outq.join()
            self._errq.join()
            self._threads = {}

    def wait_for_config(self):
        """ Blocks the thread until the configuration is received """
        while not self._got_config:
            time.sleep(1)
        self.logger = self.setup_log(self.sandbox, self.name)
        self._read_nodeserver_config()

    def _read_nodeserver_config(self):
        """ 
        Reads custom config file and presents it to node server as nodeserver_config 
        """
        if YAML:
            if self.configfile == None: 
                self.smsg('**INFO: No custom "configfile" found in server.json. Trying the default of config.yaml.')
                self.configfile = 'config.yaml'
            else:
                self.smsg('**INFO: Custom config file option found in server.json: {}'.format(self.configfile))
            try:
                with open(os.path.join(self.path, self.configfile), 'r') as cfg:
                    self.nodeserver_config = yaml.safe_load(cfg)
                    self.smsg('**INFO: {} - Config file loaded as dictionary to "poly.nodeserver_config"'.format(self.configfile))
            except yaml.YAMLError, exc:
                if hasattr(exc, 'problem_mark'):
                    mark = exc.problem_mark
                    self.smsg('**ERROR: Error in config file. Position: (Line: {}: Column: {})'.format(mark.line+1, mark.column+1))
                    self.smsg('{} - '.format(exc))
            except IOError as e:
                self.smsg('**INFO: No config file found, or it is unreadable. This is normal if your nodeserver doesn\'t need a config file.')
        else: self.smsg('**ERROR: PyYAML module not installed... skipping custom config sections. "sudo pip install pyyaml" to use')

    def write_nodeserver_config(self, default_flow_style=False, indent=4):
        """
        Writes any changes to the nodeserver custom configuration file. 
        self.nodeserver_config should be a dictionary. Refrain from calling
        this in a poll of any kind. Typically you won't even have to write this
        unless you are storing custom data you want retrieved on the next 
        run. Saved automatically during normal Polyglot shutdown. Returns 
        True for success, False for failure.
        
        :param boolean default_flow_style: YAML's default flow style formatting. Default False
        :param int indent: Override the default indent spaces for YAML. Default 4
        """
        if YAML:
            try:
                with open(os.path.join(self.path, self.configfile), 'r') as read:
                    existing = yaml.safe_load(read)
                    if existing == self.nodeserver_config: 
                        self.smsg('**INFO: NodeServer configuration file matches running config... Skipping write.')
                        return True
                with open(os.path.join(self.path, self.configfile), 'w') as write:
                    yaml.dump(self.nodeserver_config, write, default_flow_style=default_flow_style, indent=indent)
                    self.smsg('**INFO: NodeServer configuration file is different than running config... Updated file.')
                    return True
            except yaml.YAMLError as e:
                self.logger.error('**ERROR: write_nodeserver_config: {}'.format(e))
                return False
            except IOError:
                self.smsg('**ERROR: write_nodeserver_config: Could not write to nodeserver config file {}'.format(self.configfile))
                return False
        else: self.smsg('**ERROR: PyYAML module not installed... skipping custom config sections. "sudo pip install pyyaml" to use')
        return True

    # manage output
    def _send_out(self):
        """ Send output through pipe """
        while not self._outq.locked or not self._outq.empty():
            try:
                line = self._outq.get(True, 5)
            except Empty:
                pass
            else:
                sys.stdout.write('{}\n'.format(line))
                self._outq.task_done()
                sys.stdout.flush()

    def _send_err(self):
        """ Send error through pipe """
        while not self._errq.locked or not self._errq.empty():
            try:
                line = self._errq.get(True, 5)
            except Empty:
                pass
            else:
                sys.stderr.write('{}\n'.format(line))
                self._errq.task_done()
                sys.stderr.flush()

    # manage input
    def _parse_cmd(self, cmd):
        """
        Parses a received command.

        :param cmd: String command received from Polyglot
        """
        if len(cmd) >= 2:
            # parse command
            try:
                cmd = json.loads(cmd)
            except ValueError:
                self.send_error('Received badly formatted command ' +
                                '(not json): {}'.format(cmd))
                return False

            # split command
            try:
                cmd_code = list(cmd.keys())[0]
                args = cmd[cmd_code]
            except (KeyError, IndexError):
                self.send_error('Received badly formatted command: {} '
                                .format(cmd))
                return False

            # validate command
            if cmd_code not in self.commands:
                self.send_error('Received invalid command: {}'.format(cmd))
                return False

            # execute command
            return self._recv(cmd_code, args)

    def _recv(self, cmd_code, data):
        """
        Handle command was received.

        :param cmd: The command that has been received
        :param data: Dictionary of received data
        """
        # pylint: disable=broad-except
        success = []
        for fun in self._handlers[cmd_code]:
            try:
                success.append(fun(**data))
            except Exception as err:
                if '--debug' in sys.argv:
                    raise err
                else:
                    err_msg = repr(err).replace('\n', '')
                    fun_name = fun.__name__
                    self.send_error('Error handling {} in function {}: {}'
                                    .format(cmd_code, fun_name, err_msg) + traceback.format_exc())
            else:
                if not success[-1]:
                    fun_name = fun.__name__
                    self.send_error('Unsuccessful handling {} in function {}'
                                    .format(cmd_code, fun_name))
        return all(success)

    def _recv_config(self, *args, **kwargs):
        """ note that the config has been received. """
        # pylint: disable=unused-argument
        self._got_config = True
        return True

    def get_params(self, **kwargs):
        """ Get the params from nodeserver and makes them available to
        the nodeserver api """
        self.isyver = kwargs['isyver']
        self.sandbox = kwargs['sandbox']
        self.name = kwargs['name']
        self.pgver = kwargs['pgver']
        self.pgapiver = kwargs['pgapiver']
        self.profile = kwargs['profile']
        self.configfile = kwargs['configfile']
        self.path = kwargs['path']
        return True

    def setup_log(self, sandbox, name):
        # Setup logger for individual nodeservers, log to
        # /config/<nodeserver-name>
        self.log_filename = sandbox + "/" + name + ".log"
        # Could be "DEBUG", "WARNING", or "INFO"
        log_level = logging.DEBUG
        logger = logging.getLogger(name)
        logger.setLevel(log_level)
        # Make a handler that writes to a file,
        # making a new file at midnight, and keeping 30 backups
        handler = logging.handlers.TimedRotatingFileHandler(
            self.log_filename, when="midnight", backupCount=30)
        # Format each log message like this
        formatter = logging.Formatter(
            '%(asctime)s %(levelname)-8s %(name)s %(message)s')
        # Attach the formatter to the handler
        handler.setFormatter(formatter)
        # Attach the handler to the logger
        logger.addHandler(handler)
        return logger
       
    # create output
    def _mk_cmd(self, cmd_code, **kwargs):
        """
        Enqueue a command to be sent back to Polyglot.

        :param cmd_code: Command code
        :param args: arguments to send with command
        """
        cmd = json.dumps({cmd_code: kwargs})
        self._outq.put(cmd, True, 5)

    def send_error(self, err_str):
        """
        Enqueue an error to be sent back to Polyglot.

        :param str err_str: Error text to be sent to Polyglot log
        """
        self._errq.put(err_str.replace('\n', ''), True, 5)
        
    def smsg(self, str):
        """
        Logs/sends a diagnostic/debug, informative, or error message.
        Individual node servers can override this method if they desire to
        redirect or filter these messages.
        """
        self.send_error(str)

    def send_config(self, config_data):
        """
        Update the configuration in Polyglot.

        :param dict config_data: Dictionary of updated configuration
        :raises: ValueError
        """
        if isinstance(config_data, dict):
            self._mk_cmd('config', **config_data)
            return True
        raise ValueError('send_config: config_data must be dictionary')

    def install(self, *args, **kwargs):
        """
        Abstract method to install the node server in the ISY. This has not
        been implemented yet and running it will raise an error.

        :raises: NotImplementedError
        """
        # [future] implement when documentation is available
        raise NotImplementedError('install function has not been implemented')

    def report_status(self, node_address, driver_control, value, uom,
                      timeout=None, seq=None):
        """
        Updates the ISY with the current value of a driver control (e.g. the
        current temperature, light level, etc.)

        :param  str node_address: The full address of the node (e.g.
                                  'dimmer_1')
        :param str driver_control: The name of the status value (e.g. 'ST',
                                   'CLIHUM', etc.)
        :param value: The numeric status value (e.g. '80.5')
        :type value: str, float, or int
        :param uom: Unit of measure of the status value
        :type uom: int or str
        :param timeout: (optional) timeout (seconds) for REST call to ISY
        :type timeout: str, float, or int
        :param seq: (optional) set to unique id if result callback desired
        :type seq: str or int
        """
        self._mk_cmd('status', node_address=node_address,
                     driver_control=driver_control, value=value, uom=uom,
                     timeout=timeout, seq=seq)

    def report_command(self, node_address, command, value=None, uom=None,
                       timeout=None, seq=None, **kwargs):
        """
        Sends a command to the ISY that may be used in programs and/or scenes.
        A common use of this is a physical switch that somebody turns on or
        off. Each time the switch is used, a command should be reported to the
        ISY. These are used for scenes and control conditions in ISY programs.

        :param str node_address: The full address of the node (e.g. 'switch_1)
        :param str command: The command to perform (e.g. 'DON', 'CLISPH', etc.)
        :param value: Optional unnamed value the command used
        :type value: str, int, or float
        :param uom: Optional units of measurement of value
        :type uom: int or str
        :param timeout: (optional) timeout (seconds) for REST call to ISY
        :type timeout: str, float, or int
        :param seq: (optional) set to unique id if result callback desired
        :type seq: str or int
        :param optional <pN>.<uomN>: Nth Parameter name (e.g. 'level') . Unit
                                     of measure of the Nth parameter
                                     (e.g. 'seconds', 'uom58')
        """
        kwargs.update({'node_address': node_address, 'command': command})
        if value is not None:
            kwargs['value'] = value
        if uom is not None:
            kwargs['uom'] = uom
        if timeout is not None:
            kwargs['timeout'] = timeout
        if seq is not None:
            kwargs['seq'] = seq
        self._mk_cmd('command', **kwargs)

    def add_node(self, node_address, node_def_id, primary, name,
                 timeout=None, seq=None):
        """
        Adds a node to the ISY. To make this node the primary, set primary to
        the same value as node_address.

        :param str node_address: The full address of the node (e.g.
                                 'dimmer_1')
        :param str node_def_id: The id of the node definition to use for this
                                node
        :param str primary: The primary node for the device this node
                            belongs to
        :param str name: The name of the node
        :param timeout: (optional) timeout (seconds) for REST call to ISY
        :type timeout: str, float, or int
        :param seq: (optional) set to unique id if result callback desired
        :type seq: str or int
        """
        args = {'node_address': node_address, 'node_def_id': node_def_id,
                'primary': primary, 'name': name}
        if timeout is not None:
            args['timeout'] = timeout
        if seq is not None:
            args['seq'] = seq
        self._mk_cmd('add', **args)

    def change_node(self, node_address, node_def_id,
                    timeout=None, seq=None):
        """
        Changes the node definition to use for an existing node. An example of
        this is may be to change a thermostat node from Fahrenheit to Celsius.

        :param str node_address: The full address of the node (e.g.
                                 'dimmer_1')
        :param str node_def_id: The id of the node definition to use for this
                                node
        :param timeout: (optional) timeout (seconds) for REST call to ISY
        :type timeout: str, float, or int
        :param seq: (optional) set to unique id if result callback desired
        :type seq: str or int
        """
        self._mk_cmd('change', node_address=node_address,
                     node_def_id=node_def_id,
                     timeout=timeout, seq=seq)

    def remove_node(self, node_address, timeout=None, seq=None):

        """
        Removes a node from the ISY. A node cannot be removed if it is the
        primary node for at least one other node.

        :param str node_address: The full address of the node (e.g.
                                 'dimmer_1')
        :param timeout: (optional) timeout (seconds) for REST call to ISY
        :type timeout: str, float, or int
        :param seq: (optional) set to unique id if result callback desired
        :type seq: str or int
        """
        self._mk_cmd('remove', node_address=node_address,
                     timeout=timeout, seq=seq)

    def report_request_status(self, request_id, success,
                              timeout=None, seq=None):
        """
        When the ISY sends a request to the node server, the request may
        contain a 'requestId' field. This indicates to the node server that
        when the request is completed, it must send a fail or success report
        for that request. This allows the ISY to in effect, have the node
        server synchronously perform tasks. This message must be sent after all
        other messages related to the task have been sent.

        For example, if the ISY sends a request to query a node, all the
        results of the query must be sent to the ISY before a fail/success
        report is sent.

        :param str request_id: The request ID the ISY supplied on a request to
                               the node server.
        :param bool success: Indicates if the request was sucessful
        :param timeout: (optional) timeout (seconds) for REST call to ISY
        :type timeout: str, float, or int
        :param seq: (optional) set to unique id if result callback desired
        :type seq: str or int
        """
        self._mk_cmd('request', request_id=request_id, success=success,
                     timeout=timeout, seq=seq)


    def restcall(self, api, timeout=None, seq=None):

        """
        Calls a RESTful api on the ISY.  The api is the portion of
        the url after the "https://isy/rest/" prefix.

        :param str api: The url for the api to call
        :param timeout: (optional) timeout (seconds) for REST call to ISY
        :type timeout: str, float, or int
        :param seq: (optional) set to unique id if result callback desired
        :type seq: str or int
        """
        self._mk_cmd('restcall', api=api, timeout=timeout, seq=seq)

    def pong(self, *args, **kwargs):
        """
        Sends pong reply to Polyglot's ping request. This verifies that the
        communication between the Node Server and Polyglot is functioning.
        """
        # pylint: disable=unused-argument
        self._mk_cmd('pong')
        return True
        
    def exit(self, *args, **kwargs):
        """
        Tells Polyglot that this Node Server is done.
        """
        # pylint: disable=unused-argument
        self.write_nodeserver_config()
        self._mk_cmd('exit')
        self.disconnect()
        return True

    # manage handlers
    def listen(self, event, handler):
        """
        Register an event handler. Returns True on success. Event names are
        defined in `commands`. Handlers must be callable.

        :param str event: Then event name to listen for.
        :param callable handler: The callable event handler.
        """
        if event not in self.commands:
            return False
        if not callable(handler):
            return False

        self._handlers[event].append(handler)
        return True
