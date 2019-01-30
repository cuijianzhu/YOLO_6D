#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ---------------------
# solver file for yolo-6d
# @Author: Fan, Mo
# @Email: fmo@nullmax.ai
# ---------------------

from __future__ import print_function

import argparse
import datetime
import time
import os

import numpy as np
import tensorflow as tf

import yolo.config as cfg
from linemod import Linemod
from utils.MeshPly import MeshPly
from utils.timer import Timer
from utils.utils import *
from yolo.yolo_6d_net import YOLO6D_net


class Solver(object):

    def __init__(self, net, data, tfrecord, arg=None):

        #Set parameters for training and testing
        self.meshname = data.meshname
        self.backupdir = data.backupdir
        self.vx_threshold = data.vx_threshold

        self.mesh = MeshPly(self.meshname)
        self.vertices = np.c_[np.array(self.mesh.vertices), np.ones((len(self.mesh.vertices), 1))].T
        self.corners3D = get_3D_corners(self.vertices)
        self.internal_calibration = get_camera_intrinsic()
        self.best_acc = -1
        self.testing_errors_trans = []
        self.testing_errors_angle = []
        self.testing_errors_pixel = []
        self.testing_accuracies = []

        self.saveconfig = False
        self.net = net
        self.data = data

        self.batch_size = cfg.BATCH_SIZE
        self.epoch = cfg.EPOCH
        self.weight_file = cfg.WEIGHTS_FILE  # data/weights/
        self.max_iter = int(len(data.imgname) / self.batch_size)
        self.inital_learning_rate = cfg.LEARNING_RATE  # 0.001
        self.decay_steps = cfg.DECAY_STEP
        self.decay_rate = cfg.DECAY_RATE
        self.staircase = cfg.STAIRCASE
        self.summary_iter = cfg.SUMMARY_ITER
        self.save_iter = cfg.SAVE_ITER
        self.output_dir = cfg.OUTPUT_DIR
        if self.saveconfig:
            self.save_config()

        self.tfrecords = 'data/train.tfrecord'
        self.queue = tf.train.string_input_producer([self.tfrecords], num_epochs=self.epoch)
        self.reader = tf.TFRecordReader()
        self.images, self.labels = self.read_and_decode()
        self.coord = None
        self.threads = None

        self.variable_to_restore = tf.global_variables()[:-2]
        self.variable_to_save = tf.global_variables()
        self.restorer = tf.train.Saver(self.variable_to_restore, max_to_keep=3)
        self.saver = tf.train.Saver(self.variable_to_save, max_to_keep=3)
        self.features = None

        self.ckpt_file = os.path.join(self.weight_file, 'yolo_6d.ckpt')
        self.summary_op = tf.summary.merge_all()
        self.writer = tf.summary.FileWriter(self.output_dir, flush_secs=60)

        #self.global_step = tf.get_variable('global_step', [], initializer=tf.constant_initializer(0.0), trainable=False)
        self.global_step = tf.Variable(0, name='global_step', trainable=False)
        # self.learning_rate = tf.train.exponential_decay(self.inital_learning_rate, self.global_step,
                                                        # self.decay_steps, self.decay_rate, self.staircase, name='learning_rate')
        if arg.pre:
            boundaries = [1, 50, 1000, 2000]
            learning_rate = [0.001, 0.0001, 0.001, 0.0001, 0.00001]
        else:
            boundaries = [1, 50, 3000, 6000]
            learning_rate = [0.001, 0.0001, 0.001, 0.0001, 0.00001]
        self.learning_rate = tf.train.piecewise_constant(self.global_step, boundaries, learning_rate, name='learning_rate')
        #self.optimizer = tf.train.AdamOptimizer(learning_rate=self.learning_rate).minimize(
        #    self.net.total_loss, global_step=self.global_step)
        self.optimizer = tf.train.GradientDescentOptimizer(learning_rate=self.learning_rate).minimize(
            self.net.total_loss, global_step=self.global_step)
        self.ema = tf.train.ExponentialMovingAverage(decay=0.999)
        self.averages_op = self.ema.apply(tf.trainable_variables())
        with tf.control_dependencies([self.optimizer]):
            self.train_op = tf.group(self.averages_op)

        gpu_options = tf.GPUOptions()
        config = tf.ConfigProto(gpu_options=gpu_options)

        self.sess = tf.Session(config=config)
        self.sess.run(tf.global_variables_initializer())
        self.sess.run(tf.local_variables_initializer())

        if self.weight_file is not None:
            print('\n----------Restoring weights from: {}------------'.format(self.weight_file))
            self.restorer.restore(self.sess, self.weight_file)

        self.writer.add_graph(self.sess.graph)

    def read_and_decode(self):
        __, serialized_example = self.reader.read(self.queue)
        self.features = tf.parse_single_example(serialized_example,
                                                features={'labels':tf.FixedLenFeature([], tf.string), 
                                                          'images':tf.FixedLenFeature([], tf.string)})
        image = tf.decode_raw(self.features['images'], tf.float32)
        image.set_shape([416 * 416 * 3])
        image = tf.reshape(image, [416, 416, 3])
        image = tf.cast(image, tf.float32) / 255 * 2.0 - 1.0

        label = tf.decode_raw(self.features['labels'], tf.float32)
        label.set_shape([13 * 13 * 32])
        label = tf.reshape(label, [13, 13, 32])
        label = tf.cast(label, tf.float32)
        if True:
            batch = self.batch_size
            # min_after_dequeue = 10
            # capacity = min_after_dequeue + 3 * batch
            images, labels = tf.train.batch([image, label],
                                                    batch_size=batch,
                                                    num_threads=2,
                                                    capacity=2000)

        return images, labels

    def train(self):
        self.net.evaluation_off()
        train_timer = Timer()
        load_timer = Timer()
        
        self.coord = tf.train.Coordinator()
        self.threads = tf.train.start_queue_runners(sess=self.sess, coord=self.coord)

        epoch = 0
        while epoch <= self.epoch:
            for step in range(0, self.max_iter-1):
                load_timer.tic()
                # images, labels = self.data.next_batches()
                images, labels = self.sess.run([self.images, self.labels])
                load_timer.toc()
                feed_dict = {self.net.input_images: images, self.net.labels: labels}
                self.coord.request_stop()
                self.coord.join(self.threads)

                if step % self.summary_iter == 0:
                    if step % (self.summary_iter * 4) == 0:
                        train_timer.tic()
                        summary_str, loss, _ = self.sess.run(
                            [self.summary_op, self.net.total_loss, self.train_op],
                            feed_dict=feed_dict
                        )
                        train_timer.toc()

                        log_str = ('\n   {}, Epoch:{}, Step:{}, Learning rate:{},\n'
                            '   Loss: {:5.3f},\n   Speed: {:.3f}s/iter,'
                            ' Load: {:.3f}s/iter, Remain: {}').format(
                            datetime.datetime.now().strftime('%m/%d %H:%M:%S'),
                            epoch,
                            int(step),
                            round(self.learning_rate.eval(session=self.sess), 6),
                            loss,
                            train_timer.average_time,
                            load_timer.average_time,
                            train_timer.remain(step, self.max_iter))
                        print("==================================================================")
                        print(log_str)

                        # test
                        self.test()

                        if self.testing_accuracies[-1] > self.best_acc:
                            self.best_acc = self.testing_accuracies[-1]
                            print('   best model so far!')
                            print('   Save weights to %s/yolo_6d.ckpt' % (self.output_dir))
                            self.saver.save(self.sess, '%s/yolo_6d.ckpt' % (self.output_dir), global_step=self.global_step)

                    else:
                        train_timer.tic()
                        summary_str, _ = self.sess.run(
                            [self.summary_op, self.train_op],
                            feed_dict=feed_dict)
                        train_timer.toc()

                    self.writer.add_summary(summary_str, step)

                else:
                    train_timer.tic()
                    self.sess.run(self.train_op, feed_dict=feed_dict)
                    train_timer.toc()

                if step % self.save_iter == 0:
                    datetime.datetime.now().strftime('%m/%d %H:%M:%S')
                    print('   Save checkpoint file to: {}'.format(
                        self.weight_file))
                    print("==================================================================")
                    self.saver.save(self.sess, self.weight_file,
                                    global_step=self.global_step)
            epoch += 1
            self.data.batch = 0

        print('\n   Save final checkpoint file to: {}'.format(self.weight_file))
        self.saver.save(self.sess, self.weight_file, global_step=self.global_step)


    def test(self):
        # turn off batch norm
        self.net.evaluation()
        test_timer = Timer()
        load_timer = Timer()
        im_width = 640
        im_height = 480
        eps = 1e-5

        load_timer.tic()
        # images, labels = self.data.next_batches_test()

        # file_name_queue = tf.train.string_input_producer([self.tfrecords], num_epochs=None)
        # __, serialized_example = self.reader.read(file_name_queue)
        # features = tf.parse_single_example(serialized_example,
                                           # features={
                                               # 'labels':tf.FixedLenFeature([], tf.string),
                                               # 'images':tf.FixedLenFeature([], tf.string),
                                           # })
        images = tf.decode_raw(self.features['images'], tf.float32)
        labels = tf.decode_raw(self.features['labels'], tf.float32)
        if True:
            batch = self.batch_size
            min_after_dequeue = 10
            capacity = min_after_dequeue + 3 * batch
            images, labels = tf.train.shuffle_batch([images, labels],
                                                    batch_size=batch,
                                                    num_threads=3,
                                                    capacity=capacity,
                                                    min_after_dequeue=min_after_dequeue)
        truths = self.data.get_truths() #2-D [Batch, params]
        load_timer.toc()

        feed_dict = {self.net.input_images: images, self.net.labels: labels}
        #predicts: [batch, cell, cell, coords + classes + confidence]
        predicts = self.sess.run(self.net.logit, feed_dict=feed_dict)  # run
        #confidence = predicts[:, :, :, -1]
        testing_error_trans = 0.0
        testing_error_angle = 0.0
        testing_error_pixel = 0.0
        testing_samples = 0.0
        errs_2d = []
        errs_3d = []
        errs_trans = []
        errs_angle = []
        errs_corner2D = []

        #all_boxes = []
        #Iterate throught test examples
        for batch_idx in range(cfg.BATCH_SIZE):
            test_timer.tic()
            #conf_sco = confidence_score[batch_idx]
            logit = predicts[batch_idx] # 3-D
            logit = logit * 10.0
            truth = truths[batch_idx]
            #num_gts = truth[0]

            # prune tensors with low confidence (< 0.1)
            #logit = confidence_thresh(conf_sco, pred)

            # get the maximum of 3x3 neighborhood
            #logit_nms = nms33(logit, conf_sco)
            #logit = nms(logit, conf_sco)

            # compute weighted average of 3x3 neighborhood
            #logit = compute_average(predicts[batch_idx], conf_sco, logit_nms)

            """
            # get all the boxes coordinates
            all_boxes = get_region_boxes(logit, cfg.NUM_CLASSES)
            #for k in range(num_gts):
            box_gt = [truth[1], truth[2], truth[3], truth[4], truth[5],
                        truth[6], truth[7], truth[8], truth[9], truth[10],
                        truth[11], truth[12], truth[13], truth[14], truth[15],
                        truth[16], truth[17], truth[18], 1.0, 1.0, truth[0]]
            best_conf_est = -1

            #If the prediction has the highest confidence, choose it as prediction
            for j in range(len(all_boxes)):
                if all_boxes[j][18] > best_conf_est:
                    best_conf_est = all_boxes[j][18]
                    box_pr = all_boxes[j]
                    #match = corner_confidence9(box_gt[:18], all_boxes[j][:18])
            """

            # get all the boxes coordinates
            # 1st: ground true boxes
            box_gt = [truth[1], truth[2], truth[3], truth[4], truth[5],
                      truth[6], truth[7], truth[8], truth[9], truth[10],
                      truth[11], truth[12], truth[13], truth[14], truth[15],
                      truth[16], truth[17], truth[18], 1.0, 1.0, truth[0]]

            # 2nd: predict boxes
            box_pr = get_predict_boxes(logit, cfg.NUM_CLASSES)

            #denomalize the corner prediction
            corners2D_gt = np.array(np.reshape(box_gt[:18], [9, 2]), dtype='float32')
            corners2D_pr = np.array(np.reshape(box_pr[:18], [9, 2]), dtype='float32')
            corners2D_gt[:, 0] = corners2D_gt[:, 0] * im_width
            corners2D_gt[:, 1] = corners2D_gt[:, 1] * im_height
            corners2D_pr[:, 0] = corners2D_pr[:, 0] * im_width
            corners2D_pr[:, 1] = corners2D_pr[:, 1] * im_height

            # Compute corner prediction error
            corner_norm = np.linalg.norm(corners2D_gt - corners2D_pr, axis=1)
            corner_dist = np.mean(corner_norm)
            errs_corner2D.append(corner_dist)

            # Compute [R|t] by pnp
            R_gt, t_gt = pnp(np.array(np.transpose(np.concatenate((np.zeros((3, 1)), self.corners3D[:3, :]), axis=1)), dtype='float32'),
                                corners2D_gt, np.array(self.internal_calibration, dtype='float32'))
            R_pr, t_pr = pnp(np.array(np.transpose(np.concatenate((np.zeros((3, 1)), self.corners3D[:3, :]), axis=1)), dtype='float32'),
                                corners2D_pr, np.array(self.internal_calibration, dtype='float32'))

            # Compute errors

            # Compute translation error
            trans_dist   = np.sqrt(np.sum(np.square(t_gt - t_pr)))
            errs_trans.append(trans_dist)

            # Compute angle error
            angle_dist   = calcAngularDistance(R_gt, R_pr)
            errs_angle.append(angle_dist)

            # Compute pixel error
            Rt_gt        = np.concatenate((R_gt, t_gt), axis=1)
            Rt_pr        = np.concatenate((R_pr, t_pr), axis=1)
            proj_2d_gt   = compute_projection(self.vertices, Rt_gt, self.internal_calibration)
            proj_2d_pred = compute_projection(self.vertices, Rt_pr, self.internal_calibration)
            norm         = np.linalg.norm(proj_2d_gt - proj_2d_pred, axis=0)
            pixel_dist   = np.mean(norm)
            errs_2d.append(pixel_dist)

            # Compute 3D distances
            transform_3d_gt   = compute_transformation(self.vertices, Rt_gt)
            transform_3d_pred = compute_transformation(self.vertices, Rt_pr)
            norm3d            = np.linalg.norm(transform_3d_gt - transform_3d_pred, axis=0)
            vertex_dist       = np.mean(norm3d)
            errs_3d.append(vertex_dist)

            # Sum errors
            testing_error_trans  += trans_dist
            testing_error_angle  += angle_dist
            testing_error_pixel  += pixel_dist
            testing_samples      += 1
        test_timer.toc()
        # Compute 2D projection, 6D pose and 5cm5degree scores
        px_threshold = 5
        acc = len(np.where(np.array(errs_2d) <= px_threshold)[0]) * 100. / (len(errs_2d)+eps)
        acc3d = len(np.where(np.array(errs_3d) <= self.vx_threshold)[0]) * 100. / (len(errs_3d)+eps)
        acc5cm5deg = len(np.where((np.array(errs_trans) <= 0.05) & (np.array(errs_angle) <= 5))[0]) * 100. / (len(errs_trans)+eps)
        corner_acc = len(np.where(np.array(errs_corner2D) <= px_threshold)[0]) * 100. / (len(errs_corner2D)+eps)
        mean_err_2d = np.mean(errs_2d)
        mean_corner_err_2d = np.mean(errs_corner2D)
        nts = float(testing_samples)
        # Print test statistics
        print("   Mean corner error is %f" % (mean_corner_err_2d))
        print('   Acc using {} px 2D Projection = {:.2f}%'.format(px_threshold, acc))
        print('   Acc using {} vx 3D Transformation = {:.2f}%'.format(self.vx_threshold, acc3d))
        print('   Acc using 5 cm 5 degree metric = {:.2f}%'.format(acc5cm5deg))
        print('   Translation error: %f, angle error: %f' % (testing_error_trans/(nts+eps), testing_error_angle/(nts+eps)) )

        # Register losses and errors for saving later on
        self.testing_errors_trans.append(testing_error_trans/(nts+eps))
        self.testing_errors_angle.append(testing_error_angle/(nts+eps))
        self.testing_errors_pixel.append(testing_error_pixel/(nts+eps))
        self.testing_accuracies.append(acc)
        test_timer.average_time
        load_timer.average_time

    def save_config(self):
        with open(os.path.join(self.output_dir, 'config.txt'), 'w') as f:
            cfg_dict = cfg.__dict__
            for key in sorted(cfg_dict.keys()):
                if key[0].isupper():
                    cfg_str = '{}: {}\n'.format(key, cfg_dict[key])
                    f.write(cfg_str)

    def __del__(self):
        self.sess.close()


