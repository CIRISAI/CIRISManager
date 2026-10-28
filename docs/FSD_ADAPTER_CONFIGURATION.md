# Adapter Configuration System

---

## 1. Overview

### 1.1 Purpose
Enable users to configure adapters on deployed agents through a wizard-based UI that dynamically renders based on adapter manifests. Different agents may have different adapters available based on their role/deployment type.

### 1.2 Scope
- Manager UI: New "Adapters" button on agent cards
- Manager API: Wizard session management endpoints
- Agent Integration: Fetch available adapters and manifests from running agents
- Configuration Persistence: Store adapter configs in registry, apply to compose

### 1.3 Out of Scope
- Modifying adapter manifest schema (already well-designed)
- Agent-side adapter loading (already implemented)
- Discord/Reddit standalone flows (preserved for backward compatibility)

---

## 2. User Stories

### 2.1 Primary User Stories

**US-1: View Available Adapters**
> As an operator, I want to see which adapters are available for my agent, so I can understand what integrations are possible.

**US-2: Configure New Adapter**
> As an operator, I want to configure a new adapter through a guided wizard, so I don't have to manually set environment variables.

**US-3: Home Assistant Discovery**
> As a home user, I want to auto-discover my Home Assistant instance and authenticate via OAuth, so setup is seamless.

**US-4: Covenant Metrics Consent**
> As an operator, I want to explicitly consent to covenant metrics collection with full disclosure of what data is sent.

**US-5: Reddit Bot Setup**
> As a community manager, I want to configure Reddit integration by entering my OAuth credentials step-by-step.

**US-6: View/Modify Existing Configs**
> As an operator, I want to see which adapters are configured and modify or disable them.

---

## 3. System Architecture

### 3.1 Component Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                          Manager UI (React)                          │
├─────────────────────────────────────────────────────────────────────┤
│  AgentCard                                                           │
│  ├── [Adapters] Button ──────────────────┐                          │
│  └── Status, Controls, etc.              │                          │
│                                          ▼                          │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │ AdapterPanel (Slide-out or Modal)                            │   │
│  │ ├── Available Adapters List                                  │   │
│  │ │   ├── [Configure] → Opens Wizard                          │   │
│  │ │   └── [Status Badge] enabled/disabled/needs-config        │   │
│  │ │                                                            │   │
│  │ └── AdapterWizard (ViewPager-style)                         │   │
│  │     ├── Step 1: Discovery/Input                              │   │
│  │     ├── Step 2: OAuth/Credentials                            │   │
│  │     ├── Step 3: Options                                      │   │
│  │     └── Step N: Confirm                                      │   │
│  └─────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                       Manager API (FastAPI)                          │
├─────────────────────────────────────────────────────────────────────┤
│  Existing Proxy Endpoints (routes/adapters.py):                     │
│  ├── GET  /agents/{id}/adapters          → List running adapters    │
│  ├── GET  /agents/{id}/adapters/types    → List available types     │
│  ├── POST /agents/{id}/adapters/{type}   → Load adapter             │
│  └── ...                                                             │
│                                                                      │
│  NEW Wizard Endpoints (routes/adapters.py):                         │
│  ├── GET  /agents/{id}/adapters/manifests     → All manifests       │
│  ├── GET  /agents/{id}/adapters/{type}/manifest → Single manifest   │
│  ├── POST /agents/{id}/adapters/{type}/wizard/start → Start wizard  │
│  ├── POST /agents/{id}/adapters/{type}/wizard/{session}/step        │
│  ├── POST /agents/{id}/adapters/{type}/wizard/{session}/complete    │
│  ├── GET  /agents/{id}/adapters/configs       → Persisted configs   │
│  └── DELETE /agents/{id}/adapters/{type}/config → Remove config     │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                    ┌───────────────┴───────────────┐
                    ▼                               ▼
┌─────────────────────────────┐   ┌─────────────────────────────┐
│      Agent Registry          │   │     Running Agent           │
│      (metadata.json)         │   │     (Docker Container)      │
├─────────────────────────────┤   ├─────────────────────────────┤
│ agents:                      │   │ GET /v1/system/adapters     │
│   "datum":                   │   │     → Running adapters      │
│     adapter_configs:         │   │                             │
│       home_assistant:        │   │ GET /v1/system/adapters/    │
│         enabled: true        │   │     types                   │
│         url: "..."           │   │     → Available types       │
│         token: "..."         │   │                             │
│         configured_at: "..." │   │ GET /v1/system/adapters/    │
│       covenant_metrics:      │   │     {type}/manifest         │
│         consent_given: true  │   │     → Full manifest JSON    │
│         consent_timestamp:   │   │                             │
│           "2026-01-17T..."   │   │ POST /v1/system/adapters/   │
└─────────────────────────────┘   │     {type}                  │
              │                    │     → Load adapter          │
              ▼                    └─────────────────────────────┘
