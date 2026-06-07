# Obsidian

A model-facing tool surface athena can use to read and write notes in an
[Obsidian](https://obsidian.md) vault. An Obsidian vault is just a directory of
Markdown files, so these tools operate on the filesystem directly — **no
Obsidian CLI, plugin, or running app is required**. They are Obsidian-aware:
YAML frontmatter (properties/tags), `[[wikilinks]]`, `#tags`, title-based note
resolution across subfolders, and daily notes.

## Configuration

The tools are **only advertised to the model when a vault is configured** (a
`check_fn` gate). Until you set `obsidian_vault_path` to an existing directory,
the five tools stay invisible.

```toml
# ~/.athena/config.toml
obsidian_vault_path = "C:/Users/you/Documents/MyVault"
obsidian_daily_folder = "Daily"          # optional; "" = vault root
obsidian_daily_date_format = "%Y-%m-%d"  # optional; strftime for daily notes
```

athena records its vaults in `%APPDATA%/obsidian/obsidian.json` — that file
lists the absolute path of every vault Obsidian knows about.

## Tools

| Tool | Purpose |
|------|---------|
| `obsidian_write`  | Create / overwrite / append a note, with `frontmatter` + `tags` |
| `obsidian_read`   | Read a note back (resolves a bare title anywhere in the vault) |
| `obsidian_append` | Append a block to a note, optionally under a `## heading` |
| `obsidian_search` | Full-text search the vault; empty query lists notes |
| `obsidian_daily`  | Append to (or create) today's daily note |

### Note references

`note` accepts a bare **title** (`"Ideas"` → `Ideas.md` at the vault root), a
**vault-relative path** (`"Projects/Athena"`), or one already ending in `.md`.
Reads and appends also resolve a bare title to a matching `<title>.md` found
**anywhere** in the vault, so you don't have to know the folder.

### Frontmatter, wikilinks, and tags

- `frontmatter` (object) and `tags` (array) on `obsidian_write` populate the
  YAML properties block Obsidian reads. `tags` is merged into `frontmatter.tags`
  (de-duplicated).
- `[[wikilinks]]` and inline `#tags` in note bodies are preserved verbatim — put
  them straight into `content`.

### Daily notes

`obsidian_daily` resolves `<vault>/<obsidian_daily_folder>/<date>.md` using
`obsidian_daily_date_format`, creating the note on first write of the day and
appending thereafter.

## Examples

```text
obsidian_write(note="Projects/Athena", content="Kicked off the Obsidian tool.\nSee [[Daily/2026-06-07]].", tags=["project", "athena"])
obsidian_append(note="Athena", content="- Wired the vault tools.", heading="Log")
obsidian_search(query="vault tools")
obsidian_daily(content="Shipped the Obsidian integration.", heading="Done")
obsidian_read(note="Athena")
```

Each write returns an `obsidian://open?vault=...&file=...` URI you can click to
open the note in the app.

## Safety

- Every write resolves **strictly inside the vault root**. A `..` traversal or
  an absolute path pointing outside the vault is refused (`ERROR: path escapes
  the vault`).
- Write/append/daily are `requires_confirmation` tools (they mutate your
  personal vault); read/search are read-only and parallel-safe.
