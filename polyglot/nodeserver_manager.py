''' The element management module for Polyglot '''

from collections import OrderedDict
import copy
import json
import logging
import os
from polyglot import SOURCE_DIR
from polyglot.utils import AsyncFileReader, Queue, Empty, MyProcessLookupError
from polyglot.version import PGVERSION
import polyglot.nodeserver_helpers as helpers
import random
import string
import subprocess
import sys
import threading
import time

_LOGGER = logging.getLogger(__name__)
# import the paho.mqtt.client
MQTT = False
try:
    import paho.mqtt.client as mqtt
    MQTT = True
except ImportError as e:
    _LOGGER.error('Interface was mqtt however paho.mqtt.client module not found.')

ELEMENT = 'core'
SERVER_TYPES = {'python': [sys.executable],
                'node': ['/usr/bin/node']}
NS_QUIT_WAIT_TIME = 5

# Global manager diagnostics/performance data structures
NSLOCK = threading.Lock()
NSMGR = None
NSSTATS = {}

# Increment this version number each time a breaking change is made or a
# major new message (feature) is added to the API between the node server
# manager (implemented by this source file) and its clients.
# This allows the client an opportunity to adjust its behavior to suit the
# installed version of Polyglot -- keep in mind that the client node server
# is independent of Polyglot, and may not even be implemented in Python --
# and thus has no other way to know about the Polyglot server itself.
PGAPIVER = '1'

class NodeServerManager(object):
    """
    Node Server Manager

    :param pglot: The parent Polyglot object

    :ivar pglot: The parent Polyglot object
    :ivar servers: Dictionary of active Node Servers
    """

    servers = OrderedDict()

    def __init__(self, pglot):
        self.pglot = pglot

    def __getitem__(self, key):
        """ Get server by base name. """
        return self.servers[key]

    @property
    def config(self):
        """ Node Server configuration block. """
        output = []
        for nsbase_url, nodeserver in self.servers.items():
            output.append({'platform': nodeserver.platform,
                           'url_base': nsbase_url,
                           'name': nodeserver.name,
                           'profile_number': nodeserver.profile_number,
                           'config': nodeserver.config})
        return output

    def start_server(self, ns_platform, profile_number, nsname=None, base=None,
                     config=None):
        """ starts a node server """
        # pylint: disable=broad-except
        _LOGGER.info('Starting Node Server: %s:%s', ns_platform, nsname)
        # find node server
        path = helpers.get_path(ns_platform)
        interface, mqtt_server, mqtt_port = (None,)*3
        # read node server attributes
        try:
            def_file = os.path.join(path, 'server.json')
            definition = json.loads(open(def_file).read())
        except (IOError, ValueError, KeyError):
            raise ValueError("Error reading server.json for {}".format(path))

        # parse server attributes
        try:
            nstype = definition['type']
            nsexe = os.path.join(path, definition['executable'])
        except KeyError:
            raise ValueError(
                "server.json for {} is missing type or executable."
                .format(ns_platform))

        try:
            configfile = definition['configfile']
            _LOGGER.info('Config file option found in server.json: %s', configfile)
        except (IOError, ValueError, KeyError):
            _LOGGER.info('Config file option not found in server.json')
            configfile = None

        try:
            interface = definition['interface'].lower()
            if interface != 'mqtt': 
                interface = 'Default'
                _LOGGER.info('Using interface type ' + interface)
            else:
                mqtt_server = definition['mqtt_server']
                mqtt_port = definition['mqtt_port']
                _LOGGER.info('Using interface type ' + interface + ' at ' + mqtt_server+ ":" + mqtt_port)
        except (IOError, ValueError, KeyError):
            interface = 'Default'
            _LOGGER.info('Using interface type ' + interface)

        # get server base name
        while base in self.servers or base is None:
            base = random_string(5)

        # create sandbox
        sandbox = self.pglot.config.nodeserver_sandbox(ns_platform)

        # create server
        try:
            server = NodeServer(self.pglot, ns_platform, profile_number,
                                nstype, nsexe, nsname or ns_platform,
                                config or {}, sandbox, configfile,
                                interface, mqtt_server, mqtt_port)
        except Exception:
            _LOGGER.exception('Node Server %s could not start', ns_platform)
            raise ValueError(
                "Error starting Node Server: {}.", ns_platform)

        # store server
        self.servers[base] = server
        return True

    def load(self):
        """ Initial load of the active Node Servers """
        _LOGGER.info('Loading Node Servers')

        nsconfigs = self.pglot.config.get("nodeservers", [])
        for count, nsconfig in enumerate(nsconfigs, 1):
            ns_platform = nsconfig.get("platform", None)
            profile_number = nsconfig.get("profile_number", None)
            url_base = nsconfig.get("url_base", None)
            name = nsconfig.get("name", ns_platform)
            config = nsconfig.get("config", {})

            if None in [ns_platform, profile_number]:
                _LOGGER.error(
                    'Bad Node Server configuration in config file. ' +
                    'Node Server %d', count)
            else:
                try:
                    self.start_server(
                        ns_platform, profile_number, name, url_base, config)
                except ValueError as err:
                    _LOGGER.error(err.args[0])

    def delete(self, base_url):
        """ Remove a server from Polyglot. """
        node_server = self.servers[base_url]
        node_server.send_exit()

        for _ in range(10):
            if not node_server.alive:
                break
            time.sleep(0.5)
        else:
            node_server.kill()

        del self.servers[base_url]

    def unload(self):
        """ Unload all node servers """
        # request node server shutdowns
        for node_server in self.servers.values():
            node_server.send_exit()

        # wait for node servers to quit gracefully
        ns_running = any([node_server.alive
                          for node_server in self.servers.values()])
        timer = 0
        while ns_running and timer < NS_QUIT_WAIT_TIME:
            time.sleep(1)
            timer += 1
            ns_running = any([node_server.alive
                              for node_server in self.servers.values()])

        # kill any remaining node servers
        for node_server in self.servers.values():
            if node_server.alive:
                node_server.kill()
                _LOGGER.warning(
                    'Timed out waiting for Node Server %s to quit. ' +
                    'Terminated Node Server.', node_server.name)

        _LOGGER.info('Unloaded Node Servers')


