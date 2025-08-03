## **name: "✨ Feature Proposal" title: "✨ \[FEATURE\]: Implement Coherent Authentication for Dev/Prod" labels: \["enhancement", "proposal", "architecture"\] assignees: ''**

### **1\. Objective**

To implement a flexible authentication system that provides a seamless, coherent experience for all clients, including the GUI and CLI, across both local development and production environments. The goal is to maintain robust security in production via Google OAuth, while eliminating the significant setup barrier for developers who simply want to run the manager locally to build and test agents. This directive introduces a configurable "auth mode" to achieve this balance from the start.

### **2\. Functional Requirements**

* The system's authentication behavior shall be controlled by a new auth.mode setting in the configuration file, which can be set to production or development.
* The system shall log a clear, prominent message at startup indicating which authentication mode is active.
* When mode is set to production (the default), the system shall operate with the full Google OAuth2 security flow.
* When mode is set to development, the system shall completely disable the external authentication requirement.
  * All protected API endpoints (e.g., creating/deleting agents) shall be accessible without an authentication token.
  * The OAuth-specific endpoints (/auth/login, /auth/callback, etc.) shall not be available.
* In development mode, a mock user object with default values shall be provided to any endpoint that requires an authenticated user.
* The system shall expose its current authentication mode to clients, likely via an existing status or health endpoint, allowing the frontend to adapt its UI accordingly (e.g., hide the "Login" button).

### **3\. Success Criteria**

* **Given** auth.mode is set to production, **When** a request is made to a protected endpoint like POST /manager/v1/agents without a valid JWT, **Then** the API shall return a 401 Unauthorized or 403 Forbidden error.
* **Given** auth.mode is set to development, **When** a request is made to a protected endpoint like POST /manager/v1/agents without any token, **Then** the API shall process the request and return a 200 OK success response.
* **Given** auth.mode is set to development, **When** a request is made to GET /auth/login, **Then** the API shall return a 404 Not Found error.
* **Given** auth.mode is set to production, **When** the manager starts, **Then** a log message shall confirm that "Production authentication mode is active".
* **Given** auth.mode is set to development, **When** the manager starts, **Then** a prominent log message shall warn that "Development authentication mode is active. Do not use in production."
* **Given** auth.mode is set to development, **When** a client requests the status endpoint, **Then** the response body shall contain {"auth\_mode": "development"}.
