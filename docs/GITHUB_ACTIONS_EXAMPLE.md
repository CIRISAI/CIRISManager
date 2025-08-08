# GitHub Actions Example for CD with Full Changelog

This example shows how to configure GitHub Actions to send deployment notifications with full commit messages to CIRISManager.

## Workflow Example

```yaml
name: Deploy to Production

on:
  push:
    tags:
      - 'v*'

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0  # Full history for changelog

      - name: Get previous tag
        id: prev_tag
        run: |
          PREV_TAG=$(git describe --tags --abbrev=0 HEAD^ 2>/dev/null || echo "")
          echo "prev_tag=$PREV_TAG" >> $GITHUB_OUTPUT

      - name: Generate changelog
        id: changelog
        run: |
          if [ -n "${{ steps.prev_tag.outputs.prev_tag }}" ]; then
            # Get all commit messages between previous tag and current
            CHANGELOG=$(git log ${{ steps.prev_tag.outputs.prev_tag }}..HEAD --pretty=format:"%s" | head -20)
          else
            # First release - get last 10 commits
            CHANGELOG=$(git log HEAD~10..HEAD --pretty=format:"%s")
          fi
          
          # Escape for JSON (replace quotes and newlines)
          CHANGELOG_JSON=$(echo "$CHANGELOG" | jq -Rs .)
          echo "changelog=$CHANGELOG_JSON" >> $GITHUB_OUTPUT
          
          # Also output for debugging
          echo "Changelog:"
          echo "$CHANGELOG"

      - name: Build and push Docker images
        run: |
          # Your Docker build and push commands here
          echo "Building and pushing images..."

      - name: Deploy to CIRISManager
        run: |
          curl -X POST https://agents.ciris.ai/manager/v1/updates/notify \
            -H "Authorization: Bearer ${{ secrets.DEPLOY_TOKEN }}" \
            -H "Content-Type: application/json" \
            -d "{
              \"agent_image\": \"ghcr.io/cirisai/ciris-agent:${{ github.ref_name }}\",
              \"gui_image\": \"ghcr.io/cirisai/ciris-gui:${{ github.ref_name }}\",
              \"version\": \"${{ github.ref_name }}\",
              \"commit_sha\": \"${{ github.sha }}\",
              \"changelog\": ${{ steps.changelog.outputs.changelog }},
              \"message\": \"Release ${{ github.ref_name }}\",
              \"strategy\": \"canary\",
              \"risk_level\": \"low\"
            }"
```

## Alternative: Using GitHub Release Notes

If you're creating GitHub releases, you can also extract the release notes:

```yaml
      - name: Get release notes
        id: release_notes
        run: |
          # Get release notes from GitHub API
          RELEASE_NOTES=$(gh api \
            -H "Accept: application/vnd.github+json" \
            /repos/${{ github.repository }}/releases/tags/${{ github.ref_name }} \
            --jq '.body')
          
          # If no release notes, fall back to commit messages
          if [ -z "$RELEASE_NOTES" ]; then
            RELEASE_NOTES=$(git log ${{ steps.prev_tag.outputs.prev_tag }}..HEAD --pretty=format:"- %s")
          fi
          
          # Escape for JSON
          RELEASE_NOTES_JSON=$(echo "$RELEASE_NOTES" | jq -Rs .)
          echo "notes=$RELEASE_NOTES_JSON" >> $GITHUB_OUTPUT
        env:
          GH_TOKEN: ${{ github.token }}
```

## What Agents Will See

With the full changelog, agents will receive a detailed shutdown message like:

```
System shutdown requested: Runtime: CD update to version v2.1.1 (deployment abc12345)
Release notes:
  • fix: memory leak in telemetry service
  • feat: add new monitoring endpoint
  • test: improve test coverage
  • docs: update API documentation
  • chore: bump dependencies
(API shutdown by wa-system-admin)
```

This gives agents full context about what changes are being deployed, allowing them to:
1. Log the complete update reason for audit purposes
2. Make informed decisions about whether to accept the update
3. Understand what functionality might be affected

## Tips

1. **Limit changelog length**: Use `head -20` to limit to most recent 20 commits
2. **Filter commits**: Use `--grep` to exclude certain commit types:
   ```bash
   git log --pretty=format:"%s" --grep="^(feat|fix|perf|security):" --perl-regexp
   ```
3. **Format nicely**: Use conventional commit format for automatic categorization
4. **Test locally**: Test the JSON escaping with:
   ```bash
   echo "line1
   line2" | jq -Rs .
   ```

## Security Notes

- Store `DEPLOY_TOKEN` as a repository secret
- Use HTTPS for all API calls
- Validate SSL certificates in production
- Rotate deployment tokens periodically