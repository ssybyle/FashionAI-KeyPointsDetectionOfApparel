import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))


import numpy as np
import torch
from torch.autograd import Variable
from torch.backends import cudnn
from torch.nn import DataParallel
import cv2
import torch.nn.functional as F
import math
from tqdm import tqdm
from scipy.ndimage.morphology import binary_dilation
import os
import argparse
import sys

from src import pytorch_utils
from src.config import Config
from src.kpda_parser import KPDA
from src.stage2.cascade_pyramid_network import CascadePyramidNet
from src.stage2v9.cascade_pyramid_network_v9 import CascadePyramidNetV9
from src.utils import draw_heatmap, draw_keypoints
from src.stage2.keypoint_encoder import KeypointEncoder
from src.utils import normalized_error

from IPython.display import display, Image


def compute_keypoints(config, img0, net, encoder, doflip=False):
    img_h, img_w, _ = img0.shape
    # min size resizing
    scale = config.img_max_size / max(img_w, img_h)
    img_h2 = int(img_h * scale)
    img_w2 = int(img_w * scale)
    img = cv2.resize(img0, (img_w2, img_h2), interpolation=cv2.INTER_CUBIC)
    img = np.transpose(img, (2, 0, 1)).astype(np.float32)  # channel, height, width
    img[[0, 2]] = img[[2, 0]]
    img = img / 255.0
    img = (img - config.mu) / config.sigma
    pad_imgs = np.zeros([1, 3, config.img_max_size, config.img_max_size], dtype=np.float32)
    pad_imgs[0, :, :img_h2, :img_w2] = img
    data = torch.from_numpy(pad_imgs)
    data = data.cuda(non_blocking=True)
    _, hm_pred = net(data)
    hm_pred = F.relu(hm_pred, False)
    hm_pred = hm_pred[0].data.cpu().numpy()
    if doflip:
        a = np.zeros_like(hm_pred)
        a[:, :, :img_w2 // config.hm_stride] = np.flip(hm_pred[:, :, :img_w2 // config.hm_stride], 2)
        for conj in config.conjug:
            a[conj] = a[conj[::-1]]
        hm_pred = a
    return hm_pred

    # x, y = encoder.decode_np(hm_pred, scale, config.hm_stride, method='maxoffset')
    # keypoints = np.stack([x, y, np.ones(x.shape)], axis=1).astype(np.int16)
    # return keypoints

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='')
    parser.add_argument('-c', '--clothes', help='specify the clothing type', default='outwear')
    parser.add_argument('-g', '--gpu', help='cuda device to use', default='0')
    parser.add_argument('-m', '--model', help='specify the model', default=None)
    parser.add_argument('-v', '--vis', '--visual', help='whether visualize result', default=False)
    
    args = parser.parse_args(sys.argv[1:])

    config = Config(args.clothes)
    n_gpu = pytorch_utils.setgpu(args.gpu)
    val_kpda = KPDA(config, config.data_path, 'val')
    print('Testing: ' + config.clothes)
    print('Validation sample number: %d' % val_kpda.size())
    net = CascadePyramidNet(config)
    checkpoint = torch.load(args.model)  # must before cuda
    net.load_state_dict(checkpoint['state_dict'])
    net = net.cuda()
    cudnn.benchmark = True
    net = DataParallel(net)
    net.eval()
    encoder = KeypointEncoder()
    nes = []

    for idx in tqdm(range(val_kpda.size())):
        img_path = val_kpda.get_image_path(idx)
        print(img_path)
        img0 = cv2.imread(img_path)  #X
        img0_flip = cv2.flip(img0, 1)
        img_h, img_w, _ = img0.shape

        # mask_path = img_path.replace('Images', 'Masks').replace('.jpg', '.npy')
        # if os.path.exists(mask_path):
        #     mask = np.load(mask_path)
        #     mask_h, mask_w = mask.shape
        #     assert mask_h == img_h and mask_w == img_w
        #     mask_scale = config.img_max_size / config.hm_stride / max(img_w, img_h)
        #     mask_h2 = int(mask_h * mask_scale)
        #     mask_w2 = int(mask_w * mask_scale)
        #     mask = cv2.resize(mask, (mask_w2, mask_h2))
        #     pad_mask = np.zeros([config.img_max_size//config.hm_stride, config.img_max_size//config.hm_stride], dtype=mask.dtype)
        #     pad_mask[:mask_h2, :mask_w2] = mask
        #     pad_mask = binary_dilation(pad_mask, iterations=10).astype(np.float32)
        # else:
        #     pad_mask = np.ones([config.img_max_size//config.hm_stride, config.img_max_size//config.hm_stride], dtype=np.float32)


# ----------------------------------------------------------------------------------------------------------------------
        scale = config.img_max_size / max(img_w, img_h)
        with torch.no_grad():
            hm_pred = compute_keypoints(config, img0, net, encoder) #* pad_mask
            hm_pred2 = compute_keypoints(config, img0_flip, net, encoder, doflip=True) #* pad_mask
        x, y = encoder.decode_np(hm_pred + hm_pred2, scale, config.hm_stride, (img_w/2, img_h/2), method='maxoffset')
        keypoints = np.stack([x, y, np.ones(x.shape)], axis=1).astype(np.int16)
# ----------------------------------------------------------------------------------------------------------------------
        # keypoints = compute_keypoints(config, img0, net, encoder)
        # keypoints_flip = compute_keypoints(config, img0_flip, net, encoder)
        # keypoints_flip[:, 0] = img0.shape[1] - keypoints_flip[:, 0]
        # for conj in config.conjug:
        #     keypoints_flip[conj] = keypoints_flip[conj[::-1]]
        # keypoints2 = np.copy(keypoints)
        # keypoints2[:, :2] = (keypoints[:, :2] + keypoints_flip[:, :2]) // 2
# ----------------------------------------------------------------------------------------------------------------------
        if args.vis:
            print("Affiche l'image :")
            kp_img = draw_keypoints(img0, keypoints)
            cv2.imwrite(config.proj_path + 'tmp/{0}{1}.png'.format(config.clothes, idx), kp_img)