class NodeServer(object):
    """ Node Server Class """
    # pylint: disable=too-many-instance-attributes

    def __init__(self, pglot, ns_platform, profile_number, nstype, nsexe,
                 nsname, config, sandbox, configfile=None, interface=None,
                 mqtt_server=None, mqtt_port=None):
        # build run command
        if nstype in SERVER_TYPES:
            cmd = copy.deepcopy(SERVER_TYPES[nstype])
        else:
            _LOGGER.error("Unrecognized server type %s for %s", nstype,
                          ns_platform)
            raise TypeError('bad server type')
        cmd.append(nsexe)

        self.pglot = pglot
        self.isy_version = self.pglot.isy_version
        self.config = config
        self.configfile = configfile
        self._cmd = cmd
        self.platform = ns_platform
        self.profile_number = profile_number
        self.type = nstype
        self.exe = nsexe
        self.path = os.path.dirname(nsexe)
        self.name = nsname
        self.sandbox = sandbox
        self.interface = interface
        self.mqtt_server = mqtt_server
        self.mqtt_port = mqtt_port
        self.node_connected = False
        self.pgver =  PGVERSION
        self.pgapiver = PGAPIVER
        self.params = {'isyver':   self.isy_version,
                       'sandbox':  self.sandbox,
                       'name':     self.name,
                       'pgver':    self.pgver,
                       'pgapiver': self.pgapiver,
                       'profile':  self.profile_number,
                       'configfile': self.configfile,
                       'path': self.path,
                       'interface': self.interface,
                       'mqtt_server': self.mqtt_server,
                       'mqtt_port': self.mqtt_port}
        self._proc = None
        self._inq = None
        self._rqq = None
        self._mqtt = None
        self._lastping = None
        self._lastpong = None

        # define handlers
        isy = self.pglot.elements.isy
        self._handlers = {'status': isy.report_node_status,
                          'command': isy.report_command,
                          'add': isy.node_add,
                          'change': isy.node_change,
                          'remove': isy.node_remove,
                          'restcall': isy.restcall,
                          'request': isy.report_request_status}

        self.start()

    def start(self):
        """ start the node server """
        # start process
        proc = subprocess.Popen(
            self._cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, bufsize=1, env={'PYTHONPATH': SOURCE_DIR},
            cwd=self.sandbox)

        self._proc = proc
        self._inq = Queue()
        self._rqq = Queue(maxsize=4096)
        self._lastping = None
        self._lastpong = None

        # Create threads dictionary
        self._threads = {}
        # Add 'stdout' thread that attaches to STDOUT of nodeserver process with _recv_out
        self._threads['stdout'] = AsyncFileReader(self._proc.stdout,
                                                  self._recv_out)
        # Add 'stderr' thread that attaches to STERR of nodeserver process with _recv_err
        self._threads['stderr'] = AsyncFileReader(self._proc.stderr,
                                                  self._recv_err)
        # Add 'requests' thread that attaches to REST inbound commands and daemonize it
        self._threads['requests'] = threading.Thread(target=self._request_handler)
        self._threads['requests'].daemon = True
        # Add 'stdin' thread that attaches to STDIN of nodeserver
        self._threads['stdin'] = threading.Thread(target=self._send_in)
        self._threads['stdin'].daemon = True
        for _, thread in self._threads.items():
            thread.start()

        # Check if MQTT interface is used for this nodeserver
        if (self.interface == 'mqtt' and MQTT == True):
            """
            This sends the params and config over STDOUT before replacing it with the MQTT
            subsystem. We do this so that the mqtt config from server.json is sent to the
            nodeserver in the params message on startup and it can use those settings to
            configure itself instead of requiring you to set it on that side as well.
            """
            self.send_params()
            self.send_config()
            # If the MQTT subsystem is not created, create it (first boot) else use the existing
            if self._mqtt is None:
                self._mqtt = mqttSubsystem(self)
            self._mqtt.start()

        # If we aren't using MQTT
        if self._mqtt is None:
            # wait, then send config
            time.sleep(1)
            self.send_params()        
            self.send_config()

        _LOGGER.info('Started Node Server: %s:%s (%s)',
                     self.platform, self.name, self._proc.pid)

    def restart(self):
        """ restart the nodeserver """
        self.send_exit()
        if self._mqtt is not None:
            self._mqtt.stop()

        for _ in range(10):
            if not self.alive:
                break
            time.sleep(0.5)
        else:
            self.kill()
        self.start()

    @property
    def definition(self):
        """ Return the server defintion from server.json """
        def_file = os.path.join(self.path, 'server.json')
        instruct_file = os.path.join(self.path, 'instructions.txt')
        definition = json.loads(open(def_file).read())
        definition['running'] = self.alive and self.responding
        definition['instructions'] = open(instruct_file).read()
        definition['profile_number'] = self.profile_number

        return definition

    @property
    def profile(self):
        """ Return the profile.zip data. """
        return open(os.path.join(self.path, 'profile.zip'), 'rb').read()

    @property
    def alive(self):
        """ Indicates if the Node Server is running. """
        try:
            os.kill(self._proc.pid, 0)
        except MyProcessLookupError:
            return False
        return self._inq is not None

    @property
    def responding(self):
        """ Indicates if the Node Server is responding. """
        if self._lastping is None:
            # node server has not been pinged
            self.send_ping()
            self._lastping = time.time()
            return True
        elif time.time() - self._lastping >= 30:
            # If MQTT is not connected, assume we are trying to reconnect and don't send a ping
            if self._mqtt is not None and (self._mqtt.connected == False or self.node_connected == False): return True
            # last ping has expired (more than 30 seconds old)
            if self._lastpong and self._lastpong > self._lastping:
                # pong was received
                self._lastping = time.time()
                self.send_ping()
                return True
            else:
                # pong was not received
                if self._lastpong is not None:
                    _LOGGER.warning('Node Server %s: time since last pong: %5.2f',
                                self.name, (time.time() - self._lastpong))
                else:
                    _LOGGER.warning('Node Server %s: Never received a pong response.', self.name)
                return False
        else:
            # ping hasn't expired, we have to assume responding
            time.sleep(1)
            return True

    # manage IO
    def _send_in(self):
        """
        Write pending input to node server.
        Kill process if unresponsive.
        """
        if self._mqtt is None:
            while True and self._inq:
                try:
                    # try to get a line from the queue
                    line = self._inq.get(True, 5)
                except Empty:
                    # no line in queue, check if the Node Server is responding
                    if not self.responding:
                        _LOGGER.error(
                            'Node Server %s has stopped responding.', self.name)
                        self._inq = None
                        self._rqq = None
                        self._proc.kill()
                else:
                    try:
                        # found line, try to write it
                        self._proc.stdin.write('{}\n'.format(line))
                        self._proc.stdin.flush()
                    except IOError:
                        # stdin pipe is broken. process is likely dead.
                        _LOGGER.error(
                            'Node Server %s has exited unexpectedly.', self.name)
                        self._inq = None
                        self._rqq = None
                        self._proc.kill()
                    else:
                        # line wrote successfully
                        _LOGGER.debug('%s STDIN: %s', self.name, line)
                        if self._inq:
                            self._inq.task_done()
        else:
            if self.node_connected == True:
                while True and self._mqtt:
                    if not self.responding:
                        _LOGGER.error(
                            'Node Server %s has stopped responding.', self.name)
                        self._rqq = None
                        self._mqtt.stop()
                        self._mqtt = None
                        self._proc.kill()
                    time.sleep(1)
            else: 
                time.sleep(1)
                self._send_in()

    def _request_handler(self):
        """
        Read and process network requests for a node server
        """
        while True and self._rqq:

            msg = self._rqq.get(True)

            # parse message
            command = list(msg.keys())[0]
            arguments = msg[command]

            seq = arguments.get('seq', None)
            ts = time.time()
            _LOGGER.debug('%8s [%d] (%5.2f) _request_handler: command=%s seq=%s',
                          self.name,
                          (0 if self._rqq is None else self._rqq.qsize()),
                          0.0, command, ('' if seq is None else seq))

            fun = self._handlers.get(command)
            if fun:
                result = fun(self.profile_number, **arguments)
                if seq and result:
                    self._mk_cmd('result', **result)

            # Signal that this is handled
            if self._rqq:
                self._rqq.task_done()

            _LOGGER.debug('%8s [%d] (%5.2f) _request_handler: completed.',
                          self.name,
                          (0 if self._rqq is None else self._rqq.qsize()),
                          (time.time() - ts))

    def _recv_out(self, line):
        """ 
        Process the output of the nodeserver 
        (Called from STDOUT or from message receive in MQTT) 
        """
        type = 'STDOUT'
        if self._mqtt is not None: type = 'MQTT'
        l = (line[:57] + '...') if len(line) > 60 else line
        _LOGGER.debug('%8s [%d] (%5.2f) %s: %s', self.name,
                      (0 if self._rqq is None else self._rqq.qsize()),
                      0.0, type, l)
        ts = time.time()
        # parse message
        message = json.loads(line)
        command = list(message.keys())[0]
        arguments = message[command]

        # direct command
        if command == 'pong':
            # store pong time
            self._lastpong = time.time()
        elif command == 'config':
            # store new configuration in config file
            self.config = arguments
            self.pglot.update_config()
        elif command == 'install':
            # install node server on isy
            # [future] implement when documentation is available
            raise NotImplementedError('Install command is not yet supported.')
        elif command == 'manager':
            global NSLOCK, NSMGR, NSSTATS
            # Special management node server operations
            op = arguments.get('op', None)
            if op == 'IAmManager':
                NSLOCK.acquire()
                NSMGR = self.profile_number
                NSSTATS['manager'] = NSMGR
                NSLOCK.release()
            elif op == 'ClearStatistics':
                if self.profile_number == NSMGR:
                    _LOGGER.info('%8s manager request: ClearStatistics', self.name)
                    isy = self.pglot.elements.isy
                    isy.get_stats(self.profile_number, clear=True)
                else:
                    _LOGGER.info('%8s manager request refused: {}', self.name, op)
            elif op == 'IsyHasRestarted':
                if self.profile_number == NSMGR:
                    # [TODO] send restart message to all other node server queues
                    _LOGGER.info('%8s reports that ISY has restarted', self.name)
                else:
                    _LOGGER.info('%8s manager request refused: {}', self.name, op)
            else:
                _LOGGER.error('%8s manager op not implemented: {}', self.name, op)
        elif command == 'statistics':
            # manage Polyglot and network communications stats
            isy = self.pglot.elements.isy
            result = {'to_isy': isy.get_stats(self.profile_number, **arguments)}
            if self.profile_number == NSMGR:
                # TODO: may need to take NSLOCK here to avoid partial updates
                result['ns'] = NSSTATS
            self._mk_cmd('statistics', **result)
        elif command == 'exit':
            # node server is done. Kill it. Clean up is automatic.
            self.node_connected = False
            self._proc.kill()
            self._inq = None
            self._rqq = None
        elif command == 'connected':
            _LOGGER.info('%8s current status is connected to the broker.', self.name)
            self.node_connected = True
            self.send_ping()
        elif command == 'disconnected':
            _LOGGER.error('%8s current status is disconnected from the broker.', self.name)
            self.node_connected = False

        else:
            fun = self._handlers.get(command)
            if fun and self._rqq:
                self._rqq.put(message, True, 30)
            else:
                _LOGGER.error('Node Server %s delivered bad command %s',
                              self.name, command)
        _LOGGER.debug('%8s [%d] (%5.2f)   Done: %s', self.name,
                      (0 if self._rqq is None else self._rqq.qsize()),
                      (time.time() - ts), l)

    def _recv_err(self, line):
        """
        Process STDERR from nodeserver
        """
        if line.startswith('**INFO: '):
            _LOGGER.info('%s: %s', self.name, line)
        elif line.startswith('**DEBUG: '):
            _LOGGER.debug('%s: %s', self.name, line)
        elif line.startswith('**WARNING: '):
            _LOGGER.warning('%s: %s', self.name, line)
        else:
            _LOGGER.error('%s: %s', self.name, line)

    def _mk_cmd(self, cmd_code, **kwargs):
        """ Process Output TO the nodeserver (MQTT/STDIN) """
        msg = json.dumps({cmd_code: kwargs})
        # If using mqtt, send the msg to the nodeserver over that mechanism if it is connected
        if (self.node_connected):
            self._mqtt._mqttc.publish(self._mqtt.topicOutput, str(msg), 0)
            _LOGGER.debug('%s MQTT Publish: %s', self.name, str(msg))
        # Else add the msg to the STDIN queue to send to the nodeserver processed by _send_in
        elif self._inq:
            self._inq.put(msg, True, 5)

    def send_config(self):
        """ Send configuration to Node Server. """
        self._mk_cmd('config', **self.config)

    def send_params(self):
        """ Send parameters to Node Server. """
        self._mk_cmd('params', **self.params)

    def send_install(self, profile_number=None):
        """ Send install command to Node Server. """
        if not profile_number:
            profile_number = self.profile_number
        else:
            self.profile_number = profile_number
            self.pglot.update_config()
        self._mk_cmd('install', profile_number=self.profile_number)

    def send_query(self, node_address, request_id=None):
        """ Send query command to Node Server. """
        self._mk_cmd('query', node_address=node_address, request_id=request_id)

    def send_status(self, node_address, request_id=None):
        """ Send status request to Node Server. """
        self._mk_cmd('status', node_address=node_address,
                     request_id=request_id)

    def send_addall(self, request_id=None):
        """ Send add all request to Node Server. """
        self._mk_cmd('add_all', request_id=request_id)

    def send_added(self, node_address, node_def_id,
                   primary_node_address, name):
        """ Send node added confirmation to Node Server. """
        self._mk_cmd('added', node_address=node_address,
                     node_def_id=node_def_id,
                     primary_node_address=primary_node_address, name=name)

    def send_removed(self, node_address):
        """ Send node removed confirmation to Node Server. """
        self._mk_cmd('removed', node_address=node_address)

    def send_renamed(self, node_address, name):
        """ Send node renamed confirmation to Node Server. """
        self._mk_cmd('renamed', node_address=node_address, name=name)

    def send_enabled(self, node_address):
        """ Send node enabled confirmation to Node Server. """
        self._mk_cmd('enabled', node_address=node_address)

    def send_disabled(self, node_address):
        """ Send node disabled confirmation to Node Server. """
        self._mk_cmd('disabled', node_address=node_address)

    def send_cmd(self, node_address, command, value=None, uom=None,
                 request_id=None, **kwargs):
        """ Send run command signal to Node Server. """
        self._mk_cmd('cmd', node_address=node_address, command=command,
                     value=value, uom=uom, request_id=request_id, **kwargs)

    def send_ping(self):
        """ Send Ping request to the Node Server. """
        self._mk_cmd('ping')

    def send_exit(self):
        """ Send exit command to the Node Server. """
        self._mk_cmd('exit')
        self.node_connected = False

    def kill(self):
        """ Kill the node server process. """
        try:
            self._proc.kill()

        except MyProcessLookupError:
            pass

