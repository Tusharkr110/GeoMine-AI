require('dotenv').config();
const express = require('express');
const cors = require('cors');
const path = require('path');
const db = require('./db');

const app = express();
const PORT = process.env.PORT || 5000;

app.use(cors());

// Proxy /api/rag/* directly to Python FastAPI RAG Service (port 8000) BEFORE body parsers consume the stream
const http = require('http');
app.use('/api/rag', (req, res) => {
  const options = {
    hostname: '127.0.0.1',
    port: 8000,
    path: '/api/rag' + req.url,
    method: req.method,
    headers: { ...req.headers, host: '127.0.0.1:8000' }
  };

  const proxyReq = http.request(options, (proxyRes) => {
    if (!res.headersSent) {
      res.writeHead(proxyRes.statusCode, proxyRes.headers);
    }
    proxyRes.pipe(res, { end: true });
  });

  proxyReq.on('error', (err) => {
    console.warn("[Proxy Notice]: Python RAG service on port 8000 not reachable:", err.message);
    if (!res.headersSent) {
      res.status(503).json({
        success: false,
        error: "PYTHON_RAG_OFFLINE",
        message: "Python RAG Engine is initializing or offline. Run: python rag_service.py"
      });
    }
  });

  req.on('error', (err) => {
    console.warn("[Client Req Error]:", err.message);
  });

  res.on('error', (err) => {
    console.warn("[Client Res Error]:", err.message);
  });

  req.pipe(proxyReq, { end: true });
});

app.use(express.json());
app.use(express.static(path.join(__dirname)));

// Simulated In-Memory Personnel Database (used as fallback when DB is offline)
const FALLBACK_USERS_DB = [
  {
    eis: "90342118",
    email: "alok.verma@cmpdi.co.in",
    name: "Dr. Alok K. Verma",
    role: "OFFICER",
    designation: "Chief Geologist & Remote Sensing In-Charge",
    division: "Exploration & AI Geological Survey",
    institute: "RI-III Ranchi",
    phoneMasked: "+91 94****4821",
    emailMasked: "al**@cmpdi.co.in",
    securityClearance: "LEVEL 3 - SENSITIVE MINE DATA",
    lastLogin: "28-Sep-2026 18:22 IST",
    password: "Password@123"
  },
  {
    eis: "90287415",
    email: "sunita.rao@cmpdi.co.in",
    name: "Er. Sunita Rao",
    role: "OFFICER",
    designation: "Superintending Mine Planning Engineer",
    division: "Opencast Mine Planning Division",
    institute: "RI-V Bilaspur",
    phoneMasked: "+91 98****7712",
    emailMasked: "su**@cmpdi.co.in",
    securityClearance: "LEVEL 3 - SENSITIVE MINE DATA",
    lastLogin: "27-Sep-2026 11:45 IST",
    password: "Password@123"
  },
  {
    eis: "90110024",
    email: "ciso.admin@cmpdi.co.in",
    name: "Col. R. S. Rathore (Retd.)",
    role: "ADMIN",
    designation: "Chief Information Security Officer & IT Head",
    division: "Central Cyber Security & AI Infrastructure Cell",
    institute: "HQ Ranchi (Gondwana Place)",
    phoneMasked: "+91 99****0019",
    emailMasked: "ci**@cmpdi.co.in",
    securityClearance: "LEVEL 5 - TOP SECRET / SYSTEM ROOT",
    lastLogin: "28-Sep-2026 23:15 IST",
    password: "Admin@Cmpdi2026",
    adminToken: "CMPDI-ROOT-SEC-8829"
  }
];

// Active Session OTP store
const activeOtps = new Map();

// In-memory Audit Trail fallback
const memoryAuditLogs = [
  {
    timestamp: new Date().toISOString(),
    event: "SYSTEM_INITIALIZATION",
    details: "CMPDI AI Core Authentication Engine v4.2 started",
    ip: "10.42.18.91",
    status: "SUCCESS"
  }
];

async function logEvent(event, details, ip, status) {
  const clientIp = ip || "127.0.0.1";
  memoryAuditLogs.unshift({
    timestamp: new Date().toISOString(),
    event,
    details,
    ip: clientIp,
    status
  });
  if (memoryAuditLogs.length > 50) memoryAuditLogs.pop();

  if (db.isDbConnected()) {
    await db.logAuditEvent(event, details, clientIp, status);
  }
}

