#!/bin/zsh
# Lance l'interface graphique des reglages de la Viper V3 HyperSpeed.
# Ouvre http://127.0.0.1:8787 dans le navigateur. Ctrl-C pour quitter
# (le service Synapse est alors relance automatiquement).
cd "${0:A:h}"
exec ./venv/bin/python -u server.py "$@"
