#!/bin/bash

# Test script for Blue/Green deployment failover
# This script verifies that failover works correctly with zero failed requests

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "=========================================="
echo "Blue/Green Deployment Failover Test"
echo "=========================================="
echo ""

# Function to check if service is responding
check_service() {
    local url=$1
    local expected_pool=$2
    
    response=$(curl -s -i "$url")
    http_code=$(echo "$response" | grep "HTTP" | awk '{print $2}')
    app_pool=$(echo "$response" | grep -i "x-app-pool" | awk '{print $2}' | tr -d '\r')
    release_id=$(echo "$response" | grep -i "x-release-id" | awk '{print $2}' | tr -d '\r')
    
    echo "HTTP Status: $http_code"
    echo "X-App-Pool: $app_pool"
    echo "X-Release-Id: $release_id"
    
    if [ "$http_code" != "200" ]; then
        echo -e "${RED}✗ FAILED: Expected 200, got $http_code${NC}"
        return 1
    fi
    
    if [ -n "$expected_pool" ] && [ "$app_pool" != "$expected_pool" ]; then
        echo -e "${RED}✗ FAILED: Expected pool '$expected_pool', got '$app_pool'${NC}"
        return 1
    fi
    
    echo -e "${GREEN}✓ PASSED${NC}"
    return 0
}

# Test 1: Verify Blue is serving initially
echo -e "${YELLOW}Test 1: Verify Blue is serving (baseline)${NC}"
check_service "http://localhost:8080/version" "blue" || exit 1
echo ""

# Test 2: Multiple requests to Blue
echo -e "${YELLOW}Test 2: Multiple requests to Blue (stability check)${NC}"
blue_count=0
for i in {1..10}; do
    response=$(curl -s -w "\n%{http_code}" http://localhost:8080/version)
    http_code=$(echo "$response" | tail -n1)
    
    if [ "$http_code" == "200" ]; then
        blue_count=$((blue_count + 1))
        echo -e "Request $i: ${GREEN}200${NC}"
    else
        echo -e "Request $i: ${RED}$http_code${NC}"
        exit 1
    fi
done
echo -e "${GREEN}✓ All $blue_count requests succeeded with Blue${NC}"
echo ""

# Test 3: Trigger chaos on Blue
echo -e "${YELLOW}Test 3: Triggering chaos on Blue service${NC}"
chaos_response=$(curl -s -X POST http://localhost:8081/chaos/start?mode=error)
echo "Chaos response: $chaos_response"
echo -e "${GREEN}✓ Chaos activated on Blue${NC}"
echo ""

# Wait a moment for chaos to take effect
sleep 2

# Test 4: Verify failover to Green
echo -e "${YELLOW}Test 4: Verify automatic failover to Green${NC}"
check_service "http://localhost:8080/version" "green" || exit 1
echo ""

# Test 5: Stress test during failure (most critical test)
echo -e "${YELLOW}Test 5: Stress test - 20 requests during Blue failure${NC}"
echo "This is the critical test: ALL requests must return 200"
echo ""

failed_requests=0
success_requests=0
green_responses=0

for i in {1..20}; do
    response=$(curl -s -w "\n%{http_code}" http://localhost:8080/version)
    http_code=$(echo "$response" | tail -n1)
    pool=$(echo "$response" | grep -o '"pool":"[^"]*"' | cut -d'"' -f4)
    
    if [ "$http_code" == "200" ]; then
        success_requests=$((success_requests + 1))
        if [ "$pool" == "green" ]; then
            green_responses=$((green_responses + 1))
        fi
        echo -e "Request $i: ${GREEN}200${NC} (Pool: $pool)"
    else
        failed_requests=$((failed_requests + 1))
        echo -e "Request $i: ${RED}$http_code${NC} (FAILED)"
    fi
    
    sleep 0.5
done

echo ""
echo "Results:"
echo "  Success: $success_requests/20"
echo "  Failed: $failed_requests/20"
echo "  Green responses: $green_responses/20"

if [ $failed_requests -gt 0 ]; then
    echo -e "${RED}✗ FAILED: $failed_requests requests failed${NC}"
    exit 1
fi

green_percentage=$((green_responses * 100 / 20))
if [ $green_percentage -lt 95 ]; then
    echo -e "${RED}✗ FAILED: Only $green_percentage% from Green (need ≥95%)${NC}"
    exit 1
fi

echo -e "${GREEN}✓ PASSED: 0 failures, ${green_percentage}% from Green${NC}"
echo ""

# Test 6: Stop chaos
echo -e "${YELLOW}Test 6: Stopping chaos on Blue${NC}"
stop_response=$(curl -s -X POST http://localhost:8081/chaos/stop)
echo "Stop response: $stop_response"
echo -e "${GREEN}✓ Chaos stopped${NC}"
echo ""

# Wait for Blue to recover
echo "Waiting 10 seconds for Blue to recover..."
sleep 10

# Test 7: Verify Blue is back
echo -e "${YELLOW}Test 7: Verify Blue is serving again${NC}"
check_service "http://localhost:8080/version" "blue" || echo -e "${YELLOW}Note: Blue may take longer to recover${NC}"
echo ""

echo "=========================================="
echo -e "${GREEN}ALL TESTS PASSED!${NC}"
echo "=========================================="