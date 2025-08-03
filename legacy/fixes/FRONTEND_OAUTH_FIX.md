# Frontend OAuth Fix Required

## The Problem
Frontend is sending `redirect_uri=/manager/oauth/callback` but should send `redirect_uri=/manager/callback`

## The Fix
In CIRISAgent/CIRISGUI/apps/agui/app/login/page.tsx

Find this line (around line 220):
```typescript
window.location.href = `/manager/v1/oauth/login?redirect_uri=${encodeURIComponent('/manager/oauth/callback')}`;
```

Change to:
```typescript
window.location.href = `/manager/v1/oauth/login?redirect_uri=${encodeURIComponent('/manager/callback')}`;
```

## Why This Works
- Frontend already has handler at `/manager/callback/page.tsx`
- Backend will redirect to `/manager/callback?token=JWT`
- No more redirect loop!

## Test After Fix
1. Click "Manager Access"
2. Complete Google OAuth
3. Should land at `/manager/callback` with token
4. Manager dashboard loads with valid session
