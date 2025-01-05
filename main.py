import sys
import math
import threading
import logging
import time

import pythoncom
import pyWinhook as pwh
import keyboard

from PyQt5 import QtCore, QtGui, QtWidgets

###############################################################################
# ЛОГИРОВАНИЕ
###############################################################################
logging.basicConfig(
    level=logging.INFO,  # Можно поставить DEBUG для подробного логирования
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
    ]
)

###############################################################################
# ГЛОБАЛЬНЫЕ ОБЪЕКТЫ И ФЛАГИ
###############################################################################
overlay = None

# Хук мыши и поток
hm = None
hook_mouse_thread = None
MOUSE_HOOK_RUNNING = True  # флаг, по которому остановим поток

# Идентификаторы горячих клавиш
TOGGLE_HOTKEY_ID = None       # '=' — вкл/выкл измерений
CALIBRATE_HOTKEY_ID = None    # 'c' — калибровка заново
EXIT_HOTKEY_ID = None         # 'ctrl+shift+q' — закрыть оверлей
CLEAR_LINES_HOTKEY_ID = None  # '-,=' — очистить линии (сначала '-', потом '=')

# Порог расстояния в пикселях, чтобы определить: это был drag или просто клик
MIN_DRAG_DISTANCE = 10

###############################################################################
# ГЛОБАЛЬНЫЙ ХУК МЫШИ (pyWinhook)
###############################################################################
def on_mouse_event(event):
    """
    Глобальный перехватчик событий мыши.
    Возвращаем False и выставляем event.DontRouteToDefault=True,
    если нужно заблокировать событие для других приложений (включая игру).
    """
    global overlay

    # Пропускаем "mouse move", чтобы не спамить лог по 1000 раз в секунду:
    if event.MessageName == "mouse move":
        return True

    # Если оверлей не создан или измерение неактивно — всё пропускаем в игру + PyQt
    if not overlay or not overlay.is_measuring:
        return True

    logging.debug(f"Mouse event: {event.MessageName} at {event.Position}, is_measuring={overlay.is_measuring}")

    # --- ЛКМ пропускаем (не блокируем), чтобы она шла в игру ---
    if event.MessageName in ["mouse left down", "mouse left up", "mouse left drag"]:
        return True

    # --- Рисование отрезков ПКМ ---
    if event.MessageName in ["mouse right down", "mouse right up"]:
        x, y = event.Position

        if overlay.isVisible():
            # Вызываем методы по аналогии с onMouseLeftDown / onMouseLeftUp, но для ПКМ
            method = "onMouseRightDown" if event.MessageName == "mouse right down" else "onMouseRightUp"
            QtCore.QMetaObject.invokeMethod(
                overlay,
                method,
                QtCore.Qt.QueuedConnection,
                QtCore.Q_ARG(int, x),
                QtCore.Q_ARG(int, y)
            )
            # Блокируем дальше, чтобы ПКМ не шла в игру
            event.DontRouteToDefault = True
            return False

    return True


def install_mouse_hook():
    """Устанавливаем глобальный хук мыши в отдельном потоке."""
    logging.debug("Installing global mouse hook...")
    pythoncom.CoInitialize()

    global hm
    hm = pwh.HookManager()
    hm.MouseAll = on_mouse_event
    hm.HookMouse()

    try:
        # Основной цикл обработки сообщений
        while MOUSE_HOOK_RUNNING:
            pythoncom.PumpWaitingMessages()
            time.sleep(0.0001)
    except Exception as e:
        logging.exception("Exception in mouse hook thread!")
    finally:
        logging.debug("Exiting mouse hook thread (finally).")


def uninstall_mouse_hook():
    """Снимаем глобальный хук мыши и останавливаем поток."""
    logging.debug("Uninstalling global mouse hook...")
    global hm, MOUSE_HOOK_RUNNING
    MOUSE_HOOK_RUNNING = False
    if hm is not None:
        hm.UnhookMouse()
        hm = None

###############################################################################
# ГЛОБАЛЬНЫЕ ХОТКЕИ
###############################################################################
def toggle_measurement():
    """Функция, вызываемая при нажатии '=' — вкл/выкл режима измерений."""
    global overlay
    if overlay and overlay.isVisible():
        logging.debug("Hotkey '=' pressed. Toggling measurement...")
        QtCore.QMetaObject.invokeMethod(
            overlay,
            "toggleMeasurement",
            QtCore.Qt.QueuedConnection
        )


