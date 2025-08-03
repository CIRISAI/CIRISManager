# OAuth Fix Vision Seed for CIRISAgent/CIRISGUI

## 🎯 THE ONE METRIC: Manager OAuth Success Rate = 100%

## Current State (What's Broken)
- Manager OAuth login returns 500 error after Google callback
- Frontend sends callback URL: `/manager/callback`
- Backend expects: `/manager/oauth/callback`
- Already fixed: CIRISManager no longer crashes (returns proper error instead of 500)

## Success Definition
When a @ciris.ai user clicks "Manager Access" on the login page, they successfully authenticate via Google OAuth and land on the Manager GUI dashboard with a valid session.

## The ONE Change Needed
In `/CIRISAgent/CIRISGUI/apps/agui/app/login/page.tsx` line 221:

```typescript
// CURRENT (WRONG):
window.location.href = `/manager/v1/oauth/login?redirect_uri=${encodeURIComponent('/manager/callback')}`;

// SHOULD BE:
window.location.href = `/manager/v1/oauth/login?redirect_uri=${encodeURIComponent('/manager/oauth/callback')}`;
```

## Why This Matters
- CIRISManager has a compatibility redirect at `/manager/oauth/callback` → `/manager/v1/oauth/callback`
- But frontend is sending users to `/manager/callback` which doesn't exist
- This ONE character change (`/manager/callback` → `/manager/oauth/callback`) will fix the entire flow

## Testing Success
1. Click "Manager Access" button
2. Authenticate with Google
3. Land on Manager dashboard (not an error page)
4. Check cookie: `manager_token` should be set

## Context for Next Session
- This is in the OTHER repository: CIRISAgent, not CIRISManager
- The login page is a shared component that serves both agent and manager auth
- After fixing, will need to rebuild and deploy the GUI container
- Production URL: https://agents.ciris.ai/login

## Deploy Note
Once fixed in CIRISGUI, the change needs to be deployed as a new GUI container image that CIRISManager will pull and run.
