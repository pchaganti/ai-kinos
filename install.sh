#!/bin/bash

# Check for .env file
if [ ! -f .env ]; then
    echo "Error: .env file not found"
    echo "Please copy .env.example to .env and configure your API keys"
    exit 1
fi

# Check for required API keys
if ! grep -q "OPENAI_API_KEY=sk-" .env || ! grep -q "PERPLEXITY_API_KEY=pplx-" .env; then
    echo "Error: API keys not properly configured in .env"
    echo "Please ensure both OPENAI_API_KEY and PERPLEXITY_API_KEY are set"
    exit 1
fi

echo "✓ Environment configuration verified"

# Check for Cairo
if ! pkg-config --exists cairo; then
    echo "Warning: Cairo graphics library not found"
    echo "Please install Cairo:"
    echo "- Linux: sudo apt-get install libcairo2-dev pkg-config python3-dev"
    echo "- macOS: brew install cairo pkg-config"
fi

echo "🚀 Starting installation..."

# Update submodules
git submodule update --init --recursive
if [ $? -ne 0 ]; then
    echo "Error: Submodule update failed"
    exit 1
fi

# Install Python dependencies
pip install -r requirements.txt --user
if [ $? -ne 0 ]; then
    echo "Error: Python dependencies installation failed"
    exit 1
fi


# Install and build repo-visualizer
cd vendor/repo-visualizer
npm install --legacy-peer-deps
if [ $? -ne 0 ]; then
    echo "Error: repo-visualizer dependencies installation failed"
    exit 1
fi

npm install -g esbuild
if [ $? -ne 0 ]; then
    echo "Error: esbuild installation failed"
    exit 1
fi

mkdir -p dist
npm run build
if [ $? -ne 0 ]; then
    echo "Error: repo-visualizer build failed"
    exit 1
fi
cd ../..

# Create symbolic link for kin command
if [[ "$OSTYPE" == "darwin"* ]] || [[ "$OSTYPE" == "linux-gnu"* ]]; then
    sudo ln -sf "$(pwd)/kin" /usr/local/bin/kin
fi
