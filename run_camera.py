#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import argparse
import time
import traceback
import keyboard
from multiprocessing import Process, Event, Queue
from queue import Empty as QueueEmpty
from FlyCaptureUtils import Camera, img2array, getAvailableCameras

# OpenCV only needed for (optional) live preview, so allow for not having it
try:
    import cv2
    HAVE_OPENCV = True
except ImportError:
    HAVE_OPENCV = False


### Class definitions ###

class CustomFormatter(argparse.ArgumentDefaultsHelpFormatter,
                      argparse.RawTextHelpFormatter):
    "Combines argparse formatters"
    pass

class ParallelCamera(Process):
    def __init__(self, start_event, stop_event, cam_num, cam_kwargs, outfile,
                 writer_kwargs, *args, **kwargs):
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
        *args, **kwargs
            Further arguments passed to multiprocessing.Process

        Attributes
        ----------
        self.ready_event : multiprocessing.Event object
            Will be set when camera initialisation has finished. Can be used
            to signal main process when camera is ready to start acquisition.
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

        # Init further internal attributes
        self.ready_event = Event()
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
                cam.getImage()

        # Error encountered - pass up to main process
        except Exception as e:
            self.error_queue.put(e)

        ## Will reach here if stop event is set, or if error is encountered.
        ## Either way, close and finish up:
        # 1) Try to stop and close camera
        try:
            cam.stopCapture()
        except:
            pass
        try:
            cam.close()
        except:
            pass

        # 2) Close queues. We need to cancel queue joining otherwise child
        # process can block while trying to exit if queue wasn't
        # completely flushed.
        self.error_queue.close()
        self.error_queue.cancel_join_thread()


### Function definitions ###

def single_main(cam_num, cam_kwargs, outfile, writer_kwargs, preview=False,
                pixel_format='BGR'):
    """
    Main function for single camera operation.

    Parameters
    ----------
    cam_num : int
        Camera numer to use
    cam_kwargs : dict
        Keyword arguments to Camera class (excluding cam_num)
    outfile : str or None
        Output video file (ignored if preview == True)
    writer_kwargs : dict
        Keyword arguments to Camera class's .openVideoWriter() method
        (ignored if preview is True).
    preview : bool, optional
        If True, display live preview of video feed in OpenCV window. The
        default is False.
    pixel_format : PyCapture2.PIXEL_FORMAT value or str, optional
        Format to convert image to for preview display. Ignored if preview
        is not True. The default is BGR.
    """
    # Need OpenCV for preview
    if preview and not HAVE_OPENCV:
        raise ImportError('OpenCV required for preview mode')

    # Init camera
    cam = Camera(cam_num, **cam_kwargs)

    # Init video writer?
    if outfile is not None:
        cam.openVideoWriter(outfile, **writer_kwargs)

    # Report ready
    input('Ready - Enter to begin')

    # Open display window?
    if preview:
        winName = 'Preview'
        cv2.namedWindow(winName)

    # Start capture
    cam.startCapture()
    print('Running - Esc or q to quit')

    # Loop
    while True:
        ret, img = cam.getImage()
        if preview and ret:
            # Possible bug fix - converting image to array TWICE seems to
            # prevent image corruption?!
            img2array(img, pixel_format)
            frame = img2array(img, pixel_format)
            cv2.imshow(winName, frame)
            cv2.waitKey(1)

        if keyboard.is_pressed('q') or keyboard.is_pressed('esc'):
            break

    # Stop capture
    cam.stopCapture()

    # Close camera and exit
    cam.close()
    if preview:
        cv2.destroyWindow(winName)
    print('\nDone\n')


