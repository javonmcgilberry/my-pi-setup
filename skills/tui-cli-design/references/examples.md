# Examples

These examples are framework-neutral TypeScript-shaped pseudocode. Adapt the
names to the host's public API; keep the behavior.

## 1. One lifecycle owner

**Fragile:** a custom component opens a second framework dialog and waits for
it. If the host restores its editor when the nested dialog closes, the outer
component can remain hidden with an unresolved promise.

```ts
async activateModel() {
  // Unsafe unless the framework documents nested custom-dialog suspension.
  this.draft.model = await ui.select("Model", choices);
}
```

**Stable:** the root component changes its own screen and resolves once.

```ts
type Screen = "overview" | "model" | "review" | "discard";

class ConfigureComponent {
  screen: Screen = "overview";
  private closed = false;

  openModel() {
    this.screen = "model";
    this.requestRender();
  }

  finish(result: "saved" | "cancelled") {
    if (this.closed) return;
    this.closed = true;
    this.resolve(result);
  }
}
```

## 2. Searchable picker

Start with the current item selected, filter while the user types, keep a
bounded viewport, and make both list confirmation and input submission work.

```text
Select executor
Search: openai/gpt-5▌

→ openai     gpt-5                current
  openrouter openai/gpt-5

↑↓ move · PgUp/PgDn jump · Enter select · Esc back
```

Index canonical terms before aliases. Pi's model picker uses this ordering so
`openai/gpt-5` ranks the OpenAI model ahead of an OpenRouter ID containing the
same text:

```ts
function searchText({ provider, id, name }: Item): string {
  const label = name ? ` ${name}` : "";
  return `${provider} ${provider}/${id} ${provider} ${id}${label}`;
}
```

Handle semantic bindings and the input callback:

```ts
input.onSubmit = () => selectCurrent();

function handleInput(data: string) {
  if (keys.matches(data, "list.confirm") || keys.matches(data, "input.submit")) {
    selectCurrent();
  } else if (keys.matches(data, "list.up")) {
    move(-1);
  } else if (keys.matches(data, "list.down")) {
    move(1);
  } else if (keys.matches(data, "input.cancel")) {
    goBack();
  } else {
    input.handleInput(data); // printable text, paste, and IME stay text
    refilter(input.value);
  }
}
```

When a catalog refreshes in the background, preserve the selected item's key,
re-run the active query, then clamp only if that key disappeared. Report a
timeout or partial refresh while keeping the cached snapshot usable.

## 3. Configuration draft

Show committed values and draft status at the level where the choice is made.

```text
Configure deploy behavior                         Unsaved changes

→ Runtime        Node 22                          saved: Node 20
  Region         us-east-1                        current
  Retry policy   Custom
  Review and save

↑↓ move · Enter open/change · ? help · Esc back
```

Recommended state split:

```ts
type ConfigureState = {
  saved: Config;
  draft: Config;
  screen: Screen;
  selectedKey?: string;
  message?: { tone: "info" | "success" | "error"; text: string };
};

const dirty = !deepEqual(state.saved, state.draft);
```

Save from a review screen, not on every toggle. A rejected validation keeps the
draft open and focuses the setting that needs correction.

## 4. Back, cancel, and discard

Use hierarchy rather than scattered exit shortcuts:

```ts
function escape() {
  if (screen === "search" || screen === "help" || screen === "child") {
    screen = parentOf(screen);
  } else if (screen === "discard") {
    screen = "overview"; // cancel the discard decision
  } else if (dirty) {
    screen = "discard";
  } else {
    finish("cancelled");
  }
}
```

```text
Discard unsaved changes?

→ Keep editing
  Discard changes

Enter choose · Esc keep editing
```

Typing `exit`, `q`, or `x` in a search or name field must add text. If a product
wants a printable quit shortcut, expose it only on a non-typing screen and show
it in the footer.

## 5. Dynamic lists keep focus stable

Removing rows can strand an index beyond the new list length. Prefer identity:

```ts
const selectedKey = rows[selectedIndex]?.key;
rows = deriveRows(nextState);
selectedIndex = Math.max(0, rows.findIndex((row) => row.key === selectedKey));
```

When the activated row remains meaningful after mutation, set its new index
explicitly. Example: turning off a custom child policy should leave focus on
`Turn off`, not jump to `Back` because custom-only rows disappeared.

## 6. Interactive and headless paths

The interactive command and scriptable commands should operate on the same
domain functions:

```text
tool configure                         # TTY dashboard
tool config child worker on            # automation-safe mutation
tool config child worker target p/m high
tool config show --json                 # deterministic inspection
```

If stdin is not a TTY, return an actionable error such as:

```text
Interactive configuration requires a terminal.
Use: tool config child <agent> on|off|target ...
```

Do not feed synthetic keystrokes to an interactive component in CI.