┌─────────────────────────────┐
│    Compose Generator         │
│    (compose_generator.py)    │
├─────────────────────────────┤
│ Reads adapter_configs →      │
│ Generates env vars →         │
│ Writes docker-compose.yml    │
└─────────────────────────────┘
```

### 3.2 Data Flow: Configure New Adapter

```
User clicks [Adapters] on AgentCard
         │
         ▼
UI fetches GET /agents/{id}/adapters/manifests
         │
         ▼
UI displays adapter list with status badges
         │
User clicks [Configure] on "home_assistant"
         │
         ▼
UI fetches GET /agents/{id}/adapters/home_assistant/manifest
         │
         ▼
UI renders wizard from manifest.interactive_config.steps
         │
         ▼
User completes Step 1 (Discovery) → mDNS finds HA at 192.168.1.50:8123
         │
         ▼
User completes Step 2 (OAuth) → Redirects to HA → Returns with token
         │
         ▼
User completes Step 3 (Select Features) → Chooses device_control, sensors
         │
         ▼
User clicks [Finish] on Confirm step
         │
         ▼
UI calls POST /agents/{id}/adapters/home_assistant/wizard/{session}/complete
         │
         ▼
Manager:
  1. Stores config in registry.adapter_configs
  2. Regenerates docker-compose.yml with new env vars
  3. Calls POST /agents/{id}/adapters/home_assistant to load adapter
  4. Optionally restarts container if env vars changed
         │
         ▼
