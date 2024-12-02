import random
import json
import os
import logging
import time
# import serial
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


# class SerialInterface:
#     # TO TEST
#     """Interface class for communication via USB Serial."""
    
#     def __init__(self, port: str, baudrate: int=9600):
#         self.port = port
#         self.baudrate = baudrate
#         self.serial_conn = None
#         """Serial connection object."""

#     def connect(self):
#         """Establish a serial connection."""
#         try:
#             self.serial_conn = serial.Serial(self.port, self.baudrate, timeout=1)
#             self.logger.info(f"Connected to {self.port} at {self.baudrate} baud.")
#         except serial.SerialException as e:
#             self.logger.error(f"Failed to connect to {self.port}: {e}")
#             raise

#     def disconnect(self):
#         """Close the serial connection."""
#         if self.serial_conn and self.serial_conn.is_open:
#             self.serial_conn.close()
#             self.logger.info("Serial connection closed.")

#     def publish(self, topic: str, payload: Any):
#         """Send data over serial."""
#         if not self.serial_conn or not self.serial_conn.is_open:
#             self.logger.error("Attempted to publish without an open connection.")
#             raise RuntimeError("Serial connection is not open.")

#         message = json.dumps({"topic": topic, "payload": payload})
#         self.serial_conn.write(message.encode('utf-8'))
#         self.logger.info(f"Published to serial: {message}")

#     def listen(self):
#         """Listen for incoming data."""
#         if not self.serial_conn or not self.serial_conn.is_open:
#             raise RuntimeError("Serial connection is not open.")

#         while True:
#             try:
#                 line = self.serial_conn.readline().decode('utf-8').strip()
#                 if line:
#                     self.logger.info(f"Received: {line}")
#                     message = json.loads(line)
#                     self.on_message_callback(message["topic"], message["payload"])
#             except Exception as e:
#                 self.logger.error(f"Error processing incoming data: {e}")


class MQTTInterface:
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
            self.logger.critical("Failed to tipify MQTT message.")
        except:
            self.logger.critical("Failed to store MQTT message.")

    def connect(self):
        """Connect to the MQTT broker and start the loop."""
        self.client.connect(self.hostname, self.port, keepalive=self.keep_alive)
        self.client.loop_start()

    def disconnect(self):
        """Disconnect from the MQTT broker and stop the loop."""
        self.client.loop_stop()
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

    
if __name__ == "__main__":
    pass
#    # Test code
#     setup_logger('test', fname='test_logger.log')
    
#     topic = "remote_module/gps_test"
#     message = f"Lorem ipsum dolor sit amet. {random.uniform(0., 1.)}"

#     test_publish_fetch(topic, message, publish=True)
    
