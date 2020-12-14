# -*- coding: utf-8 -*-
"""
Run video feed from multiple cameras. Shows live feed via OpenCV window,
and provides option to record feed to file.
"""

import os
import argparse
import cv2
import numpy as np
import traceback
from threading import Thread, Event, Barrier
from queue import Queue, Full as QueueFull, Empty as QueueEmpty
from FlyCaptureUtils import (Camera, img2array, imgSize_from_vidMode,
                             imgDepth_from_pixFormat, getAvailableCameras)


class CustomFormatter(argparse.ArgumentDefaultsHelpFormatter,
                      argparse.RawTextHelpFormatter):
    """
    Combines argparse formatters
    """
    pass


def run_func(barrier, start_event, stop_event, frame_queue,
             cam_num, cam_kwargs, outfile, writer_kwargs, pixel_format):
    """
    Target function - execute as child thread. Runs camera acquisition and
    passess images back up to main thread for display.

    Arguments
    ---------
    barrier : Barrier object
        Child thread will wait at barrier once camera is initialised. This
        can be used to signal main thread when all childs have initialised.
    start_event : Event object
        Child thread will block after barrier till start event is set. Allows
        main thread to signal to start acquisition.
    stop_event : Event object
        Child thread will continue execution till stop event is set. Allows
        main thread to signal to stop acquisition.
    frame_queue : Queue object
        Queue will be used to pass images back up to main thread for display.

    All other arguments as per main function.

    """

    # Init cam
    cam = Camera(cam_num, **cam_kwargs)

    # Init video writer?
    if outfile is not None:
        cam.openVideoWriter(outfile, **writer_kwargs)

    # Signal main thread we're ready by waiting for barrier
    barrier.wait()

    # Wait for start event to signal go
    start_event.wait()

    # Go!
    cam.startCapture()
    while not stop_event.is_set():
        ret, img = cam.getImage()
        if ret:
            # Possible bug fix - converting image to array TWICE seems to
            # prevent image corruption?!
            img2array(img, pixel_format)
            arr = img2array(img, pixel_format).copy()
            # Append to queue
            try:
                frame_queue.put_nowait(arr)
            except QueueFull:
                pass

    # Stop & close camera
    cam.stopCapture()
    cam.close()


