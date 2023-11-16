import argparse
import socket


def main(server_ip: str, server_port: int):

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

    server.bind((server_ip, server_port))
    server.settimeout(30)
    server.listen(0)
    print(f"Listening on {server_ip}:{server_port}")

    client_socket, client_address = server.accept()
    client_socket.settimeout(30)
    print(f"Accepted connection from {client_address[0]}:{client_address[1]}")

    while True:
        request = client_socket.recv(1024)
        if not request:
            break

        request = request.decode()
        print(f"Received: {request}")
        print(f"Sending: {request.upper()}")
        client_socket.send(request.upper().encode())

    client_socket.close()
    server.close()
    print("Connection to client closed")
    print("Exiting...")


if __name__ == "__main__":

    parser = argparse.ArgumentParser(prog='LTE CLI',
                                     description='')

    parser.add_argument("server_ip", type=str, help='COM port for your development kit')
    parser.add_argument("server_port", type=int, help='COM port for your development kit')
    args = parser.parse_args()

    try:
        main(args.server_ip, args.server_port)
    except KeyboardInterrupt:
        pass
