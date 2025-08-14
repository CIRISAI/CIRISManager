#!/bin/bash
# Build and deploy the telemetry SDK for the dashboard

set -e

echo "Building Telemetry SDK..."

# Navigate to SDK directory
cd sdk/typescript/packages/ciristelemetry-sdk

# Install dependencies if needed
if [ ! -d "node_modules" ]; then
    echo "Installing dependencies..."
    npm ci
fi

# Build the SDK
echo "Building SDK..."
npm run build
npm run build:browser

# Copy to static directory
echo "Deploying SDK to static directory..."
mkdir -p ../../../../static/sdk
cp dist/ciristelemetry-sdk.min.js ../../../../static/sdk/

echo "Telemetry SDK build complete!"
echo "SDK available at: /static/sdk/ciristelemetry-sdk.min.js"