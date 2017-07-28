''' Polyglot ISY Virtual Node API definition '''
# pylint: disable=no-name-in-module, import-error
import logging
from polyglot.element_manager import http
from . import incoming
import xml.etree.ElementTree as ET
import os
import requests
import time
import threading
try:
    from urllib import quote, urlencode  # Python 2.x
except ImportError:
    from urllib.parse import quote, urlencode  # Python 3.x

DEFAULT_CONFIG = {'address': '192.168.10.100', 'https': False,
                  'password': 'admin', 'username': 'admin',
                  'port': 80, 'version':'0.0.0'}

# Timeout used when no timeout provided by caller (seconds)
_TIMEOUT = 25.0

# [future] This single global should probably be owned by each nodeserver
SESSION = None

ADDRESS = None
HTTPS = None
PASSWORD = None
PORT = None
USERNAME = None
VERSION = '0.0.0'
_LOGGER = logging.getLogger(__name__)

# Global diagnostic/performance data structure

SLOCK = threading.Lock()
STATS = {'ntotal':  0,     # Total requests
         'rtotal':  0,     # Total retries
         'oktotal': 0,     # Total responses == 200
         'ertotal': 0,     # Total responses != 200
         'ettotal': 0.0,   # Sum of elapsed time for requests
         'ethigh':  0.0,   # Longest elapsed time
         'etlow':   0.0}   # Shortest elapsed time

# [future] only accept incoming requests from the ISY


def load(pglot, user_config):
    ''' setup the http server '''
    # setup the configuration
    config = dict(DEFAULT_CONFIG)
    config.update(user_config)
    set_config(config)

    # register addresses with server
    http.register(incoming.HANDLERS, parent_dir='ns')

    # Register Polyglot application
    incoming.PGLOT = pglot

    _LOGGER.info('Loaded ISY element')
    


def unload():
    ''' stops the http server '''
    _LOGGER.info('Unloaded ISY element')


def get_config():
    """ Returns the element's configuration. """
    return {'address': ADDRESS, 'https': HTTPS == 'https',
            'password': PASSWORD, 'username': USERNAME,
            'port': PORT, 'version': VERSION}


def set_config(config):
    """ Updates the current configuration. """
    # pylint: disable=global-statement
    global ADDRESS, HTTPS, PASSWORD, PORT, USERNAME, SESSION, VERSION

    # pull config settings
    ADDRESS = config['address']
    HTTPS = 'https' if config['https'] else 'http'
    PASSWORD = config['password']
    PORT = config['port']
    USERNAME = config['username']

    # Invalidate the current global Session object
    SESSION = None

    # Fetch the version number using the new configuration
    VERSION = get_version()

def add_node_prefix(ns_profnum, nid):
    '''
    Adds a node prefix to a node ID.

    :param nid: The nodes ID to which a prefix will be added.
    '''
    prefix = 'n{}_'.format(str(ns_profnum).zfill(3))
    return '{}{}'.format(prefix, nid)


def report_node_status(ns_profnum, node_address, driver_control, value, uom,
                       timeout=None, seq=None):
    '''
    Reports the node status to the ISY.

    :param ns_profnum: Node Server ID
    :param node_address: The Node Address
    :param driver_control: Driver control for the node
    :param value: The node's value
    :param uom: The units of measurement of the value
    :param timeout: optional, timeout in seconds
    :param seq: optional, sequence number for reporting callback
    '''
    node_address = add_node_prefix(ns_profnum, node_address)
    url = make_url(ns_profnum, ['nodes', node_address, 'report', 'status',
                                driver_control, value, uom])
    return request(ns_profnum, url, timeout, seq)


def report_command(ns_profnum, node_address, command, value=None, uom=None,
                   timeout=None, seq=None, **kwargs):
    '''
    Reports a command that has run on a node.

    :param ns_profnum: Node Server ID
    :param node_address: The Node Address
    :param command: The command that was run on the node
    :param optional value: The unnamed parameter the command ran with
    :param optional uom: The unit of measurement for the unnamed parameter
    :param optional <pN>.<uomN>: Named parameter (p) with specificed uom
    :param timeout: optional, timeout in seconds
    :param seq: optional, sequence number for reporting callback
    '''
    node_address = add_node_prefix(ns_profnum, node_address)
    url = make_url(ns_profnum, ['nodes', node_address, 'report', 'cmd',
                                command, value, uom],
                   kwargs)
    return request(ns_profnum, url, timeout, seq)


