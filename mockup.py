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
from src.helpers import setup_logger
from src.database import Track

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
        result = client.publish(topic, message, qos=2)
    
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
    logger_fname = os.path.join(os.getcwd(), 'mockup.log')
    setup_logger('logger', fname=logger_fname, silent=False)
    logging.basicConfig(level=logging.INFO)
    
    # Start communicator and initialize interfaces
    serial_kwargs = {'port': "/dev/ttyACM0", 'baudrate': 9600, 'topics': 'rm2/wind/speed'}
    mqtt_kwargs = {'hostname': "test.mosquitto.org", 'topics': ['rm1/gps/lat', 'rm1/gps/long']}

    comms = Communicator(interfaces={SerialInterface: serial_kwargs, MQTTInterface: mqtt_kwargs})
    comms.connect()
    
    # Getters
    # NOTE: these can be streamlined by writing a simple function
    # which takes the returned attribute as an argument

    def raw_data_getter():
        return comms.raw_data

    def db_getter():
        return aggregator.database.get_current()

    def save_status_getter():
        return aggregator.database.save_mode

    # Setters
    def refresh_interval_setter(interval):
        aggregator.interval = interval

    def save_database_json(filename):
        aggregator.database.export_to_json(filename)

    def start_database_save():
        aggregator.database.start_run()

    def end_database_save():
        aggregator.database.end_run()
        
    getters_website = {'database': db_getter, 'save_status': save_status_getter}
    setters_website = {'aggregator_refresh_rate': refresh_interval_setter, 'start_save': start_database_save, 'end_save': end_database_save}

    # Thesaurus for remote units names
    units_thesaurus = {'rm1': 'GPS+IMU', 'rm2': 'Anemometer'}
    
    # Start aggregator
    aggregator = Aggregator(raw_data_getter=raw_data_getter, interval=1, database=None, output_dir='data')
    aggregator.start()

    # # Load JSON file - without Aggregator
    # track = Track()
    # track.load('data/chk/20250131-172606.json.chk')

    # def json_data_getter():
    #     return track.get_current()

    # getters_website = {'database': json_data_getter}
    
    # Start webapp in background
    web_app = WebApp(getters=getters_website, setters=setters_website, logger_fname=logger_fname, rm_thesaurus=units_thesaurus)
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
    # print('from interface', comms.raw_data)
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
    
