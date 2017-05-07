Optional Components
===================

Docker
~~~~~~

These are the instructions for Docker configuration provided by
UDI forum and Polyglot contributor i814u2.

Original Threads:

http://forum.universal-devices.com/topic/19807-%20polyglot-docker-%20image/#entry187776
http://forum.universal-devices.com/topic/19807-%20polyglot-docker-%20image/page-2

Linux x86_64
------------
Create a file named "Dockerfile" (case-sensitive) and place these
commands in there:

.. code-block:: bash

  ARG binfile=polyglot.linux.x86_64.pyz
  ARG user=polyglot
  ARG group=polyglot
  ARG uid=1000
  ARG gid=1000


  RUN addgroup -g ${gid} ${group} \
      && adduser -h /home/${user} -s /bin/sh -G ${group} -D -u ${uid} ${user}


  WORKDIR /home/${user}
  COPY custom.txt .


  RUN pip install --upgrade pip \
  && pip install -r https://raw.githubusercontent.com/UniversalDevicesInc/Polyglot/unstable-release/requirements.txt \
  && while read line; do $line; done < custom.txt


  RUN wget https://github.com/UniversalDevicesInc/Polyglot/raw/unstable-release/bin/${binfile}-P Polyglot \
  && chown -R ${user}:${group} /home/${user} \
  && chmod 755 /home/${user}/Polyglot/${binfile}


  USER ${user}
  WORKDIR /home/${user}/Polyglot
  ENTRYPOINT ["./polyglot.linux.x86_64.pyz","-v"]

Create a file named "custom.txt" and add whatever python modules and node servers you'd like installed.
Here is the example I have for adding Sonos and Nest:

.. code-block:: bash

  pip install soco
  pip install python-nest
  git clone https://github.com/Einstein42/sonos-polyglot Polyglot/config/node_servers/sonos-polyglot
  git clone https://github.com/Einstein42/nest-polyglot Polyglot/config/node_servers/nest-polyglot

Create a folder to store your config:

.. code-block:: bash

  mkdir -p ~/docker/polyglot

(If you already have polyglot up and running, backup your config folder and then just point this to your existing config folder instead of the one above. This should work, but always make a backup.)

The image is built by running this command (from the folder where you Dockerfile and custom.txt files are located):

.. code-block:: bash

  docker build -t polyglot .

After that completes, you should be able to run a command like this:

.. code-block:: bash

  docker run -d --name=polyglot -v ~/docker/polyglot:/home/polyglot/Polyglot/config --net=host -t polyglot-docker

The polyglot page should be available via your docker host machine's IP and port 8080. If that needs to change, allow it to start, then stop the container (docker stop polyglot), edit the configuration.json in the config folder on your docker host. Then start it back up (docker start polyglot).
I chose to use the non-compiled variation so that it would run across more systems. Another item I'd like to improve is only using the compiled version in order to save space.

**Ready to use image for linux x86_64**

Run this command, assuming you already have docker setup and running for your user on your linux machine.

.. code-block:: bash

  mkdir -p ~/docker/polyglot && docker run -d --name=polyglot -v ~/docker/polyglot:/home/polyglot/Polyglot/config --net=host -t i814u2/udi-polyglot

Then re-pull the image in order to update it, and re-create the container (this will also start the container, of course):

.. code-block:: bash
  docker pull i814u2/udi-polyglot && docker run -d --name=polyglot -v ~/docker/polyglot:/home/polyglot/Polyglot/config --net=host -t i814u2/udi-polyglot


Raspberry Pi
------------

