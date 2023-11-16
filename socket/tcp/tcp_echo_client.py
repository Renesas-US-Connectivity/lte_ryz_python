import argparse
from enum import IntEnum
import queue
import serial
import threading
import time
from typing import Tuple
from prompt_toolkit import PromptSession
from prompt_toolkit.patch_stdout import patch_stdout


serial_port = serial.Serial()
serial_rx_q = queue.Queue()
session = PromptSession()

# This command sets the socket configuration parameters.
SOCKET_CFG_CMD = "AT+SQNSCFG="

# This command opens a remote connection using a socket.
SOCKET_DIAL_CMD_HEADER = "AT+SQNSD="

# This command closes a socket connection
SOCKET_DISCONNECT_CMD_HEADER = "AT+SQNSH="

# A This command allows to send binary data on a connected socket while the module is in ‘command mode’.
SOCKET_SEND_COMMAND_MODE_CMD_HEADER = "AT+SQNSSENDEXT="

# This command dumps the data received on a connected socket while the module is in ‘command mode’.
SOCKET_RECEIVE_CMD = "AT+SQNSRECV="

# This command reports the current status of the sockets.
SCOKET_STATUS_CMD = "AT+SQNSS"


class SOCKET_STATE(IntEnum):
    CLOSED = 0
    ACTIVE_TXSFER_CONNECTION = 1
    SUSPENDED_NO_PENDING_DATA = 2
    SUSPENDED_PENDING_DATA = 3
    LISTENING = 4
    INCOMING_CONNECTION = 5
    IN_OPENING_PROCESS = 6


class TRANSMISSION_PROTOCOL(IntEnum):
    TCP = 0
    UDP = 1


class TCP_CLOSURE(IntEnum):
    HANG_UP_AFTER_REMOTE = 0
    HANG_UP_AFTER_ESCAPE = 255


class CONNECTION_MODE(IntEnum):
    ONLINE_MODE = 0
    COMMAND_MODE = 1


class ACCEPT_ANY_REMPOTE(IntEnum):
    DISABLED = 0
    ACCEPTS_ANY = 1
    RECEIVE_SEND_ANY = 2


class CONNECTION_SETUP(IntEnum):
    SYNCHRONOUS = 0
    ASYNCHRONOUS = 1


class CONNECTION_SETUP_RESULT(IntEnum):
    OK = 0
    NO_CARRIER = 1
    UNKNOWN = 2
    COINNECTION_REFUSED = 3
    AUTHENTICATION_REJECTED = 4


class RESPONSE_ERROR(IntEnum):
    OK = 0
    ERROR = 1
    TIMEOUT = 2


def config_socket_cmd(connection_id: int,
                      cid: int = 1,
                      packet_size: int = 0,
                      max_timeout: int = 0,
                      connection_timeout: int = 600,
                      tx_timeout: int = 50):

    return SOCKET_CFG_CMD + \
           str(connection_id) + "," + \
           str(cid) + "," + \
           str(packet_size) + "," + \
           str(max_timeout) + "," + \
           str(connection_timeout) + "," + \
           str(tx_timeout)


def dial_socket_cmd(connection_id: int,
                    tx_protocol: TRANSMISSION_PROTOCOL,
                    remote_host_port: int,
                    ip_addr: str,
                    closure: TCP_CLOSURE = TCP_CLOSURE.HANG_UP_AFTER_REMOTE,
                    udp_local_port: int = 0,
                    conn_mode: CONNECTION_MODE = CONNECTION_MODE.COMMAND_MODE,
                    accept_any_remote: ACCEPT_ANY_REMPOTE = ACCEPT_ANY_REMPOTE.DISABLED,
                    conn_setup: CONNECTION_SETUP = CONNECTION_SETUP.SYNCHRONOUS):

    return SOCKET_DIAL_CMD_HEADER + \
           str(connection_id) + "," + \
           str(tx_protocol.value) + "," + \
           str(remote_host_port) + "," + \
           "\"" + ip_addr + "\"" + "," + \
           str(closure.value) + "," + \
           str(udp_local_port) + "," + \
           str(conn_mode.value) + "," + \
           str(accept_any_remote.value) + "," + \
           str(conn_setup.value)


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

def parse_socket_state(state_resposne: bytes, connection_id: int) -> SOCKET_STATE:

    # Response of the form:
    # +SQNSS: 1,2,"100.111.25.78",64675,"xxx.xx.xxx.xx",12345,1\n
    # +SQNSS: 2,0\n
    # +SQNSS: 3,0\n
    # +SQNSS: 4,0\n
    # +SQNSS: 5,0\n
    # +SQNSS: 6,0\n

    # split for each connection id
    response_split = state_resposne.split("\n")
    # get the string for the associated connection id
    response_split = response_split[connection_id - 1]
    # split at ","" to isolate the connection status
    response_split = response_split.split(",")
    status_code = response_split[1]

    return SOCKET_STATE(int(status_code))


