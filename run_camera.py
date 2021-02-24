#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import argparse
import cv2
import traceback
import ctypes
import keyboard
import numpy as np
from multiprocessing import Process, Event, Queue
from queue import Full as QueueFull, Empty as QueueEmpty
from FlyCaptureUtils import (Camera, img2array, imgSize_from_vidMode,
                             imgDepth_from_pixFormat, getAvailableCameras)


### Class definitions ###

class CustomFormatter(argparse.ArgumentDefaultsHelpFormatter,
                      argparse.RawTextHelpFormatter):
    "Combines argparse formatters"
    pass

class ParallelCamera(Process):
    def __init__(self, start_event, stop_event, cam_num, cam_kwargs, outfile,
                 writer_kwargs, pixel_format, *args, **kwargs):
        """
        Class supports running camera within parallel child process.

        Arguments
        ---------
        start_event : multiprocessing.Event object
            Child process will block after barrier till start event is set.
            Allows main process to signal to start acquisition.
        stop_event : multiprocessing.Event object
            Child process will continue execution till stop event is set.
            Allows main process to signal to stop acquisition.
        cam_num, cam_kwargs
            As per Camera class.
        outfile, writer_kwargs
            As per Camera.openVideoWriter function.
        pixel_format : PyCapture2.PIXEL_FORMAT value or str
            Format to convert image to for display. Can be one of the
            PyCapture2.PIXEL_FORMAT codes, or a key for the PIXEL_MODES lookup
            dict.
        *args, **kwargs
            Further arguments passed to multiprocessing.Process

        Attributes
        ----------
        self.ready_event : multiprocessing.Event object
            Will be set when camera initialisation has finished. Can be used
            to signal main process when camera is ready to start acquisition.
        self.frame_queue : multiprocessing.Queue object
            Queue will pass images back up to main process for display.
        self.error_queue : multiprocessing.Queue object
            Queue will pass error instances back up to main process.
        """
        # Allocate args to class
        self.start_event = start_event
        self.stop_event = stop_event
        self.cam_num = cam_num
        self.cam_kwargs = cam_kwargs
        self.outfile = outfile
        self.writer_kwargs = writer_kwargs
        self.pixel_format = pixel_format

        # Init further internal attributes
        self.ready_event = Event()
        self.frame_queue = Queue(maxsize=1)
        self.error_queue = Queue()

        # Super call implements inheritance from multiprocessing.Process
        super(ParallelCamera, self).__init__(*args, **kwargs)

    def run(self):
        """
        Overwrite multiprocessing.Process.run method.  Gets called in its
        place when the process's .start() method is called.
        """
        # Everything in try block to handle errors
        try:
            # Init cam
            cam = Camera(self.cam_num, **self.cam_kwargs)

            # Init video writer?
            if self.outfile is not None:
                cam.openVideoWriter(self.outfile, **self.writer_kwargs)

            # Signal main process we're ready
            self.ready_event.set()

            # Wait for start event to signal go
            self.start_event.wait()

            # Go!
            cam.startCapture()
            while not self.stop_event.is_set():
                ret, img = cam.getImage()
                if ret:
                    # Possible bug fix - converting image to array TWICE seems
                    # to prevent image corruption?!
                    img2array(img, self.pixel_format)
                    frame = img2array(img, self.pixel_format)
                    # Append to queue
                    try:
                        self.frame_queue.put_nowait(frame.copy())  # NB: copy
                    except QueueFull:
                        pass

        # Error encountered - pass up to main process
        except Exception as e:
            self.error_queue.put(e)

        # Finish - try to close cameras and queues. We need to cancel queue
        # joining otherwise child process can block while trying to exit if
        # queue wasn't completely flushed.
        finally:
            try:
                cam.close()
            except:
                pass
            self.frame_queue.close()
            self.frame_queue.cancel_join_thread()
            self.error_queue.close()
            self.error_queue.cancel_join_thread()


### Function definitions ###

