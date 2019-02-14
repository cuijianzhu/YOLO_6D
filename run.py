#! /usr/bin/env python
# coding=utf-8
#================================================================
#   Copyright (C) 2019 * Ltd. All rights reserved.
#
#   Editor      : VIM
#   File name   : run.py
#   Author      : Mofan
#   Created date: 2019-02-14 21:29:34
#   Description :
#
#================================================================

import os

print("running ape...")
os.system('python tfrecords.py --name ape')
print("running benchvise...")
os.system('python tfrecords.py --name benchvise')
print("running cam...")
os.system('python tfrecords.py --name cam')
print("running can...")
os.system('python tfrecords.py --name can')
print("running cat...")
os.system('python tfrecords.py --name cat')
print("running driller...")
os.system('python tfrecords.py --name driller')
print("running duck...")
os.system('python tfrecords.py --name duck')
print("running eggbox...")
os.system('python tfrecords.py --name eggbox')
print("running glue...")
os.system('python tfrecords.py --name glue')
print("running holepuncher...")
os.system('python tfrecords.py --name holepuncher')
print("running iron...")
os.system('python tfrecords.py --name iron')
print("running lamp...")
os.system('python tfrecords.py --name lamp')
print("running phone...")
os.system('python tfrecords.py --name phone')

