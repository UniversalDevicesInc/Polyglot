Node Server Development
=======================

Background
~~~~~~~~~~

Node servers in Polyglot are nothing more than stand alone processes that are
managed by Polyglot. Polyglot communicates with the node servers by reading the
STDOUT and STDERR streams as well as writing to the STDIN stream. STDIN and
STDOUT messages are JSON formatted commands that are documented in
:doc:`nsapi`. 

As of Polyglot 0.0.6 MQTT is available as a communication mechanism
as well. See MQTT_.

File Structure
~~~~~~~~~~~~~~

Node servers are defined in self contained folders. The name given to this
folder will be the node server ID and must be unique form all other node
servers. New node servers can be stored in Polyglot's configuration directory
in the folder titled `node_servers`. Inside of this folder, at least the
following three files must exist.

  * *profile.zip* is the profile that must be uploaded to the ISY describing
    the node server. This file is documented in the ISY Node Server API
    documentation.
  * *instructions.txt* should be a file containing instructions on the use of
    the node server documented using `markdown
    <https://help.github.com/articles/markdown-basics/>`_. The contents of this
    file will be formatted and displayed on the frontend.
  * *server.json* is the metadata used by Polyglot to identify the node server.
    This file is documented in the next section.

The rest of the node server's folder should contain the code required to
execute the node server and all necessary libraries with the exception of those
explicitly included as part of the Polyglot distribution.

Node servers are executed in special directories in the user's configuration
directory. Each node server type is assigned its own directory. Any required
inforation may be written to this directory. Keep in mind, that all running
node servers of the same type will share the same directory.

Server Metadata
~~~~~~~~~~~~~~~

The *server.json* file in the node server source directory is a JSON formatted
file that informs Polyglot of how the node server is executed as well as
other important details about the node server. The file contains a dictionary
formatted object with specific fields. A sample *server.json* is included
below. It has been extracted from the Philips Hue node server.

.. code-block:: json

    {
        "name": "Phillips Hue",
        "docs": "https://www.universal-devices.com/",
        "type": "python",
        "executable": "hue.py",
		"configfile": "config.yaml",
		"interface": "Default",
        "description": "Connect Phillips Hue Personal Wireless Lighting system to the ISY994.",
        "notice": "\"Hue Personal Wireless Lighting\" is a trademark owned by Koninklijke Philips Electronics N.V., see www.meethue.com for more information. This Node Server is neither developed by nor endorsed by the Philips organization.",
        "credits": [
            {
                "title": "phue: A Python library for Philips Hue",
                "author": "Nathanaël Lécaudé (studioimaginaire)",
                "version": "0.9",
                "date": "May 18, 2015",
                "source": "https://github.com/studioimaginaire/phue/tree/c48845992b476f4b1de9549ea5b5277399f56581",
                "license": "https://raw.githubusercontent.com/studioimaginaire/phue/c48845992b476f4b1de9549ea5b5277399f56581/LICENSE"
            }
        ]
    }

Below is a description of the required fields:

  * *name* is the name of the node server type as it will be displayed to the user.
  * *docs* is a link to an appropriate website about the node server. This value is not currently displayed anywhere.
  * *type* is the node server executable type. This instructs Polyglot as to how the node server should be launched. Currently, only *python* is accepted.
  * *executable* is the file that Polyglot should execute to start the node server process.
  * *description* is a short description of the node server that will be displayed to the user on the frontend.
  * *notice* contains any important notices the user might need to know.
  * *credits* is a list of dictionaries indicating all third party library used in the node server. Some open source projects require that they be credited some where in the project. Others do not. Either way, it is nice to give credit here. When including a third party library in your node server, ensure that it is licensed for commercial use.

In the credits list:

  * *title* is the title of the third party library.
  * *author* is the author of the third party library.
  * *version* is the appropriate versioning tag used to identify the third party library.
  * *date* is the date the third party library was either released or obtained.
  * *source* is a link to the library's source code.
  * *license* is a link to the library's license file. Ensure that this is a static link whose contents cannot be changed. Linking to a specific GitHub commit is handy for this.

It can be a good idea to check the formatting of this file with a JSON linter
before attempting to load the node server in Polyglot. If this file cannot be
read, for whatever reason, the node server will not appear in the Polyglot
frontend and an error will be logged.

Python Development
~~~~~~~~~~~~~~~~~~

A Python 2.7 compatible implimentation of the API is provided with Polyglot to
assist in Node Server development. It may be easily imported as shown below. In
the future, more libraries may be made available and more languages may be
supported.

.. code-block:: python

    from polyglot import nodeserver_api

The provided Node Server Library exposes all of the `ISY controller's Node
Server RESTful API
<http://www.universal-devices.com/developers/wsdk/5.0.0/ISY-WS-SDK-Node-Server.pdf>`_
as is. Data recieved by Polyglot's web server is parsed and
directed immediately to the node server process via this library. The library
will also send messages back up to Polyglot to be transmitted directly to the
ISY. The only exception to this rule is that node ID's will not have the node
server ID prefix prepended to them. It will also be expected that the node
server will not prepend these prefixes. Polyglot will handle the node ID
prefixes on behalf of the node servers.

