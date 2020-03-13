# -*- coding: utf-8 -*-
"""
Provides functions and classes for interfacing with Point Grey / FLIR
cameras, using the PyCapture2 python bindings to the FlyCapture2 SDK.
"""

import os
import traceback
import PyCapture2

def enum2dict(obj, key_filter=None):
    """
    PyCapture2 enumerated values are stored as classes making it difficult to
    check the values within them. This function can be used to take a class
    and return it's attributes as a dict.

    Parameters
    ----------
    obj : class
        A PyCapture2.<ENUMERATED VALUE> class
    key_filter : callable, optional
        A callable returning a boolean value that can be used to filter the
        keys of the dict. Entries for which the corresponding keys return
        False will be remoed.

    Returns
    -------
    D : dict
        Attribute names and values as the dictionary's keys and values.
    
    Examples
    --------
    >>> D = enum2dict(PyCapture2.VIDEO_MODE, lambda k: k.startswith('VM_'))
    """
    D = dict(obj.__dict__)
    D = dict(filter(lambda elem: not elem[0].startswith('__'), D.items()))
    if (key_filter is not None):
        D = dict(filter(lambda elem: key_filter(elem[0]), D.items()))
    return D

def img2array(img):
    """
    Converts PyCapture2 image object to BGR numpy array.

    Parameters
    ----------
    img : PyCaputre2.Image object
        Image retrieved from buffer.

    Returns
    -------
    frame : numpy.ndarray
        Image data as a BGR uint8 array.
    """
    return img.convert(PyCapture2.PIXEL_FORMAT.BGR) \
        .getData().reshape(img.getRows(), img.getCols(), 3)

def get_available_cameras(bus=None, camNums=None):
    """
    List indices and serial numbers of available cameras.

    Parameters
    ----------
    bus : PyCapture2.BusManager instance, optional
        Bus manager. If None (default), will create one.
    camNums : list, optional
        List of camera indices. If None (default), will use all cameras
        available on the bus.

    Returns
    -------
    serial_nums : list
        List of (idx, serialNum) tuples. 
    """
    if bus is None:
        bus = PyCapture2.BusManager()
    if camNums is None:
        camNums = range(bus.getNumOfCameras())
    return [(i, bus.getCameraSerialNumberFromIndex(i)) for i in camNums]

def list_available_modes(cam):
    """
    List valid video modes and framerates for specified camera.

    Parameters
    ----------
    cam : PyCapture2.Camera instance
        Handle to camera connection.

    Returns
    -------
    res : list
        List of (mode, framerate) tuples giving all valid options.
    """
    res = []
    for modename, modeval in VIDEO_MODES.items():
        for ratename, rateval in FRAMERATES.items():
            try:
                if cam.getVideoModeAndFrameRateInfo(modeval, rateval):
                    res.append((modename, ratename))
            except:
                pass
    return res


