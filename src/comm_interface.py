import threading
import random
import json
import os
import logging
import time
import serial
from datetime import datetime
import paho.mqtt.client as mqtt

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
    
    def __init__(self, port, baudrate=9600, topics=None):
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
        self.raw_data = {k: [] for k in self.topics}
        """Dictionary of all raw data fetched from available topics. Topics are keys, list of {timestamp: quantity} as values"""

        # Setup logger
        self.logger = logging.getLogger("Serial-Interface")
        self.logger.info("-------------Serial Interface-------------")
        
    def connect(self):
        """Connect to the serial port and start the loop."""
        try:
            self.serial_conn = serial.Serial(self.port, self.baudrate, timeout=1)
            self.logger.info(f"connected to {self.port} at {self.baudrate} baud.")
        except serial.SerialException as e:
            self.logger.error(f"failed to connect to {self.port}: {e}")
            raise RuntimeError(f"failed to connect to {self.port}: {e}")
        
        # Start loop (non-blocking)
        self._loop_start()
    
    def _loop_start(self):
        """Start a non-blocking loop"""
        if not self.running:
            self.running = True
            self.thread = threading.Thread(target=self._run_loop, daemon=True)
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
                    self.logger.info(f"received: {line}")
                    message = json.loads(line)
                    # Suboptimal way to get topic and value, given a
                    # single topic-value pair is passed at each serial
                    # entry
                    topic = list(message.keys())[0]
                    value = list(message.values())[0]
                    self.on_message_callback(topic, value)
            except Exception as e:
                self.logger.error(f"error processing incoming data: {e}")

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

    def publish(self, topic: str, payload):
        """Send data over serial."""
        if not self.serial_conn or not self.serial_conn.is_open:
            self.logger.error("attempted to publish without an open connection.")
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
        self.logger.info(f"message received on {msg.topic}: {msg.payload.decode()}")
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
        except self.client.MQTTException as e:
            self.logger.error(f"failed to connect to {self.hostname} at port {self.port}: {e}")
            raise RuntimeError(f"failed to connect to {self.hostname} at port {self.port}: {e}")

        # Start loop (non-blocking)
        self.client.loop_start()

    def disconnect(self):
        """Disconnect from the MQTT broker and stop the loop."""
        # Stop loop
        self.client.loop_stop()
        # Close connection
        self.client.disconnect()
        
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


class Communicator:
    pass
    

if __name__ == "__main__":
    pass
#    # Test code
#     setup_logger('test', fname='test_logger.log')
    
#     topic = "remote_module/gps_test"
#     message = f"Lorem ipsum dolor sit amet. {random.uniform(0., 1.)}"

#     test_publish_fetch(topic, message, publish=True)
    
