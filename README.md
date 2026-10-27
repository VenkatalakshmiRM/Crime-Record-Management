# Casework — Criminal Management System

CASEWORK has two implementations in this repository: the original Java Swing/MySQL application (`legacy/java/src/CriminalManagementSystem`) and the browser interface (`index.html`, `styles.css`, `app.js`). The browser interface uses a Python API for data persistence; see [Web app setup](docs/WEB_APP_SETUP.md). It does not automatically share records with the legacy Java app.

## Current browser application

The responsive CASEWORK interface includes an overview dashboard, case records, persons of interest, team directory, reports, and activity log. The browser client calls a same-origin API for data and login. MySQL is supported for deployment. A dependency-free SQLite adapter exists for isolated local API development/tests; SQLite is not MySQL connectivity proof.

### Quick start

See [docs/WEB_APP_SETUP.md](docs/WEB_APP_SETUP.md) for Python environment setup, initial administrator provisioning, SQLite quick start, and MySQL configuration. To run the configured app:

```powershell
python backend/api.py
```

This serves both frontend and API at `http://localhost:8010`. Check `http://localhost:8010/api/health` to see whether the configured adapter is connected.

## Database resources

- [ER diagram and data dictionary](docs/ER_DIAGRAM.md)
- [Public demo deployment](docs/RENDER_DEPLOYMENT.md)
- [Project reports](docs/reports/)
- [Original diagrams](docs/diagrams/)
- MySQL schema: `database/schema.mysql.sql`
- API implementation: `backend/api.py`
- Automated API tests: `tests/test_api.py`

## Legacy Java application

Java source is in `legacy/java/src/CriminalManagementSystem`; its JDBC driver and license are in `legacy/java/lib`. It uses Swing, JDBC, and MySQL Connector/J. Source references a database called `CriminalApplication` and tables such as `FIR`, `Criminal`, `Operator`, and `LogIn`; the original schema-creation SQL was not found in the repository. The legacy database and the new web schema (`casework`) are separate. Avoid copying live/personal data into a student demo environment.

## Repository layout

| Path | Contents |
|---|---|
| `index.html`, `styles.css`, `app.js` | Browser UI |
| `backend/` | Python API and database adapter |
| `database/` | MySQL schema, role grants, and numbered migrations |
| `docs/` | Setup, schema docs, and project reports/diagrams |
| `scripts/` | Verification, seed/demo, performance, backup, and restore utilities |
| `tests/` | API and SQL-script structure tests |
| `tools/` | Explicit legacy browser-export importer |
| `legacy/java/` | Preserved Swing application source and JDBC connector |

Generated Python caches and compiled Java classes are excluded from the project tree; rebuild them when needed.
