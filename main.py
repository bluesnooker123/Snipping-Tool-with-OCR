"""L2-easy application

The application uses Tesseract to extract bid and ask values in real time.
"""
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
from PIL import ImageGrab
from cryptlex.lexactivator import LexActivator, LexStatusCodes, PermissionFlags

from ocr_utils import extract_data


# Default config if not found config.yaml
default_config = {
    'logfile': 'app.log',
    'debug': False,
    'time_periods': [1, 5, 20, 60],
    'interval': 0.5,
    'rois': {
        'left': [0, 0, 0, 0],
        'right': [0, 0, 0, 0]
    }
}


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


# Load global config
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
# Ready event is used to notice the extraction thread starts
ready_event = threading.Event()

# Notice the extraction thread stops
terminate_event = threading.Event()
ready_event.clear()
terminate_event.clear()

# Control access to shared `sums` variable
show_lock = threading.Lock()
sums = {
    'bid': deque([0] * (len(config['time_periods']) + 1), maxlen=(len(config['time_periods']) + 1)),
    'ask': deque([0] * (len(config['time_periods']) + 1), maxlen=(len(config['time_periods']) + 1)),
}

# The application mode: ['view']
mode = None


class OCRWorker(QRunnable):
    def __init__(self, pts1, pts2, interval=1):
        """OCR worker thread. This thread extracts data from the given region of interest
        on screen.
        
        Args
        :pts1: (x1, y1, x2, y2) Region of interest of Bid column
        :pts2: (x1, y1, x2, y2) Region of interest of Ask column
        
        Attributes
        :debug: Enable debug mode if true
        :conf_thresh: Tesseract confidence thresh
        :inputs: A dict stores the above RoIs
        """
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
        """Post process the given results.
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
        """Extract bid and ask values from the input RoIs"""
        global show_lock, sums
        while True:
            # Check terminate signal
            if terminate_event.wait(0.01):
                break
            
            # Check ready signal
            if not ready_event.wait(self.interval):
                continue
                        
            # Start to capture screen and extract data
            results = {}
            for col_name, roi in self.inputs.items():
                x1, y1, x2, y2 = roi
                try:
                    # Crop RoI
                    img = ImageGrab.grab((x1, y1, x2, y2))
                    if self.debug:
                        filename = f'roi_{col_name}.png'
                        img.save(filename)
                        logger.debug('Dump image as {}'.format(filename))
                    
                    # Extract data actually
                    col_result = extract_data(img, self.conf_thresh, col_name, self.debug)
                except Exception as e:
                    logger.error(f'Error while extracting data: {e}')
                    continue
                
                # Sorted by y-axis
                col_result = sorted(col_result, key=lambda x: x[1])
                results[col_name] = col_result

            # Post-processing
            if len(results) > 0:
                with show_lock:
                    # Take sum of each column
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
        """Popup window helps to select bid and ask column.
        
        Attributes
        :is_selected: The state.
        :mode: 'view' or 'selecting'?
        :rois: Stores coordinates of the 2 RoIs
        :selected_rois: Number of RoIs are selected.
        """
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

                # Save config
                config['rois']['left'] = self.rois[0]
                config['rois']['right'] = self.rois[1]
                save_config(config)

                self.close()
                self.switch_window.emit()


class MainWindow(QtWidgets.QWidget):

    switch_window = QtCore.pyqtSignal()

    def __init__(self):
        """
        """
        QtWidgets.QWidget.__init__(self)
        self.setGeometry(400, 400, 300, 300)
        self.text_len = 13
        self.setupUi(self)
        
        # Step counter
        self.step_cnt = 0
        self.steps = [int(x) for x in config['time_periods']]
        self.history = {}
        for period in config['time_periods']:
            max_len = int(period)
            self.history[period] = {
                'bid': deque([0] * max_len, maxlen=max_len),
                'ask': deque([0] * max_len, maxlen=max_len),
            }

        self.select_button.clicked.connect(self.select_button_handler)
        self.view_button.clicked.connect(self.view_button_handler)
        self.start_button.clicked.connect(self.start_button_handler)
        self.stop_button.clicked.connect(self.stop_button_handler)
        
        self.is_started = False
        QtWidgets.QApplication.setOverrideCursor(
            QtGui.QCursor(QtCore.Qt.ArrowCursor)
        )
        
        self.setWindowFlags(QtCore.Qt.WindowStaysOnTopHint)
    
    def setupUi(self, Form):
        Form.setObjectName('Form')
        Form.resize(70, 300)
        g_layout = QtWidgets.QVBoxLayout()
        row_widget_1 = QtWidgets.QWidget()
        row_widget_2 = QtWidgets.QWidget()
        g_layout.addWidget(row_widget_1)
        g_layout.addWidget(row_widget_2)

        # Setup row 1
        layout_1 = QtWidgets.QGridLayout()
        row_widget_1.setLayout(layout_1)
        self.select_button = QtWidgets.QPushButton(Form)
        self.select_button.setObjectName('select_button')
        self.view_button = QtWidgets.QPushButton(Form)
        self.view_button.setText('View')
        self.start_button = QtWidgets.QPushButton(Form)
        self.start_button.setText('Start')
        self.stop_button = QtWidgets.QPushButton(Form)
        self.stop_button.setText('Stop')

        layout_1.addWidget(self.select_button, 0, 0)
        layout_1.addWidget(self.view_button, 0, 1)
        layout_1.addWidget(self.start_button, 1, 0)
        layout_1.addWidget(self.stop_button, 1, 1)
        
        # Setup row 2
        row_widget_2_layout = QtWidgets.QHBoxLayout()
        row_widget_2.setLayout(row_widget_2_layout)

        label_widget = QtWidgets.QWidget()
        label_widget_layout = QtWidgets.QVBoxLayout()
        label_widget.setLayout(label_widget_layout)
        row_widget_2_layout.addWidget(label_widget)

        bid_widget = QtWidgets.QWidget()
        bid_widget_layout = QtWidgets.QVBoxLayout()
        bid_widget.setLayout(bid_widget_layout)
        row_widget_2_layout.addWidget(bid_widget)
        
        value_widget = QtWidgets.QWidget()
        value_widget_layout = QtWidgets.QVBoxLayout()
        value_widget.setLayout(value_widget_layout)
        row_widget_2_layout.addWidget(value_widget)
        
        ask_widget = QtWidgets.QWidget()
        ask_widget_layout = QtWidgets.QVBoxLayout()
        ask_widget.setLayout(ask_widget_layout)
        row_widget_2_layout.addWidget(ask_widget)
        
        self.values = []  # Store these widgets to update later
        
        # Initialize number of widgets as the same as number of periods + 1
        periods = [0] + config['time_periods']
        for i, period in enumerate(periods):
            # Label column
            if i == 0:
                label_widget_layout.addWidget(QtWidgets.QLabel('Newest'))
            else:
                if period < 60:
                    text = '{:<8}'.format('%s sec.' % period)
                else:
                    if period % 60 == 0:
                        text = '{:<8}'.format('%d min.' % (period // 60))
                    else:
                        text = '{:<8}'.format('%.2f min.' % (period / 70))
                label_widget_layout.addWidget(QtWidgets.QLabel(text))

            # Bid column
            bid_widget_layout.addWidget(QtWidgets.QLabel('Bid'))
            bid_widget_layout.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
            
            # Value column
            if i == 0:
                left_text = ' ' * self.text_len
                right_text = ' ' * self.text_len
                text = '{} {}'.format(left_text, right_text)
            else:
                left_text = ' ' * self.text_len
                right_text = ' ' * self.text_len
                text = '{} {}'.format(left_text, right_text)
            widget = QtWidgets.QLabel(text)
            self.values.append(widget)
            value_widget_layout.addWidget(widget)
            
            # Ask column
            label = QtWidgets.QLabel('Ask')
            label.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
            ask_widget_layout.addWidget(label)
            
        self.setLayout(g_layout)
        self.retranslateUi(Form)
        QtCore.QMetaObject.connectSlotsByName(Form)

    def retranslateUi(self, Form):
        _translate = QtCore.QCoreApplication.translate
        Form.setWindowTitle(_translate('Form', 'L2-easy'))
        self.select_button.setText(_translate('Form', 'Select'))
    
    def update_sums(self):
        global sums
        with show_lock:
            # Update history
            for i, period in enumerate(self.history, 1):
                self.history[period]['bid'].append(sums['bid'][i])
                self.history[period]['ask'].append(sums['ask'][i])
            
            self.step_cnt += 1
            bid_data = sums['bid']
            ask_data = sums['ask']
            
            # Set first column text
            if bid_data[0] > 0 and ask_data[0] > 0:
                bid_text = '{label:<{n}}'.format(label='%d' % bid_data[0], n=self.text_len)
                ask_text = '{label:>{n}}'.format(label='%d' % ask_data[0], n=self.text_len)
                text = '{} {}'.format(bid_text, ask_text)
                self.values[0].setText(text)
            
            for i, period in enumerate(config['time_periods'], 1):
                if self.step_cnt % period == 0:
                    acc_bid = sum(self.history[period]['bid'])
                    acc_ask = sum(self.history[period]['ask'])
                    if acc_bid == 0 or acc_ask == 0:
                        bid_text = ' ' * self.text_len
                        ask_text = ' ' * self.text_len
                        text = '{} {}'.format(bid_text, ask_text)
                        self.values[i].setText(text)
                        continue

                    if acc_bid > acc_ask:
                        bid_text = '{label:>{n}}'.format(label='%.2f' % (acc_bid / acc_ask), n=self.text_len)
                        ask_text = '{label:<{n}}'.format(label='1', n=self.text_len)
                    elif acc_ask > acc_bid:
                        ask_text = '{label:<{n}}'.format(label='%.2f' % (acc_ask / acc_bid), n=self.text_len)
                        bid_text = '{label:>{n}}'.format(label='1', n=self.text_len)
                    else:
                        bid_text = '{label:>{n}}'.format(label='1', n=self.text_len)
                        ask_text = '{label:<{n}}'.format(label='1', n=self.text_len)
                    text = '{} : {}'.format(bid_text, ask_text)
                    self.values[i].setText(text)
        
        # Reset
        if self.step_cnt == self.steps[-1]:
            self.step_cnt = 0

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
            terminate_event.clear()
            
            config = load_config()
            
            # Update sums on GUI
            self.timer = QtCore.QTimer(self)
            self.timer.timeout.connect(self.update_sums)
            self.timer.start(config['interval'] * 1000)

            # Extract data
            self.pool = QThreadPool.globalInstance()
            runnable = OCRWorker(config['rois']['left'], config['rois']['right'], config['interval'])
            self.pool.start(runnable)
            self.is_started = True
            
            # Disable view
            self.start_button.setEnabled(False)
            self.view_button.setEnabled(False)
            self.select_button.setEnabled(False)

    def stop_button_handler(self):
        # Reset UI
        for i, widget in enumerate(self.values):
            left_text = ' ' * (self.text_len + 4)
            right_text = ' ' * (self.text_len + 4)
            text = '{} {}'.format(left_text, right_text)
            widget.setText(text)
        
        ready_event.clear()
        terminate_event.set()
        self.is_started = False
        self.view_button.setEnabled(True)
        self.select_button.setEnabled(True)
        self.start_button.setEnabled(True)
        self.timer.stop()
        self.step_cnt = 0
    
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

        try:
            status = LexActivator.ActivateLicense()
            if LexStatusCodes.LA_OK == status or LexStatusCodes.LA_EXPIRED == status or LexStatusCodes.LA_SUSPENDED == status:
                self.switch_window.emit()
                self.close()
            else:
                self.activate_status.setText('failed')
                self.activate_status.setStyleSheet('color: red')
        except Exception as e:
            logger.error(f'Failed when activate license: {e}')
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
                activate_message = 'The trial has expired. Please visit https://market-lv2data.com to get activation key!'
                activate_required = True
            else:
                try:
                    status = LexActivator.ActivateTrial()
                    if LexStatusCodes.LA_OK == status:
                        logger.info("Product trial activated successfully!")
                        activate_required = False
                    elif LexStatusCodes.LA_TRIAL_EXPIRED == status:
                        logger.info("Product trial has expired")
                        activate_message = 'The trial has expired. Please visit https://market-lv2data.com to get activation key!'
                        activate_required = True
                    else:
                        logger.info("Product trial has failed")
                        activate_message = 'The trial has failed. Please visit https://market-lv2data.com to get activation key!'
                        activate_required = True
                except Exception as e:
                    logger.error(f'Trial activation has failed')
                    activate_message = 'The trial activation has failed. Please visit https://market-lv2data.com to get activation key!'
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
