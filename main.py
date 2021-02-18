import sys
import time
import threading
import yaml
import logging
from logging.handlers import RotatingFileHandler
from collections import deque
from PyQt5 import QtWidgets, QtCore, QtGui
from PyQt5.QtCore import QRunnable, Qt, QThreadPool
import tkinter as tk
from PIL import Image, ImageDraw, ImageGrab, ImageQt
from cryptlex.lexactivator import LexActivator, LexStatusCodes, PermissionFlags, LexActivatorException
import numpy as np
import cv2

from ocr_utils import extract_data


# Default config if not found config.yaml
default_config = {
    'logfile': 'app.log',
    'debug': False,
    'max_trace': 4,
    'max_trace': 10,
    'interval': 0.5,
    'rois': {
        'left': [0, 0, 0, 0],
        'right': [0, 0, 0, 0]
    }
}

# Overwrite
def load_config(config_file='config.yaml'):
    config = default_config
    try:
        with open('config.yaml') as f:
            config = yaml.load(f, Loader=yaml.FullLoader)
    except FileNotFoundError:
        logging.exception('Not found config file')
    except Exception as e:
        logging.exception(f'Unexpected error: {e}')
    return config


def save_config(config, config_file='config.yaml'):
    try:
        with open(config_file, 'w') as f:
            yaml.dump(config, f)
    except:
        logging.exception(f'Failed when saving config: {config}')


config = load_config()

# Setup logging
level = logging.DEBUG if config['debug'] else logging.INFO
fmt = logging.Formatter('%(asctime)s %(levelname)s %(funcName)s(%(lineno)d) %(message)s')

handler = RotatingFileHandler(config['logfile'], mode='a', maxBytes=5*1024*1024, 
                                         backupCount=2, encoding=None, delay=0)
handler.setFormatter(fmt)
handler.setLevel(level)

logger = logging.getLogger('root')
logger.setLevel(level)
logger.addHandler(handler)


# Define global vars
ready_event = threading.Event()
terminate_event = threading.Event()
ready_event.clear()
terminate_event.clear()
lock = threading.Lock()
g_column_data = {
    'bid': {'image': None, 'result': []},
    'ask': {'image': None, 'result': []}
}

show_lock = threading.Lock()
sums = {
    'bid': deque([0] * config['max_trace'], maxlen=config['max_trace']),
    'ask': deque([0] * config['max_trace'], maxlen=config['max_trace']),
}
mode = None


# class DebugWindow(QtWidgets.QMainWindow):
#     def __init__(self):
#         super().__init__()

#         # Horizontal layout
#         layout = QtWidgets.QHBoxLayout()
        
#         # First column
#         layout.addStretch(1)
#         self.column_1 = QtWidgets.QLabel(self)
#         img1 = Image.fromarray(np.full((300, 300, 3), 255, dtype='uint8'))
#         pixmap_1 = QtGui.QPixmap.fromImage(ImageQt.ImageQt(img1))
#         self.column_1.setPixmap(pixmap_1)
#         layout.addWidget(self.column_1)
#         layout.addStretch(1)
        
#         # Second column
#         self.column_2 = QtWidgets.QLabel(self)
#         img2 = Image.fromarray(np.full((300, 300, 3), 255, dtype='uint8'))
#         pixmap_2 = QtGui.QPixmap.fromImage(ImageQt.ImageQt(img2))
#         self.column_2.setPixmap(pixmap_2)
#         layout.addWidget(self.column_2)
#         layout.addStretch(1)

#         self.setWindowTitle('Debugger')
        
#         # Initialize
#         self.is_resized = False
#         self.update_images()
        
#         self.setGeometry(200, 200, 300, 300)
        
#         self.timer = QtCore.QTimer(self)
#         self.timer.timeout.connect(self.update_images)
#         self.timer.start(1000)

#     def update_images(self):
#         global lock, g_column_data
#         height, width = 300, 300
#         with lock:
#             if g_column_data['column_1']['image'] is not None:
#                 # Draw
#                 image_1 = g_column_data['column_1']['image']
#                 draw_1 = ImageDraw.Draw(image_1)
#                 for text_box in g_column_data['column_1']['result']:
#                     x1, y1, text = text_box[0], text_box[1], text_box[4]
#                     draw_1.text((x1, y1), text, fill=(0, 255, 0))
#                 pixmap_1 = QtGui.QPixmap.fromImage(ImageQt.ImageQt(image_1))
#                 self.column_1.setPixmap(pixmap_1)
#                 height = pixmap_1.height()
#                 width = pixmap_1.width()
        
