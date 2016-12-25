#!/usr/bin/env python
#
# VM Backup extension
#
# Copyright 2014 Microsoft Corporation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from os.path import *

import re
import sys
import subprocess
import types
from DiskUtil import DiskUtil

from StringIO import StringIO

class Error(Exception):
    pass

class Mount:
    def __init__(self, name, type, fstype, mount_point):
        self.name = name
        self.type = type
        self.fstype = fstype
        self.mount_point = mount_point

class Mounts:
    def __init__(self,patching,logger):
        self.mounts = []
        disk_util = DiskUtil(patching,logger)
        device_items = disk_util.get_device_items(None);
        device_mounts = []
        device_mount_points = []
        for device_item in device_items:
            mount = Mount(device_item.name, device_item.type, device_item.file_system, device_item.mount_point)
            device_mounts.append(mount)
            device_mount_points.append(device_item.mount_point)
        mount_points = disk_util.get_mount_points(None)
        mount_point_names = []
        for i in range(len(mount_points)-1, -1, -1):
            mount_point = mount_points[i]
            if((mount_point in device_mount_points) and (mount_point not in mount_point_names)):
                mount_point_names.append(mount_point)
                self.mounts.append(device_mounts[device_mount_points.index(mount_point)])
