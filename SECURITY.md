# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| 3.x     | Yes       |
| < 3.0   | No        |

## Reporting a Vulnerability

If you discover a security vulnerability in CrawlKit, please report it responsibly. **Do not open a public issue.**

### How to Report

1. Email your report to the project maintainers (see the repository contact information)
2. Include the following details:
   - A description of the vulnerability
   - Steps to reproduce the issue
   - The potential impact
   - Any suggested fix (optional)

### What to Expect

- **Acknowledgment** within 48 hours of your report
- **Status update** within 7 days with an initial assessment
- **Resolution timeline** communicated once the issue is confirmed

### Scope

The following are in scope for security reports:

- Authentication bypass in the Web Admin panel
- Session token vulnerabilities (prediction, replay, fixation)
- Injection vulnerabilities in URL handling or HTML parsing
- Path traversal in file operations (seed files, export paths, session files)
- Denial of service through crafted input
- Information disclosure through error messages or logs

### Out of Scope

- Vulnerabilities in third-party dependencies (report these to the upstream project)
- Issues requiring physical access to the host machine
- Social engineering attacks

## Security Considerations

### Web Admin Panel

- The admin panel binds to `127.0.0.1` by default. Binding to `0.0.0.0` exposes it to the network -- use only behind a reverse proxy with TLS.
- Passwords are hashed with SHA256 and a random salt. Session tokens are HMAC-signed and expire after 24 hours.
- If no password is provided at startup, a cryptographically random one is generated.

### Crawling

- CrawlKit follows links and fetches content from arbitrary URLs. Run it in an isolated environment or container when crawling untrusted sites.
- SSL verification is disabled for `.onion` URLs since Tor provides its own encryption. This is intentional and scoped only to deepweb mode.

### Output Files

- Crawl results may contain content from untrusted sources. Treat exported data (JSON, CSV, SQLite) as untrusted input when processing downstream.
