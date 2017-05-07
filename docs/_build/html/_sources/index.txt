.. Polyglot documentation master file, created by
   sphinx-quickstart on Sun Nov  8 20:49:14 2015.
   You can adapt this file completely to your liking, but it should at least
   contain the root `toctree` directive.

Polyglot Virtual Node Server Framework
======================================

Polyglot Virtual Node Server Framework is an application that makes it easy and
quick to both develop and maintain virtual node servers for the ISY-994i home
automation controller by Universal Devices Inc. Using virtual node servers, the
ISY-994i is able to communicate with and control third-party devices to which
the ISY-994i cannot natively connect.

Polyglot is written primarily with Python 2.7 and makes it easy
to develop new Virtual Node Servers with Python 2.7. It should, however, by
noted, that Virtual Node Servers may by developed using any language. Polyglot
is intended to be run on a Raspberry Pi 2 Model B, but could potentially run on
any ARM based machine running Linux with Python 2.7. FreeBSD, OSX, and x64 linux
binaries are provided as well. 

This document will document the usage of and development for Polyglot. For
additional help, please reference the `UDI Forum
<http://forum.universal-devices.com/forum/111-polyglot/>`_.

.. toctree::
   :maxdepth: 2

   usage
   nsdev
   nsexample
   nsapi
   module
   optional
   changelog
