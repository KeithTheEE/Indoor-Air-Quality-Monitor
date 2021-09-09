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
import neopixel


# Sensor Imports
import adafruit_sgp40
from adafruit_sgp40 import voc_algorithm
from adafruit_bme280 import basic as adafruit_bme280
from adafruit_pm25.uart import PM25_UART
import adafruit_scd4x


pixels = neopixel.NeoPixel(board.ne, 1, brightness=0.3)
pixels.direction = digitalio.Direction.OUTPUT

pixels[0] = (180, 0, 255)
pixels.show()

#import test_the_wifi
#time.sleep(1)



#import sgp40_VOC_algorithm # Dummy file to test VOC Algorithm port soon
#print("Sleeping past the autoreload..")
#time.sleep(300) 


class Sensor(object):
    def __init__(self, name):
        self.name = name
        self.is_connected = False
        self._in_keys = []
        pass

    def set_input_keys(self, in_keys):
        self._in_keys = in_keys
    def set_update(self, update_function):
        '''
        Attach a 'update reading' function to this class
        making the call to update convient 
        '''
        self._run_update = update_function
        return
    def set_null_state(self, null_readings):
        '''
        Set default returns if a sensor is having trouble 
        replying for update, formatted according to
        how the update formats a return key, value pair
        '''
        self._null_reading_value = null_readings

    def update(self, sensor, *args, **kwargs):
        '''
        Talks to the sensor and returns the sensor readings
        in a key value paired dictionary naming which sensor
        values were read
        '''
        #print("HIOINO", *args, **kwargs)
        #print(self._in_keys)
        try:
            results = self._run_update(sensor, *args, **kwargs)
        except RuntimeError:
            results = self._null_reading_value
        return results

class Sensor_Array(object):
    def __init__(self, list_of_sensors=[]):
        self.list_of_sensors = list_of_sensors
    def update_sensors(self):
        self.sensor_readings = {}

        timestamp = time.time()
        self.sensor_readings['raw_timestamp'] = timestamp
        for sensor in self.list_of_sensors:
            if sensor.is_connected:
                #print("Updating new sensor, grabbing keys..")
                #print(sensor.name)
                key_args = {x:self.sensor_readings[x] for x in self.sensor_readings if x in sensor._in_keys}
                #print('>',key_args)
                if sensor._in_keys:
                    sensor_values = sensor.update(sensor.sensor, key_args)
                else:
                    sensor_values = sensor.update(sensor.sensor)
                self.sensor_readings.update(sensor_values)
        return self.sensor_readings

