#!/bin/zsh
# Lit ou modifie les paliers DPI de la Razer Viper V3 HyperSpeed.
#
#   ./dpi.sh                              -> affiche la config actuelle
#   ./dpi.sh 400 800 1600 2400 3200       -> ecrit les 5 paliers
#   ./dpi.sh 400 800 1600 2400 3200 --active 2  -> + choisit le palier actif
#   ./dpi.sh --restore stages-backup.hex  -> revient a la config sauvegardee
#
# Le service Synapse (com.razer.gms) monopolise le canal de configuration du
# recepteur : il est arrete le temps de l'operation, puis relance a la sortie.
cd "${0:A:h}"
PLIST="$HOME/Library/LaunchAgents/com.razer.gms.plist"
UID_N=$(id -u)

relancer_synapse() {
  [ -f "$PLIST" ] && launchctl bootstrap "gui/$UID_N" "$PLIST" 2>/dev/null
  return 0
}
trap relancer_synapse EXIT INT TERM

if launchctl list 2>/dev/null | grep -q com.razer.gms; then
  echo "arret temporaire du service Synapse..."
  launchctl bootout "gui/$UID_N/com.razer.gms" 2>/dev/null
  sleep 1
fi

if [ $# -eq 0 ]; then
  ./venv/bin/python probe.py
else
  ./venv/bin/python set_stages.py "$@"
fi
