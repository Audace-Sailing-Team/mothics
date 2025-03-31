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
    """Base Interface class for communications"""

    def connect(self):
        """Establish a connection."""
        pass

    def disconnect(self):
        """Close the connection."""
        pass
    
    def publish(self):
        """Send data."""
        pass


class SerialInterface(BaseInterface):
    """Interface class for communication via USB Serial."""
    
    def __init__(self, port, baudrate=9600, topics=None, name=None):
        self.port = port
        self.baudrate = baudrate
        self.serial_conn = None
        """Serial connection object."""
        self.running = False

        if topics is None:
            # NOTE: `<topic>_sudo` should only be used to push
            #       commands to the remote unit (rm)
            # NOTE: topic syntax is <module>/<sensor>/<quantity>
            topics = ['rm1/gps/lat', 'rm1/gps/long']
        elif isinstance(topics, str):
            topics = [topics]
        self.topics = topics
        """Client topics to subscribe to"""
        self.name = name
        """Interface name"""
        self.raw_data = {k: [] for k in self.topics}
        """Dictionary of all raw data fetched from available topics. Topics are keys, list of {timestamp: quantity} as values"""
        self.connected = False
        """Connection status flag"""
        
        # Setup logger
        self.logger = logging.getLogger(f"Serial-Interface - {self.name}")
        self.logger.info("-------------Serial Interface-------------")
        
    def connect(self):
        """Connect to the serial port and start the loop."""
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
        """Start a non-blocking loop"""
        if not self.running:
            self.running = True
            self.thread = threading.Thread(target=self._run_loop, daemon=True, name=f'serial communication interface - {self.name}')
            self.thread.start()
            self.logger.info("started non-blocking loop.")

    def _loop_stop(self):
        """Stop non-blocking loop"""
        self.running = False
        if self.thread and self.thread.is_alive():
            self.thread.join()
            self.logger.info("stopped loop.")
            
    def _run_loop(self):
        """Blocking listening loop"""
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
        """Aggregate raw data from messages into dict"""
        if topic not in self.topics:
            self.raw_data[topic] = []
        timestamp = datetime.now()
        self.raw_data[topic].append({timestamp: data})
                
    def disconnect(self):
        """Close the serial connection."""
        # Stop loop
        if self.running:
            self._loop_stop()
            
        # Close connection
        if self.serial_conn and self.serial_conn.is_open:
            self.serial_conn.close()
            self.logger.info("serial connection closed.")
        self.connected = False
            
    def publish(self, topic: str, payload):
        """Send data over serial."""
        if not self.serial_conn or not self.serial_conn.is_open:
            self.logger.critical("attempted to publish without an open connection.")
            raise RuntimeError("serial connection is not open.")

        message = json.dumps({"topic": topic, "payload": payload})
        self.serial_conn.write(message.encode('utf-8'))
        self.logger.info(f"published to serial: {message}")


class MQTTInterface(BaseInterface):
    """Interface class for remote communications via MQTT protocol"""

    def __init__(self, hostname, topics=None, port=1883, keep_alive=120):
        self.hostname = hostname
        """MQTT broker hostname"""
        self.port = port
        """ MQTT broker port"""
        self.keep_alive = keep_alive
        """Maximum time between comms with broker, before being disconnected (in seconds)"""
        if topics is None:
            # NOTE: `<topic>_sudo` should only be used to push
            #       commands to the remote unit (rm)
            # NOTE: topic syntax is <module>/<sensor>/<quantity>
            topics = ['rm1/gps/lat', 'rm1/gps/long']
        elif isinstance(topics, str):
            topics = [topics]
        self.topics = topics
        """Client topics to subscribe to"""
        self.raw_data = {k: [] for k in self.topics}
        """Dictionary of all raw data fetched from available topics. Topics are keys, list of {timestamp: quantity} as values"""
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
        Callback function for MQTT connection.
        Subscribes to topics upon successful connection.
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
        Callback function for MQTT disconnection.
        Handles automatic reconnection attempts.
        """
        self.logger.info("disconnected from MQTT broker. Attempting to reconnect...")
        self.client.reconnect()

    def _on_message(self, client, userdata, msg):
        """
        Callback function for incoming MQTT messages.
        Processes and passes data to the provided callback.
        
        :param msg: The MQTT message received.
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
        """Connect to the MQTT broker and start the loop."""
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
        """Disconnect from the MQTT broker and stop the loop."""
        # Stop loop
        self.client.loop_stop()
        # Close connection
        self.client.disconnect()
        self.connected = False
        
    def on_message_callback(self, topic, data):
        """Aggregate raw data from messages into dict"""
        if topic not in self.topics:
            self.raw_data[topic] = []
        timestamp = datetime.now()
        self.raw_data[topic].append({timestamp: data})

    def publish(self, topic, payload):
        """
        Publish a message to a specified topic.
        
        :param topic: Topic to publish the message to.
        :param payload: Dictionary to be JSON-encoded and published.
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
    """Class to manage multiple communication interfaces and merge their data."""
    
    def __init__(self, interfaces=None, max_values=1e3, trim_fraction=0.5):
        """
        Initialize communicator with optional interfaces.
        
        Args:
            interfaces (dict): Dictionary mapping interface classes to their kwargs
                             Format: {InterfaceClass: {'arg1': val1, ...}}
        """
        self.interfaces = {}
        """Initialized interfaces"""
        # Parameters
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
        Add new interfaces to the communicator.
        
        Args:
            interfaces (dict or class): Single interface class or dict of 
                                      {InterfaceClass: {'arg1': val1, ...}}
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
        Remove an interface from the communicator.
        
        Args:
            interface_class: The class of the interface to remove
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
        """Start all communication interfaces."""
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
        """Stop all communication interfaces."""
        for name, interface in self.interfaces.items():
            try:
                interface.disconnect()
                self.logger.info(f"stopped {name}")
            except Exception as e:
                self.logger.critical(f"error stopping {name}: {e}")
                raise RuntimeError(f"failed to stop {name}: {e}")

    def _format_topic(self, topic):
        """
        Split MQTT topic in its components.  
        MQTT topics are composed by <module>/<sensor>/<quantity>
        """
        topic_split = topic.split("/")
        assert len(topic_split) == 3, "topic is malformed, got {topic_split}"
        return topic_split

    @property
    def raw_data(self):
        """
        Merge and return raw data from all interfaces.
        
        Returns:
            dict: Merged dictionary of all raw data from all interfaces
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
        Publish message to specified interfaces.
        
        Args:
            topic (str): Topic to publish to
            payload: Message payload
            interfaces (list, optional): List of interface names to publish to.
                                      If None, publish to all interfaces.
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
        Refresh the communicator by connecting any new interfaces and optionally
        reconnecting existing ones
        
        Args:
            force_reconnect (bool): If True, forcibly disconnect and reconnect
                                    all existing interfaces
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
            
                
if __name__ == "__main__":
    pass
#    # Test code
#     setup_logger('test', fname='test_logger.log')
    
#     topic = "remote_module/gps_test"
#     message = f"Lorem ipsum dolor sit amet. {random.uniform(0., 1.)}"

#     test_publish_fetch(topic, message, publish=True)
    
