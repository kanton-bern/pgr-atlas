# Security policy

## Reporting a vulnerability

Please don't report a vulnerability in a public issue, pull request or discussion.

Report it privately through GitHub instead: open the repository's **Security** tab and choose
**Report a vulnerability**. Only the maintainers see the report. Please include:

- what is affected (a view, an endpoint, a file type, the container image),
- the steps to reproduce it, and
- what an attacker could do with it.

If you can't use GitHub, write to the Amt für Wald und Naturgefahren (AWN) of Kanton Bern at
naturgefahren@be.ch and ask for a private channel. Please don't put the details into that first
email.

We acknowledge a report within 5 working days and agree on a fix and disclosure date with you.

**Safe harbour.** Good-faith security research that follows this policy, doesn't access other
people's data and doesn't disrupt the service won't be pursued.

## Supported versions

Only the latest release, the one running in production, receives fixes.

## Scope

This repository: the Streamlit app, its map components, the tile and raster sidecar servers,
the container image and the deployment configuration. The data served by the app and the
basemaps from swisstopo and OpenStreetMap are outside its scope.
