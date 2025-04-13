# Mothics
Mothics is a package for acquiring, aggregating, and analyzing data
collected from remote sensors for sailing on moth boats. The project
is part of the development of sensor technology and electronics for
the moths designed by Audace Sailing Team.

Mothics provides a dashboard, an integrated command-line interface,
and system management tools to analyze navigation tracks.

## Documentation
The API is available
[here](https://audace-sailing-team.github.io/mothics/api/mothics). [Full documentation](https://audace-sailing-team.github.io/mothics/docs) will be released soon.

## Quick setup
Full setup information is available [here](https://audace-sailing-team.github.io/mothics/docs/setup.html).
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
python3 cli.py
```

To exit the CLI, use `exit` or `CTRL-D`. 

Documentation for most CLI commands is available; run
```sh
(mothics) help <command>
```

### Available commands
A partial list of available commands is

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
