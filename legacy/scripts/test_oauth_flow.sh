#\!/bin/bash
# Test OAuth logout flow

echo "Testing Manager OAuth Logout Flow"
echo "================================="

# Test logout endpoint directly
echo -e "
1. Testing logout endpoint with cookie auth:"
ssh root@108.61.119.117 "curl -s -X POST https://agents.ciris.ai/manager/v1/oauth/logout \
  -H \"Cookie: manager_token=test\" \
  -w \"
HTTP Status: %{http_code}
\" \
  -o /dev/null"

# Check if manager page requires auth after logout
echo -e "
2. Checking if manager requires auth (should redirect):"
ssh root@108.61.119.117 "curl -s -I https://agents.ciris.ai/manager/ | grep -E \"(HTTP|Location)\" | head -3"