class Sensors_Packet(object):
    '''
    Dictionary structure which the sensors dump their values into
    Can be replace with dummy values without issue
    
    TODO:
    - compress stable reading so longer bouts of stable values
        results in fewer bytes needed 
    '''
    def __init__(self):
        self.packet = {}
        self.pack_size = 0
    def update(self, sensor_readings):
        for key in sensor_readings:
            if key in self.packet:
                self.packet[key].append(sensor_readings[key])
            else:
                self.packet[key] = [sensor_readings[key]]
                
        self.pack_size += 1
    def print_and_update_raw(self, sensor_readings):
        '''
        Appends all of the input values to the packet dictionary then prints
        out the latest values
        '''
        self.update(sensor_readings)
        # Watch status and Memory Consumption as time goes on
        spacer = '    '
        vals = [str(x) for x in sensor_readings.values()]
        print(spacer.join(vals))

        return
    def print_and_update_limited(self, sensor_readings):
        '''
        Appends all of the input values to the packet dictionary then prints
        out the latest values
        '''
        self.update(sensor_readings)
        # Watch status and Memory Consumption as time goes on
        spacer = '    '
        msg = str(sensor_readings['raw_timestamp'])+spacer+str(gc.mem_free())+spacer
        if 'temp_c' in sensor_readings:
            msg += str(sensor_readings['temp_c']*9/5+32) + spacer
        if 'humidity' in sensor_readings: 
            msg += str(sensor_readings['humidity']) + spacer
        if 'pressure' in sensor_readings:
            msg += str(sensor_readings['pressure']) + spacer
        if 'sgp40_raw' in sensor_readings:
            msg += str(sensor_readings['sgp40_raw']) + spacer
        if 'voc_index' in sensor_readings:
            msg += str(sensor_readings['voc_index']) + spacer
        if 'particles 03um' in sensor_readings:
            msg += str(sensor_readings['particles 03um']) + spacer
        if 'particles 05um' in sensor_readings:
            msg += str(sensor_readings['particles 05um']) + spacer
        if 'particles 10um' in sensor_readings:
            msg += str(sensor_readings['particles 10um']) + spacer
        if 'CO2' in sensor_readings:
            msg += str(sensor_readings['CO2']) + spacer
        if 'SCD4X_temp' in sensor_readings:
            msg += str(sensor_readings['SCD4X_temp']) + spacer
        if 'SCD4x_humidity' in sensor_readings:
            msg += str(sensor_readings['SCD4x_humidity']) + spacer
        #vals = [str(x) for x in sensor_readings.values()]
        print(msg)

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
        success = False
        if self.connected_to_network: 
            
            run_count = 0
            run_limit = 500 
            try:
                response = self.https.post(post_sensor_webpage, json=packet_json) 
                success = True
                pixels[0]=(0,0,0)
                pixels.show()
                try: 
                    self._close_request_socket(response)
                except Exception as e:
                    print("During closing of socket, error occured", e)
            except RuntimeError as e:
                # Reasons
                # Server may be down
                run_count += 1
                print("> Runtime Error Caught", e)
                success = False
            except OSError as e:
                self.connected_to_network = False
                print("> Os Error Caught", e)
                success = False
            except OutOfRetries as e:
                print(">Outofretries>", e)
                success = False


            if run_count == run_limit:
                self.homeserver_is_online = False
            
            if not success:
                pixels[0]=(100,0,0)
                pixels.show()

        return success


def set_bme280_sea_level_pressure(bme280, my_network):
    # Grab up to date pressure at sealevel
    sea_level = my_network.get_sea_level()
    if my_network.homeserver_is_online:
        bme280.sea_level_pressure = sea_level
    return bme280




# Start i2c and UART bus and ADC and connect to sensors
i2c = busio.I2C(board.SCL, board.SDA)
uart = busio.UART(tx=board.IO5, rx=board.IO6, baudrate=9600)

## Start up and initalize sensors


# BME280
def read_bme(bme_sensor):
    results = {}
    results['pressure'] = bme_sensor.pressure
    results['humidity'] = bme_sensor.relative_humidity
    results['temp_c'] = bme_sensor.temperature
    return results

bme280 = Sensor("bme280")
bme280.set_null_state(null_readings={'temp_c':-40, 
                          'humidity':-1,
                          'pressure':-1})
bme280.set_update(read_bme)
try: 
    bme280.sensor = adafruit_bme280.Adafruit_BME280_I2C(i2c)
    bme280.is_connected = True
    # Default value in event server is offline
    bme280.sensor.sea_level_pressure = 1001.7
except ValueError:
    print("BME 280 Sensor not found")
    pass



#bme280 = adafruit_bme280.Adafruit_BME280_I2C(i2c)
def read_sgp40(sgp40_sensor, x):
    temp_c = x['temp_c']
    humidity = x['humidity']
    results = {}
    raw_value = sgp40_sensor.measure_raw(temp_c, humidity)
    raw = sgp40_sensor.measure_raw(temp_c, humidity)
    results['sgp40_raw'] = raw
    if raw < 0:
        voc_index = -1
    else:
        voc_index = sgp40_sensor._voc_algorithm.vocalgorithm_process(raw)
    results['voc_index'] = voc_index
    return results

sgp40 = Sensor("sgp40")
sgp40.set_null_state(null_readings={'sgp40_raw':-1, 
                          'voc_index':-1})
sgp40.set_update(read_sgp40)
sgp40.set_input_keys(['temp_c', 'humidity'])
try:
    sgp40.sensor = adafruit_sgp40.SGP40(i2c)
    sgp40.sensor._voc_algorithm = voc_algorithm.VOCAlgorithm()
    sgp40.sensor._voc_algorithm.vocalgorithm_init()
    print("Made it")
    sgp40.is_connected = True
