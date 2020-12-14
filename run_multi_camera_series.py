# -*- coding: utf-8 -*-
"""
Run video feed from multiple cameras. Shows live feed via OpenCV window,
and provides option to record feed to file.
"""

import os
import argparse
import cv2
import numpy as np
from FlyCaptureUtils import (Camera, img2array, imgDepth_from_pixFormat,
                             getAvailableCameras)


class CustomFormatter(argparse.ArgumentDefaultsHelpFormatter,
                      argparse.RawTextHelpFormatter):
    """
    Combines argparse formatters
    """
    pass


def main(cam_nums, cam_kwargs, base_outfile, writer_kwargs, pixel_format):
    """
    Main function.

    Parameters
    ----------
    cam_kwargs : dict
        Keyword arguments to Camera class (excluding cam_num).
    outfile : str or None
        Output video file.
    writer_kwargs : dict
        Keyward arguments to Camera class's .openVideoWriter() method.
    pixel_format : PyCapture2.PIXEL_FORMAT value or str
        Format to convert image to for display.
    """

    # Set up cameras
    cams = []
    for cam_num in cam_nums:
        # Init
        cam = Camera(cam_num, **cam_kwargs)

        # Init video writer?
        if base_outfile is not None:
            _outfile, ext = os.path.splitext(base_outfile)
            outfile = _outfile + f'-cam{cam_num}' + ext
            cam.openVideoWriter(outfile, **writer_kwargs)

        # Append to list
        cams.append(cam)

    # Set up viewport for display
    nCams = len(cam_nums)
    nRows = np.floor(np.sqrt(nCams)).astype(int)
    nCols = np.ceil(nCams/nRows).astype(int)
    imgW, imgH = cams[0].img_size
    imgD = imgDepth_from_pixFormat(pixel_format)
    viewport = np.zeros([imgH*nRows, imgW*nCols, imgD], dtype='uint8').squeeze()

    # Report ready
    input('Ready - Enter to begin')
    print('Select window then Esc to quit')

    # Open display window
    winName = 'Display'
    cv2.namedWindow(winName, cv2.WINDOW_NORMAL | cv2.WINDOW_KEEPRATIO)

    # Start capture
    for cam in cams:
        cam.startCapture()

    # Loop
    while True:
        for cam_num, cam in enumerate(cams):
            i,j = np.unravel_index(cam_num, (nRows, nCols))
            ret, img = cam.getImage()
            if ret:
                # Possible bug fix - converting image to array TWICE seems to
                # prevent image corruption?!
                img2array(img, pixel_format)
                arr = img2array(img, pixel_format).copy()
                # Allocate to array
                viewport[i*imgH:(i+1)*imgH, j*imgW:(j+1)*imgW, ...] = arr

        # Concat images, return colour dim to 2nd axis
        cv2.imshow(winName, viewport)

        # Display
        k = cv2.waitKey(1)
        if k == 27:
            break

    # Stop & close cameras
    for cam in cams:
        cam.stopCapture()
        cam.close()

    # Clear window and exit
    cv2.destroyWindow(winName)
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
