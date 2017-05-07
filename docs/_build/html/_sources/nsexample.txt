Python Node Server Example
==========================

The following is a brief example of some impliemented node servers written in
Python. The examples included are pulled from the Philips Hue Node Server and
may not be current with the actual code used in that node server and is
redacted a bit for clarity, but will serve as a solid jumping off point for
defining the process by which a new node server can be developed.

Node Type Definition
~~~~~~~~~~~~~~~~~~~~

Some may find it easiest to start by developing all the types of nodes that the
node server may be controlling. As these are being defined in code, it may be
best to also define them in the file that will eventually make up the
*profile.zip* file. Documentation for profile files is available in the ISY
Virtual Node Server API documentation.

Below is the definition for a Hue color changing light.

.. code-block:: python

    from converters import RGB_2_xy, color_xy, color_names
    from functools import partial
    from polyglot.nodeserver_api import Node

    def myint(value):
        """ round and convert to int """
        return int(round(float(value)))


    def myfloat(value, prec=4):
        """ round and return float """
        return round(float(value), prec)

    class HueColorLight(Node):
        """ Node representing Hue Color Light """

        def __init__(self, parent, address, name, lamp_id, manifest=None):
            super(HueColorLight, self).__init__(parent, address, name, manifest)
            self.lamp_id = int(lamp_id)

        def query(self):
            """ command called by ISY to query the node. """
            updates = self.parent.query_node(self.address)
            if updates:
                self.set_driver('GV1', updates[0], report=False)
                self.set_driver('GV2', updates[1], report=False)
                self.set_driver('ST', updates[2], report=False)
                self.report_driver()
                return True
            else:
                return False

        def _set_brightness(self, value=None, **kwargs):
            """ set node brightness """
            # pylint: disable=unused-argument
            if value is not None:
                value = int(value / 100. * 255)
                if value > 0:
                    command = {'on': True, 'bri': value}
                else:
                    command = {'on': False}
            else:
                command = {'on': True}
            return self._send_command(command)

        def _on(self, **kwargs):
            """ turn light on """
            status = kwargs.get("value")
            return self._set_brightness(value=status)

        def _off(self, **kwargs):
            """ turn light off """
            # pylint: disable=unused-argument
            return self._set_brightness(value=0)

        def _set_color_rgb(self, **kwargs):
            """ set light RGB color """
            color_r = kwargs.get('R.uom56', 0)
            color_g = kwargs.get('G.uom56', 0)
            color_b = kwargs.get('B.uom56', 0)
            (color_x, color_y) = RGB_2_xy(color_r, color_g, color_b)
            command = {'xy': [color_x, color_y], 'on': True}
            return self._send_command(command)

        def _set_color_xy(self, **kwargs):
            """ set light XY color """
            color_x = kwargs.get('X.uom56', 0)
            color_y = kwargs.get('Y.uom56', 0)
            command = {'xy': [color_x, color_y], 'on': True}
            return self._send_command(command)

        def _set_color(self, value=None, **_):
            """ set color from index """
            ind = int(value) - 1

            if ind >= len(color_names):
                return False

            cname = color_names[int(value) - 1]
            color = color_xy(cname)
            return self._set_color_xy(
                **{'X.uom56': color[0], 'Y.uom56': color[1]})

        def _send_command(self, command):
            """ generic method to send command to hue hub """
            responses = self.parent.hub.set_light(self.lamp_id, command)
            return all(
                [list(resp.keys())[0] == 'success' for resp in responses[0]])

        _drivers = {'GV1': [0, 56, myfloat], 'GV2': [0, 56, myfloat],
                    'ST': [0, 51, myint]}
        """ Driver Details:
        GV1: Color X
        GV2: Color Y
        ST: Status / Brightness
        """
        _commands = {'DON': _on, 'DOF': _off,
                     'SET_COLOR_RGB': _set_color_rgb,
                     'SET_COLOR_XY': _set_color_xy,
                     'SET_COLOR': _set_color}
        node_def_id = 'COLOR_LIGHT'

As can be seen here, one method is defined for each of the commands that the
node may run. The query method from the Node ABC is also overwritten to
provide the desired functionality. An additional method called _send_command is
also created. This is not called by the ISY directly, but is a helper used to
send information to the Hue device. This method calls a method from a third
party library that connects to the Hue lighting system.

Additionally, the _drivers, _command, and node_def_id properties are
overwritten. This must be done by every node class as it instructs the node
server classes on how to interact with this node. Custom formatters myint and
myfloat are used to format the control values.

This process must be repeated for each type of node that is desired.

Node Server Creation
~~~~~~~~~~~~~~~~~~~~

Once all the nodes are defined, the node server class can be created.

