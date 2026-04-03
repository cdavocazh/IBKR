#!/bin/bash
# IB Gateway Health Check Script
# Usage: ./health_check.sh

echo "=== IB Gateway Health Check ==="
echo ""

# Check Docker container status
echo "--- Container Status ---"
docker compose -f ~/ib-gateway/docker-compose.yml ps
echo ""

# Check if API port is accepting connections
echo "--- API Port Check ---"
nc -z 127.0.0.1 4001 && echo "✅ Live API (4001): UP" || echo "❌ Live API (4001): DOWN"
nc -z 127.0.0.1 4002 && echo "✅ Paper API (4002): UP" || echo "❌ Paper API (4002): DOWN"
nc -z 127.0.0.1 5900 && echo "✅ VNC (5900): UP" || echo "❌ VNC (5900): DOWN"
echo ""

# Show last 10 log lines
echo "--- Recent Logs ---"
docker compose -f ~/ib-gateway/docker-compose.yml logs --tail 10
echo ""

# Memory usage
echo "--- Memory Usage ---"
docker stats --no-stream --format "table {{.Name}}\t{{.MemUsage}}\t{{.CPUPerc}}" | head -5
