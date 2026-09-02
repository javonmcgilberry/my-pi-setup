# Context

`my-pi-setup` is a private, portable Pi configuration repository. It renders a
small managed subset of global settings, copies non-secret config files, links
shared skills and commands, and verifies drift.

Substantial code lives elsewhere:

- `javon-pi-extensions` owns personal extensions and the session dashboard.
- `webflow-designer-agent-browser` owns the Webflow skill and validation suite.
- `pi-prewalk` owns Prewalk.

Routine `pi-update-all` runs no tests. Configuration changes use the small local
check suite; each product runs its own tests only in its own repository.
