#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import inspect
import argparse
import cv2
import numpy as np
import traceback
from multiprocessing import Process, Barrier, Event, Queue
from queue import Full as QueueFull, Empty as QueueEmpty
from FlyCaptureUtils import (Camera, img2array, imgSize_from_vidMode,
                             imgDepth_from_pixFormat, getAvailableCameras)


### Class definitions ###

class CustomFormatter(argparse.ArgumentDefaultsHelpFormatter,
                      argparse.RawTextHelpFormatter):
    "Combines argparse formatters"
    pass

class ParallelCamera(Process):
    def __init__(self, ready_barrier, start_event, stop_event, cam_num,
                 cam_kwargs, outfile, writer_kwargs, pixel_format,
                 *args, **kwargs):
        """
        Class supports running camera within parallel child process.

        Arguments
        ---------
        ready_barrier : Barrier object
            Child process will wait at barrier once camera is initialised. This
            can be used to signal main process when all children have
            initialised.
        start_event : Event object
            Child process will block after barrier till start event is set.
            Allows main process to signal to start acquisition.
        stop_event : Event object
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
        self.frame_queue : Queue object
            Queue will pass images back up to main process for display.
        self.error_queue : Queue object
            Queue will pass error instances back up to main process.
        """
        # Allocate args to class
        self.ready_barrier = ready_barrier
        self.start_event = start_event
        self.stop_event = stop_event
        self.cam_num = cam_num
        self.cam_kwargs = cam_kwargs
        self.outfile = outfile
        self.writer_kwargs = writer_kwargs
        self.pixel_format = pixel_format

        # Init further internal queues
        self.frame_queue = Queue(maxsize=1)
        self.error_queue = Queue()

        # Super call implements inheritance from multiprocessing.Process
        super(self).__init__(*args, **kwargs)


    def run(self):
        """
        Overwrite multiprocessing.Process.run method.  Gets called in its
        place when the process's .start() method is called.
        """
        # Init cam
        cam = Camera(self.cam_num, **self.cam_kwargs)

        # Init video writer?
        if self.outfile is not None:
            cam.openVideoWriter(self.outfile, **self.writer_kwargs)

        # Signal main process we're ready by waiting for barrier
        self.ready_barrier.wait(timeout=10)

        # Wait for start event to signal go
        self.start_event.wait()

        # Go!
        try:
            cam.startCapture()
            while not self.stop_event.is_set():
                ret, img = cam.getImage()
                if ret:
                    # Possible bug fix - converting image to array TWICE seems
                    # to prevent image corruption?!
                    img2array(img, self.pixel_format)
                    frame = img2array(img, self.pixel_format).copy()  # TODO is copying necessary?
                    # Append to queue
                    try:
                        self.frame_queue.put_nowait(frame)
                    except QueueFull:
                        pass

            # Stop & close camera
            cam.stopCapture()
            cam.close()

            # Close queue. We need to cancel queue joining otherwise child process
            # can block while trying to exit if queue wasn't completely flushed.
            self.frame_queue.close()
            self.frame_queue.cancel_join_thread()

        # Error encountered - pass up to main process, and try to close camera
        except Exception as e:
            self.error_queue.put(e)
            try:
                cam.close()
            except:
                pass


### Function definitions ###

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
    input('Ready - Enter to begin')
    print('Select window then Esc to quit')

    # Open display window
    winName = 'Display'
    cv2.namedWindow(winName)

    # Start capture
    cam.startCapture()

    # Loop
    while True:
        ret, img = cam.getImage()
        if ret:
            # Possible bug fix - converting image to array TWICE seems to
            # prevent image corruption?!
            img2array(img, pixel_format)
            frame = img2array(img, pixel_format).copy()  # TODO is copying necessary?
            cv2.imshow(winName, frame)

        k = cv2.waitKey(1)
        if k == 27:
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
    ready_barrier = Barrier(nCams+1)
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

        parCam = ParallelCamera(
            ready_barrier, start_event, stop_event, cam_num, cam_kwargs,
            outfile, writer_kwargs, pixel_format, name=f'cam{cam_num}',
            daemon=True
            )
        parCam.start()
        parCams.append(parCam)

    # Wait at barrier till all child processs signal ready
    try:
        ready_barrier.wait(timeout=5)
    except Exception:
        raise RuntimeError('Child processes failed to initialise')
    input('Ready - Enter to begin')
    print('Select window then Esc to quit')

    # Open display window
    winName = 'Display'
    cv2.namedWindow(winName, cv2.WINDOW_NORMAL | cv2.WINDOW_KEEPRATIO)

    # Send go signal
    start_event.set()

    # Begin display loop - all in try block so we can kill child processs in
    # case of main process error
    try:
        KEEPGOING = True
        while KEEPGOING:
            for cam_num, parCam in zip(cam_nums, parCams):

                # Check process is still alive - stop if not
                try:
                    e = parCam.error_queue.get_nowait()
                    print(f'Camera process ({parCam.name}) died, exiting')
                    print(e)
                    KEEPGOING = False
                    break
                except QueueEmpty:
                    pass

                # Try to retrieve frame from child process
                try:
                    frame = parCam.frame_queue.get_nowait()
                except QueueEmpty:
                    continue

                # Allocate to array
                i,j = np.unravel_index(cam_num, (nRows, nCols))
                viewport[i*imgH:(i+1)*imgH, j*imgW:(j+1)*imgW, ...] = frame

            # Display
            cv2.imshow(winName, viewport)

            # Display
            k = cv2.waitKey(1)
            if k == 27:
                KEEPGOING = False

    except Exception:  # main process errored
        traceback.print_exc()

    # Stop
    stop_event.set()

    # Clear window and exit
    cv2.destroyWindow(winName)
    for parCam in parCams:
        parCam.join(timeout=1)
        if (parCam.exitcode is None) or (parCam.exitcode < 0):
            parCam.terminate()

    print('\nDone\n')


