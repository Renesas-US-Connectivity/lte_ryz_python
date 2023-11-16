import argparse
from enum import Enum, IntEnum
import json
import queue
import serial
import threading
import time
from typing import Tuple
from prompt_toolkit import PromptSession
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.patch_stdout import patch_stdout


serial_port = serial.Serial()
serial_rx_q = queue.Queue()
user_command_q = queue.Queue()


PROFILE_ID = "1"
# HTTP configure command. This command sets the parameters needed to establish the HTTP connection
HTTP_CFG_CMD_HEADER = "AT+SQNHTTPCFG="
HTTP_URL = "\"httpbin.org\""
# Footer details
#   Port 80
#   no authentication
#   empty user name
#   empty password
#   no SSL, 30 second txsfer timeout ( maximum time in seconds allowed for the HTTP(S) connection establishment/completion (if needed) and the data transfer)
#   1 second receive timeout (Maximum time in seconds to wait for the HTTP server response)
HTTP_CFG_CMD_FOOTER = "80,0,\"\",\"\",0,120,1"

# This command performs HTTP GET, HEAD or DELETE requests to the server
HTTP_QRY_CMD_HEADER = "AT+SQNHTTPQRY="
HTTP_BIN_GET_URL = "\"/get\""
HTTP_BIN_DELETE_URL = "\"/delete\""
HTTP_BIN_STREAM_URL = "\"/stream"

# This command reads the HTTP response content data received with the last HTTP response (the HTTP
# response reception advertised by the +SQNHTTPRING notification)
HTTP_RCV_CMD_HEADER = "AT+SQNHTTPRCV="
HTTP_STATUS_OK = "200"

# This command performs a POST or PUT request to a HTTP server and sends it the data.
HTTP_SND_CMD_HEADER = "AT+SQNHTTPSND="
HTTP_BIN_POST_URL = "\"/post\""

HTTP_BIN_PUT_URL = "\"/put\""


class HTTP_QRY_COMMNAND(str, Enum):
    GET = "0"
    HEAD = "1"
    DELETE = "2"


class HTTP_SND_COMMNAND(str, Enum):
    POST = "0"
    PUT = "1"


class RESPONSE_ERROR(IntEnum):
    OK = 0
    ERROR = 1
    TIMEOUT = 2


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


def get_user_input():
    # Accepted commands
    commands = ['HTTP_DELETE',
                'HTTP_GET',
                'HTTP_POST',
                'HTTP_PUT',
                'HTTP_STREAM',
                'EXIT'
                ]
    commands.sort()
    word_completer = WordCompleter(commands, ignore_case=True)

    session = PromptSession(completer=word_completer)
    while True:
        with patch_stdout():
            try:
                input_str: str = session.prompt('>>> ')
                if input_str:
                    args = input_str.split()
                    # Ensure we have a valid command
                    if len(args) > 0 and args[0] in commands:
                        user_command_q.put_nowait(input_str)
                    else:
                        print("Invalid command")
            except KeyboardInterrupt:
                return


def handle_command():
    while True:
        command: str = user_command_q.get()
        args = command.split(' ', maxsplit=1)
        match args[0]:
            case 'HTTP_DELETE':
                http_delete()

            case 'HTTP_GET':
                http_get()

            case 'HTTP_POST':
                if len(args) == 1:
                    message = "default POST message"
                else:
                    message = args[1]
                http_post(message)

            case 'HTTP_PUT':
                if len(args) == 1:
                    message = "default PUT message"
                else:
                    message = args[1]
                    print(f"Using: {message}")
                http_put(message)

            case 'HTTP_STREAM':
                if len(args) == 1:
                    num_responses = 10
                else:
                    num_responses = int(args[1])

                http_stream(num_responses)

            case 'EXIT':
                return


def http_delete():

    print(f"Sending HTTP GET request to {HTTP_URL}")
    # HTTP configure command. This command sets the parameters needed to establish the HTTP connection
    cmd = HTTP_CFG_CMD_HEADER + PROFILE_ID + "," + HTTP_URL + "," + HTTP_CFG_CMD_FOOTER
    send_command(cmd)
    response, error = wait_for_response('OK')

    if error != RESPONSE_ERROR.OK:
        print(f"Error: {error.name}. Failed at {cmd}")
        return

    # HTTP Query. This command performs HTTP GET, HEAD or DELETE requests to the server
    cmd = HTTP_QRY_CMD_HEADER + PROFILE_ID + "," + HTTP_QRY_COMMNAND.DELETE + "," + HTTP_BIN_DELETE_URL
    send_command(cmd)
    response, error = wait_for_response('+SQNHTTPRING')

    if error != RESPONSE_ERROR.OK:
        print(f"Error: {error.name}. Failed at {cmd}")
        return 

    http_status_code = http_response_to_status_code(response)
    if http_status_code != HTTP_STATUS_OK:
        print(f"HTTP Error: {http_status_code}")

    # This command reads the HTTP response content data received with the last HTTP response (the HTTP
    # response reception advertised by the +SQNHTTPRING notification)
    cmd = HTTP_RCV_CMD_HEADER + PROFILE_ID
    send_command(cmd)
    response, error = wait_for_response('OK')

    if error != RESPONSE_ERROR.OK:
        print(f"Error: {error.name}. Failed at {cmd}")
        return

    response = response[:-2]  # remove trailing "OK"
    response = response.strip("<<<")  # remove leading "<<<"
    json_dict = json.loads(response)  # load data into dictionary

    print("\nReceived response:")
    print("=================JSON RESPONSE=====================")
    print(json.dumps(json_dict, sort_keys=False, indent=4))
    print("===================================================")