.. code-block:: python

    from polyglot.nodeserver_api import SimpleNodeServer, PolyglotConnector
    # ... additional imports are redacted for clarity

    class HueNodeServer(SimpleNodeServer):
        """ Phillips Hue Node Server """

        hub = None

        def setup(self):
            """ Initial node setup. """
            super(SimpleNodeServer, self).setup()
            # define nodes for settings
            manifest = self.config.get('manifest', {})
            HubSettings(self, 'hub', 'Hue Hub', manifest)
            self.connect()
            self.update_config()

        def connect(self):
            """ Connect to Phillips Hue Hub """
            # get hub settings
            hub = self.get_node('hub')
            ip_addr = '{}.{}.{}.{}'.format(
                hub.get_driver('GV1')[0], hub.get_driver('GV2')[0],
                hub.get_driver('GV3')[0], hub.get_driver('GV4')[0])

            # ... Connects to the hub and validate connection. Redacted for clarity.

        def poll(self):
            """ Poll Hue for new lights/existing lights' statuses """

            # ... Connects to Hue Hub and gets current values for lights,
            #     stores in dictionary called lights. Redacted for clarity.

            for lamp_id, data in lights.items():
                address = id_2_addr(data['uniqueid'])
                name = data['name']

                lnode = self.get_node(address)
                if not lnode:
                    # Add the light to the Node Server if it doesn't already
                    # exist. Sets the primary to the 'hub' Node.
		    # This automatically adds the light to the ISY.
                    lnode = HueColorLight(self, address, 
                                         name, lamp_id, 
                                          self.get_node('hub'), manifest)

                (color_x, color_y) = [round(val, 4)
                                      for val in data['state']['xy']]
                brightness = round(data['state']['bri'] / 255. * 100., 4)
                brightness = brightness if data['state']['on'] else 0
                lnode.set_driver('GV1', color_x)
                lnode.set_driver('GV2', color_y)
                lnode.set_driver('ST', brightness)

            return True

        def query_node(self, lkp_address):
            """ find specific node in api. """

            # ... Polls Hue Hub for current specified light values, and updates
            #     Node object with new values. Works very similarly to poll
            #     above. Redacted for clarity.

        def _get_api(self):
            """ get hue hub api data. """

            # ... Uses third party library to get updated Hue Hub information.
            #     Redacted for clarity.

        def long_poll(self):
            """ Save configuration every 30 seconds. """
            self.update_config()
            # In this example, the configuration is autoatically saved every
            # 30 seconds. Make sure your node server saves its configuration
            # at some point.

This example class contains four methods that are not part of the abstract
class. They are setup, connect, query_node, and _get_api. These functions will
probably not appear in all node servers and are very specific to this one.

However, the setup method is a good way to handle any node server setup that
must be done that is specific to your node server. In this example, the primary
node, the Hue Hub, is created and a connection is attempted.

This class also stores an object called hub as an attribute. This objet is an
instance of a class from the third party library used. This object is the
actual connection to the Hue Hub. It may be best to follow a similar method
when creating node servers so that the code that handles the connection is
differentiated from the code that organizes the nodes.

The poll and long_poll methods from the abstract class are used in this
example. The Hue Hub sends no event stream, so it must be polled for updates.
This is done in the poll method. The long_poll method is utilized to ensure the
configuration data is saved consistently. These methods do not need to be
manually called anywhere as they are automatically invoked from the run loop
every (approximately) 1 second and 30 seconds respectively.

Starting the Node Server
~~~~~~~~~~~~~~~~~~~~~~~~

Finally, your program must be able to initialize itself and begin running the
node server. In Python, it will very nearly look like this.

.. code-block:: python

    def main():
        """ setup connection, node server, and nodes """
        poly = PolyglotConnector()
        nserver = HueNodeServer(poly)
        poly.connect()  # begin listening for Polyglot commands
        poly.wait_for_config()  # This is best practice to not start until
                                # Polyglot has begun communicating. This way,
                                # Polyglot will not miss messages sent from
                                # the node server.
        nserver.setup()  # setup method is specific to this example
        nserver.run()  # begin node server run loop


    if __name__ == "__main__":
        main()

Installing the Node Server
~~~~~~~~~~~~~~~~~~~~~~~~~~

Once all of this has been coded and all the appropriate files (documented in
the last section) have been created, the node server directory can be placed
in the configuration directory in a subfolder called *node_servers*. Polyglot
should then be restarted to trigger the discovery of new node server types. If
there is an issue with your node server, it will appear in the log.

Custom Node Server Configuration File
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

You may specify a custom configuration file in the server.json file as such:

.. code-block:: python

    "configfile": "customfile.yaml"
	
This should be placed in the top level of configuration, for example right after 
"executable". If no "configfile" is specified, Polyglot will look for "config.yaml"
in the root node_server folder(the same location as the server.json). If either
file is found, then the contents will be loaded into a dictionary for consumption.
The **poly.nodeserver_config** variable holds this dictionary.

Your node server may modify this dictionary as necessary and use the function

.. code-block:: python

        write_nodeserver_config():
		
This method has two parameters that are optional. The defaults are shown here:

.. code-block:: python

    default_flow_style = False 
    indent = 4

The default_flow_style is the formatting of the YAML file, look at the PyYAML 
documentation for specifics. The indent parameter is the number of spaces
indented for each subline in the file. The default for our method is 4 because
Python...

This method checks for any differences in the running configuration and the
existing file, and refrains from writing if they are identical. This method is 
also automatically called upon a normal shutdown of Polyglot. If Polyglot shuts
down abnormally, it will not record any changes that you made if you did not
call the write_nodeserver_config() method.
		
