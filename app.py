import glob
import os
import socket
import sys
import tempfile
from datetime import datetime, time

import cv2
import psycopg2
from openpyxl import Workbook
from openpyxl.drawing.image import Image as XLImage
from openpyxl.styles import PatternFill
from PySide6.QtCore import QDate, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QColor, QImage, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDateEdit,
    QDialog,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

IMAGE_DIR = r"C:\Users\Admin\Documents\dist\images"


# ===================Helper Function============
def clean_text(s):
    if s is None:
        return ""
    return s.replace("\x00", "").strip()


# ================= DB CONFIG =================


DB = dict(
    dbname="camera_inspection",
    user="postgres",
    password="1234",
    host="localhost",
    port=5432,
)
TABLE = "camera_inspection"
last_data = None


# ================= SOCKET THREAD (ADDED) =================
class FHVSocketThread(QThread):
    data_received = Signal(str)
    invalid_detected = Signal()

    def __init__(self, host="172.21.2.11", port=9876):
        super().__init__()
        self.blocked = False

        self.host = host
        self.last_invalid_ts = 0
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
            if self.blocked:
                self.msleep(50)
                continue

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
                print(len(msg))
                # STRICT FORMAT CHECK
                if len(msg) == 7:
                    print(" VALID DATA:", msg)
                    self.waiting_for_user = True
                    self.data_received.emit(msg)

                else:
                    #  Length < 22 or wrong start → Gear not in position

                    if self.waiting_for_user or self.blocked:
                        continue

                    now = time.time()
                    if now - self.last_invalid_ts > 2:  # debounce 2 sec
                        self.last_invalid_ts = now
                        self.invalid_detected.emit()

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
        self.blocked = True

    def resume(self):
        print(" Socket resumed")
        self.waiting_for_user = False
        self.blocked = False

    def stop(self):
        print(" Socket stopped")
        self.running = False
        self._close_conn()
        try:
            self.server.close()
        except:
            pass


# ================= DB INIT =================
def batch_serial_exists(batch, serial):
    conn = psycopg2.connect(**DB)
    cur = conn.cursor()
    cur.execute(
        f"""
        SELECT 1
        FROM {TABLE}
        WHERE unique_no = %s AND serial_no = %s
        LIMIT 1
        """,
        (batch, serial),
    )
    exists = cur.fetchone() is not None
    cur.close()
    conn.close()
    return exists


