#!/bin/bash
set -e

TARGET_USER="xavier"
HOME_DIR="/home/$TARGET_USER"
REPO_DIR="$(pwd)"  # répertoire courant = racine du projet (avec home/ et etc/)
SYSTEMD_DIR="/etc/systemd/system"

echo "=== failover-pi - Script d'installation ==="

# 1) Vérifications de base
if [ "$EUID" -ne 0 ]; then
  echo "Erreur : ce script doit être exécuté en root (sudo)."
  exit 1
fi

if ! id "$TARGET_USER" >/dev/null 2>&1; then
  echo "Erreur : l'utilisateur $TARGET_USER n'existe pas."
  echo "Crée-le avec par exemple : sudo adduser $TARGET_USER"
  exit 1
fi

echo "Utilisateur cible : $TARGET_USER"
echo "Home : $HOME_DIR"
echo "Repo : $REPO_DIR"
echo

# 2) Création des dossiers nécessaires
echo "-> Création des dossiers backups et restore_tmp..."
mkdir -p "$HOME_DIR/backups"
mkdir -p "$HOME_DIR/restore_tmp"

# 3) Copie des fichiers dans /home/xavier
echo "-> Copie des fichiers dans $HOME_DIR..."

# on copie les fichiers de home/xavier/ vers /home/xavier
# sans écraser un config.json existant
if [ -d "$REPO_DIR/home/xavier" ]; then
  # dashboard (on écrase la version existante si besoin)
  rm -rf "$HOME_DIR/dashboard"
  cp -r "$REPO_DIR/home/xavier/dashboard" "$HOME_DIR/"

  # autres fichiers (monitor, scripts, etc.)
  for f in config.json connect_4g.sh monitor_failover.py run_dashboard.py send_sms.py status_history.json; do
    if [ -f "$REPO_DIR/home/xavier/$f" ]; then
      # config.json : on ne l'écrase pas si déjà présent
      if [ "$f" = "config.json" ] && [ -f "$HOME_DIR/config.json" ]; then
        echo "   - $f existe déjà, non écrasé."
      else
        cp "$REPO_DIR/home/xavier/$f" "$HOME_DIR/"
      fi
    fi
  done
else
  echo "Erreur : dossier $REPO_DIR/home/xavier introuvable."
  exit 1
fi

# 4) Préparation des fichiers de log / JSON
echo "-> Préparation de monitor.log et status_history.json..."

# monitor.log
if [ ! -f "$HOME_DIR/monitor.log" ]; then
  touch "$HOME_DIR/monitor.log"
fi

# status_history.json avec JSON valide
if [ ! -s "$HOME_DIR/status_history.json" ]; then
  echo '{"times":[],"states":[]}' > "$HOME_DIR/status_history.json"
fi

# base utilisateurs du dashboard
if [ ! -f "$HOME_DIR/.dashboard_users.json" ]; then
  echo '{"users":[]}' > "$HOME_DIR/.dashboard_users.json"
fi

# 5) Droits et exécutions
echo "-> Attribution des droits et des permissions d'exécution..."

chown -R "$TARGET_USER:$TARGET_USER" "$HOME_DIR"

chmod +x "$HOME_DIR/connect_4g.sh" \
         "$HOME_DIR/monitor_failover.py" \
         "$HOME_DIR/run_dashboard.py" \
         "$HOME_DIR/send_sms.py"

# 6) Installation des services systemd
echo "-> Installation des services systemd..."

if [ -f "$REPO_DIR/etc/systemd/system/failover-dashboard.service" ]; then
  cp "$REPO_DIR/etc/systemd/system/failover-dashboard.service" "$SYSTEMD_DIR/"
fi

if [ -f "$REPO_DIR/etc/systemd/system/failover-monitor.service" ]; then
  cp "$REPO_DIR/etc/systemd/system/failover-monitor.service" "$SYSTEMD_DIR/"
fi

# 7) Génération automatique d'une DASH_SECRET_KEY si placeholder
echo "-> Configuration de DASH_SECRET_KEY dans failover-dashboard.service..."

if grep -q "your_generated_key" "$SYSTEMD_DIR/failover-dashboard.service"; then
  NEW_KEY=$(python3 - << 'EOF'
import secrets, base64
print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())
EOF
)
  sed -i "s/your_generated_key/$NEW_KEY/" "$SYSTEMD_DIR/failover-dashboard.service"
  echo "   Nouvelle DASH_SECRET_KEY générée."
else
  echo "   DASH_SECRET_KEY déjà définie, laissé tel quel."
fi

# 8) Installation des dépendances système (Debian / Ubuntu / Raspbian)
echo "-> Installation des paquets nécessaires via apt..."

apt-get update
apt-get install -y \
  python3 \
  python3-pip \
  python3-venv \
  python3-serial \
  python3-flask \
  jq \
  qmicli

# 9) Installation (ou mise à jour) des dépendances Python via pip
echo "-> Installation des modules Python (pip)..."

pip3 install --upgrade pip
pip3 install --upgrade flask pyserial

# 10) Activation des services
echo "-> Activation des services failover-dashboard et failover-monitor..."

systemctl daemon-reload
systemctl enable failover-dashboard.service
systemctl enable failover-monitor.service

echo
echo "=== Installation terminée ==="
echo "Tu peux maintenant démarrer les services avec :"
echo "  sudo systemctl start failover-dashboard.service"
echo "  sudo systemctl start failover-monitor.service"
echo
echo "Ensuite, ouvre ton navigateur sur : http://<ip_du_pi>:5123/"
echo "La première fois, tu passeras par /setup pour créer le compte admin."
