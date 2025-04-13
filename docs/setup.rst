Setup
=============

Prerequisites
-------------

Mothics is designed to be used on a Raspberry Pi 4B with DietPi, thus
keeping resource usage to a minimum. Nonetheless, it also runs on most
Linux-based machines.

Before installing Mothics, ensure you have the following dependencies installed

- `make`
- `python3`
- `python3-venv`
- `pip`
- `git`
- `tmux` (optional)
- `systemd` (optional)
- `avahi-daemon` (optional)
  
`tmux` and `systemd` are needed to install Mothics as a service and to
run it at startup; `avahi-daemon` is needed to setup a different
hostname.

Installation
------------

Mothics is open-source, and it is hosted on `GitHub
<https://github.com/Audace-Sailing-Team/mothics>`_ .

First of all, clone the repository

.. code-block:: sh

   git clone https://github.com/Audace-Sailing-Team/mothics.git
   cd mothics

Most of the setup process is automated by a Makefile! To perform a
basic installation, run 

.. code-block:: sh

   make

this sets up a Python virtual environment with all the packages needed
to run Mothics, which are

- `argh==0.31.3`
- `bokeh==3.6.2`
- `Flask==3.1.0`
- `Flask-Compress==1.17`
- `jsonschema==4.23.0`
- `jsonschema-specifications==2024.10.1`
- `numpy==2.1.3`
- `paho-mqtt==2.1.0`
- `pyproj==3.7.1`
- `pyserial==3.5`
- `psutil==7.0.0`
- `requests==2.32.3`
- `rpi-lgpio==0.6`
- `tabulate==0.9.0`
- `tinydb==4.8.2`
- `toml==0.10.2`
- `waitress==3.0.2`

Now, activate the virtual environment

.. code-block:: sh

    . .venv/bin/activate

and start Mothics

.. code-block:: sh

   python3 cli.py

Advanced setup
--------------

The provided Makefile also includes some more advanced setup
options. Since the project revolves around easy usage in rough
conditions (*e.g.* on a Raspberry Pi inside a watertight box on a
moth!), running Mothics without user interaction is essential.

Start Mothics at startup
^^^^^^^^^^^^^^^^^^^^^^^^

To **run Mothics at startup** (as a service with `systemd`), make sure to
clone the package in the `/home/<user>` directory; then, run

.. code-block:: sh

   make install-service

Mothics-as-a-service lives inside a `tmux` session to allow users to
access the currently running Mothics instance and to use the command
line interface (CLI).

When Mothics runs as a service, it automatically runs the command

.. code-block:: sh

   start live

(more on this in Basics/Commands!)

Aliases
^^^^^^^

To **attach the current shell** session to the running `tmux` session, run

.. code-block:: sh

   tmux attach -t mothics

this command isn't that easy to remember. To make it more
memorable, set up an alias by running

.. code-block:: sh

   make alias-tmux

which allows the user to access the current Mothics CLI using
   
.. code-block:: sh

   mothics-join

**Starting Mothics manually** is quite bothersome too, since the virtual
environment needs to be started before starting the CLI

.. code-block:: sh

   . .venv/bin/activate
   python3 cli.py

we can make it more memorable by running

.. code-block:: sh

    make alias-start

which enables the command

.. code-block:: sh

   mothics-start
   
Update and clean
^^^^^^^^^^^^^^^^
   
Furthermore, to check for **Mothics updates**, run

.. code-block:: sh

   make update

and to **clean up** files generated during the installation process and
normal usage, run

.. code-block:: sh

   make clean

Hostname
^^^^^^^^

DietPi allows to change hostname to allow for easy access to the web
dashboard and via SSH. To do so, install `avahi-daemon` and use the
default `dietpi-config` setup tool

.. code-block:: sh

   sudo apt install avahi-daemon
   sudo dietpi-config

For the purposes of this tutorial, we set `mothics` as the system
hostname.

> **Note:** by default, the standard DietPi hostname available after
`avahi-daemon` is enabled, is `dietpi`.

> **Note:** different Linux distributions offer different
ways to modify the hostname.
