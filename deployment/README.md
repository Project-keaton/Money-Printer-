# deployment/

VPS deployment files and service configurations.

Typical contents:

- `forexbot.service` - systemd unit file
- `setup.sh` - server provisioning script
- `Dockerfile` / `docker-compose.yml` (optional)

Never commit secrets here; load them from environment variables on the server.
