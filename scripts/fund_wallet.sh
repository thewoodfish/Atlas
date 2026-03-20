#!/usr/bin/env bash
# fund_wallet.sh — Fund the WDK wallet on a local Anvil devnet
# Usage: ./scripts/fund_wallet.sh [wallet_address]
# Requires: cast (Foundry) and the WDK service running on :3001

set -e

ANVIL_RPC=${ANVIL_RPC:-http://localhost:8545}
WDK_URL=${WDK_URL:-http://localhost:3001}

# Anvil account #0 private key (well-known, devnet only)
ANVIL_KEY=0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80

# Tether Treasury — holds billions of USDT on mainnet fork
USDT_WHALE=0x47ac0Fb4F2D84898e4D9E7b4DaB3C24507a6D503
USDT_CONTRACT=0xdAC17F958D2ee523a2206206994597C13D831ec7

# Resolve wallet address from WDK service (or accept as argument)
if [ -n "$1" ]; then
  WALLET=$1
else
  echo "[fund] Fetching wallet address from WDK service..."
  WALLET=$(curl -sf "${WDK_URL}/wallet/address" | python3 -c "import sys,json; print(json.load(sys.stdin)['data']['address'])")
fi

echo "[fund] Wallet address : $WALLET"
echo "[fund] Anvil RPC      : $ANVIL_RPC"
echo ""

# 1. Send 0.1 ETH for gas
echo "[fund] Sending 0.1 ETH for gas..."
cast send \
  --value 0.1ether \
  "$WALLET" \
  --private-key "$ANVIL_KEY" \
  --rpc-url "$ANVIL_RPC" \
  --quiet
echo "[fund] ETH sent ✓"

# 2. Impersonate the USDT whale
echo "[fund] Impersonating USDT whale..."
cast rpc anvil_impersonateAccount "$USDT_WHALE" --rpc-url "$ANVIL_RPC" > /dev/null

# 3. Give the whale some ETH so it can pay gas
cast send \
  --value 0.01ether \
  "$USDT_WHALE" \
  --private-key "$ANVIL_KEY" \
  --rpc-url "$ANVIL_RPC" \
  --quiet

# 4. Transfer 50 USDT (50_000_000 units, 6 decimals)
echo "[fund] Sending 50 USDT..."
cast send "$USDT_CONTRACT" \
  "transfer(address,uint256)" \
  "$WALLET" 50000000 \
  --from "$USDT_WHALE" \
  --rpc-url "$ANVIL_RPC" \
  --unlocked \
  --quiet
echo "[fund] USDT sent ✓"

# 5. Stop impersonation
cast rpc anvil_stopImpersonatingAccount "$USDT_WHALE" --rpc-url "$ANVIL_RPC" > /dev/null

echo ""
echo "[fund] Verifying balances..."
curl -sf "${WDK_URL}/wallet/balance" | python3 -c "
import sys, json
d = json.load(sys.stdin)['data']
print(f\"  ETH  : {d['eth']}\")
print(f\"  USDT : {d['usdt']}\")
print(f\"  XAUT : {d['xaut']}\")
"
echo ""
echo "[fund] Wallet funded and ready."