def run_echo_client(server_ip: str, server_port: int):

    socket_conn_id = 1

    print("Checking socket state...")
    # Check if the socket associated with connection ID 1 is open/closed
    cmd = SCOKET_STATUS_CMD
    send_command(cmd)
    response, error = wait_for_response('OK')
    if error != RESPONSE_ERROR.OK:
        print(f"Error: {error.name}. Failed at {cmd}")
        return

    # If the socket is open, close it
    print(f"Parsing socket state...")
    socket_state = parse_socket_state(response, socket_conn_id)
    if socket_state != SOCKET_STATE.CLOSED:
        # If the socket is open, close it to start fresh
        print(f"Socket with connection_id={socket_conn_id} open. Closing socket...")
        cmd = SOCKET_DISCONNECT_CMD_HEADER + str(socket_conn_id)
        send_command(cmd)
        response, error = wait_for_response('OK')

    # Configure the socket
    print("Configuring socket...")
    cmd = config_socket_cmd(socket_conn_id)
    send_command(cmd)
    response, error = wait_for_response('OK')
    if error != RESPONSE_ERROR.OK:
        print(f"Error: {error.name}. Failed at {cmd}")
        return

    # Dial the server
    print("Connecting to server...")
    cmd = dial_socket_cmd(socket_conn_id,
                          TRANSMISSION_PROTOCOL.TCP,
                          server_port,
                          server_ip)
    send_command(cmd)
    response, error = wait_for_response('OK')
    if error != RESPONSE_ERROR.OK:
        print(f"Error: {error.name}. Failed at {cmd}")
        return

    print("Connected to server")
    while True:
        try:
            with patch_stdout():
                try:
                    # Get a message from the user to send to the server
                    message = session.prompt('Enter a message to send to the server, or exit to quit: ')
                    if message is None:
                        continue
                    elif message == "exit":
                        print("Disconnecting socket...")
                        cmd = SOCKET_DISCONNECT_CMD_HEADER + str(socket_conn_id)  # TODO keep track of identifier
                        send_command(cmd)
                        response, error = wait_for_response('OK')
                        break
                except KeyboardInterrupt:
                    return

                # Send the extended send data command to inform the modem how many bytes we will send 
                print(f"Preparing to send message...")
                cmd = SOCKET_SEND_COMMAND_MODE_CMD_HEADER + str(socket_conn_id) + "," + str(len(message))
                send_command(cmd)
                response, error = wait_for_response(">")
                if error != RESPONSE_ERROR.OK:
                    print(f"Error: {error.name}. Failed at {cmd}")
                    return

                # Send the message
                print(f"Sending to server: {message}")
                send_command(message, False)
                response, error = wait_for_response("+SQNSRING") # When +SQNSRING received a response is available
                if error != RESPONSE_ERROR.OK:
                    print(f"Error: {error.name}. Failed at {cmd}")
                    return

                print("Response available...")
                # Receive the data
                cmd = SOCKET_RECEIVE_CMD + str(socket_conn_id) + "," + str(len(message))
                send_command(cmd)

                # Expect response:
                # +SQNSRECV: 1,xx
                # <Message from server>
                # OK
                # Use wait_for_response twice to separate "+SQNSRECV:1,xx" from actual message.
                response, error = wait_for_response("+SQNSRECV")
                if error != RESPONSE_ERROR.OK:
                    print(f"Error: {error.name}. Failed at {cmd}")
                    return
                response, error = wait_for_response("OK")

                response = response[:-2]  # Remove trailing "OK"
                print(f"Received from server: {response}")


        except KeyboardInterrupt:
            return


def main(com_port: str, flow_cntrl: bool, server_ip: str, server_port: int):

    global serial_port
    serial_port = open_serial_port(com_port, flow_cntrl)

    lte_rx_task = threading.Thread(target=get_lte_response)
    lte_rx_task.daemon = True
    lte_rx_task.start()

    echo_client_task = threading.Thread(target=run_echo_client, args=[server_ip, server_port])
    echo_client_task.daemon = True
    echo_client_task.start()

    while True:
        # If one of the tasks exits, exit the application
        if lte_rx_task.is_alive() and echo_client_task.is_alive():
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
            response_buffer = serial_rx_q.get(timeout=10)
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

        response += response_buffer + '\n' # add a newline character to make parsing easier


if __name__ == "__main__":
    parser = argparse.ArgumentParser(prog='LTE CLI',
                                     description='')

    parser.add_argument("com_port", type=str, help='COM port for your development kit')
    parser.add_argument("--flow_cntrl", action="store_true", help='Enable serial flow control')
    parser.add_argument("server_ip", type=str, help='COM port for your development kit')
    parser.add_argument("server_port", type=str, help='COM port for your development kit')
    args = parser.parse_args()

    try:
        main(args.com_port, args.flow_cntrl, args.server_ip, args.server_port)
    except KeyboardInterrupt:
        pass

    print("Exiting...")