def check_enumerated_value(x):
    """
    Enumerated values (video modes, pixel formats, etc.) should be able to be
    given as either the lookup key (e.g. 'VM_640x480RGB') or the PyCapture2
    code (e.g. 4). Argparse can only return one datatype though, so this func
    is used to convert to codes to ints while keeping keys as strings
    """
    try:
        return int(x)
    except ValueError:
        return x

def get_screen_resolution():
    """
    Get resolution of primary display. Only works on Windows, but so does
    PyCapture so should be okay.
    """
    user32 = ctypes.windll.user32
    # https://docs.microsoft.com/en-gb/windows/win32/api/winuser/nf-winuser-getsystemmetrics
    W, H = user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
    return W, H

def single_main(cam_num, cam_kwargs, outfile, writer_kwargs, pixel_format):
    """
    Main function for single camera operation.

    Parameters
    ----------
    cam_num : int
        Camera numer to use
    cam_kwargs : dict
        Keyword arguments to Camera class (excluding cam_num)
    outfile : str or None
        Output video file
    writer_kwargs : dict
        Keyword arguments to Camera class's .openVideoWriter() method
    pixel_format : PyCapture2.PIXEL_FORMAT value or str
        Format to convert image to for display
    """
    # Init camera
    cam = Camera(cam_num, **cam_kwargs)

    # Init video writer?
    if outfile is not None:
        cam.openVideoWriter(outfile, **writer_kwargs)

    # Report ready
    print('Ready - Enter to begin')
    keyboard.wait('enter')

    # Open display window
    winName = 'Display'
    cv2.namedWindow(winName)
    print('Running - Esc or q to quit')

    # Start capture
    cam.startCapture()

    # Loop
    while True:
        ret, img = cam.getImage()
        if ret:
            # Possible bug fix - converting image to array TWICE seems to
            # prevent image corruption?!
            img2array(img, pixel_format)
            frame = img2array(img, pixel_format)
            cv2.imshow(winName, frame)
            cv2.waitKey(1)

        # Check for quit signal
        if keyboard.is_pressed('esc') or keyboard.is_pressed('q'):
            print('Quitting...')
            break

    # Stop capture
    cam.stopCapture()

    # Close camera and exit
    cam.close()
    cv2.destroyWindow(winName)
    print('\nDone\n')


