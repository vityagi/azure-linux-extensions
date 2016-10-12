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

import array
import base64
import os
import os.path
import re
import json
import string
import subprocess
import sys
import imp
import time
import shlex
import traceback
import httplib
import xml.parsers.expat
import datetime
import ConfigParser
from threading import Thread
from time import sleep
from os.path import join
from mounts import Mounts
from mounts import Mount
from patch import *
from fsfreezer import FsFreezer
from common import CommonVariables
from parameterparser import ParameterParser
from Utils import HandlerUtil
from Utils import Status
from urlparse import urlparse
from snapshotter import Snapshotter
from backuplogger import Backuplogger
from blobwriter import BlobWriter
from taskidentity import TaskIdentity
from MachineIdentity import MachineIdentity
from PluginHost import PluginHost

#Main function is the only entrence to this extension handler

def main():
    global MyPatching,backup_logger,hutil,run_result,run_status,error_msg,freezer,freeze_result,g_fsfreeze_on
    run_result = CommonVariables.success
    run_status = 'success'
    error_msg = ''
    freeze_result = None
    g_fsfreeze_on = True
    HandlerUtil.LoggerInit('/var/log/waagent.log','/dev/stdout')
    HandlerUtil.waagent.Log("%s started to handle." % (CommonVariables.extension_name)) 
    hutil = HandlerUtil.HandlerUtility(HandlerUtil.waagent.Log, HandlerUtil.waagent.Error, CommonVariables.extension_name)
    backup_logger = Backuplogger(hutil)
    MyPatching = GetMyPatching(logger = backup_logger)
    hutil.patching = MyPatching

    for a in sys.argv[1:]:
        if re.match("^([-/]*)(disable)", a):
            disable()
        elif re.match("^([-/]*)(uninstall)", a):
            uninstall()
        elif re.match("^([-/]*)(install)", a):
            install()
        elif re.match("^([-/]*)(enable)", a):
            enable()
        elif re.match("^([-/]*)(update)", a):
            update()
        elif re.match("^([-/]*)(daemon)", a):
            daemon()

def install():
    global hutil
    hutil.do_parse_context('Install')
    hutil.do_exit(0, 'Install','success','0', 'Install Succeeded')

def timedelta_total_seconds(delta):
    if not hasattr(datetime.timedelta, 'total_seconds'):
        return delta.days * 86400 + delta.seconds
    else:
        return delta.total_seconds()

def status_report(status,status_code,message):
    global backup_logger,hutil,para_parser
    trans_report_msg = None
    if(para_parser is not None and para_parser.statusBlobUri is not None and para_parser.statusBlobUri != ""):
        trans_report_msg = hutil.do_status_report(operation='Enable',status=status,\
                status_code=str(status_code),\
                message=message,\
                taskId=para_parser.taskId,\
                commandStartTimeUTCTicks=para_parser.commandStartTimeUTCTicks)
        blobWriter = BlobWriter(hutil)
        blobWriter.WriteBlob(trans_report_msg,para_parser.statusBlobUri)
        if(trans_report_msg is not None):
            backup_logger.log("trans status report message:", True)
            backup_logger.log(trans_report_msg)
        else:
            backup_logger.log("trans_report_msg is none", True)

def exit_with_commit_log(error_msg, para_parser):
    global backup_logger
    backup_logger.log(error_msg, True, 'Error')
    if(para_parser is not None and para_parser.logsBlobUri is not None and para_parser.logsBlobUri != ""):
        backup_logger.commit(para_parser.logsBlobUri)
    sys.exit(0)

def convert_time(utcTicks):
    return datetime.datetime(1, 1, 1) + datetime.timedelta(microseconds = utcTicks / 10)

def snapshot():
    try: 
        global backup_logger,run_result,run_status,error_msg,freezer,freeze_result,snapshot_result,snapshot_done,para_parser,g_fsfreeze_on
        
        run_result = CommonVariables.success
        run_status = 'success'

        if (g_fsfreeze_on == True):
            freeze_result = freezer.freezeall() 
            backup_logger.log('T:S freeze result ' + str(freeze_result)) 
            if(freeze_result is not None and len(freeze_result.errors) > 0): 
                run_result = CommonVariables.error 
                run_status = 'error' 
            	error_msg = 'T:S Enable failed with error: ' + str(freeze_result) 
            	backup_logger.log(error_msg, False, 'Warning') 

        if (run_result == CommonVariables.success): 
            backup_logger.log('T:S doing snapshot now...') 
            snap_shotter = Snapshotter(backup_logger) 
            snapshot_result = snap_shotter.snapshotall(para_parser) 
            backup_logger.log('T:S snapshotall ends...') 
            if(snapshot_result is not None and len(snapshot_result.errors) > 0): 
                error_msg = 'T:S snapshot result: ' + str(snapshot_result) 
                run_result = CommonVariables.error 
                run_status = 'error' 
                backup_logger.log(error_msg, False, 'Error') 

        if (run_result == CommonVariables.success):
            error_msg = 'Enable Succeeded'
            backup_logger.log("T:S " + error_msg)
    except Exception as e: 
        errMsg = 'Failed to do the snapshot with error: %s, stack trace: %s' % (str(e), traceback.format_exc()) 
        backup_logger.log(errMsg, False, 'Error') 
    snapshot_done = True 

