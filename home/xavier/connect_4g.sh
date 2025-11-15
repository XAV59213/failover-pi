#!/usr/bin/env bash
# =====================================================================
#  Failover-Pi : Connexion 4G via SIM7600E / qmicli
#  Fichier  : /home/xavier/connect_4g.sh
# =====================================================================

APN="${APN:-free}"
MODEM_DEV="${MODEM_DEV:-/dev/cdc-wdm0}"
WWAN_IF="${WWAN_IF:-wwan0}"

log() {
    echo "$(date '+%d/%m/%Y %H:%M:%S') [4G] $*"
}

echo "=== Failover-Pi : Connexion 4G ==="
echo "APN : $APN"
echo "Modem : $MODEM_DEV"
echo "Interface : $WWAN_IF"
echo

log "Arrêt éventuel de ModemManager (si présent)..."
if command -v systemctl >/dev/null 2>&1; then
    sudo systemctl stop ModemManager.service 2>/dev/null || true
fi

# ---------------------------------------------------------------------
#  Reset USB du modem (en cas de freeze / endpoint hangup)
# ---------------------------------------------------------------------
usb_reset_modem() {
    log "Tentative de reset USB du modem..."

    if [ ! -e "$MODEM_DEV" ]; then
        log "Impossible de trouver $MODEM_DEV, reset USB via sysfs impossible."
        return 1
    fi

    # Exemple : /sys/class/usbmisc/cdc-wdm0
    local misc_path sys_path bus_id
    misc_path="$(readlink -f "/sys/class/usbmisc/$(basename "$MODEM_DEV")" 2>/dev/null || true)"
    if [ -z "$misc_path" ] || [ ! -e "$misc_path" ]; then
        log "Chemin sysfs introuvable pour $MODEM_DEV."
        return 1
    fi

    # Remonter jusqu'à un noeud type "1-1", "2-1.2", etc.
    sys_path="$misc_path"
    while [ "$sys_path" != "/" ] && [[ "$(basename "$sys_path")" != *"-"* ]]; do
        sys_path="$(dirname "$sys_path")"
    done

    bus_id="$(basename "$sys_path")"
    if [[ -z "$bus_id" || "$bus_id" == "/" ]]; then
        log "Impossible de déterminer le bus USB du modem ($misc_path)."
        return 1
    fi

    log "Reset USB sur le bus : $bus_id"
    if [ -w /sys/bus/usb/drivers/usb/unbind ] && [ -w /sys/bus/usb/drivers/usb/bind ]; then
        echo "$bus_id" | sudo tee /sys/bus/usb/drivers/usb/unbind >/dev/null 2>&1 || true
        sleep 2
        echo "$bus_id" | sudo tee /sys/bus/usb/drivers/usb/bind >/dev/null 2>&1 || true
        sleep 5
        log "Reset USB demandé. Attente que $MODEM_DEV réapparaisse..."

        for i in $(seq 1 20); do
            if [ -e "$MODEM_DEV" ]; then
                log "$MODEM_DEV détecté à nouveau après reset USB."
                return 0
            fi
            sleep 1
        done

        log "Après reset USB, $MODEM_DEV n'est toujours pas présent."
        return 1
    else
        log "Impossible d'écrire dans /sys/bus/usb/drivers/usb/* (droits manquants ?)."
        return 1
    fi
}

# ---------------------------------------------------------------------
#  Conversion masque → /CIDR sans bc
# ---------------------------------------------------------------------
mask_to_prefix() {
    local mask="$1"
    local o1 o2 o3 o4
    IFS=. read -r o1 o2 o3 o4 <<< "$mask"

    local sum=0
    for o in "$o1" "$o2" "$o3" "$o4"; do
        local b=0
        case "$o" in
            255) b=8 ;;
            254) b=7 ;;
            252) b=6 ;;
            248) b=5 ;;
            240) b=4 ;;
            224) b=3 ;;
            192) b=2 ;;
            128) b=1 ;;
            0)   b=0 ;;
            *)   b=0 ;; # valeur non standard, on ne casse pas tout
        esac
        sum=$((sum + b))
    done
    echo "$sum"
}

# ---------------------------------------------------------------------
#  Configuration de l'interface wwan0 en raw-ip
# ---------------------------------------------------------------------
echo "[i] Configuration $WWAN_IF en raw-ip..."
if [ -w "/sys/class/net/$WWAN_IF/qmi/raw_ip" ]; then
    echo "Y" | sudo tee "/sys/class/net/$WWAN_IF/qmi/raw_ip" >/dev/null 2>&1 || true
fi

echo "[i] Remise à zéro de $WWAN_IF..."
sudo ip link set "$WWAN_IF" down 2>/dev/null || true
sudo ip addr flush dev "$WWAN_IF" 2>/dev/null || true

# ---------------------------------------------------------------------
#  Lecture / bascule du mode du modem (ONLINE) avec plusieurs tentatives
# ---------------------------------------------------------------------
echo "[i] Vérification du mode du modem..."

get_modem_mode() {
    sudo qmicli -d "$MODEM_DEV" --dms-get-operating-mode 2>&1
}

set_modem_online() {
    sudo qmicli -d "$MODEM_DEV" --dms-set-operating-mode="online" 2>&1
}

MAX_MODE_TRIES=3
MODE_OK=0

