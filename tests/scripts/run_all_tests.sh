#!/bin/bash
# Script to run all CurateAI tests

echo "🧪 Running CurateAI Test Suite..."
echo "=============================="

# Check if we are in the project root
if [ ! -f "pyproject.toml" ]; then
    echo "❌ Error: Please run this script from the project root."
    exit 1
fi

echo "📦 Running Unit Tests..."
pytest tests/unit/ -v

echo ""
echo "🔗 Running Integration Tests..."
pytest tests/integration/ -v

echo ""
echo "✅ Testing Complete."
