# database/

SQLite database files and the data-access layer.

- `forexbot.db` - default database (git-ignored); path set by `database.url` in `config.yaml`
- SQLAlchemy ORM models and session helpers live in this package.

Back up the database before schema changes.
