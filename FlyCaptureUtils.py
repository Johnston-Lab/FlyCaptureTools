# -*- coding: utf-8 -*-
"""
Provides functions and classes for interfacing with Point Grey / FLIR
cameras, using the PyCapture2 python bindings to the FlyCapture2 SDK.
"""

import os
import re
import warnings
import traceback
import PyCapture2
from csv import DictWriter


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
        A callable returning a boolean that can be used to filter the keys of
        the dict. Entries for which the callable return False will be removed.

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

def imgSize_from_vidMode(video_mode):
    """
    Attempts to extract image resolution given PyCapture2 VIDEO_MODE code

    Parameters
    ----------
    video_mode : str or int
        PyCapture2.VIDEO_MODE code or a key for the VIDEO_MODES lookup dict.

    Returns
    -------
    size : tuple
        (width, height) values
    """
    # If code, lookup name from dict
    if isinstance(video_mode, int):
        video_mode = [k for k,v in VIDEO_MODES.items() if v == video_mode]
        if len(video_mode) > 1:
            raise RuntimeError('Multiple matching video mode codes')
        video_mode = video_mode[0]
        
    # Split at 'x' character to get width and height portions of string
    s1, s2 = video_mode.split('x')
    
    # Width is easy - just strip 'VM_' from front of 1st string
    width = int(re.sub('^VM_', '', s1))
    
    # Height bit harder - find numeric chars in 2nd string but only at start
    # (e.g. in '480YUV422', count the '480' but not the '422')
    height = int(re.search('^[0-9]*', s2).group())
    
    # Return
    return (width, height)

def img2array(img, pixel_format='BGR'):
    """
    Converts PyCapture2 image object to BGR numpy array.

    Parameters
    ----------
    img : PyCapture2.Image object
        Image retrieved from buffer.
    pixel_format : PyCapture2.PIXEL_FORMAT value or str, optional
        Format to convert image to. Can be one of the PyCapture2.PIXEL_FORMAT
        codes, or a key for the PIXEL_MODES lookup dict. The default is 'BGR'.

    Returns
    -------
    frame : numpy.ndarray
        Image data as a BGR uint8 array.
    """
    if isinstance(pixel_format, str):
        pixel_format = PIXEL_FORMATS[pixel_format]
    return img.convert(pixel_format).getData() \
              .reshape(img.getRows(), img.getCols(), -1).squeeze()

def getAvailableCameras(bus=None, camNums=None):
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

