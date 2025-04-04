"""
This module defines a flexible system for managing multiple
communication interfaces, such as Serial (USB) and MQTT, and merging
all their incoming data into one coherent structure. It is able to
manage multiple data sources and can potentially publish messages
through several different protocols.

Classes
-------
- BaseInterface : Abstract base class defining the required methods for any interface.
- SerialInterface : Implementation for reading from and writing to a serial (USB) port.
- MQTTInterface : Implementation for connecting to and communicating with an MQTT broker.
- Communicator : High-level manager that orchestrates all interfaces, merges their data, 
                 and provides a unified interface for publishing and retrieving messages.

Quick example
-------------
1. Define a Communicator and configure interfaces:

    ```
    from mothics.comm_interface import Communicator, SerialInterface, MQTTInterface

    interfaces_config = {
        SerialInterface: [
            {'port': '/dev/ttyUSB0', 'baudrate': 9600, 'name': 'serial_device_1'},
            {'port': '/dev/ttyUSB1', 'baudrate': 115200, 'name': 'serial_device_2'}
        ],
        MQTTInterface: {
            'hostname': 'mqtt.broker.local',
            'topics': ['rm1/gps/lat', 'rm1/gps/long'],
        }
    }

    comm = Communicator(interfaces=interfaces_config)
    ```

2. Connect all interfaces and begin collecting data:

    ```
    comm.connect()
    ```

3. Publish a message to a specific interface:

    ```
    comm.publish('rm1/gps/lat', {'value': 42.1234}, interfaces=['MQTTInterface_mqtt.broker.local'])
    ```

4. When finished, disconnect all interfaces:

    ```
    comm.disconnect()
    ```

Notes
-----
- By default, each interface runs its own internal loop to capture data. 
- Use the `raw_data` property to get a merged dictionary of data from all active interfaces.
- You can add your own custom interfaces by subclassing `BaseInterface` and implementing
  `connect`, `disconnect`, and `publish` methods.

"""


import threading
import random
import json
import os
import logging
import time
import serial
from datetime import datetime, timedelta
import paho.mqtt.client as mqtt
from paho.mqtt import MQTTException

from .helpers import setup_logger, tipify


# Interface

class BaseInterface:
    """
    Base Interface class for communications
    
    This abstract base class defines the structure for communication
    interfaces (e.g., serial, MQTT). Subclasses should implement
    their own connection, disconnection, and publishing logic.
    """

    def connect(self):
        """
        Establish a connection to the communication channel.

        This method should set up and open the communication channel
        (e.g., open a serial port, connect to an MQTT broker).
        Implementations in subclasses should raise exceptions on failure.
        """
        pass

    def disconnect(self):
        """
        Close the connection gracefully.

        This method should safely shut down the communication channel
        and release any resources (e.g., close the serial port,
        disconnect from the MQTT broker).
        """
        pass
    
    def publish(self):
        """
        Send or publish data to the communication channel.

        Subclasses should implement logic to serialize (if needed) and
        send the payload to the remote endpoint. Usually, preferred
        serialization is JSON.

        Generally, a strict addressing convention is used to send and
        receive message from remote units. Units should always listen
        on the `<remote_unit>/sudo` address.

        """
        pass


