#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Contains functions for running camera capture (from either one or multiple
cameras), and provides a commandline user interface.
"""

import os
import sys
import argparse
import keyboard
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


### Function definitions ###

def main(cam_nums, cam_kwargs, base_outfile, writer_kwargs, preview=False,
          pixel_format='BGR'):
    """
    Main function for single camera operation.

    Parameters
    ----------
    cam_nums : list
        List of camera numbers to use.
    cam_kwargs : dict
        Keyword arguments to Camera class (excluding cam_num)
    base_outfile : str or None
        Output video file name. If multiple cameras are specified, the camera
        numbers will be appended to the filename. If only one camera is
        specified, the filename will be used as is.
    writer_kwargs : dict
        Keyword arguments to Camera class's .openVideoWriter() method.
    preview : bool, optional
        If True, display live preview of video feed in OpenCV window. Only
        allowable for single camera operation, and will raise an error if set
        to True with multiple cameras. The default is False.
    pixel_format : PyCapture2.PIXEL_FORMAT value or str, optional
        Format to convert image to for preview display. Ignored if preview
        is not True. The default is BGR.
    """
    # Check if we have one or multiple cameras
    cam_mode = 'multi' if len(cam_nums) > 1 else 'single'

    # Preview mode only supported for single cam operation
    if cam_mode == 'multi' and preview:
        raise Exception('Preview mode not supported for multi-camera operation')

    # Need OpenCV for preview
    if preview and not HAVE_OPENCV:
        raise ImportError('OpenCV required for preview mode')

    # Set up cameras
    cams = []
    for cam_num in cam_nums:
        if (cam_mode == 'multi') and (base_outfile is not None):
            _outfile, ext = os.path.splitext(base_outfile)
            outfile = _outfile + f'-cam{cam_num}' + ext
        else:
            outfile = base_outfile

        these_cam_kwargs = cam_kwargs.copy()
        these_cam_kwargs['cam_num'] = cam_num

        cam = Camera(**these_cam_kwargs)
        if outfile:
            cam.openVideoWriter(outfile, **writer_kwargs)

        cams.append(cam)

    # Report ready
    print('Ready - Enter to begin')
    keyboard.wait('enter')

    # Open display window?
    if preview:
        winName = 'Preview'
        cv2.namedWindow(winName)

    # Start
    for cam in cams:
        cam.startCapture()

    # Begin main loop
    print('Running - Esc or q to quit')
    KEEPGOING = True
    while KEEPGOING:
        # Acquire images
        for cam in cams:
            ret, img = cam.getImage()

        # Display (single-cam + preview mode only)
        if ret and preview:
            # Possible bug fix - converting image to array TWICE seems to
            # prevent image corruption?!
            img2array(img, pixel_format)
            frame = img2array(img, pixel_format)
            cv2.imshow(winName, frame)
            cv2.waitKey(1)

        # Check for quit signal
        if keyboard.is_pressed('esc') or keyboard.is_pressed('q'):
            print('Quitting...')
            KEEPGOING = False

    # Stop and exit
    for cam in cams:
        cam.stopCapture()
        cam.close()

    if preview:
        cv2.destroyWindow(winName)

    print('\nDone\n')




if __name__ == '__main__':
    doc="""
Script for running camera acquisition.

Can either run from commandline, or import main function for custom usage.

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

# Run multiple cameras, save to video files
> python run_camera.py -c 0 1 2 -o test.avi

# Run all available cameras, save to video files
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

    # If no args, print help and exit
    if not len(sys.argv) > 1:
        parser.print_help()
        sys.exit(0)

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

    # Process and format args
    if 'all' in cam_nums:
        cam_nums = sorted([num_ser[0] for num_ser in AVAILABLE_CAMS])
        print('Using: ' + ', '.join([f'cam{n}' for n in cam_nums]))
    else:
        cam_nums = list(map(int, cam_nums))

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
    main(cam_nums, cam_kwargs, outfile, writer_kwargs, preview, pixel_format)