def http_get():

    print(f"Sending HTTP GET request to {HTTP_URL}")
    # HTTP configure command. This command sets the parameters needed to establish the HTTP connection
    cmd = HTTP_CFG_CMD_HEADER + PROFILE_ID + "," + HTTP_URL + "," + HTTP_CFG_CMD_FOOTER
    send_command(cmd)
    response, error = wait_for_response('OK')

    if error != RESPONSE_ERROR.OK:
        print(f"Error: {error.name}. Failed at {cmd}")
        return

    # HTTP Query. This command performs HTTP GET, HEAD or DELETE requests to the server
    cmd = HTTP_QRY_CMD_HEADER + PROFILE_ID + "," + HTTP_QRY_COMMNAND.GET + "," + HTTP_BIN_GET_URL
    send_command(cmd)
    response, error = wait_for_response('+SQNHTTPRING')

    if error != RESPONSE_ERROR.OK:
        print(f"Error: {error.name}. Failed at {cmd}")
        return 

    http_status_code = http_response_to_status_code(response)
    if http_status_code != HTTP_STATUS_OK:
        print(f"HTTP Error: {http_status_code}")

    # This command reads the HTTP response content data received with the last HTTP response (the HTTP
    # response reception advertised by the +SQNHTTPRING notification)
    cmd = HTTP_RCV_CMD_HEADER + PROFILE_ID
    send_command(cmd)
    response, error = wait_for_response('OK')

    if error != RESPONSE_ERROR.OK:
        print(f"Error: {error.name}. Failed at {cmd}")
        return

    response = response[:-2]  # remove trailing "OK"
    response = response.strip("<<<")  # remove leading "<<<"
    json_dict = json.loads(response)  # load data into dictionary

    print("\nReceived response:")
    print("=================JSON RESPONSE=====================")
    print(json.dumps(json_dict, sort_keys=False, indent=4))
    print("===================================================")


def http_post(message: str):

    print(f"Sending HTTP POST request to {HTTP_URL}")

    # HTTP configure command. This command sets the parameters needed to establish the HTTP connection
    cmd = HTTP_CFG_CMD_HEADER + PROFILE_ID + "," + HTTP_URL + "," + HTTP_CFG_CMD_FOOTER
    send_command(cmd)
    response, error = wait_for_response('OK')

    if error != RESPONSE_ERROR.OK:
        print(f"Error: {error.name}. Failed at {cmd}")
        return

    # POST request to a HTTP server and sends it the data.
    cmd = HTTP_SND_CMD_HEADER + PROFILE_ID + "," + HTTP_SND_COMMNAND.POST + "," + HTTP_BIN_POST_URL + "," + str(len(message))
    send_command(cmd)
    response, error = wait_for_response('>')
    if error != RESPONSE_ERROR.OK:
        print(f"Error: {error.name}. Failed at {cmd}")
        return

    send_command(message, False)
    response, error = wait_for_response('+SQNHTTPRING')

    if error != RESPONSE_ERROR.OK:
        print(f"Error: {error.name}. Failed at {cmd}")
        return

    http_status_code = http_response_to_status_code(response)
    if http_status_code != HTTP_STATUS_OK:
        print(f"HTTP Error: {http_status_code}")
        return

    # This command reads the HTTP response content data received with the last HTTP response (the HTTP
    # response reception advertised by the +SQNHTTPRING notification)
    cmd = HTTP_RCV_CMD_HEADER + PROFILE_ID
    send_command(cmd)
    response, error = wait_for_response('OK')
    if error != RESPONSE_ERROR.OK:
        print(f"Error: {error.name}. Failed at {cmd}")

    response = response[:-2]  # remove trailing "OK"
    response = response.strip("<<<")  # remove leading "<<<"
    json_dict = json.loads(response)  # load data into dictionary

    print("\nReceived response:")
    print("=================JSON RESPONSE=====================")
    print(json.dumps(json_dict, sort_keys=False, indent=4))
    print("===================================================")