class SerialInterface(BaseInterface):
    """
    Interface class for communication via USB Serial.

    This interface continuously reads data from a specified serial
    port in a non-blocking thread and updates a `raw_data` dictionary
    accordingly. It can also publish data back through the same serial
    port in JSON format.
    """
    
    def __init__(self, port, baudrate=9600, topics=None, name=None):
        """
        Initialize the SerialInterface.

        Args:
            port (str): The system name/path of the serial port.
            baudrate (int, optional): The baud rate for communication.
                Defaults to 9600.
            topics (list[str] or str, optional): A list (or single string) of
                topics to which this interface will subscribe. Defaults to
                ['rm1/gps/lat', 'rm1/gps/long'].
            name (str, optional): Optional (but strongly recommended) nickname 
                for this interface.

        Raises:
            ValueError: If `topics` is given in an unrecognized format.
        """
        self.port = port
        """System name of the serial port (e.g., '/dev/ttyUSB0')"""
        self.baudrate = baudrate
        """Baud rate for the serial communication"""
        self.serial_conn = None
        """Serial connection object"""
        self.running = False
        """Status of the listening thread"""
        # Topics parsing
        if topics is None:
            # FLAWED: no address should be explicitly specified!
            # NOTE: topic syntax is <module>/<sensor>/<quantity>
            topics = ['rm1/gps/lat', 'rm1/gps/long']
            
        elif isinstance(topics, str):
            topics = [topics]
        self.topics = topics
        """Client topics to subscribe to"""
        self.name = name
        """Name for the interface instance"""
        self.raw_data = {k: [] for k in self.topics}
        """Dictionary of all raw data fetched from subscribed topics. Keys are topics, values are lists of {timestamp: quantity}"""
        self.connected = False
        """Connection status"""
        
        # Setup logger
        self.logger = logging.getLogger(f"Serial-Interface - {self.name}")
        self.logger.info("-------------Serial Interface-------------")
        
    def connect(self):
        """
        Connect to the serial port and start the listener loop.

        This method attempts to open a serial connection using the
        configured port and baud rate. If successful, it sets
        `connected=True` and starts a non-blocking thread to read
        incoming data.

        Raises:
            RuntimeError: If the serial connection fails to open.
        """
        try:
            self.serial_conn = serial.Serial(self.port, self.baudrate, timeout=1)
            self.logger.info(f"connected to {self.port} at {self.baudrate} baud.")
            self.connected = True
        except serial.SerialException as e:
            self.logger.critical(f"failed to connect to {self.port}: {e}")
            raise RuntimeError(f"failed to connect to {self.port}: {e}")
        
        # Start loop (non-blocking)
        self._loop_start()
    
    def _loop_start(self):
        """
        Start a non-blocking background thread to continuously read the serial port.

        The reading loop runs in a separate daemon thread, allowing the main thread
        to continue execution. This loop processes incoming lines, attempts to parse
        them as JSON objects, and routes them to `on_message_callback`.
        """
        if not self.running:
            self.running = True
            self.thread = threading.Thread(target=self._run_loop, daemon=True, name=f'serial communication interface - {self.name}')
            self.thread.start()
            self.logger.info("started non-blocking loop.")

    def _loop_stop(self):
        """
        Stop the non-blocking background reading loop and wait for it to exit.
        """
        self.running = False
        if self.thread and self.thread.is_alive():
            self.thread.join()
            self.logger.info("stopped loop.")
            
    def _run_loop(self):
        """
        Blocking method that continually reads the serial connection.

        Each line read from the serial port is decoded from UTF-8 and stripped.
        If multiple JSON objects are concatenated in the line, they are split
        and parsed individually. Unparseable data is logged as a warning.
        """
        # Sanity check - connection
        if not self.serial_conn or not self.serial_conn.is_open:
            raise RuntimeError("Serial connection is not open.")

        # Loop
        while self.running:
            try:
                line = self.serial_conn.readline().decode('utf-8').strip()
                if line:
                    self.logger.debug(f"received: {line}")
                    try:
                        for json_obj in line.split("}{"):  # Handles multiple JSON objects
                            if not json_obj.startswith("{"):
                                json_obj = "{" + json_obj
                            if not json_obj.endswith("}"):
                                json_obj = json_obj + "}"
                            message = json.loads(json_obj)
                            for topic, value in message.items():
                                self.on_message_callback(topic, value)
                    except json.JSONDecodeError as e:
                        self.logger.warning(f"error processing incoming data: {e} - raw: {line}")
                        continue
            except Exception as e:
                self.logger.warning(f"error processing incoming data: {e} - raw: {line}")
                continue

    def on_message_callback(self, topic, data):
        """
        Handle incoming data for a particular topic.

        This method appends a dict containing the current timestamp
        and the received data to `raw_data[topic]`. If the topic did not
        previously exist, a new entry is created.

        Args:
            topic (str): The topic under which data was received.
            data (Any): The decoded data for that topic.
        """
        if topic not in self.topics:
            self.raw_data[topic] = []
        timestamp = datetime.now()
        self.raw_data[topic].append({timestamp: data})
                
    def disconnect(self):
        """
        Close the serial connection and stop the reading loop.

        If the loop is still running, it is gracefully shut down first.
        Then the serial connection is closed and `connected` is set to False.
        """
        # Stop loop
        if self.running:
            self._loop_stop()
            
        # Close connection
        if self.serial_conn and self.serial_conn.is_open:
            self.serial_conn.close()
            self.logger.info("serial connection closed.")
        self.connected = False
            
    def publish(self, topic: str, payload):
        """
        Send data over the serial connection as a JSON string.

        Args:
            topic (str): The topic or identifier for the data being sent.
            payload (Any): The payload to be JSON-encoded and transmitted.

        Raises:
            RuntimeError: If the serial connection is not open.
        """
        if not self.serial_conn or not self.serial_conn.is_open:
            self.logger.critical("attempted to publish without an open connection.")
            raise RuntimeError("serial connection is not open.")

        message = json.dumps({"topic": topic, "payload": payload})
        self.serial_conn.write(message.encode('utf-8'))
        self.logger.info(f"published to serial: {message}")


