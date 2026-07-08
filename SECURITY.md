# Security Policy

## Supported versions

Only the latest release on PyPI receives security fixes.

## Reporting a vulnerability

Please use GitHub private vulnerability reporting:
https://github.com/minhhq-a1/odoo-pulse/security/advisories/new
(or email minhhq@arrowhitech.com). Expect an acknowledgement within 72 hours.

## Scope notes

odoo-pulse holds Odoo credentials in environment variables and talks to your
Odoo over XML-RPC. Reports about credential handling, the write-safety chain
(`ODOO_READ_ONLY` / `ODOO_WRITABLE_MODELS` / `ODOO_ALLOW_DELETE` / `confirm`),
or SSL verification (`ODOO_VERIFY_SSL`) are especially welcome.
