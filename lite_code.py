import board
import digitalio
import time
import busio
import adafruit_requests 
import json
import gc
import ipaddress
import ssl
import wifi
import socketpool


# Default value in event server is offline
bme280_sea_level_pressure = 1001.7


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
                        'dummy_val': []}
        self.pack_size = 0
    def update(self, raw_timestamp, dummy_val):
        self.packet['raw_timestamp'].append(raw_timestamp) 
        self.packet['dummy_val'].append(dummy_val) 
        self.pack_size += 1
    def print_and_update(self,raw_timestamp, dummy_val):
        self.packet['raw_timestamp'].append(raw_timestamp) 
        self.packet['dummy_val'].append(dummy_val) 
        self.pack_size += 1
        # Watch status and Memory Consumption as time goes on
        print(raw_timestamp, '\t',gc.mem_free(), '\t',dummy_val)
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

        self._base_url = 'http://192.168.1.100:7000/'
    def connect_with_mywifi(self):
        try:
            from secrets import secrets
        except ImportError:
            print("WiFi secrets are kept in secrets.py, please add them there!")
            raise

        try:
            wifi.radio.connect(secrets["ssid"], secrets["password"])
            self.connected_to_network = True
        except:
            self.connected_to_network = False 
            print("CAN'T CONNECT TO NEWTORK")

        return 
    def start_sessions_pool(self):
        self.pool = socketpool.SocketPool(wifi.radio)
        self.connection_pool_available = True
        pass
    def _get_request_socket(self):
        
        if self._used_sockets < 4:
            # keep track of used sockets when drawing from pool
            request = adafruit_requests.Session(self.pool, ssl.create_default_context())
            self._used_sockets += 1
            self._total_sockets_requested += 1
            print("TOTAL REQUESTED SOCKETS: ", self._total_sockets_requested)
            self.request = request
            return request
        
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
            request = self._get_request_socket()
            site_weather_vals = self._base_url+ "api/weather_status"
            print("Fetching and parsing json from", site_weather_vals)


            # Get Json
            try:
                response = request.get(site_weather_vals) 
                text = response.text
                self.homeserver_is_online = True
                sea_level_pressure = json.loads(text)["sea level"]
            except:
                self.homeserver_is_online = False
                print("CAN'T CONNECT TO HOME SERVER")


            # Close Socket
            try: 
                self._close_request_socket(response)
            except Exception as e:
                print(e)
                raise(e)
        return sea_level_pressure


    def post_sensor_packet(self, sensor_packet):
        '''
        Take in a packet of data, convert it to json, then try to 
        post it to the home server. 
        '''

        post_sensor_webpage = self._base_url+ "enviornmental_sensors"
        packet_json = sensor_packet.prep_json() 
        
        # If we're not connected, try to connect just in case
        if not self.connected_to_network:
            self.connect_with_mywifi() 
            
        
        request = self._get_request_socket()

        # Go to server
        if self.connected_to_network: 
            
            run_count = 0
            run_limit = 2 
            while run_count < run_limit:
                try:
                    response = request.post(post_sensor_webpage, json=packet_json) 
                    break
                except RuntimeError:
                    run_count += 1
                except OSError:
                    self.connected_to_network = False


            if run_count == run_limit:
                self.homeserver_is_online = False

            try: 
                self._close_request_socket(response)
            except Exception as e:
                print(e)
        return




def set_bme280_sea_level_pressure(my_network):
    # Just performs a get request, value is of no concequence
    sea_level = my_network.get_sea_level()
    if my_network.homeserver_is_online:
        bme280_sea_level_pressure = sea_level
    return bme280_sea_level_pressure


Ok so I'm not that great at paring code down--here's the full version:https://gist.github.com/CrakeNotSnowman/f6a4af43cd83b23b4f4226c6a2ec228e
And here it's cut down: https://gist.github.com/CrakeNotSnowman/9609deec29c82fc10257247876c5406a
I'm having trouble figuring out how to successfully close the sockets on a Metro Esp32-S2 once I'm done with a get or post request
I threw them into a class to make it easier to manage various kinds of networking issues--wifi or home server being down--so the logic flow is a bit awkward



# initalize Network
my_network = Current_Web_Status()
my_network.connect_with_mywifi()
my_network.start_sessions_pool()




bme280_sea_level_pressure = set_bme280_sea_level_pressure(my_network)

header_string = "Time\t\t Free Memory\t Dummy_val
print(header_string) 


i = 0
sensor_pack = Sensors_Packet()

while True:
    i += 1
    if i > 50:
        i = 0
        print(header_string)
    if sensor_pack.pack_size >= 100:
        my_network.post_sensor_packet(sensor_pack)
        sensor_pack = Sensors_Packet()
        
    sensor_pack.print_and_update(time.time(), time.time()%7)

    time.sleep(1) 