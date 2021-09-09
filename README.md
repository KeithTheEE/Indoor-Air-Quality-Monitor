


# Indoor Air Quality Monitor with CircuitPython

This library runs circuit python on a metro esp32-s2 to monitor air quality with a suite of sensors. 

## Overview 

It places all sensors into a generic sensor class, so a sensor array function can sweep through everything and simply run an update command. 

The sensor readings are placed into a sensor packet class, which grows in size for each new read until it's ready to be packaged in as a json string posted via wifi to a home server. 

Wifi communications are managed by a class to make it easier to initialize, handle connection errors, and manage reconnections in the event of networking issues. This class is a work in progress and will be expanded and slimmed down as necessary for network stability.

Anticipated networking issues are:
  - Socket management on the esp32-s2 itself --Somewhat implemented, but is over done in scenarios it does not apply to
  - server communication issues -- mostly implemented: retry typically works 
  - server being down -- Not explored, but hopefully the code is functional 
  - wifi network disconnect -- Not explored, no idea if the code can handle it
  - wifi network down -- checking for network being back up, and reconnecting is not explored. Additionally, there needs to be a point where the program drops old sensor packets as necessary. This triage is mildly implemented, but not extensively tested. 

### Sensors
- sgp40
- bme280
- pm2.5
- scd4x

With the exception of the pm2.5 (which is connected via uart), the code will ignore any sensor which isn't connected to the i2c bus. This makes it easier to grab a sensor for testing, without having the whole suite of sensors go offline. A drawback is sensors which require a period of initialization will have to reinitialize and their readings may be errant during that phase. 