# Cross-Repository Integration Guide

## Repository Architecture

### Primary Repositories
- **`brc-tools`** (this repo) - Data collection and processing on CHPC
- **`ubair-website`** - Web display and API endpoints hosted on Akamai/Linode

### Data Flow Between Repos
```
brc-tools (CHPC) → HTTP API → ubair-website (Akamai) → Browser Display
```

## Integration Strategy

### 1. API Contract Definition
Both repos should share API specifications:

**In `brc-tools/data/schema/`:**
```
api-contract.json          # Shared API specification
weather-data-schema.json   # Weather data format
aviation-data-schema.json  # Aviation data format
```

**In `ubair-website/api/schemas/`:**
```
incoming-data.json         # Mirror of brc-tools schemas
validation-rules.json      # Server-side validation
```

### 2. Testing Cross-Repo Integration

**From `brc-tools` side:**
```bash
# Test data upload to website
pytest tests/integration/test_website_api.py

# Mock website responses for development
pytest tests/integration/test_with_mock_server.py
```

**From `ubair-website` side:**
```bash
# Test API endpoints accept brc-tools data
npm test api/data-upload.test.js

# Validate incoming data format
npm test validation/data-schemas.test.js
```

### 3. Shared Configuration

**Environment Variables (both repos):**
```bash
# Data Pipeline
DATA_UPLOAD_API_KEY=shared_64_char_key
WEBSITE_BASE_URL=https://basinwx.com

# API Endpoints
HEALTH_CHECK_ENDPOINT=/api/data/health
UPLOAD_ENDPOINT=/api/data/upload
```

### 4. Claude Code Coordination

**Option A: Separate Claude Instances**
- Each repo has its own CLAUDE.md
- Cross-reference between repos in documentation
- Use consistent naming and patterns

**Option B: Shared Claude Context**
- Clone both repos in same parent directory
- Claude can see both codebases simultaneously
- Unified development and testing

### 5. Deployment Coordination

**Staging Environment:**
```bash
# Deploy both repos to staging
./deploy-staging-brc-tools.sh
./deploy-staging-website.sh

# Test integration
./test-staging-integration.sh
```

**Production Deployment:**
1. Deploy website changes first
2. Test API compatibility
3. Deploy brc-tools changes
4. Verify end-to-end flow

## Development Workflow

### New Feature Development
1. **Design Phase**: Update API contracts in both repos
2. **Implementation**: Develop in parallel with mocked endpoints
3. **Integration Testing**: Test against real APIs in staging
4. **Deployment**: Coordinated release to production

### Bug Fixes
1. **Identify Source**: Data generation (brc-tools) vs display (website)
2. **Test Isolation**: Reproduce with minimal test case
3. **Fix and Verify**: Test both directions of data flow

### Schema Changes
1. **Backward Compatibility**: Ensure old data still works
2. **Versioned APIs**: Support multiple schema versions
3. **Migration Path**: Clear upgrade procedures

## Monitoring Integration

### Health Checks
- `brc-tools` checks website health before uploads
- Website monitors data freshness and quality
- Automated alerts for integration failures

### Logging Coordination
```bash
# Shared request ID for tracing
X-Request-ID: brc-tools-upload-20250918-1800

# Correlated logs across systems
[brc-tools] INFO: Uploading data with ID abc123
[website]   INFO: Received data with ID abc123
```

## Claude Code Best Practices

### For Multi-Repo Development
1. **Consistent Patterns**: Use same coding conventions
2. **Shared Documentation**: Cross-reference between repos
3. **API-First Design**: Define contracts before implementation
4. **Testing Strategy**: Mock external dependencies

### When to Use Multiple Claude Instances
- **Large feature changes** spanning both repos
- **Independent bug fixes** in single repo
- **Different team members** working separately

### When to Use Single Claude Instance
- **API contract changes** affecting both repos
- **End-to-end feature development**
- **Debugging integration issues**

## Getting Started

### Option 1: Clone Both Repos (Recommended)
```bash
mkdir basin-wx-development
cd basin-wx-development
git clone https://github.com/your-org/brc-tools.git
git clone https://github.com/your-org/ubair-website.git

# Claude can see both repositories
cd brc-tools
# Tell Claude about the sibling repo
```

### Option 2: Coordinate Via Documentation
```bash
# In brc-tools
echo "Sister repo: ../ubair-website" >> CLAUDE.md
echo "API docs: data/schema/api-contract.json" >> CLAUDE.md

# In ubair-website
echo "Data source: ../brc-tools" >> README.md
echo "Incoming schemas: api/schemas/" >> README.md
```

This integration strategy ensures smooth coordination between your data pipeline and web display systems.