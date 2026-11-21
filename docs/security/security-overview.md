# Salesman security overview

For a customer's IT or security review. Plain answers about how Salesman protects a distributor's data.
Contact: Ahmed Irfan, Founder & CEO, Stonic — ahmed@stonic.site

## 1. What Salesman is made of

| Part | Runs on | Talks to |
| --- | --- | --- |
| API and background jobs (FastAPI, Python) | Render | PostgreSQL, WhatsApp Cloud API, Groq, the customer's ERP, ZATCA |
| Database (PostgreSQL) | Render managed PostgreSQL | API only; not reachable from the internet without credentials |
| Web dashboard (Next.js) | Vercel | API only |
| Mobile app (Expo / React Native) | Staff phones | API only |
| Print agent (Python) | A PC at the warehouse | API only, outgoing HTTPS; no inbound ports |

## 2. Data separation

Every business is a separate tenant. Every table that holds business data carries the tenant id, and every query
filters on it. Branch staff (salesmen, drivers, dispatchers, warehouse) see only their branch. Tests cover a user
of one business trying to read another's records.

## 3. Identity and access

- Passwords hashed with bcrypt. Access tokens expire after 60 minutes; refresh tokens after 14 days.
- A password reset or "sign out everywhere" ends every existing session (token versioning).
- Roles: owner, admin, salesman, dispatcher, driver, warehouse, read-only demo. Costs, margins and data
  protection tools are owner/admin only.
- Stonic staff use a separate console with separate accounts; every console action is written to an audit log.

## 4. Encryption and secrets

- HTTPS everywhere (TLS 1.2+), including the print agent and ERP connections.
- ERP keys, ZATCA private keys and API tokens are encrypted before they are stored (Fernet: AES-128-CBC with
  HMAC-SHA256), with a key kept outside the database.
- Print-agent keys are shown once and stored only as SHA-256 hashes; an agent's key can do nothing except fetch
  and report its own branch's slips, and can be revoked at once from the dashboard.
- The database is encrypted at rest by the hosting provider.

## 5. Integrations

- **WhatsApp:** every webhook is checked against Meta's X-Hub-Signature-256 before it is processed.
- **ERP (Odoo, SAP Business One, Dynamics 365 Business Central):** only public HTTPS addresses are accepted, so
  Salesman can't be made to call into a private network; redirects are not followed; a refused login stops
  scheduled syncs until it is checked again. Every record sent is logged with its result.
- **AI (Groq):** only what the conversation needs (message text, product names, the customer's order history)
  is sent. The AI cannot change prices or stock; it quotes stored values, and doubtful orders are held for staff.

## 6. Logging and audit

Order history (who did what, when), staff decisions on held orders, sign-ins, console actions, ERP sync events,
and every data export, customer erasure and retention run are recorded and kept.

## 7. Data protection (PDPL)

- **Export:** Settings > Data protection > Export downloads all of a business's data (no passwords or keys).
- **Erasure:** a customer's personal data can be erased on request; tax invoices are kept as VAT law requires.
- **Retention:** WhatsApp message text can be deleted automatically after a chosen number of days.
- **Breach notice:** customers are told within 24 hours so they can notify SDAIA within 72 hours.
- Data location and sub-processors: see the Data Processing Agreement, Annex 2.

## 8. Availability and backups

- Target availability 99.5% (Enterprise 99.9%). Jobs (WhatsApp sends, ERP syncs, reminders) run from a
  database-backed queue and are retried automatically, so a short outage delays work rather than losing it.
- Automatic backups with point-in-time recovery on the managed PostgreSQL plan, restorable to a new database.

## 9. Building it safely

- Every change runs an automated test suite (240+ tests, including tenant separation, ERP connectors against
  simulated servers, and data-protection functions) before release.
- Dependencies are pinned and updated regularly; secrets are never committed to the code repository.

## 10. Incidents

See `incident-response.md`.
