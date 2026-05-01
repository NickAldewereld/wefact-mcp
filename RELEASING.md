# Releasing wefact-mcp

This is the runbook for shipping a new version to PyPI. Most steps are
automated; the manual parts are clearly marked **MANUAL**.

## One-time setup

### 1. Create the GitHub repository

```bash
# From this directory, after `git init`:
gh repo create NickAldewereld/wefact-mcp --public --source=. --remote=origin --push
```

(Or create via the GitHub web UI and `git remote add origin …` manually.)

### 2. Configure PyPI Trusted Publishing — **MANUAL**

Trusted Publishing uses GitHub's OIDC tokens to authenticate, so we
never store a PyPI API token in GitHub Secrets.

1. Go to <https://pypi.org/manage/account/publishing/>
2. Click **Add a new pending publisher**.
3. Fill in:

   | Field | Value |
   |---|---|
   | PyPI project name | `wefact-mcp` |
   | Owner | `NickAldewereld` |
   | Repository | `wefact-mcp` |
   | Workflow filename | `publish.yml` |
   | Environment | `pypi` |

4. Save. (Pending = the project hasn't been published yet; PyPI will
   bind the publisher when the first matching workflow runs.)

### 3. Configure the GitHub `pypi` environment

In GitHub: **Settings → Environments → New environment** named `pypi`.
Optional but recommended:
- Add a "Required reviewers" rule with yourself as approver, so a tag
  push waits for your manual click before publishing.
- Add a deployment branch rule: only allow deployments from tags
  matching `v*`.

## Cutting a release

For each version bump:

```bash
# 1. Bump the version in pyproject.toml
$EDITOR pyproject.toml      # change `version = "0.1.0"` → "0.2.0" etc.

# 2. Update CHANGELOG.md with the new section at the top
$EDITOR CHANGELOG.md

# 3. Commit
git add pyproject.toml CHANGELOG.md
git commit -m "chore(release): v0.2.0"

# 4. Tag (annotated; use a GPG-signed tag if your update.sh checks for it)
git tag -s v0.2.0 -m "wefact-mcp 0.2.0"
# or unsigned:
# git tag -a v0.2.0 -m "wefact-mcp 0.2.0"

# 5. Push commit + tag
git push origin main
git push origin v0.2.0
```

The `publish.yml` workflow then:

1. Runs the test suite.
2. Builds wheel + sdist.
3. Verifies the tag matches `pyproject.toml` `version`.
4. Validates metadata with `twine check`.
5. Publishes to PyPI via OIDC trusted publishing.
6. Creates a GitHub Release with the changelog excerpt + dist files.

## Local build sanity check (before tagging)

```bash
# Inside the project venv:
pip install -e ".[dev]"
pytest -q                    # 28 tests should pass
rm -rf dist/ build/ *.egg-info
python -m build              # produces dist/*.whl + dist/*.tar.gz
twine check dist/*           # PASSED on both
```

If `twine check` complains about README rendering, fix it before
tagging — broken Markdown breaks the PyPI project page.

## Yanking a bad release

If `0.2.0` ships with a critical bug:

```bash
# yank from PyPI (does NOT delete; existing pins still resolve)
twine yank wefact-mcp==0.2.0 --reason "Critical regression in X — use 0.2.1"
```

Then ship 0.2.1 with the fix via the normal release flow.

## License delivery (paid customers)

Customers who buy via [easeo.nl/diensten/wefact-mcp](https://easeo.nl/diensten/wefact-mcp)
receive their **commercial license key** by email after their Revolut
payment is confirmed. The key is a receipt code, not a runtime gate —
the package on PyPI is the same artifact for everyone. The commercial
license grants legal rights (proprietary use, no AGPL §13 obligation)
that the AGPL alone does not.

For agency / white-label / WeFact-side partnerships, route to
[nick@easeo.nl](mailto:nick@easeo.nl).
