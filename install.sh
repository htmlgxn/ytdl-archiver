#!/usr/bin/env bash
set -euo pipefail

PACKAGE_NAME="ytdl-archiver"

ask_yes_no() {
  local prompt="$1"
  local default_yes="${2:-1}"
  local suffix="[Y/n]"
  local default_answer="y"

  if [[ "${default_yes}" != "1" ]]; then
    suffix="[y/N]"
    default_answer="n"
  fi

  # curl|bash leaves stdin unavailable for prompts, so read from /dev/tty when possible.
  if [[ ! -e /dev/tty ]]; then
    [[ "${default_yes}" == "1" ]]
    return
  fi

  while true; do
    local input
    local input_normalized
    read -r -p "${prompt} ${suffix} " input </dev/tty || input=""
    input="${input:-${default_answer}}"
    input_normalized="$(printf '%s' "${input}" | tr '[:upper:]' '[:lower:]')"
    case "${input_normalized}" in
      y|yes) return 0 ;;
      n|no) return 1 ;;
      *) echo "Please answer y or n." ;;
    esac
  done
}

run_with_sudo() {
  if [[ "${EUID:-$(id -u)}" -eq 0 ]]; then
    "$@"
    return
  fi
  if command -v sudo >/dev/null 2>&1; then
    sudo "$@"
    return
  fi
  echo "Need elevated privileges for: $*"
  return 1
}

is_firefox_installed() {
  if command -v firefox >/dev/null 2>&1; then
    return 0
  fi

  # macOS app-bundle installs typically don't provide a PATH binary.
  if [[ "$(uname -s)" == "Darwin" ]]; then
    if [[ -d "/Applications/Firefox.app" || -d "$HOME/Applications/Firefox.app" ]]; then
      return 0
    fi
  fi

  return 1
}

install_firefox() {
  if is_firefox_installed; then
    echo "Good! Firefox is already installed!"
    return 0
  fi

  case "$(uname -s)" in
    Darwin)
      if command -v brew >/dev/null 2>&1; then
        # brew can fail (network/permissions/toolchain). Do not fail the full installer.
        if ! brew list --cask firefox >/dev/null 2>&1; then
          if ! brew install --cask firefox; then
            echo "Warning: Firefox install failed. Install manually from https://www.mozilla.org/firefox/."
            return 0
          fi
        fi
      else
        echo "Homebrew not found. Install Firefox manually from https://www.mozilla.org/firefox/."
      fi
      ;;
    Linux)
      if command -v apt-get >/dev/null 2>&1; then
        run_with_sudo apt-get update
        run_with_sudo apt-get install -y firefox || run_with_sudo apt-get install -y firefox-esr
      elif command -v dnf >/dev/null 2>&1; then
        run_with_sudo dnf install -y firefox
      elif command -v pacman >/dev/null 2>&1; then
        run_with_sudo pacman -Sy --noconfirm firefox
      elif command -v zypper >/dev/null 2>&1; then
        run_with_sudo zypper --non-interactive install MozillaFirefox
      else
        echo "No supported package manager detected. Install Firefox manually from https://www.mozilla.org/firefox/."
      fi
      ;;
    *)
      echo "Unsupported OS for automatic Firefox install. Install manually from https://www.mozilla.org/firefox/."
      ;;
  esac
}

is_ffmpeg_installed() {
  if command -v ffmpeg >/dev/null 2>&1; then
    return 0
  fi

  if [[ "$(uname -s)" == "Darwin" ]] && command -v brew >/dev/null 2>&1; then
    if brew list ffmpeg >/dev/null 2>&1; then
      return 0
    fi
  fi

  return 1
}

