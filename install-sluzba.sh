#!/bin/bash
# Nainstaluje systemd službu, aby se čtečka spustila po každém zapnutí Pi.
# Spouštěj z adresáře projektu na Raspberry Pi:  ./install-sluzba.sh
set -euo pipefail

ADRESAR=$(cd "$(dirname "$0")" && pwd)
UZIVATEL=$(whoami)

if [ ! -x "$ADRESAR/.venv/bin/python" ]; then
    echo "Chyba: $ADRESAR/.venv/bin/python neexistuje — nejdřív vytvoř venv." >&2
    exit 1
fi

# Doplní skutečného uživatele a cestu do šablony a nainstaluje jednotku.
sed "s|__UZIVATEL__|$UZIVATEL|g; s|__ADRESAR__|$ADRESAR|g" "$ADRESAR/ctecka.service" \
    | sudo tee /etc/systemd/system/ctecka.service > /dev/null

sudo systemctl daemon-reload
sudo systemctl enable ctecka.service
sudo systemctl restart ctecka.service

echo "Hotovo — čtečka se teď spustí po každém zapnutí."
echo "  stav:    sudo systemctl status ctecka"
echo "  log:     journalctl -u ctecka -f"
echo "  vypnout: sudo systemctl disable --now ctecka"
