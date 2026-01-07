

# server.py
import socket

HOST = "172.21.2.11"
PORT = 9876

server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
server.bind((HOST, PORT))
server.listen(5)

print("SERVER LISTENING")

while True:
    conn, addr = server.accept()
    print("CLIENT CONNECTED:", addr)

    buffer = ""

    try:
        while True:
            data = conn.recv(4096)
            if not data:
                print("CLIENT CLOSED")
                break

            buffer += data.decode(errors="ignore")

            #  Process full messages only
            while "\r\n" in buffer:
                message, buffer = buffer.split("\r\n", 1)

                print(" FULL HERCULES DATA:")
                print(message)

                conn.sendall(b"ACK\r\n")

    except ConnectionResetError:
        print("CLIENT FORCEFULLY DISCONNECTED")

    finally:
        conn.close()
        print("READY FOR NEXT CLIENT\n")
