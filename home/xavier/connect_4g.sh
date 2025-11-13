#!/bin/bash

CONFIG_FILE="/home/xavier/config.json"
DEVICE="/dev/cdc-wdm0"

APN=$(jq -r '.apn' "$CONFIG_FILE")

qmicli -d $DEVICE --dms-set-operating-mode=online

CID=$(qmicli -d $DEVICE --wds-allocate-cid | grep 'CID' | awk '{print $2}' | tr -d "'")

qmicli -d $DEVICE --wds-start-network=apn="$APN" --client-cid=$CID --client-no-release-cid

dhclient wwan0

ip addr show wwan0
