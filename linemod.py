# -*- coding: utf-8 -*-
# ---------------------
# using Linemod dataset for training and testing
# @Author: Fan, Mo
# @Email: fmo@nullmax.ai
# ---------------------

import copy
import os

import cv2
import numpy as np
import tensorflow as tf

import yolo.config as cfg
from utils.utils import *


class Linemod(object):

    def __init__(self, phase, arg=None):
        # Set parameters for training and testing
        self.data_options = read_data_cfg(arg)
        self.trainlist = self.data_options['train']
        self.testlist = self.data_options['valid']
        #self.gpus = self.data_options['gpu']
        self.meshname = self.data_options['mesh']
        #self.num_workers = int(self.data_options['num_workers'])
        self.backupdir = self.data_options['backup']
        self.diam = float(self.data_options['diam'])
        self.dataset_name = self.data_options['name']
        self.vx_threshold = self.diam * 0.1

        self.phase = phase
        self.datasets_dir = os.path.join('LINEMOD', self.dataset_name)
        self.batch_size = cfg.BATCH_SIZE
        self.image_size = cfg.IMAGE_SIZE
        self.cell_size = cfg.CELL_SIZE
        self.boxes_per_cell = cfg.BOXES_PER_CELL
        self.num_classes = cfg.NUM_CLASSES
        self.flipped = False
        self.train_imgname = None
        self.test_imgname = None
        self.imgname = None
        self.train_gt_labels = None
        self.test_gt_labels = None
        self.gt_labels = None
        self.epoch = 0
        self.batch = 0
        self.prepare()  # get the image files name and label files name


    def prepare(self):
        if self.phase == 'train':
            with open(self.trainlist, 'r') as f:
                self.imgname = [x.strip() for x in f.readlines()]  # a list of trianing files
            self.gt_labels = self.load_labels() # a list of all labels with respect to imgname
        elif self.phase == 'test':
            with open(self.testlist, 'r') as f:
                self.imgname = [x.strip() for x in f.readlines()]
            self.gt_labels = self.load_labels()
        else:
            print('Wrong phase...')

    def next_batches(self):
        if self.batch == 245:
            print('   Last small batch of {}'.format(self.dataset_name))
        images = np.zeros((self.batch_size, 416, 416, 3), np.float32)
        labels = np.zeros((self.batch_size, 13, 13, 1 + self.boxes_per_cell*9*2 + self.num_classes), np.float32)
        for idx in range(self.batch_size):
            images[idx] = self.image_read(self.imgname[idx + self.batch * self.batch_size])
            labels[idx] = self.label_read(self.gt_labels[idx + self.batch * self.batch_size])
        self.batch += 1
        return images, labels

    def next_batches_test(self):
        images = np.zeros((self.batch_size, 416, 416, 3), np.float32)
        labels = np.zeros((self.batch_size, 13, 13, 32), np.float32)
        for idx in range(self.batch_size):
            images[idx] = self.image_read(self.imgname[idx + self.batch * self.batch_size], self.flipped)
            labels[idx] = self.label_read(self.gt_labels[idx + self.batch * self.batch_size])
        return images, labels

    def get_truths(self):
        gt_truths = []
        for idx in range(self.batch_size):
            gt_truths.append(self.gt_labels[idx + self.batch * self.batch_size])
        return gt_truths

    def load_labels(self):
        """
        Return: 2-D list, a list of all the list in folder
        """
        gt_labels = []
        label_path = os.path.join(self.datasets_dir, 'labels')
        for i in range(len(self.imgname)):
            f_name_idx = self.imgname[i][-10:-4]
            f_name = f_name_idx + '.txt'
            full_path = os.path.join(label_path, f_name)
            with open(full_path, 'r') as f:
                labels = f.readline().split()
            for j in range(len(labels)):
                labels[j] = float(labels[j])
            labels[0] = int(labels[0])
            gt_labels.append(labels)
        return gt_labels

    def image_read(self, imgname, flipped=False):
        image = cv2.imread(imgname)
        image = cv2.resize(image, (self.image_size, self.image_size))
        image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB).astype(np.float32)
        image = (image / 255.0) * 2.0 - 1.0
        if flipped:
            image = image[:, ::-1, :]
        return image

    def label_read(self, gt_labels):
        labels = np.zeros((13, 13, 1+self.boxes_per_cell*9*2 + self.num_classes), np.float32)
        gt_label = gt_labels[0]
        gt_xc = gt_labels[1] * 13
        gt_yc = gt_labels[2] * 13
        gt_x0 = gt_labels[3] * 13
        gt_y0 = gt_labels[4] * 13
        gt_x1 = gt_labels[5] * 13
        gt_y1 = gt_labels[6] * 13
        gt_x2 = gt_labels[7] * 13
        gt_y2 = gt_labels[8] * 13
        gt_x3 = gt_labels[9] * 13
        gt_y3 = gt_labels[10] * 13
        gt_x4 = gt_labels[11] * 13
        gt_y4 = gt_labels[12] * 13
        gt_x5 = gt_labels[13] * 13
        gt_y5 = gt_labels[14] * 13
        gt_x6 = gt_labels[15] * 13
        gt_y6 = gt_labels[16] * 13
        gt_x7 = gt_labels[17] * 13
        gt_y7 = gt_labels[18] * 13
        coords = [gt_xc, gt_yc, gt_x0, gt_y0, gt_x1, gt_y1, gt_x2, gt_y2, gt_x3, gt_y3, gt_x4, gt_y4, gt_x5, gt_y5, gt_x6, gt_y6, gt_x7, gt_y7]
        response_x = int(gt_xc)
        response_y = int(gt_yc)
        labels[response_x, response_y, 0] = 1

        for i in range(1, 19, 1):
            labels[response_x, response_y, i] = coords[i - 1]

        labels[response_x, response_y, 19 + gt_label] = 1

        return labels