def freeze_snapshot(timeout):
    try:
        snapshot_thread = Thread(target = snapshot)
        start_time=datetime.datetime.utcnow()
        snapshot_thread.start()
        snapshot_thread.join(float(timeout))
        if not snapshot_done:
            run_result = CommonVariables.error
            run_status = 'error'
            error_msg = 'T:W Snapshot timeout'
            backup_logger.log(error_msg, False, 'Warning')
        end_time=datetime.datetime.utcnow()
        time_taken=end_time-start_time
        backup_logger.log('total time taken..' + str(time_taken))
    
        if (g_fsfreeze_on == True):
            for i in range(0,3):
                unfreeze_result = freezer.unfreezeall()
                backup_logger.log('unfreeze result ' + str(unfreeze_result))
                if(unfreeze_result is not None):
                    if len(unfreeze_result.errors) > 0:
                        error_msg += ('unfreeze with error: ' + str(unfreeze_result.errors))
                        backup_logger.log(error_msg, False, 'Warning')
                    else:
                        backup_logger.log('unfreeze result is None')
                        break;
            backup_logger.log('unfreeze ends...')
    except Exception as e:
        errMsg = 'Failed to do the snapshot with error: %s, stack trace: %s' % (str(e), traceback.format_exc())
        backup_logger.log(errMsg, False, 'Error')
        run_result = CommonVariables.error
        run_status = 'error'
        error_msg = 'Enable failed with exception in safe freeze or snapshot '

def safe_freeze_snapshot(timeout):
    try:
        global backup_logger,run_result,run_status,error_msg,freezer,freeze_result,para_parser
        
        run_result = CommonVariables.success
        run_status = 'success'

        if (g_fsfreeze_on == True):
            freeze_result = freezer.freeze_safe(timeout)
            backup_logger.log('T:S freeze result ' + str(freeze_result))
            if(freeze_result is not None and len(freeze_result.errors) > 0):
                run_result = CommonVariables.error
                run_status = 'error'
                error_msg = 'T:S Enable failed with error: ' + str(freeze_result)
                backup_logger.log(error_msg, True, 'Warning')

        if (run_result == CommonVariables.success):
            backup_logger.log('T:S doing snapshot now...')
            snap_shotter = Snapshotter(backup_logger)
            snapshot_result = snap_shotter.snapshotall(para_parser)
            backup_logger.log('T:S snapshotall ends...')
            if(snapshot_result is not None and len(snapshot_result.errors) > 0):
                error_msg = 'T:S snapshot result: ' + str(snapshot_result)
                run_result = CommonVariables.error
                run_status = 'error'
                backup_logger.log(error_msg, False, 'Error')
               
        if (g_fsfreeze_on == True):
            thaw_result=freezer.thaw_safe()
            backup_logger.log('T:S thaw result ' + str(thaw_result))
            if(thaw_result is not None and len(thaw_result.errors) > 0):
                run_result = CommonVariables.error
                run_status = 'error'
                error_msg = 'T:S Enable failed with error: ' + str(thaw_result)
                backup_logger.log(error_msg, True, 'Warning')

        if (run_result == CommonVariables.success):
            error_msg = 'Enable Succeeded'
            backup_logger.log("T:S " + error_msg)
    except Exception as e:
        errMsg = 'Failed to do the snapshot with error: %s, stack trace: %s' % (str(e), traceback.format_exc())
        backup_logger.log(errMsg, False, 'Error')
        run_result = CommonVariables.error
        run_status = 'error'
        error_msg = 'Enable failed with exception in safe freeze or snapshot ' 
    #snapshot_done = True