for attempt in $(seq 1 $MAX_MODE_TRIES); do
    OUT="$(get_modem_mode)"
    RC=$?
    if [ $RC -eq 0 ] && echo "$OUT" | grep -q "Mode: 'online'"; then
        log "Modem déjà en mode ONLINE."
        MODE_OK=1
        break
    fi

    log "Erreur lecture mode modem (tentative $attempt) : $OUT"

    if echo "$OUT" | grep -qi "endpoint hangup\|Resource temporarily unavailable\|No such device"; then
        log "Anomalie USB détectée (endpoint hangup / resource unavailable)."
        usb_reset_modem || log "Reset USB modem a échoué (on continue quand même)."
    fi

    OUT2="$(set_modem_online)"
    if echo "$OUT2" | grep -q "set successfully"; then
        log "Modem basculé en mode ONLINE avec succès."
        MODE_OK=1
        break
    else
        log "Échec bascule ONLINE (tentative $attempt) : $OUT2"
    fi

    sleep 3
done

if [ $MODE_OK -ne 1 ]; then
    echo "ERREUR : impossible de lire ou mettre le modem en mode ONLINE"
    log "ERREUR : impossible de lire ou mettre le modem en mode ONLINE"
    exit 1
fi

# ---------------------------------------------------------------------
#  Démarrage session data (QMI)
# ---------------------------------------------------------------------
echo "[i] Démarrage de la session data (QMI)..."

START_OUT="$(sudo qmicli -d "$MODEM_DEV" --wds-start-network="apn='$APN',ip-type=4" --client-no-release-cid 2>&1)"
if echo "$START_OUT" | grep -qi "endpoint hangup\|No such device"; then
    log "Erreur endpoint hangup lors du démarrage data. Tentative de reset USB..."
    usb_reset_modem || log "Reset USB (échec ou partiel)."
    START_OUT="$(sudo qmicli -d "$MODEM_DEV" --wds-start-network="apn='$APN',ip-type=4" --client-no-release-cid 2>&1)"
fi

if ! echo "$START_OUT" | grep -q "Network started"; then
    echo "ERREUR : échec du démarrage réseau 4G"
    log "ERREUR : échec du démarrage réseau 4G"
    echo "$START_OUT"
    exit 1
fi

echo "$START_OUT" | sed 's/^/    /'
echo

# ---------------------------------------------------------------------
#  Lecture des paramètres IP via --wds-get-current-settings
# ---------------------------------------------------------------------
echo "[i] Lecture des paramètres IP via --wds-get-current-settings..."
SETTINGS_OUT="$(sudo qmicli -d "$MODEM_DEV" --wds-get-current-settings 2>&1)"
echo "$SETTINGS_OUT" | sed 's/^/    /'
echo

ADDR="$(echo "$SETTINGS_OUT" | awk -F": " '/IPv4 address:/ {print $2; exit}')"
MASK="$(echo "$SETTINGS_OUT" | awk -F": " '/IPv4 subnet mask:/ {print $2; exit}')"
GW="$(echo "$SETTINGS_OUT" | awk -F": " '/IPv4 gateway address:/ {print $2; exit}')"
DNS1="$(echo "$SETTINGS_OUT" | awk -F": " '/IPv4 primary DNS:/ {print $2; exit}')"
DNS2="$(echo "$SETTINGS_OUT" | awk -F": " '/IPv4 secondary DNS:/ {print $2; exit}')"

echo "DEBUG ADDR='$ADDR' GW='$GW' MASK='$MASK'"

if [ -z "$ADDR" ] || [ -z "$GW" ] || [ -z "$MASK" ]; then
    echo "ERREUR : impossible de récupérer l'adresse IP ou la gateway depuis QMI."
    log "ERREUR : impossible de récupérer l'adresse IP ou la gateway depuis QMI."
    exit 1
fi

PREFIX="$(mask_to_prefix "$MASK")"
echo
echo "Adresse IP  : $ADDR/$PREFIX"
echo "Gateway     : $GW"
echo "Masque brut : $MASK"
echo "DNS         : $DNS1 $DNS2"
echo

# ---------------------------------------------------------------------
#  Application configuration IP + routes
# ---------------------------------------------------------------------
echo "[i] Activation de $WWAN_IF et application de la configuration IP..."

sudo ip link set "$WWAN_IF" up || true
sudo ip addr flush dev "$WWAN_IF" || true
sudo ip addr add "$ADDR/$PREFIX" dev "$WWAN_IF" || true

echo "[i] Suppression des routes par défaut existantes sur $WWAN_IF..."
sudo ip route del default dev "$WWAN_IF" 2>/dev/null || true

echo "[i] Ajout de la route par défaut via $GW ($WWAN_IF)..."
sudo ip route add default via "$GW" dev "$WWAN_IF" metric 10 2>/dev/null || true

echo
echo "État de $WWAN_IF :"
ip addr show "$WWAN_IF"
echo
echo "Table de routage actuelle :"
ip route
echo

# ---------------------------------------------------------------------
#  Test ping
# ---------------------------------------------------------------------
echo "Test ping 8.8.8.8 depuis $WWAN_IF..."
if ping -I "$WWAN_IF" -c 3 -W 3 8.8.8.8 >/dev/null 2>&1; then
    echo
    echo "=== Connexion 4G : OK (ping réussi) ==="
    log "Connexion 4G active (ping OK)."
    exit 0
else
    echo
    echo "=== Connexion 4G : ping KO (à vérifier) ==="
    log "Connexion 4G active mais ping KO (à vérifier)."
    exit 0  # 0 pour indiquer au monitor que la 4G a au moins une IP
fi