class Camera(object):
    def __init__(self, cam_num, bus=None, video_mode='VM_640x480RGB',
                 framerate='FR_30', grab_mode='BUFFER_FRAMES'):
        """
        Class provides methods for controlling camera, capturing images,
        and writing video files.

        Parameters
        ----------
        cam_num : int
            Index of camera to use. See also the get_available_cameras()
            function.
        bus : PyCapture2.BusManager, optional
            Bus manager object. If None (default), one will be created.
        video_mode : PyCapture2.VIDEO_MODE value or str, optional
            Determines the resolution and colour mode of video capture.
            Can be one of the PyCapture2.VIDEO_MODE.* values or a key for
            the VIDEO_MODES lookup dict. The default is 'VM_640x480RGB'.
            See also the list_available_modes() function.
        framerate : PyCapture2.FRAMERATE value or str, optional
            Determines the frame rate of the video. Note that this is NOT the
            actual fps value, but the code PyCapture uses to determine it.
            Can be one of the PyCapture2.FRAMERATE.* values or a key for the
            FRAMERATES lookup dict. The default is 'FR_30'.
            See also the list_available_modes() function.
        grab_mode : PyCapture2.GRAB_MODE value or str, optional
            Method for acquiring images from the buffer. Can be one of the
            PyCapture2.GRAB_MODE.* values or a key for the GRAB_MODES lookup
            dict. BUFFER_FRAMES mode (default) grabs the oldest frame from
            the buffer each time and does not clear the buffer in between -
            this ensures frames are not dropped, but the buffer may overflow
            if the program cannot keep up. DROP_FRAMES mode grabs the newest
            frame from the buffer each time and clears the buffer in between -
            this prevents the buffer overflowing but may lead to frames
            being missed. BUFFER_FRAMES should generally be preferred for
            recording, DROP_FRAMES may be preferable for live streaming.
            
        Methods
        -------
        

        """
        # Allocate args to class
        self.cam_num = cam_num
        self.bus = bus
        self.video_mode = video_mode
        self.framerate = framerate
        self.grab_mode = grab_mode
        
        # Allocate further defaults where needed
        if self.bus is None:
            self.bus = PyCapture2.BusManager()
        if isinstance(self.video_mode, str):
            self.video_mode = VIDEO_MODES[self.video_mode]
        if isinstance(self.framerate, str):
            self.framerate = FRAMERATES[self.framerate]
        if isinstance(self.grab_mode, str):
            self.grab_mode = GRAB_MODES[self.grab_mode]
        
        # Init camera
        self.cam = PyCapture2.Camera()
        self.uid = self.bus.getCameraFromIndex(self.cam_num)
        self.cam.connect(self.uid)
        if not self.cam.getStats().cameraPowerUp:
            raise OSError('Camera is not powered on')
        if not self.cam.isConnected:
            raise OSError('Camera faied to connect')
        
        # Set mode and frame rate
        if not self.cam.getVideoModeAndFrameRateInfo(self.video_mode,
                                                     self.framerate):
            raise OSError('Video mode and / or frame rate incompatible '
                          'with camera')
        self.cam.setVideoModeAndFrameRate(self.video_mode, self.framerate)
        
        # Further config
        self.cam.setConfiguration(grabMode=self.grab_mode)
        
        # Place holders for video writer
        self.video_writer = None
        self.file_format = None

        # Internal flags
        self._capture_isOn = False        
        self._video_writer_isOpen = False

    
    def get_image(self):
        """
        Acquire a single image from the camera. If a video writer has been
        opened, the frame will additionally be appended to the writer.

        Returns
        -------
        success : bool
            Indicates whether capture was successful or not.
        img : PyCapture2.Image object or None
            The image object if capture was successful, or None if not.
                    
        See also
        --------
        .startCapture() - method must be called prior to acquiring any image.
        .openVideoWriter() - method allows frames to be written to video file.
        img2array() - function converts returned images to numpy arrays that
            can, for example, be used for a live display.
        """
        success = False
        img = None
        try:
            img = self.cam.retrieveBuffer()
            if self.video_writer is not None:
                self.video_writer.append(img)
            success = True
        except Exception as e:
            print(e)
        return success, img
    
    def openVideoWriter(self, filename, file_format=None, overwrite=False,
                        *args, **kwargs):
        """
        Opens a video writer. Subsequent calls to .get_image() will
        additionally write those frames out to the file.

        Parameters
        ----------
        filename : str
            Path to desired output file
        file_format : str { 'AVI' | 'MJPG' | 'H264' } or None, optional
            Output format to use. If None, will automatically set to 'AVI'
            if filename ends with an '.avi' extension, 'H264' if filename
            ends with a 'mp4' extension, or will raise an error for other
            extensions. Note that 'MJPG' and 'H264' formats require addtional
            arguments to be passed (see *args, **kwargs). The default is None.
        overwrite : bool, optional
            If False and the output file already exists, an error will be
            raised. The default if False.
        *args, **kwargs
            Additional arguments to be passed to the format-specfic
            writer.*Open() methods (except framerate). These are necessary
            for MJPG and H264 formats - see PyCapture2 documention.
            DESCRIPTION.
        """
        # Without overwrite, error if file exists
        if not overwrite and os.path.isfile(filename):
            raise OSError(f'Output file {filename} already exists')
        
        # Try to auto-determine file format if unspecified
        if file_format is None:
            ext = os.path.splitext(filename)[1].lower()  # case insensitive
            if ext == '.avi':
                file_format = 'AVI'
            elif ext == '.mp4':
                file_format = 'H264'
            else:
                raise ValueError('Cannot determine file_format automatically '
                                 f'from {ext} extension')
            print(f'Recording using {file_format} format')
                
        file_format = file_format.upper()  # ensure case insensitive
        
        if not file_format in ['AVI', 'MJPG', 'H264']:
            raise ValueError("file_format must be  'AVI', 'MJPG', or 'H264, "
                             f"but received {file_format}")
            
        # Grab framerate from camera properties
        framerate = self.cam.getProperty(PyCapture2.PROPERTY_TYPE.FRAME_RATE).absValue

        # Filename needs to be bytes string
        if not isinstance(filename, bytes):
            filename = filename.encode('utf-8')
           
        # Initialise video writer, allocate to class
        self.video_writer = PyCapture2.FlyCapture2Video()
        self.file_format = file_format

        # Open video file
        if self.file_format == 'AVI':
            self.video_writer.AVIOpen(filename, framerate)
        elif self.file_format == 'MJPG':
            self.video_writer.MJPGOpen(filename, framerate, *args, **kwargs)
        elif self.file_format == 'H264':
            self.video_writer.H264Open(filename, framerate, *args, **kwargs)
            
        # Success!
        self._video_writer_isOpen = True

    def closeVideoWriter(self):
        """
        Close video writer object.
        """
        self.video_writer.close()
        self._video_writer_isOpen = False

    def startCapture(self):
        """
        Start capture from camera. Note this MUST be called before attempting
        to acquire any images.
        """
        self.cam.startCapture()
        self._capture_isOn = True
            
    def stopCapture(self):
        """
        Stop capture from camera.
        """
        self.cam.stopCapture()
        self._capture_isOn = False
            
    def close(self):
        """
        Close everything. Stops camera capture, closes video writer (if
        applicable), and disconnects camera.
        """
        if self._capture_isOn:
            try:
                self.stopCapture()
            except Exception:
                traceback.print_exc()
            
        if self.video_writer and self._video_writer_isOpen:
            try:
                self.closeVideoWriter()
            except Exception:
                traceback.print_exc()
            
        self.cam.disconnect()
        

# Assorted lookup dicts storing critical PyCapture codes
VIDEO_MODES = enum2dict(PyCapture2.VIDEO_MODE, lambda k: k.startswith('VM_'))
FRAMERATES = enum2dict(PyCapture2.FRAMERATE, lambda k: k.startswith('FR_'))
IMAGE_FILE_FORMATS = enum2dict(PyCapture2.IMAGE_FILE_FORMAT)
PIXEL_FORMATS = enum2dict(PyCapture2.PIXEL_FORMAT)
GRAB_MODES = enum2dict(PyCapture2.GRAB_MODE)


if __name__ == '__main__':
    print('Running demo - Esc to exit')
    
    import cv2
    
    cam = Camera(0)
    
    #cam.openVideoWriter('test.avi')
    
    cam.startCapture()
    
    while True:
        ret, img = cam.get_image()
        if ret:
            cv2.imshow('window1', img2array(img))
        kb = cv2.waitKey(1)
        if kb == 27:
            break
        
    cam.close()
    
    cv2.destroyAllWindows()
    
    print('\nDone\n')