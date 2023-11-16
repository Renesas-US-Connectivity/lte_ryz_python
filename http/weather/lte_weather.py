import argparse
from enum import IntEnum
import json
import queue
import serial
import threading
from typing import Tuple


serial_port = serial.Serial()
serial_rx_q = queue.Queue()


'''
Note requesting weather by city name has been depracted by openweathermap.org. However, that API has been used here for simplicity.

Per openweathermap.org:
Please note that API requests by city name, zip-codes and city id have been deprecated. Although they are still available for use, bug fixing and updates are no longer available for this functionality.
Built-in API request by city name
'''
OPEN_WEATHER_API_KEY = ""  # Fill in your www.openweathermap.org API key here
HTTP_GET_WEATHER_HEADER = "AT+SQNHTTPCFG=1,\"api.openweathermap.org/data/2.5/weather?appid=" + OPEN_WEATHER_API_KEY
HTTP_GET = "AT+SQNHTTPQRY=1,0,\"/get\""
HTTP_RCV = "AT+SQNHTTPRCV=1"
HTTP_STATUS_OK = "200"


class RESPONSE_ERROR(IntEnum):
    OK = 0
    ERROR = 1
    TIMEOUT = 2


def http_response_parse_status_code(http_response: str):

    response_split = http_response.split(",")
    status_code = response_split[1]
    return status_code


def get_lte_response():
    while True:
        received = serial_port.readline()
        # uncomment below to see raw data received
        # print(f"\t<-- Rx: {received}")
        received = received.strip(b'\r\n')
        if not received:
            continue
        print(f"\t<-- Rx: {received.decode()}")
        serial_rx_q.put_nowait(received.decode())


def get_weather(location: str, print_json: bool):
    print(f"Requesting weather for {location} from openweathermap.org...\n")

    cmd = HTTP_GET_WEATHER_HEADER + "&q=" + location + "\""
    send_command(cmd)
    response, error = wait_for_response("OK")
    if error != RESPONSE_ERROR.OK:
        print(f"Error: {error.name}. Failed at {cmd}")
        return

    cmd = HTTP_GET
    send_command(cmd)
    response, error = wait_for_response("+SQNHTTPRING")
    if error != RESPONSE_ERROR.OK:
        print(f"Error: {error.name}. Failed at {cmd}")
        return

    http_status_code = http_response_parse_status_code(response)
    if http_status_code != HTTP_STATUS_OK:
        print(f"HTTP Error: {http_status_code}")
        return

    cmd = HTTP_RCV
    send_command(cmd)
    response, error = wait_for_response("OK")
    if error != RESPONSE_ERROR.OK:
        print(f"Error: {error.name}. Failed at {cmd}")
        return

    response = response[:-2]  # remove trailing "OK"
    response = response.strip("<<<")  # remove leading "<<<"
    json_dict = json.loads(response)  # load data into dictionary

    if print_json:
        print("\nReceived weather data:")
        print("=================JSON RESPONSE=====================")
        print(json.dumps(json_dict, sort_keys=False, indent=4))
        print("===================================================")

    print(f"\nWeather for {location}:")
    forecast_desc = json_dict['weather'][0]['description'].title()
    print(f"\tForecast: {forecast_desc}")
    print(f"\tTemperature (°F): {round(kelvin_to_fahrenheit(json_dict['main']['temp']))}")
    print(f"\tHumidity (RH): {json_dict['main']['humidity']}")


def kelvin_to_fahrenheit(kelvin: int):
    return (9.0 / 5.0) * (kelvin - 273.15) + 32.0


def main(com_port: str, location: str, flow_cntrl: bool, print_json: bool):

    global serial_port
    serial_port = open_serial_port(com_port, flow_cntrl)

    lte_task = threading.Thread(target=get_lte_response)
    lte_task.daemon = True
    lte_task.start()

    get_weather(location, print_json)


def open_serial_port(com_port: str, flow_cntrl: bool) -> serial.Serial:
    ser = serial.Serial()
    ser.port = com_port
    ser.baudrate = 115200
    ser.rtscts = flow_cntrl
    ser.timeout = 1
    ser.open()
    return ser


def send_command(command: str):
    print(f"\t--> Tx: {command}")
    if command != "+++":
        command += "\r"
    # uncomment below to see raw data transmitted
    # print(f"\t--> Tx:{command.encode()}")
    serial_port.write(command.encode())


def wait_for_response(expected: str) -> Tuple[str, RESPONSE_ERROR]:
    response = str()
    response_buffer = str()
    while True:
        try:
            response_buffer = serial_rx_q.get(timeout=30)
        except queue.Empty:
            return str(), RESPONSE_ERROR.TIMEOUT

        if expected in response_buffer:

            response += response_buffer
            return response, RESPONSE_ERROR.OK
        elif "ERROR" in response_buffer:
            # print(f"ERROR in reponse")
            return response, RESPONSE_ERROR.ERROR
        elif "+CEREG" in response_buffer:
            continue

        response += response_buffer


if __name__ == "__main__":
    parser = argparse.ArgumentParser(prog='LTE CLI',
                                     description='')

    parser.add_argument("com_port", type=str, help='COM port for your development kit')
    parser.add_argument("location", type=str, nargs='+', help='Location to get weather from. Example: New York,NY,US')
    parser.add_argument("--flow_cntrl", action="store_true", help='Enable serial flow control')
    parser.add_argument("--print_json", action="store_true", help='Print the raw JSON response from openweathermap.org')

    args = parser.parse_args()

    try:
        location = ' '.join(args.location)
        main(args.com_port, location, args.flow_cntrl, args.print_json)
    except KeyboardInterrupt:
        pass