def start_calibration():
    """Функция хоткея 'c' — начать калибровку заново."""
    global overlay
    if overlay and overlay.isVisible():
        logging.debug("Hotkey 'c' pressed. Starting new calibration.")
        QtCore.QMetaObject.invokeMethod(
            overlay,
            "startCalibration",
            QtCore.Qt.QueuedConnection
        )


def close_overlay():
    """Функция хоткея 'ctrl+shift+q' — закрыть оверлей."""
    global overlay
    if overlay and overlay.isVisible():
        logging.debug("Hotkey 'ctrl+shift+q' pressed. Closing overlay.")
        QtCore.QMetaObject.invokeMethod(
            overlay,
            "close",
            QtCore.Qt.QueuedConnection
        )


def clear_lines_shortcut():
    """Функция, вызываемая при последовательном нажатии '-', затем '='."""
    global overlay
    if overlay and overlay.isVisible():
        logging.debug("Hotkey '-,=' pressed. Clearing lines...")
        QtCore.QMetaObject.invokeMethod(
            overlay,
            "clearLines",
            QtCore.Qt.QueuedConnection
        )


def install_keyboard_hotkey():
    """
    Регистрируем все необходимые хоткеи.
    """
    global TOGGLE_HOTKEY_ID, CALIBRATE_HOTKEY_ID, EXIT_HOTKEY_ID, CLEAR_LINES_HOTKEY_ID
    logging.debug("Installing global hotkeys: '=', 'c', 'ctrl+shift+q', '-,=' ...")

    # 1) '=' — вкл/выкл измерений
    TOGGLE_HOTKEY_ID = keyboard.add_hotkey('=', toggle_measurement)
    # 2) 'c' — начать калибровку заново
    CALIBRATE_HOTKEY_ID = keyboard.add_hotkey('c', start_calibration)
    # 3) 'ctrl+shift+q' — закрыть окно
    EXIT_HOTKEY_ID = keyboard.add_hotkey('ctrl+shift+q', close_overlay)
    # 4) '-,=' — сначала минус, потом равно => очистить все линии
    CLEAR_LINES_HOTKEY_ID = keyboard.add_hotkey('-,=', clear_lines_shortcut)

