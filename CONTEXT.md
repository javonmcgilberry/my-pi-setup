# Project context

## Managed install inventory

The managed install inventory is the authoritative declaration of artifacts
this setup owns, where each artifact is installed, and which obsolete targets
must be retired. Installers, drift checks, and validation all interpret the
same inventory.

## Managed target

A managed target is a filesystem location whose contents or link are owned by
this setup. A target may belong to the Pi installation or to the shared
cross-harness skill installation.

## Shared skill installation

A shared skill installation is one harness-discoverable skill location used by
Pi and other compatible harnesses. Duplicate copies of the same skill are not
independent installations; they are a collision risk.