def init_db():
    conn = psycopg2.connect(**DB)
    cur = conn.cursor()
    cur.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {TABLE} (
            id SERIAL PRIMARY KEY,
            employee_id TEXT,
            work_order TEXT,
            charge_no TEXT,
            serial_no TEXT,
            part_no TEXT,
            unique_no TEXT,
            status TEXT,
            time TIMESTAMP,
            image BYTEA,
            front_image BYTEA,
            back_image BYTEA
        )
    """
    )
    conn.commit()
    cur.close()
    conn.close()


# ================= DB SAVE =================
def save_record(data, status, img_bytes, front_img, back_img):
    conn = psycopg2.connect(**DB)
    cur = conn.cursor()
    cur.execute(
        f"""
        INSERT INTO {TABLE}
        (employee_id, work_order, charge_no, serial_no,
         part_no, unique_no, status, time, image, front_image, back_image)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
    """,
        (
            data["emp"],
            data["wo"],
            data["charge"],
            data["serial"],
            data["part"],
            data["unique"],
            status,
            datetime.now(),
            psycopg2.Binary(img_bytes),
            psycopg2.Binary(front_img),
            psycopg2.Binary(back_img),
        ),
    )
    conn.commit()
    cur.close()
    conn.close()


# ================= DB FETCH =================
def fetch_report(from_dt, to_dt, status, unique_no=None, limit=None, offset=None):
    conn = psycopg2.connect(**DB)
    cur = conn.cursor()

    q = f"""
        SELECT employee_id, work_order, charge_no,
               serial_no, part_no, unique_no,
               image,front_image, back_image, status, time
        FROM {TABLE}
        WHERE time BETWEEN %s AND %s
    """
    params = [from_dt, to_dt]

    if status != "ALL":
        q += " AND status=%s"
        params.append(status)

    if unique_no:
        q += " AND unique_no ILIKE %s"
        params.append(f"%{unique_no}%")

    q += " ORDER BY time DESC"

    if limit is not None:
        q += " LIMIT %s OFFSET %s"
        params.extend([limit, offset])

    cur.execute(q, params)
    rows = cur.fetchall()

    # total count
    count_q = f"""
        SELECT COUNT(*)
        FROM {TABLE}
        WHERE time BETWEEN %s AND %s
    """
    count_params = [from_dt, to_dt]

    if status != "ALL":
        count_q += " AND status=%s"
        count_params.append(status)

    if unique_no:
        count_q += " AND unique_no ILIKE %s"
        count_params.append(f"%{unique_no}%")

    cur.execute(count_q, count_params)
    total = cur.fetchone()[0]

    cur.close()
    conn.close()
    return rows, total


def get_home_counts():
    conn = psycopg2.connect(**DB)
    cur = conn.cursor()

    # Total counts
    cur.execute(
        f"""
        SELECT
            COUNT(*) AS total,
            COUNT(*) FILTER (WHERE status='OK') AS ok_count,
            COUNT(*) FILTER (WHERE status='NOT_OK') AS not_ok_count
        FROM {TABLE}
    """
    )
    total, ok_cnt, not_ok_cnt = cur.fetchone()

    # Today count
    today_start = datetime.combine(datetime.today().date(), time.min)
    today_end = datetime.combine(datetime.today().date(), time.max)

    cur.execute(
        f"""
        SELECT COUNT(*)
        FROM {TABLE}
        WHERE time BETWEEN %s AND %s
    """,
        (today_start, today_end),
    )
    today_cnt = cur.fetchone()[0]

    cur.close()
    conn.close()

    return (total or 0, ok_cnt or 0, not_ok_cnt or 0, today_cnt or 0)


class TextToast(QWidget):
    def __init__(self, text, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)

        label = QLabel(text)
        label.setStyleSheet(
            """
            QLabel {
                background:#b71c1c;
                color:white;
                padding:12px 22px;
                border-radius:10px;
                font-size:14px;
                font-weight:bold;
            }
        """
        )

        layout = QVBoxLayout(self)
        layout.addWidget(label)
        self.adjustSize()

        QTimer.singleShot(2500, self.close)

    def show_bottom(self):
        screen = QApplication.primaryScreen().availableGeometry()
        self.move(
            screen.center().x() - self.width() // 2,
            screen.bottom() - self.height() - 40,
        )
        self.show()


class ImageToast(QWidget):
    def __init__(self, pixmap, parent=None):
        super().__init__(parent)

        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)

        frame = QLabel(self)
        frame.setStyleSheet(
            """
            QLabel {
                background: #222;
                border-radius: 10px;
                padding: 8px;
            }
        """
        )

        frame.setPixmap(pixmap.scaled(220, 140, Qt.KeepAspectRatio))
        frame.setAlignment(Qt.AlignCenter)

        lay = QVBoxLayout(self)
        lay.addWidget(frame)

        self.adjustSize()

        # Auto close
        QTimer.singleShot(2500, self.close)

    def show_at_bottom_right(self):
        screen = QApplication.primaryScreen().availableGeometry()
        self.move(
            screen.right() - self.width() - 20, screen.bottom() - self.height() - 20
        )
        self.show()


# ================= HOME =================
class Home(QWidget):
    def __init__(self):
        super().__init__()

        self.setStyleSheet(
            """
        QWidget {
            background: #f4f6f9;
            font-family: Segoe UI;
        }
        QLabel {
            color: #333;
        }
        """
        )

        self.main = QVBoxLayout(self)
        self.main.setContentsMargins(30, 30, 30, 30)
        self.main.setSpacing(20)

        title = QLabel("Home")
        title.setStyleSheet("font-size:22px;font-weight:bold;")
        self.main.addWidget(title)

        # ---- Cards ----
        self.cards = QHBoxLayout()
        self.cards.setSpacing(20)
        self.main.addLayout(self.cards)

        self.total_lbl = self._card("TOTAL INSPECTIONS", "#1e88e5")
        self.ok_lbl = self._card("OK COUNT", "#2e7d32")
        self.nok_lbl = self._card("NOT OK COUNT", "#c62828")
        self.today_lbl = self._card("TODAY INSPECTIONS", "#6a1b9a")

        self.main.addStretch()

        self.refresh()  # initial load

    def _card(self, title, color):
        w = QWidget()
        w.setStyleSheet("background:white;border-radius:8px;")
        v = QVBoxLayout(w)
        v.setContentsMargins(20, 20, 20, 20)

        t = QLabel(title)
        t.setStyleSheet("color:#777;font-size:13px;")

        val = QLabel("0")
        val.setStyleSheet(f"font-size:22px;font-weight:bold;color:{color};")

        v.addWidget(t)
        v.addWidget(val)

        self.cards.addWidget(w)
        return val

    def refresh(self):
        total, ok_cnt, not_ok_cnt, today_cnt = get_home_counts()
        self.total_lbl.setText(str(total))
        self.ok_lbl.setText(str(ok_cnt))
        self.nok_lbl.setText(str(not_ok_cnt))
        self.today_lbl.setText(str(today_cnt))

    def showEvent(self, event):
        super().showEvent(event)


# ================= OPERATOR =================
class Operator(QWidget):
    record_saved = Signal()
    EMP_LEN = 10
    WO_LEN = 10

    def retry_scan(self):
        print("Retry scan clicked")

        # clear only input fields (not employee / WO)
        for _, le, _ in self.inputs.values():
            le.clear()
            le.setStyleSheet(
                "background:transparent;color:white;border:1px solid #555;"
            )

        self.duplicate_detected = False
        self.camera_paused = False

        # ▶ resume socket ONLY
        if self.socket_thread:
            self.socket_thread.resume()

        TextToast("Waiting for gear in position", self).show_bottom()
        self.reset_batch_serial_style()

    def __init__(self):
        super().__init__()
        self.camera_paused = False
        self.inspection_active = False
        self.duplicate_detected = False

        # ---- Dark UI, clean inputs ----
        self.setStyleSheet(
            """
        QWidget { background:#121212; }
        QLabel { color:#ddd; background:transparent; }
        QLineEdit {
            background:transparent;
            color:black;
            border:1px solid #555;
            padding:6px;
            font-size:13px;
        }
        """
        )

        self.cap = None
        self.frame = None
        self.socket_thread = None

        # ---- Top bar with refresh ----
        self.btn_refresh = QPushButton("🔄 New User")
        self.btn_refresh.setStyleSheet(
            "background:#6c757d;color:white;font-weight:bold;padding:6px 16px;"
        )
        self.btn_refresh.clicked.connect(self.reset_all)

        self.btn_retry = QPushButton("▶ Retry Scan")
        self.btn_retry.setStyleSheet(
            "background:#0277bd;color:white;font-weight:bold;padding:6px 16px;"
        )
        self.btn_retry.clicked.connect(self.retry_scan)

        top = QHBoxLayout()
        top.addStretch()
        top.addWidget(self.btn_retry)  # 👈 new button
        top.addWidget(self.btn_refresh)

        # ---- Employee & Work Order ----

        self.emp = QLineEdit(placeholderText="Employee ID")
        self.wo = QLineEdit(placeholderText="Work Order")

        normal = """
        QLineEdit {
            background:white;
            color:black;
            border:1px solid #999;
        }
        """
        self.emp.setStyleSheet(normal)
        self.wo.setStyleSheet(normal)

        self.emp.returnPressed.connect(self.emp_done)
        self.wo.returnPressed.connect(self.wo_done)
        self.emp.show()
        self.wo.hide()
        self.emp.setFocus()

        # ---- 4 fields ----
        self.fields = {
            "charge": ("Charge no", 14),
            "unique": ("Batch no", 4),
            "Vendor Code": ("Vendor code", 8),
            "serial": ("Part no", 3),
        }

        self.inputs = {}
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(4)

        col = 0
        for key, (label, ln) in self.fields.items():
            lbl = QLabel(label)
            lbl.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
            lbl.setStyleSheet("font-size:20px;color:black;")

            le = QLineEdit()

            le.setFixedWidth(160)
            le.setMaxLength(ln)
            le.setReadOnly(False)
            le.setPlaceholderText(f"{ln} digits")
            le.textChanged.connect(lambda _, k=key: self.validate_field(k))

            lbl.hide()
            le.hide()

            grid.addWidget(lbl, 0, col)
            grid.addWidget(le, 1, col)
            self.inputs[key] = (lbl, le, ln)
            col += 1

        # ---- Camera ----
        self.preview = QLabel("Camera OFF")
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setMinimumHeight(420)
        self.preview.setStyleSheet("background:black;color:white;")

        self.preview_dialog = None

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_frame)

        # ---- MAIN LAYOUT ----
        lay = QVBoxLayout(self)
        lay.addLayout(top)
        lay.addWidget(self.emp)
        lay.addWidget(self.wo)
        lay.addLayout(grid)
        lay.addWidget(self.preview)

    def mark_all_green(self):
        for _, le, _ in self.inputs.values():
            le.setStyleSheet("background:#1b5e20;color:white;border:2px solid #2ecc71;")

    def mark_all_red(self):
        for _, le, _ in self.inputs.values():
            le.setStyleSheet("background:#7f0000;color:white;border:2px solid #ff4d4d;")

    def try_capture(self):
        print("ENTER PRESSED")

        if self.frame is None:
            print(" Camera frame not ready")
            return

        if not self.all_fields_valid():
            print(" Fields invalid")
            return

        print(" CAPTURE TRIGGERED")
        self.capture()

    def show_ok_notok_dialog(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("Inspection Result")
        dlg.setFixedSize(420, 420)  # medium dialog

        # -------- Image --------
        img_label = QLabel()
        img_label.setAlignment(Qt.AlignCenter)

        if self.captured_img:
            pix = QPixmap()
            pix.loadFromData(self.captured_img)
            img_label.setPixmap(
                pix.scaled(320, 240, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            )

        # -------- Buttons --------
        btn_ok = QPushButton("OK")
        btn_ng = QPushButton("NOT OK")

        btn_ok.setStyleSheet(
            "background:#2e7d32;color:white;font-size:14px;padding:8px;"
        )
        btn_ng.setStyleSheet(
            "background:#c62828;color:white;font-size:14px;padding:8px;"
        )

        btn_ok.clicked.connect(lambda: self.final_save("OK", dlg))
        btn_ng.clicked.connect(lambda: self.final_save("NOT_OK", dlg))

        # -------- Layout --------
        btn_layout = QHBoxLayout()
        btn_layout.addWidget(btn_ok)
        btn_layout.addWidget(btn_ng)

        layout = QVBoxLayout(dlg)
        layout.addWidget(img_label)
        layout.addLayout(btn_layout)

        dlg.exec()

    def highlight_batch_serial_red(self):
        self.inputs["unique"][1].setStyleSheet(
            "background:#7f0000;color:white;border:2px solid #ff4d4d;"
        )
        self.inputs["serial"][1].setStyleSheet(
            "background:#7f0000;color:white;border:2px solid #ff4d4d;"
        )

    def reset_batch_serial_style(self):

        self.inputs["unique"][1].setStyleSheet(
            "background:white;color:black;border:1px solid #999;"
        )
        self.inputs["serial"][1].setStyleSheet(
            "background:white;color:black;border:1px solid #999;"
        )

    def final_save(self, status, dlg):
        dlg.close()

        data = {
            "emp": clean_text(self.emp.text()),
            "wo": clean_text(self.wo.text()),
            "charge": clean_text(self.inputs["charge"][1].text()),
            "serial": clean_text(self.inputs["serial"][1].text()),
            "part": clean_text(self.inputs["Vendor Code"][1].text()),
            "unique": clean_text(self.inputs["unique"][1].text()),
        }

        save_record(data, status, self.captured_img, self.front_img, self.back_img)

        TextToast(f"{status} saved | Batch {data['unique']}", self).show_bottom()

        #  CLEAR ALL INPUT FIELDS FOR NEXT GEAR
        for _, le, _ in self.inputs.values():
            le.clear()
            le.setStyleSheet(
                "background:transparent;color:white;border:1px solid #555;"
            )

        self.reset_batch_serial_style()

        #  RESET IMAGE
        self.captured_img = None

        #  READY FOR NEXT GEAR (resume socket)
        if self.socket_thread:
            self.socket_thread.resume()

        self.duplicate_detected = False

        self.record_saved.emit()

    def on_enter_key(self):
        if self.duplicate_detected:
            TextToast(
                "Duplicate batch not allowed. Scan other gear", self
            ).show_bottom()
            return

        if not self.all_fields_valid():
            TextToast("Invalid input", self).show_bottom()
            return

        # ---- 1. CAPTURE CAMERA IMAGE ----
        frame = self.grab_latest_frame()
        if frame is None:
            TextToast("Camera not ready", self).show_bottom()
            return

        _, buf = cv2.imencode(".jpg", frame)
        self.captured_img = buf.tobytes()

        # ---- 2. CHECK FOLDER FOR MPI IMAGES ----
        batch = self.inputs["unique"][1].text()
        serial = self.inputs["serial"][1].text()

        # store pending batch/serial
        self.pending_batch = batch
        self.pending_serial = serial

        # start folder polling
        self.folder_timer = QTimer(self)
        self.folder_timer.timeout.connect(self.retry_folder_check)
        self.folder_timer.start(1000)  # check every 1 second

        TextToast("Waiting for MPI images", self).show_bottom()

    def retry_folder_check(self):
        print("DEBUG: retry_folder_check running")

        front_files = glob.glob(
            os.path.join(IMAGE_DIR, f"*{self.pending_batch}*{self.pending_serial}*01*")
        )
        back_files = glob.glob(
            os.path.join(IMAGE_DIR, f"*{self.pending_batch}*{self.pending_serial}*02*")
        )

        if not front_files or not back_files:
            return

        # stop timer
        self.folder_timer.stop()

        # load images
        with open(front_files[0], "rb") as f:
            self.front_img = f.read()

        with open(back_files[0], "rb") as f:
            self.back_img = f.read()

        print("DEBUG: MPI images found")

        self.show_ok_notok_dialog()

    def check_folder_and_decide(self, batch, serial):
        # EXPECTED FILE NAMES:
        # 1100100-01.bmp
        # 1100100-02.bmp

        front_path = os.path.join(IMAGE_DIR, f"{batch}{serial}-01.jpg")
        back_path = os.path.join(IMAGE_DIR, f"{batch}{serial}-02.jpg")

        print("DEBUG: checking", front_path, back_path)

        if not os.path.exists(front_path) or not os.path.exists(back_path):
            TextToast("Waiting for MPI images (01 / 02)", self).show_bottom()
            return

        # LOAD MPI IMAGES
        with open(front_path, "rb") as f:
            self.front_img = f.read()

        with open(back_path, "rb") as f:
            self.back_img = f.read()

        print("DEBUG: MPI images found")

        # ASK OK / NOT OK
        self.show_ok_notok_dialog()

    def grab_latest_frame(self):
        if not self.cap or not self.cap.isOpened():
            return None

        # grab 2 frames to flush camera buffer
        self.cap.grab()
        ret, frame = self.cap.read()
        if not ret:
            return None
        return frame

    def on_socket_data(self, msg):
        msg = msg.strip()
        print("Socket accepted:", repr(msg), "LEN:", len(msg))

        # ---------- BASIC VALIDATION ----------
        if not msg or msg in ("ER", "OK", "0"):
            TextToast("Batch number is missing", self).show_bottom()
            return

        if len(msg) != 7:
            TextToast("Gear In Position", self).show_bottom()
            return

        # ---------- PARSE ----------
        charge = "A7152693506002"
        batch_code = msg[:4]
        part_no = msg[4:7]
        vendor_code = "16099680"

        if not batch_code.strip():
            TextToast("Batch number is missing", self).show_bottom()
            return

        # ---------- SHOW INPUTS ONLY AFTER WO ----------
        if self.wo.isHidden():  # WO already entered
            self.wo_done()
        else:
            # WO not entered yet → do nothing
            print("Waiting for Work Order entry")
            return

        # ---------- FILL INPUTS (FOR BOTH CASES) ----------
        self.inputs["charge"][1].setText(charge)
        self.inputs["serial"][1].setText(part_no)
        self.inputs["unique"][1].setText(batch_code)
        self.inputs["Vendor Code"][1].setText(vendor_code)

        self.inputs["unique"][1].setFocus()

        if batch_serial_exists(batch_code, part_no):
            self.duplicate_detected = True

            self.highlight_batch_serial_red()

            TextToast(
                f"Duplicate detected : Batch {batch_code} / Serial {part_no}", self
            ).show_bottom()

            if self.socket_thread:
                self.socket_thread.pause()
            return

        # ---------- NORMAL FLOW ----------
        self.duplicate_detected = False
        self.mark_all_green()

    def bind_enter_keys(self):
        for _, le, _ in self.inputs.values():
            le.returnPressed.connect(self.on_enter_key, Qt.UniqueConnection)

    def clear_and_resume(self):
        for _, le, _ in self.inputs.values():
            le.clear()
            le.setStyleSheet(
                "background:transparent;color:white;border:1px solid #555;"
            )

        print(" Camera resumed")
        self.camera_paused = False

        if self.socket_thread:
            self.socket_thread.resume()

    def reset_input_colors(self):
        for _, le, _ in self.inputs.values():
            le.setStyleSheet(
                "background:transparent;color:white;border:1px solid #555;"
            )

    # ---------- FLOW ----------
    def emp_done(self):
        if self.emp.text():
            self.emp.hide()
            self.wo.show()
            self.wo.setFocus()

    def on_invalid_gear(self):
        # Show only after work order entered
        if self.wo.isHidden():
            TextToast("Gear not detected or number not in position", self).show_bottom()

    def on_enter(self):
        print("Operator screen entered")

        if self.socket_thread is None:
            self.socket_thread = FHVSocketThread()
            self.socket_thread.data_received.connect(self.on_socket_data)
            self.socket_thread.invalid_detected.connect(self.on_invalid_gear)

            self.socket_thread.start()
        else:
            self.socket_thread.resume()

    def wo_done(self):

        self.wo.hide()

        for lbl, le, _ in self.inputs.values():
            lbl.show()
            le.show()

        self.bind_enter_keys()
        self.start_camera()

        # focus batch field
        self.inputs["unique"][1].setFocus()

    def validate_field(self, key):
        _, le, ln = self.inputs[key]

        if not le.text():
            le.setStyleSheet(
                "background:transparent;color:white;border:1px solid #555;"
            )
            return

        # length check
        if len(le.text()) != ln:
            le.setStyleSheet("background:#7f0000;color:white;border:1px solid #e74c3c;")
            return

        #  UNIQUE (BATCH) DUPLICATE CHECK
        batch = self.inputs["unique"][1].text()
        serial = self.inputs["serial"][1].text()

        if len(batch) == 4 and len(serial) == 3:
            if batch_serial_exists(batch, serial):
                self.duplicate_detected = True
                self.highlight_batch_serial_red()

                TextToast(
                    f"Duplicate Batch {batch} + Serial {serial}", self
                ).show_bottom()
                return
            else:
                self.duplicate_detected = False

        #  VALID FIELD

        le.setStyleSheet("background:#1b5e20;color:black;border:1px solid #2ecc71;")

    # ---------- CAMERA ----------
    def start_camera(self):
        self.camera_paused = False

        if self.cap is None:
            self.cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
            if not self.cap.isOpened():
                self.preview.setText("Camera not available")
                return
        self.timer.start(20)

    def stop_camera(self):
        self.timer.stop()
        if self.cap:
            self.cap.release()
            self.cap = None
        self.preview.setText("Camera OFF")

    def update_frame(self):
        if not self.cap or self.camera_paused:
            return  #  camera frozen

        ret, frame = self.cap.read()
        if not ret:
            return

        self.frame = frame
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb.shape
        self.preview.setPixmap(
            QPixmap.fromImage(QImage(rgb.data, w, h, ch * w, QImage.Format_RGB888))
        )

    # ---------- RESET ----------
    def reset_all(self):
        self.stop_camera()

        self.emp.clear()
        self.wo.clear()

        self.emp.show()
        self.wo.hide()
        self.socket_waiting = False

        for lbl, le, _ in self.inputs.values():
            lbl.hide()
            le.hide()
            le.clear()
            le.setStyleSheet(
                "background:transparent;\
                    color:white;\
                        border:1px solid #555;"
            )

        self.emp.setFocus()

    def all_fields_valid(self):
        for _, le, ln in self.inputs.values():
            if len(le.text()) != ln:
                return False
        return True

    def on_leave(self):
        print("Leaving Operator screen")

        if self.socket_thread:
            self.socket_thread.pause()


# ================= REPORT =================
class Report(QWidget):
    def __init__(self):
        super().__init__()
        main = QVBoxLayout(self)

        # ---------- HEADER ----------
        header = QHBoxLayout()
        left = QHBoxLayout()

        self.from_dt = QDateEdit(calendarPopup=True)
        self.from_dt.setDate(QDate.currentDate().addDays(-7))

        self.to_dt = QDateEdit(calendarPopup=True)
        self.to_dt.setDate(QDate.currentDate())

        self.status = QComboBox()
        self.status.addItems(["ALL", "OK", "NOT_OK"])

        #  debounce timer
        self.search_timer = QTimer(self)
        self.search_timer.setSingleShot(True)
        self.search_timer.timeout.connect(self.reset_and_load)

        left.addWidget(QLabel("From"))
        left.addWidget(self.from_dt)
        left.addWidget(QLabel("To"))
        left.addWidget(self.to_dt)
        left.addWidget(QLabel("Status"))
        left.addWidget(self.status)
        left.addWidget(QLabel("Unique No"))
        self.search_unique = QLineEdit()
        left.addWidget(self.search_unique)

        right = QHBoxLayout()
        self.btn_excel = QPushButton("Export Excel")
        self.btn_excel.setStyleSheet(
            "background:#28a745;color:white;font-weight:bold;padding:6px 18px;"
        )
        right.addStretch()
        right.addWidget(self.btn_excel)

        header.addLayout(left)
        header.addStretch()
        header.addLayout(right)
        main.addLayout(header)

        # ---------- PAGINATION ----------
        pager = QHBoxLayout()
        self.btn_prev = QPushButton("⬅ Previous")
        self.btn_next = QPushButton("Next ➡")
        self.page_lbl = QLabel("Page 1")

        pager.addStretch()
        pager.addWidget(self.btn_prev)
        pager.addWidget(self.page_lbl)
        pager.addWidget(self.btn_next)
        pager.addStretch()

        main.addLayout(pager)

        self.page_size = 10
        self.current_page = 1
        self.total_rows = 0

        # ---------- TABLE ----------
        self.table = QTableWidget(0, 12)
        self.table.setHorizontalHeaderLabels(
            [
                "Employee ID",
                "Work Order",
                "Charge No",
                "Serial No",
                "Vendor Code",
                "Unique No",
                "Image",
                "Front Image",
                "Back Image",
                "Status",
                "Date",
                "Time",
            ]
        )

        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)

        from PySide6.QtWidgets import QAbstractItemView

        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)

        main.addWidget(self.table)

        # ---------- SIGNALS ----------
        self.from_dt.dateChanged.connect(self.on_filter_changed)
        self.to_dt.dateChanged.connect(self.on_filter_changed)
        self.status.currentIndexChanged.connect(self.on_filter_changed)

        self.search_unique.textChanged.connect(self.on_search_text_changed)

        self.btn_prev.clicked.connect(self.prev_page)
        self.btn_next.clicked.connect(self.next_page)
        self.btn_excel.clicked.connect(self.export_excel)

        self.load()

    def on_search_text_changed(self, text):
        # restart debounce timer on each key press
        self.search_timer.start(400)  # milliseconds

    def on_filter_changed(self, *args):
        # debounce all filters
        self.search_timer.start(400)

    # ---------- LOAD ----------
    def load(self):
        self.table.setRowCount(0)

        f = datetime.combine(self.from_dt.date().toPython(), time.min)
        t = datetime.combine(self.to_dt.date().toPython(), time.max)
        unique_text = self.search_unique.text().strip()
        offset = (self.current_page - 1) * self.page_size

        rows, self.total_rows = fetch_report(
            f, t, self.status.currentText(), unique_text, self.page_size, offset
        )

        for r in rows:
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setRowHeight(row, 150)

            # ---- TEXT COLUMNS ----
            for c in range(6):
                self.table.setItem(row, c, QTableWidgetItem(str(r[c])))

            # ---- STATUS ----
            status_item = QTableWidgetItem(r[9])
            status_item.setTextAlignment(Qt.AlignCenter)
            status_item.setForeground(
                QColor("green") if r[9] == "OK" else QColor("red")
            )
            self.table.setItem(row, 9, status_item)

            # ---- DATE & TIME ----
            if r[10]:
                self.table.setItem(
                    row, 10, QTableWidgetItem(r[10].strftime("%Y-%m-%d"))
                )
                self.table.setItem(
                    row, 11, QTableWidgetItem(r[10].strftime("%H:%M:%S"))
                )

            # ---- IMAGES ----
            self._set_image(row, 6, r[6])  # main image
            self._set_image(row, 7, r[7])  # front image
            self._set_image(row, 8, r[8])  # back image

            total_pages = max(
                1, (self.total_rows + self.page_size - 1) // self.page_size
            )
            self.page_lbl.setText(f"Page {self.current_page} / {total_pages}")

            self.btn_prev.setEnabled(self.current_page > 1)
            self.btn_next.setEnabled(self.current_page < total_pages)

    def reset_and_load(self):
        self.current_page = 1
        self.load()

    def next_page(self):
        self.current_page += 1
        self.load()

    def prev_page(self):
        if self.current_page > 1:
            self.current_page -= 1
            self.load()

    def show_image_dialog_pixmap(self, pix):
        dlg = QDialog(self)
        dlg.setWindowTitle("Image View")
        dlg.resize(700, 700)

        lbl = QLabel(alignment=Qt.AlignCenter)
        lbl.setPixmap(pix.scaled(680, 680, Qt.KeepAspectRatio))

        lay = QVBoxLayout(dlg)
        lay.addWidget(lbl)
        dlg.exec()

    def _set_image(self, row, col, img):
        if not img:
            return

        pix = QPixmap()
        pix.loadFromData(bytes(img))

        lbl = QLabel()
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setPixmap(pix.scaled(220, 130, Qt.KeepAspectRatio))
        lbl.setCursor(Qt.PointingHandCursor)

        lbl.mousePressEvent = lambda e, b=img: self.show_image_dialog(b)

        self.table.setCellWidget(row, col, lbl)

    def export_excel(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Excel", "", "Excel Files (*.xlsx)"
        )
        if not path:
            return

        if not path.lower().endswith(".xlsx"):
            path += ".xlsx"

        wb = Workbook()
        ws = wb.active
        ws.title = "Inspection Report"

        headers = [
            "Employee ID",
            "Work Order",
            "Charge No",
            "Serial No",
            "Vendor Code",
            "Batch No",
            "Status",
            "Date",
            "Time",
            "ColorImage",
            "Front_MpiImage",
            "Back_MpiImage",
        ]
        ws.append(headers)

        green = PatternFill("solid", fgColor="C6EFCE")
        red = PatternFill("solid", fgColor="FFC7CE")

        f = datetime.combine(self.from_dt.date().toPython(), time.min)
        t = datetime.combine(self.to_dt.date().toPython(), time.max)
        unique_text = self.search_unique.text().strip()

        rows, _ = fetch_report(f, t, self.status.currentText(), unique_text)

        row_no = 2  # start after header

        for r in rows:
            ws.append(
                [
                    r[0],  # employee_id
                    r[1],  # work_order
                    r[2],  # charge_no
                    r[3],  # serial_no
                    r[4],  # vendor_code
                    r[5],  # batch
                    r[9],  # status
                    r[10].strftime("%Y-%m-%d"),
                    r[10].strftime("%H:%M:%S"),
                    "",  # Image
                    "",  # Front Image
                    "",  # Back Image
                ]
            )

            # Status color
            ws[f"G{row_no}"].fill = green if r[7] == "OK" else red

            # -------- IMAGE INSERT --------
            if r[6]:
                img_bytes = bytes(r[6])

                with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
                    tmp.write(img_bytes)
                    tmp_path = tmp.name

                img = XLImage(tmp_path)
                img.width = 120
                img.height = 80

                ws.add_image(img, f"J{row_no}")

                ws.row_dimensions[row_no].height = 65

            row_no += 1

        # Adjust column width
        ws.column_dimensions["J"].width = 22

        wb.save(path)

        TextToast("Excel exported with images", self).show_bottom()

    def show_image_dialog(self, img_bytes):
        dlg = QDialog(self)
        dlg.setWindowTitle("Image View")
        dlg.resize(600, 600)

        pix = QPixmap()
        pix.loadFromData(bytes(img_bytes))

        lbl = QLabel(alignment=Qt.AlignCenter)
        lbl.setPixmap(pix.scaled(560, 560, Qt.KeepAspectRatio))

        lay = QVBoxLayout(dlg)
        lay.addWidget(lbl)

        dlg.exec()


# ================= MAIN =================
class Main(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Camera Inspection System")
        self.resize(1600, 900)

        nav = QHBoxLayout()
        self.stack = QStackedWidget()

        # ---- Pages ----
        self.home = Home()
        self.operator = Operator()
        self.report = Report()

        # ---- Add pages to stack (CRITICAL) ----
        self.stack.addWidget(self.home)
        self.stack.addWidget(self.operator)
        self.stack.addWidget(self.report)

        # ---- Navigation buttons (NO UI change) ----
        btn_home = QPushButton("Home")
        btn_operator = QPushButton("Operator")
        btn_report = QPushButton("Report")

        btn_home.clicked.connect(self.go_home)
        btn_operator.clicked.connect(self.go_operator)
        btn_report.clicked.connect(self.go_report)

        nav.addWidget(btn_home)
        nav.addWidget(btn_operator)
        nav.addWidget(btn_report)
        nav.addStretch()

        # ---- Refresh connections ----
        self.operator.record_saved.connect(self.report.load)
        self.operator.record_saved.connect(self.home.refresh)

        # ---- Layout ----
        lay = QVBoxLayout(self)
        lay.addLayout(nav)
        lay.addWidget(self.stack)

        # ---- Default page ----
        self.stack.setCurrentWidget(self.home)

    def go_home(self):
        self.operator.on_leave()
        self.stack.setCurrentWidget(self.home)

    def go_operator(self):
        self.stack.setCurrentWidget(self.operator)
        self.operator.on_enter()

    def go_report(self):
        self.operator.on_leave()
        self.stack.setCurrentWidget(self.report)

    def closeEvent(self, event):
        if self.operator.socket_thread:
            print("Stopping socket thread")
            self.operator.socket_thread.stop()
            self.operator.socket_thread.wait()
        event.accept()


# ================= RUN =================
if __name__ == "__main__":
    init_db()
    app = QApplication(sys.argv)
    w = Main()
    w.show()
    sys.exit(app.exec())
