-- =============================================================================
-- CMPDI AI-Based System - PostgreSQL Database Schema
-- Central Mine Planning & Design Institute Limited (Coal India Limited)
-- =============================================================================

-- 1. Create Users Table (Officers & Administrators Only)
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    eis VARCHAR(20) UNIQUE NOT NULL,
    email VARCHAR(100) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    name VARCHAR(120) NOT NULL,
    role VARCHAR(20) NOT NULL CHECK (role IN ('OFFICER', 'ADMIN')),
    designation VARCHAR(150) NOT NULL,
    division VARCHAR(150) NOT NULL,
    institute VARCHAR(100) NOT NULL,
    phone_masked VARCHAR(30) NOT NULL,
    email_masked VARCHAR(50) NOT NULL,
    security_clearance VARCHAR(50) NOT NULL,
    admin_token VARCHAR(100),
    is_active BOOLEAN DEFAULT TRUE,
    failed_attempts INT DEFAULT 0,
    lockout_until TIMESTAMP,
    last_login TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 2. Audit Trail & Security Logs Table
CREATE TABLE IF NOT EXISTS audit_logs (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    event VARCHAR(60) NOT NULL,
    details TEXT NOT NULL,
    ip_address VARCHAR(50) NOT NULL,
    status VARCHAR(20) NOT NULL
);

-- 3. Active 2FA Sessions & OTP Store
CREATE TABLE IF NOT EXISTS active_sessions (
    id SERIAL PRIMARY KEY,
    session_id VARCHAR(100) UNIQUE NOT NULL,
    eis VARCHAR(20) NOT NULL REFERENCES users(eis) ON DELETE CASCADE,
    otp VARCHAR(10) NOT NULL,
    expires_at TIMESTAMP NOT NULL,
    attempts INT DEFAULT 0,
    is_verified BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 4. CMPDI AI Autonomous Mining Telemetry
CREATE TABLE IF NOT EXISTS ai_telemetry (
    id SERIAL PRIMARY KEY,
    module_name VARCHAR(120) NOT NULL,
    model_version VARCHAR(50) NOT NULL,
    mine_field VARCHAR(100) NOT NULL,
    telemetry_status VARCHAR(50) NOT NULL,
    metric_name VARCHAR(50),
    metric_value VARCHAR(50),
    last_ping TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 5. Seed Initial CMPDI Officers & Admins
INSERT INTO users (
    eis, email, password_hash, name, role, designation, division, 
    institute, phone_masked, email_masked, security_clearance, admin_token
) VALUES 
(
    '90342118',
    'alok.verma@cmpdi.co.in',
    'Password@123',
    'Dr. Alok K. Verma',
    'OFFICER',
    'Chief Geologist & Remote Sensing In-Charge',
    'Exploration & AI Geological Survey',
    'RI-III Ranchi',
    '+91 94****4821',
    'al**@cmpdi.co.in',
    'LEVEL 3 - SENSITIVE MINE DATA',
    NULL
)
ON CONFLICT (eis) DO UPDATE 
SET password_hash = EXCLUDED.password_hash, name = EXCLUDED.name;

INSERT INTO users (
    eis, email, password_hash, name, role, designation, division, 
    institute, phone_masked, email_masked, security_clearance, admin_token
) VALUES 
(
    '90287415',
    'sunita.rao@cmpdi.co.in',
    'Password@123',
    'Er. Sunita Rao',
    'OFFICER',
    'Superintending Mine Planning Engineer',
    'Opencast Mine Planning Division',
    'RI-V Bilaspur',
    '+91 98****7712',
    'su**@cmpdi.co.in',
    'LEVEL 3 - SENSITIVE MINE DATA',
    NULL
)
ON CONFLICT (eis) DO UPDATE 
SET password_hash = EXCLUDED.password_hash, name = EXCLUDED.name;

INSERT INTO users (
    eis, email, password_hash, name, role, designation, division, 
    institute, phone_masked, email_masked, security_clearance, admin_token
) VALUES 
(
    '90110024',
    'ciso.admin@cmpdi.co.in',
    'Admin@Cmpdi2026',
    'Col. R. S. Rathore (Retd.)',
    'ADMIN',
    'Chief Information Security Officer & IT Head',
    'Central Cyber Security & AI Infrastructure Cell',
    'HQ Ranchi (Gondwana Place)',
    '+91 99****0019',
    'ci**@cmpdi.co.in',
    'LEVEL 5 - TOP SECRET / SYSTEM ROOT',
    'CMPDI-ROOT-SEC-8829'
)
ON CONFLICT (eis) DO UPDATE 
SET password_hash = EXCLUDED.password_hash, admin_token = EXCLUDED.admin_token;

-- 6. Seed Telemetry Modules
INSERT INTO ai_telemetry (module_name, model_version, mine_field, telemetry_status, metric_name, metric_value)
VALUES 
('Drone LiDAR 3D Coal Seam Volumetrics', 'GeoNet-V4.2', 'Jharia & Raniganj Basin', 'ACTIVE', 'Accuracy', '99.4%'),
('Opencast Blast Fragmentation Predictor', 'BlastAI-V2.1', 'Korba Coalfield', 'OPTIMIZING', 'Fragmentation Index', '94.2%'),
('Underground Toxic Gas & Strata Telemetry', 'StrataSafe-V3', 'Moonidih Underground Mine', 'NOMINAL', 'Methane CH4', '0.02%'),
('Satellite Land Reclamation Audit', 'SatVeg-NDVI', 'Singrauli OCP', 'TELEMETRY SYNCED', 'Vegetation Gain', '+14.6%');

-- 7. Initial System Audit Entry
INSERT INTO audit_logs (event, details, ip_address, status)
VALUES ('DB_INITIALIZED', 'PostgreSQL CMPDI schema and role partitions created successfully', '127.0.0.1', 'SUCCESS');
