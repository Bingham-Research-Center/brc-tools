# Download scripts for observation, forecast, etc data 
John Lawson and Michael Davies, Bingham Research Center, 2025

### Current procedure for getting live data to website 
Here is a guide and explanation of what's going on, using the live air-quality for Uinta Basin stations as example.

1. Get API tokens set up (Synoptic Weather; also to send from CHPC to Akamai) 
   - This is done by... (how to set up API keys securely and automatically where possible, but in an understandable way?)
2. Download data from Synoptic Weather with `get_map_obs.py`.
   - This script downloads the latest data from Synoptic Weather
   - The data is saved in json that is cleaned ready for website
2. Send json to server with functions in `push_data.py`.
   - This script uses the `requests` library to send the json data to the server
   - To send...
   - On the website, when received...
3. Website displays data on Leaflet map. 

TODO:
- [ ] Add more documentation on how to use the scripts
- [ ] Add satellite, NWP, etc...