###############################################################################
# PYQT-КЛАСС: Оверлей на весь экран
###############################################################################
class OverlayWindow(QtWidgets.QMainWindow):
    """
    Главное окно-оверлей, где мы обрабатываем ПКМ для рисования линий.
    ЛКМ идёт в игру, калибровка — при нажатии 'c', очистка линий — '-,='.
    """

    @QtCore.pyqtSlot(int, int)
    def onMouseRightDown(self, x, y):
        """Обработчик клика ПКМ (Down) — вызывается из глобального хука."""
        logging.debug(f"onMouseRightDown: x={x}, y={y}, is_measuring={self.is_measuring}")

        if not self.is_measuring:
            return

        # Начинаем рисовать линию
        self.is_drawing = True
        self.first_point = (x, y)
        logging.debug(f"First point set to {self.first_point}")

    @QtCore.pyqtSlot(int, int)
    def onMouseRightUp(self, x, y):
        """Обработчик клика ПКМ (Up) — вызывается из глобального хука."""
        try:
            logging.debug(
                f"onMouseRightUp: x={x}, y={y}, "
                f"is_measuring={self.is_measuring}, first_point={self.first_point}"
            )

            if not self.is_measuring:
                return

            if not self.is_drawing or self.first_point is None:
                return

            x1, y1 = self.first_point
            x2, y2 = x, y
            self.first_point = None
            self.is_drawing = False

            # Рассчитываем расстояние между точками
            dist_px = self._distance_in_pixels(x1, y1, x2, y2)

            # Фильтр слишком короткого движения
            if dist_px < MIN_DRAG_DISTANCE:
                logging.debug(
                    f"Distance {dist_px:.2f} < {MIN_DRAG_DISTANCE} px -> click, no measurement."
                )
                return

            logging.debug(f"Distance in pixels: {dist_px:.2f}")

            # Если калибруемся
            if self.is_calibrating:
                if self.is_calibration_dialog_open:
                    self.text_info = "Окно калибровки уже открыто, введите число или закройте диалог."
                    self.update()
                    return

                self.is_calibration_dialog_open = True
                old_meas = self.is_measuring
                self.is_measuring = False  # чтобы не ловить клики в диалоге

                text, ok = QtWidgets.QInputDialog.getText(
                    self,
                    "Калибровка",
                    f"Вы протянули {dist_px:.1f} px.\nСколько это в метрах?"
                )
                logging.debug(f"Calibration dialog: text='{text}', ok={ok}")

                if ok and text.strip():
                    try:
                        real_length = float(text.replace(',', '.'))
                        logging.debug(f"Parsed real_length={real_length}")
                        if real_length > 0:
                            self.scale_factor = real_length / dist_px
                            self.is_calibrating = False
                            # Снова включаем измерения
                            self.is_measuring = True
                            self.text_info = (
                                f"Калибровка завершена:\n"
                                f"1 px = {self.scale_factor:.4f} м.\n"
                                "Теперь рисуйте новые отрезки (ПКМ) или "
                                "нажмите '-,=' чтобы очистить."
                            )
                            logging.debug(
                                f"Calibration success. scale_factor={self.scale_factor}"
                            )
                        else:
                            self.text_info = "Некорректная длина. Калибровка не выполнена."
                            logging.debug("Calibration failed: non-positive real_length.")
                    except ValueError:
                        self.text_info = "Не удалось распознать число. Калибровка не выполнена."
                        logging.debug("Calibration failed: ValueError on input.")
                else:
                    self.text_info = "Калибровка отменена или не введено число."
                    logging.debug("Calibration canceled or empty input.")

                # Если калибровка провалилась, оставим is_calibrating = True
                if not hasattr(self, 'scale_factor') or self.scale_factor is None:
                    self.is_calibrating = True

                self.is_measuring = old_meas
                self.is_calibration_dialog_open = False
                self.update()

            else:
                # Мы уже откалиброваны — сохраняем отрезок
                if self.scale_factor is not None and self.scale_factor > 0:
                    dist_m = dist_px * self.scale_factor
                    dx = x2 - x1
                    dy = y2 - y1
                    # Угол: 0° — вверх, 90° — вправо, 180° — вниз
                    angle_deg = math.degrees(math.atan2(dx, (y1 - y2)))
                    angle_deg %= 360

                    self.lines.append((x1, y1, x2, y2, dist_m, angle_deg))
                    self.text_info = (
                        f"Новый отрезок: {dist_m:.2f} м, {angle_deg:.2f}°\n"
                        f"(в пикселях: {dist_px:.1f})\n"
                        "Продолжайте рисовать ПКМ или нажмите '-,=' для очистки.\n"
                        "Нажмите 'c' для повторной калибровки."
                    )
                    logging.debug(
                        f"New segment: {dist_m:.2f} m, {angle_deg:.2f} deg. "
                        f"Lines total={len(self.lines)}"
                    )
                    print("Ваш отрезок:", dist_m, "м, угол:", angle_deg, "° (px:", dist_px, ")")
                else:
                    self.text_info = "Сначала нужно откалиброваться (нажмите 'c')."
                    logging.debug("Attempted to measure without valid calibration.")

                self.update()

        except Exception as e:
            logging.exception("Ошибка в onMouseRightUp:")

    def __init__(self):
        super().__init__()
        logging.debug("Initializing OverlayWindow...")

        # Окно без рамок, поверх всех окон, но без захвата фокуса
        self.setWindowFlags(
            QtCore.Qt.FramelessWindowHint
            | QtCore.Qt.WindowStaysOnTopHint
            | QtCore.Qt.WindowDoesNotAcceptFocus
        )
        # Прозрачный фон
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground, True)
        # По умолчанию окно пропускает клики
        self.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents, True)

        # Разворачиваем на весь экран
        screen = QtWidgets.QApplication.primaryScreen().size()
        self.setGeometry(0, 0, screen.width(), screen.height())

        # Переменные для логики измерения
        self.is_measuring = False
        self.is_calibrating = True
        self.is_calibration_dialog_open = False
        self.scale_factor = None

        self.is_drawing = False
        self.lines = []
        self.first_point = None

        self.text_info = (
            "Оверлей запущен.\n"
            "Нажмите '=' для включения измерений (ПКМ).\n"
            "Первый отрезок — калибровка (или 'c' для перекалибровки).\n"
            "ЛКМ при этом проходит в игру.\n"
            "Ctrl+Shift+Q — закрыть.\n"
            "Чтобы очистить все линии, нажмите '-' а затем '='."
        )

        # Создаём центральный виджет (прозрачный)
        central_widget = QtWidgets.QWidget(self)
        central_widget.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents, True)
        self.setCentralWidget(central_widget)

        # Создаём панель информации
        self.info_panel = QtWidgets.QFrame(self)
        self.info_panel.setGeometry(20, 20, 350, 160)
        self.info_panel.setStyleSheet("""
            QFrame {
                background-color: rgba(30, 30, 30, 200);
                border-radius: 10px;
            }
        """)
        self.info_layout = QtWidgets.QVBoxLayout(self.info_panel)
        self.info_layout.setContentsMargins(10, 10, 10, 10)

        self.info_label = QtWidgets.QLabel(self.text_info, self.info_panel)
        self.info_label.setStyleSheet("color: white; font-size: 14px;")
        self.info_label.setWordWrap(True)
        self.info_layout.addWidget(self.info_label)

        # Кнопка очистки линий (дублирует хоткей '-,=')
        self.clear_button = QtWidgets.QPushButton("Очистить все линии", self.info_panel)
        self.clear_button.setFixedHeight(40)
        self.clear_button.setStyleSheet("""
            QPushButton {
                background-color: #555555;
                color: white;
                border: none;
                border-radius: 5px;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #777777;
            }
            QPushButton:pressed {
                background-color: #999999;
            }
        """)
        self.clear_button.clicked.connect(self.clearLines)
        self.info_layout.addWidget(self.clear_button)

        # Кнопка закрытия (крестик)
        self.close_button = QtWidgets.QPushButton("✕", self.info_panel)
        self.close_button.setFixedSize(30, 30)
        self.close_button.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: white;
                font-size: 18px;
                border: none;
            }
            QPushButton:hover {
                color: red;
            }
        """)
        self.close_button.clicked.connect(self.close)
        self.close_button.move(self.info_panel.width() - 40, 10)

        self.show()
        logging.debug("OverlayWindow shown.")

    def clearLines(self):
        """Очищает все нарисованные линии."""
        logging.debug("Clearing all lines.")
        self.lines.clear()
        self.text_info = (
            "Все линии очищены.\n"
            "Продолжайте измерения (ПКМ) или нажмите '=' для настроек."
        )
        self.info_label.setText(self.text_info)
        self.update()

    @QtCore.pyqtSlot()
    def toggleMeasurement(self):
        """
        Вкл/выкл режима измерений (ПКМ).
        Когда измерение включено — окно ловит ПКМ (WA_TransparentForMouseEvents=False).
        Когда выключено — пропускаем все клики (ПКМ тоже не ловим).
        """
        self.is_measuring = not self.is_measuring
        logging.debug(f"Measurement toggled: is_measuring={self.is_measuring}")

        if self.is_measuring:
            self.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents, False)
            self.text_info = (
                "Режим измерений (ПКМ) ВКЛ.\n"
                "Первый отрезок — калибровка (если не сделано) или 'c' для перекалибровки.\n"
                "ЛКМ идёт в игру.\n"
                "Нажмите '=': выключить измерения.\n"
                "Нажмите '-,=': очистить линии.\n"
                "Ctrl+Shift+Q: закрыть."
            )
        else:
            self.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents, True)
            self.text_info = (
                "Режим измерений ВЫКЛ.\n"
                "Клики (в т.ч. ПКМ) идут в игру.\n"
                "Нажмите '=': снова включить.\n"
                "Ctrl+Shift+Q: закрыть.\n"
                "'-,=': очистить линии в любой момент."
            )
        self.info_label.setText(self.text_info)
        self.update()

    def startCalibration(self):
        """Перезапуск калибровки при хоткее 'c'."""
        self.is_calibrating = True
        self.is_measuring = True
        self.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents, False)
        self.scale_factor = None
        self.text_info = (
            "Режим калибровки ВКЛ (ПКМ).\n"
            "Протяните новую линию и введите реальную длину.\n"
            "Нажмите '=': отключить измерения.\n"
            "Ctrl+Shift+Q: закрыть."
        )
        self.info_label.setText(self.text_info)
        self.update()

    def paintEvent(self, event):
        """Рисуем все линии + текстовую подсказку (self.text_info)."""
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)

        # Полупрозрачный слой для линий
        painter.setBrush(QtCore.Qt.NoBrush)

        # Все нарисованные линии
        pen = QtGui.QPen(QtGui.QColor(255, 0, 0, 200), 3)
        painter.setPen(pen)
        for (x1, y1, x2, y2, dist_m, angle_deg) in self.lines:
            painter.drawLine(x1, y1, x2, y2)
            # Рисуем стрелки на концах линии
            self.draw_arrow(painter, x1, y1, x2, y2)

            # Текст с информацией о линии
            mx = (x1 + x2) / 2
            my = (y1 + y2) / 2
            text = f"{dist_m:.2f} м, {angle_deg:.1f}°"
            painter.setPen(QtGui.QColor(255, 255, 255, 220))
            painter.setFont(QtGui.QFont("Arial", 12, QtGui.QFont.Bold))
            painter.drawText(QtCore.QPointF(mx + 10, my - 10), text)

    def draw_arrow(self, painter, x1, y1, x2, y2):
        """Рисует стрелку между двумя точками."""
        line = QtCore.QLineF(x1, y1, x2, y2)
        angle = math.atan2(-line.dy(), line.dx())

        arrow_size = 10
        p1 = line.p2() - QtCore.QPointF(
            math.cos(angle + math.pi / 6) * arrow_size,
            math.sin(angle + math.pi / 6) * arrow_size
        )
        p2 = line.p2() - QtCore.QPointF(
            math.cos(angle - math.pi / 6) * arrow_size,
            math.sin(angle - math.pi / 6) * arrow_size
        )

        arrow_head = QtGui.QPolygonF([line.p2(), p1, p2])
        painter.setBrush(QtGui.QColor(255, 0, 0, 200))
        painter.drawPolygon(arrow_head)

    def keyPressEvent(self, event: QtGui.QKeyEvent):
        """Отключаем выход по Esc, чтобы не мешало."""
        pass

    def closeEvent(self, event):
        """Закрытие окна: снимаем хук, удаляем хоткеи и завершаем приложение."""
        logging.debug("closeEvent triggered. Removing hotkeys и unhooking mouse.")
        try:
            if TOGGLE_HOTKEY_ID is not None:
                keyboard.remove_hotkey(TOGGLE_HOTKEY_ID)
            if CALIBRATE_HOTKEY_ID is not None:
                keyboard.remove_hotkey(CALIBRATE_HOTKEY_ID)
            if EXIT_HOTKEY_ID is not None:
                keyboard.remove_hotkey(EXIT_HOTKEY_ID)
            if CLEAR_LINES_HOTKEY_ID is not None:
                keyboard.remove_hotkey(CLEAR_LINES_HOTKEY_ID)
        except Exception as e:
            logging.exception("Ошибка при удалении горячих клавиш:")

        uninstall_mouse_hook()

        global hook_mouse_thread
        if hook_mouse_thread is not None and hook_mouse_thread.is_alive():
            hook_mouse_thread.join()

        super().close()
        QtWidgets.QApplication.quit()

    @staticmethod
    def _distance_in_pixels(x1, y1, x2, y2):
        dx = x2 - x1
        dy = y2 - y1
        return math.sqrt(dx * dx + dy * dy)

###############################################################################
# MAIN
###############################################################################
def main():
    logging.debug("Starting application...")
    app = QtWidgets.QApplication(sys.argv)

    global overlay
    overlay = OverlayWindow()

    # Глобальные хоткеи
    install_keyboard_hotkey()

    # Запуск отдельного потока с хуком мыши
    global hook_mouse_thread
    hook_mouse_thread = threading.Thread(target=install_mouse_hook, daemon=True)
    hook_mouse_thread.start()
    logging.debug("Mouse hook thread started.")

    # Запуск GUI
    ret_code = app.exec_()
    logging.debug(f"App exec returned {ret_code}. Exiting main().")
    sys.exit(ret_code)


if __name__ == "__main__":
    main()