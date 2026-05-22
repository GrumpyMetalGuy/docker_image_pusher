# dip — Docker Image Pusher

A small CLI that builds the Docker image in the current directory and pushes it to
your registry under rolling semver tags (`X.Y.Z`, `X.Y`, `X`, `latest`).

## Install

```bash
./install.sh
```

This requires [`uv`](https://docs.astral.sh/uv/). It symlinks `pusher.py` to
`~/.local/bin/dip` and creates `~/.config/docker_image_pusher/config.yaml`. Edit that
file to set your registry:

```yaml
registry: registry.example.com/myorg
```

Make sure `~/.local/bin` is on your `PATH` and that you are `docker login`-ed.

## Usage

From any project folder containing a `Dockerfile`:

```bash
dip
```

- If `VERSION.txt` exists (image name then `MAJOR.MINOR.PATCH`, each on its own line;
  `#` comment lines are ignored), you are prompted for a bump level
  (major / minor / revision).
- If `VERSION.txt` is missing, you are prompted for an image name and starting version
  (default `0.1.0`); that version is built and pushed as-is and the file is created.

`dip` writes (and rewrites) `VERSION.txt` with a short comment header identifying the
tool, e.g.:

```
# Created and managed by DIP (Docker Image Pusher).
# https://github.com/GrumpyMetalGuy/docker_image_pusher
my-image
1.7.3
```

`dip` then shows the tags it will push, asks for confirmation, builds, pushes
`X.Y.Z` / `X.Y` / `X` / `latest`, and (on success) writes the new version back to
`VERSION.txt`.

## Development

```bash
uv run --with pyyaml --with pytest pytest        # pusher unit/integration tests
uv run --with pytest pytest test_install.py      # installer tests
```
