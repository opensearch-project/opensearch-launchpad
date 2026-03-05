# Release Process

## Prerequisites

1. Set up PyPI Trusted Publisher (one-time setup):
   - Go to https://pypi.org/manage/account/publishing/
   - Add a new trusted publisher with:
     - PyPI Project Name: `opensearch-orchestrator`
     - Owner: Your GitHub username/org
     - Repository name: `agent` (or your repo name)
     - Workflow name: `release.yml`
     - Environment name: (leave blank)

## Release Steps

### Create and Push Tag

Simply create and push a tag with the desired version:

```bash
git tag -a v0.2.7 -m "Release v0.2.7"
git push origin v0.2.7
```

### GitHub Actions Automatically

The workflow will:
1. Extract version from tag (e.g., `v0.2.7` → `0.2.7`)
2. Update `pyproject.toml` and `opensearch_orchestrator/__init__.py` with the new version
3. Commit the version changes back to main
4. Run tests
5. Build distribution packages
6. Publish to PyPI using OIDC (no token needed!)
7. Create a GitHub release with artifacts

Monitor progress at: https://github.com/YOUR_USERNAME/agent/actions

## Troubleshooting

### PyPI Trusted Publisher Not Set Up

If you see authentication errors, ensure you've completed the PyPI trusted publisher setup in Prerequisites.

### Tests Fail

Fix the failing tests before proceeding with the release.

### Build Artifacts Invalid

Check that all required files are included in `pyproject.toml` under `[tool.hatch.build]`.
