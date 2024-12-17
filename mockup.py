import asyncio
import json
import random
import time
import logging
import paho.mqtt.client as mqtt
from pprint import pprint

from src.aggregator import Aggregator
from src.comm_interface import MQTTInterface, SerialInterface, Communicator
from src.webapp import WebApp

# Tests

def mock_publisher(topics, messages, broker_host="test.mosquitto.org", broker_port=1883, waits=2):
    """
    Connects to an MQTT broker and publishes a message to a specified topic.
    
    :param topic: The topic to which the message will be published.
    :param message: The message to be published.
    :param broker_host: MQTT broker hostname or IP address (default is test.mosquitto.org).
    :param broker_port: MQTT broker port (default is 1883).
    """
    # Create an MQTT client instance
    client = mqtt.Client()
    
    # Connect to the broker
    client.connect(broker_host, broker_port, keepalive=60)
    client.loop_start()
    
    if not isinstance(messages, list):
        message = [message]
    if not isinstance(topics, list):
        topics = [topics]
    if not isinstance(waits, list):
        waits = [waits]

    for topic, message, wait in zip(topics, messages, waits):
        # Publish the message to the topic
        result = client.publish(topic, message)
    
        # Check for publishing success
        if result.rc == mqtt.MQTT_ERR_SUCCESS:
            print(f"Message published to {topic}: {message}")
        else:
            print(f"Failed to publish message to {topic}: {message}")
        time.sleep(wait)
    
    # Disconnect after publishing
    client.loop_stop()
    client.disconnect()

    
if __name__ == '__main__':
    # Start logger
    logging.basicConfig(level=logging.INFO)

    # Start communicator and initialize interfaces
    serial_kwargs = {'port': "/dev/ttyACM0", 'baudrate': 9600, 'topics': 'rm2/wind/speed'}
    mqtt_kwargs = {'hostname': "test.mosquitto.org", 'topics': ['rm1/gps/lat', 'rm1/gps/long']}

    units_thesaurus = {'rm1': 'GPS+IMU', 'rm2': 'Anemometer'}

    comms = Communicator(interfaces={SerialInterface: serial_kwargs, MQTTInterface: mqtt_kwargs}, thesaurus=units_thesaurus)
    comms.connect()

    # Getters
    def raw_data_getter():
        return comms.raw_data

    def status_getter():
        return comms.status

    def db_getter():
        return aggregator.database

    # Start aggregator
    aggregator = Aggregator(raw_data_getter=raw_data_getter, interval=1, database=None)
    aggregator.start()

    # # Start webapp in background
    web_app = WebApp(database_getter=db_getter, status_getter=status_getter)
    web_app.start_in_background()
    
    # Simulate posting messages on topics at different intervals
    topics = ['rm1/gps/lat', 'rm1/gps/lat', 'rm1/gps/long', 'rm1/gps/long']
    messages = ['12', '13', '14.5', '15.5']
    sleeps = [1, 2, 1, 3]
    
    # Publish
    mock_publisher(topics, messages, waits=sleeps)
    time.sleep(120)

    # Disconnect all
    comms.disconnect()
    aggregator.stop()

    # Compare dictionary with database
    print("Script completed and all services stopped.")
    print('from interface', comms.raw_data)
    print('from aggregator\n', aggregator.database)
    
    # # Initialize MQTT interface
    # topics = ['rm/gps/lat', 'rm/gps/long', 'rm/gps/sudo']
    # mqtt_interface = MQTTInterface("test.mosquitto.org", topics=topics)
    # serial_interface = SerialInterface(port="/dev/ttyACM0", baudrate=9600, topics=['rm/wind/speed'])
    # mqtt_interface.connect()
    # serial_interface.connect()

    # aggregator = Aggregator(mqtt_interface.raw_data, interval=1, database=None)
    # aggregator = Aggregator(serial_interface.raw_data, interval=1, database=None)

    # Start aggregator
    # aggregator.start()
    
    # Simulate posting messages on two topics at different intervals
    # topics = ['rm/gps/lat', 'rm/gps/lat', 'rm/gps/long', 'rm/gps/long']
    # messages = ['12', '13', '14.5', '15.5']
    # sleeps = [1, 2, 1, 3]
    
    # # Publish
    # mock_publisher(topics, messages, waits=sleeps)

    # time.sleep(12)
    
    # # Stop aggregator and MQTT interface
    # mqtt_interface.disconnect()
    # serial_interface.disconnect()
    # aggregator.stop()

    # print("Script completed and all services stopped.")
    # print('from interface', mqtt_interface.raw_data)
    # print('from interface', serial_interface.raw_data)
    # print('from aggregator\n', aggregator.database)
    
