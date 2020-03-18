# -*- coding: utf-8 -*-
"""
Run simultaneous video feeds from multiple cameras. Shows live feed via
OpenCV window, and provides option to record feeds to files.
"""

import os
import sys
import argparse
import cv2
import threading
import queue
import traceback
import numpy as np
from PyCapture2 import startSyncCapture

from FlyCaptureUtils import Camera, img2array, getAvailableCameras


class CustomFormatter(argparse.ArgumentDefaultsHelpFormatter,
                      argparse.RawTextHelpFormatter):
    """
    Combines argparse formatters
    """
    pass

def capture_func(cam, frame_queue, start_event, stop_event):
    """
    Function to be run from child thread. Acquires images from a single camera
    and passes them back to parent thread. Will close camera when done.

    Parameters
    ----------
    cam : FlyCaptureUtils.Camera instance
        Camera object - should be already instantiated.
    frame_queue : queue.Queue instance
        Queue will be used to pass images back to main thread.
    start_event : threading.Event instance
        Will block till event is set before starting image acquisition.
    stop_event : threading.Event instance
        Image acquisition will continue until event is set.
    """
    # Error handling for main run code in case of child thread crash
    try:
        # Block till start-event set
        start_event.wait()

        # Begin capture loop, keep going till stop-event set
        while not stop_event.is_set():
            ret, img = cam.getImage()
            if ret:
                try:
                    frame_queue.put_nowait(ret)
                except queue.Full:
                    pass

        # Stop capture but finish writing frames from buffer
        cam.stop_capture()
        while True:
            ret, img = cam.getImage()
            if not ret:
                break

    except Exception:
        traceback.print_exc()

    # Close camera
    cam.close()

def main(cam_nums, cam_kwargs, outfile, writer_kwargs):
    """
    Main function.

    Parameters
    ----------
    cam_nums : list of ints
        Indices of cameras to use.
    cam_kwargs : dict
        Keyword arguments to Camera class.
    outfile : str or None
        Output video file.
    writer_kwargs : dict
        Keyward arguments to Camera class's .openVideoWriter() method.
    """
    # Set up viewport array
    nCams = len(cam_nums)
    nRows = int(np.floor(np.sqrt(nCams)))
    nCols = int(np.ceil(nCams / nRows))
    viewports = np.empty(nRows * nCols, dtype=object)

    # Init cameras
    cams = []
    cam_handles = []
    for n in cam_nums:
        cam = Camera(n, **cam_kwargs)

        # Init video writer?
        if outfile:
            this_outfile = str(n).join(os.path.splitext(outfile))
            cam.openVideoWriter(this_outfile, **writer_kwargs)

        cams.append(cam)
        cam_handles.append(cam.cam)

    # Init threads and threading objects
    start_event = threading.Event()
    stop_event = threading.Event()
    threads = []
    frame_queues = []
    for cam in cams:
        q = queue.Queue(maxsize=1)
        t = threading.Thread(target=capture_func,
                             args=(cam, q, start_event, stop_event))
        threads.append(t)
        frame_queues.append(q)

    # Report ready
    input('Ready - Enter to begin')

    # Start threads (will block at start till event is set)
    for t in threads:
        t.start()

    # Open display window
    winName = 'Display'
    cv2.namedWindow(winName)

    # Error handling for main run code in case of main thread crash
    try:
        # Begin capture
        startSyncCapture(cam_handles)
        start_event.set()
        print('Esc to quit')

        # Begin display loop
        while True:
            # Collect frames from each thread
            for i, q in enumerate(frame_queues):
                try:
                    img = q.get_nowait()
                    viewports[i] = np.pad(img2array(img), [(2,), (2,), (0,)])
                except queue.Empty:
                    pass

            # Display
            dispArr = np.block(viewports.reshape(nRows, nCols).tolist())
            cv2.imshow(winName, dispArr)
            k = cv2.waitKey(1)

            # Check for quit
            if k == 27:
                stop_event.set()
                break

    except Exception:
        # Error - set events to try and stop child threads
        start_event.set()
        stop_event.set()
        traceback.print_exc()

    # Close display window
    cv2.destroyWindow(winName)

    # Wait for threds to finish
    for t in threads:
        t.join(timeout=3)

    # Done
    print('\nDone\n')


if __name__ == '__main__':
    # Parse args
    parser = argparse.ArgumentParser(usage=__doc__,
                                     formatter_class=CustomFormatter)

    parser.add_argument('--ls', action='store_true',
                        help='List available cameras and exit')
    parser.add_argument('-c', '--cam-nums', nargs='+', type=int,
                        help='Indices of cameras to use')
    parser.add_argument('-m', '--video-mode', default='VM_640x480RGB',
                        help='PyCapture2 video mode code or lookup key')
    parser.add_argument('-r', '--frame-rate', default='FR_30',
                        help='PyCapture2 framerate code or lookup key')
    parser.add_argument('--grab-mode', default='BUFFER_FRAMES',
                        help='PyCapture2 grab mode code or lookup key')
    parser.add_argument('-o', '--output',
                        help='Path to output video file basename')
    parser.add_argument('--overwrite', action='store_true',
                        help='Overwrite an existing output file')
    parser.add_argument('--output-format', choices=['AVI','MJPG','H264'],
                        help='File format for output (if omitted will try to '
                             'determine automatically)')
    parser.add_argument('--output-quality', type=int,
                        help='Value between 0-100. Only applicable for '
                             'MJPG format')
    parser.add_argument('--output-size', type=int, nargs=2,
                        help='WIDTH HEIGHT values (pixels). Only applicable '
                             'for H264 format')
    parser.add_argument('--output-bitrate', type=int,
                        help='Bitrate. Only applicable for H264 format')

    if not len(sys.argv) > 1:
        parser.print_help()
        parser.exit()

    args = parser.parse_args()

    if args.ls:
        print('Cam\tSerial')
        for cam_ser in getAvailableCameras():
            print('\t'.join(*cam_ser))
        parser.exit()

    cam_nums = args.cam_nums
    cam_kwargs = {'video_mode':args.video_mode,
                  'framerate':args.framerate,
                  'grab_mode':args.grab_mode}
    outfile = args.output

    # Further checks on args
    if len(cam_nums) < 2:
        raise OSError('Must specify at least 2 cam_nums')

    writer_kwargs = {}
    if outfile:
        writer_kwargs['overwrite'] = args.overwrite

        file_format = args.output_format
        if file_format is None:
            ext = os.path.splitext(outfile)[1].lower()  # case insensitive
            if ext == '.avi':
                file_format = 'AVI'
            elif ext == '.mp4':
                file_format = 'H264'
            else:
                raise ValueError('Cannot determine file_format automatically '
                                 f'from {ext} extension')
            print(f'Recording using {file_format} format')
        writer_kwargs['file_format'] = file_format

        if file_format == 'MJPG':
            if not args.output_quality:
                raise OSError('Must specify output quality for MJPG format')
            writer_kwargs['quality'] = args.output_quality
        elif file_format == 'H264':
            if not args.output_size:
                raise OSError('Must specify output size for H264 format')
            if not args.output_bitrate:
                raise OSError('Must specify bitrate for H264 format')
            writer_kwargs['width'] = args.output_size[0]
            writer_kwargs['height'] = args.output_size[1]
            writer_kwargs['bitrate'] = args.output_bitrate

    # Go
    main(cam_nums, cam_kwargs, outfile, writer_kwargs)