def daemon():
    global MyPatching,backup_logger,hutil,run_result,run_status,error_msg,freezer,para_parser,snapshot_done,g_fsfreeze_on
    #this is using the most recent file timestamp.
    hutil.do_parse_context('Executing')
    freezer = FsFreezer(patching= MyPatching, logger = backup_logger)
    global_error_result = None
    # precheck
    freeze_called = False
    configfile='/etc/azure/vmbackup.conf'
    thread_timeout=str(60)
    safe_freeze_on = True
    try:
        backup_logger.log(" configfile " + str(configfile), True)
        config = ConfigParser.ConfigParser()
        config.read(configfile)
        if (config.has_option('SnapshotThread','timeout')):
            thread_timeout = config.get('SnapshotThread','timeout')
        if (config.has_option('SnapshotThread','fsfreeze')):
            g_fsfreeze_on = config.getboolean('SnapshotThread','fsfreeze')
        if (config.has_option('SnapshotThread','safefreeze')):
            safe_freeze_on = config.getboolean('SnapshotThread','safefreeze')
    except Exception as ex:
        errMsg='cannot read config file or file not present, ex: '+str(ex)
        backup_logger.log(errMsg, True, 'Warning')
    backup_logger.log("final thread timeout" + thread_timeout, True)
    backup_logger.log(" fsfreeze flag " + str(g_fsfreeze_on), True)
    backup_logger.log(" safe freeze flag " + str(safe_freeze_on), True)

    try:
        # we need to freeze the file system first
        backup_logger.log('starting daemon', True)
        """
        protectedSettings is the privateConfig passed from Powershell.
        WATCHOUT that, the _context_config are using the most freshest timestamp.
        if the time sync is alive, this should be right.
        """

        protected_settings = hutil._context._config['runtimeSettings'][0]['handlerSettings'].get('protectedSettings')
        public_settings = hutil._context._config['runtimeSettings'][0]['handlerSettings'].get('publicSettings')
        para_parser = ParameterParser(protected_settings, public_settings)

        commandToExecute = para_parser.commandToExecute
        #validate all the required parameter here
        if(commandToExecute.lower() == CommonVariables.iaas_install_command):
            backup_logger.log('install succeed.',True)
            run_status = 'success'
            error_msg = 'Install Succeeded'
            run_result = CommonVariables.success
            backup_logger.log(error_msg)
        elif(commandToExecute.lower() == CommonVariables.iaas_vmbackup_command):
            if(para_parser.backup_metadata is None or para_parser.public_config_obj is None or para_parser.private_config_obj is None):
                run_result = CommonVariables.error_parameter
                run_status = 'error'
                error_msg = 'required field empty or not correct'
                backup_logger.log(error_msg, False, 'Error')
            else:
                backup_logger.log('commandToExecute is ' + commandToExecute, True)
                """
                make sure the log is not doing when the file system is freezed.
                """
                temp_status= 'success'
                temp_result=CommonVariables.ExtensionTempTerminalState
                temp_msg='Transitioning state in extension'
                status_report(temp_status,temp_result,temp_msg)
                backup_logger.log('doing freeze now...', True)
                #partial logging before freeze
                if(para_parser is not None and para_parser.logsBlobUri is not None and para_parser.logsBlobUri != ""):
                    backup_logger.commit_to_blob(para_parser.logsBlobUri)
                else:
                    backup_logger.log("the logs blob uri is not there, so do not upload log.")
                
                backup_logger.log('commandToExecute is ' + commandToExecute, True)

                PluginHostObj = PluginHost(logger=backup_logger)
                preResult = PluginHostObj.pre_script()
                dobackup = preResult.continueBackup
                if preResult.continueBackup:
                    if(safe_freeze_on==True):
                        safe_freeze_snapshot(thread_timeout)
                    else:
                        freeze_snapshot(thread_timeout)
                postResult = PluginHostObj.post_script()
                if not postResult.continueBackup:
                    dobackup = False

                if not dobackup:
                    run_status = 'error'
                    run_result = CommonVariables.error
                    error_msg = 'Scripts failed and backup also failed'
                    backup_logger.log(error_msg,False,'Error')
                elif preResult.anyScriptFailed or postResult.anyScriptFailed:
                    error_msg = 'Scripts failed but continue backup'
                    backup_logger.log(error_msg,False,'Error')
                
        else:
            run_status = 'error'
            run_result = CommonVariables.error_parameter
            error_msg = 'command is not correct'
            backup_logger.log(error_msg, False, 'Error')
    except Exception as e:
        errMsg = 'Failed to enable the extension with error: %s, stack trace: %s' % (str(e), traceback.format_exc())
        backup_logger.log(errMsg, False, 'Error')
        global_error_result = e

    """
    we do the final report here to get rid of the complex logic to handle the logging when file system be freezed issue.
    """
    if(global_error_result is not None):
        if(hasattr(global_error_result,'errno') and global_error_result.errno == 2):
            run_result = CommonVariables.error_12
        elif(para_parser is None):
            run_result = CommonVariables.error_parameter
        else:
            run_result = CommonVariables.error
        run_status = 'error'
        error_msg  += ('Enable failed.' + str(global_error_result))
    status_report_msg = None
    status_report(run_status,run_result,error_msg)
    if(para_parser is not None and para_parser.logsBlobUri is not None and para_parser.logsBlobUri != ""):
        backup_logger.commit(para_parser.logsBlobUri)
    else:
        backup_logger.log("the logs blob uri is not there, so do not upload log.")
        backup_logger.commit_to_local()

    hutil.do_exit(0, 'Enable', run_status, str(run_result), error_msg)

