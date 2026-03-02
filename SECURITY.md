# Security Policy

## Supported Versions

| Environment | Version        | Supported |
| ----------- | -------------- | --------- |
| Production  | latest `main`  | Yes       |
| Staging     | latest `main`  | Yes       |
| Local dev   | any branch     | No        |

## Reporting a Vulnerability

This is an internal tool for the Royal Academy Summer Exhibition catalogue
team. If you discover a security issue, please contact the repository owner
directly rather than opening a public issue.

## Authentication

- **Staging / Production:** AWS Cognito (JWT-based)
- **Local development:** Auth disabled by default (`API_KEY=` empty)

## Accepted Risks

| Alert | Decision | Rationale |
| ----- | -------- | --------- |
| Clear-text token storage in `localStorage` | Won't fix | Required for multi-tab session sharing. Tokens are Cognito JWTs with short expiry. XSS risk is mitigated by limited user base and Cognito auth. |

## Dependencies

We pin direct dependencies in `requirements.txt` and review Dependabot
alerts promptly. Transitive dependency alerts are evaluated for actual
impact before acting.
