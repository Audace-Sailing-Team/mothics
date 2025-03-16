# Mothics
Mothics is a package for acquiring, aggregating, and analyzing data
collected from remote sensors for sailing on moth boats. The project
is part of the development of sensor technology and electronics for
the moths designed by Audace Sailing Team.

Mothics provides a dashboard, an integrated command-line interface,
and system management tools to analyze navigation tracks.

## Documentation
Partial documentation is available on the [internal website](https://audace-sailing-team.github.io) of the Sensor Technology department of Audace Sailing Team.  

The API is available [here](https://audace-sailing-team.github.io/mothics/). 

Full documentation will be released soon.

## Quick setup
### Prerequisites
The following packages are required:
- `tmux`
- `python3`
- `python3-venv`
- `pip`
- `git`
- `systemd`

> Note: Mothics is designed for use on DietPi and Ubuntu.

### Installation
Clone the repository
```sh
git clone https://github.com/Audace-Sailing-Team/mothics.git
cd mothics
```

Set up the package
```
make
```

To update the package
```sh
make update
```

To clean up generated files
```sh
make clean
```

### Automatic startup configuration
To run Mothics automatically on startup of the Raspberry Pi as a background service
```sh
make install-service
```
This will install and start `mothics.service`, ensuring it runs automatically at startup.

## Automatic startup and SSH access
Mothics can be accessed remotely via SSH. The default address is
```sh
ssh root@192.168.42.1
```

To manually run Mothics
```sh
cd mothics
. .venv/bin/activate
python3 cli.py 
```

## Session management
Mothics runs inside a `tmux` session to keep it active in the background.

To connect to the automatically started session
```sh
tmux attach -t mothics
```

> **Note:** by running `make alias-tmux`, you can join the active
> Mothics session by using the command `mothics-join` - which is far
> easier to remember!

To detach from the session (keeping it active), press `CTRL + B`, then `D`.

## Dashboard
Mothics provides a web dashboard for viewing navigation data. It is accessible at
```
https://192.168.42.1:5000
```

The dashboard allows you to:
- view real-time navigation data
- monitor system status
- manage track saving
- view available tracks

> **Note**: the first startup should be done with an active internet
> connection. Without it, needed CDNs will not be available and the
> dashboard won't load properly.

## Integrated CLI
Mothics includes a command-line interface (CLI) to manage tracks and
system status. Ensure the virtual environment is active
```sh
. .venv/bin/activate
```

and start the CLI with
```sh
python -m cli.py
```

To exit the CLI, use `exit` or `CTRL-D`. 

Documentation for most CLI commands is available; run
```sh
(mothics) help <command>
```

### Available commands
- `start live`: starts real-time monitoring
- `start replay <track_file>`: replays a saved track
- `start database`: initializes the database
- `stop`: stops the running system
- `restart`: restarts the system
- `restart reload_config`: restarts the system and reload the
  configuration file
- `interface_refresh`: refreshes communication interfaces
- `status`: shows system status
- `list_tracks`: lists available tracks
- `select_track <index>`: selects a track by index
- `log show`: displays logs
- `log clear`: clears logs
- `resources`: shows resource usage
- `resources mothics`: shows resource usage due to Mothics
- `resources system`: shows system-wide resource usage
- `serial_stream`: shows serial port data stream for debugging purposes 
- `shell <command>` or `!<command>`: executes a shell command
- `exit`: exits the CLI
- `shutdown`: stops the running system and shuts down the device 
- `reboot`: stops the running system and reboots the device 
- `update`: updates the CLI (akin to running `git pull`)

To see all available commands, run
```sh
(mothics) help
```

### Settings
Mothics settings can be found in `config.toml`. After updating them,
restart Mothics or use `restart reload_config`.

## Authors
 - [Iacopo Ricci](https://www.iricci.frama.io)