class mqttSubsystem:
    """ 
    mqttSubsystem class instantiated if interface is mqtt in server.json 
    
    :param parent: The NodeServer object that called this function
    :type parent: polyglot.nodeserver_manager.NodeServer
    """
    # pylint: disable=too-many-instance-attributes
    # pylint: disable=unused-argument
    
    def __init__(self, parent):
        self.parent = parent
        self.connected = False
        self.topicOutput = 'udi/polyglot/' + self.parent.name + "/node"
        self.topicInput = 'udi/polyglot/' + self.parent.name + "/poly"
        self._mqttc = mqtt.Client(self.parent.name + "-poly", True)
        self._mqttc.will_set(self.topicOutput,json.dumps({"disconnected": {}}), retain=True)
        self._mqttc.on_connect = self._connect
        self._mqttc.on_message = self._message
        self._mqttc.on_subscribe = self._subscribe
        self._mqttc.on_disconnect = self._disconnect
        self._mqttc.on_publish = self._publish
        self._mqttc.on_log = self._log
        self._server = self.parent.mqtt_server
        self._port = self.parent.mqtt_port
    
    def _connect(self, mqttc, userdata, flags, rc):
        """
        The callback for when the client receives a CONNACK response from the server.
        Subscribing in on_connect() means that if we lose the connection and
        reconnect then subscriptions will be renewed.
        
        :param mqttc: The client instance for this callback
        :param userdata: The private userdata for the mqtt client. Not used in Polyglot
        :param flags: The flags set on the connection.
        :param rc: Result code of connection, 0 = Success, anything else is a failure
        """
        if rc == 0:
            self.connected = True
            _LOGGER.info("MQTT Connected with result code " + str(rc) + " (Success)")
            result, mid = self._mqttc.subscribe(self.topicInput)
            if result == 0:
                _LOGGER.info("MQTT Subscribing to topic: " + self.topicInput + " - " + " MID: " + str(mid) + " Result: " + str(result))
            else:
                _LOGGER.info("MQTT Subscription to " + self.topicInput + " failed. This is unusual. MID: " + str(mid) + " Result: " + str(result))
                # If subscription fails, try to reconnect.
                self._mqttc.reconnect()
        else:
            _LOGGER.error("MQTT Failed to connect. Result code: " + str(rc))
        
    def _message(self, mqttc, userdata, msg):
        """
        The callback for when a PUBLISH message is received from the server.

        :param mqttc: The client instance for this callback
        :param userdata: The private userdata for the mqtt client. Not used in Polyglot
        :param flags: The flags set on the connection.
        :param msg: Dictionary of MQTT received message. Uses: msg.topic, msg.qos, msg.payload
        """
        #_LOGGER.info('MQTT Received Message: ' + msg.topic + ": QoS: " + str(msg.qos) + ": " + str(msg.payload))
        self.parent._recv_out(msg.payload)
    
    def _disconnect(self, mqttc, userdata, rc):
        """
        The callback for when a DISCONNECT occurs.
        
        :param mqttc: The client instance for this callback
        :param userdata: The private userdata for the mqtt client. Not used in Polyglot
        :param rc: Result code of connection, 0 = Graceful, anything else is unclean
        """
        self.connected = False
        if rc != 0:
            _LOGGER.info("MQTT Unexpected disconnection. Trying reconnect1.")
            try:
                self._mqttc.reconnect()
            except Exception as ex:
                template = "An exception of type {0} occured. Arguments:\n{1!r}"
                message = template.format(type(ex).__name__, ex.args)
                _LOGGER.error("MQTT Connection error: " + message)                
        if rc == 0:
            _LOGGER.info("MQTT Graceful disconnection.")
            
    def _log(self, mqttc, userdata, level, string):
        """ Use for debugging MQTT Packets, disable for normal use, NOISY. """
        #_LOGGER.info('MQTT Log - ' + str(level) + ': ' + str(string))
        pass
            
    def _subscribe(self, mqttc, userdata, mid, granted_qos):
        """ Callback for Subscribe message. Unused currently. """
        #_LOGGER.info("MQTT Subscribed Succesfully for Message ID: " + str(mid) + " - QoS: " + str(granted_qos))
        pass

    def _publish(self, mqttc, userdata, mid):
        """ Callback for publish message. Unused currently. """
        #_LOGGER.info("MQTT Published message ID: " + str(mid))
        pass
        
    def start(self):
        """
        The client start method. Starts the thread for the MQTT Client
        and publishes the connected message.
        """
        _LOGGER.info('Connecting to MQTT... ' + self._server + ':' + self._port)
        try:
            self._mqttc.connect(str(self._server), int(self._port), 10)
            self._mqttc.loop_start()
            self._mqttc.publish(self.topicOutput,json.dumps({"connected": {}}), retain=True)
        except Exception as ex:
            template = "An exception of type {0} occured. Arguments:\n{1!r}"
            message = template.format(type(ex).__name__, ex.args)
            _LOGGER.error("MQTT Connection error: " + message)
        
    def stop(self):
        """
        The client stop method. If the client is currently connected
        stop the thread and disconnect. Publish the disconnected 
        message if clean shutdown.
        """
        if (self.connected):
            _LOGGER.info('Disconnecting from MQTT... ' + self._server + ':' + self._port)
            self._mqttc.publish(self.topicOutput,json.dumps({"disconnected": {}}), retain=True)
            self._mqttc.loop_stop()
            self._mqttc.disconnect()
   
def random_string(length):
    """ Generate a random string of uppercase, lowercase, and digits """
    library = string.ascii_uppercase + string.ascii_lowercase + string.digits
    return ''.join(random.choice(library) for _ in range(length))
