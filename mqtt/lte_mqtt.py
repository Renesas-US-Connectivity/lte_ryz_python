import argparse
from enum import Enum, IntEnum
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


# This command configures the MQTT stack with the client id, user name, and password (if required) for the
# remote broker, and the CA cert name to use for server authentication
MQTT_CFG_CMD_HEADER = "AT+SQNSMQTTCFG=0,"
MQTT_CLIENT_ID = "\"ryz_client\""

# This command is used to create new client connection to an external bridge or a broker
MQTT_CONNECT_CMD_HEADER = "AT+SQNSMQTTCONNECT=0,"
MQTT_SERVER = "\"test.mosquitto.org\""
MQTT_PORT = "1883"

# This command subscribes to a topic on a broker host previously contacted with AT+SQNSMQTTCONNECT. This
# command performs the subscription
MQTT_SUBSCRIBE_CMD_HEADER = "AT+SQNSMQTTSUBSCRIBE=0,"
MQTT_TOPIC = "\"renesas/lte_mqtt\""

# This command is used to publish a payload into a topic on to a broker host. It starts the publishing operation
MQTT_PUBLISH_CMD_HEADER = "AT+SQNSMQTTPUBLISH=0,"

# This command disconnects from a broker. Connection must have been previously initiated with the +SQNSMQTTCONNECT command
MQTT_DISCONNECT_CMD = "AT+SQNSMQTTDISCONNECT=0"

# This command delivers a message selected by its id or the last received message if <qos>=0. The device
# must have been connected using the AT+SQNSMQTTCONNECT command
MQTT_RCV_MESSAGE_CMD_HEADER = "AT+SQNSMQTTRCVMESSAGE=0,"


class MQTT_ERROR(IntEnum):
    OK = 0
    ERROR = 1


class QOS(str, Enum):
    AT_MOST_ONCE = "0"
    AT_LEAST_ONCE = "1"
    EXACTLY_ONCE = "2"


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


def handle_command():
    commands = ['MQTT_PUB',
                'MQTT_SUB',
                'EXIT'
                ]
    commands.sort()
    word_completer = WordCompleter(commands, ignore_case=True)

    global session
    session = PromptSession(completer=word_completer)

    while True:
        try: 
            input_str: str = session.prompt('>>> ')
            if input_str:
                args = input_str.split(' ', maxsplit=1)
                match args[0]:
                    case 'MQTT_PUB':
                        error = mqtt_pub()

                    case 'MQTT_SUB':
                        if len(args) == 1:
                            timeout = 30
                        else:
                            timeout = int(args[1])
                        error = mqtt_sub(timeout)

                    case 'EXIT':
                        return

                if error == MQTT_ERROR.ERROR:
                    return

        except KeyboardInterrupt:
            return


def main(com_port: str, flow_cntrl: bool):

    global serial_port
    serial_port = open_serial_port(com_port, flow_cntrl)

    lte_rx_task = threading.Thread(target=get_lte_response)
    lte_rx_task.daemon = True
    lte_rx_task.start()

    command_handle_task = threading.Thread(target=handle_command)
    command_handle_task.daemon = True
    command_handle_task.start()

    while True:
        # If one of the tasks exits, exit the application
        if lte_rx_task.is_alive() and command_handle_task.is_alive():
            time.sleep(1)
        else:
            return


def mqtt_disconnect():
    cmd = MQTT_DISCONNECT_CMD
    send_command(cmd)
    response, error = wait_for_response('+SQNSMQTTONDISCONNECT')
    if error != RESPONSE_ERROR.OK:
        # print(f"Error: {error.name}. Failed at {cmd}")
        return


