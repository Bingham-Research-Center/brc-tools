# Claude Code Team Guide for BRC Tools

## Quick Start for New Team Members

1. **Install Claude Code** (if not already done)
2. **Open this repo** with Claude Code
3. **Read the main [CLAUDE.md](CLAUDE.md)** for project overview
4. **Your personal settings** go in `.claude/` (automatically ignored by git)

## Team Collaboration Rules

### Shared Files (everyone uses same version)
- `CLAUDE.md` - Main project guide
- `CLAUDE-INDEX.md` - Project navigation
- `pyproject.toml` - Dependencies and settings
- All code files

### Personal Files (your own copy, not shared)
- `.claude/` directory - Your Claude Code preferences
- `.env` files - Your API keys
- `~/.config/ubair-website/` - Your local config

## Getting Started

### 1. Set Up Environment
```bash
# Copy example environment file
cp .env.example .env

# Edit with your API keys
nano .env
```

### 2. Create Config Directory
```bash
mkdir -p ~/.config/ubair-website
echo "https://basinwx.com" > ~/.config/ubair-website/website_url
```

### 3. Test Your Setup
```python
from brc_tools.download.push_data import load_config
api_key, url = load_config()  # Should work without errors
```

## Common Tasks for Team Members

### Data Scientists/Students
- Focus on `in_progress/` for experiments
- Use existing functions in `brc_tools/`
- Ask for help with API integration

### Developers
- Edit core `brc_tools/` package
- Add tests in `tests/`
- Update documentation

### Server Admins
- Use `shellscripts/` for deployment
- Manage environment variables
- Monitor data pipeline

## Getting Help

1. **Read error messages carefully** - they usually explain the problem
2. **Check [WISHLIST-TASKS.md](WISHLIST-TASKS.md)** for known issues
3. **Ask team members** or post in team chat
4. **Claude Code docs**: Use `/help` command

## Best Practices

- **Test locally first** before deploying to servers
- **Keep API keys secret** - never commit them
- **Use meaningful commit messages**
- **Update CLAUDE.md** if you change how things work