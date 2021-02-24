#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GUI interface to camera runner.
"""

import os
import sys
import textwrap
import functools
from PyQt5.QtGui import *
from PyQt5.QtCore import *
from PyQt5.QtWidgets import *
from FlyCaptureUtils import (Camera, img2array, getAvailableCameras,
                             imgSize_from_vidMode, VIDEO_MODES, FRAMERATES,
                             GRAB_MODES, PIXEL_FORMATS)

# Assorted default parameters
DEFAULTS = {'cam_mode':'Multi',
            'video_mode':'VM_640x480RGB',
            'framerate':'FR_30',
            'grab_mode':'BUFFER_FRAMES',
            'preview':Qt.Unchecked,
            'pixel_format':'RGB',
            'save_output':Qt.Checked,
            'output_encoder':'Auto',
            'output_format':'Auto',
            'overwrite':Qt.Unchecked,
            'save_timestamps':Qt.Checked,
            'mjpg_quality':75,
            'h264_bitrate':1e6,
            'h264_size':'Auto',
            'embedded_info':{'timestamp':Qt.Checked,
                             'gain':Qt.Unchecked,
                             'shutter':Qt.Unchecked,
                             'brightness':Qt.Unchecked,
                             'exposure':Qt.Unchecked,
                             'whiteBalance':Qt.Unchecked,
                             'frameCounter':Qt.Unchecked,
                             'strobePattern':Qt.Unchecked,
                             'ROIPosition':Qt.Unchecked} }

# Supported PyCapture2 pixel formats (i.e. those which can be converted
# to a PyQt QImage format)
SUPPORTED_PIXEL_FORMATS = ['MONO8','RGB','RGB8','RGB16']


### Utility functions ###

def convert_pixel_format(pixel_format):
    """
    Convery PyCapture2 pixel format into PyQt QImage format. Only some pixel
    formats are supported (see SUPPORTED_PIXEL_FORMATS list). Other formats
    will raise an error.

    Parameters
    ----------
    pixel_format : str
        PyCapture2.PIXEL_FORMAT code or key for PIXEL_FORMATS lookup dict.

    Returns
    -------
    qimage_format : int
        QImage format code
    """
    # If code, lookup name from dict
    if isinstance(pixel_format, int):
        pixel_format = [k for k,v in PIXEL_FORMATS.items() if v == pixel_format]
        if len(pixel_format) > 1:
            raise RuntimeError('Multiple matching pixel format codes')
        pixel_format = pixel_format[0]

    # Match with qimage format
    if pixel_format == 'MONO8':
        return QImage.Format_Grayscale8
    elif pixel_format in ['RGB','RGB8']:
        return QImage.Format_RGB888
    elif pixel_format == 'RGB16':
        return QImage.Format_RGB16
    else:
        raise ValueError(f'No PyQt conversion for {pixel_format} format')

def error_dlg(parent, msg, title='Error', icon=QMessageBox.Critical):
    """
    Return error dialog box
    """
    dlg = QMessageBox(parent)
    dlg.setWindowTitle(title)
    dlg.setIcon(icon)
    dlg.setText(msg)
    return dlg

def format_tooltip(text, *args, **kwargs):
    """
    Wrapper around textwrap.fill that preserves newline characters
    """
    return '\n'.join(textwrap.fill(t, *args, **kwargs) \
                     for t in text.splitlines())

def BoldQLabel(text):
    """
    Return QLabel formatted in bold
    """
    font = QFont()
    font.setBold(True)
    label = QLabel(text)
    label.setFont(font)
    return label

def errorHandler(func):
    """
    Decorator for handling errors in MainWindow GUI. Need to define outside
    of class, but should only be used for MainWindow class.

    If error encountered will trigger window's stop method, close preview
    window (if applicable) and display the error in dialogue.

    If using to decorate a slot, the method must first by decorated with the
    @pyqtSlot() decorator to prevent the slot args being passed to this
    decorator.
    """
    # functools.wraps is used to make sure names and docstrings etc are
    # assigned properly from given func, and also seems to be needed to
    # prevent decorator swallowing function output (e.g. printed output
    # disappears, and preview window can't be opened otherwise?)
    @functools.wraps(func)
    def wrapper(self, *args, **kwargs):
        try:
            return func(self, *args, **kwargs)
        except Exception as e:
            errValue = str(e)
            errType = str(type(e).__name__)
            self.on_stop()
            self.close_preview()
            error_dlg(self, errValue, errType).exec_()
    return wrapper


### Main class definitions ###
class MainWindow(QMainWindow):
    def __init__(self):
        """
        Main window for selecting camera and output settings, and running
        camera acquisition.
        """
        super().__init__()

        # Find available cameras
        self.AVAILABLE_CAMERAS = getAvailableCameras()

        # Init gui
        self.initUI()
        self.show()

        # Display warning if no cameras found
        if not self.AVAILABLE_CAMERAS:
            error_dlg(self, 'No cameras found!', 'Warning',
                      QMessageBox.Warning).exec_()

    ## Initialisation functions for GUI elements ##
    def initUI(self):
        """
        Initialise user interface
        """
        # Init central widget
        self.centralWidget = QWidget()
        self.setCentralWidget(self.centralWidget)

        # Init window
        self.resize(600, 700)
        self.setWindowTitle('Camera Runner')

        # Init main grid layout
        grid = QGridLayout()
        self.centralWidget.setLayout(grid)

        # Add selectCamsGroup
        self.initSelectCamsGroup()
        grid.addWidget(self.selectCamsGroup, 0, 0)

        # Add optsGroup
        self.initOptsGroup()
        grid.addWidget(self.optsGroup, 0, 1)

        # Add outputGroup
        self.initOutputGroup()
        grid.addWidget(self.outputGroup, 1, 0, 1, 2)

        # Add statusGroup
        self.initStatusGroup()
        grid.addWidget(self.statusGroup, 2, 0, 1, 2)

        # Add buttons
        hbox = QHBoxLayout()
        hbox.addStretch(1)

        self.connectBtn = QPushButton('Connect')
        self.connectBtn.clicked.connect(self.on_connect)
        self.connectBtn.setToolTip('Connect to camera(s)')
        hbox.addWidget(self.connectBtn)

        self.startBtn = QPushButton('Start')
        self.startBtn.clicked.connect(self.on_start)
        self.startBtn.setToolTip('Start video capture')
        self.startBtn.setEnabled(False)
        hbox.addWidget(self.startBtn)

        self.stopBtn = QPushButton('Stop')
        self.stopBtn.clicked.connect(self.on_stop)
        self.stopBtn.setToolTip('Stop video capture')
        self.stopBtn.setEnabled(False)
        hbox.addWidget(self.stopBtn)

        self.exitBtn = QPushButton('Exit')
        self.exitBtn.clicked.connect(self.on_exit)
        self.exitBtn.setToolTip('Exit application')
        hbox.addWidget(self.exitBtn)

        grid.addLayout(hbox, 3, 0, 1, 2)

    def initSelectCamsGroup(self):
        """
        Initialise group box for camera selection.
        """
        # Init group and vbox
        self.selectCamsGroup = QGroupBox('Select Cameras')
        group_vbox = QVBoxLayout()

        # Add camera mode dropdown
        hbox = QHBoxLayout()
        hbox.addWidget(QLabel('Camera mode'))
        self.camMode = QComboBox()
        self.camMode.addItems(['Single', 'Multi'])
        self.camMode.setCurrentText(DEFAULTS['cam_mode'])
        self.camMode.currentTextChanged.connect(self.on_camera_mode_change)
        self.camMode.setToolTip('Acquire images from one or multiple cameras')
        hbox.addWidget(self.camMode)
        hbox.addStretch(1)
        group_vbox.addLayout(hbox)

        # Add camera select table
        self.cameraTable = QTableWidget(len(self.AVAILABLE_CAMERAS), 3)

        self.cameraTable.setHorizontalHeaderLabels([None,'Camera','Serial'])
        header = self.cameraTable.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        self.cameraTable.verticalHeader().setVisible(False)

        for row, (cam_num, serial) in enumerate(self.AVAILABLE_CAMERAS):
            chk = QTableWidgetItem()
            chk.setCheckState(Qt.Checked)

            txt1 = QTableWidgetItem(str(cam_num))
            txt1.setFlags(Qt.ItemIsEnabled)
            txt2 = QTableWidgetItem(str(serial))
            txt2.setFlags(Qt.ItemIsEnabled)

            self.cameraTable.setItem(row, 0, chk)
            self.cameraTable.setItem(row, 1, txt1)
            self.cameraTable.setItem(row, 2, txt2)

        self.cameraTable.cellClicked.connect(self.on_camera_check)

        self.cameraTable.setToolTip('Select camera(s) to use')

        self.set_camTable_selectivity()

        group_vbox.addWidget(self.cameraTable)

        # Update group
        self.selectCamsGroup.setLayout(group_vbox)

    def initOptsGroup(self):
        """
        Initialise group box for camera settings
        """
        # Init group and grid
        self.optsGroup = QGroupBox('Camera Options')
        form = QFormLayout()

        # Add widgets
        self.vidMode = QComboBox()
        self.vidMode.addItems(VIDEO_MODES.keys())
        self.vidMode.setCurrentText(DEFAULTS['video_mode'])
        self.vidMode.setToolTip('Camera resolution and colour mode')
        form.addRow('Video mode', self.vidMode)

        self.framerate = QComboBox()
        self.framerate.addItems(FRAMERATES.keys())
        self.framerate.setCurrentText(DEFAULTS['framerate'])
        self.framerate.setToolTip('Camera frame rate')
        form.addRow('Framerate', self.framerate)

        self.grabMode = QComboBox()
        self.grabMode.addItems(GRAB_MODES.keys())
        self.grabMode.setCurrentText(DEFAULTS['grab_mode'])
        self.grabMode.setToolTip(format_tooltip(
            'If BUFFER_FRAMES, read oldest frame out of buffer. Frames are '
            'not lost, but computer must keep up to avoid buffer overflows.'
            '\n\n'
            'If DROP_FRAMES, read newest frame out of buffer. Older frames '
            'will be lost if computer falls behind.'
            ))
        form.addRow('Grab mode', self.grabMode)

        self.saveOutput = QCheckBox()
        self.saveOutput.stateChanged.connect(self.on_save_output_check)
        self.saveOutput.setCheckState(DEFAULTS['save_output'])
        self.saveOutput.setToolTip('Enable/disable Output Options dialog')
        form.addRow('Save video', self.saveOutput)

        self.preview = QCheckBox()
        self.preview.setCheckState(DEFAULTS['preview'])
        self.preview.setToolTip(
            'Display live video preview.\n'
            'Only available for single-camera operation.'
            )
        form.addRow('Preview', self.preview)

        self.pixelFormat = QComboBox()
        self.pixelFormat.addItems(SUPPORTED_PIXEL_FORMATS)
        self.pixelFormat.setCurrentText(DEFAULTS['pixel_format'])
        self.pixelFormat.setToolTip(
            'Colour mode for display: must be appropriate for video mode.\n'
            'Only available for single-camera operation.'
            )
        form.addRow('Pixel format', self.pixelFormat)

        if self.camMode.currentText() == 'Multi':
            self.preview.setEnabled(False)
            self.pixelFormat.setEnabled(False)


        # Update group
        self.optsGroup.setLayout(form)

    def initOutputGroup(self):
        """
        Initialise group box for output settings
        """
        # Init group and vbox
        self.outputGroup = QGroupBox('Output Options')
        self.outputGroup.setEnabled(self.saveOutput.isChecked())

        group_vbox = QVBoxLayout()

        ## File select
        vbox = QVBoxLayout()
        vbox.addWidget(BoldQLabel('File select'), Qt.AlignLeft)

        hbox = QHBoxLayout()
        self.outputFile = QLineEdit()
        self.outputFile.setToolTip(format_tooltip(
            'Base filepath to desired output file. If camera mode is Multi '
            'then camera numbers will be appended to filename. File '
            'extension can be added automatically if an output encoder is '
            'specified.'
            ))
        hbox.addWidget(self.outputFile)
        btn = QPushButton('Browse')
        btn.clicked.connect(self.on_fileselect_browse)
        hbox.addWidget(btn)
        vbox.addLayout(hbox)

        group_vbox.addLayout(vbox)
        group_vbox.addSpacing(10)

        ## Opts
        opts_hbox = QHBoxLayout()

        # General Opts
        form = QFormLayout()
        form.addRow(BoldQLabel('General Options'))

        self.outputEncoder = QComboBox()
        self.outputEncoder.addItems(['Auto','AVI','MJPG','H264'])
        self.outputEncoder.setCurrentText(DEFAULTS['output_encoder'])
        self.outputEncoder.setToolTip(format_tooltip(
            'Writer format. If Auto, will attempt to determine from '
            'filename extension, or will error if no extension provided.'
            ))
        form.addRow('Encoder', self.outputEncoder)

        self.outputOverwrite = QCheckBox()
        self.outputOverwrite.setCheckState(DEFAULTS['overwrite'])
        self.outputOverwrite.setToolTip('Overwrite file if it already exists')
        form.addRow('Overwrite', self.outputOverwrite)

        self.outputSaveTimestamps = QCheckBox()
        self.outputSaveTimestamps.setCheckState(DEFAULTS['save_timestamps'])
        self.outputSaveTimestamps.setToolTip(
            'Save timestamps for each frame to a corresponding CSV file'
            )
        form.addRow('Timestamps CSV', self.outputSaveTimestamps)

        opts_hbox.addLayout(form)
        opts_hbox.addStretch(1)

        # MJPG & H264 options
        vbox = QVBoxLayout()

        mjpg_form = QFormLayout()
        lab = BoldQLabel('MJPG Options')
        lab.setToolTip('Options applicable only for MJPG format')
        mjpg_form.addRow(lab)

        self.outputQuality = QSpinBox()
        self.outputQuality.setRange(0, 100)
        self.outputQuality.setValue(DEFAULTS['mjpg_quality'])
        self.outputQuality.setToolTip('Video quality (value between 0 and 100)')
        mjpg_form.addRow('Quality', self.outputQuality)

        h264_form = QFormLayout()
        lab = BoldQLabel('H264 Options')
        lab.setToolTip('Options applicable only for H264 format')
        h264_form.addRow(lab)

        self.outputBitrate = QSpinBox()
        self.outputBitrate.setRange(0, 2**31-1)
        self.outputBitrate.setSingleStep(1000)
        self.outputBitrate.setValue(DEFAULTS['h264_bitrate'])
        self.outputBitrate.setToolTip('Bitrate (in bits per second)')
        h264_form.addRow('Bitrate', self.outputBitrate)

        self.outputSize = QLineEdit()
        self.outputSize.setText(DEFAULTS['h264_size'])
        self.outputSize.setToolTip(format_tooltip(
            'Image width and height in pixels, specified as (W,H) tuple '
            '(including brackets). Must match resolution specified in video '
            'mode. If Auto, will attempt to determine from video mode.'
            ))
        h264_form.addRow('Image Size', self.outputSize)

        vbox.addLayout(mjpg_form)
        vbox.addSpacing(10)
        vbox.addLayout(h264_form)
        vbox.addStretch(1)

        opts_hbox.addLayout(vbox)
        opts_hbox.addStretch(1)

        # Embedded image info options
        form = QFormLayout()
        lab = BoldQLabel('Embed Image Info')
        lab.setToolTip(format_tooltip(
            'Information to be embedded in top-left image pixels. To be '
            'usable, video mode must be set to monochrome.'
            ))
        form.addRow(lab)

        self.outputEmbeddedImageInfo = {}
        for prop, prop_default in DEFAULTS['embedded_info'].items():
            widget = QCheckBox()
            widget.setCheckState(prop_default)
            self.outputEmbeddedImageInfo[prop] = widget
            form.addRow(prop, widget)

        opts_hbox.addLayout(form)

        # Add options to main vbox
        group_vbox.addLayout(opts_hbox)

        # Add stretch below
        group_vbox.addStretch(1)

        # Update group
        self.outputGroup.setLayout(group_vbox)

    def initStatusGroup(self):
        """
        Initialise group box for status message.
        """
        self.statusGroup = QGroupBox('Status')

        self.statusText = QLabel()
        self.statusText.setAlignment(Qt.AlignCenter)
        font = self.statusText.font()
        font.setPointSize(16)
        self.statusText.setFont(font)
        self.set_status('Disconnected', 'red')

        layout = QHBoxLayout()
        layout.addWidget(self.statusText)

        self.statusGroup.setLayout(layout)


    ## Internal utility functions for handling gui and camera operation ##
    def set_status(self, text, color=None):
        """
        Update status text, and optionally the colour
        """
        self.statusText.setText(text)
        if color:
            self.statusText.setStyleSheet('QLabel {color:' + color + '}')

    def set_camTable_selectivity(self, row=0):
        """
        Sets whether one or multiple cameras in table may be selected,
        dependent on camera mode
        """
        if self.camMode.currentText() == 'Single':
            for rowN in range(self.cameraTable.rowCount()):
                chk = QTableWidgetItem()
                if rowN == row:
                    chk.setCheckState(Qt.Checked)
                else:
                    chk.setCheckState(Qt.Unchecked)
                self.cameraTable.setItem(rowN, 0, chk)

    def close_preview(self):
        """
        If preview window open, close it and remove handle from class
        """
        if hasattr(self, 'preview_window'):
            self.preview_window.close()
            delattr(self, 'preview_window')

    def extract_settings(self):
        """
        Extract current settings. Dict of values assigned into .SETTINGS
        attribute.
        """
        # Misc values
        cam_mode = self.camMode.currentText()
        preview = self.preview.isEnabled() and self.preview.isChecked()
        pixel_format = self.pixelFormat.currentText()

        # Cam nums
        cam_nums = []
        for rowN in range(self.cameraTable.rowCount()):
            use_cam = self.cameraTable.item(rowN, 0).checkState() == Qt.Checked
            cam_num = int(self.cameraTable.item(rowN, 1).text())
            if use_cam:
                cam_nums.append(cam_num)

        if cam_mode == 'Single' and len(cam_nums) > 1:
            raise Exception('Cannot have more than one camera for single '
                            'camera operation')

        # Cam kwargs
        cam_kwargs = {'video_mode':self.vidMode.currentText(),
                      'framerate':self.framerate.currentText(),
                      'grab_mode':self.grabMode.currentText()}

        # Output video and writer kwargs
        if self.saveOutput.isChecked():
            outfile = self.outputFile.text()

            # Error if no outfile provided
            if not outfile:
                raise Exception('Must specify file name')

            writer_kwargs = {
                'encoder':self.outputEncoder.currentText(),
                'overwrite':self.outputOverwrite.isChecked(),
                'csv_timestamps':self.outputSaveTimestamps.isChecked(),
                'quality':self.outputQuality.value(),
                'bitrate':self.outputBitrate.value(),
                }

            if self.outputEncoder.currentText() == 'Auto':
                writer_kwargs['encoder'] = None
            else:
                writer_kwargs['encoder'] = self.outputEncoder.currentText()

            if self.outputSize.text() == 'Auto':
                writer_kwargs['img_size'] = None
            else:
                writer_kwargs['img_size'] = eval(self.outputSize.text())

            writer_kwargs['embed_image_info'] = []
            for prop, widget in self.outputEmbeddedImageInfo.items():
                if widget.isChecked():
                    writer_kwargs['embed_image_info'].append(prop)

        else:  # don't save video
            outfile = None
            writer_kwargs = {}

        # Assign into class
        self.SETTINGS = {'cam_mode':cam_mode,
                         'cam_nums':cam_nums,
                         'cam_kwargs':cam_kwargs,
                         'outfile':outfile,
                         'writer_kwargs':writer_kwargs,
                         'preview':preview,
                         'pixel_format':pixel_format}

    def connect_cameras(self):
        """
        Connect cameras. List of handles assigned to .CAM_HANDLES attribute.
        """
        settings = self.SETTINGS  # for brevity

        if not settings['cam_nums']:
            raise Exception('No cameras selected')

        self.CAM_HANDLES = []  # also overwrites existing (which we want)
        for cam_num in settings['cam_nums']:
            if (settings['cam_mode'] == 'Multi') and (settings['outfile'] is not None):
                _outfile, ext = os.path.splitext(settings['outfile'])
                outfile = _outfile + f'-cam{cam_num}' + ext
            else:
                outfile = settings['outfile']

            these_cam_kwargs = settings['cam_kwargs'].copy()
            these_cam_kwargs['cam_num'] = cam_num

            cam = Camera(**these_cam_kwargs)
            if outfile:
                cam.openVideoWriter(outfile, **settings['writer_kwargs'])

            self.CAM_HANDLES.append(cam)

    def run_capture(self):
        """
        Main function for running cameras. Frames are acquired from cameras,
        saved to file (if applicable), and displayed in preview window (if
        applicable).  Application events are processed periodically so that
        the app doesn't lock up.

        Set .KEEPGOING attribute to False to end capture and disconnect
        cameras.
        """
        # Start cameras
        for cam in self.CAM_HANDLES:
            cam.startCapture()

        # Begin main capture loop
        self.KEEPGOING = True
        while self.KEEPGOING:
            # Acquire images
            for cam in self.CAM_HANDLES:
                ret, img = cam.getImage()

            # Display (single-cam + preview mode only)
            if ret and hasattr(self, 'preview_window'):
                # Possible bug fix - converting image to array TWICE seems to
                # prevent image corruption?!
                fmt = self.SETTINGS['pixel_format']
                img2array(img, fmt)
                frame = img2array(img, fmt)
                self.preview_window.setImage(frame)

            # Refresh app (e.g. to check for button events)
            QApplication.processEvents()

        # Attempt to close cameras
        failed_cams = []
        for cam in self.CAM_HANDLES:
            try:
                cam.close()
            except:
                failed_cams.append(cam.cam_num)
        if failed_cams:
            raise Exception(f'Failed to close cameras: {failed_cams}')


    ## Slot functions for handling gui signals, e.g. clicked buttons etc. ##
    @pyqtSlot(str)
    def on_camera_mode_change(self, text):
        """
        On camera mode change: re-select default cameras & disable/enable
        preview options
        """
        for rowN in range(self.cameraTable.rowCount()):
            chk = QTableWidgetItem()
            if text == 'Multi' or (text == 'Single' and rowN == 0):
                chk.setCheckState(Qt.Checked)
            else:
                chk.setCheckState(Qt.Unchecked)
            self.cameraTable.setItem(rowN, 0, chk)

        if text == 'Single':
            self.preview.setEnabled(True)
            self.pixelFormat.setEnabled(True)
        else:
            self.preview.setEnabled(False)
            self.pixelFormat.setEnabled(False)

    @pyqtSlot(int, int)
    def on_camera_check(self, row, col):
        """
        On (un)checking of cameras in table: update table
        """
        self.set_camTable_selectivity(row)

    @pyqtSlot()
    def on_fileselect_browse(self):
        """
        On clicking output file browse button: open save file dialog and
        assign results back into GUI.
        """
        dlg = QFileDialog()
        file = dlg.getSaveFileName()[0]
        self.outputFile.setText(file)

    @pyqtSlot()
    def on_save_output_check(self):
        """
        On (un)checking of save output box: enable/disable 'Output Options'
        group box
        """
        # Options-group created BEFORE output-group so would error 1st time
        if hasattr(self, 'outputGroup'):
            self.outputGroup.setEnabled(self.saveOutput.isChecked())

    @pyqtSlot()
    @errorHandler
    def on_connect(self):
        """
        On Connect button click: parse settings, connect to cameras, and maybe
        open preview window.
        """
        self.connectBtn.setEnabled(False)

        # Parse parameter values
        self.extract_settings()
        if not hasattr(self, 'SETTINGS'):
            raise Exception('Failed to extract settings')

        # Connect
        self.connect_cameras()

        # Init preview window?
        # NOTE - window instance must be assigned into this class to prevent
        # it getting immediately garbage collected!
        if self.SETTINGS['preview']:
            xPos = self.pos().x() + self.size().width()
            yPos = self.pos().y()
            vidmode = self.SETTINGS['cam_kwargs']['video_mode']
            size = imgSize_from_vidMode(vidmode)
            self.preview_window = PreviewWindow(
                parent=self, pixel_format=self.SETTINGS['pixel_format'],
                winsize=size, pos=(xPos,yPos)
                )

        # Update window
        self.set_status('Connected', 'green')
        self.startBtn.setEnabled(True)
        self.stopBtn.setEnabled(True)

    @pyqtSlot()
    @errorHandler
    def on_start(self):
        """
        On Start button click: start camera capture.
        """
        self.startBtn.setEnabled(False)
        self.stopBtn.setEnabled(True)
        self.set_status('Running', 'green')
        self.run_capture()

    @pyqtSlot()
    def on_stop(self):
        """
        On Stop button click: stop capture & close preview window.
        """
        self.KEEPGOING = False  # set KEEPGOING flag False to stop capture
        self.close_preview()
        self.stopBtn.setEnabled(False)
        self.set_status('Disconnected', 'red')
        self.connectBtn.setEnabled(True)

    @pyqtSlot()
    def on_exit(self):
        """
        On Exit button click: as per stop, but also close main window.
        """
        self.on_stop()
        self.close()


class PreviewWindow(QMainWindow):
    def __init__(self, parent, pixel_format, winsize=(640,480), pos=(0,0)):
        """
        Preview window for displaying video feed.

        Parameters
        ----------
        parent : Window handle or None
            Handle to parent window, or None if not applicable
        pixel_format : PyCaputre2 pixel format
            PyCapture2.PIXEL_FORMAT code or key for PIXEL_FORMATS lookup dict.
            Note that not all pixel formats are supported; must be one that
            can be converted to QImage format.
        winsize : (W,H) tuple, optional
            Size of window in pixels. The default is (640,480).
        pos : (x,y), optional
            Position of window in pixels. The default is (0,0).
        """
        # Init parent
        super().__init__(parent)

        # Allocate variables
        self.parent = parent
        self.winsize = winsize
        self.pos = pos

        # Convert pixel format
        self.qimg_format = convert_pixel_format(pixel_format)

        # Init interface
        self.initUI()
        self.show()

    def initUI(self):
        """
        Initialise user interface
        """
        # Init window
        self.setWindowTitle('Preview')
        self.setFixedSize(*self.winsize)
        self.move(*self.pos)
        self.setWindowFlag(Qt.WindowCloseButtonHint, False)
        self.setWindowFlag(Qt.WindowMinMaxButtonsHint, False)

        # Add label for pixmap, allocate as central widget
        self.imgQLabel = QLabel()
        self.imgQLabel.setAlignment(Qt.AlignCenter)
        self.setCentralWidget(self.imgQLabel)

    def setImage(self, im):
        """
        Takes image (as numpy array) and updates QLabel display.

        Parameters
        ----------
        im : numpy array
            Image as numpy array (probably 2D/mono or 3D/RGB uint8)
        """
        W, H = im.shape[:2]
        stride = im.strides[0]
        qimg = QImage(im.data, H, W, stride, self.qimg_format)
        qpixmap = QPixmap(qimg).scaled(self.imgQLabel.size(), Qt.KeepAspectRatio)
        self.imgQLabel.setPixmap(qpixmap)


### Run application ###
if __name__ == '__main__':
    app = QApplication(sys.argv)
    win = MainWindow()
    sys.exit(app.exec_())
