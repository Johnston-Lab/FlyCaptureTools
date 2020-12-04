# -*- coding: utf-8 -*-
"""
Run video feed from a single camera. Shows live feed via OpenCV window,
and provides option to record feed to file.
"""

import argparse
import cv2
from FlyCaptureUtils import Camera, img2array, getAvailableCameras


class CustomFormatter(argparse.ArgumentDefaultsHelpFormatter,
                      argparse.RawTextHelpFormatter):
    """
    Combines argparse formatters
    """
    pass

def main(cam_kwargs, outfile, writer_kwargs, pixel_format):
    """
    Main function.

    Parameters
    ----------
    cam_kwargs : dict
        Keyword arguments to Camera class.
    outfile : str or None
        Output video file.
    writer_kwargs : dict
        Keyword arguments to Camera class's .openVideoWriter() method.
    pixel_format : PyCapture2.PIXEL_FORMAT value or str
        Format to convert image to for display.
    """
    # Init camera
    cam = Camera(**cam_kwargs)

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
            arr = img2array(img, pixel_format)
            cv2.imshow(winName, arr)

        k = cv2.waitKey(1)
        if k == 27:
            break

    # Stop capture
    cam.stopCapture()

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

    if args.cam_num is None:
        raise argparse.ArgumentTypeError('cam_num is required')

    cam_kwargs = {}
    cam_kwargs['cam_num'] = args.cam_num
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
    main(cam_kwargs, outfile, writer_kwargs, pixel_format)