#         with lock:
#             if g_column_data['column_2']['image'] is not None:
#                 # Draw
#                 image_2 = g_column_data['column_2']['image']
#                 draw_2 = ImageDraw.Draw(image_2)
#                 for text_box in g_column_data['column_2']['result']:
#                     x1, y1, text = text_box[0], text_box[1], text_box[4]
#                     draw_2.text((x1, y1), text, fill=(0, 255, 0))
#                 pixmap_2 = QtGui.QPixmap.fromImage(ImageQt.ImageQt(image_2))
#                 self.column_2.setPixmap(pixmap_2)
#                 height = pixmap_2.height()
#                 width += pixmap_2.width() + 50
        
#         if not self.is_resized:
#             self.resize(width, height)
#             self.is_resized = True


class OCRWorker(QRunnable):
    def __init__(self, pts1, pts2, interval=0.5):
        super().__init__()
        self.interval = interval

        self.first_x1, self.first_y1, self.first_x2, self.first_y2 = pts1
        self.second_x1, self.second_y1, self.second_x2, self.second_y2 = pts2
        self.debug = config.get('debug', False)
        self.conf_thresh = config.get('conf_thresh', 80)
        self.inputs = {
            'bid': (self.first_x1, self.first_y1, self.first_x2, self.first_y2),
            'ask': (self.second_x1, self.second_y1, self.second_x2, self.second_y2)
        }
    
    def _process_results(self, results):
        """
        """
        sorted_rs = sorted(results, key=lambda x: x[1])
        prev = None
        data = []
        row = []
        for text_box in sorted_rs:
            y1, y2 = text_box[1], text_box[3]
            if prev is None:
                row = [text_box]
            else:
                if y1 > prev:
                    data.append(text_box)
                    row = [text_box]
                else:
                    row.append(text_box)
            prev = y2
        return data

    def run(self):
        """
        """
        global lock, g_column_data, show_lock, sums
        while True:
            if terminate_event.wait(0.01):
                break
            
            if not ready_event.wait(self.interval):
                continue
                        
            # Start to capture screen and extract data
            results = {}
            for col_name, roi in self.inputs.items():
                x1, y1, x2, y2 = roi
                try:
                    img = ImageGrab.grab((x1, y1, x2, y2))
                    if self.debug:
                        filename = f'roi_{col_name}.png'
                        img.save(filename)
                        logger.debug('Dump image as {}'.format(filename))
                    col_result = extract_data(img, self.conf_thresh, col_name, self.debug)
                    if self.debug:
                        with lock:
                            g_column_data[col_name]['image'] = img
                            g_column_data[col_name]['result'] = col_result
                except Exception as e:
                    logger.exception(f'Error while captured: {e}')
                    continue
                
                col_result = sorted(col_result, key=lambda x: x[1])
                results[col_name] = col_result
                
            # Post-processing
            if len(results) > 0:
                with show_lock:
                    for col_name, rs in results.items():
                        if self.debug:
                            logger.info('{} with result: {}'.format(col_name, rs))
                        sum_ = 0
                        for cell in rs:
                            try:
                                sum_ += int(cell[4])
                            except:
                                pass
                        sums[col_name].appendleft(sum_)
            else:
                logger.warn('Not found anything')


