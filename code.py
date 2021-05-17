import board
import digitalio
from digitalio import DigitalInOut, Direction, Pull
import time
import busio
import adafruit_requests 
from adafruit_requests import OutOfRetries
import json
import gc
import ipaddress
import ssl
import wifi
import socketpool


# Sensor Imports
import adafruit_sgp40
import adafruit_bme280
from adafruit_pm25.uart import PM25_UART




#import test_the_wifi
#time.sleep(1)

# Start i2c bus and connect to sensors
i2c = busio.I2C(board.SCL, board.SDA)
sgp = adafruit_sgp40.SGP40(i2c)
bme280 = adafruit_bme280.Adafruit_BME280_I2C(i2c)


# Connect to a PM2.5 sensor over UART
reset_pin = None
uart = busio.UART(tx=board.IO5, rx=board.IO6, baudrate=9600)
pm25 = PM25_UART(uart, reset_pin)

# Default value in event server is offline
bme280.sea_level_pressure = 1001.7


import sgp40_VOC_algorithm # Dummy file to test VOC Algorithm port soon
#print("Sleeping past the autoreload..")
#time.sleep(300) 

class Sensors_Packet(object):
    '''
    Dictionary structure which the sensors dump their values into
    Can be replace with dummy values without issue
    
    TODO:
    - compress stable reading so longer bouts of stable values
        results in fewer bytes needed 
    '''
    def __init__(self):
        self.packet = {'raw_timestamp': [],
                        'raw_gas': [], 
                        'temp_c': [],
                        'humidity': [],
                        'pressure': [],
                        'particles': {  "particles 03um": [], 
                                        "particles 05um": [], 
                                        "particles 100um": [], 
                                        "particles 10um": [], 
                                        "particles 25um": [], 
                                        "particles 50um": [], 
                                        "pm10 env": [], 
                                        "pm10 standard": [], 
                                        "pm100 env": [], 
                                        "pm100 standard": [], 
                                        "pm25 env": [], 
                                        "pm25 standard": []}}
        self.pack_size = 0
    def update(self, raw_timestamp, raw_gas, temp_c, humidity, pressure, particles):
        self.packet['raw_timestamp'].append(raw_timestamp) 
        self.packet['raw_gas'].append(raw_gas) 
        self.packet['temp_c'].append(temp_c) 
        self.packet['humidity'].append(humidity) 
        self.packet['pressure'].append(pressure) 
        for key in particles:
            self.packet['particles'][key].append(particles[key])
        self.pack_size += 1
    def print_and_update(self, raw_timestamp, raw_gas, temp_c, humidity, pressure, particles):
        '''
        Appends all of the input values to the packet dictionary then prints
        out the latest values
        '''
        self.packet['raw_timestamp'].append(raw_timestamp) 
        self.packet['raw_gas'].append(raw_gas) 
        self.packet['temp_c'].append(temp_c) 
        self.packet['humidity'].append(humidity) 
        self.packet['pressure'].append(pressure) 
        for key in particles:
            self.packet['particles'][key].append(particles[key])
        self.pack_size += 1
        # Watch status and Memory Consumption as time goes on
        print(raw_timestamp, '\t',gc.mem_free(), '\t',raw_gas,'\t',
                temp_c*9/5+32,'\t',humidity,'\t',pressure,'\t', 
                    particles["particles 03um"], 
                    particles["particles 05um"], 
                    particles["particles 10um"],
                    particles["particles 25um"],
                    particles["particles 50um"],
                    particles["particles 100um"])

        return
    def prep_json(self):
        '''
        Converts and returns the sensor packet into json ready string
        '''
        return json.dumps(self.packet)


