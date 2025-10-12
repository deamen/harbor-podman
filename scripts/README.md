Patch docker-compose.yml logging settings for Podman

Usage

- Install dependencies: pip install -r requirements.txt
- Run the script from repository root (default file names):

  python3 scripts/patch_compose.py --backup

- To specify paths:

  python3 scripts/patch_compose.py -c path/to/docker-compose.yml -y path/to/harbor.yml --backup

What it does

- Removes the `log` service from `docker-compose.yml`.
- Removes `log` from any `depends_on` entries.
- Sets every service logging.driver to `json-file`.
- Removes logging.options `syslog-address` and `tag`.
- Adds logging.options `path`, `max-size`, and `max-file` using values from `harbor.yml` -> `log.local`.