class ROISelector(QtWidgets.QMainWindow):
    switch_window = QtCore.pyqtSignal()
    def __init__(self):
        super().__init__()
        global mode
        
        root = tk.Tk()
        screen_width = root.winfo_screenwidth()
        screen_height = root.winfo_screenheight()
        self.is_selected = False
        self.setGeometry(0, 0, screen_width, screen_height)
        self.setWindowTitle(' ')
        
        # ROIs
        self.mode = mode
        self.rois = [[0, 0, 0, 0], [0, 0, 0, 0]]
        self.selected_rois = 0
        
        self.setWindowOpacity(0.3)
        if self.mode != 'view':
            QtWidgets.QApplication.setOverrideCursor(
                QtGui.QCursor(QtCore.Qt.CrossCursor)
            )
        self.setWindowFlags(QtCore.Qt.FramelessWindowHint)

    def paintEvent(self, event):
        qp = QtGui.QPainter(self)
        qp.setPen(QtGui.QPen(QtGui.QColor('black'), 3))
        qp.setBrush(QtGui.QColor(128, 128, 255, 128))

        # Draw ROIs
        if self.mode == 'view':
            # Load data from config
            self.rois = [config['rois']['left'], config['rois']['right']]
        
        if self.rois[0][0] > 0:
            left_column_pts = (
                QtCore.QPoint(*self.rois[0][:2]),
                QtCore.QPoint(*self.rois[0][2:]),
            )
            qp.drawRect(QtCore.QRect(*left_column_pts))
        
        if self.rois[1][0] > 0:
            right_column_pts = (
                QtCore.QPoint(*self.rois[1][:2]),
                QtCore.QPoint(*self.rois[1][2:]),
            )
            qp.drawRect(QtCore.QRect(*right_column_pts))
            
    def keyPressEvent(self, event: QtGui.QKeyEvent) -> None:
        if event.key() == Qt.Key_Escape:
            self.close()
            self.switch_window.emit()

    def mousePressEvent(self, event):
        if self.mode != 'view':
            self.selected_rois += 1
            if self.selected_rois == 1:
                pos = event.pos()
                x, y = pos.x(), pos.y()
                self.rois[0] = [x, y, x, y]
            elif self.selected_rois == 2:
                pos = event.pos()
                x, y = pos.x(), pos.y()
                self.rois[1] = [x, y, x, y]
                
            self.update()
        elif self.mode == 'view':
            self.close()
            self.switch_window.emit()

    def mouseMoveEvent(self, event):
        if self.mode != 'view':
            pos = event.pos()
            x, y = pos.x(), pos.y()
            if self.selected_rois == 1:
                self.rois[0][2:] = [x, y]
            elif self.selected_rois == 2:
                self.rois[1][2:] = [x, y]
            self.update()

    def mouseReleaseEvent(self, event):
        if self.mode != 'view':
            if self.selected_rois == 1:
                pos = event.pos()
                x, y = pos.x(), pos.y()
                self.rois[0][2:] = x, y
            elif self.selected_rois == 2:
                pos = event.pos()
                x, y = pos.x(), pos.y()
                self.rois[1][2:] = x, y
                # x1 = min(*self.rois[0][::2], *self.rois[1][::2])
                # y1 = min(*self.rois[0][1::2], *self.rois[1][1::2])
                # x2 = max(*self.rois[0][::2], *self.rois[1][::2])
                # y2 = max(*self.rois[0][1::2], *self.rois[1][1::2])

                # self.setGeometry(x1, y1, (x2 - x1), (y2 - y1))
                # Save config
                config['rois']['left'] = self.rois[0]
                config['rois']['right'] = self.rois[1]
                save_config(config)

                self.close()
                self.switch_window.emit()