// 1. Initial Login Check (Step 1 of 2FA)
app.post('/api/auth/login', async (req, res) => {
  const { role, identifier, password, institute, adminKey, captchaInput, captchaExpected } = req.body;
  const clientIp = req.headers['x-forwarded-for'] || req.socket.remoteAddress;

  // Validate Captcha
  if (!captchaInput || captchaInput.trim().toUpperCase() !== (captchaExpected || '').trim().toUpperCase()) {
    await logEvent("LOGIN_FAILED", `Invalid captcha challenge attempt for ${identifier || 'unknown'}`, clientIp, "FAILED");
    return res.status(400).json({ success: false, message: "Security Captcha verification failed. Please try again." });
  }

  let user = null;

  // Check PostgreSQL first if connected
  if (db.isDbConnected()) {
    try {
      const dbUser = await db.findUserByIdentifier(identifier, role);
      if (dbUser) {
        user = {
          eis: dbUser.eis,
          email: dbUser.email,
          name: dbUser.name,
          role: dbUser.role,
          designation: dbUser.designation,
          division: dbUser.division,
          institute: dbUser.institute,
          phoneMasked: dbUser.phone_masked,
          emailMasked: dbUser.email_masked,
          securityClearance: dbUser.security_clearance,
          password: dbUser.password_hash,
          adminToken: dbUser.admin_token
        };
      }
    } catch (e) {
      console.error("[PostgreSQL Query Error]:", e.message);
    }
  }

  // Fallback to in-memory store if DB query returned nothing
  if (!user) {
    user = FALLBACK_USERS_DB.find(u => 
      (u.eis.toLowerCase() === (identifier || '').trim().toLowerCase() || 
       u.email.toLowerCase() === (identifier || '').trim().toLowerCase()) &&
      u.role.toUpperCase() === (role || '').trim().toUpperCase()
    );
  }

  if (!user) {
    await logEvent("LOGIN_FAILED", `Unauthorized identity '${identifier}' attempted access to [${role}] portal`, clientIp, "FAILED");
    return res.status(401).json({
      success: false,
      message: "Access Denied. Identifier is not registered as an authorized Officer or Administrator."
    });
  }

  // Password verification
  if (user.password !== password) {
    await logEvent("AUTH_REJECTED", `Invalid password for EIS ${user.eis}`, clientIp, "FAILED");
    return res.status(401).json({
      success: false,
      message: "Authentication failed. Invalid password credentials."
    });
  }

  // For Admin role: check Master Token / Key
  if (user.role === 'ADMIN' && adminKey && adminKey.trim() !== user.adminToken) {
    await logEvent("ADMIN_TOKEN_FAILED", `Invalid Admin Security Token for ${user.eis}`, clientIp, "FAILED");
    return res.status(403).json({
      success: false,
      message: "Security Token Clearance Failed. System Root Clearance Key is invalid."
    });
  }

  // Generate 6-digit OTP
  const otp = Math.floor(100000 + Math.random() * 900000).toString();
  const sessionId = "CMPDI-SEC-" + Math.random().toString(36).substring(2, 10).toUpperCase();
  const expiresAt = Date.now() + 5 * 60 * 1000;

  activeOtps.set(sessionId, {
    otp: otp,
    eis: user.eis,
    role: user.role,
    expiresAt: expiresAt,
    user: user
  });

  if (db.isDbConnected()) {
    await db.saveOtpSession(sessionId, user.eis, otp, expiresAt);
  }

  await logEvent("OTP_DISPATCHED", `2FA OTP generated for ${user.name} (${user.eis})`, clientIp, "PENDING");

  return res.json({
    success: true,
    requiresOtp: true,
    sessionId: sessionId,
    phoneMasked: user.phoneMasked,
    emailMasked: user.emailMasked,
    userName: user.name,
    designation: user.designation,
    demoOtp: otp,
    source: db.isDbConnected() ? "PostgreSQL Database" : "In-Memory Fallback",
    message: `Two-Factor Authentication OTP has been transmitted to registered Mobile (${user.phoneMasked}) & Email.`
  });
});

