from PySide6.QtCore import QThread,Signal
import socket



class FHVSocketThread(QThread):
    data_received = Signal(str)

    def __init__(self, host="172.21.2.11", port=9876):
        super().__init__()
        self.host = host
        self.port = port
        self.running = True
        self.waiting_for_user = False
        self.server = None
        self.conn = None

    def run(self):
        self._create_server()

        while self.running:
            try:
                print(" Waiting for camera connection...")
                self.conn, addr = self.server.accept()
                print(" Camera connected:", addr)

                self._configure_conn(self.conn)
                self._handle_client(self.conn)

            except Exception as e:
                print(" Accept error:", e)
                self._close_conn()
                self.msleep(1000)

    # ---------------- INTERNAL ----------------

    def _create_server(self):
        self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server.bind((self.host, self.port))
        self.server.listen(1)
        print(" Socket server ready")

    def _configure_conn(self, conn):
        conn.settimeout(2.0)
        conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        conn.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)

    def _handle_client(self, conn):
        while self.running:
            try:
                if self.waiting_for_user:
                    self.msleep(20)
                    continue

                # Poll camera
                conn.sendall(b"M\r\n")

                data = conn.recv(4096)
                if not data:
                    raise ConnectionResetError("Camera disconnected")

                msg = data.decode("ascii", errors="ignore").strip()
                msg = msg.replace("\x00", "")

                if msg in ("ER", "OK", "0"):
                    continue
                print(msg)

                if len(msg) == 23 or len(msg)==22 and msg.isalnum():
                    print(" VALID DATA:", msg)
                    self.waiting_for_user = True
                    self.data_received.emit(msg)

            except socket.timeout:
                continue

            except Exception as e:
                print(" Connection lost:", e)
                self._close_conn()
                break

    def _close_conn(self):
        try:
            if self.conn:
                self.conn.close()
        except:
            pass
        self.conn = None

    # ---------------- CONTROL ----------------

    def pause(self):
        print(" Socket paused")
        self.waiting_for_user = True

    def resume(self):
        print(" Socket resumed")
        self.waiting_for_user = False

    def stop(self):
        print(" Socket stopped")
        self.running = False
        self._close_conn()
        try:
            self.server.close()
        except:
            pass