class MainWindow(QtWidgets.QWidget):

    switch_window = QtCore.pyqtSignal()

    def __init__(self):
        QtWidgets.QWidget.__init__(self)
        self.setGeometry(100, 100, 300, 300)
        self.setupUi(self)

        self.select_button.clicked.connect(self.select_button_handler)
        self.view_button.clicked.connect(self.view_button_handler)
        self.start_button.clicked.connect(self.start_button_handler)
        
        self.is_started = False
        QtWidgets.QApplication.setOverrideCursor(
            QtGui.QCursor(QtCore.Qt.ArrowCursor)
        )
        
        # Update sums on GUI
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.update_sums)
        self.timer.start(50)
    
    def setupUi(self, Form):
        Form.setObjectName('Form')
        Form.resize(300, 300)
        g_layout = QtWidgets.QVBoxLayout()
        row_widget_1 = QtWidgets.QWidget()
        row_widget_2 = QtWidgets.QWidget()
        g_layout.addWidget(row_widget_1)
        g_layout.addWidget(row_widget_2)

        # Setup row 1
        layout_1 = QtWidgets.QHBoxLayout()
        row_widget_1.setLayout(layout_1)
        self.select_button = QtWidgets.QPushButton(Form)
        self.select_button.setObjectName('select_button')
        self.view_button = QtWidgets.QPushButton(Form)
        self.view_button.setText('View')
        self.start_button = QtWidgets.QPushButton(Form)
        self.start_button.setText('Start')

        layout_1.addStretch(1)
        layout_1.addWidget(self.select_button)
        layout_1.addStretch(1)
        layout_1.addWidget(self.view_button)
        layout_1.addStretch(1)
        layout_1.addWidget(self.start_button)
        
        # Setup row 2
        layout_2 = QtWidgets.QHBoxLayout()
        row_widget_2.setLayout(layout_2)
        left_widget = QtWidgets.QWidget()
        right_widget = QtWidgets.QWidget()
        layout_2.addWidget(left_widget)
        layout_2.addWidget(right_widget)
        
        self.values = {
            'bid': [],
            'ask': [],
        }
        left_layout = QtWidgets.QVBoxLayout()
        left_widget.setLayout(left_layout)
        right_layout = QtWidgets.QVBoxLayout()
        right_widget.setLayout(right_layout)

        for i in range(config['max_trace']):
            # Left
            left_row_widget = QtWidgets.QWidget()

            left_row_layout = QtWidgets.QHBoxLayout()
            if i == 0:
                left_row_layout.addWidget(QtWidgets.QLabel('Newest result: Bid: '))
            else:
                interval = config['interval']
                if isinstance(interval, float):
                    text = '{:.2f} seconds ago: Bid: '.format(interval * i)
                else:
                    text = '{:02d} seconds ago: Bid: '.format(interval * i)
                left_row_layout.addWidget(QtWidgets.QLabel(text))
            value_widget = QtWidgets.QLabel('0')
            self.values['bid'].append(value_widget)
            left_row_layout.addWidget(value_widget)

            left_row_widget.setLayout(left_row_layout)
            left_layout.addWidget(left_row_widget)
            
            # Right
            right_row_widget = QtWidgets.QWidget()

            right_row_layout = QtWidgets.QHBoxLayout()
            right_row_layout.addWidget(QtWidgets.QLabel('Ask:'))
            value_widget = QtWidgets.QLabel('0')
            self.values['ask'].append(value_widget)
            right_row_layout.addWidget(value_widget)

            right_row_widget.setLayout(right_row_layout)
            right_layout.addWidget(right_row_widget)
            
        self.setLayout(g_layout)

        # self.setWindowFlag(Qt.WindowCloseButtonHint, False)

        self.retranslateUi(Form)
        QtCore.QMetaObject.connectSlotsByName(Form)

    def retranslateUi(self, Form):
        _translate = QtCore.QCoreApplication.translate
        Form.setWindowTitle(_translate('Form', 'Form'))
        self.select_button.setText(_translate('Form', 'Select'))
    
    def update_sums(self):
        global sums
        with show_lock:
            # Update
            for col_name, values in sums.items():
                for i, value in enumerate(values):
                    self.values[col_name][i].setText(str(value))

    def select_button_handler(self):
        global mode
        mode = 'select'
        self.switch_window.emit()
    
    def view_button_handler(self):
        global mode
        mode = 'view'
        self.switch_window.emit()

    def start_button_handler(self):
        if not self.is_started:
            ready_event.set()
            
            config = load_config()

            # Extract data
            pool = QThreadPool.globalInstance()
            runnable = OCRWorker(config['rois']['left'], config['rois']['right'], config['interval'])
            pool.start(runnable)
            self.is_started = True
    
    def closeEvent(self, event):
        ready_event.clear()
        terminate_event.set()
        self.close()


class ActivateWindow(QtWidgets.QWidget):

    switch_window = QtCore.pyqtSignal()
    def __init__(self, message):
        QtWidgets.QWidget.__init__(self)
        self.setGeometry(300, 300, 600, 100)
        self.message = message
        self.setupUi(self)

        self.activate_button.clicked.connect(self.activate_button_handler)
        self.activate_input_box.textChanged.connect(self.text_changed_handler)
    
    def setupUi(self, Form):
        Form.setObjectName('Form')
        Form.resize(600, 100)
        
        g_layout = QtWidgets.QVBoxLayout()
        row_widget_1 = QtWidgets.QLabel()
        row_widget_2 = QtWidgets.QWidget()
        g_layout.addWidget(row_widget_1)
        g_layout.addWidget(row_widget_2)
        row_widget_2_layout = QtWidgets.QHBoxLayout()
        row_widget_2.setLayout(row_widget_2_layout)
        
        self.activate_input_box = QtWidgets.QLineEdit()
        font = self.activate_input_box.font()
        font.setPointSize(10)
        self.activate_input_box.setFont(font)
        # self.activate_input_box.setMaxLength(1000)
        # self.activate_input_box.setMaximumWidth(1000)
        self.activate_button = QtWidgets.QPushButton()
        self.activate_button.setObjectName('activate_button')
        self.activate_status = QtWidgets.QLabel()
        row_widget_2_layout.addWidget(self.activate_input_box)
        row_widget_2_layout.addSpacing(10)
        row_widget_2_layout.addWidget(self.activate_status)
        row_widget_2_layout.addSpacing(50)
        row_widget_2_layout.addWidget(self.activate_button)
        self.setLayout(g_layout)
        
        row_widget_1.setText(self.message)
        self.activate_input_box.setPlaceholderText('XXXXXX-XXXXXX-XXXXXX-XXXXXX-XXXXXX-XXXXXX')
        self.retranslateUi(self)
    
    def retranslateUi(self, Form):
        _translate = QtCore.QCoreApplication.translate
        Form.setWindowTitle(_translate('Form', 'Activate'))
        self.activate_button.setText(_translate('Form', 'Activate'))
        self.activate_input_box.setFixedSize(330, 25)
        self.activate_button.setFixedSize(60, 30)
    
    def text_changed_handler(self):
        curr_text = self.activate_input_box.text()
        self.activate_status.setText('')
    
    def activate_button_handler(self):
        license_key = self.activate_input_box.text()
        try:
            LexActivator.SetLicenseKey(license_key)
        except Exception as e:
            logger.exception(f'Failed when set license key: {e}')
            self.activate_status.setText('Failed')
            self.activate_status.setStyleSheet('color: red')
            return

        status = LexActivator.ActivateLicense()
        if LexStatusCodes.LA_OK == status or LexStatusCodes.LA_EXPIRED == status or LexStatusCodes.LA_SUSPENDED == status:
            self.switch_window.emit()
            self.close()
        else:
            self.activate_status.setText('failed')
            self.activate_status.setStyleSheet('color: red')