def http_put(message: str):

    print(f"Sending HTTP PUT request to {HTTP_URL}")

    # HTTP configure command. This command sets the parameters needed to establish the HTTP connection
    cmd = HTTP_CFG_CMD_HEADER + PROFILE_ID + "," + HTTP_URL + "," + HTTP_CFG_CMD_FOOTER
    send_command(cmd)
    response, error = wait_for_response('OK')

    if error != RESPONSE_ERROR.OK:
        print(f"Error: {error.name}. Failed at {cmd}")
        return

    # PUT request to a HTTP server and sends it the data.
    cmd = HTTP_SND_CMD_HEADER + PROFILE_ID + "," + HTTP_SND_COMMNAND.PUT + "," + HTTP_BIN_PUT_URL + "," + str(len(message))
    send_command(cmd)
    response, error = wait_for_response('>')
    if error != RESPONSE_ERROR.OK:
        print(f"Error: {error.name}. Failed at {cmd}")
        return

    send_command(message, False)
    response, error = wait_for_response('+SQNHTTPRING')

    if error != RESPONSE_ERROR.OK:
        print(f"Error: {error.name}. Failed at {cmd}")
        return

    http_status_code = http_response_to_status_code(response)
    if http_status_code != HTTP_STATUS_OK:
        print(f"HTTP Error: {http_status_code}")
        return

    # This command reads the HTTP response content data received with the last HTTP response (the HTTP
    # response reception advertised by the +SQNHTTPRING notification)
    cmd = HTTP_RCV_CMD_HEADER + PROFILE_ID
    send_command(cmd)
    response, error = wait_for_response('OK')
    if error != RESPONSE_ERROR.OK:
        print(f"Error: {error.name}. Failed at {cmd}")

    response = response[:-2]  # remove trailing "OK"
    response = response.strip("<<<")  # remove leading "<<<"
    json_dict = json.loads(response)  # load data into dictionary

    print("\nReceived response:")
    print("=================JSON RESPONSE=====================")
    print(json.dumps(json_dict, sort_keys=False, indent=4))
    print("===================================================")


def http_response_to_status_code(http_response: str):

    response_split = http_response.split(",")
    status_code = response_split[1]
    return status_code


def http_stream(num_responses: int):

    print(f"Sending HTTP STREAM test to {HTTP_URL}, streaming {num_responses} chunks")
    # HTTP configure command. This command sets the parameters needed to establish the HTTP connection
    cmd = HTTP_CFG_CMD_HEADER + PROFILE_ID + "," + HTTP_URL + "," + HTTP_CFG_CMD_FOOTER
    send_command(cmd)
    response, error = wait_for_response('OK')

    if error != RESPONSE_ERROR.OK:
        print(f"Error: {error.name}. Failed at {cmd}")
        return

    # HTTP Query. This command performs HTTP GET, HEAD or DELETE requests to the server
    cmd = HTTP_QRY_CMD_HEADER + PROFILE_ID + "," + HTTP_QRY_COMMNAND.GET + "," + HTTP_BIN_STREAM_URL + "/" + str(num_responses) + "\""
    send_command(cmd)
    response, error = wait_for_response('+SQNHTTPRING')

    if error != RESPONSE_ERROR.OK:
        print(f"Error: {error.name}. Failed at {cmd}")
        return 

    http_status_code = http_response_to_status_code(response)
    if http_status_code != HTTP_STATUS_OK:
        print(f"HTTP Error: {http_status_code}")

    # This command reads the HTTP response content data received with the last HTTP response (the HTTP
    # response reception advertised by the +SQNHTTPRING notification)
    cmd = HTTP_RCV_CMD_HEADER + PROFILE_ID
    send_command(cmd)
    response, error = wait_for_response('OK')

    if error != RESPONSE_ERROR.OK:
        print(f"Error: {error.name}. Failed at {cmd}")
        return

    print("Stream test successful")


def main(com_port: str, flow_cntrl: bool):

    global serial_port
    serial_port = open_serial_port(com_port, flow_cntrl)

    cli_task = threading.Thread(target=get_user_input)
    cli_task.daemon = True
    cli_task.start()

    lte_rx_task = threading.Thread(target=get_lte_response)
    lte_rx_task.daemon = True
    lte_rx_task.start()

    command_handle_task = threading.Thread(target=handle_command)
    command_handle_task.daemon = True
    command_handle_task.start()

    while True:
        # If one of the tasks exits, exit the application
        if cli_task.is_alive() and lte_rx_task.is_alive() and command_handle_task.is_alive():
            time.sleep(1)
        else:
            return


def open_serial_port(com_port: str, flow_cntrl: bool) -> serial.Serial:
    ser = serial.Serial()
    ser.port = com_port
    ser.baudrate = 115200
    ser.rtscts = flow_cntrl
    ser.timeout = 1
    ser.open()
    return ser


def send_command(command: str, add_terminator: bool = True):
    print(f"\t--> Tx: {command}")
    if add_terminator:
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
            return response, RESPONSE_ERROR.ERROR
        elif "+CEREG" in response_buffer:
            continue

        response += response_buffer


if __name__ == "__main__":
    parser = argparse.ArgumentParser(prog='LTE CLI',
                                     description='')

    parser.add_argument("com_port", type=str, help='COM port for your development kit')
    parser.add_argument("--flow_cntrl", action="store_true", help='Enable serial flow control')

    args = parser.parse_args()

    try:
        main(args.com_port, args.flow_cntrl)
    except KeyboardInterrupt:
        pass

    print("Exiting...")
