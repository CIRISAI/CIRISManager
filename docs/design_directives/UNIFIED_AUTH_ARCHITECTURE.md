## **name: "🔐 Architecture Directive" title: "🔐 [ARCHITECTURE]: Unified Authentication Architecture" labels: ["architecture", "authentication", "security"] assignees: ''**

### **1. Objective**

To establish a coherent authentication architecture that supports multiple authentication methods across different user types and deployment scenarios. This directive unifies the authentication requirements for CIRISManager administrators, agent operators, and end users, providing clear separation of concerns while maintaining security and usability.

### **2. Authentication Contexts**

The system recognizes three distinct authentication contexts:

1. **Manager Administration**: Access to CIRISManager API for agent lifecycle management
2. **Agent Operation**: Access to individual agent APIs for configuration and control
3. **Agent Usage**: End-user access to agent functionality

### **3. Authentication Methods**

#### **3.1 Manager Authentication (Administrator Access)**

* **Primary Method**: Google OAuth 2.0
* **Scope**: Access to `/manager/v1/*` endpoints
* **Token Type**: JWT with manager-specific claims
* **Configuration**:
  ```yaml
  auth:
    mode: production  # or development
    google:
      client_id: ${GOOGLE_CLIENT_ID}
      client_secret: ${GOOGLE_CLIENT_SECRET}
    jwt:
      secret: ${MANAGER_JWT_SECRET}
      expiry: 24h
  ```

#### **3.2 Agent Authentication (Operator Access)**

* **OAuth Support**: Agents can implement their own OAuth providers
* **Methods Available**:
  - Google OAuth (reusing manager's provider)
  - GitHub OAuth
  - Custom OAuth providers
  - API key authentication
* **Scope**: Access to `/agent/{name}/admin/*` endpoints
* **Token Type**: Agent-specific JWT or API keys
* **Configuration** (per agent):
  ```yaml
  auth:
    providers:
      - type: google
        client_id: ${AGENT_GOOGLE_CLIENT_ID}
      - type: github
        client_id: ${AGENT_GITHUB_CLIENT_ID}
      - type: api_key
        header: X-Agent-API-Key
  ```

#### **3.3 User Authentication (End User Access)**

* **Primary Method**: Username/password
* **Alternate Methods**: 
  - Social login (if configured by agent)
  - Anonymous access (if allowed by agent)
* **Scope**: Access to `/agent/{name}/api/*` endpoints
* **Token Type**: Session cookies or bearer tokens
* **Storage**: Agent-specific user database

### **4. Functional Requirements**

#### **4.1 Authentication Flow Separation**

* Manager authentication SHALL be completely independent from agent authentication
* Each agent SHALL maintain its own user database and session management
* Authentication tokens SHALL NOT be valid across different contexts
* The nginx router SHALL preserve authentication headers when proxying requests

#### **4.2 Development Mode**

* When `auth.mode: development`, ALL authentication SHALL be bypassed for manager endpoints
* Agents SHALL have independent development mode configuration
* Development mode SHALL be clearly indicated in logs and API responses
* Production deployments SHALL reject configurations with development mode enabled

#### **4.3 Token Management**

* Manager JWTs SHALL include:
  ```json
  {
    "sub": "user@example.com",
    "context": "manager",
    "permissions": ["agents:read", "agents:write"],
    "exp": 1234567890
  }
  ```

* Agent JWTs SHALL include:
  ```json
  {
    "sub": "user@example.com",
    "context": "agent:{name}",
    "role": "operator|user",
    "permissions": ["config:read", "config:write"],
    "exp": 1234567890
  }
  ```

#### **4.4 OAuth Callback Routing**

* Manager OAuth callback: `/auth/callback`
* Agent OAuth callbacks: `/agent/{name}/auth/callback`
* Nginx SHALL route callbacks to appropriate services based on URL pattern

### **5. Implementation Architecture**

```
┌─────────────────────────────────────────────────┐
│                    Client                        │
└─────────────────────────────────────────────────┘
                        │
                    HTTPS:443
                        │
    ┌───────────────────┴───────────────────────┐
    │                nginx                        │
    │          (Auth Header Passthrough)          │
    └───────────────────┬───────────────────────┘
                        │
    ┌───────────────────┼───────────────────────┐
    │                   │                        │
    ▼                   ▼                        ▼
/manager/v1/*      /agent/{name}/admin/*    /agent/{name}/api/*
    │                   │                        │
    ▼                   ▼                        ▼
┌──────────┐      ┌──────────┐            ┌──────────┐
│ Manager  │      │  Agent   │            │  Agent   │
│  OAuth   │      │  OAuth   │            │ User DB  │
│ (Google) │      │(Multiple)│            │(User/Pass)│
└──────────┘      └──────────┘            └──────────┘
```

### **6. Security Considerations**

#### **6.1 Token Isolation**

* Manager tokens SHALL NOT grant access to agent endpoints
* Agent tokens SHALL NOT grant access to manager endpoints
* Cross-agent token usage SHALL be prevented
* Token validation SHALL occur at service boundaries

#### **6.2 Secret Management**

* OAuth secrets SHALL be stored in environment variables
* JWT secrets SHALL be unique per service
* Development mode SHALL use well-known secrets
* Production SHALL enforce secret rotation

#### **6.3 Session Security**

* Sessions SHALL be bound to IP address and user agent
* Concurrent session limits SHALL be configurable
* Session revocation SHALL be immediate
* Failed authentication SHALL implement rate limiting

### **7. Migration Path**

For existing deployments:

1. **Phase 1**: Implement manager OAuth with development mode
2. **Phase 2**: Add agent OAuth provider support
3. **Phase 3**: Implement agent user authentication
4. **Phase 4**: Deprecate any legacy auth methods

### **8. Success Criteria**

* **Given** a manager admin with valid Google OAuth token, **When** accessing `/manager/v1/agents`, **Then** request succeeds
* **Given** a manager admin token, **When** accessing `/agent/foo/admin/config`, **Then** request is rejected with 401
* **Given** an agent operator with agent-specific OAuth token, **When** accessing `/agent/foo/admin/config`, **Then** request succeeds
* **Given** an agent user with username/password session, **When** accessing `/agent/foo/api/v1/interact`, **Then** request succeeds
* **Given** development mode is enabled, **When** accessing any manager endpoint, **Then** authentication is bypassed
* **Given** an expired token, **When** accessing any protected endpoint, **Then** request is rejected with 401

### **9. Configuration Examples**

#### **9.1 Production Manager + Agent**
```yaml
# Manager config
auth:
  mode: production
  google:
    client_id: "manager-client-id.apps.googleusercontent.com"
    client_secret: ${GOOGLE_CLIENT_SECRET}

# Agent config
agents:
  support-bot:
    auth:
      providers:
        - type: google
          client_id: "agent-client-id.apps.googleusercontent.com"
        - type: user_pass
          bcrypt_rounds: 12
```

#### **9.2 Development Setup**
```yaml
# Manager config
auth:
  mode: development

# Agent config  
agents:
  test-agent:
    auth:
      allow_anonymous: true
```

### **10. Future Enhancements**

* SAML/SSO support for enterprise deployments
* Multi-factor authentication for sensitive operations
* OAuth scope mapping to granular permissions
* Federated authentication across multiple CIRIS deployments
* WebAuthn/FIDO2 support for passwordless authentication