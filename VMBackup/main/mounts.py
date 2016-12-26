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
        added_mount_point_names = []
        disk_util = DiskUtil(patching,logger)
        # Get mount points
        mount_points = disk_util.get_mount_points(None)
        # Get lsblk devices
        device_items = disk_util.get_device_items(None);
        lsblk_mounts = []
        lsblk_mount_points = []
        # List to hold mount-points returned from lsblk command but not reurned from mount command
        lsblk_mounts_not_in_mount = []
        for device_item in device_items:
            mount = Mount(device_item.name, device_item.type, device_item.file_system, device_item.mount_point)
            lsblk_mounts.append(mount)
            lsblk_mount_points.append(device_item.mount_point)
            # If lsblk mount is not found in "mount command" mount-list, add it to the lsblk_mounts_not_in_mount array
            if((device_item.mount_point not in mount_points) and (device_item.mount_point not in lsblk_mounts_not_in_mount)):
                lsblk_mounts_not_in_mount.append(device_item.mount_point)
        # Sort lsblk_mounts_not_in_mount array in ascending order
        lsblk_mounts_not_in_mount.sort()
        # Add the lsblk devices in the same order as they are returned in mount command output
        for i in range(0, len(mount_points)):
            mount_point = mount_points[i]
            if((mount_point in lsblk_mount_points) and (mount_point not in added_mount_point_names)):
                self.mounts.append(lsblk_mounts[lsblk_mount_points.index(mount_point)])
                added_mount_point_names.append(mount_point)
        # Append all the lsblk devices corresponding to lsblk_mounts_not_in_mount list mount-points
        for i in range(0, len(lsblk_mounts_not_in_mount)):
            mount_point = lsblk_mounts_not_in_mount[i]
            if((mount_point in lsblk_mount_points) and (mount_point not in added_mount_point_names)):
                self.mounts.append(lsblk_mounts[lsblk_mount_points.index(mount_point)])
                added_mount_point_names.append(mount_point)
        added_mount_point_names.reverse()
        logger.log("added_mount_point_names :" + str(added_mount_point_names), True)
        # Reverse the mounts list
        self.mounts.reverse()
