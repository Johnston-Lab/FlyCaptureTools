# -*- coding: utf-8 -*-
"""
Run video feed from a single camera. Shows live feed via OpenCV window,
and provides option to record feed to file.
"""

import os
import sys
import argparse
import cv2
from FlyCaptureUtils import Camera, img2array, getAvailableCameras


class CustomFormatter(argparse.ArgumentDefaultsHelpFormatter,
                      argparse.RawTextHelpFormatter):
    """
    Combines argparse formatters
    """
    pass

def main(cam_num, cam_kwargs, outfile, writer_kwargs):
    """
    Main function.

    Parameters
    ----------
    cam_num : int
        Index of camera to use.
    cam_kwargs : dict
        Keyword arguments (except cam_num) to Camera class.
    outfile : str or None
        Output video file.
    writer_kwargs : dict
        Keyward arguments to Camera class's .openVideoWriter() method.
    """
    # Init camera
    cam = Camera(cam_num, **cam_kwargs)

    # Init video writer?
    if outfile:
        cam.openVideoWriter(outfile, **writer_kwargs)

    # Report ready
    input('Ready - Enter to begin')
    print('Esc to quit')

    # Open display window
    winName = 'Display'
    cv2.namedWindow(winName)

    # Start capture
    cam.startCapture()

    # Loop
    while True:
        ret, img = cam.getImage()
        if ret:
            cv2.imshow(winName, img2array(img))

        k = cv2.waitKey(1)
        if k == 27:
            break

    # Stop capture but finish writing frames from buffer
    cam.stopCapture()
    while True:
        ret, img = cam.getImage()
        if not ret:
            break

    # Close camera and exit
    cam.close()
    cv2.destroyWindow(winName)
    print('\nDone\n')


if __name__ == '__main__':
    # Parse args
    parser = argparse.ArgumentParser(usage=__doc__,
                                     formatter_class=CustomFormatter)

    parser.add_argument('--ls', action='store_true',
                        help='List available cameras and exit')
    parser.add_argument('-c', '--cam-num', type=int,
                        help='Index of camera to use')
    parser.add_argument('-m', '--video-mode', default='VM_640x480RGB',
                        help='PyCapture2 video mode code or lookup key')
    parser.add_argument('-r', '--frame-rate', default='FR_30',
                        help='PyCapture2 framerate code or lookup key')
    parser.add_argument('--grab-mode', default='BUFFER_FRAMES',
                        help='PyCapture2 grab mode code or lookup key')
    parser.add_argument('-o', '--output',
                        help='Path to output video file')
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
        for num_ser in getAvailableCameras():
            print('\t'.join(map(str, num_ser)))
        parser.exit()

    cam_num = args.cam_num
    cam_kwargs = {'video_mode':args.video_mode,
                  'framerate':args.frame_rate,
                  'grab_mode':args.grab_mode}
    outfile = args.output

    # Further checks on args
    if cam_num is None:
        raise OSError('Must specify cam_num')

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

    # Go
    main(cam_num, cam_kwargs, outfile, writer_kwargs)
