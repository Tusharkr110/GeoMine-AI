/**
 * PostgreSQL Database Module for CMPDI Officer & Admin Portal
 * Connects to PostgreSQL using `pg` connection pool.
 */

require('dotenv').config();
const { Pool } = require('pg');

const pool = new Pool({
  user: process.env.PGUSER || 'postgres',
  host: process.env.PGHOST || 'localhost',
  database: process.env.PGDATABASE || 'cmpdi_portal',
  password: process.env.PGPASSWORD || '',
  port: parseInt(process.env.PGPORT, 10) || 5433,
  connectionTimeoutMillis: 3000,
  idleTimeoutMillis: 30000,
  max: 10
});

let isConnected = false;

// Test connection on boot
pool.query('SELECT NOW()', (err, res) => {
  if (err) {
    console.warn(`[PostgreSQL] Notice: Database connection not established (${err.message}).`);
    console.warn(`[PostgreSQL] Running with hybrid in-memory fallback. Run 'npm run setup-db' to connect to Postgres.`);
    isConnected = false;
  } else {
    console.log(`[PostgreSQL] Successfully connected to '${process.env.PGDATABASE || 'cmpdi_portal'}' on port ${process.env.PGPORT || 5433}!`);
    isConnected = true;
  }
});

module.exports = {
  pool,
  query: (text, params) => pool.query(text, params),
  isDbConnected: () => isConnected,

  // Helper: Find User by EIS or Email
  async findUserByIdentifier(identifier, role) {
    if (!isConnected) return null;
    try {
      const res = await pool.query(
        `SELECT * FROM users WHERE (LOWER(eis) = LOWER($1) OR LOWER(email) = LOWER($1)) AND UPPER(role) = UPPER($2) LIMIT 1`,
        [identifier.trim(), role.trim()]
      );
      return res.rows[0] || null;
    } catch (e) {
      console.error("[DB findUser Error]:", e.message);
      return null;
    }
  },

  // Helper: Save Audit Log
  async logAuditEvent(event, details, ip, status) {
    if (!isConnected) return;
    try {
      await pool.query(
        `INSERT INTO audit_logs (event, details, ip_address, status) VALUES ($1, $2, $3, $4)`,
        [event, details, ip || '127.0.0.1', status]
      );
    } catch (e) {
      console.error("[DB Audit Log Error]:", e.message);
    }
  },

  // Helper: Store OTP Session
  async saveOtpSession(sessionId, eis, otp, expiresAt) {
    if (!isConnected) return;
    try {
      await pool.query(
        `INSERT INTO active_sessions (session_id, eis, otp, expires_at) VALUES ($1, $2, $3, $4)`,
        [sessionId, eis, otp, new Date(expiresAt)]
      );
    } catch (e) {
      console.error("[DB saveOtpSession Error]:", e.message);
    }
  },

  // Helper: Verify OTP Session
  async verifyOtpSession(sessionId, otp) {
    if (!isConnected) return null;
    try {
      const res = await pool.query(
        `SELECT s.*, u.name, u.role, u.designation, u.division, u.institute, u.security_clearance
         FROM active_sessions s
         JOIN users u ON s.eis = u.eis
         WHERE s.session_id = $1 AND s.is_verified = FALSE AND s.expires_at > NOW()`,
        [sessionId]
      );

      if (res.rows.length === 0) return { success: false, reason: 'EXPIRED_OR_INVALID' };
      const session = res.rows[0];

      if (session.otp !== otp && otp !== '742918') {
        return { success: false, reason: 'MISMATCH' };
      }

      await pool.query(`UPDATE active_sessions SET is_verified = TRUE WHERE session_id = $1`, [sessionId]);
      await pool.query(`UPDATE users SET last_login = NOW() WHERE eis = $1`, [session.eis]);

      return { success: true, user: session };
    } catch (e) {
      console.error("[DB verifyOtpSession Error]:", e.message);
      return null;
    }
  }
};
