#!/usr/bin/env bash

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null && pwd )"

source "$DIR/launch_env.sh"

# Load environment variables from .env file if it exists
if [ -f "$DIR/.env" ]; then
  source "$DIR/.env"
else
  # Set default environment variables if .env file doesn't exist
  echo "No .env file found, setting default environment variables..."
  # Users can manually add GPU support in .env file
  # export DEV=AMD  # Use AMD GPU for model inference
  # export DEV=NVIDIA  # Use NVIDIA GPU for model inference
  export ZMQ=1         # Enable ZMQ for IPC
  export USE_WEBCAM=1  # Enable webcam support
  export ROAD_CAM=0    # Default road camera setting
  # Disable other cameras
  export DRIVER_CAM=""  # Disable driver camera
  export WIDE_CAM=""    # Disable wide camera
  export PYTHONPATH="$PWD"  # Set Python path
  export LOG_READABLE="1"   # Enable human-readable log format
fi

# PC environment detection and configuration
if [ ! -f /TICI ]; then
  echo "Detected PC environment, applying PC-specific configuration..."

  # Create necessary directories if they don't exist
  # Set default PARAMS_ROOT if not already set
  if [ -z "$PARAMS_ROOT" ]; then
    PARAMS_ROOT="$PWD/data/params"
  fi
  mkdir -p $PARAMS_ROOT/d /tmp/openpilot

  # Set default language if not already set
  if [ ! -f $PARAMS_ROOT/d/LanguageSetting ]; then
    echo -n "main_en" > $PARAMS_ROOT/d/LanguageSetting
  fi

  # Set HardwareC3xLite to 1 by default (forced)
  echo "1" > $PARAMS_ROOT/d/HardwareC3xLite

  # Set DisableDM to 1 by default (forced)
  echo "1" > $PARAMS_ROOT/d/DisableDM

  # Set default SWAGLOG_ROOT if not already set
  if [ -z "$SWAGLOG_ROOT" ]; then
    SWAGLOG_ROOT="$PWD/data/log"
  fi
  mkdir -p $SWAGLOG_ROOT
fi

