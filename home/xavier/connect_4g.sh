#!/bin/bash

CONFIG_FILE="/home/xavier/config.json"
DEVICE="/dev/cdc-wdm0"

APN=$(jq -r '.apn' "$CONFIG_FILE")

# Mettre le modem en mode online
qmicli -d $DEVICE --dms-set-operating-mode=online

# Allocation du client ID
CID=$(qmicli -d $DEVICE --wds-allocate-cid | grep 'CID' | awk '{print $2}' | tr -d "'")

# Démarrage connexion data
qmicli -d $DEVICE --wds-start-network=apn="$APN" --client-cid=$CID --client-no-release-cid

# Attribution IP au modem
dhclient wwan0

# Affichage
ip addr show wwan0
