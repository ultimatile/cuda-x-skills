#!/bin/bash

# Workflow Simulation: "How do I use cuda::atomic?" (CCCL)

echo "--- 1. Agent Logic: Determine intent (CCCL source) ---"
KEYWORD="atomic"
SOURCE="cccl"
echo "🤖 Agent: User asked about cuda::atomic. Searching CCCL index for '$KEYWORD'..."

echo "--- 2. Call Smart Mapper (CCCL Mode) ---"
echo "🔍 Tool: topology_mapper.py --source cccl --keywords '$KEYWORD' --fuzzy"

# Use --fuzzy to get robust matches directly from Python
# The mapper now fetches objects.inv from CCCL docs
MAPPER_OUTPUT=$(uv run prototype/topology_mapper.py --source "$SOURCE" --keywords "$KEYWORD" --fuzzy --json)

echo "📄 Mapper Output (Top Candidate):"
echo "$MAPPER_OUTPUT" | jq '{total_found, filtered_count, best_match: .candidates[0]}'

# 3. Agent Logic: Select best candidate
CANDIDATE_COUNT=$(echo "$MAPPER_OUTPUT" | jq '.filtered_count')

if [ "$CANDIDATE_COUNT" -eq "0" ]; then
    echo "❌ No candidates found."
    exit 1
fi

TARGET_URL=$(echo "$MAPPER_OUTPUT" | jq -r '.candidates[0].url')
GROUP_NAME=$(echo "$MAPPER_OUTPUT" | jq -r '.candidates[0].group')

echo "🤖 Agent: Selected best match '$GROUP_NAME'"
echo "Target URL: $TARGET_URL"

echo "--- 3. Call Structure Extractor (Sphinx Mode) ---"
echo "⛏️  Tool: structure_extractor.py --url '$TARGET_URL'"

# structure_extractor auto-detects Sphinx HTML via dl.cpp tag
EXTRACTOR_OUTPUT=$(uv run prototype/structure_extractor.py --url "$TARGET_URL")

echo "--- 4. Agent Logic: Final Response Generation ---"
echo "📄 Extractor Output (First Item):"
echo "$EXTRACTOR_OUTPUT" | jq '.[0]' | head -n 20 

echo "🤖 Agent: I found the structured documentation for you!"
