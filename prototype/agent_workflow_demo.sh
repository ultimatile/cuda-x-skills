#!/bin/bash

# Workflow Simulation: "How do I use cudaMalloc?"

echo "--- 1. Agent Logic: Determine intent ---"
KEYWORD="Memory"
echo "🤖 Agent: User asked about cudaMalloc. I want to search for topics related to '$KEYWORD'."

echo "--- 2. Call Smart Mapper (Fuzzy Mode with rapidfuzz) ---"
echo "🔍 Tool: topology_mapper.py --keywords '$KEYWORD' --fuzzy"

# Use --fuzzy to get robust matches directly from Python
# We assume the First match is the best due to scoring sort
MAPPER_OUTPUT=$(uv run prototype/topology_mapper.py --keywords "$KEYWORD" --fuzzy --json)

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
SCORE=$(echo "$MAPPER_OUTPUT" | jq -r '.candidates[0].score')

echo "🤖 Agent: Selected best match '$GROUP_NAME' (Score: $SCORE)"
echo "Target URL: $TARGET_URL"

echo "--- 3. Call Structure Extractor ---"
echo "⛏️  Tool: structure_extractor.py --url '$TARGET_URL'"

# Prototyping hack: use local file if network is flaky
if [[ "$TARGET_URL" == *"group__CUDART__MEMORY"* ]]; then
  TARGET_SOURCE="prototype/test_docs.html" # Use local file for robust demo
  # TARGET_SOURCE="$TARGET_URL" # Unleash to use real URL
else
  TARGET_SOURCE="$TARGET_URL"
fi

EXTRACTOR_OUTPUT=$(uv run prototype/structure_extractor.py --url "$TARGET_SOURCE")

echo "--- 4. Agent Logic: Final Response Generation ---"
echo "📄 Extractor Output (First Item):"
echo "$EXTRACTOR_OUTPUT" | jq '.[0]' | head -n 20 

echo "🤖 Agent: I found the structured documentation for you!"
