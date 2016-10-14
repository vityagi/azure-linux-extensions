#!/bin/bash
instance=$1

# variables used for returning the status of the scripts
success=0
error=1
warning=2

retVal=$success

log_path="/etc/postScript.log"   #path of log file
printf  "Instance: $instance \n" > $log_path

csession $instance -U%SYS "##Class(Backup.General).ExternalThaw()"
status=$?
if [ $status -eq 5 ]; then
echo "SYSTEM IS UNFROZEN"
printf  "SYSTEM IS UNFROZEN\n" >> $log_path
elif [ $status -eq 3 ]; then
echo "SYSTEM UNFREEZE FAILED"
printf  "SYSTEM UNFREEZE FAILED\n" >> $log_path
retVal=$error
fi

exit $retVal

