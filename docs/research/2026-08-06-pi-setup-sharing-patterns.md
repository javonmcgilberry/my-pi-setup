# Research: Sharing a Personal Pi Workflow on GitHub

## Summary

`my-pi-setup` is not unjustified, but it is more infrastructure than most
personal Pi setups need. Pi already provides global and project settings,
resource discovery, Git and npm packages, pinned Git refs, project trust, and
automatic package installation.

The simplest suitable architecture is a Pi package plus a small, public-safe
global settings file. Custom synchronization is worth retaining only where it
provides something Pi does not: deterministic machine restoration, drift
detection, cross-harness skill linking, or local development of substantial
extensions.

## What Pi supports natively

1. **Configuration has two scopes.** Global configuration belongs in
   `~/.pi/agent/settings.json`; project configuration belongs in
   `.pi/settings.json`, with project settings overriding global settings.
   [Settings](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/settings.md)
   · [Quickstart](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/quickstart.md)

2. **Pi packages are Pi's documented sharing primitive.** A package can contain
   extensions, skills, prompts, and themes through a `package.json` `pi`
   manifest or conventional directories. Packages can be installed from npm,
   Git, URLs, or local paths. Project-scoped packages can be committed in
   `.pi/settings.json`, and Pi installs missing packages after project trust is
   granted.
   [Pi Packages](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/packages.md)

3. **Some determinism is already built in.** Versioned npm specs are pinned,
   and Git package refs can be pinned to tags or commits. Pi stores global
   packages under `~/.pi/agent/npm` and `~/.pi/agent/git`, project packages
   under `.pi/npm` and `.pi/git`, and reconciles pinned Git checkouts during
   updates.
   [Pi Packages](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/packages.md)

4. **Local extension development is supported.** Extensions can live in
   `~/.pi/agent/extensions` or `.pi/extensions`, can be tested with `pi -e`,
   and can be hot-reloaded with `/reload`. Local packages can use normal npm
   dependencies.
   [Extensions](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/extensions.md)

5. **Cross-harness skills are supported.** Pi discovers `~/.agents/skills` and
   can explicitly load other skill directories. A single shared skill location
   is reasonable; duplicating the same skill under both `~/.pi/agent/skills`
   and `~/.agents/skills` is not.
   [Skills](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/skills.md)

6. **Runtime state should stay outside Git.** Pi's docs place authentication
   and sessions in the agent directory. This repository's own portability and
   privacy requirements additionally exclude caches, installed package
   checkouts, browser profiles, and machine-local credentials.
   [Quickstart](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/quickstart.md)
   · [Sessions](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/sessions.md)

## Patterns used by other Pi users

Public repositories show several recurring approaches rather than one standard:

- **A small tracked agent home:**
  [jvz-devx/my-pi-setup](https://github.com/jvz-devx/my-pi-setup) tracks public
  settings and a small extension while excluding runtime data.
- **A package plus bootstrap:**
  [LEUNGUU/pi-agent-config](https://github.com/LEUNGUU/pi-agent-config) exposes
  Pi resources as a package and uses a separate setup script for personal files.
- **A template installer:**
  [ywh555hhh/pi-dotfiles](https://github.com/ywh555hhh/pi-dotfiles) combines
  settings templates, environment placeholders, an installer, and a package
  manifest.
- **A symlinked personal suite:**
  [espennilsen/pi](https://github.com/espennilsen/pi) symlinks a large personal
  repository into the agent directory.
- **A tested bootstrap:**
  [ppowo/pi-config](https://github.com/ppowo/pi-config) adds reconciliation and
  tests, an intermediate pattern rather than a requirement.
- **A directly installable extension collection:**
  [tomsej/pi-ext](https://github.com/tomsej/pi-ext),
  [w-winter/dot314](https://github.com/w-winter/dot314), and
  [chrisetheridge/my-little-pi](https://github.com/chrisetheridge/my-little-pi)
  use Pi's Git-package installation and resource filtering.

These are representative examples, not a statistical survey.

## Assessment of this repository

The current complexity is partly requirements-driven. `AGENTS.md` makes this
repository the source of truth, separates Pi core and Prewalk ownership,
requires `config/manifest.json` to define the installed inventory, and assigns
distinct roles to `sync`, `scripts/check.sh`, and `scripts/drift.sh`. Those are
real benefits when reproducible restoration and safe drift detection matter.

However, parts of `setup.sh`, `sync`, `settings.json`, `package.json`, and the
manifest overlap with Pi's own package installation, update, discovery, scope,
and trust features.

The simplification opportunities are therefore:

- **High:** setup and sync behavior that merely copies or installs Pi package
  resources.
- **Medium:** manifest inventory, drift checks, safe restore behavior, and
  pre-apply validation. These are useful but optional personal guarantees.
- **Low:** one cross-harness skill link. The requirement is legitimate and the
  implementation should remain singular.
- **Separately justified:** tests and local development for extensions with
  meaningful behavior. These should live with the package that owns them.

## Repository boundaries

Pi core and the personal setup should remain separate repositories. The Pi
repository is the application and upstream development checkout; this
repository is personal configuration, resources, and integration policy. Pi's
package system allows those custom resources to be distributed without merging
them into the core source tree.

Pi Lens is also an independent package boundary, not part of Pi core.
[Pi repository](https://github.com/earendil-works/pi) ·
[Pi Lens](https://github.com/apmantza/pi-lens)

The confusing part is operational: starting every Pi-related task in this
repository can make a session appear to own work in other repositories. That
does not mean the repositories should be merged. It means this repository
should avoid acting as a universal coding workspace. Pi should normally be
started in the repository being changed; this setup repository should be used
when the setup itself is being changed.

## Recommended architecture

### Simplest viable option

- Keep Pi core in `~/Developer/pi`.
- Turn `my-pi-setup` into an installable Pi package containing `extensions/`,
  `skills/`, `prompts/`, and `themes/`.
- Keep a minimal public-safe `settings.json` with preferences and pinned package
  sources. Treat it as a bootstrap input or documented template; installing the
  package does not merge that file into Pi's global settings.
- Ignore authentication, sessions, caches, package directories, browser
  profiles, and machine-local overrides.
- Install the package with a normal Pi command:

  ```sh
  pi install git:github.com/javonmcgilberry/my-pi-setup@<tag>
  ```

- Keep only a small bootstrap script for the global settings template and other
  resources Pi packages do not manage, such as global instructions or
  cross-harness links.

### Balanced option

Retain a thin configuration repository with:

- a Pi package manifest;
- pinned package refs;
- a small bootstrap/reconcile script;
- secret and runtime exclusion checks;
- `check.sh` and, if useful, `drift.sh`;
- explicit cross-harness skill-link setup.

Remove custom behavior that duplicates `pi install`, `pi update`, resource
discovery, or package checkout management.

### When the current architecture is worth keeping

Keep it if these guarantees are important enough to maintain:

- deterministic managed inventory across machines;
- safe reconciliation and stale-file cleanup;
- validation before applying changes;
- read-only comparison against the live setup;
- local development and tests for substantial extensions;
- deliberate cross-harness installation;
- a publication boundary stronger than cloning or installing a package.

## Conclusion

The setup is somewhat over-engineered relative to Pi's native sharing model,
but not irrational. The best direction is to narrow its responsibility:

> Let Pi own package installation, resource discovery, updates, and scope. Let
> this repository own the personal resources themselves plus only the safety
> and restoration behavior Pi does not provide.

The balanced option is the strongest fit: it preserves the valuable safety
work while removing infrastructure that duplicates Pi.