class Current_Web_Status(object):
    '''
    Handles all 'connect to internet' type communications.

    Wraps everything in nice try and excepts to handle being
    outside of the wifi's range, and to handle events where
    the home server is down. Prioritizes reliable sensor recordings
    over internet connection

    Base Functionality:
        Networking:
            connect_with_mywifi
            start_sessions_pool
            _get_request_socket
            _close_request_socket

        Sensor Data Management:
            get_sea_level
            post_sensor_packet


    TODO:
    - Create a packet buffer for when transmittion is not possible,
        and ensure buffer does not exceed limited ram
    '''
    def __init__(self):
        self.connected_to_network = False
        self.connection_pool_available = False
        self.homeserver_is_online = False 
        self._used_sockets = 0
        self._total_sockets_requested = 0
        self._attempted_requests = 0
        self._successful_requests = 0
        self._socket_issues = 0
    def connect_with_mywifi(self):
        try:
            from secrets import secrets
        except ImportError:
            print("WiFi secrets are kept in secrets.py, please add them there!")
            raise

        try:
            wifi.radio.connect(secrets["ssid"], secrets["password"])
            self.connected_to_network = True
        except Exception as e:
            self.connected_to_network = False 
            print("CAN'T CONNECT TO NEWTORK")
            raise(e)

        return 
    def start_sessions_pool(self):
        self.socket = socketpool.SocketPool(wifi.radio)
        self.connection_pool_available = True
        self._get_request_socket()
        pass
    def _get_request_socket(self):
        self.https = adafruit_requests.Session(self.socket, ssl.create_default_context())
        
    def _close_request_socket(self, response):
        # Hopefully this works
        response.close()
        self._used_sockets -= 1
        print("active sockets", self._used_sockets)
        return 

    def get_sea_level(self):
        '''
        Go to the home server to try and grab json of weather values to 
        get pressure at sea level after checking if we're connected
        to the wifi

        '''

        sea_level_pressure = None

        # Before doing anything, double check if we think we're connected
        # If we're not connected, try to connect just in case
        if not self.connected_to_network:
            self.connect_with_mywifi()

        

        # Go to server
        if self.connected_to_network:
            # Open Socket
            site_weather_vals = "http://192.168.1.147:5000/api/weather_status"
            print("Fetching and parsing json from", site_weather_vals)


            # Get Json
            while True:
                try:
                    response = self.https.get(site_weather_vals) 
                    text = response.text
                    self.homeserver_is_online = True
                    sea_level_pressure = json.loads(text)["sea level"]



                    # Close Socket
                    try: 
                        self._close_request_socket(response)
                    except Exception as e:
                        print(e)
                        raise(e)
                    break
                except OutOfRetries:
                    print("OUT OF RETRIES CAUGHT")
                    pass
                except Exception as e:
                    self.homeserver_is_online = False
                    print("CAN'T CONNECT TO HOME SERVER")
                    #raise(e)
                break

        return sea_level_pressure


    def post_sensor_packet(self, sensor_packet):
        '''
        Take in a packet of data, convert it to json, then try to 
        post it to the home server. 
        '''

        post_sensor_webpage = "http://192.168.1.147:5000/enviornmental_sensors"
        packet_json = sensor_packet.prep_json() 
        
        # If we're not connected, try to connect just in case
        if not self.connected_to_network:
            self.connect_with_mywifi() 
            
        
        # Go to server
        if self.connected_to_network: 
            
            run_count = 0
            run_limit = 500 
            while run_count < run_limit:
                try:
                    response = self.https.post(post_sensor_webpage, json=packet_json) 
                    break
                except RuntimeError as e:
                    run_count += 1
                    print("> Runtime Error Caught", e)
                except OSError as e:
                    self.connected_to_network = False
                    print("> Os Error Caught", e)
                except OutOfRetries as e:
                    print(">Outofretries>", e)
                    time.sleep(2)


            if run_count == run_limit:
                self.homeserver_is_online = False

            try: 
                self._close_request_socket(response)
            except Exception as e:
                print(e)
        return




def set_bme280_sea_level_pressure(bme280, my_network):
    # Grab up to date pressure at sealevel
    sea_level = my_network.get_sea_level()
    if my_network.homeserver_is_online:
        bme280.sea_level_pressure = sea_level
    return bme280


def read_pm25_safely(pm25):
    read_tries = 0
    read_attempt_limit = 5

    while read_tries < read_attempt_limit:
        try:
            particles = pm25.read()
            break
        except RuntimeError:
            print("RuntimeError while reading pm25, trying again. Attempt: ", read_tries)
            read_tries += 1
            time.sleep(0.1)
    if read_tries >= read_attempt_limit:
        # Generate Fake particles
        particles  = {"particles 03um": -1, 
                      "particles 05um": -1, 
                      "particles 100um": -1, 
                      "particles 10um": -1, 
                      "particles 25um": -17, 
                      "particles 50um": -10, 
                      "pm10 env": -1, 
                      "pm10 standard": 5, 
                      "pm100 env": -1, 
                      "pm100 standard": 11, 
                      "pm25 env": -1, 
                      "pm25 standard": 11}
    return particles



# initalize Network
my_network = Current_Web_Status()
my_network.connect_with_mywifi()
my_network.start_sessions_pool()




bme280 = set_bme280_sea_level_pressure(bme280, my_network)
print("Altitude = %0.2f meters" % bme280.altitude) # Home Altitude is about 270-264 meters
header_string = "Time\t\t Free Memory\t RAWGAS\t Temp\t\t Humidity\t Pressure"
print(header_string) 


i = 0
sensor_pack = Sensors_Packet()
packet_size_limit = 100
start_time = time.time()

while True:
    i += 1
    if i > 50:
        i = 0
        #print(header_string)
    if sensor_pack.pack_size >= packet_size_limit:
        my_network.post_sensor_packet(sensor_pack)
        # try:
        #     my_network.post_sensor_packet(sensor_pack)
        # except Exception as e:
        #     print(e)
        #     print("Continuing..")
        sensor_pack = Sensors_Packet()
    
    particles = read_pm25_safely(pm25)
            
    sensor_pack.print_and_update(time.time(), sgp.raw,bme280.temperature,bme280.relative_humidity,bme280.pressure, particles)

    time.sleep(1) 