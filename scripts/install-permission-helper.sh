#!/bin/bash
# Install CIRIS permission fix helper
# This script must be run as root

set -e

if [ "$EUID" -ne 0 ]; then
    echo "Please run as root (use sudo)"
    exit 1
fi

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
SOURCE_FILE="$SCRIPT_DIR/ciris-fix-permissions.c"
BINARY_NAME="ciris-fix-permissions"
INSTALL_PATH="/usr/local/bin/$BINARY_NAME"

echo "Installing CIRIS permission fix helper..."

# Check if source file exists
if [ ! -f "$SOURCE_FILE" ]; then
    echo "Error: Source file $SOURCE_FILE not found"
    exit 1
fi

# Compile the helper
echo "Compiling $BINARY_NAME..."
gcc -o "/tmp/$BINARY_NAME" "$SOURCE_FILE"

if [ $? -ne 0 ]; then
    echo "Error: Compilation failed"
    exit 1
fi

# Install with setuid permissions
echo "Installing to $INSTALL_PATH..."
mv "/tmp/$BINARY_NAME" "$INSTALL_PATH"
chown root:root "$INSTALL_PATH"
chmod 4755 "$INSTALL_PATH"  # setuid bit + executable

echo "Testing installation..."
if [ -x "$INSTALL_PATH" ]; then
    echo "✓ Helper installed successfully at $INSTALL_PATH"
    echo ""
    echo "The helper will automatically fix permissions for new agents."
    echo "To manually fix permissions for an existing agent, run:"
    echo "  $INSTALL_PATH /opt/ciris/agents/AGENT_ID"
    echo ""
    echo "Note: This helper only works on directories under /opt/ciris/agents/"
else
    echo "✗ Installation failed"
    exit 1
fi
