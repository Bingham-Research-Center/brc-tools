#!/usr/bin/env python3
"""
Setup configuration for BRC Tools.

This script helps team members set up their environment consistently.
Run this once after cloning the repository.
"""
import os
import shutil
from pathlib import Path


def setup_env_file():
    """Create .env file from example if it doesn't exist."""
    env_file = Path('.env')
    example_file = Path('.env.example')

    if env_file.exists():
        print(f"✅ .env file already exists")
        return True

    if not example_file.exists():
        print(f"❌ .env.example not found")
        return False

    shutil.copy(example_file, env_file)
    print(f"✅ Created .env file from example")
    print(f"📝 Edit .env to add your actual API keys")
    return True


def setup_config_dirs():
    """Create necessary config directories."""
    # For website uploads (weather data)
    ubair_config = Path.home() / '.config' / 'ubair-website'
    ubair_config.mkdir(parents=True, exist_ok=True)

    # For aviation data (if needed)
    brc_config = Path.home() / '.config' / 'brc-tools'
    brc_config.mkdir(parents=True, exist_ok=True)

    print(f"✅ Created config directories:")
    print(f"   {ubair_config}")
    print(f"   {brc_config}")

    return ubair_config, brc_config


def setup_website_url(ubair_config):
    """Set up website URL file."""
    url_file = ubair_config / 'website_url'

    if url_file.exists():
        current_url = url_file.read_text().strip()
        print(f"✅ Website URL already configured: {current_url}")
        return

    # Default to BasinWX
    default_url = "https://basinwx.com"
    url_file.write_text(default_url)
    print(f"✅ Set default website URL: {default_url}")
    print(f"📝 Edit {url_file} if you need a different URL")


def check_dependencies():
    """Check if required packages are installed."""
    try:
        import brc_tools
        print("✅ brc_tools package installed")
    except ImportError:
        print("❌ brc_tools not installed. Run: pip install -e .")
        return False

    try:
        import requests
        print("✅ requests package available")
    except ImportError:
        print("❌ requests not installed. Run: pip install requests")
        return False

    return True


def main():
    """Set up BRC Tools configuration."""
    print("🔧 BRC Tools Configuration Setup")
    print("=" * 50)

    # Check we're in the right directory
    if not Path('brc_tools').exists():
        print("❌ Run this script from the brc-tools repository root")
        return False

    success = True

    print("\n1. Setting up environment file...")
    success &= setup_env_file()

    print("\n2. Creating config directories...")
    ubair_config, brc_config = setup_config_dirs()

    print("\n3. Setting up website URL...")
    setup_website_url(ubair_config)

    print("\n4. Checking dependencies...")
    success &= check_dependencies()

    print("\n" + "=" * 50)
    if success:
        print("🎉 Configuration setup complete!")
        print("\n📋 Next steps:")
        print("   1. Edit .env with your actual API keys")
        print("   2. Run: ./test_pipeline_simple.py")
        print("   3. If tests pass, enable uploads in get_map_obs.py")
    else:
        print("⚠️  Setup incomplete. Please address the issues above.")

    print(f"\n💡 See CLAUDE-TEAM-GUIDE.md for more details")
    return success


if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)