class Controller:
    def __init__(self):
        self.roi_selector = None
        self.window = None
        self.activate_window = None
        self.is_startup = True

    def show_roi_selector(self):
        self.roi_selector = ROISelector()
        self.roi_selector.switch_window.connect(self.show_main)
        self.roi_selector.show()
        if self.window is not None:
            self.window.hide()

    def show_main(self):
        self.window = MainWindow()
        self.window.switch_window.connect(self.show_roi_selector)
        if self.roi_selector is not None:
            self.roi_selector.close()
        
        if self.activate_window is not None:
            self.activate_window.close()
        self.window.show()
    
    def show_activate(self):
        # Initialize license verification
        LexActivator.SetProductFile('product_v5b67c9c8-4094-4f55-b3d3-fd1227899e1a.dat')
        LexActivator.SetProductId(
            '5b67c9c8-4094-4f55-b3d3-fd1227899e1a', PermissionFlags.LA_USER)
        
        # License verification
        activate_required = True
        activate_message = ''
        status = LexActivator.IsLicenseGenuine()
        if status == LexStatusCodes.LA_OK:
            expiry_date = LexActivator.GetLicenseExpiryDate()
            days_left = (expiry_date - time.time()) / 86400
            username = LexActivator.GetLicenseUserName()
            logger.info(f'License user: {username}')
            logger.info('License is genuinely activated!')
            activate_required = False
        elif LexStatusCodes.LA_EXPIRED == status:
            logger.error('License is genuinely activated but has expired!')
            activate_required = True
            activate_message = 'License is genuinely activated but has expired!'
        elif LexStatusCodes.LA_SUSPENDED == status:
            logger.error('License is genuinely activated but has been suspended!')
            activate_required = True
            activate_message = 'License is genuinely activated but has been suspended!'
        elif LexStatusCodes.LA_GRACE_PERIOD_OVER == status:
            logger.error('License is genuinely activated but grace period is over!')
            activate_message = 'License is genuinely activated but grace period is over!'
            activate_required = True
        else:
            trial_status = LexActivator.IsTrialGenuine()
            if LexStatusCodes.LA_OK == trial_status:
                trial_expiry_date = LexActivator.GetTrialExpiryDate()
                days_left = (trial_expiry_date - time.time()) / 86400
                logger.info('Trial days left: ', days_left)
                activate_required = False
            elif LexStatusCodes.LA_TRIAL_EXPIRED == trial_status:
                logger.info('Trial has expired!')
                # Time to buy the license and activate the app
                activate_message = 'The trial has expired. Please visit https://buyit.com to get activation key!'
                activate_required = True
            else:
                try:
                    status = LexActivator.ActivateTrial()
                    if LexStatusCodes.LA_OK == status:
                        logger.info("Product trial activated successfully!")
                        activate_required = False
                    elif LexStatusCodes.LA_TRIAL_EXPIRED == status:
                        logger.info("Product trial has expired")
                        activate_message = 'The trial has expired. Please visit https://buyit.com to get activation key!'
                        activate_required = True
                    else:
                        logger.info("Product trial has failed")
                        activate_message = 'The trial has failed. Please visit https://buyit.com to get activation key!'
                        activate_required = True
                except Exception as e:
                    logger.error(f'Trial activation has failed')
                    activate_message = 'The trial activation has failed. Please visit https://buyit.com to get activation key!'
                    activate_required = True

        if activate_required:
            self.activate_window = ActivateWindow(activate_message)
            self.activate_window.switch_window.connect(self.show_main)
            self.activate_window.show()
        else:
            self.show_main()


def main():
    app = QtWidgets.QApplication(sys.argv)
    controller = Controller()
    controller.show_activate()
    sys.exit(app.exec_())


if __name__ == '__main__':
    main()