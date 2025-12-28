#!/usr/bin/env bash
set -e

# Increase the pip timeout to handle TimeoutError
export PIP_DEFAULT_TIMEOUT=200

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null && pwd )"
ROOT="$DIR"/../
cd "$ROOT"

if ! command -v "uv" > /dev/null 2>&1; then
  echo "installing uv..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  UV_BIN="$HOME/.local/bin"
  PATH="$UV_BIN:$PATH"
fi

echo "updating uv..."
# ok to fail, can also fail due to installing with brew
uv self update || true

echo "installing python packages..."
uv sync --frozen --all-extras
source .venv/bin/activate

# Create .env file if it doesn't exist
if [ ! -f "$ROOT"/.env ]; then
  echo "# Environment variables for openpilot" > "$ROOT"/.env
fi

# Add PYTHONPATH if not already present
if ! grep -q "PYTHONPATH=" "$ROOT"/.env; then
  echo "PYTHONPATH=${PWD}" >> "$ROOT"/.env
fi

# Users can manually add GPU support by uncommenting and modifying the following line
# export DEV=AMD  # Use AMD GPU for model inference
# export DEV=NVIDIA  # Use NVIDIA GPU for model inference

# Enable ZMQ by default if not already present
if ! grep -q "export ZMQ=" "$ROOT"/.env; then
  echo "# Enable ZMQ for IPC" >> "$ROOT"/.env
  echo "export ZMQ=1" >> "$ROOT"/.env
fi

# Enable webcam support by default if not already present
if ! grep -q "export USE_WEBCAM=" "$ROOT"/.env; then
  echo "# Enable webcam support" >> "$ROOT"/.env
  echo "export USE_WEBCAM=1" >> "$ROOT"/.env
fi

# Add ROAD_CAM if not already present
if ! grep -q "export ROAD_CAM=" "$ROOT"/.env; then
  echo "export ROAD_CAM=0" >> "$ROOT"/.env
fi

# Add DRIVER_CAM to disable driver camera
if grep -q "export DRIVER_CAM=" "$ROOT"/.env; then
  sed -i 's/.*export DRIVER_CAM=.*/export DRIVER_CAM=""  # Disable driver camera/' "$ROOT"/.env
else
  echo "export DRIVER_CAM=""  # Disable driver camera" >> "$ROOT"/.env
fi

# Add WIDE_CAM to disable wide camera
if grep -q "export WIDE_CAM=" "$ROOT"/.env; then
  sed -i 's/.*export WIDE_CAM=.*/export WIDE_CAM=""  # Disable wide camera/' "$ROOT"/.env
else
  echo "export WIDE_CAM=""  # Disable wide camera" >> "$ROOT"/.env
fi

# Add PARAMS_ROOT to set parameter directory to project root for PC environment
if ! grep -q "export PARAMS_ROOT=" "$ROOT"/.env; then
  echo "# Set parameter directory to project root for PC environment" >> "$ROOT"/.env
  echo "export PARAMS_ROOT=${PWD}/data/params" >> "$ROOT"/.env
fi

# Enable human-readable log format by default
if ! grep -q "export LOG_READABLE=" "$ROOT"/.env; then
  echo "# Enable human-readable log format" >> "$ROOT"/.env
  echo "export LOG_READABLE=1" >> "$ROOT"/.env
fi

# macOS specific settings
if [[ "$(uname)" == 'Darwin' ]]; then
  if ! grep -q "msgq doesn't work on mac" "$ROOT"/.env; then
    echo "# msgq doesn't work on mac" >> "$ROOT"/.env
  fi
  if ! grep -q "export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=" "$ROOT"/.env; then
    echo "export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES" >> "$ROOT"/.env
  fi
fi