UI shows success, adapter now shows [Enabled] badge
```

---

## 4. API Specification

### 4.1 New Endpoints

#### GET /manager/v1/agents/{agent_id}/adapters/manifests

Get all available adapter manifests for this agent.

**Response:**
```json
{
  "adapters": [
    {
      "adapter_type": "home_assistant",
      "name": "Home Assistant",
      "description": "Enhanced Home Assistant integration...",
      "version": "1.0.0",
      "status": "not_configured",
      "requires_consent": false,
      "has_wizard": true,
      "workflow_type": "discovery_then_config"
    },
    {
      "adapter_type": "reddit",
      "name": "Reddit",
      "description": "Reddit bot integration...",
      "version": "1.0.0",
      "status": "configured",
      "requires_consent": false,
      "has_wizard": true,
      "workflow_type": "wizard"
    },
    {
      "adapter_type": "ciris_covenant_metrics",
      "name": "CIRIS Covenant Metrics",
      "description": "Covenant compliance metrics...",
      "version": "1.0.0",
      "status": "not_configured",
      "requires_consent": true,
      "has_wizard": true,
      "workflow_type": "wizard"
    }
  ]
}
```

**Status Values:**
- `not_configured` - Adapter available but not set up
- `configured` - Config exists in registry
- `enabled` - Config exists and adapter is running
- `disabled` - Config exists but adapter not running
- `error` - Config exists but adapter failed to load

---

#### GET /manager/v1/agents/{agent_id}/adapters/{adapter_type}/manifest

Get full manifest for a specific adapter.

**Response:** Full manifest JSON from agent, plus Manager overlay:
```json
{
  "module": { "name": "home_assistant", ... },
  "interactive_config": {
    "required": false,
    "workflow_type": "discovery_then_config",
    "steps": [
      {
        "step_id": "discover",
        "step_type": "discovery",
        "title": "Discover Home Assistant",
        "description": "Find Home Assistant instances...",
        "discovery_method": "mdns"
      },
      {
        "step_id": "oauth",
        "step_type": "oauth",
        "title": "Authenticate with Home Assistant",
        ...
      },
      ...
    ]
  },
  "configuration": { ... },
  "_manager": {
    "current_config": { ... },  // If configured
    "status": "configured"
  }
}
```

---

#### POST /manager/v1/agents/{agent_id}/adapters/{adapter_type}/wizard/start

Start a new wizard session.

**Request:**
```json
{
  "resume_from": null  // Optional: session_id to resume
}
```

**Response:**
```json
{
  "session_id": "wiz_abc123",
  "adapter_type": "home_assistant",
  "current_step": "discover",
  "steps_completed": [],
  "steps_remaining": ["discover", "oauth", "select_features", "confirm"],
  "collected_data": {},
  "expires_at": "2026-01-17T07:00:00Z"
}
```

---

#### POST /manager/v1/agents/{agent_id}/adapters/{adapter_type}/wizard/{session_id}/step

Execute a wizard step.

**Request:**
```json
{
  "step_id": "discover",
  "action": "execute",  // or "skip" for optional steps
  "data": {
    // Step-specific data
  }
}
```

**Response (Discovery Step):**
```json
{
  "session_id": "wiz_abc123",
  "step_id": "discover",
  "status": "completed",
  "result": {
    "discovered": [
      {
        "name": "Home Assistant",
        "url": "http://192.168.1.50:8123",
        "version": "2025.1.0"
      }
    ]
  },
  "next_step": "oauth",
  "collected_data": {
    "homeassistant_url": "http://192.168.1.50:8123"
  }
}
```

**Response (OAuth Step):**
```json
{
  "session_id": "wiz_abc123",
  "step_id": "oauth",
  "status": "pending_redirect",
  "result": {
    "authorization_url": "http://192.168.1.50:8123/auth/authorize?...",
    "state": "oauth_state_xyz",
    "callback_url": "https://agents.ciris.ai/manager/v1/agents/{id}/adapters/home_assistant/wizard/{session}/oauth-callback"
  }
}
```

**Response (Input Step):**
```json
{
  "session_id": "wiz_abc123",
  "step_id": "client_credentials",
  "status": "completed",
  "validation": {
    "valid": true,
    "errors": []
  },
  "next_step": "bot_account",
  "collected_data": {
    "client_id": "abc123",
    "client_secret": "***"  // Masked in response
  }
}
```

---

#### POST /manager/v1/agents/{agent_id}/adapters/{adapter_type}/wizard/{session_id}/complete

Complete the wizard and apply configuration.

**Request:**
```json
{
  "confirm": true
}
```

**Response:**
```json
{
  "session_id": "wiz_abc123",
  "status": "completed",
  "adapter_type": "home_assistant",
  "config_applied": true,
  "adapter_loaded": true,
  "restart_required": false,
  "message": "Home Assistant adapter configured and started successfully"
}
```

---

#### GET /manager/v1/agents/{agent_id}/adapters/configs

Get all persisted adapter configurations for this agent.

**Response:**
```json
{
  "configs": {
    "home_assistant": {
      "enabled": true,
      "configured_at": "2026-01-17T06:30:00Z",
      "config": {
        "homeassistant_url": "http://192.168.1.50:8123",
        "enabled_features": ["device_control", "sensors"]
      },
      "env_vars": {
        "HOME_ASSISTANT_URL": "http://192.168.1.50:8123",
        "HOME_ASSISTANT_TOKEN": "***"
      }
    },
    "ciris_covenant_metrics": {
      "enabled": true,
      "configured_at": "2026-01-17T06:00:00Z",
      "consent_given": true,
      "consent_timestamp": "2026-01-17T06:00:00Z",
      "config": {
        "endpoint_url": "https://lens.ciris.ai/v1",
        "batch_size": 10
      }
    }
  }
}
```

---

#### DELETE /manager/v1/agents/{agent_id}/adapters/{adapter_type}/config

Remove adapter configuration.

**Response:**
```json
{
  "adapter_type": "home_assistant",
  "config_removed": true,
  "adapter_unloaded": true,
  "message": "Home Assistant adapter disabled and configuration removed"
}
```

---

## 5. UI Design

### 5.1 Agent Card - Adapters Button

```
┌─────────────────────────────────────────────────────────┐
│  datum                                     [Running ●]  │
│  Template: base | Port: 8001                            │
│  Version: 1.0.8 | Cognitive: WORK                       │
├─────────────────────────────────────────────────────────┤
│  [Start] [Stop] [Restart] [Logs] [Config] [Adapters ▾] │
└─────────────────────────────────────────────────────────┘
```

**Adapters Button Behavior:**
- Click opens AdapterPanel (slide-out from right or modal)
- Badge shows count of configured adapters: `[Adapters (2)]`

### 5.2 Adapter Panel

```
┌─────────────────────────────────────────────────────────┐
│  Adapters for: datum                              [X]   │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  ┌─────────────────────────────────────────────────┐   │
│  │ 🏠 Home Assistant              [Enabled ●]      │   │
│  │    Smart home integration                       │   │
│  │    [Configure] [Disable]                        │   │
│  └─────────────────────────────────────────────────┘   │
│                                                         │
│  ┌─────────────────────────────────────────────────┐   │
│  │ 🤖 Reddit                      [Configured ○]   │   │
│  │    Reddit bot integration                       │   │
│  │    [Configure] [Enable]                         │   │
│  └─────────────────────────────────────────────────┘   │
│                                                         │
│  ┌─────────────────────────────────────────────────┐   │
│  │ 📊 Covenant Metrics            [Not Configured] │   │
│  │    Compliance metrics (requires consent)        │   │
│  │    [Set Up]                                     │   │
│  └─────────────────────────────────────────────────┘   │
│                                                         │
│  ┌─────────────────────────────────────────────────┐   │
│  │ 🎮 Discord                     [Not Available]  │   │
│  │    Requires Discord bot token                   │   │
│  │    [View Requirements]                          │   │
│  └─────────────────────────────────────────────────┘   │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

