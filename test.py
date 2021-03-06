# ------------------------------------------------------------------------------
# Copyright (c) Zhichao Zhao
# Licensed under the MIT License.
# Created by Zhichao zhao(zhaozhichao4515@gmail.com)
# ------------------------------------------------------------------------------
import argparse
import time

import cv2
import numpy as np
import torch
import torch.backends.cudnn as cudnn
from matplotlib import pyplot as plt
from scipy.integrate import simps
from torch.utils.data import DataLoader
from torchvision import transforms

from dataset.datasets import LoadWebcam, WLFWDatasets
from models.pfld import PFLDInference

cudnn.benchmark = True
cudnn.determinstic = True
cudnn.enabled = True
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")


def compute_nme(preds, target):
    """preds/target:: numpy array, shape is (N, L, 2)
    N: batchsize L: num of landmark
    """
    N = preds.shape[0]
    L = preds.shape[1]
    rmse = np.zeros(N)

    for i in range(N):
        pts_pred, pts_gt = (
            preds[
                i,
            ],
            target[
                i,
            ],
        )
        if L == 19:  # aflw
            interocular = 34  # meta['box_size'][i]
        elif L == 29:  # cofw
            interocular = np.linalg.norm(
                pts_gt[
                    8,
                ]
                - pts_gt[
                    9,
                ]
            )
        elif L == 68:  # 300w
            # interocular
            interocular = np.linalg.norm(
                pts_gt[
                    36,
                ]
                - pts_gt[
                    45,
                ]
            )
        elif L == 98:
            interocular = np.linalg.norm(
                pts_gt[
                    60,
                ]
                - pts_gt[
                    72,
                ]
            )
        else:
            raise ValueError("Number of landmarks is wrong")
        rmse[i] = np.sum(np.linalg.norm(pts_pred - pts_gt, axis=1)) / (interocular * L)

    return rmse


def compute_auc(errors, failureThreshold, step=0.0001, showCurve=True):
    """compute_auc"""
    nErrors = len(errors)
    xAxis = list(np.arange(0.0, failureThreshold + step, step))
    ced = [float(np.count_nonzero([errors <= x])) / nErrors for x in xAxis]

    AUC = simps(ced, x=xAxis) / failureThreshold
    failureRate = 1.0 - ced[-1]

    if showCurve:
        plt.plot(xAxis, ced)
        plt.show()

    return AUC, failureRate


def validate(args, wlfw_val_dataloader, pfld_backbone):
    """validate the model"""
    pfld_backbone.eval()

    nme_list = []
    cost_time = []
    with torch.no_grad():
        for i, (img, landmark_gt, _, _) in enumerate(wlfw_val_dataloader):
            img = img.to(device)
            landmark_gt = landmark_gt.to(device)
            pfld_backbone = pfld_backbone.to(device)

            start_time = time.time()
            _, landmarks = pfld_backbone(img)
            cost_time.append(time.time() - start_time)

            landmarks = landmarks.cpu().numpy()
            landmarks = landmarks.reshape(landmarks.shape[0], -1, 2)  # landmark
            landmark_gt = (
                landmark_gt.reshape(landmark_gt.shape[0], -1, 2).cpu().numpy()
            )  # landmark_gt

            if args.show_image or args.save_image:
                img_clone = np.array(np.transpose(img[0].cpu().numpy(), (1, 2, 0)))
                img_clone = (img_clone * 255).astype(np.uint8)
                np.clip(img_clone, 0, 255)

                pre_landmark = landmarks[0] * [112, 112]

                cv2.imwrite("show_img.png", img_clone)
                img_clone = cv2.imread("show_img.png")

                for (x, y) in pre_landmark.astype(np.int32):
                    cv2.circle(img_clone, (x, y), 1, (255, 0, 0), -1)

                if args.save_image:
                    cv2.imwrite(f"results/image_{i:03}.png", img_clone)

                if args.show_image:
                    cv2.imshow("show_img.png", img_clone)
                    cv2.waitKey(0)

            nme_temp = compute_nme(landmarks, landmark_gt)
            for item in nme_temp:
                nme_list.append(item)

        # nme
        print("nme: {:.4f}".format(np.mean(nme_list)))
        # auc and failure rate
        failureThreshold = 0.1
        auc, failure_rate = compute_auc(nme_list, failureThreshold)
        print("auc @ {:.1f} failureThreshold: {:.4f}".format(failureThreshold, auc))
        print("failure_rate: {:}".format(failure_rate))
        # inference time
        print("inference_cost_time: {0:4f}".format(np.mean(cost_time)))


def detect(args, model, dataset):
    """validate the model"""
    model.eval()
    with torch.no_grad():
        for i, (img, landmark_gt, _, _) in enumerate(dataset):
            if len(img.shape) == 3:
                img = img[None]  # expand for batch dim
            img = img.to(device)
            model = model.to(device)

            # start_time = time.time()
            _, landmarks = model(img)
            # (time.time() - start_time)

            landmarks = landmarks.cpu().numpy()
            landmarks = landmarks.reshape(landmarks.shape[0], -1, 2)  # landmark

            if args.show_image or args.save_image:
                img_clone = np.array(np.transpose(img[0].cpu().numpy(), (1, 2, 0)))
                img_clone = (img_clone * 255).astype(np.uint8)
                np.clip(img_clone, 0, 255)

                pre_landmark = landmarks[0] * [112, 112]

                cv2.imwrite("show_img.png", img_clone)
                img_clone = cv2.imread("show_img.png")

                for (x, y) in pre_landmark.astype(np.int32):
                    cv2.circle(img_clone, (x, y), 1, (255, 0, 0), -1)

                if args.save_image:
                    cv2.imwrite(f"results/image_{i:03}.png", img_clone)

                if args.show_image:
                    cv2.imshow("show_img.png", img_clone)


def main(args):
    """main"""
    checkpoint = torch.load(args.model_path, map_location=device)
    pfld_backbone = PFLDInference().to(device)
    pfld_backbone.load_state_dict(checkpoint["pfld_backbone"])

    val_transforms = transforms.Compose([transforms.ToTensor()])

    if args.camera:
        val_dataset = LoadWebcam(transforms=val_transforms)
        detect(args, pfld_backbone, val_dataset)
    else:
        wlfw_val_dataset = WLFWDatasets(args.test_dataset, val_transforms)
        wlfw_val_dataloader = DataLoader(
            wlfw_val_dataset, batch_size=1, shuffle=False, num_workers=0
        )

        validate(args, wlfw_val_dataloader, pfld_backbone)


def parse_args():
    """parse arguments"""
    parser = argparse.ArgumentParser(description="Testing")
    parser.add_argument(
        "--model-path", default="./checkpoint/snapshot/checkpoint.pth.tar", type=str
    )
    parser.add_argument("--test-dataset", default="./data/test_data/list.txt", type=str)
    parser.add_argument("--save-image", action="store_true", default=True)
    parser.add_argument("--show-image", action="store_true", default=False)
    parser.add_argument("--camera", action="store_true", default=False)
    args = parser.parse_args()
    return args


def run():
    args = parse_args()
    main(args)


if __name__ == "__main__":

    run()