There also exists, in the Python library, some abstract classes that may be
used to ease the development of a new node server. Except in rare cases where
it may not be appropriate, it is recomended that these be used.

When Python is used to develop node server, the Polyglot environment is loaded
into the Python path. This environment includes the `Requests library
<http://docs.python-requests.org/en/latest/>`_.

Python Polyglot Library
~~~~~~~~~~~~~~~~~~~~~~~

Summary
-------

.. automodule:: polyglot.nodeserver_api

Custom Node Types
-----------------

When creating a new node server, each node type that will be controlled by the
server must be defined. This abstract class may be used as a skeleton for each
node type. When inheriting this class, a new method should be defined for each
command that the node can perform. Additionally, the _drivers and _commands
attributes should be overwritten to define the drivers and commands relevant to
the node.

.. autoclass:: polyglot.nodeserver_api.Node
   :members:
   :private-members:

Polyglot API Implimentation
---------------------------

This class impliments the Polyglot API and calls registered functions when
the API is invoked. This class is a singleton and will not allow itself to be
initiated more than once. This class binds itself to the STDIN stream to accept
commands from Polyglot.

To create a connection in your node server to Polyglot, use something similar
to the following. This creates the connection, connect to Polyglot, and then
waits for the Node Server's configuration to be received. The configuration
will be the first command received from Polyglot and will never be sent again
after the first transmission.::

    poly = PolyglotConnector()
    poly.connect()
    poly.wait_for_config()

Then, commands can be sent upstream to Polyglot or to the ISY by using the
connector's methods.::

    poly.send_error('This is an error message. It will be in Polyglot\'s log.')
    poly.add_node('node_id_1', 'NODE_DEFINITION', 'node_id_0', 'New Node')
    poly.report_status('node_id_1', 'ST', value=55, uom=51)
    poly.remove_node('node_id_1')

To respond to commands received from Polyglot and the ISY, handlers must be
registered for events. The handlers arguments will be the parameters specified
in the API for that event. This will look something like the following.::

    def status_handler(node_address, request_id=None):
        print('Status Event Handler Called')

    poly.listen('status', status_handler)

Now, when the ISY requests a status update from Polyglot, this function will be
called. Handlers will not be called in the node server's main thread.

.. autoclass:: polyglot.nodeserver_api.PolyglotConnector
   :members:

Node Server Classes
-------------------

.. autoclass:: polyglot.nodeserver_api.NodeServer
   :members:

.. autoclass:: polyglot.nodeserver_api.SimpleNodeServer
   :members:

Helper Functions
----------------

.. autofunction:: polyglot.nodeserver_api.auto_request_report

.. _MQTT:

MQTT
~~~~

MQTT communication mechanism has been developed for communications between 
Polyglot and the nodeservers. This becomes useful so that you can connected 
many different nodes to your nodeserver without having the distributed code 
running directly on the same platform Polyglot resides on. For example, I have 
a system of nodes that all communicates over MQTT to keep updated, and I don't 
want to wrap that entire system into Polyglot. I can develop a simple nodeserver
that runs and listens to your existing MQTT to allow communications without 
having to completely redevelop the system as a polyglot nodeserver. This lays 
the framework of allowing for completly distributed nodeservers.

Usage
-----
To use the MQTT Subsystem for communications you must include the following
into your server.json of your nodeserver::

	"interface": "mqtt",
	"mqtt_server": "192.168.1.20",
	"mqtt_port": "1883",

When Polyglot reads the server.json file and see's the MQTT interface command
it enables the MQTT subsystem for that particular nodeserver. It then sends 
these params along with the normal params and config to the nodeserver over STDIN, 
which allows for dynamic passing of the mqtt_server and mqtt_port information to 
the nodeserver. This is done to avoid having to set the connection information on 
both server.json AND your nodeserver. If the "interface" setting is missing or
anything other than "mqtt" case insensitive, then the standard STDIN/STDOUT 
mechansims will be used, regardless of if mqtt_server and mqtt_port are provided.

When the Polyglot nodeserver manager enables the MQTT interface, it automatically
connects to the MQTT broker and subscribes to the topic::

	udi/polyglot/<nodeserver name>/poly

This topic is where your nodeserver will publish any commands destined for Polyglot
for example the pong keepalive messages. These messages are formatted in JSON 
exactly like the exisiting STDOUT messages.

When creating a nodeserver that uses MQTT, you should listen on both STDIN and MQTT
and respond based on which mechanism was used. MQTT is a network resource, 
therefore inherently it is possible to have network disruption or connection
issues. When using MQTT in your nodeserver you will subscribe to the topic::

	udi/polyglot/<nodeserver name>/node

There is a retianed message that you will get upon subscription to the topic above
reflecting the current connection state of the Polyglot side. The json messages are
listed below.::

	{"connected": {}}
	or
	{"disconnected": {}}

This state is how you should respond to Polyglot. Using STDOUT if disconnected or 
MQTT if connected. A "Last Will and Testament" message is configured on the
Polyglot side to always make sure the state is accurate even on catastrophic 
failure. The nodeserver should be configured with this same feature. An example is
provided in the Node Server example section of the documentation.

MQTT Subsystem Class
--------------------

.. autoclass:: polyglot.nodeserver_manager.mqttSubsystem
   :members:
