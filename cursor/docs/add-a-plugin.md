# Add a plugin

Add a new plugin under `plugins/` and register it in `.cursor-plugin/marketplace.json`.

## 1. Create plugin directory

Create a new folder:

```text
plugins/my-new-plugin/
```

Add the required manifest:

```text
plugins/my-new-plugin/.cursor-plugin/plugin.json
```

Example manifest:

```json
{
  "name": "my-new-plugin",
  "displayName": "My New Plugin",
  "version": "0.1.0",
  "description": "Describe what this plugin does",
  "author": {
    "name": "Your Org"
  },
  "logo": "assets/logo.svg"
}
```

## 2. Add plugin components

Add only the components you need:

- `rules/` with `.mdc` files (YAML frontmatter required)
- `skills/` with `SKILL.md` (YAML frontmatter required); can symlink to repo `skills/` for shared content
- `agents/*.md` (YAML frontmatter required)
- `commands/*.(md|mdc|markdown|txt)` (frontmatter recommended)
- `hooks/hooks.json` and `scripts/*` for automation hooks
- `mcp.json` for MCP server definitions
- `assets/logo.svg` for marketplace display

## 3. Register in marketplace manifest

Edit `.cursor-plugin/marketplace.json` and append a new entry:

```json
{
  "name": "my-new-plugin",
  "source": "./plugins/my-new-plugin",
  "description": "Describe your plugin"
}
```

`source` is the relative path from this `cursor/` folder (template root) to the plugin folder.

## 4. Validate

If you add `scripts/validate-template.mjs` (as in the [Cursor plugin template](https://github.com/cursor/plugin-template)), run:

```bash
node scripts/validate-template.mjs
```

Fix any reported errors before committing.