def main(cam_nums, cam_kwargs, base_outfile, writer_kwargs, pixel_format):
    """
    Main function.

    Parameters
    ----------
    cam_nums : list
        List of camera numbers to use.
    cam_kwargs : dict
        Keyword arguments to Camera class (excluding cam_num).
    outfile : str or None
        Output video file.
    writer_kwargs : dict
        Keyward arguments to Camera class's .openVideoWriter() method.
    pixel_format : PyCapture2.PIXEL_FORMAT value or str
        Format to convert image to for display.
    """
    # Set up viewport for display
    nCams = len(cam_nums)
    nRows = np.floor(np.sqrt(nCams)).astype(int)
    nCols = np.ceil(nCams/nRows).astype(int)
    imgW, imgH = imgSize_from_vidMode(cam_kwargs['video_mode'])  # TODO - handle None
    imgD = imgDepth_from_pixFormat(pixel_format)
    viewport = np.zeros([imgH*nRows, imgW*nCols, imgD], dtype='uint8').squeeze()

    # Set up events and barriers
    barrier = Barrier(nCams+1)
    start_event = Event()
    stop_event = Event()

    # Set up camera threads and queues
    cam_threads = []
    frame_queues = []
    for cam_num in cam_nums:

        if base_outfile is not None:
            _outfile, ext = os.path.splitext(base_outfile)
            outfile = _outfile + f'-cam{cam_num}' + ext
        else:
            outfile = None

        frame_queue = Queue(maxsize=1)
        args = (barrier, start_event, stop_event, frame_queue,
                cam_num, cam_kwargs, outfile, writer_kwargs, pixel_format)
        cam_thread = Thread(target=run_func, args=args, name=f'cam{cam_num}')
        cam_thread.start()

        cam_threads.append(cam_thread)
        frame_queues.append(frame_queue)

    # Wait at barrier till all child threads signal ready
    try:
        barrier.wait(timeout=5)
    except:
        raise RuntimeError('Child threads failed to initialise')
    input('Ready - Enter to begin')
    print('Select window then Esc to quit')

    # Open display window
    winName = 'Display'
    cv2.namedWindow(winName, cv2.WINDOW_NORMAL | cv2.WINDOW_KEEPRATIO)

    # Send go signal
    start_event.set()

    # Begin display loop - all in try block so we can kill child threads in
    # case of main thread error
    try:
        KEEPGOING = True
        while KEEPGOING:
            for cam_num in range(nCams):
                i,j = np.unravel_index(cam_num, (nRows, nCols))
                cam_thread = cam_threads[cam_num]
                frame_queue = frame_queues[cam_num]

                # Check thread is still alive - stop if not
                if not cam_thread.is_alive():
                    print(f'Camera thread ({cam_thread.name}) died, exiting')
                    KEEPGOING = False
                    break

                # Try to retrieve frame from child thread
                try:
                    frame = frame_queue.get_nowait()
                except QueueEmpty:
                    continue

                # Allocate to array
                viewport[i*imgH:(i+1)*imgH, j*imgW:(j+1)*imgW, ...] = frame

            # Display
            cv2.imshow(winName, viewport)

            # Display
            k = cv2.waitKey(1)
            if k == 27:
                KEEPGOING = False

    except Exception:  # main thread errored
        traceback.print_exc()

    # Stop
    stop_event.set()

    # Clear window and exit
    cv2.destroyWindow(winName)
    for cam_thread in cam_threads:
        try:
            cam_thread.join(timeout=3)
        except RuntimeError:
            print('Failed to close camera thread ({cam_thread.name})')
    print('\nDone\n')


if __name__ == '__main__':
    # Parse args
    parser = argparse.ArgumentParser(usage=__doc__,
                                     formatter_class=CustomFormatter)

    parser.add_argument('--ls', action='store_true',
                        help='List available cameras and exit')
    parser.add_argument('-c', '--cam-nums', type=int, nargs='+',
                        help='Index of camera to use. Omit to use all.')
    parser.add_argument('-m', '--video-mode', default='VM_640x480RGB',
                        help='PyCapture2 video mode code or lookup key')
    parser.add_argument('-r', '--frame-rate', default='FR_30',
                        help='PyCapture2 framerate code or lookup key')
    parser.add_argument('--grab-mode', default='BUFFER_FRAMES',
                        help='PyCapture2 grab mode code or lookup key')
    parser.add_argument('-o', '--output', help='Path to output video file')
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
    parser.add_argument('--embed-image-info', nargs='*',
                        default=['timestamp','frameCounter'],
                        help='List of properties to embed in image pixels')
    parser.add_argument('--csv-timestamps', action='store_true',
                        help='Specify to save timestamps to csv')
    parser.add_argument('--pixel-format', default='BGR',
                        help='Image conversion format for display')

    args = parser.parse_args()

    if args.ls:
        print('Cam\tSerial')
        for num_ser in getAvailableCameras():
            print('\t'.join(map(str, num_ser)))
        parser.exit()

    cam_nums = args.cam_nums
    if cam_nums is None:
        cam_nums = [num_ser[0] for num_ser in getAvailableCameras()]

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
        writer_kwargs['file_format'] = args.output_format
        if args.output_quality is not None:
            writer_kwargs['quality'] = args.output_quality
        if args.output_size is not None:
            writer_kwargs['img_size'] = args.output_size
        if args.output_bitrate is not None:
            writer_kwargs['bitrate'] = args.output_bitrate
        writer_kwargs['embed_image_info'] = args.embed_image_info
        writer_kwargs['csv_timestamps'] = args.csv_timestamps

    pixel_format = args.pixel_format

    # Go
    main(cam_nums, cam_kwargs, outfile, writer_kwargs, pixel_format)
