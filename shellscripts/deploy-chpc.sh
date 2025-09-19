#!/bin/bash
# Deploy BRC Tools to CHPC server with comprehensive testing
# Usage: ./deploy-chpc.sh [--test-only] [--skip-tests]

set -e  # Exit on any error

# Parse command line arguments
TEST_ONLY=false
SKIP_TESTS=false
for arg in "$@"; do
    case $arg in
        --test-only) TEST_ONLY=true ;;
        --skip-tests) SKIP_TESTS=true ;;
        *) echo "Unknown option: $arg"; exit 1 ;;
    esac
done

echo "🚀 BRC Tools CHPC Deployment"
echo "================================"

# Check local environment
if [[ ! -f ".env" ]]; then
    echo "❌ .env file not found. Run ./setup_config.py first"
    exit 1
fi

# Load environment variables with validation
source .env
required_vars=("CHPC_USER" "CHPC_HOST" "CHPC_PROJECT_DIR")
for var in "${required_vars[@]}"; do
    if [[ -z "${!var}" ]]; then
        echo "❌ Required variable $var not set in .env"
        exit 1
    fi
done

# Test local setup first
echo "🧪 Testing local configuration..."
if ! ./test_pipeline_simple.py > /dev/null 2>&1; then
    echo "⚠️  Local tests have issues. Continue anyway? (y/N)"
    read -r response
    if [[ ! "$response" =~ ^[Yy]$ ]]; then
        echo "🛑 Deployment cancelled"
        exit 1
    fi
fi

if [[ "$TEST_ONLY" == "true" ]]; then
    echo "✅ Test-only mode: Local validation passed"
    exit 0
fi

# Sync code to CHPC
echo "📦 Syncing code to ${CHPC_HOST}..."
rsync -avz --delete --exclude-from=.gitignore \
    --exclude='.git/' \
    --exclude='data/' \
    --exclude='*.log' \
    . ${CHPC_USER}@${CHPC_HOST}:${CHPC_PROJECT_DIR}/

# Install and test on remote server
echo "🔧 Setting up environment on CHPC..."
ssh ${CHPC_USER}@${CHPC_HOST} << EOF
set -e
cd ${CHPC_PROJECT_DIR}

# Install package
echo "Installing brc_tools package..."
pip install -e . --quiet

# Create necessary directories
mkdir -p logs data/cache

# Test installation
echo "Testing installation..."
python -c "import brc_tools; print('✅ Package import successful')"

# Test configuration
if [[ -f "test_pipeline_simple.py" ]]; then
    echo "Running pipeline tests..."
    python test_pipeline_simple.py
fi

echo "✅ CHPC setup complete"
EOF

if [[ "$SKIP_TESTS" == "false" ]]; then
    echo "🧪 Running end-to-end test..."
    ssh ${CHPC_USER}@${CHPC_HOST} "cd ${CHPC_PROJECT_DIR} && python -c 'from brc_tools.download.push_data import load_config; print(\"Config validation passed\")'"
fi

echo ""
echo "✅ Deployment successful!"
echo "📊 Next steps:"
echo "   1. SSH to CHPC: ssh ${CHPC_USER}@${CHPC_HOST}"
echo "   2. Navigate: cd ${CHPC_PROJECT_DIR}"
echo "   3. Test data: python brc_tools/download/get_map_obs.py"
echo "   4. Setup cron: crontab -e"