def mqtt_pub() -> MQTT_ERROR:

    print(f"Publishing MQTT data to topic: {MQTT_TOPIC} on server: {MQTT_SERVER}")

    mqtt_disconnect()

    cmd = MQTT_CFG_CMD_HEADER + MQTT_CLIENT_ID
    send_command(cmd)
    response, error = wait_for_response('OK')
    if error != RESPONSE_ERROR.OK:
        print(f"Error: {error.name}. Failed at {cmd}")
        return MQTT_ERROR.ERROR

    cmd = MQTT_CONNECT_CMD_HEADER + MQTT_SERVER + "," + MQTT_PORT
    send_command(cmd)
    response, error = wait_for_response('+SQNSMQTTONCONNECT')
    if error != RESPONSE_ERROR.OK:
        print(f"Error: {error.name}. Failed at {cmd}")
        return MQTT_ERROR.ERROR

    response_code = response.split(",")[1]
    if response_code != "0":
        print(f"MQTT connect failed with error code: {response_code}")
        return MQTT_ERROR.ERROR

    while True:

        with patch_stdout():
            try:
                message = session.prompt('Enter a message to publish, or exit to quit: ')
                if message is None or message == "exit":
                    break
            except KeyboardInterrupt:
                return MQTT_ERROR.ERROR

        cmd = MQTT_PUBLISH_CMD_HEADER + MQTT_TOPIC + ",," + str(len(message))
        send_command(cmd)
        response, error = wait_for_response('>')
        if error != RESPONSE_ERROR.OK:
            print(f"Error: {error.name}. Failed at {cmd}")
            return MQTT_ERROR.ERROR

        send_command(message)
        response, error = wait_for_response('+SQNSMQTTONPUBLISH')
        if error != RESPONSE_ERROR.OK:
            print(f"Error: {error.name}. Failed at {cmd}. response {response}")
            return MQTT_ERROR.ERROR

        print(f"Published \"{message}\" to topic {MQTT_TOPIC} at {MQTT_SERVER} ")

    mqtt_disconnect()

    return MQTT_ERROR.OK


def mqtt_sub(timeout: int) -> MQTT_ERROR:

    print(f"Subscribing to MQTT data for topic: {MQTT_TOPIC} on server: {MQTT_SERVER} ")

    mqtt_disconnect()

    cmd = MQTT_CFG_CMD_HEADER + MQTT_CLIENT_ID
    send_command(cmd)
    response, error = wait_for_response('OK')
    if error != RESPONSE_ERROR.OK:
        print(f"Error: {error.name}. Failed at {cmd}")
        return MQTT_ERROR.ERROR

    cmd = MQTT_CONNECT_CMD_HEADER + MQTT_SERVER + "," + MQTT_PORT
    send_command(cmd)
    response, error = wait_for_response('+SQNSMQTTONCONNECT')
    if error != RESPONSE_ERROR.OK:
        print(f"Error: {error.name}. Failed at {cmd}")
        return MQTT_ERROR.ERROR

    response_code = response.split(",")[1]
    if response_code != "0":
        print(f"MQTT connect failed with error code: {response_code}")

    cmd = MQTT_SUBSCRIBE_CMD_HEADER + MQTT_TOPIC + "," + QOS.AT_LEAST_ONCE
    send_command(cmd)
    response, error = wait_for_response('+SQNSMQTTONSUBSCRIBE')
    if error != RESPONSE_ERROR.OK:
        print(f"Error: {error.name}. Failed at {cmd}")
        return MQTT_ERROR.ERROR

    print(f"Subscribed to {MQTT_TOPIC} at {MQTT_SERVER}. Listening for {timeout} seconds...")

    start_time = time.time()
    while True:
        if time.time() - start_time > timeout:
            print(f"{timeout} timeout expired. Disconnecting from MQTT broker")
            mqtt_disconnect()
            return MQTT_ERROR.OK

        response, error = wait_for_response('+SQNSMQTTONMESSAGE')
        if error == RESPONSE_ERROR.TIMEOUT:
            print(f"{timeout} timeout expired. Disconnecting from broker")
            mqtt_disconnect()
            return

        elif error == RESPONSE_ERROR.OK:
            cmd = MQTT_RCV_MESSAGE_CMD_HEADER + MQTT_TOPIC
            send_command(cmd)
            response, error = wait_for_response('OK')
            if error != RESPONSE_ERROR.OK:
                print(f"Error: {error.name}. Failed at {cmd}")
                return MQTT_ERROR.ERROR

            response = response.strip("OK")
            print(f"Received message: {response}")


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
            # ignore CEREG updates
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
