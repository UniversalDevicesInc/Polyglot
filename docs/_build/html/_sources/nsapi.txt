Polyglot Node Server API
========================

Documented here is the JSON API used for communication between Polyglot and the
Node Server processes. This API will never be referenced directly by either by
an end user and will rarely be referenced by a developer. It is documented here
for continuity. Nearly each command and its arguments maps to a command and
arguments specified in the ISY Virtual Node Server API documentation. The only
exceptions are the additions of some commands necessary for Polyglot's
operation.

General Format
~~~~~~~~~~~~~~

In general, each API message is formatted as such:

.. code-block:: json

    {COMMAND: {ARG_NAME_1: ARG_VALUE_1, ..., ARG_NAME_N: ARG_VALUE_N}}

All of the arguments are named. Each message ends with a new line and will
contain no new lines. Each message will contain only one command. Never will
multiple command be sent in the same message.

Node Server STDIN - Polyglot to Node Server
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The following messages may be sent from Polyglot to the Node Server to trigger
an action inside of the Node Server.

* | *{'config': {... arbitrary data saved by the node server ...}}*
  | This command is the first one sent to the node server and is only sent
    once. The arguments dictionary will be of an arbitrary structure and will
    match what the Node Server had last saved.
* | *{'install': {'profile_number': ...}}*
  | Instructs the node server to install itself with the specified
    *profile_number*.
* | *{"params": {"profile": 8, "pgver": "0.0.4", "name": "nodeservername", "pgapiver": "1", "sandbox": "/home/Polyglot/config/nodeservername", "configfile": "config.yaml", "interface": "mqtt", "path": "/home/Polyglot/config/node_servers/nodeservername", "isyver": "5.0.4", "mqtt_server": "pi3", "mqtt_port": "1883"}}*
  | Params passed back from Polyglot to the node server with info about the node server.
* | *{'query': {'node_address': ..., 'request_id': ...}}*
  | Instructs the node server to query a node. *request_id* is optional.
* | *{'status': {'node_address': ..., 'request_id': ...}}*
  | Requests the node server to send current node status to the ISY.
    *request_id* is optional.
* | *{'add_all': {'request_id': ...}}*
  | Requests that the node server add all its nodes to the ISY.
    *request_id* is optional.
* | *{'added': {'node_address': ..., 'node_def_id': ..., 'primary_node_address': ..., 'name': ...}}*
  | Indicates that the node has been added to the ISY.
* | *{'removed': {'node_address': ...}}*
  | Indicates that the node has been removed from the ISY.
* | *{'renamed': {'node_address': ..., 'name': ...}}*
  | Indicates that the node has been renamed in the ISY.
* | *{'enabled': {'node_address': ...}}*
  | Indicates that the node has been enabled in the ISY.
* | *{'disabled': {'node_address': ...}}*
  | Indicates that the node has been disabled in the ISY.
* | *{'cmd': {'node_address': ..., 'command': ..., *'value': ...., *'uom': ..., *'<pn>.<uomn>': ..., *'request_id': ...}}*
  | Instructs the node server to run the specified command on the specified
    node. *value* and *uom* are optional and described the unnamed parameter.
    They will always appear together. *<pn>.<uomn>* will be repeated as
    necessary to described the unnamed parameters. They are also optional.
    *request_id* is optional.
* | *{'ping': {}}*
  | This is a command from Polyglot requesting a Pong response. This is handled
    in the PolyglotConnector class.
* | *{'exit': {}}*
  | This command is Polyglot instructing the node server to cleanly shut down.

Node Server STDOUT - Node Server to Polyglot
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The following messages are accepted by Polyglot from the Node Server and will
typically instruct Polyglot to send a response upstream to the ISY.

* | *{'config': {... arbitrary data saved by the node server ...}}*
  | Sends configuration data to Polyglot to be saved. This data will be sent
    back to the Node Server, exactly as it has been sent to Polyglot, the next
    time the Node Server is started.
* | *{'install': {}}*
  | Install the node server on the ISY. This has not been implemented yet.
* | *{'status': {'node_address': ..., 'driver_control': ..., 'value': ..., 'uom': ...}}*
  | Reports a node's driver status.
* | *{'command': {'node_address': ..., 'command', ..., 'value': ...., 'uom': ..., '<pn>.<uomn>': ...}}*
  | Reports that a command has been run on a node. *value* and *uom* are
    optional and described the unnamed parameter. They will always appear
    together. *<pn>.<uomn>* will be repeated as necessary to described the
    unnamed parameters. They are also optional.
* | *{'add': {'node_address': ..., 'node_def_id': ..., 'primary': ..., 'name': ...}}*
  | Adds a node to the ISY.
* | *{'change': {'node_address': ..., 'node_def_id': ...}}*
  | Changes the node's definition in the ISY.
* | *{'remove': {'node_address': ...}}*
  | Instructs the ISY to remove a node.
* | *{'request': {'request_id': ..., 'result': ...}}*
  | Replies to the ISY indicating that a request has been finished either
    successfully or unsuccessfully. The result parameter must be a boolean
    indicating this.
* | *{'pong': {}}*
  | The proper response to a Ping command. Must be recieved within 30 seconds
    of a Ping command or Polyglot assumes the Node Server has stalled and
    kills it. This is handled automatically in the PolyglotConnector class.
* | *{'exit': {}}*
  | Indicates to Polyglot that the node server has exited and is now closing.
    This is the last message sent from a node server. All messages following
    this will be ignored. It is not guaranteed that the node server process
    will continue to run after this command is sent.

Node Server STDERR - Node Server to Polyglot
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

STDERR messages have no structured formatting, they are free flowing text.
Anything recieved by Polyglot through this stream will not be processed and
will be immediately logged as an error. Do not send personal information in
error messages as they will always be logged regardless of the log verbosity.
