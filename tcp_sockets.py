import socket
import time

HOST = "172.21.2.11"
PORT = 9876

server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
server.bind((HOST, PORT))
server.listen(1)

print("FHV SERVER LISTENING")

conn, addr = server.accept()
print("FHV CONNECTED:", addr)

waiting_for_user = False
last_data = None

while True:
    try:

        conn.sendall(b"M\r\n")
        print("MEASURE COMMAND SENT")

        #  Receive data
        data = conn.recv(4096)
        if not data:
            continue

        msg = data.decode("ascii", errors="ignore").strip()
        print("RAW:", msg)

        # Ignore protocol chatter
        if msg in ("ER", "OK"):
            continue

        #  Accept ONLY 23-digit data

        print(" DATA RECEIVED:", msg)

        last_data = msg
        waiting_for_user = True   # 🔒 PAUSE SOCKET

        print("⏸ Waiting for user input...")



        time.sleep(0.2)

    except Exception as e:
        print("Socket error:", e)
        break
