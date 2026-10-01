# Security and data exposure

If you find anything in this repository that should not be public — a
credential, a token, personal data, an unpublished document, or a local file
path that reveals more than it should — please report it privately rather than
opening a public issue.

**Email:** info@roseworth.co, with "Repository security" in the subject line.

Please include the file path and commit, and a short description. We aim to
acknowledge reports within two working days and to remove confirmed exposures
promptly, including from the repository history where necessary.

This repository is designed to contain no credentials and no raw cached data:
the Companies House API key is read from a local `.env` file that is never
committed (see `.env.example`), and the raw API cache is excluded by
`.gitignore` and not distributed (see [docs/DATA-GOVERNANCE.md](docs/DATA-GOVERNANCE.md)).
