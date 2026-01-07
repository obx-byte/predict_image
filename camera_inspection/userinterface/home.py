from PySide6.QtWidgets import (
                                QWidget
                               ,QVBoxLayout,
                               QLabel,
                               QHBoxLayout
                               )


from db.db_queries import get_home_counts



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
