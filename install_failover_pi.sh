#!/bin/bash
set -e

TARGET_USER="xavier"
HOME_DIR="/home/$TARGET_USER"
REPO_DIR="$(pwd)"
SYSTEMD_DIR="/etc/systemd/system"

echo "=== failover-pi - Script d'installation ==="

# ---------------------------------------------------------
# Vérification root
# ---------------------------------------------------------
if [ "$EUID" -ne 0 ]; then
  echo "Erreur : ce script doit être exécuté avec sudo."
  exit 1
fi

# ---------------------------------------------------------
# Vérification utilisateur
# ---------------------------------------------------------
if ! id "$TARGET_USER" >/dev/null 2>&1; then
  echo "Erreur : l'utilisateur $TARGET_USER n'existe pas."
  exit 1
fi

echo
echo "Utilisateur : $TARGET_USER"
echo "Home : $HOME_DIR"
echo "Repo : $REPO_DIR"
echo

# ---------------------------------------------------------
# Création des répertoires nécessaires
# ---------------------------------------------------------
mkdir -p "$HOME_DIR/backups"
mkdir -p "$HOME_DIR/restore_tmp"

# ---------------------------------------------------------
# Copie des fichiers depuis le dépôt
# ---------------------------------------------------------
echo "-> Copie des fichiers…"

if [ -d "$REPO_DIR/home/xavier" ]; then

  # Dossier dashboard complet
  rm -rf "$HOME_DIR/dashboard"
  cp -r "$REPO_DIR/home/xavier/dashboard" "$HOME_DIR/"

  # Copie des fichiers racine
  for f in config.json connect_4g.sh monitor_failover.py run_dashboard.py send_sms.py status_history.json; do
    SRC="$REPO_DIR/home/xavier/$f"
    DEST="$HOME_DIR/$f"
    [ ! -f "$SRC" ] && continue

    # Ne jamais écraser un config.json existant
    if [ "$f" = "config.json" ] && [ -f "$DEST" ]; then
      echo "   - config.json déjà présent → conservé."
      continue
    fi

    cp "$SRC" "$DEST"
  done

else
  echo "ERREUR : dossier $REPO_DIR/home/xavier introuvable."
  exit 1
fi

# ---------------------------------------------------------
# Fichiers système requis
# ---------------------------------------------------------
touch "$HOME_DIR/monitor.log"

# status_history.json si vide
if [ ! -s "$HOME_DIR/status_history.json" ]; then
  echo '{"times":[],"states":[]}' > "$HOME_DIR/status_history.json"
fi

# Base utilisateurs si absente
if [ ! -f "$HOME_DIR/.dashboard_users.json" ]; then
  echo '{"users":[]}' > "$HOME_DIR/.dashboard_users.json"
fi

# ---------------------------------------------------------
# Permissions
# ---------------------------------------------------------
chown -R "$TARGET_USER:$TARGET_USER" "$HOME_DIR"

chmod +x "$HOME_DIR"/{connect_4g.sh,monitor_failover.py,run_dashboard.py,send_sms.py}

# ---------------------------------------------------------
# Installation des services systemd
# ---------------------------------------------------------
echo "-> Installation services systemd…"

cp "$REPO_DIR/etc/systemd/system/failover-dashboard.service" "$SYSTEMD_DIR/"
cp "$REPO_DIR/etc/systemd/system/failover-monitor.service" "$SYSTEMD_DIR/"

# ---------------------------------------------------------
# Dépendances
# ---------------------------------------------------------
echo "-> Installation paquets…"

apt-get update
apt-get install -y \
  python3 python3-pip python3-venv python3-serial python3-flask \
  jq libqmi-utils usb-modeswitch modemmanager

# pip3 install --upgrade pip
# pip3 install --upgrade flask pyserial

# ---------------------------------------------------------
# Génération secret key auto
# ---------------------------------------------------------
if grep -q "your_generated_key" "$SYSTEMD_DIR/failover-dashboard.service"; then
  NEW_KEY=$(python3 - << 'EOF'
import secrets, base64
print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())
EOF
)
  sed -i "s/your_generated_key/$NEW_KEY/" "$SYSTEMD_DIR/failover-dashboard.service"
  echo "Nouvelle secret-key générée."
fi

# ---------------------------------------------------------
# Activation des services
# ---------------------------------------------------------
systemctl daemon-reload
systemctl enable failover-dashboard.service
systemctl enable failover-monitor.service

echo
echo "=== Installation terminée ==="
echo "Lance les services :"
echo "  sudo systemctl start failover-dashboard"
echo "  sudo systemctl start failover-monitor"
echo
echo "Dashboard → http://<ip-du-pi>:5123/"