install_ffmpeg() {
  if is_ffmpeg_installed; then
    echo "Good! FFmpeg is already installed!"
    return 0
  fi

  case "$(uname -s)" in
    Darwin)
      if command -v brew >/dev/null 2>&1; then
        if ! brew install ffmpeg; then
          echo "Warning: FFmpeg install failed. Install manually from https://ffmpeg.org/download.html."
          return 0
        fi
      else
        echo "Homebrew not found. Install FFmpeg manually from https://ffmpeg.org/download.html."
      fi
      ;;
    Linux)
      if command -v apt-get >/dev/null 2>&1; then
        run_with_sudo apt-get update
        if ! run_with_sudo apt-get install -y ffmpeg; then
          echo "Warning: FFmpeg install failed. Install manually from https://ffmpeg.org/download.html."
          return 0
        fi
      elif command -v dnf >/dev/null 2>&1; then
        if ! run_with_sudo dnf install -y ffmpeg; then
          echo "Warning: FFmpeg install failed. Install manually from https://ffmpeg.org/download.html."
          return 0
        fi
      elif command -v pacman >/dev/null 2>&1; then
        if ! run_with_sudo pacman -Sy --noconfirm ffmpeg; then
          echo "Warning: FFmpeg install failed. Install manually from https://ffmpeg.org/download.html."
          return 0
        fi
      elif command -v zypper >/dev/null 2>&1; then
        if ! run_with_sudo zypper --non-interactive install ffmpeg; then
          echo "Warning: FFmpeg install failed. Install manually from https://ffmpeg.org/download.html."
          return 0
        fi
      else
        echo "No supported package manager detected. Install FFmpeg manually from https://ffmpeg.org/download.html."
      fi
      ;;
    *)
      echo "Unsupported OS for automatic FFmpeg install. Install manually from https://ffmpeg.org/download.html."
      ;;
  esac
}

if ! command -v uv >/dev/null 2>&1; then
  echo "uv not found. Installing uv..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi

if ask_yes_no "Install Deno? (recommended for best yt-dlp compatibility)" 1; then
  if ! command -v deno >/dev/null 2>&1; then
    echo "deno not found. Installing deno..."
    curl -fsSL https://deno.land/install.sh | sh
    export PATH="$HOME/.deno/bin:$PATH"
  else
    echo "Good! Deno is already installed!"
  fi
else
  echo "Skipping Deno install."
fi

if ask_yes_no "Install Firefox? (recommended for cookie import)" 1; then
  install_firefox
else
  echo "Skipping Firefox install."
fi

if ask_yes_no "Install FFmpeg? (recommended)" 1; then
  install_ffmpeg
else
  echo "Skipping FFmpeg install."
fi

echo "Installing ${PACKAGE_NAME}..."
uv tool install --upgrade "${PACKAGE_NAME}"
export PATH="$HOME/.local/bin:$PATH"

echo
echo "Install complete!"
echo "Launching ${PACKAGE_NAME} setup..."

set +e
if command -v "${PACKAGE_NAME}" >/dev/null 2>&1; then
  if [[ "$(uname -s)" == "Darwin" ]] && command -v script >/dev/null 2>&1; then
    # macOS: run through a PTY to ensure ratatui sees an interactive terminal.
    script -q /dev/null "${PACKAGE_NAME}" init
  elif [[ -r /dev/tty ]]; then
    "${PACKAGE_NAME}" init </dev/tty >/dev/tty 2>/dev/tty
  else
    "${PACKAGE_NAME}" init
  fi
else
  if [[ "$(uname -s)" == "Darwin" ]] && command -v script >/dev/null 2>&1; then
    script -q /dev/null uv tool run "${PACKAGE_NAME}" init
  elif [[ -r /dev/tty ]]; then
    uv tool run "${PACKAGE_NAME}" init </dev/tty >/dev/tty 2>/dev/tty
  else
    uv tool run "${PACKAGE_NAME}" init
  fi
fi
launch_exit=$?
set -e

if [[ "${launch_exit}" -ne 0 ]]; then
  echo
  echo "${PACKAGE_NAME} setup exited with status ${launch_exit}. You can retry with:"
  echo "  ${PACKAGE_NAME} init"
fi