def uninstall():
    hutil.do_parse_context('Uninstall')
    hutil.do_exit(0,'Uninstall','success','0', 'Uninstall succeeded')

def disable():
    hutil.do_parse_context('Disable')
    hutil.do_exit(0,'Disable','success','0', 'Disable Succeeded')

def update():
    hutil.do_parse_context('Upadate')
    hutil.do_exit(0,'Update','success','0', 'Update Succeeded')

def enable():
    global backup_logger,hutil,error_msg,para_parser
    hutil.do_parse_context('Enable')
    try:
        backup_logger.log('starting to enable', True)

        # handle the restoring scenario.
        mi = MachineIdentity()
        stored_identity = mi.stored_identity()
        if(stored_identity is None):
            mi.save_identity()
        else:
            current_identity = mi.current_identity()
            if(current_identity != stored_identity):
                current_seq_no = -1
                backup_logger.log("machine identity not same, set current_seq_no to " + str(current_seq_no) + " " + str(stored_identity) + " " + str(current_identity), True)
                hutil.set_last_seq(current_seq_no)
                mi.save_identity()

        hutil.exit_if_same_seq()
        hutil.save_seq()

        """
        protectedSettings is the privateConfig passed from Powershell.
        WATCHOUT that, the _context_config are using the most freshest timestamp.
        if the time sync is alive, this should be right.
        """
        protected_settings = hutil._context._config['runtimeSettings'][0]['handlerSettings'].get('protectedSettings')
        public_settings = hutil._context._config['runtimeSettings'][0]['handlerSettings'].get('publicSettings')
        para_parser = ParameterParser(protected_settings, public_settings)

        if(para_parser.commandStartTimeUTCTicks is not None and para_parser.commandStartTimeUTCTicks != ""):
            utcTicksLong = long(para_parser.commandStartTimeUTCTicks)
            backup_logger.log('utcTicks in long format' + str(utcTicksLong), True)
            commandStartTime = convert_time(utcTicksLong)
            utcNow = datetime.datetime.utcnow()
            backup_logger.log('command start time is ' + str(commandStartTime) + " and utcNow is " + str(utcNow), True)
            timespan = utcNow - commandStartTime
            THIRTY_MINUTES = 30 * 60 # in seconds
            # handle the machine identity for the restoration scenario.
            total_span_in_seconds = timedelta_total_seconds(timespan)
            backup_logger.log('timespan is ' + str(timespan) + ' ' + str(total_span_in_seconds))
            if(abs(total_span_in_seconds) > THIRTY_MINUTES):
                error_msg = 'the call time stamp is out of date. so skip it.'
                exit_with_commit_log(error_msg, para_parser)

        if(para_parser.taskId is not None and para_parser.taskId != ""):
            taskIdentity = TaskIdentity()
            taskIdentity.save_identity(para_parser.taskId)
        temp_status= 'transitioning'
        temp_result=CommonVariables.success
        temp_msg='Transitioning state in enable'
        status_report(temp_status,temp_result,temp_msg)
        start_daemon();
    except Exception as e:
        errMsg = 'Failed to call the daemon with error: %s, stack trace: %s' % (str(e), traceback.format_exc())
        backup_logger.log(errMsg, False, 'Error')
        global_error_result = e

def start_daemon():
    args = [os.path.join(os.getcwd(), __file__), "-daemon"]
    backup_logger.log("start_daemon with args: {0}".format(args), True)
    #This process will start a new background process by calling
    #    handle.py -daemon
    #to run the script and will exit itself immediatelly.

    #Redirect stdout and stderr to /dev/null.  Otherwise daemon process will
    #throw Broke pipe exeception when parent process exit.
    devnull = open(os.devnull, 'w')
    child = subprocess.Popen(args, stdout=devnull, stderr=devnull)

if __name__ == '__main__' :
    main()