def listAvailableModes(cam_num=None, cam=None, bus=None):
    """
    List valid video modes and framerates for specified camera.

    Parameters
    ----------
    cam_num : int, optional
        Index of camera to connect to. Cannot be specified alongside <cam>,
        and must be specified if <cam> is not.
    cam : PyCapture2.Camera instance, optional
        Handle to camera connection. Cannot be specified alongisde <cam_num>,
        and must be specified if <cam_num> is not.
    bus : PyCapture2.BusManager instance, optional
        Only relevant if <cam> is None / <cam_num> is not None. Bus manager
        to connect camera. If None (default), one will be created.

    Returns
    -------
    res : list
        List of (mode, framerate) tuples giving all valid options.
    """

    # Ensure one of cam_num or cam is specified
    if cam_num is None and cam is None:
        raise ValueError('Must specify cam_num or cam')
    elif cam_num is not None and cam is not None:
        raise ValueError('Can only specify one of cam_num or cam')

    # If no cam given, create one from index. Also create bus if needed.
    if cam is None:
        cam = PyCapture2.Camera()
        if bus is None:
            bus = PyCapture2.BusManager()
        cam.connect(bus.getCameraFromIndex(cam_num))

    # Find and return compatible modes
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
            Index of camera to use. See also the getAvailableCameras()
            function.
        bus : PyCapture2.BusManager, optional
            Bus manager object. If None (default), one will be created.
        video_mode : PyCapture2.VIDEO_MODE value or str, optional
            Determines the resolution and colour mode of video capture. Can be
            one of the PyCapture2.VIDEO_MODE codes, or a key for the
            VIDEO_MODES lookup dict. The default is 'VM_640x480RGB'. See also
            the listAvailableModes() function.
        framerate : PyCapture2.FRAMERATE value or str, optional
            Determines the frame rate of the video. Note that this is NOT the
            actual fps value, but the code PyCapture uses to determine it.
            Can be one of the PyCapture2.FRAMERATE codes, or a key for the
            FRAMERATES lookup dict. The default is 'FR_30'. See also the
            listAvailableModes() function.
        grab_mode : PyCapture2.GRAB_MODE value or str, optional
            Method for acquiring images from the buffer. Can be one of the
            PyCapture2.GRAB_MODE codes, or a key for the GRAB_MODES lookup
            dict. BUFFER_FRAMES mode (default) grabs the oldest frame from
            the buffer each time and does not clear the buffer in between;
            this ensures frames are not dropped, but the buffer may overflow
            if the program cannot keep up. DROP_FRAMES mode grabs the newest
            frame from the buffer each time and clears the buffer in between;
            this prevents the buffer overflowing but may lead to frames
            being missed. BUFFER_FRAMES should generally be preferred for
            recording, DROP_FRAMES may be preferable for live streaming.

        Examples
        --------

        Open connection to first available camera.

        >>> cam = Camera(0)

        Optionally open a video file to write frames to.

        >>> cam.openVideoWriter('test.avi')

        Start camera capture - this must be called before acquiring images.

        >>> cam.startCapture()

        Acquire frames in a loop. Optionally display them in an OpenCV window.
        If a video writer was opened, each call to .getImage() will also write
        the frame out to the video file.

        >>> for i in range(300):
        ...     ret, img = cam.getImage()
        ...     if ret:
        ...         cv2.imshow('Camera', img2array(img))
        ...         cv2.waitKey(1)

        Close the camera when done. This will stop camera capture,
        close the video writer (if applicable), and disconnect the camera.

        >>> cam.close()

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
        self.serial_num = self.bus.getCameraSerialNumberFromIndex(self.cam_num)
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

        # Reverse grab image resolution out of video mode
        self.img_size = imgSize_from_vidMode(self.video_mode)

        # Also note fps value
        self.fps = self.cam.getProperty(PyCapture2.PROPERTY_TYPE.FRAME_RATE).absValue

        # Place holders for video writer
        self.video_writer = None
        self.file_format = None
        self.csv_fd = None
        self.csv_writer = None

        # Internal flags
        self._capture_isOn = False
        self._video_writer_isOpen = False

    def getImage(self, onError='warn'):
        """
        Acquire a single image from the camera. If a video writer has been
        opened, the frame will additionally be appended to the writer.

        Parameters
        ----------
        onError : str { 'ignore' | 'warn' | 'error' }, optional
            Whether to ignore, warn about, or raise any errors encountered
            during image acquisition. The default is 'warn'.

        Returns
        -------
        success : bool
            Indicates whether capture was successful or not.
        img : PyCapture2.Image object or None
            The image object if capture was successful, or None if not.

        See also
        --------
        * .startCapture() - must be called prior to acquiring any image.
        * .openVideoWriter() - allows frames to be written to video file.
        * img2array() - converts returned images to numpy arrays that
          can, for example, be used for a live display.
        """
        if onError not in ['ignore','warn','error']:
            raise ValueError(f'Invalid value {onError} to onError')

        success = False
        img = None

        try:
            img = self.cam.retrieveBuffer()
            if self.video_writer is not None:
                self.video_writer.append(img)
                if self.csv_writer is not None:
                    self.csv_writer.writerow(img.getTimeStamp().__dict__)
            success = True

        except Exception as e:
            if onError == 'error':
                raise e
            elif onError == 'warn':
                warnings.warn(str(e))

        return success, img

    def openVideoWriter(self, filename, file_format=None, overwrite=False,
                        quality=75, bitrate=1000000, img_size=None,
                        embed_image_info=['timestamp','frameCounter'],
                        csv_timestamps=False):
        """
        Opens a video writer. Subsequent calls to .get_image() will
        additionally write those frames out to the file.

        Parameters
        ----------
        filename : str
            Path to desired output file. If extension is omitted it will be
            inferred from <file_format> (if specified).
        file_format : str { 'AVI' | 'MJPG' | 'H264' } or None, optional
            Output format to use. If None, will automatically set to 'AVI'
            if filename ends with an '.avi' extension, 'H264' if filename
            ends with a 'mp4' extension, or will raise an error for other
            extensions. Note that 'MJPG' and 'H264' formats permit addtional
            arguments to be passed. The default is None.
        overwrite : bool, optional
            If False and the output file already exists, an error will be
            raised. The default is False.
        quality : int, optional
            Value between 0-100 determining output quality. Only applicable
            for MJPG format. The default is 75.
        bitrate : int, optional
            Bitrate to encode at. Only applicable for H264 format. The default
            is 1000000.
        img_size : (W,H) tuple of ints, optional
            Image resolution. Only applicable for H264 format. If not given,
            will attempt to determine from camera's video mode, but this
            might not work. The default is None.
        embed_image_info : list or 'all' or None, optional
            List of property names indicating information to embed within image
            pixels. Available properties: timestamp, gain, shutter, brightness,
            exposure, whiteBalance, frameCounter, strobePattern, ROIPosition.
            Alternatively specify string 'all' to use all available properties.
            Specify None or False to not embed any properties. The default is
            to embed timestamps and the frameCounter.
        csv_timestamps : bool, optional
            If True, timestamps for each frame will be saved to a csv file
            corresponding to the output video file. Note that embedding
            timestamps image info is preferable as they are more accurate.
            The default is False.
        """
        # Try to auto-determine file format if unspecified
        if file_format is None:
            ext = os.path.splitext(filename)[1].lower()  # case insensitive
            if ext == '.avi':
                file_format = 'AVI'
            elif ext == '.mp4':
                file_format = 'H264'
            elif not ext:
                raise ValueError('Cannot determine file_format automatically '
                                 'without file extension')
            else:
                raise ValueError('Cannot determine file_format automatically '
                                 f'from {ext} extension')
            print(f'Recording using {file_format} format')

        file_format = file_format.upper()  # ensure case insensitive

        if not file_format in ['AVI', 'MJPG', 'H264']:
            raise ValueError("file_format must be  'AVI', 'MJPG', or 'H264, "
                             f"but received {file_format}")

        # Auto-determine file extension if necessary
        if not os.path.splitext(filename)[1]:
            if file_format in ['AVI','MJPG']:
                filename += '.avi'
            elif file_format == 'H264':
                filename += '.mp4'

        # Without overwrite, error if file exists. AVI writer sometimes
        # appends a bunch of zeros to name, so check that too.
        if not overwrite:
            _filename, ext = os.path.splitext(filename)
            alt_filename = _filename + '-0000' + ext
            if os.path.isfile(filename) or os.path.isfile(alt_filename):
                raise OSError(f'Output file {filename} already exists')

        # Update camera to embed image info
        available_info = self.cam.getEmbeddedImageInfo().available
        keys = [k for k in dir(available_info) if not k.startswith('__')]
        _info = dict((k, False) for k in keys)
        
        if embed_image_info:
            if (embed_image_info == 'all') or ('all' in embed_image_info):
                for k in keys:
                    _info[k] = getattr(available_info, k)
            else:  # use specified values
                for k in embed_image_info:
                    if not hasattr(available_info, k):
                        raise KeyError(f'\'{k}\' not a valid embedded property')
                    elif not getattr(available_info, k):
                        raise ValueError(f'\{k}\' embedded property not available')
                    _info[k] = True
                
        self.cam.setEmbeddedImageInfo(**_info)

        # Open csv writer for timestamps?
        if csv_timestamps:
            csv_filename = os.path.splitext(filename)[0] + '.csv'
            if not overwrite and os.path.isfile(csv_filename):
                raise OSError(f'Timestamps file {csv_filename} already exists')
            self.csv_fd = open(csv_filename, 'w')

            fieldnames=['seconds', 'microSeconds', 'cycleSeconds',
                        'cycleCount', 'cycleOffset']
            self.csv_writer = DictWriter(self.csv_fd, fieldnames,
                                         delimiter=',', lineterminator='\n')
            self.csv_writer.writeheader()

        # Filename needs to be bytes string
        if not isinstance(filename, bytes):
            filename = filename.encode('utf-8')

        # Initialise video writer, allocate to class
        self.video_writer = PyCapture2.FlyCapture2Video()
        self.file_format = file_format

        # Open video file
        if self.file_format == 'AVI':
            self.video_writer.AVIOpen(filename, self.fps)
        elif self.file_format == 'MJPG':
            self.video_writer.MJPGOpen(filename, self.fps, quality)
        elif self.file_format == 'H264':
            if img_size is None:
                if self.img_size is None:
                    raise RuntimeError('Cannot determine image resolution')
                else:
                    img_size = self.img_size
            W, H = img_size
            self.video_writer.H264Open(filename, self.fps, W, H, bitrate)

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
                if self.csv_writer:
                    self.csv_fd.close()
            except Exception:
                traceback.print_exc()

        self.cam.disconnect()


# Assorted lookup dicts storing critical PyCapture codes
VIDEO_MODES = enum2dict(PyCapture2.VIDEO_MODE, lambda k: k.startswith('VM_'))
FRAMERATES = enum2dict(PyCapture2.FRAMERATE, lambda k: k.startswith('FR_'))
IMAGE_FILE_FORMATS = enum2dict(PyCapture2.IMAGE_FILE_FORMAT)
PIXEL_FORMATS = enum2dict(PyCapture2.PIXEL_FORMAT)
GRAB_MODES = enum2dict(PyCapture2.GRAB_MODE)