except ValueError:
    print("SGP40 Sensor not found")
    pass

#sgp = adafruit_sgp40.SGP40(i2c)


# Connect to a PM2.5 sensor over UART

def read_pm25(pm25_sensor):
    read_tries = 0
    read_attempt_limit = 5

    while read_tries < read_attempt_limit:
        try:
            particles = pm25_sensor.read()
            break
        except RuntimeError:
            print("RuntimeError while reading pm25, trying again. Attempt: ", read_tries)
            read_tries += 1
            time.sleep(0.1)
    if read_tries >= read_attempt_limit:
        raise RuntimeError
    return particles
reset_pin = None
pm25 = Sensor("PM2.5")
pm25.set_null_state(null_readings={"particles 03um": -1, 
                      "particles 05um": -1, 
                      "particles 100um": -1, 
                      "particles 10um": -1, 
                      "particles 25um": -1, 
                      "particles 50um": -1, 
                      "pm10 env": -1, 
                      "pm10 standard": -1, 
                      "pm100 env": -1, 
                      "pm100 standard": -1, 
                      "pm25 env": -1, 
                      "pm25 standard": -1})
pm25.set_update(read_pm25)
try:
    pm25.sensor = PM25_UART(uart, reset_pin)
    pm25.is_connected = True
except RuntimeError:
    print("Pm2.5 Sensor Not Found")

#scd4x Sensor
def read_scd4x(scd4x_sensor):
    results = {}
    if scd4x_sensor.data_ready:
        results['CO2'] = scd4x_sensor.CO2
        results['SCD4X_temp'] = scd4x_sensor.temperature
        results['SCD4x_humidity'] = scd4x_sensor.relative_humidity
    else:
        # sensor's not ready
        raise RuntimeError
    return results
scd4x = Sensor("SCD4x")
scd4x.set_null_state(null_readings={'CO2':-1,
                        "SCD4X_temp":-40,
                        "SCD4x_humidity":-1})
scd4x.set_update(read_scd4x)
try:
    scd4x.sensor = adafruit_scd4x.SCD4X(i2c)
    scd4x.sensor.start_periodic_measurement()
    scd4x.is_connected = True
except ValueError:
    print("SCD4X Sensor Not Found")





# initalize Network
my_network = Current_Web_Status()
my_network.connect_with_mywifi()
my_network.start_sessions_pool()




# bme280 = set_bme280_sea_level_pressure(bme280, my_network)
# print("Altitude = %0.2f meters" % bme280.altitude) # Home Altitude is about 270-264 meters
# header_string = "Time\t\t Free Memory\t RAWGAS\t Temp\t\t Humidity\t Pressure"
# print(header_string) 



i = 0
connected_sensors = Sensor_Array([bme280, sgp40, pm25, scd4x])
sensor_pack = Sensors_Packet()
packet_size_limit = 20
start_time = time.time()

packets_to_post = []

pixels[0] = (0,0,0)
pixels.show()

while True:
    start_time = time.monotonic_ns() / 10**9
    
    # Read sensors
    sensor_readings = connected_sensors.update_sensors()          
    sensor_pack.print_and_update_limited(sensor_readings)

    # Sensor pack is at size, add it to the the list of packs to post
    # and generate a new one
    if sensor_pack.pack_size >= packet_size_limit:
        packets_to_post.append(sensor_pack)
        sensor_pack = Sensors_Packet()
    # there's a pack to post, let's post it
    if len(packets_to_post) > 0:
        success = my_network.post_sensor_packet(packets_to_post[0])
        if success:
            packets_to_post = packets_to_post[1:] 
    # there's too many packs, let's just drop one for ram
    if len(packets_to_post) > 10:
        packets_to_post[1:]
            

    # Sleep between no and 1 second adjusted for the time of the sensor reads
    sleep_time = min(1, max(0, 1-((time.monotonic_ns() / 10**9)-start_time)))
    #print("SLeeping", sleep_time)
    if sleep_time > 0:
        time.sleep(sleep_time)  