def multi_main(cam_nums, cam_kwargs, base_outfile, writer_kwargs):
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
    """
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
                                outfile, writer_kwargs, name=f'cam{cam_num}')
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
    # Otherwise, good to go
    else:
        input('Ready - Enter to begin')

    # Send go signal
    start_event.set()

    # Begin display loop - all in try block so we can kill child processes in
    # case of main process error
    print('Running - Esc or q to quit')
    try:
        KEEPGOING = True
        while KEEPGOING:
            # Check each camera process is still alive. Stop if not.
            for parCam in parCams:
                if not parCam.is_alive():
                    print(f'Camera ({parCam.name} died, exiting')
                    try:
                        e = parCam.error_queue.get(timeout=0.5)
                        print(e)
                    except QueueEmpty:
                        pass
                    KEEPGOING = False
                    break

            # Check for quit signal
            if keyboard.is_pressed('esc') or keyboard.is_pressed('q'):
                print('Quitting...')
                KEEPGOING = False

    except Exception:  # main process errored
        traceback.print_exc()

    ## Will reach here if user signals to stop, or if error encountered.
    ## Either way, stop and exit:
    # 1) Signal cameras to stop
    stop_event.set()

    # 2) Check processes have exited cleanly. Terminate them if not.
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
    Space delimited list of cameras to use, or 'all'. If only one camera
    specified, will be run in main process. If multiple cameras specified,
    will run each in parallel child process. If 'all' specified, will run
    all available cameras. Use --ls flag to see available cameras.

--video-mode
    Determines resolution and colour space for image acquisition. Can be a
    PyCapture2.VIDEO_MODE code or a key for the VIDEO_MODES lookup dict.
    Defaults to 640x480 resolution and RGB colour space.

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
    See PyCaputre2 documentation or FlyCaptureUtils.Camera.openVideoWriter
    docstring for available properties. Note that a monochrome colour space
    MUST be specified by the video mode for the pixel values to be usable.
    Also note that embedded timestamps MUST be enabled to get 1394 cycle
    timestamps in the CSV file, regardless of whether the information is to be
    taken from the CSV or pixels. Default is to embed timestamps only.

--preview
    Specify flag to run a live display of the camera feed in an OpenCV window.
    Note this is only available for single (not multi) camera operation.

--pixel-format
    Determines colour conversion for image display. Only applicable if preview
    mode is enabled. Can be a PyCapture2.PIXEL_FORMAT code or a key for the
    PIXEL_FORMATS lookup dict. This does not affect the colour space of the
    image acquisition specified by the video mode, but it must be appropriate
    both for conversion from that space and for display within an OpenCV
    window. Defaults to 'BGR', which is appropriate both for conversion from
    the default RGB image acquisition space and for display in OpenCV.

Example usage
-------------
# Run single camera, display live preview
> python run_camera.py -c 0 --preview

# Run single camera, save to video file
> python run_camera.py -c 0 -o test.avi

# Run multiple cameras in parallel, save to video files
> python run_camera.py -c 0 1 2 -o test.avi

# Run all available cameras in parallel
> python run_camera.py -c all -o test.avi

# Timestamps are embedded in pixel data by default, but image must be
# monochrome for the values to be usable. If also running a live preview,
# the pixel format will need to be updated accordingly too.
> python run_camera.py -c 0 -o test.avi --embed-image-info timestamp \\
    --video-mode VM_640x480Y8  --preview --pixel-format MONO8

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
    parser.add_argument('--embed-image-info', nargs='+', default=['timestamp'],
                        choices=['all','timestamp','gain','shutter',
                                 'brightness','exposure','whiteBalance',
                                 'frameCounter','strobePattern','ROIPosition'],
                        help='List of properties to embed in image pixels')
    parser.add_argument('--preview', action='store_true',
                        help='Show live preview (single camera mode only)')
    parser.add_argument('--pixel-format', default='BGR',
                        help='Image conversion format for live preview. '
                             'PyCapture2.PIXEL_FORMAT code or lookup key.')

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
    video_mode = args.video_mode
    frame_rate = args.frame_rate
    grab_mode = args.grab_mode
    outfile = args.output
    overwrite = args.overwrite
    output_encoder = args.output_encoder
    output_quality = args.output_quality
    output_size = args.output_size
    output_bitrate = args.output_bitrate
    no_timestamps = args.no_timestamps
    embed_image_info = args.embed_image_info
    preview = args.preview
    pixel_format = args.pixel_format

    # Error check
    if not cam_nums:
       raise OSError('-c/--cam-nums argument is required')

    if 'all' in cam_nums:
        cam_nums = sorted([num_ser[0] for num_ser in AVAILABLE_CAMS])
    else:
        cam_nums = list(map(int, cam_nums))

    if len(cam_nums) > 1:
        mode = 'multi'
        print('Running multiple cameras in parallel')
    else:
        mode = 'single'
        cam_num = cam_nums[0]  # unlist
        print('Running single camera')

    if mode == 'multi' and preview:
        raise OSError('Preview mode not supported for multi-camera operation')

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
        if output_quality is not None:
            writer_kwargs['quality'] = output_quality
        if output_size is not None:
            writer_kwargs['img_size'] = output_size
        if output_bitrate is not None:
            writer_kwargs['bitrate'] = output_bitrate
        if embed_image_info is not None:
            writer_kwargs['embed_image_info'] = embed_image_info
        writer_kwargs['csv_timestamps'] = no_timestamps  # False if flag IS specified

    # Go
    if mode == 'single':
        single_main(cam_num, cam_kwargs, outfile, writer_kwargs, preview, pixel_format)
    elif mode == 'multi':
        multi_main(cam_nums, cam_kwargs, outfile, writer_kwargs)
