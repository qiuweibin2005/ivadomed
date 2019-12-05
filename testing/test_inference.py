import numpy as np
import time

import torch.backends.cudnn as cudnn
from torch.utils.data import DataLoader, dataloader
from torchvision import transforms

from medicaltorch.filters import SliceFilter
from medicaltorch import datasets as mt_datasets
from medicaltorch import transforms as mt_transforms
from torch import optim

from tqdm import tqdm

from ivadomed import loader as loader
from ivadomed import models
from ivadomed import losses
from ivadomed.utils import *
import ivadomed.transforms as ivadomed_transforms

cudnn.benchmark = True

GPU_NUMBER = 5
BATCH_SIZE = 8
DROPOUT = 0.4
BN = 0.1
PATH_BIDS = 'testing_data/'

def test_inference(film_bool=False):
    device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
    cuda_available = torch.cuda.is_available()
    if not cuda_available:
        print("cuda is not available.")
        print("Working on {}.".format(device))
    if cuda_available:
        # Set the GPU
        torch.cuda.set_device(GPU_NUMBER)
        print("using GPU number {}".format(GPU_NUMBER))

    validation_transform_list = [
        ivadomed_transforms.Resample(wspace=0.75, hspace=0.75),
        ivadomed_transforms.ROICrop2D(size=[48, 48]),
        ivadomed_transforms.ToTensor(),
        ivadomed_transforms.NormalizeInstance()
    ]

    val_transform = transforms.Compose(validation_transform_list)
    val_undo_transform = ivadomed_transforms.UndoCompose(val_transform)

    test_lst = ['sub-test001']

    ds_test = loader.BidsDataset(PATH_BIDS,
                                  subject_lst=test_lst,
                                  target_suffix="_lesion-manual",
                                  roi_suffix="_seg-manual",
                                  contrast_lst=['T2w'],
                                  metadata_choice="contrast",
                                  contrast_balance={},
                                  slice_axis=2,
                                  transform=val_transform,
                                  multichannel=False,
                                  slice_filter_fn=SliceFilter(filter_empty_input=True,
                                                                filter_empty_mask=False))

    ds_test.filter_roi(nb_nonzero_thr=10)

    if film_bool:  # normalize metadata before sending to network
        print('FiLM inference not implemented yet.')
        quit()
        # metadata_clustering_models = joblib.load("./" + context["log_directory"] + "/clustering_models.joblib")
        # ds_test = loader.normalize_metadata(ds_test,
        #                                     metadata_clustering_models,
        #                                     context["debugging"],
        #                                     context["metadata"],
        #                                     False)

        # one_hot_encoder = joblib.load("./" + context["log_directory"] + "/one_hot_encoder.joblib")

    test_loader = DataLoader(ds_test, batch_size=BATCH_SIZE,
                             shuffle=False, pin_memory=True,
                             collate_fn=mt_datasets.mt_collate,
                             num_workers=1)

    if film_bool:
        model = torch.load(PATH_BIDS + "model_film_test.pt")
    else:
        model = torch.load(PATH_BIDS + "model_unet_test.pt")

    if cuda_available:
        model.cuda()
    model.eval()

    metric_fns = [dice_score,  # from ivadomed/utils.py
                  mt_metrics.hausdorff_score,
                  mt_metrics.precision_score,
                  mt_metrics.recall_score,
                  mt_metrics.specificity_score,
                  mt_metrics.intersection_over_union,
                  mt_metrics.accuracy_score]

    metric_mgr = IvadoMetricManager(metric_fns)

    fname_img = ''
    for i, batch in enumerate(test_loader):
        input_samples, gt_samples = batch["input"], batch["gt"]
        print(batch['input_metadata'][0]['zooms'], batch['input_metadata'][0]['data_shape'])

        # if batch['input_metadata'][0]['input_filename']
        # print(batch['input_metadata'][0]['input_filename'])
        # print(batch['input_metadata'][0]['slice_index'])

        with torch.no_grad():
            if cuda_available:
                test_input = input_samples.cuda()
                test_gt = gt_samples.cuda(non_blocking=True)
            else:
                test_input = input_samples
                test_gt = gt_samples

            if film_bool:
                sample_metadata = batch["input_metadata"]
                test_contrast = [sample_metadata[k]['contrast'] for k in range(len(sample_metadata))]

                test_metadata = [one_hot_encoder.transform([sample_metadata[k]["film_input"]]).tolist()[0] for k in
                                 range(len(sample_metadata))]
                preds = model(test_input, test_metadata)  # Input the metadata related to the input samples
            else:
                preds = model(test_input)

        rdict = {}
        rdict['pred'] = preds
        batch.update(rdict)
        sample_lst = []
        for smp_idx in range(len(batch['pred'])):
            rdict = {}
            for k in batch.keys():
                rdict[k] = batch[k][smp_idx]
            rdict_undo = val_undo_transform(rdict)
            sample_lst.append(rdict_undo)

        # Metrics computation
        gt_npy = gt_samples.numpy().astype(np.uint8)
        gt_npy = gt_npy.squeeze(axis=1)

        preds_npy = preds.data.cpu().numpy()
        preds_npy = threshold_predictions(preds_npy)
        preds_npy = preds_npy.astype(np.uint8)
        preds_npy = preds_npy.squeeze(axis=1)

        metric_mgr(preds_npy, gt_npy)

    metrics_dict = metric_mgr.get_results()
    metric_mgr.reset()
    print(metrics_dict)
