''' Polyglot API definition '''
# pylint: disable=no-name-in-module, import-error
import json
import logging
# from polyglot.element_manager import http
import http
import polyglot.nodeserver_helpers as nshelpers

_LOGGER = logging.getLogger(__name__)
CONFIG = {}
PGLOT = None


def load(pglot, user_config):
    ''' setup the API handlers '''
    # pylint: disable=global-statement, unused-argument
    global PGLOT

    # register addresses with server
    http.register(HANDLERS, parent_dir='api')

    # Register Polyglot application
    PGLOT = pglot

    _LOGGER.info('Loaded API element')


def unload():
    ''' stops the http server '''
    _LOGGER.info('Unloaded API element')


def get_config():
    """ Returns the element's configuration. """
    return {}


def set_config(config):
    """ Updates the current configuration. """
    # pylint: disable=unused-argument
    pass


class GenericAPIHandler(http.AbstractHandler):
    """ Generic Handler that verifies Node Server. """

    STATUS = {200: 'HTTP_OK', 400: 'BAD_REQUEST', 404: 'HTTP_NOT_FOUND'}

    def __init__(self, *args, **kwargs):
        super(GenericAPIHandler, self).__init__(*args, **kwargs)
        self.node_server = None
        self.store = None
        self.request_id = None

    def send_not_found(self):
        ''' sends a not found response back to the client. '''
        self.send_json({}, 404)

    def send_json(self, data=None, status=200, message=None):
        '''
        sends json payload to as a response.

        :param data: Payload to send to client
        :param status: Status code to send to client
        '''
        if not data:
            data = {}
        self.set_status(status, self.STATUS[status])
        output = ({'success': status < 300, 'payload': data})
        if message:
            output['message'] = str(message)
        self.write(json.dumps(output))
        self.finish()

    def send_zip(self, fname, data):
        ''' Sends zip data to client. '''
        self.set_status(200, 'HTTP_OK')
        self.set_header('Content-Type', 'application/zip')
        self.set_header(
            'Content-Disposition', 'attachment; filename={}'.format(fname))
        self.write(data)
        self.finish()

    def send_txt(self, data):
        ''' Sends zip data to client. '''
        self.set_status(200, 'HTTP_OK')
        self.set_header('Content-Type', 'text/plain')
        self.write(data)
        self.finish()


class ConfigHandler(GenericAPIHandler):
    ''' /config '''
    def get(self):
        ''' worker '''
        config = PGLOT.elements.config
        config['pgver'] = PGLOT.version
        self.send_json(config)


class ConfigSetHTTPHandler(GenericAPIHandler):
    ''' /config/set/http '''
    def get(self):
        ''' worker '''
        config = {'username': self.get_argument('username'),
                  'password': self.get_argument('password'),
                  'port': int(self.get_argument('port'))}

        if config['port'] <= 1024:
            self.send_json(message='Port must be greater than 1024',
                           status=400)
            return

        PGLOT.elements.set_config({'http': config})

        self.send_json()


class ConfigSetISYHandler(GenericAPIHandler):
    ''' /config/set/isy '''
    def get(self):
        ''' worker '''
        config = {'username': self.get_argument('username'),
                  'password': self.get_argument('password'),
                  'address': self.get_argument('address'),
                  'port': int(self.get_argument('port')),
                  'https': self.get_argument('https', 'off') == 'on'}

        PGLOT.elements.set_config({'isy': config})

        self.send_json()


class ServersAvailableHandler(GenericAPIHandler):
    ''' /servers/available '''
    def get(self):
        ''' worker '''
        servers = nshelpers.available_servers()
        payload = [{'platform': key, 'name': val['name']}
                   for key, val in servers.items()]
        self.send_json(payload)


class ServersAddHandler(GenericAPIHandler):
    ''' /servers/add '''
    def get(self):
        ''' worker '''
        nsdata = {'nsname': self.get_argument('name'),
                  'profile_number': int(self.get_argument('nsid')),
                  'ns_platform': self.get_argument('type')}

        try:
            PGLOT.nodeservers.start_server(**nsdata)
            self.send_json()
        except ValueError as err:
            self.send_json(message=err.args[0], status=400)


class ServersActiveHandler(GenericAPIHandler):
    ''' /servers/active '''
    def get(self):
        ''' worker '''
        servers = [{'id': key, 'name': val.name,
                    'running': val.alive and val.responding}
                   for key, val in PGLOT.nodeservers.servers.items()]

        self.send_json(servers)


class ServerHandler(GenericAPIHandler):
    ''' /server/([A-Za-z0-9]+) '''
    def get(self, base_url):
        ''' worker '''
        if base_url in PGLOT.nodeservers.servers:
            self.send_json(PGLOT.nodeservers.servers[base_url].definition)
        else:
            self.send_not_found()


class ServerProfileHandler(GenericAPIHandler):
    ''' /server/([A-Za-z0-9]+)/profile '''
    def get(self, base_url):
        ''' worker '''
        if base_url in PGLOT.nodeservers.servers:
            profile = PGLOT.nodeservers.servers[base_url].profile
            name = PGLOT.nodeservers.servers[base_url].name
            self.send_zip('{}_profile.zip'.format(name), profile)
        else:
            self.send_not_found()


class ServerRestartHandler(GenericAPIHandler):
    ''' /server/([A-Za-z0-9]+)/restart '''
    def get(self, base_url):
        ''' worker '''
        if base_url in PGLOT.nodeservers.servers:
            PGLOT.nodeservers.servers[base_url].restart()
            self.send_json()
        else:
            self.send_not_found()


class ServerDeleteHandler(GenericAPIHandler):
    ''' /server/([A-Za-z0-9]+)/delete '''
    def get(self, base_url):
        ''' worker '''
        if base_url in PGLOT.nodeservers.servers:
            PGLOT.nodeservers.delete(base_url)
            self.send_json()
        else:
            self.send_not_found()


class LogHandler(GenericAPIHandler):
    ''' /log.txt '''
    def get(self):
        ''' worker '''
        text = PGLOT.get_log()
        self.send_txt(text)


HANDLERS = [ConfigHandler, ConfigSetHTTPHandler, ConfigSetISYHandler,
            ServersAvailableHandler, ServersAddHandler, ServersActiveHandler,
            ServerHandler, ServerProfileHandler, ServerRestartHandler,
            ServerDeleteHandler, LogHandler]
