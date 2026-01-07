from db.db_init import init_db
from PySide6.QtWidgets import QApplication

from userinterface.main import Main
import sys


if __name__ == "__main__":
    init_db()
    app = QApplication(sys.argv)
    w = Main()
    w.show()
    sys.exit(app.exec())