if __name__ == '__main__':
    doc="""
Script for running camera acquisition and providing a live display.

Can either run from commandline, or import functions for custom usage.

Commandline Flags
-----------------
-h
    Show this help message and exit.

--ls
    List available cameras and exit.

-c, --cam-nums
    Space delimited list of cameras to use. If omitted, defaults to all
    available cameras if camera mode is 'multi', or raises an error if camera
    mode is 'single'. Must be specified if camera mode is not. Use --ls flag
    to see available camera numbers.

-m, --mode
    Operation mode: 'single' or 'multi'. If 'single', a single camera is run in
    the main process. If 'multi', multiple cameras are run each in their own
    parallel child process. If omitted, defaults to 'single' if only one camera
    number is specified, or 'multi' if multiple camera numbers are specified.
    Must be specified if camera numbers are not.

--video-mode
    Determines resolution and colour space for image acquisition. Can be a
    PyCapture2.VIDEO_MODE code or a key for the VIDEO_MODES lookup dict.
    Default to 640x480 resolution and RGB colour space.

--frame-rate
    Frame rate for image acquisition. Can be a PyCapture2.FRAMERATE code or a
    key for the FRAMERATES lookup dict. Defaults to 30 fps.

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
    See PyCaputre2 documentation FlyCaptureUtils.Camera.openVideoWriter docstring for . Note that a
    monochrome colour space MUST be specified by the video mode for the pixel
    values to be usable. Default is not to embed anything.

--pixel-format
    Determines colour conversion for image display. Can be a
    PyCapture2.PIXEL_FORMAT code or a key for the PIXEL_FORMATS lookup dict.
    This does not affect the colour space of the image acquisition specified by
    the video mode, but it must be appropriate both for conversion from that
    space and for display within an OpenCV window. Defaults to 'BGR', which is
    appropriate both for conversion from the default RGB image acquisition
    space and for display in OpenCV.

"""
    # Parse args



    parser = argparse.ArgumentParser(usage=doc,
                                     formatter_class=CustomFormatter)

    parser.add_argument('--ls', action='store_true',
                        help='List available cameras and exit')
    parser.add_argument('-c', '--cam-nums', type=int, nargs='+',
                        help='Index/indices of camera(s) to use')
    parser.add_argument('-m', '--mode', choices=['single','multi'],
                        help='Whether to run one or multiple cameras')
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
    parser.add_argument('--embed-image-info', nargs='+',
                        choices=['all','timestamp','gain','shutter',
                                 'brightness','exposure','whiteBalance',
                                 'frameCounter','strobePattern','ROIPosition'],
                        help='List of properties to embed in image pixels')
    parser.add_argument('--pixel-format', default='BGR',
                        help='Image conversion format for display. '
                             'PyCapture2.PIXEL_FORMAT code or lookup key.')

    args = parser.parse_args()

    # Check avialable cameras. List them and exit if requested
    available_cams = getAvailableCameras()
    if args.ls:
        print('Cam\tSerial')
        for num_ser in getAvailableCameras():
            print('\t'.join(map(str, num_ser)))
        parser.exit()
    elif not available_cams:
        raise OSError('No cameras found on bus!')

    # Set default cam nums and cam modes, dependent on each other
    if not args.mode:
        if not args.cam_nums:
            raise argparse.ArgumentTypeError(
                'Must specify camera number(s) if not specifying camera mode'
                )
        elif len(args.cam_nums) == 1:
            args.cam_mode = 'single'
        elif len(args.cam_nums) > 1:
            args.cam_mode = 'multi'

    if not args.cam_nums:
        if args.mode == 'single':
            raise argparse.ArgumentTypeError(
                'Must specify a camera number if camera mode is \'single\''
                )
        elif args.mode == 'multi':
            args.cam_nums = [num for (num, ser) in getAvailableCameras()]

    # Extract args
    cam_nums = args.cam_nums
    if args.mode == 'single':
        if len(cam_nums) > 1:
            raise argparse.ArgumentTypeError(
                'Can only specify one camera if camera mode is \'single\''
                )
        else:
            cam_nums = cam_nums[0]

    cam_kwargs = {}
    if args.video_mode is not None:
        cam_kwargs['video_mode'] = args.video_mode
    if args.frame_rate is not None:
        cam_kwargs['framerate'] = args.frame_rate
    if args.grab_mode is not None:
        cam_kwargs['grab_mode'] = args.grab_mode

    outfile = args.output
    writer_kwargs = {}
    if outfile:
        writer_kwargs['overwrite'] = args.overwrite
        writer_kwargs['encoder'] = args.output_encoder
        if args.output_quality is not None:
            writer_kwargs['quality'] = args.output_quality
        if args.output_size is not None:
            writer_kwargs['img_size'] = args.output_size
        if args.output_bitrate is not None:
            writer_kwargs['bitrate'] = args.output_bitrate
        writer_kwargs['embed_image_info'] = args.embed_image_info
        writer_kwargs['csv_timestamps'] = not args.no_timestamps

    pixel_format = args.pixel_format

    # Go
    if args.mode == 'single':
        main = single_main
    elif args.mode == 'multi':
        main = multi_main
    main(cam_nums, cam_kwargs, outfile, writer_kwargs, pixel_format)