### 5.3 Wizard Modal

```
┌─────────────────────────────────────────────────────────────────┐
│  Configure: Home Assistant                                 [X]  │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ● ─ ○ ─ ○ ─ ○           Step 1 of 4                           │
│  Discover  Auth  Features  Confirm                              │
│                                                                  │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  🔍 Discover Home Assistant                                     │
│                                                                  │
│  Find Home Assistant instances on your network via mDNS         │
│  or enter the URL manually.                                     │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  Discovered Instances:                                   │   │
│  │                                                          │   │
│  │  ○ Home Assistant (192.168.1.50:8123) - v2025.1.0       │   │
│  │  ○ Enter URL manually...                                 │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                  │
│  [Scan Again]                                                   │
│                                                                  │
├─────────────────────────────────────────────────────────────────┤
│                                        [Cancel]  [Next →]       │
└─────────────────────────────────────────────────────────────────┘
```

### 5.4 Consent Step (Covenant Metrics)

```
┌─────────────────────────────────────────────────────────────────┐
│  Configure: CIRIS Covenant Metrics                         [X]  │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ● ─ ○ ─ ○           Step 1 of 3                               │
│  Disclosure  Consent  Confirm                                   │
│                                                                  │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  📊 Data Collection Disclosure                                  │
│                                                                  │
│  This adapter will send the following data to CIRIS L3C:        │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  **WBD (Wisdom-Based Deferral) Events:**                 │   │
│  │  - Anonymized agent ID (hash)                            │   │
│  │  - Thought/Task IDs                                      │   │
│  │  - Deferral reason (no message content)                  │   │
│  │  - Timestamp and priority                                │   │
│  │                                                          │   │
│  │  **PDMA Decision Events:**                               │   │
│  │  - Anonymized agent ID (hash)                            │   │
│  │  - Selected action type                                  │   │
│  │  - Rationale summary (no user content)                   │   │
│  │  - Timestamp                                             │   │
│  │                                                          │   │
│  │  **NOT collected:**                                      │   │
│  │  - User messages or content                              │   │
│  │  - Personal information                                  │   │
│  │  - Chat history                                          │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                  │
│  Data is sent via HTTPS to https://lens.ciris.ai/v1            │
│                                                                  │
├─────────────────────────────────────────────────────────────────┤
│                                        [Cancel]  [I Understand] │
└─────────────────────────────────────────────────────────────────┘
```

---

## 6. Step Type Implementations

### 6.1 Step Type: `input`

Renders form fields based on `fields[]` array.

**Field Types:**
- `text` → `<input type="text">`
- `password` → `<input type="password">` with show/hide toggle
- `boolean` → Checkbox or toggle switch
- `integer` → Number input with min/max validation
- `float` → Number input with step="0.1"
- `array` → Tag input or multi-select

**Validation:**
- `required: true` → Field must have value
- `min/max` → Range validation for numbers
- `pattern` → Regex validation for text

### 6.2 Step Type: `select`

Renders selection from options.

**Options Source:**
- Static: `options[]` array in step definition
- Dynamic: `options_method` calls agent endpoint to get options

**Selection Modes:**
- Single select (radio buttons or dropdown)
- Multi-select (checkboxes)

### 6.3 Step Type: `discovery`

Triggers automatic discovery.

**Discovery Methods:**
- `mdns` → Network scan for service
- `manual` → User enters URL/address

**UI:**
- Loading spinner during scan
- List of discovered items with radio selection
- "Enter manually" option always available

### 6.4 Step Type: `oauth`

Handles OAuth2 authentication flow.

**Flow:**
1. Manager generates authorization URL with state
2. User clicks "Authorize" → Opens popup/redirect
3. OAuth provider redirects to callback URL
4. Manager exchanges code for tokens
5. Stores tokens in wizard session

**Callback URL:**
`https://agents.ciris.ai/manager/v1/agents/{id}/adapters/{type}/wizard/{session}/oauth-callback`

### 6.5 Step Type: `confirm`

Final review before applying config.