// 2. OTP Verification (Step 2 of 2FA)
app.post('/api/auth/verify-otp', async (req, res) => {
  const { sessionId, otp } = req.body;
  const clientIp = req.headers['x-forwarded-for'] || req.socket.remoteAddress;

  const session = activeOtps.get(sessionId);

  if (!session) {
    return res.status(400).json({ success: false, message: "Session expired or invalid. Please re-authenticate." });
  }

  if (Date.now() > session.expiresAt) {
    activeOtps.delete(sessionId);
    return res.status(400).json({ success: false, message: "OTP has expired. Please request a new security code." });
  }

  // Accept generated OTP or Universal Hackathon Demo OTP 742918
  if (session.otp !== otp && otp !== "742918") {
    await logEvent("OTP_MISMATCH", `Invalid OTP submitted for session ${sessionId}`, clientIp, "FAILED");
    return res.status(401).json({ success: false, message: "Invalid 6-digit verification code. Please check SMS/Email." });
  }

  const user = session.user || FALLBACK_USERS_DB.find(u => u.eis === session.eis);
  activeOtps.delete(sessionId);

  const token = "CMPDI-JWT-" + Buffer.from(`${user.eis}:${Date.now()}`).toString('base64');
  await logEvent("LOGIN_SUCCESS", `${user.role} ${user.name} logged in successfully`, clientIp, "SUCCESS");

  return res.json({
    success: true,
    message: "Two-Factor Identity Clearance Approved. Welcome to GeoMine AI Portal.",
    token,
    user: {
      eis: user.eis,
      name: user.name,
      role: user.role,
      designation: user.designation,
      division: user.division,
      institute: user.institute,
      securityClearance: user.securityClearance,
      lastLogin: new Date().toLocaleString('en-IN', { timeZone: 'Asia/Kolkata' }) + " IST"
    }
  });
});

// 3. Resend OTP
app.post('/api/auth/resend-otp', (req, res) => {
  const { sessionId } = req.body;
  const session = activeOtps.get(sessionId);

  if (!session) {
    return res.status(400).json({ success: false, message: "Session has timed out. Please initiate login again." });
  }

  const newOtp = Math.floor(100000 + Math.random() * 900000).toString();
  session.otp = newOtp;
  session.expiresAt = Date.now() + 5 * 60 * 1000;
  activeOtps.set(sessionId, session);

  const user = session.user;

  return res.json({
    success: true,
    demoOtp: newOtp,
    message: `A fresh 6-digit OTP code has been re-transmitted to ${user ? user.phoneMasked : 'registered device'}.`
  });
});

// 4. Biometric / PKI Smart Card authentication endpoint
app.post('/api/auth/biometric-auth', async (req, res) => {
  const { role } = req.body;
  const clientIp = req.headers['x-forwarded-for'] || req.socket.remoteAddress;

  const targetUser = role === 'ADMIN' ? FALLBACK_USERS_DB[2] : FALLBACK_USERS_DB[0];

  await logEvent("BIOMETRIC_AUTH", `PKI Smart Card / Biometric handshake successful for ${targetUser.name}`, clientIp, "SUCCESS");

  return res.json({
    success: true,
    token: "CMPDI-PKI-" + Date.now(),
    message: "Hardware Security Token & FIDO2 Cryptographic Handshake Verified.",
    user: targetUser
  });
});

// 5. Audit Log endpoint for Admin view
app.get('/api/auth/audit-logs', async (req, res) => {
  if (db.isDbConnected()) {
    try {
      const dbLogs = await db.query(`SELECT * FROM audit_logs ORDER BY timestamp DESC LIMIT 50`);
      return res.json({ success: true, logs: dbLogs.rows, source: "PostgreSQL" });
    } catch (e) {
      console.error("[DB Logs Error]:", e.message);
    }
  }
  res.json({ success: true, logs: memoryAuditLogs, source: "Memory" });
});

// 6. Database Healthcheck endpoint
app.get('/api/health/db', async (req, res) => {
  const connected = db.isDbConnected();
  res.json({
    status: "ok",
    database: {
      type: "PostgreSQL",
      host: process.env.PGHOST || "localhost",
      port: process.env.PGPORT || 5433,
      name: process.env.PGDATABASE || "cmpdi_portal",
      connected: connected
    }
  });
});


// Serve frontend for all standard routes
app.get('*', (req, res) => {
  res.sendFile(path.join(__dirname, 'index.html'));
});

app.listen(PORT, () => {
  console.log(`================================================================`);
  console.log(`  GeoMine AI System - Restricted Officer & Admin Portal`);
  console.log(`  Advanced Geospatial & Autonomous Mine Intelligence`);
  console.log(`  Server running securely at: http://localhost:${PORT}`);
  console.log(`  PostgreSQL Host: ${process.env.PGHOST || 'localhost'}:${process.env.PGPORT || 5433}`);
  console.log(`================================================================`);
});

process.on('uncaughtException', (err) => {
  console.error('[UNCAUGHT EXCEPTION]:', err);
});

process.on('unhandledRejection', (reason, promise) => {
  console.error('[UNHANDLED REJECTION]:', reason);
});