def multi_main(cam_nums, cam_kwargs, base_outfile, writer_kwargs, pixel_format):
    """
    Main function for multiple camera operation.

    Parameters
    ----------
    cam_nums : list
        List of camera numbers to use.
    cam_kwargs : dict
        Keyword arguments to Camera class (excluding cam_num).
    base_outfile : str or None
        Base output video file path. Will adjust to append camera numbers.
    writer_kwargs : dict
        Keyword arguments to Camera class's .openVideoWriter() method.
    pixel_format : PyCapture2.PIXEL_FORMAT value or str
        Format to convert image to for display.
    """
    # Imports only needed for this function
    import inspect, time

    # Set up viewport for display
    nCams = len(cam_nums)
    nRows = np.floor(np.sqrt(nCams)).astype(int)
    nCols = np.ceil(nCams/nRows).astype(int)

    if cam_kwargs['video_mode']:
        imgW, imgH = imgSize_from_vidMode(cam_kwargs['video_mode'])
    else:
        sig = inspect.signature(Camera)
        default_vid_mode = sig.parameters['video_mode'].default
        imgW, imgH = imgSize_from_vidMode(default_vid_mode)

    imgD = imgDepth_from_pixFormat(pixel_format)

    viewport = np.zeros([imgH*nRows, imgW*nCols, imgD], dtype='uint8').squeeze()

    # Set up events and barriers
    nCams = len(cam_nums)
    start_event = Event()
    stop_event = Event()

    # Set up camera processes
    parCams = []
    for cam_num in cam_nums:
        if base_outfile is not None:
            _outfile, ext = os.path.splitext(base_outfile)
            outfile = _outfile + f'-cam{cam_num}' + ext
        else:
            outfile = None

        these_cam_kwargs = cam_kwargs.copy()
        these_cam_kwargs['cam_num'] = cam_num

        parCam = ParallelCamera(start_event, stop_event, cam_num, cam_kwargs,
                                outfile, writer_kwargs, pixel_format,
                                name=f'cam{cam_num}')
        parCam.start()
        parCams.append(parCam)

    # Wait till all child processes signal ready
    timeout = 5
    all_ready = [False] * nCams
    t0 = time.time()
    KEEPGOING = True
    while KEEPGOING:
        for i, parCam in enumerate(parCams):
            all_ready[i] = parCam.ready_event.is_set()
            try:
                e = parCam.error_queue.get_nowait()
                print(f'Camera ({parCam.name}) errored during initialisation')
                print(e)
                KEEPGOING = False
                break
            except QueueEmpty:
                pass
        if all(all_ready) or time.time() - t0 >= timeout:
            KEEPGOING = False

    # If initialisation failed, terminate child processes and exit
    if not all(all_ready):
        failed_cams = [parCam.name for success, parCam in \
                       zip(all_ready, parCams) if not success]
        print('Following cameras failed to initialise: ' + ', '.join(failed_cams))
        print('Terminating all camera processes and exiting')
        stop_event.set()
        start_event.set()
        for parCam in parCams:
            parCam.join(timeout=5)
            if (parCam.exitcode is None) or (parCam.exitcode < 0):
                parCam.terminate()
        return

    # Wait to begin
    print('Ready - Enter to begin')
    keyboard.wait('enter')

    # Open display window - size it to fit within monitor (while keeping
    # viewport aspect ratio) and position in centre
    winName = 'Display'
    cv2.namedWindow(winName, cv2.WINDOW_NORMAL)

    screenSize = get_screen_resolution()
    viewportSize = viewport.shape[:2][::-1]
    if viewportSize[0] > viewportSize[1]:  # landscape
        winW = min(viewportSize[0], int(round(0.9 * screenSize[0])))
        winH = int(round(viewportSize[1] * winW/viewportSize[0]))
    else:  # portrait
        winH = min(viewportSize[1], int(round(0.9 * screenSize[1])))
        winW = int(round(viewportSize[0] * winH/viewportSize[1]))
    winSize = (winW, winH)
    cv2.resizeWindow(winName, *winSize)

    screenMid = [ss//2 for ss in screenSize]
    winMid = [ws//2 for ws in winSize]
    origin = (screenMid[0] - winMid[0], screenMid[1] - winMid[1])
    cv2.moveWindow(winName, *origin)

    # Send go signal
    start_event.set()

    # Begin display loop - all in try block so we can kill child processes in
    # case of main process error
    print('Running - Esc to quit')
    try:
        KEEPGOING = True
        while KEEPGOING:
            for i, parCam in enumerate(parCams):
                # Check for error in child process - exit if found
                if not parCam.is_alive():
                    msg = f'Camera ({parCam.name}) died, exiting'
                    try:
                        e = parCam.error_queue.get(timeout=1)
                        msg += '\n' + str(e)
                    except QueueEmpty:
                        pass
                    raise RuntimeError(msg)

                # Try to retrieve frame from child process
                try:
                    frame = parCam.frame_queue.get_nowait()
                except QueueEmpty:
                    continue

                # Allocate to array
                y,x = np.unravel_index(i, (nRows, nCols))
                viewport[y*imgH:(y+1)*imgH, x*imgW:(x+1)*imgW, ...] = frame

            # Display
            cv2.imshow(winName, viewport)
            cv2.waitKey(1)

            # Check for quit signal
            if keyboard.is_pressed('esc') or keyboard.is_pressed('q'):
                print('Quitting...')
                KEEPGOING = False

    # Main process encountered error - print it
    except Exception:
        traceback.print_exc()

    # Finish up - stop cameras, clear window, and exit
    finally:
        # Stop
        stop_event.set()

        # Clear window and exit
        cv2.destroyWindow(winName)
        for parCam in parCams:
            parCam.join(timeout=5)
            if (parCam.exitcode is None) or (parCam.exitcode < 0):
                print('Force terminating {parCam.name}')
                parCam.terminate()

    print('\nDone\n')


if __name__ == '__main__':
    doc="""
Script for running camera acquisition and providing a live display.

Can either run from commandline, or import functions for custom usage.

Commandline flags
-----------------
-h
    Show this help message and exit.
--ls
    List available cameras and exit.
-c, --cam-nums
    Space delimited list of cameras to use, or 'all' to use all available
    cameras. Use --ls flag to see available cameras.
--video-mode
    Determines resolution and colour space for image acquisition. Can be a
    PyCapture2.VIDEO_MODE code or a key for the VIDEO_MODES lookup dict.
    Defaults to 640x480 resolution and RGB colour space.
--frame-rate
    Frame rate for image acquisition. Can be a PyCapture2.FRAMERATE code or a
    key for the FRAMERATES lookup dict. Defaults to 30 fps.
--grab-mode
    Grab mode for image acquisition. Can be a PyCapture2.GRAB_MODE code or a
    key for the GRAB_MODES lookup dict. Defaults to BUFFER_FRAMES. Would not
    recommend changing from this as the alternative (DROP_FRAMES) is highly
    liable to drop frames (unsurprisingly).
-o, --output
    Path to output video file. If omitted, video writer will not be opened
    and further output flags are ignored.
--overwrite
    If output file already exists, will be overwritten if flag is specified,
    or an error will be raised if flag is omitted.
--output-encoder
    Encoder for output file: AVI, MJPG, or H264. If omitted, will attempt to
    determine from output file extension.
--output-quality
    Quality of output video: integer in range 0 to 100. Only applicable for
    MJPG encoder.
--output-size
    Space delimited list giving image width and height (in pixels). Only
    applicable for H264 encoder. Must match resolution specified in video
    mode. If omitted, will attempt to determine from video mode.
--output-bitrate
    Bitrate for output file. Only applicable for H264 encoder. If omitted,
    will use default value (see FlyCaptureUtils.Camera class).
--no-timestamps
    If specified, will NOT write timestamps (contained within image metadata)
    to csv file alongside output video file.
--embed-image-info
    Space delimited list of image properties to embed in top-left image pixels.
    See PyCaputre2 documentation or FlyCaptureUtils.Camera.openVideoWriter
    docstring for available properties. Note that a monochrome colour space
    MUST be specified by the video mode for the pixel values to be usable.
    Also note that embedded timestamps MUST be enabled to get 1394 cycle
    timestamps in the CSV file, regardless of whether the information is to be
    taken from the CSV or pixels. Default is to embed timestamps only.
    Pass flag without any arguments to disable embedded image info.
--pixel-format
    Determines colour conversion for image display. Only applicable if preview
    mode is enabled. Can be a PyCapture2.PIXEL_FORMAT code or a key for the
    PIXEL_FORMATS lookup dict. This does not affect the colour space of the
    image acquisition specified by the video mode, but it must be appropriate
    both for conversion from that space and for display within an OpenCV
    window. Defaults to 'BGR', which is appropriate both for conversion from
    the default RGB image acquisition space and for display in OpenCV.

Example usage (Windows Powershell)
----------------------------------
# Run single camera
> python run_camera.py -c 0

# Run single camera, save to video file
> python run_camera.py -c 0 -o test.avi

# Run multiple cameras, save to video files
> python run_camera.py -c 0 1 2 -o test.avi

# Run all available cameras, save to video files
> python run_camera.py -c all -o test.avi

# Timestamps are embedded in pixel data by default, but image must be
# monochrome for the values to be usable. The pixel format used for the live
# preview will need to be updated accordingly too.
> python run_camera.py -c 0 -o test.avi --embed-image-info timestamp `
    --video-mode VM_640x480Y8 --pixel-format MONO8

"""
    # Parse args
    parser = argparse.ArgumentParser(usage=doc,
                                     formatter_class=CustomFormatter)

    parser.add_argument('--ls', action='store_true',
                        help='List available cameras and exit')
    parser.add_argument('-c', '--cam-nums', nargs='+',
                        help='Index/indices of camera(s) to use')
    parser.add_argument('--video-mode', default='VM_640x480RGB',
                        help='PyCapture2.VIDEO_MODE code or lookup key')
    parser.add_argument('--frame-rate', default='FR_30',
                        help='PyCapture2.FRAMERATE code or lookup key')
    parser.add_argument('--grab-mode', default='BUFFER_FRAMES',
                        help='PyCapture2.GRAB_MODE code or lookup key')
    parser.add_argument('-o', '--output', help='Path to output video file')
    parser.add_argument('--overwrite', action='store_true',
                        help='Overwrite an existing output file')
    parser.add_argument('--output-encoder', choices=['AVI','MJPG','H264'],
                        help='Encoder for output (if omitted will try to '
                             'determine from output file extension)')
    parser.add_argument('--output-quality', type=int,
                        help='Value between 0-100. Only applicable for '
                              'MJPG format')
    parser.add_argument('--output-size', type=int, nargs=2,
                        help='WIDTH HEIGHT values (pixels). Only applicable '
                             'for H264 format')
    parser.add_argument('--output-bitrate', type=int,
                        help='Bitrate. Only applicable for H264 format')
    parser.add_argument('--no-timestamps', action='store_false',
                        help='Specify to NOT save timestamps to csv')
    parser.add_argument('--embed-image-info', nargs='*', default=['timestamp'],
                        choices=['all','timestamp','gain','shutter',
                                 'brightness','exposure','whiteBalance',
                                 'frameCounter','strobePattern','ROIPosition'],
                        help='List of properties to embed in image pixels')
    parser.add_argument('--pixel-format', default='BGR',
                        help='Image conversion format for display. '
                             'PyCapture2.PIXEL_FORMAT code or lookup key.')

    if not len(sys.argv) > 1:
        parser.print_help()
        sys.exit(0)

    args = parser.parse_args()

    # Check avialable cameras
    AVAILABLE_CAMS = getAvailableCameras()
    if not AVAILABLE_CAMS:
        raise OSError('No cameras found on bus!')

    # List cameras and exit if requested
    if args.ls:
        print('Cam\tSerial')
        for num_ser in AVAILABLE_CAMS:
            print('\t'.join(map(str, num_ser)))
        parser.exit()

    # Extract args
    cam_nums = args.cam_nums
    video_mode = check_enumerated_value(args.video_mode)
    frame_rate = check_enumerated_value(args.frame_rate)
    grab_mode = check_enumerated_value(args.grab_mode)
    outfile = args.output
    overwrite = args.overwrite
    output_encoder = args.output_encoder
    output_quality = args.output_quality
    output_size = args.output_size
    output_bitrate = args.output_bitrate
    no_timestamps = args.no_timestamps
    embed_image_info = args.embed_image_info
    pixel_format = check_enumerated_value(args.pixel_format)

    # Error check
    if not cam_nums:
       raise OSError('-c/--cam-nums argument is required')

    # Process and format args
    if 'all' in cam_nums:
        cam_nums = sorted([num_ser[0] for num_ser in AVAILABLE_CAMS])
    else:
        cam_nums = list(map(int, cam_nums))

    if len(cam_nums) > 1:
        mode = 'multi'
        print('Running multiple cameras in parallel')
    else:
        mode = 'single'
        cam_nums = cam_nums[0]  # unlist
        print('Running single camera')

    cam_kwargs = {}
    if video_mode is not None:
        cam_kwargs['video_mode'] = video_mode
    if frame_rate is not None:
        cam_kwargs['framerate'] = frame_rate
    if grab_mode is not None:
        cam_kwargs['grab_mode'] = grab_mode

    writer_kwargs = {}
    if outfile:
        writer_kwargs['overwrite'] = overwrite
        writer_kwargs['encoder'] = output_encoder
        if args.output_quality is not None:
            writer_kwargs['quality'] =output_quality
        if args.output_size is not None:
            writer_kwargs['img_size'] = output_size
        if args.output_bitrate is not None:
            writer_kwargs['bitrate'] = output_bitrate
        if args.embed_image_info is not None:
            writer_kwargs['embed_image_info'] = embed_image_info
        writer_kwargs['csv_timestamps'] = no_timestamps  # False if flag IS specified

    # Go
    if mode == 'single':
        main = single_main
    elif mode == 'multi':
        main = multi_main
    main(cam_nums, cam_kwargs, outfile, writer_kwargs, pixel_format)