class MQTTInterface(BaseInterface):
    """
    Interface class for remote communications via MQTT protocol.

    This interface connects to an MQTT broker and subscribes to a set
    of topics. Incoming messages are passed to `on_message_callback`,
    and data can be published back to the broker.
    """

    def __init__(self, hostname, topics=None, port=1883, keep_alive=120):
        """
        Initialize the MQTTInterface.

        Args:
            hostname (str): The MQTT broker's hostname or IP address.
            topics (list[str] or str, optional): List (or single string) of
                topics to subscribe to. Defaults to ['rm1/gps/lat', 'rm1/gps/long'].
            port (int, optional): Broker's port. Defaults to 1883.
            keep_alive (int, optional): Maximum keepalive interval in seconds
                before the broker disconnects the client. Defaults to 120.
        """
        
        self.hostname = hostname
        """MQTT broker hostname"""
        self.port = port
        """ MQTT broker port"""
        self.keep_alive = keep_alive
        """Maximum time between comms with broker, before being disconnected (in seconds)"""
        if topics is None:
            # FLAWED: no address should be explicitly specified!
            # NOTE: topic syntax is <module>/<sensor>/<quantity>
            topics = ['rm1/gps/lat', 'rm1/gps/long']
        elif isinstance(topics, str):
            topics = [topics]
        self.topics = topics
        """Client topics to subscribe to"""
        self.raw_data = {k: [] for k in self.topics}
        """Dictionary of all raw data fetched from subscribed topics. Keys are topics, values are lists of {timestamp: quantity}"""
        self.connected = False
        """Connection status flag"""
        
        # Initialize client
        self.client = mqtt.Client()
        # Assign callback functions
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        self.client.on_disconnect = self._on_disconnect

        # Setup logger
        self.logger = logging.getLogger("MQTT-Interface")
        self.logger.info("-------------MQTT Interface-------------")
        # self.client.enable_logger(logger=self.logger)
        
    def _on_connect(self, client, userdata, flags, rc):
        """
        Callback triggered when the MQTT client connects to the broker.

        If the connection is successful (rc == 0), the client subscribes
        to all configured topics.

        Args:
            client (mqtt.Client): The MQTT client instance for this callback.
            userdata (Any): User-defined data passed to the client object.
            flags (dict): Response flags sent by the broker.
            rc (int): The connection result.
        """
        if rc == 0:
            self.logger.info("connected to MQTT broker.")
            for topic in self.topics:
                self.client.subscribe(topic)
                self.logger.info(f"subscribed to topic: {topic}")
        else:
            self.logger.info(f"connection failed with code {rc}")

    def _on_disconnect(self, client, userdata, rc):
        """
        Callback triggered when the MQTT client disconnects from the broker.

        By default, this method attempts to reconnect automatically.

        Args:
            client (mqtt.Client): The MQTT client instance for this callback.
            userdata (Any): User-defined data passed to the client object.
            rc (int): The disconnection result.
        """
        self.logger.info("disconnected from MQTT broker. Attempting to reconnect...")
        self.client.reconnect()

    def _on_message(self, client, userdata, msg):
        """
        Callback triggered when an MQTT message is received.

        Decodes payload to a string, then attempts to convert it into
        typed data (`tipify` helper). The result is handed off to
        `on_message_callback`.

        Args:
            client (mqtt.Client): The MQTT client instance for this callback.
            userdata (Any): User-defined data passed to the client object.
            msg (mqtt.MQTTMessage): The received MQTT message.
        """
        self.logger.debug(f"message received on {msg.topic}: {msg.payload.decode()}")
        try:
            data = tipify(msg.payload.decode())
            # Pass topic and data to the external handler
            self.on_message_callback(msg.topic, data)
        except ValueError:
            self.logger.critical("failed to tipify MQTT message.")
        except:
            self.logger.critical("failed to store MQTT message.")

    def connect(self):
        """
        Connect to the MQTT broker and start the network loop (non-blocking).

        This method attempts to create a connection to the specified
        hostname/port. If successful, the MQTT network loop is started
        to process network events asynchronously.

        Raises:
            RuntimeError: If connecting to the broker fails.
        """
        try:
            self.client.connect(self.hostname, self.port, keepalive=self.keep_alive)
            self.logger.info(f"connected to {self.hostname} at port {self.port}.")
            self.connected = True
        except (MQTTException, OSError) as e:
            self.logger.critical(f"failed to connect to {self.hostname} at port {self.port}: {e}")
            raise RuntimeError(f"failed to connect to {self.hostname} at port {self.port}: {e}")

        # Start loop (non-blocking)
        self.client.loop_start()

    def disconnect(self):
        """
        Disconnect from the MQTT broker and stop the network loop.

        This method requests a disconnection from the broker and then
        stops the background MQTT listener.
        """
        # Stop loop
        self.client.loop_stop()
        # Close connection
        self.client.disconnect()
        self.connected = False
        
    def on_message_callback(self, topic, data):
        """
        Callback to handle incoming data for a particular topic.

        This method appends a dict containing the current timestamp
        and the received data to `raw_data[topic]`. If the topic did not
        previously exist in the dictionary, it is created.

        Args:
            topic (str): The topic under which data was received.
            data (Any): The typed or raw data payload.
        """
        if topic not in self.topics:
            self.raw_data[topic] = []
        timestamp = datetime.now()
        self.raw_data[topic].append({timestamp: data})

    def publish(self, topic, payload):
        """
        Publish a JSON-encoded message to a specified topic.

        Args:
            topic (str): MQTT topic to publish the message to.
            payload (dict): Data to be JSON-encoded and published.

        Raises:
            RuntimeError: If `topic` is not in the subscribed topics list.
        """
        message = json.dumps(payload)
        if topic in self.topics:
            self.client.publish(topic, message)
        else:
            self.logger.critical(f'{topic} is not in topics list: {self.topics}')
            raise RuntimeError(f'{topic} is not in topics list: {self.topics}')
        self.logger.info(f"published to {topic}: {message}")


