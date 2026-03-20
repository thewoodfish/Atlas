/**
 * Atlas WDK Wallet Service
 *
 * A lightweight Express REST API wrapping the Tether WDK for self-custodial
 * wallet operations. The Python orchestrator calls this service to perform
 * real onchain USDT / XAUT transactions.
 *
 * Endpoints
 * ---------
 * GET  /health              — liveness probe
 * GET  /wallet/address      — resolve EVM wallet address
 * GET  /wallet/balance      — USDT + XAUT + ETH balances
 * POST /wallet/send-usdt    — send USDT to a recipient
 * POST /wallet/send-xaut    — send XAUT (Tether Gold) to a recipient
 * POST /wallet/sign         — sign arbitrary message (EIP-191)
 * GET  /wallet/seed         — generate a new random seed phrase (dev only)
 */

import WDK from '@tetherto/wdk'
import WalletManagerEvm from '@tetherto/wdk-wallet-evm'
import { ethers } from 'ethers'
import express from 'express'

const PORT = process.env.WDK_SERVICE_PORT || 3001
const PROVIDER = process.env.EVM_PROVIDER || 'https://eth.drpc.org'

// USDT (ERC-20) on Ethereum mainnet
const USDT_ADDRESS  = '0xdAC17F958D2ee523a2206206994597C13D831ec7'
// XAUT (Tether Gold ERC-20) on Ethereum mainnet
const XAUT_ADDRESS  = '0x68749665FF8D2d112Fa859AA293F07A622782F38'

const ERC20_ABI_MINIMAL = [
  'function balanceOf(address owner) view returns (uint256)',
  'function decimals() view returns (uint8)',
  'function transfer(address to, uint256 amount) returns (bool)',
]

// ── WDK initialisation ────────────────────────────────────────────────────────

const SEED_PHRASE = process.env.WDK_SEED_PHRASE || WDK.getRandomSeedPhrase()

// Ethers provider for receipt polling (independent of WDK internals)
const provider = new ethers.JsonRpcProvider(PROVIDER)

// Wait for a tx to be confirmed (1 block, 30 s timeout). Returns receipt or null.
async function awaitConfirmation(txHash) {
  try {
    return await provider.waitForTransaction(txHash, 1, 30_000)
  } catch (_) {
    return null
  }
}

let wdk = null
let account = null
let walletAddress = null