def node_add(ns_profnum, node_address, node_def_id, primary, name,
             timeout=None, seq=None):
    '''
    Adds a node to the ISY.

    :param ns_profnum: Node Server ID
    :param node_address: The Node Address
    :param node_def_id: The node definition ID
    :param primary: The address to the primary node
    :param name: The node name
    :param timeout: optional, timeout in seconds
    :param seq: optional, sequence number for reporting callback
    '''
    node_address = add_node_prefix(ns_profnum, node_address)
    primary = add_node_prefix(ns_profnum, primary)
    url = make_url(ns_profnum, ['nodes', node_address, 'add', node_def_id],
                   {'primary': primary, 'name': name})
    return request(ns_profnum, url, timeout, seq)


def node_change(ns_profnum, node_address, node_def_id,
                timeout=None, seq=None):
    '''
    Change node on the ISY.

    :param ns_profnum: Node Server ID
    :param node_address: The Node Address
    :param node_def_id: The node definition ID
    :param timeout: optional, timeout in seconds
    :param seq: optional, sequence number for reporting callback
    '''
    node_address = add_node_prefix(ns_profnum, node_address)
    url = make_url(ns_profnum, ['nodes', node_address, 'change', node_def_id])
    return request(ns_profnum, url, timeout, seq)


def node_remove(ns_profnum, node_address, timeout=None, seq=None):
    '''
    Remove node on the ISY.

    :param ns_profnum: Node Server ID
    :param node_address: The Node Address
    :param timeout: optional, timeout in seconds
    :param seq: optional, sequence number for reporting callback
    '''
    node_address = add_node_prefix(ns_profnum, node_address)
    url = make_url(ns_profnum, ['nodes', node_address, 'remove'])
    return request(ns_profnum, url, timeout, seq)


def report_request_status(ns_profnum, request_id, success,
                          timeout=None, seq=None):
    '''
    Report the status of a request back to the ISY.

    :param request_id: The request ID from the controller.
    :param result: Boolean indicating the success of the command.
    :param timeout: optional, timeout in seconds
    :param seq: optional, sequence number for reporting callback
    '''
    status = 'success' if success else 'failed'
    url = make_url(ns_profnum,
                   ['report', 'request', request_id, status])
    return request(ns_profnum, url, timeout, seq)

def get_version():
    """
    Get the version of the ISY when requested by the nodeservers
    Set version information in config file for reference.
    """
    ver = '0.0.0'
    req = restcall(0, 'config', 10.0)
    if req['text'] is not None:
        try:                   
            tree = ET.fromstring(req['text'])
            ver = tree.findall('app_version')[0].text
            if ver is None:
                ver = '0.0.0'
            _LOGGER.info("ISY: firmware version: %s", ver)
        except ET.ParseError:
            _LOGGER.error("No version information found on ISY.")
    return ver

def make_url(ns_profnum, path, path_args=None):
    '''
    Create a URL from the given path.

    :param ns_profnum: Node Server ID
    :param path: List or subdirectories in path.
    :param path_args: Dictionary of arguments to add to the path.
    '''
    url = '{}://{}:{}/rest/ns/{}/'.format(HTTPS, ADDRESS, PORT, ns_profnum)
    url += '/'.join([quote(str(item)) for item in path if item is not None])

    if path_args is not None:
        if len(path_args) > 0:
            url += '?{}'.format(urlencode(path_args))

    return url

def restcall(ns_profnum, api, timeout=None, seq=None, noretry=False):
    '''
    Requests a REST API from the ISY. Returns response.

    :param ns_profnum: Node Server ID
    :param api: API to request.
    :param timeout: optional, timeout in seconds
    :param seq: optional, sequence number for reporting callback
    :param noretry: optional, True to disable retry attempts
    '''

    url = '{}://{}:{}/rest/{}'.format(HTTPS, ADDRESS, PORT, api)
    return request(ns_profnum, url, timeout, seq, text_needed=True)