# Communicator

class Communicator:
    """
    Class to manage multiple communication interfaces and merge their data.

    This keeps track of any number of interfaces (Serial, MQTT, etc.),
    allowing you to start or stop them all together, publish messages
    selectively, and retrieve merged data from all interfaces.
    """
    
    def __init__(self, interfaces=None, max_values=1e3, trim_fraction=0.5):
        """
        Initialize the Communicator with desired interfaces.

        If `interfaces` is provided, each interface class is instantiated
        with the supplied kwargs. This approach allows you to specify multiple
        interfaces or multiple instances of the same interface, each with
        its own parameters.

        Args:
            interfaces (dict, optional): Dictionary mapping interface classes
                to their kwargs in this form:
                {InterfaceClass: {'arg1': val1, ...}} or
                {InterfaceClass: [ {...}, {...} ]}.
                If you pass a single interface class, it will be initialized
                with default kwargs.
            max_values (int, optional): Maximum number of data points stored
                per topic before old data is trimmed. Defaults to 1000.
            trim_fraction (float, optional): Fraction of oldest data to remove
                whenever a topic exceeds `max_values`. Defaults to 0.5.
        """
        self.interfaces = {}
        """Dictionary of interface instances keyed by a unique name."""
        self.max_values = max_values
        """Trim threshold for raw_data dict"""
        self.trim_fraction = trim_fraction
        """Fraction of values to trim from raw_data"""
        self.preprocessors = []
        """Preprocessors for incoming data"""
        
        # Setup logger
        self.logger = logging.getLogger("Communicator")
        self.logger.info("-------------Communicator-------------")
        
        # Initialize interfaces if provided
        if interfaces:
            self.add_interfaces(interfaces)
            
    def add_interfaces(self, interfaces):
        """
        Add new interfaces to the Communicator.

        You can pass either a single interface class or a dictionary
        of interface classes to kwargs.

        Args:
            interfaces (Union[type, dict]): If it is a class, it is
                instantiated with no kwargs. If it is a dict, it should
                have the format {InterfaceClass: {'arg': val, ...}} or
                {InterfaceClass: [ {...}, {...} ]} for multiple instances.

        Raises:
            ValueError: If the `interfaces` argument is not a class or dict.
            RuntimeError: If an interface fails to initialize.
        """
        # Handle single interface class case
        if isinstance(interfaces, type):
            interfaces = {interfaces: {}}
        # Handle dict with single interface
        elif not isinstance(interfaces, dict):
            raise ValueError("interfaces must be a class or dict of {class: kwargs}")
            
        # Initialize each interface            
        for interface_class, kwargs in interfaces.items():
            if isinstance(kwargs, list):
                for kwarg in kwargs:
                    class_name = interface_class.__name__
                    if kwarg['name'] is not None:
                        class_name = interface_class.__name__+'_'+kwarg['name']
                    if class_name in self.interfaces:
                        self.logger.warning(f"interface {class_name} already exists, skipping")
                        continue
                
                    try:
                        self.interfaces[class_name] = interface_class(**kwarg)
                        self.logger.info(f"initialized {class_name} with kwargs: {kwarg}")
                    except Exception as e:
                        self.logger.critical(f"failed to initialize {class_name}: {e}")
                        raise RuntimeError(f"failed to initialize {class_name}: {e}")
    
    def remove_interface(self, interface_class):
        """
        Remove an interface from the Communicator by class.

        This method looks up the interface by the class name and disconnects
        it before removing it from the internal dictionary.

        Args:
            interface_class (type): The class of the interface to remove.

        Raises:
            RuntimeError: If disconnecting the interface fails.
        """
        class_name = interface_class.__name__
        if class_name in self.interfaces:
            try:
                # Ensure interface is disconnected
                if hasattr(self.interfaces[class_name], 'disconnect'):
                    self.interfaces[class_name].disconnect()
                del self.interfaces[class_name]
                self.logger.info(f"removed interface {class_name}")
            except Exception as e:
                self.logger.critical(f"error removing interface {class_name}: {e}")
                raise RuntimeError(f"error removing interface {class_name}: {e}")
        else:
            self.logger.warning(f"interface {class_name} not found")
    
    def connect(self):
        """
        Start all communication interfaces.

        For each interface in `self.interfaces`, calls its `connect`
        method. If any fail to connect, logs a warning. If all fail,
        an additional warning is logged.

        Raises:
            RuntimeError: If critical connection logic fails in a subclass.
        """
        failed_interfaces = []
        
        for name, interface in self.interfaces.items():
            try:
                interface.connect()
                self.logger.info(f"started {name}")
            except Exception as e:
                self.logger.warning(f"failed to start {name}: {e}")
                failed_interfaces.append(name)

        if failed_interfaces == list(self.interfaces.keys()):
            self.logger.warning('failed to start all interfaces')

        if failed_interfaces:
            error_msg = f"Failed to start interfaces: {', '.join(failed_interfaces)}"
            self.logger.warning(error_msg)
    
    def disconnect(self):
        """
        Stop all communication interfaces.

        Calls the `disconnect` method on each managed interface.
        If any interface fails to disconnect, a critical error is logged
        and a `RuntimeError` is raised.
        """
        for name, interface in self.interfaces.items():
            try:
                interface.disconnect()
                self.logger.info(f"stopped {name}")
            except Exception as e:
                self.logger.critical(f"error stopping {name}: {e}")
                raise RuntimeError(f"failed to stop {name}: {e}")

    def _format_topic(self, topic):
        """
        Split a topic in its components.

        This helper expects the MQTT-style topic format ("address"):
        <module>/<sensor>/<quantity>.

        Args:
            topic (str): The topic string.

        Returns:
            list[str]: A list of components (module, sensor, quantity).

        Raises:
            AssertionError: If the topic does not have exactly 3 sections.
        """
        topic_split = topic.split("/")
        assert len(topic_split) == 3, "topic is malformed, got {topic_split}"
        return topic_split

    @property
    def raw_data(self):
        """
        Merge and return raw data from all interfaces.

        This property iterates over every interface's `raw_data` dict,
        merges them into a single dictionary keyed by topic, and sorts
        each topic's data by timestamp. If any topic in a particular
        interface exceeds `max_values`, the oldest data are trimmed
        according to `trim_fraction`.

        Returns:
            dict: A merged dictionary of raw data from all interfaces.
                  Structure is {topic: [ {timestamp: data}, ... ]}.
        """
        merged_data = {}
        
        # Merge data from all interfaces
        for interface in self.interfaces.values():
            for topic, data_list in interface.raw_data.items():
                # Ensure each interface does not exceed max values to avoid memory leaks
                if len(data_list) > self.max_values:
                    trim_count = int(len(data_list) * self.trim_fraction)
                    interface.raw_data[topic] = data_list[trim_count:]  # Trim oldest data
                    self.logger.debug(f"trimmed {trim_count} entries from {topic} in {interface.__class__.__name__}")
                
                if topic not in merged_data:
                    merged_data[topic] = []
                merged_data[topic].extend(data_list)
        
        # Sort data by timestamp for each topic
        for topic in merged_data:
            merged_data[topic].sort(key=lambda x: list(x.keys())[0])

            # Preprocess each data item
            # NOTE: processing functions should operate on data columns            
            if hasattr(self, 'preprocessors') and self.preprocessors:
                processed_list = []
                for item in merged_data[topic]:
                    for processor in self.preprocessors:
                        item = processor(item, topic)
                    processed_list.append(item)
                merged_data[topic] = processed_list
            
        return merged_data        
    
    def publish(self, topic, payload, interfaces=None):
        """
        Publish a message to one or more interfaces.

        Args:
            topic (str): Topic string where the message is to be published.
            payload (Any): Data or object to be published. In some interfaces
                           (e.g., MQTT, serial), this may be JSON-encoded.
            interfaces (list[str], optional): A list of interface names (keys of
                           `self.interfaces`) to which the message should be
                           published. If None, publish to all interfaces.

        Raises:
            RuntimeError: If an interface rejects the publish due to being
                          disconnected or invalid topic.
        """
        if interfaces is None:
            interfaces = self.interfaces.keys()
        
        for interface_name in interfaces:
            if interface_name not in self.interfaces:
                self.logger.warning(f"interface {interface_name} not found")
                continue
                
            try:
                self.interfaces[interface_name].publish(topic, payload)
            except Exception as e:
                self.logger.warning(f"failed to publish to {interface_name}: {e}")

    def refresh(self, force_reconnect=False):
        """
        Refresh the Communicator by connecting any new interfaces and optionally
        reconnecting existing ones.

        If `force_reconnect=True`, all interfaces are disconnected and then
        reconnected. Otherwise, only interfaces that are currently disconnected
        will be connected.

        Args:
            force_reconnect (bool): If True, forcibly disconnect and reconnect
                                    all existing interfaces.
        """
        if force_reconnect:
            # Disconnect everything first
            self.logger.info("force reconnect: stopping all interfaces before refresh")
            for name, interface in list(self.interfaces.items()):
                try:
                    interface.disconnect()
                except Exception as e:
                    self.logger.warning(f"error stopping {name}: {e}")

        # Now connect all (or reconnect in the case of 'force_reconnect')
        failed_interfaces = []
        for name, interface in self.interfaces.items():
            if not interface.connected:
                try:
                    interface.connect()
                    self.logger.info(f"refreshed and started {name}")
                except Exception as e:
                    self.logger.warning(f"failed to refresh {name}: {e}")
                    failed_interfaces.append(name)

        if failed_interfaces:
            error_msg = f"failed to refresh interfaces: {', '.join(failed_interfaces)}"
            self.logger.warning(error_msg)    
