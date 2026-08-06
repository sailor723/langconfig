/**
 * Express API server for the Local Studio.
 *
 * Responsibilities:
 * 1. Serve the built React frontend (production mode).
 * 2. Proxy `/api/langgraph/*` to the local `langgraph dev` server,
 *    so the browser never talks to it directly (avoids CORS + mixed content).
 */
import express, { type Request, type Response } from 'express'
import cors from 'cors'
import http from 'http'
import https from 'https'
import path from 'path'
import fs from 'fs'
import dotenv from 'dotenv'
import { fileURLToPath } from 'url'

// for esm mode
const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)

// load env
dotenv.config()

// Upstream LangGraph API (the `langgraph dev` server)
const LANGGRAPH_API_URL = process.env.LANGGRAPH_API_URL || 'http://127.0.0.1:2024'

const app: express.Application = express()

app.use(cors())
app.use(express.json({ limit: '10mb' }))
app.use(express.urlencoded({ extended: true, limit: '10mb' }))

/**
 * Health check
 */
app.get('/api/health', (_req: Request, res: Response): void => {
  res.status(200).json({ success: true, message: 'ok' })
})

/**
 * LangGraph API proxy
 * Forward any /api/langgraph/* request to the langgraph dev server,
 * stripping the /api/langgraph mount prefix.
 *
 * Uses raw socket piping (Node http/https) instead of fetch() so SSE
 * responses (runs/stream) stream through byte-for-byte with correct
 * connection handling.
 */
app.use('/api/langgraph', (req: Request, res: Response) => {
  const upstreamUrl = new URL(`${LANGGRAPH_API_URL}${req.url}`)
  const lib = upstreamUrl.protocol === 'https:' ? https : http

  // Forwarded headers; hop-by-hop headers are managed by Node itself
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  if (req.headers.authorization) headers.Authorization = req.headers.authorization

  const upstreamReq = lib.request(
    upstreamUrl,
    { method: req.method, headers },
    (upstreamRes) => {
      // Hop-by-hop headers (transfer-encoding, connection, ...) are managed
      // by Node itself; forwarding them would corrupt the response framing.
      const HOP_BY_HOP = new Set([
        'transfer-encoding',
        'connection',
        'keep-alive',
        'upgrade',
        'proxy-connection',
        'te',
        'trailer',
        'proxy-authenticate',
        'proxy-authorization',
      ])
      const responseHeaders: Record<string, string> = {}
      for (const [key, value] of Object.entries(upstreamRes.headers)) {
        if (HOP_BY_HOP.has(key.toLowerCase())) continue
        if (value !== undefined) {
          responseHeaders[key] = Array.isArray(value) ? value.join(', ') : value
        }
      }
      res.writeHead(upstreamRes.statusCode ?? 500, responseHeaders)
      // Forward the upstream body manually with backpressure instead of
      // pipe(). If the upstream aborts mid-body (e.g. uvicorn closes the SSE
      // socket without a clean chunked terminator), pipe() would destroy the
      // client response; manual forwarding lets us end it cleanly instead.
      upstreamRes.on('data', (chunk) => {
        if (!res.write(chunk)) upstreamRes.pause()
      })
      res.on('drain', () => upstreamRes.resume())
      upstreamRes.on('end', () => {
        if (!res.writableEnded) res.end()
      })
      upstreamRes.on('aborted', () => {
        console.error('[langgraph proxy] upstream stream aborted mid-body; finishing client response')
        if (!res.writableEnded) res.end()
      })
      upstreamRes.on('error', (err) => {
        console.error('[langgraph proxy] upstream stream error:', err)
        if (!res.writableEnded) res.end()
      })
    },
  )

  upstreamReq.on('error', (err) => {
    console.error('[langgraph proxy] upstream request failed:', err)
    if (!res.headersSent) {
      res.status(502).json({
        success: false,
        error: `Cannot reach LangGraph dev server at ${LANGGRAPH_API_URL}. Is "langgraph dev" running?`,
      })
    } else {
      res.end()
    }
  })

  // Forward the parsed body only when the method supports one and the body
  // is non-empty. Writing a body to GETs makes Node emit
  // "Transfer-Encoding: chunked", which uvicorn/h11 rejects with a 400.
  const supportsBody = !['GET', 'HEAD', 'OPTIONS'].includes(req.method)
  const hasBody = req.body !== undefined && Object.keys(req.body).length > 0
  if (supportsBody && hasBody) {
    upstreamReq.write(JSON.stringify(req.body))
  }
  upstreamReq.end()
})

/**
 * Serve built frontend (production). Registered after API routes,
 * before the 404/error handlers, with an SPA fallback.
 */
const distPath = path.join(__dirname, '../dist')
if (fs.existsSync(distPath)) {
  app.use(express.static(distPath))
  app.get('*', (_req: Request, res: Response) => {
    res.sendFile(path.join(distPath, 'index.html'))
  })
}

/**
 * error handler middleware
 */
app.use((error: Error, _req: Request, res: Response) => {
  console.error('[api] unhandled error:', error)
  res.status(500).json({
    success: false,
    error: 'Server internal error',
  })
})

/**
 * 404 handler
 */
app.use((req: Request, res: Response) => {
  res.status(404).json({
    success: false,
    error: 'API not found',
  })
})

export default app
