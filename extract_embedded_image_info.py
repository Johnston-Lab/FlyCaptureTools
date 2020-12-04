# -*- coding: utf-8 -*-
"""
Functions may be used to extract embedded image information from video pixels.
Can import functions, or run script from commandline.
"""

import os
import csv
import warnings
import argparse
import numpy as np
from moviepy.editor import VideoFileClip

# List of all possible fields
PROPERTIES = ['timestamp', 'gain', 'shutter', 'brightness', 'exposure',
              'whiteBalance', 'frameCounter', 'strobePattern',
              'GPIOPinState', 'ROIPosition']

class CustomFormatter(argparse.ArgumentDefaultsHelpFormatter,
                      argparse.RawTextHelpFormatter):
    """
    Combines argparse formatters
    """
    pass

def extractInfo(frame, properties):
    """
    Extracts embedded image properties from frame pixels.

    Parameters
    ----------
    frame : numpy array, required
        Frame image as numpy array. Should have uint8 datatype - will be
        converted if it doesn't. Image should be monochrome - it may still be
        given as RGB array, but all colour channels must be identical.
    properties : list or 'all', required
        List of properties to extract. Alternatively, specify string 'all'
        to extract all possible properties. Properties must match those that
        were embedded in image pixels. See PROPERTIES global variable for
        list of options.

    Returns
    -------
    res : dict
        Extracted values for each property, keyed by property name.
        Timestamp and ROIPosition properties are represented as dicts of
        multiple values, other properties are represented directly.
    """    
    # Use all properties if requested
    if (properties == 'all') or ('all' in properties):
        properties = PROPERTIES
        
    # Convert image to uint8 if necessary
    if not frame.dtype == 'uint8':
        warnings.warn('Converting frame to uint8')
        frame = frame.dtype()
    
    # Assert frame is grayscale
    if frame.ndim == 3:
        for ii in range(1, frame.shape[2]):  
            if not np.all(frame[...,0] == frame[...,ii]):
                raise ValueError('Image must be grayscale')
        frame = frame[...,0]
        
    # Assert requested fields are valid names
    for prop in properties:
        if prop not in PROPERTIES:
            raise ValueError(f'\{property}\ not a valid proptery name')
        
    # Pre-allocate dict for storing results
    res = {}
        
    # We now need to check properties IN ORDER    
    idx = 0
    for prop in PROPERTIES:
        # Skip properties not requested
        if prop not in properties:
            continue
        
        # Extract pixels and convert to binary string
        data = frame[0,idx:(idx+4)]
        b = ''.join(np.binary_repr(x, width=8) for x in data)
        idx += 4
        
        # Timestamps need some special handling
        if prop == 'timestamp':
            second_count = int(b[:7], 2)
            cycle_count = int(b[7:20], 2)
            cycle_offset = int(b[20:], 2)
            cycle_offset_as_count = cycle_offset / 3072
            cycle_seconds = (cycle_count + cycle_offset_as_count) / 8000            
            res['timestamp'] = {'second_count':second_count,
                                'cycle_count':cycle_count,
                                'cycle_offset':cycle_offset,
                                'cycle_seconds':cycle_seconds}
            
        # ROI position also needs special handling
        elif prop == 'ROIPosition':
            res['ROIPosition'] = {'left':int(b[:2], 2), 'top':int(b[2:], 2)}
            
        # All other fields, just convert straight away
        else:
            res[prop] = int(b, 2)
            
    # Return
    return res


def processClip(filepath, properties):
    """
    Extract properties for all frames in a given clip.

    Parameters
    ----------
    filepath : str, required
        Filepath to clip.
    properties : list or string 'all', required
        As per extractInfo function.

    Yields
    -------
    res
        Generator of dicts, each representing properties for a single frame.
    """
    # Load clip
    clip = VideoFileClip(filepath)
    
    # Loop frames, yield info for each    
    for frame in clip.iter_frames():
        yield extractInfo(frame, properties)

            
if __name__ == '__main__':
    
    # Parse args
    parser = argparse.ArgumentParser(usage=__doc__,
                                     formatter_class=CustomFormatter)

    parser.add_argument('-i', '--input', required=True,
                        help='Path to input video file')
    parser.add_argument('-p', '--properties', required=True, nargs='+',
                        help='List of properties to extract from frames')
    parser.add_argument('-o', '--output', required=True,
                        help='Path to output csv file')
    
    args = parser.parse_args()
    infile = args.input
    properties = args.properties
    outfile = args.output
    if not os.path.splitext(outfile)[1]:
        outfile += '.csv'
    
    # Open outfile
    fd = open(outfile, 'w')
    
    # Process & write out
    res = processClip(infile, properties)
    for i, row in enumerate(res):
        
        # Timestamps and ROIPosition need a bit of re-formatting
        if 'timestamp' in row.keys():
            for k, val in row['timestamp'].items():
                row[f'timestamp.{k}'] = val
            row.pop('timestamp')
            
        if 'ROIPosition' in row.keys():
            for k, val in row['ROIPosition'].items():
                row[f'ROIPosition.{k}'] = val
            row.pop('ROIPosition')
            
        # On 1st iter, open csv writer and write headers
        if i == 0:
            writer = csv.DictWriter(fd, fieldnames=row.keys(), delimiter=',',
                                    lineterminator='\n')
            writer.writeheader()
            
        # Write data
        writer.writerow(row)
        
    # Close outfile and finish
    fd.close()    