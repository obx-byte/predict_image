from PySide6.QtWidgets import QWidget,QHBoxLayout,QStackedWidget,QPushButton,QVBoxLayout
from home import Home
from report import Report
from operator import Operator






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
