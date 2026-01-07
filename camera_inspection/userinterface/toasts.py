
from PySide6.QtWidgets import QWidget,QLabel,QVBoxLayout,QApplication
from PySide6.QtCore import QTimer


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
