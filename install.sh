#!/usr/bin/env bash
set -euo pipefail

# --- Preflight: dependency checks -------------------------------------------
if ! command -v uv >/dev/null 2>&1; then
    echo "error: 'uv' is required but not found on PATH." >&2
    echo "       Install it: curl -LsSf https://astral.sh/uv/install.sh | sh" >&2
    echo "       Docs: https://docs.astral.sh/uv/" >&2
    exit 1
fi

if ! command -v docker >/dev/null 2>&1; then
    echo "warning: 'docker' not found on PATH. dip needs the docker CLI at run time;" >&2
    echo "         install Docker before using dip (continuing with install)." >&2
fi

# --- Resolve paths (bash builtins only) -------------------------------------
src="${BASH_SOURCE[0]}"
case "${src}" in
    */*) script_dir="$(cd "${src%/*}" && pwd)" ;;
    *) script_dir="$(pwd)" ;;
esac
pusher="${script_dir}/pusher.py"
if [ ! -f "${pusher}" ]; then
    echo "error: pusher.py not found next to install.sh (${pusher})." >&2
    exit 1
fi

bin_dir="${HOME}/.local/bin"
link="${bin_dir}/dip"
config_dir="${XDG_CONFIG_HOME:-${HOME}/.config}/docker_image_pusher"
config="${config_dir}/config.yaml"

# --- Make the script executable + symlink it as `dip` -----------------------
chmod +x "${pusher}"
mkdir -p "${bin_dir}"
if [ -e "${link}" ] && [ ! -L "${link}" ]; then
    echo "error: ${link} exists and is not a symlink; refusing to overwrite." >&2
    exit 1
fi
ln -sfn "${pusher}" "${link}"
echo "linked ${link} -> ${pusher}"

# --- Scaffold config (never overwrite an existing one) ----------------------
mkdir -p "${config_dir}"
if [ -f "${config}" ]; then
    echo "config already exists, leaving it untouched: ${config}"
else
    {
        echo "# Docker registry to push images to."
        echo "# Include a namespace/org if needed, e.g. registry.example.com/myorg"
        echo "registry: registry.example.com"
    } > "${config}"
    echo "wrote starter config: ${config}"
fi

# --- PATH hint --------------------------------------------------------------
case ":${PATH}:" in
    *":${bin_dir}:"*) ;;
    *) echo "note: ${bin_dir} is not on your PATH. Add it, e.g.:"
       echo "      echo 'export PATH=\"\$HOME/.local/bin:\$PATH\"' >> ~/.zshrc" ;;
esac

echo
echo "Done. Edit ${config} to set your registry, make sure you're 'docker login'-ed,"
echo "then run 'dip' from any project folder containing a Dockerfile."
