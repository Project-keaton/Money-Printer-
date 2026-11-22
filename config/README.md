# config/

Additional configuration files and settings loaders.

- `config.yaml` at the project root is the main configuration.
- Environment-specific overrides (e.g. `config.dev.yaml`, `config.prod.yaml`) may live here.
- Secrets (API keys, broker credentials) belong in the git-ignored `.env` file,
  never in committed YAML. See `.env.example` at the project root.