async function initWallet() {
  console.log('[WDK] Initialising wallet...')
  wdk = new WDK(SEED_PHRASE).registerWallet('ethereum', WalletManagerEvm, {
    provider: PROVIDER,
  })

  account = await wdk.getAccount('ethereum', 0)
  walletAddress = await account.getAddress()
  console.log(`[WDK] Wallet ready  address=${walletAddress}`)
  if (!process.env.WDK_SEED_PHRASE) {
    console.warn('[WDK] No WDK_SEED_PHRASE set — using ephemeral seed (funds will be lost on restart!)')
    console.log(`[WDK] Ephemeral seed: ${SEED_PHRASE}`)
  }
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function ok(res, data) {
  return res.json({ success: true, data, ts: Date.now() })
}

function err(res, message, code = 500) {
  console.error(`[WDK] Error: ${message}`)
  return res.status(code).json({ success: false, error: message, ts: Date.now() })
}

function requireWallet(res) {
  if (!account) { err(res, 'Wallet not initialised', 503); return false }
  return true
}

// ── App ───────────────────────────────────────────────────────────────────────

const app = express()
app.use(express.json())

app.get('/health', (req, res) => {
  ok(res, { status: 'ok', address: walletAddress, provider: PROVIDER })
})

app.get('/wallet/seed', (req, res) => {
  if (process.env.NODE_ENV === 'production') {
    return err(res, 'Seed endpoint disabled in production', 403)
  }
  ok(res, { seed: WDK.getRandomSeedPhrase() })
})

app.get('/wallet/address', async (req, res) => {
  if (!requireWallet(res)) return
  try {
    ok(res, { address: walletAddress, chain: 'ethereum' })
  } catch (e) { err(res, e.message) }
})

app.get('/wallet/balance', async (req, res) => {
  if (!requireWallet(res)) return
  try {
    const ethBalance = await account.getBalance()

    // ERC-20 balances via WDK token support (falls back to zero if unavailable)
    let usdtBalance = '0'
    let xautBalance = '0'
    try {
      const usdtBal = await account.getTokenBalance(USDT_ADDRESS)
      usdtBalance = (Number(usdtBal) / 1e6).toFixed(6)   // USDT has 6 decimals
    } catch (_) {}
    try {
      const xautBal = await account.getTokenBalance(XAUT_ADDRESS)
      xautBalance = (Number(xautBal) / 1e6).toFixed(6)   // XAUT has 6 decimals
    } catch (_) {}

    ok(res, {
      address:  walletAddress,
      eth:      ethBalance.toString(),
      usdt:     usdtBalance,
      xaut:     xautBalance,
    })
  } catch (e) { err(res, e.message) }
})

app.post('/wallet/send-usdt', async (req, res) => {
  if (!requireWallet(res)) return
  const { to, amount, wait_confirmation = true } = req.body
  if (!to || !amount) return err(res, 'Missing required fields: to, amount', 400)
  try {
    console.log(`[WDK] Sending ${amount} USDT → ${to}`)
    const amountUnits = BigInt(Math.round(Number(amount) * 1e6))  // USDT 6 decimals
    const txHash = await account.sendToken(USDT_ADDRESS, to, amountUnits)
    console.log(`[WDK] USDT tx submitted  hash=${txHash}`)
    let status = 'pending'
    let blockNumber = null
    let gasUsed = null
    if (wait_confirmation) {
      const receipt = await awaitConfirmation(txHash)
      if (receipt) {
        status = receipt.status === 1 ? 'confirmed' : 'failed'
        blockNumber = receipt.blockNumber
        gasUsed = receipt.gasUsed?.toString()
        console.log(`[WDK] USDT tx ${status}  block=${blockNumber}  gas=${gasUsed}`)
      }
    }
    ok(res, { tx_hash: txHash, asset: 'USDT', amount, to, status, block_number: blockNumber, gas_used: gasUsed })
  } catch (e) { err(res, e.message) }
})

app.post('/wallet/send-xaut', async (req, res) => {
  if (!requireWallet(res)) return
  const { to, amount, wait_confirmation = true } = req.body
  if (!to || !amount) return err(res, 'Missing required fields: to, amount', 400)
  try {
    console.log(`[WDK] Sending ${amount} XAUT → ${to}`)
    const amountUnits = BigInt(Math.round(Number(amount) * 1e6))  // XAUT 6 decimals
    const txHash = await account.sendToken(XAUT_ADDRESS, to, amountUnits)
    console.log(`[WDK] XAUT tx submitted  hash=${txHash}`)
    let status = 'pending'
    let blockNumber = null
    let gasUsed = null
    if (wait_confirmation) {
      const receipt = await awaitConfirmation(txHash)
      if (receipt) {
        status = receipt.status === 1 ? 'confirmed' : 'failed'
        blockNumber = receipt.blockNumber
        gasUsed = receipt.gasUsed?.toString()
        console.log(`[WDK] XAUT tx ${status}  block=${blockNumber}  gas=${gasUsed}`)
      }
    }
    ok(res, { tx_hash: txHash, asset: 'XAUT', amount, to, status, block_number: blockNumber, gas_used: gasUsed })
  } catch (e) { err(res, e.message) }
})

app.post('/wallet/sign', async (req, res) => {
  if (!requireWallet(res)) return
  const { message } = req.body
  if (!message) return err(res, 'Missing required field: message', 400)
  try {
    const signature = await account.signMessage(message)
    ok(res, { signature, message, address: walletAddress })
  } catch (e) { err(res, e.message) }
})

// ── Start ─────────────────────────────────────────────────────────────────────

initWallet()
  .then(() => {
    app.listen(PORT, () => {
      console.log(`[WDK] Service listening on port ${PORT}`)
    })
  })
  .catch(e => {
    console.error('[WDK] Fatal init error:', e)
    process.exit(1)
  })
