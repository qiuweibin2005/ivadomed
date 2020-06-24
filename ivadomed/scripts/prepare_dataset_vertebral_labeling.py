#!/usr/bin/env python
##############################################################
#
# This script is used to create a dataset with (i) mid-sagittal image and
# (ii) heatmap of disc labels associated with the mid-sagittal image.
#
# Usage: python scripts/automate_training.py -p bids_path -s T2w -a -1
#
##############################################################


import argparse
import ivadomed.utils as imed_utils
import ivadomed.preprocessing as imed_preprocessing
import nibabel as nib
import numpy as np
import os
import scipy


def gaussian_kernel(kernlen=10):
    """
    Create a 2D gaussian kernel with user-defined size.

    Args:
        kernlen (int): size of kernel

    Returns:
        ndarray: a 2D array of size (kernlen,kernlen)
    """

    x = np.linspace(-1, 1, kernlen + 1)
    kern1d = np.diff(scipy.stats.norm.cdf(x))
    kern2d = np.outer(kern1d, kern1d)
    return kern2d / kern2d.sum()


def heatmap_generation(image, kernel_size):
    """
    Generate heatmap from image containing sing voxel label using
    convolution with gaussian kernel
    Args:
        image (ndarray): 2D array containing single voxel label
        kernel_size (int): size of gaussian kernel

    Returns:
        ndarray: 2D array heatmap matching the label.

    """
    kernel = gaussian_kernel(kernel_size)
    map = scipy.signal.convolve(image, kernel, mode='same')
    return map


def mask2label(path_label, aim='full'):
    """
    Retrieve points coordinates and value from a label file containing singl voxel label
    Args:
        path_label (str): path of nifti image
        aim (int): -1 will return all points with label between 3 and 30 , any other int > 0  will return
        only the coordinates of points with label defined by aim.

    Returns:
        ndarray: array containing the asked point in the format [x,y,z,value] in the RAS orientation.

    """
    image = nib.load(path_label)
    image = nib.as_closest_canonical(image)
    arr = np.array(image.dataobj)
    list_label_image = []
    # Arr non zero used since these are single voxel label
    for i in range(len(arr.nonzero()[0])):
        x = arr.nonzero()[0][i]
        y = arr.nonzero()[1][i]
        z = arr.nonzero()[2][i]
        # need to check every points
        if aim == -1:
            # we don't want to account for pmj (label 49) nor C1/C2 which is hard to distinguish.
            if arr[x, y, z] < 30 and arr[x, y, z] != 1:
                list_label_image.append([x, y, z, arr[x, y, z]])
        elif aim > 0:
            if arr[x, y, z] == aim:
                list_label_image.append([x, y, z, arr[x, y, z]])
    list_label_image.sort(key=lambda x: x[3])
    return list_label_image


def extract_mid_slice_and_convert_coordinates_to_heatmaps(bids_path, suffix, aim=-1):
    """
    This function takes as input a path to a dataset  and generates a set of images:
    (i) mid-sagittal image and
    (ii) heatmap of disc labels associated with the mid-sagittal image.
    
    Args:
        bids_path (string): path to BIDS dataset form which images will be generated
        suffix (string): suffix of image that will be processed (e.g., T2w)
        aim (int): If aim is not -1, retrieves only labels with value = aim, else create heatmap with all labels.

    Returns:
        None. Images are saved in BIDS folder
    """
    t = os.listdir(bids_path)
    t.remove('derivatives')

    for i in range(len(t)):
        sub = t[i]
        path_image = os.path.join(bids_path, t[i], 'anat', t[i] + suffix + '.nii.gz')
        if os.path.isfile(path_image):
            path_label = os.path.join(bids_path, 'derivatives', 'labels', t[i], 'anat', t[i] + suffix +
                                      '_label-disc-manual.nii.gz')
            list_points = mask2label(path_label, aim=aim)
            image_ref = nib.load(path_image)
            nib_ref_can = nib.as_closest_canonical(image_ref)
            imsh = np.array(nib_ref_can.dataobj).shape
            mid_nifti = imed_preprocessing.get_midslice_average(path_image, list_points[0][0], slice_axis=0)
            nib.save(mid_nifti, os.path.join(bids_path, t[i], 'anat', t[i] + suffix + '_mid.nii.gz'))
            lab = nib.load(path_label)
            nib_ref_can = nib.as_closest_canonical(lab)
            label_array = np.zeros(imsh[1:])

            for j in range (len(list_points)):
                label_array[list_points[j][1], list_points[j][2]] = 1

            heatmap = heatmap_generation(label_array[:, :], 10)
            arr_pred_ref_space = imed_utils.reorient_image(np.expand_dims(heatmap[:, :], axis=0), 2, lab, nib_ref_can)
            nib_pred = nib.Nifti1Image(arr_pred_ref_space, lab.affine)
            nib.save(nib_pred, os.path.join(bids_path, 'derivatives', 'labels', t[i], 'anat', t[i] + suffix +
                                            '_mid_heatmap' + str(aim) + '.nii.gz'))
        else:
            pass


def get_parser():
    parser = argparse.ArgumentParser()
    parser.add_argument("-p", "--path", dest="path", required=True, type=str,
                        help="Path to bids folder")
    parser.add_argument("-s", "--suffix", dest="suffix", required=True,
                        type=str, help="Suffix of the input file as in sub-xxxSUFFIX.nii.gz (E.g., _T2w)")
    parser.add_argument("-a", "--aim", dest="aim", default=-1, type=int,
                        help="-1 or positive int. If set to any positive int,"
                             " only label with this value will be taken into account ")
    return parser


if __name__ == '__main__':
    parser = get_parser()
    args = parser.parse_args()
    bids_path = args.path
    suffix = args.suffix
    aim = args.aim
    # Run Script
    extract_mid_slice_and_convert_coordinates_to_heatmaps(bids_path, suffix, aim)