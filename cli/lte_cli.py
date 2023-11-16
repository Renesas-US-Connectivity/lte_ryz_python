import argparse
import serial
import threading
import time
from prompt_toolkit import PromptSession
from prompt_toolkit.patch_stdout import patch_stdout


def open_serial_port(com_port: str, flow_cntrl: bool) -> serial.Serial:
    ser = serial.Serial()
    ser.port = com_port
    ser.baudrate = 115200
    ser.rtscts = flow_cntrl
    ser.timeout = 1
    ser.open()
    return ser


def get_lte_response(ser: serial.Serial):
    while True:
        received = ser.readline()
        # uncomment below to see raw data received
        # print(f"\t<-- Rx: {received}")
        received = received.strip(b'\r\n')
        if not received:
            continue
        print(f"\t<-- Rx: {received.decode()}")


def get_user_input(ser: serial.Serial):
    session = PromptSession()
    while True:
        with patch_stdout():
            try:
                input_str: str = session.prompt('>>> ')
                if input_str:
                    print(f"\t--> Tx: {input_str}")
                    if input_str != "+++":
                        input_str += "\r"
                    # uncomment below to see raw data transmitted
                    # print(f"\t--> Tx:{input_str.encode()}")
                    ser.write(input_str.encode())
            except KeyboardInterrupt:
                pass
                return


def main(com_port: str, flow_cntrl: bool):

    ser = open_serial_port(com_port, flow_cntrl)

    cli_task = threading.Thread(target=get_user_input, args=[ser])
    cli_task.daemon = True
    cli_task.start()

    lte_task = threading.Thread(target=get_lte_response, args=[ser])
    lte_task.daemon = True
    lte_task.start()

    while True:
        # If one of the tasks exits, exit the application
        if cli_task.is_alive() and lte_task.is_alive():
            time.sleep(1)
        else:
            return


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
