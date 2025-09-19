#!/bin/bash
# Deploy BRC Tools to CHPC server
# Usage: ./deploy-chpc.sh

set -e  # Exit on any error

echo "🚀 Deploying BRC Tools to CHPC..."

# Load environment variables
source .env

# Sync code to CHPC
echo "📦 Syncing code..."
rsync -avz --exclude-from=.gitignore \
    . ${CHPC_USER}@${CHPC_HOST}:${CHPC_PROJECT_DIR}/

echo "🔧 Installing dependencies on CHPC..."
ssh ${CHPC_USER}@${CHPC_HOST} << 'EOF'
cd ${CHPC_PROJECT_DIR}
pip install -e .
EOF

echo "✅ Deployment complete!"
echo "🔍 Test with: ssh ${CHPC_USER}@${CHPC_HOST} 'cd ${CHPC_PROJECT_DIR} && python -c \"import brc_tools; print(\"Success\")\"'"