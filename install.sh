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
    read -r -p "${prompt} ${suffix} " input </dev/tty || input=""
    input="${input:-${default_answer}}"
    case "${input,,}" in
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

install_firefox() {
  if command -v firefox >/dev/null 2>&1; then
    echo "Firefox already installed."
    return 0
  fi

  case "$(uname -s)" in
    Darwin)
      if command -v brew >/dev/null 2>&1; then
        brew install --cask firefox
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

if ! command -v uv >/dev/null 2>&1; then
  echo "uv not found. Installing uv..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi

if ! command -v deno >/dev/null 2>&1; then
  if ask_yes_no "Install Deno? (recommended for best yt-dlp compatibility)" 1; then
    echo "deno not found. Installing deno..."
    curl -fsSL https://deno.land/install.sh | sh
    export PATH="$HOME/.deno/bin:$PATH"
  else
    echo "Skipping Deno install."
  fi
fi

if ask_yes_no "Install Firefox? (recommended for cookie import)" 1; then
  install_firefox
else
  echo "Skipping Firefox install."
fi

echo "Installing ${PACKAGE_NAME}..."
uv tool install --upgrade "${PACKAGE_NAME}"
export PATH="$HOME/.local/bin:$PATH"

echo
echo "Install complete!"
echo "Launching ${PACKAGE_NAME}..."

set +e
if command -v "${PACKAGE_NAME}" >/dev/null 2>&1; then
  "${PACKAGE_NAME}"
else
  uv tool run "${PACKAGE_NAME}"
fi
launch_exit=$?
set -e

if [[ "${launch_exit}" -ne 0 ]]; then
  echo
  echo "${PACKAGE_NAME} exited with status ${launch_exit}. You can retry with:"
  echo "  ${PACKAGE_NAME}"
fi