**UI:**
- Summary of all collected data
- Checkboxes for consent (if `requires_consent`)
- [Apply] button triggers completion

---

## 7. State Management

### 7.1 Wizard Session (Server-Side)

```python
class WizardSession:
    session_id: str
    agent_id: str
    adapter_type: str
    created_at: datetime
    expires_at: datetime  # 1 hour TTL
    current_step: str
    steps_completed: List[str]
    collected_data: Dict[str, Any]  # Encrypted at rest
    oauth_state: Optional[str]  # For OAuth flows
```

**Storage:** In-memory with optional Redis for multi-instance deployments.

### 7.2 Adapter Config (Persistent)

```python
# In agent_registry.py
class AdapterConfig:
    adapter_type: str
    enabled: bool
    configured_at: str  # ISO timestamp
    config: Dict[str, Any]  # Wizard-collected values
    env_vars: Dict[str, str]  # Mapped to env var names
    consent_given: Optional[bool]  # For consent-required adapters
    consent_timestamp: Optional[str]
```

### 7.3 UI State (Client-Side)

```typescript
interface WizardState {
  sessionId: string;
  adapterType: string;
  manifest: AdapterManifest;
  currentStep: number;
  stepsCompleted: string[];
  collectedData: Record<string, any>;
  validationErrors: Record<string, string>;
  isLoading: boolean;
}
```

---

## 8. Security Considerations

### 8.1 Sensitive Data

- **API Keys/Tokens:** Encrypted at rest in registry
- **OAuth Tokens:** Stored with refresh token, auto-renewed
- **Passwords:** Never logged, masked in responses
- **Consent Records:** Immutable audit trail

### 8.2 Authorization

- All endpoints require Manager authentication
- Adapter configs scoped to specific agents
- OAuth callbacks validated with state parameter

### 8.3 Rate Limiting

- Wizard sessions: Max 5 concurrent per user
- OAuth attempts: Max 3 per minute per agent
- Discovery scans: Max 1 per 30 seconds

---

## 9. Error Handling

### 9.1 Wizard Errors

| Error | Response | UI Handling |
|-------|----------|-------------|
| Session expired | 410 Gone | Restart wizard |
| Validation failed | 400 Bad Request | Show field errors |
| OAuth failed | 401 Unauthorized | Retry auth step |
| Agent unreachable | 502 Bad Gateway | Show connectivity error |
| Discovery timeout | 504 Gateway Timeout | Offer manual entry |

### 9.2 Recovery

- Sessions auto-saved after each step
- "Resume" option for interrupted wizards
- Partial configs not applied until completion

---

## 10. Test Cases

### 10.1 Unit Tests

- Wizard session creation/expiration
- Step validation for each field type
- Config persistence and retrieval
- Env var mapping from config

### 10.2 Integration Tests

- Full wizard flow: Home Assistant with OAuth
- Full wizard flow: Reddit with credentials
- Full wizard flow: Covenant Metrics with consent
- Config application to compose file
- Adapter loading after config

### 10.3 E2E Tests

- UI: Complete wizard, verify adapter runs
- UI: Modify existing config
- UI: Disable and re-enable adapter

---

## 11. Appendix

### A. Manifest `interactive_config` Schema

```json
{
  "interactive_config": {
    "required": false,
    "workflow_type": "wizard | discovery_then_config",
    "steps": [
      {
        "step_id": "string",
        "step_type": "input | select | discovery | oauth | confirm",
        "title": "string",
        "description": "string",
        "fields": [/* for input steps */],
        "options": [/* for select steps */],
        "options_method": "string",
        "discovery_method": "string",
        "oauth_config": {/* for oauth steps */},
        "depends_on": ["step_id"],
        "optional": false
      }
    ],
    "completion_method": "apply_config"
  }
}
```

### B. Existing Adapters with Wizards

| Adapter | Workflow | Steps | Consent |
|---------|----------|-------|---------|
| home_assistant | discovery_then_config | 5 | No |
| reddit | wizard | 6 | No |
| ciris_covenant_metrics | wizard | 4 | Yes |

### C. Environment Variable Mapping

From manifest `configuration` section:
```json
"homeassistant_url": {
  "type": "string",
  "env": "HOME_ASSISTANT_URL",
  "default": "http://homeassistant.local:8123"
}
```

Manager maps wizard-collected values to env vars:
- Wizard collects: `homeassistant_url = "http://192.168.1.50:8123"`
- Registry stores: `env_vars["HOME_ASSISTANT_URL"] = "http://192.168.1.50:8123"`
- Compose generator writes: `HOME_ASSISTANT_URL=http://192.168.1.50:8123`
