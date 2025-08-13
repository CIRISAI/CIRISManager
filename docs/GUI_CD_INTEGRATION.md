# CIRISGUI CD Integration with CIRISManager

Since CIRISGUI is now in a separate repository, its CI/CD pipeline needs to notify CIRISManager when a new GUI image is deployed. This document provides the necessary GitHub Actions workflow snippet for CIRISGUI.

## GitHub Actions Workflow Addition for CIRISGUI

Add this job to your `.github/workflows/deploy.yml` (or equivalent) in the CIRISGUI repository:

```yaml
  notify-manager:
    name: Notify CIRISManager of GUI Update
    needs: [build-and-push]  # Adjust based on your job names
    runs-on: ubuntu-latest
    if: github.ref == 'refs/heads/main' && github.event_name == 'push'
    
    steps:
      - name: Notify CIRISManager
        run: |
          # Get the image tag that was just pushed
          GUI_IMAGE="ghcr.io/cirisai/ciris-gui:latest"
          
          # Notify CIRISManager about the new GUI image
          response=$(curl -X POST https://agents.ciris.ai/manager/v1/updates/notify \
            -H "Content-Type: application/json" \
            -H "Authorization: Bearer ${{ secrets.CIRIS_DEPLOY_TOKEN }}" \
            -d '{
              "agent_image": null,
              "gui_image": "'${GUI_IMAGE}'",
              "message": "GUI update from CIRISGUI repository",
              "strategy": "immediate"
            }')
          
          echo "Manager response: $response"
          
          # Check if notification was successful
          if echo "$response" | grep -q "deployment_id"; then
            echo "✅ Successfully notified CIRISManager"
          else
            echo "❌ Failed to notify CIRISManager"
            echo "$response"
            exit 1
          fi
```

## Required Secrets

Add these secrets to your CIRISGUI repository settings:

1. **CIRIS_DEPLOY_TOKEN**: The deployment token for authenticating with CIRISManager
   - This should be the same token used in the CIRISAgent repository
   - Contact the CIRIS infrastructure team to get this token

## How It Works

1. When CIRISGUI pushes a new image to ghcr.io/cirisai/ciris-gui:latest
2. The GitHub Action calls CIRISManager's `/manager/v1/updates/notify` endpoint
3. CIRISManager:
   - Pulls the new GUI image
   - Updates the ciris-gui container
   - No agent restarts needed (GUI-only update)
   - Completes immediately (no canary deployment for GUI)

## Testing the Integration

You can test the notification manually:

```bash
curl -X POST https://agents.ciris.ai/manager/v1/updates/notify \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_DEPLOY_TOKEN" \
  -d '{
    "agent_image": null,
    "gui_image": "ghcr.io/cirisai/ciris-gui:latest",
    "message": "Test GUI update",
    "strategy": "immediate"
  }'
```

## Important Notes

- GUI updates are deployed immediately (no canary rollout)
- Only the GUI container is restarted, agents remain running
- The nginx configuration is not affected by GUI-only updates
- If both agent and GUI images are provided, the deployment follows the specified strategy (canary/immediate)

## Deployment Strategies

- **immediate**: Deploy to all containers at once (recommended for GUI-only updates)
- **canary**: Staged rollout (only applies when agent_image is provided)
- **manual**: Agents decide when to update (not applicable for GUI-only updates)

## Monitoring Deployment Status

After notification, you can check the deployment status:

```bash
# Get deployment status
curl -X GET https://agents.ciris.ai/manager/v1/updates/status \
  -H "Authorization: Bearer YOUR_DEPLOY_TOKEN"
```

## Rollback

If needed, GUI can be rolled back:

```bash
curl -X POST https://agents.ciris.ai/manager/v1/updates/rollback \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_DEPLOY_TOKEN" \
  -d '{
    "target_version": "n-1",
    "include_gui": true,
    "include_nginx": false,
    "affected_agents": []
  }'
```