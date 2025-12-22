#!/bin/bash

# E2E Test Suite for Mapper-Miner Architecture
# Runs multiple scenarios for Core (CUDA Runtime) and CCCL (CUDA-X)

set -e

LOGFILE="prototype/e2e.log"
exec > >(tee -a "$LOGFILE") 2>&1

run_test() {
    local name="$1"
    local source="$2"
    local keywords="$3"
    
    echo "========================================================"
    echo "🧪 TEST CASE: $name"
    echo "   Source: $source | Keywords: $keywords"
    echo "========================================================"

    # 1. Mapper
    echo "🔍 Running Mapper..."
    MAPPER_START=$(date +%s%N)
    MAPPER_OUTPUT=$(uv run prototype/topology_mapper.py --source "$source" --keywords "${keywords}" --fuzzy --json)
    MAPPER_END=$(date +%s%N)
    MAPPER_DURATION=$(( (MAPPER_END - MAPPER_START) / 1000000 ))

    COUNT=$(echo "$MAPPER_OUTPUT" | jq '.filtered_count')
    echo "   Found $COUNT candidates in ${MAPPER_DURATION}ms"

    if [ "$COUNT" -eq "0" ]; then
        echo "❌ No candidates found!"
        return 1
    fi

    # Pick best match
    BEST_MATCH=$(echo "$MAPPER_OUTPUT" | jq '.candidates[0]')
    GROUP=$(echo "$BEST_MATCH" | jq -r '.group')
    URL=$(echo "$BEST_MATCH" | jq -r '.url')
    SCORE=$(echo "$BEST_MATCH" | jq -r '.score')

    echo "   Selected: $GROUP (Score: $SCORE)"
    echo "   URL: $URL"

    # 2. Extract
    echo "⛏️  Running Extractor..."
    EXTRACTOR_START=$(date +%s%N)
    EXTRACTOR_OUTPUT=$(uv run prototype/structure_extractor.py --url "$URL")
    EXTRACTOR_END=$(date +%s%N)
    EXTRACTOR_DURATION=$(( (EXTRACTOR_END - EXTRACTOR_START) / 1000000 ))

    ITEM_COUNT=$(echo "$EXTRACTOR_OUTPUT" | jq 'length')
    echo "   Extracted $ITEM_COUNT API items in ${EXTRACTOR_DURATION}ms"

    if [ "$ITEM_COUNT" -eq "0" ]; then
        echo "⚠️  Warning: No items extracted (might be an empty group or parsing issue)"
    else
        echo "   Sample Item:"
        echo "$EXTRACTOR_OUTPUT" | jq '.[0]' | sed 's/^/      /' | head -n 10
    fi
    echo ""
}

# --- Core Scenarios ---
run_test "Core: Memory Management" "cuda_runtime" "Memory Management"
run_test "Core: Event Management" "cuda_runtime" "Event Management"
run_test "Core: Stream Management" "cuda_runtime" "Stream"

# --- CCCL Scenarios ---
run_test "CCCL: Atomic" "cccl" "atomic"
run_test "CCCL: Barrier" "cccl" "barrier"
run_test "CCCL: Semaphore" "cccl" "semaphore"

echo "✅ All tests completed."