def update_config_paths(data_dir, weights_file):
    cfg.DATA_DIR = data_dir
    cfg.DATASETS_DIR = os.path.join(data_dir, 'datasets')
    cfg.CACHE_DIR = os.path.join(cfg.DATASETS_DIR, 'cache')
    cfg.OUTPUT_DIR = os.path.join(cfg.DATASETS_DIR, 'output')
    cfg.WEIGHTS_DIR = os.path.join(cfg.DATASETS_DIR, 'weights')
    cfg.WEIGHTS_FILE = os.path.join(cfg.WEIGHTS_DIR, weights_file)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--datacfg', default='cfg/ape.data', type=str)
    parser.add_argument('--weights', default="yolo_6d.ckpt", type=str)
    parser.add_argument('--pre', default=False, type=bool)
    parser.add_argument('--data_dir', default="data", type=str)
    parser.add_argument('--gpu', default='0', type=str)
    args = parser.parse_args()

    if len(args.datacfg) == 0:
        print('No datacfg file specified')

    if args.pre:
        print("Pre-training... ")
        cfg.CONF_OBJ_SCALE = 0.0
        cfg.CONF_NOOBJ_SCALE = 0.0

    if args.data_dir != cfg.DATA_DIR:
        update_config_paths(args.data_dir, args.weights)

    os.environ['CUDA_VISABLE_DEVICES'] = args.gpu

    yolo = YOLO6D_net()
    datasets = Linemod('train', arg=args.datacfg)
    tfrecords = 'data/train.tfrecords'
    # solver = Solver(yolo, datasets, arg=args)
    solver = Solver(yolo, datasets, tfrecords, arg=args)

    print("\n-----------------------------start training----------------------------")
    tic = time.clock()
    solver.train()
    toc = time.clock()
    print("All training time: {}h".format((toc - tic) / 3600.0))
    print("------------------------------training end-----------------------------\n")

if __name__ == "__main__":

    main()
