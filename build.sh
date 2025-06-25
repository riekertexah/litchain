#!/usr/bin/env bash
set -o errexit

python3 -m pip install --upgrade pip

# Force install the wheel file directly
pip install ./chainlit-2.5.5+lc-cp312-cp312-manylinux_2_39_x86_64.whl --force-reinstall --no-deps

# Install other requirements
pip install -r requirements.txt -vvv