Use NOOBS to install Raspbian on your Raspberry Pi (see here: https://www.raspberrypi.org/documentation/installation/noobs.md)

Once the Raspberry Pi is booted, open the terminal and enter the following command:

.. code-block:: bash

  curl -sSL https://get.docker.com | sh && sudo usermod -aG docker pi

This may take a while, depending on the speed of the machine and SD card.

Once the above command is complete, logout and log back in, or just reboot if you prefer.

Run this command to download and start the docker container (using the pre-setup image in my docker hub repository):

.. code-block:: bash

  mkdir ~/docker/polyglot && docker run -d --name=polyglot -v ~/docker/polyglot:/home/polyglot/Polyglot/config --net=host -t i814u2/rpi-udi-polyglot

Image contains the default Kodi and Hue nodes and also the Sonos and Nest nodes.
Second command updated to include the creation of the local config directory to ensure proper permissions.

If you've followed my instructions so far, and want to update, here is what you can do: (This assumes you followed the instructions and have your config files pointed to a local directory. Always make a backup of your config first, just in case):

.. code-block:: bash

  docker stop polyglot
  docker rm polyglot
  docker pull i814u2/rpi-udi-polyglot
  docker run -d --name=polyglot -v ~/docker/polyglot:/home/polyglot/Polyglot/config --net=host -t i814u2/rpi-udi-polyglot

(4 separate commands, one per line, each starts with the word 'docker')

Again, the last line assumes you followed the copy/paste style info in my previous posts for a RaspberryPi setup. Adjust, as needed, for your own directory structure.

Quick note: this will take a while on initial startup. It's upgrading packages when the container is started (in order to avoid the need to re-pull the image each time).

**More detail on how the image is setup:**

Follow the normal guides to install Raspbian on your RPi, then run this command to install Docker:

.. code-block:: bash

  curl -sSL https://get.docker.com | sh

When that is complete, it will mention adding your user to the docker group in order to run without sudo. That is accomplished with this command:

.. code-block:: bash

  sudo usermod -aG docker pi

That assumes you're using the "pi" user, and not your own. You'll need to log out, then log back on in order for that change to take effect.

Here is the Dockerfile info for a Raspberry Pi:

.. code-block:: bash

  FROM fnphat/rpi-alpine-python:2.7

  ARG binfile=polyglot.linux.armv7l.pyz
  ARG user=polyglot
  ARG group=polyglot
  ARG uid=1000
  ARG gid=1000

  RUN addgroup -g ${gid} ${group} \
          && adduser -h /home/${user} -s /bin/sh -G ${group} -D -u ${uid} ${user}

  WORKDIR /home/${user}
  COPY custom.txt .

  RUN apk add --update \
          build-base python-dev linux-headers git ca-certificates wget openssl-dev \
          && rm -rf /var/cache/apk/*

  RUN pip install --upgrade pip \
      && pip install -r https://raw.githubusercontent.com/UniversalDevicesInc/Polyglot/unstable-release/requirements.txt \
      && while read line; do $line; done < custom.txt

  RUN wget https://github.com/UniversalDevicesInc/Polyglot/raw/unstable-release/bin/${binfile} -P Polyglot \
      && chown -R ${user}:${group} /home/${user} \
      && chmod 755 /home/${user}/Polyglot/${binfile}

  USER ${user}
  WORKDIR /home/${user}/Polyglot
  ENTRYPOINT ["./polyglot.linux.armv7l.pyz", "-v"]


1. Use NOOBS to install Raspbian on your Raspberry Pi (see here: https://www.raspberr...lation/noobs.md)
2. Once the Raspberry Pi is booted, open the terminal and enter the following command:

.. code-block:: bash

  curl -sSL https://get.docker.com | sh && sudo usermod -aG docker pi

That will take a while, depending on the speed of the machine and SD card.
3. Once the above command is complete, logout and log back in, or just reboot if you prefer.
4. Run this command to download and start the docker container (using the pre-setup image in my docker hub repository):

.. code-block:: bash

  mkdir -p ~/docker/polyglot && docker run -d --name=polyglot -v ~/docker/polyglot:/home/polyglot/Polyglot/config --net=host -t i814u2/rpi-udi-polyglot


That image contains the default Kodi and Hue nodes and also the Sonos and Nest nodes.
Re-pulling the images and restarting new containers is easily done by running these commands:

.. code-block:: bash

  docker stop polyglot
  docker rm polyglot

Then re-pull the image in order to update it, and re-create the container (this will also start the container, of course):

.. code-block:: bash

  docker pull i814u2/rpi-udi-polyglot && docker run -d --name=polyglot -v ~/docker/polyglot:/home/polyglot/Polyglot/config --net=host -t i814u2/rpi-udi-polyglot
