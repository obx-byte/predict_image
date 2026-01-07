from PySide6.QtWidgets import (
                                QWidget,
                                QPushButton,
                                QHBoxLayout,
                                QLineEdit,
                                QGridLayout,
                                QLabel,
                                QSizePolicy,
                                QVBoxLayout,
                                QDialog
                                )


from PySide6.QtGui import QPixmap,QImage

from PySide6.QtCore import Signal,QTimer,Qt

from config.socket_config import FHVSocketThread

from db.db_queries import save_record,unique_exists

from utils.helpers import clean_text

from userinterface.toasts import TextToast
import cv2

class Operator(QWidget):
    record_saved = Signal()
    EMP_LEN = 10
    WO_LEN = 10

    def __init__(self):
        super().__init__()
        self.camera_paused = False

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

        top = QHBoxLayout()
        top.addStretch()
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
            le.setReadOnly(True)
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
        dlg.setFixedSize(300, 160)

        btn_ok = QPushButton(" OK")
        btn_ng = QPushButton(" NOT OK")

        btn_ok.setStyleSheet("background:green;color:white;font-size:14px")
        btn_ng.setStyleSheet("background:red;color:white;font-size:14px")

        btn_ok.clicked.connect(lambda: self.final_save("OK", dlg))
        btn_ng.clicked.connect(lambda: self.final_save("NOT_OK", dlg))

        lay = QVBoxLayout(dlg)
        lay.addStretch()
        lay.addWidget(btn_ok)
        lay.addWidget(btn_ng)
        lay.addStretch()

        dlg.exec()





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

        save_record(data, status, self.captured_img)

        TextToast(f"{status} saved | Batch {data['unique']}", self).show_bottom()

        self.captured_img = None

        if self.socket_thread:
            self.socket_thread.resume()

        self.record_saved.emit()



    def on_enter_key(self):
        # Validate first
        if self.frame is None:
            TextToast("Camera not ready", self).show_bottom()
            return

        if not self.all_fields_valid():
            TextToast("Invalid input", self).show_bottom()
            return

        # Capture ONE image only
        _, buf = cv2.imencode(".jpg", self.frame)
        self.captured_img = buf.tobytes()

        self.show_ok_notok_dialog()






    def on_socket_data(self, msg):
        print("Socket accepted:", msg)

        charge = "A7152693506002"
        part_no = msg[18:22]
        batch_code = msg[13:17]  # UNIQUE
        vendor_code = "16099680"

        #  DUPLICATE CHECK
        if unique_exists(batch_code):
            print(" Duplicate UNIQUE detected:", batch_code)

            # Fill fields so operator sees the issue
            self.inputs["charge"][1].setText(charge)
            self.inputs["serial"][1].setText(part_no)
            self.inputs["unique"][1].setText(batch_code)
            self.inputs["Vendor Code"][1].setText(vendor_code)

            # Mark all RED
            self.mark_all_red()

            #  SHOW TOAST
            toast = TextToast(" DUPLICATE PART DETECTED", self)
            toast.show_bottom()

            # ⏸ Pause socket (already paused by waiting_for_user=True)
            if self.socket_thread:
                self.socket_thread.pause()

            # ⏱ Clear fields & resume socket after 3 sec
            QTimer.singleShot(3000, self.clear_and_resume)
            return


        #  NEW UNIQUE → NORMAL FLOW
        self.reset_input_colors()

        self.emp.returnPressed.connect(self.on_enter_key)
        self.wo.returnPressed.connect(self.on_enter_key)



        self.inputs["charge"][1].setText(charge)
        self.inputs["serial"][1].setText(part_no)
        self.inputs["unique"][1].setText(batch_code)
        self.inputs["Vendor Code"][1].setText(vendor_code)

        print(" Unique OK → auto capture in 4s")


    def clear_and_resume(self):
        for _, le, _ in self.inputs.values():
            le.clear()
            le.setStyleSheet(
                "background:transparent;color:white;border:1px solid #555;"
            )

        print("▶ Camera resumed")
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

    def wo_done(self):
        if self.wo.text():
            self.wo.hide()

            for lbl, le, _ in self.inputs.values():
                lbl.show()
                le.show()

            self.start_camera()

    def validate_field(self, key):
        _, le, ln = self.inputs[key]
        if not le.text():
            le.setStyleSheet(
                "background:transparent;color:white;border:1px solid #555;"
            )
        elif len(le.text()) == ln:
            le.setStyleSheet("background:#1b5e20;color:white;border:1px solid #2ecc71;")
        else:
            le.setStyleSheet("background:#7f0000;color:white;border:1px solid #e74c3c;")

    # ---------- CAMERA ----------
    def start_camera(self):
        if self.cap is None:
            self.cap = cv2.VideoCapture(1, cv2.CAP_DSHOW)
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
            return   #  camera frozen

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
                "background:transparent;color:white;border:1px solid #555;"
            )

        self.emp.setFocus()

    def all_fields_valid(self):
        for _, le, ln in self.inputs.values():
            if len(le.text()) != ln:
                return False
        return True

    def on_enter(self):
        print("Operator screen entered")

        if self.socket_thread is None:
            print("Starting socket thread")
            self.socket_thread = FHVSocketThread()
            self.socket_thread.data_received.connect(self.on_socket_data)
            self.socket_thread.start()
        else:
            print("Resuming socket")
            self.socket_thread.resume()

    def on_leave(self):
        print("Leaving Operator screen")

        if self.socket_thread:
            self.socket_thread.pause()