def request(ns_profnum, url, timeout=None, seq=None, text_needed=False,
            noretry=False):
    '''
    Requests a URL from the ISY, returns response.

    :param ns_profnum: Node Server ID
    :param url: URL to request.
    :param timeout: optional, timeout in seconds
    :param seq: optional, sequence number for reporting callback
    :param noretry: optional, True to disable retry attempts
    :param text_needed: optional, default = False

    Returns a dictionary r containing:
        r.text:        response text     (string or None)
        r.seq:         sequence number   (string or None)
        r.retries:     retries required  (integer)
        r.elapsed:     time, in seconds  (float)
        r.status_code: response code     (integer)
            values < 100 are connection errors,
            values > 99 are standard HTTP status codes,
            value of 200 = success
    '''
    global SESSION
    _LOGGER.debug('ISY: Request: %s', url)

    # check environment for special overrides
    no_sessions = ('PG_NOSESSIONS' in os.environ)
    max_retries = int(os.environ.get('PG_RETRIES', '3'))

    # check for override of retry count
    if noretry:
        max_retries = 0

    # determine timeout
    tmo = _TIMEOUT
    if timeout is not None:
        try:
            tmo = float(timeout)
        except:
            tmo = _TIMEOUT

    # make request

    retries = 0
    retry = True

    while retry:

        # Add a delay if we're retrying; use sane delays, though
        if retries == 1:
            time.sleep(0.25)
        elif retries == 2:
            time.sleep(1.0)
        elif retries == 3:
            time.sleep(2.0)
        elif retries > 3:
            time.sleep(3.0)

        text = None
        retry = False
        ts = time.time()

        try:
            if no_sessions:
                # send request, new connection each time 
               req = requests.get(url, timeout=tmo, verify=False,
                                   auth=(USERNAME, PASSWORD))
            else:
                # get, check, and possibly update the session (thread-safe)
                s = SESSION
                if s is None:
                    s = requests.Session()
                    s.auth = (USERNAME, PASSWORD)
                    SESSION = s
                    _LOGGER.debug('ISY: created new Session object.')
                # send request, with connection re-use
                req = s.get(url, timeout=tmo, verify=False)

            # valid response - extract relevant information
            elapsed = (time.time() - ts)
            scode = req.status_code
            if scode == 200:
                diag = 'OK'
            elif scode == 503:
                # Per ISY docs, 503 means ISY too busy - retry
                diag = 'BUSY'
                retry = True
            else:
                diag = 'ERR'
                #if text_needed:
                text = req.text

        except requests.Timeout:
            # Timeout is not retryable
            elapsed = (time.time() - ts)
            diag = 'Timeout'
            scode = 1

        except requests.HTTPError:
            # Generic HTTP error is not retryable
            elapsed = (time.time() - ts)
            diag = 'HTTP Error'
            scode = 2

        except requests.URLRequired:
            # Internal error?  Not retryable
            elapsed = (time.time() - ts)
            diag = 'Valid URL Required'
            scode = 3

        except requests.ConnectionError as err:
            # Connection error - retryable, reset session
            elapsed = (time.time() - ts)
            text = repr(err)
            diag = repr(err).replace('\n', ' ')
            scode = 4
            retry = True
            # Invalidate session, force new connection
            SESSION = None

        # Increment retry counter and see if we've reached the limit
        retries += 1
        if retries > max_retries:
            retry = False

        # Log at the correct level depending on the status code
        _LOGGER.info("TEXT=%s",text)
        logstr = 'ISY: [%d] (%5.2f) %3d %s: %s'
        if scode == 200:
            _LOGGER.info(logstr, retries, elapsed, scode, diag, url)
        elif retry:
            _LOGGER.warning(logstr, retries, elapsed, scode, diag, url)
        else:
            _LOGGER.error(logstr, retries, elapsed, scode, diag, url)

    # End of loop

    # Correct our retries counter
    retries -= 1

    # Update global diagnostic statistics structure
    global SLOCK, STATS
    # Lock the global dict
    SLOCK.acquire()
    # Update the statistics
    STATS['ntotal'] += 1
    STATS['ettotal'] += elapsed
    STATS['rtotal'] += retries
    if scode == 200:
        STATS['oktotal'] += 1
    else:
        STATS['ertotal'] += 1
    if STATS['ethigh'] < elapsed:
        STATS['ethigh'] = elapsed
    if STATS['etlow'] > elapsed or STATS['etlow'] == 0.0:
        STATS['etlow'] = elapsed
    # Release the global lock
    SLOCK.release()

    return {'text': text, 'status_code': scode, 'seq': seq,
            'elapsed': elapsed, 'retries': retries}


def get_stats(ns_profnum, clear=False, **kwargs):
    """"
    Returns and optionally clears the Polyglot-to-ISY stats
    :param ns_profnum: Node Server ID (for future use)
    :param clear: optional, zero out stats if True
    """
    global SLOCK, STATS
    SLOCK.acquire()
    st = STATS
    if clear:
        STATS['ntotal']  = 0
        STATS['rtotal']  = 0
        STATS['oktotal'] = 0
        STATS['ertotal'] = 0
        STATS['ettotal'] = 0.0
        STATS['ethigh']  = 0.0
        STATS['etlow']   = 0.0
    SLOCK.release()
    #_LOGGER.info('get_stats(): %d %f %d', st['ntotal'], st['ettotal'], st['rtotal'])
    return st