function agnos_init {
  # TODO: move this to agnos
  sudo rm -f /data/etc/NetworkManager/system-connections/*.nmmeta

  # set success flag for current boot slot
  sudo abctl --set_success

  # TODO: do this without udev in AGNOS
  # udev does this, but sometimes we startup faster
  sudo chgrp gpu /dev/adsprpc-smd /dev/ion /dev/kgsl-3d0
  sudo chmod 660 /dev/adsprpc-smd /dev/ion /dev/kgsl-3d0

  # Check if AGNOS update is required
  if [ $(< /VERSION) != "$AGNOS_VERSION" ]; then
    AGNOS_PY="$DIR/system/hardware/tici/agnos.py"
    MANIFEST="$DIR/system/hardware/tici/agnos.json"
    if $AGNOS_PY --verify $MANIFEST; then
      sudo reboot
    fi
    $DIR/system/hardware/tici/updater $AGNOS_PY $MANIFEST
  fi
}

function launch {
  # Remove orphaned git lock if it exists on boot
  [ -f "$DIR/.git/index.lock" ] && rm -f $DIR/.git/index.lock

  # Check to see if there's a valid overlay-based update available. Conditions
  # are as follows:
  #
  # 1. The DIR init file has to exist, with a newer modtime than anything in
  #    the DIR Git repo. This checks for local development work or the user
  #    switching branches/forks, which should not be overwritten.
  # 2. The FINALIZED consistent file has to exist, indicating there's an update
  #    that completed successfully and synced to disk.

  if [ -f "${DIR}/.overlay_init" ]; then
    find ${DIR}/.git -newer ${DIR}/.overlay_init | grep -q '.' 2> /dev/null
    if [ $? -eq 0 ]; then
      echo "${DIR} has been modified, skipping overlay update installation"
    else
      if [ -f "${STAGING_ROOT}/finalized/.overlay_consistent" ]; then
        if [ ! -d /data/safe_staging/old_openpilot ]; then
          echo "Valid overlay update found, installing"
          LAUNCHER_LOCATION="${BASH_SOURCE[0]}"

          mv $DIR /data/safe_staging/old_openpilot
          mv "${STAGING_ROOT}/finalized" $DIR
          cd $DIR

          echo "Restarting launch script ${LAUNCHER_LOCATION}"
          unset AGNOS_VERSION
          exec "${LAUNCHER_LOCATION}"
        else
          echo "openpilot backup found, not updating"
          # TODO: restore backup? This means the updater didn't start after swapping
        fi
      fi
    fi
  fi

  # handle pythonpath
  if [ -w /data ]; then
    ln -sfn $(pwd) /data/pythonpath
  fi
  # Only set PYTHONPATH if not already set from .env
  if [ -z "$PYTHONPATH" ]; then
    export PYTHONPATH="$PWD"
  fi

  # hardware specific init
  if [ -f /AGNOS ]; then
    agnos_init
  fi

  # write tmux scrollback to a file if tmux is available
  if command -v tmux &> /dev/null && [ -n "$TMUX" ]; then
    tmux capture-pane -pq -S-1500 > /tmp/launch_log
  else
    echo "Tmux not available, skipping scrollback capture"
  fi
  # Install/Update dependencies using uv sync
  if ! command -v "uv" > /dev/null 2>&1; then
    echo "installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    UV_BIN="$HOME/.local/bin"
    PATH="$UV_BIN:$PATH"
  fi

  echo "updating dependencies with uv sync..."
  uv sync --frozen --all-extras

  # Activate virtual environment if it exists
  if [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
  fi

  # events language init
  # Set default PARAMS_ROOT if not already set
  if [ -z "$PARAMS_ROOT" ]; then
    PARAMS_ROOT="$PWD/data/params"
  fi
  LANG=$(cat $PARAMS_ROOT/d/LanguageSetting)
  EVENTSTAT=$(git status)

  # events.py 한글로 변경 및 파일이 교체된 상태인지 확인
  if [ "${LANG}" = "main_ko" ] && [[ ! "${EVENTSTAT}" == *"modified:   selfdrive/selfdrived/events.py"* ]]; then
    # Backup English version only if it doesn't exist yet
    if [ ! -f "$DIR/scripts/add/events_en.py" ]; then
      cp -f $DIR/selfdrive/selfdrived/events.py $DIR/scripts/add/events_en.py
    fi
    cp -f $DIR/scripts/add/events_ko.py $DIR/selfdrive/selfdrived/events.py
  elif [ "${LANG}" = "main_zh-CHS" ] && [[ ! "${EVENTSTAT}" == *"modified:   selfdrive/selfdrived/events.py"* ]]; then
    # Backup English version only if it doesn't exist yet
    if [ ! -f "$DIR/scripts/add/events_en.py" ]; then
      cp -f $DIR/selfdrive/selfdrived/events.py $DIR/scripts/add/events_en.py
    fi
    cp -f $DIR/scripts/add/events_zh.py $DIR/selfdrive/selfdrived/events.py
  elif [ "${LANG}" = "main_en" ] && [[ "${EVENTSTAT}" == *"modified:   selfdrive/selfdrived/events.py"* ]]; then
    # Only restore English if backup exists
    if [ -f "$DIR/scripts/add/events_en.py" ]; then
      cp -f $DIR/scripts/add/events_en.py $DIR/selfdrive/selfdrived/events.py
    fi
  fi

  # c3xl amplifier file change - only execute on TICI hardware
  if [ -f /TICI ]; then
    C3XL=$(cat $PARAMS_ROOT/d/HardwareC3xLite)

    if [ "${C3XL}" = "1" ] && [[ ! "${EVENTSTAT}" == *"modified:   system/hardware/tici/amplifier.py"* ]]; then
      cp -f $DIR/system/hardware/tici/amplifier.py $DIR/scripts/add/amplifier_org.py
      cp -f $DIR/scripts/add/amplifier_c3xl.py $DIR/system/hardware/tici/amplifier.py
    elif [ "${C3XL}" = "0" ] && [[ "${EVENTSTAT}" == *"modified:   system/hardware/tici/amplifier.py"* ]]; then
      cp -f $DIR/scripts/add/amplifier_org.py $DIR/system/hardware/tici/amplifier.py
    fi
  fi

  # start manager
  cd system/manager
  if [ ! -f $DIR/prebuilt ]; then
    ./build.py
  fi
  ./manager.py

  # if broken, keep on screen error
  while true; do sleep 1; done
}

launch
