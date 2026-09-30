/**
 * PostgreSQL Database Initialization Script for CMPDI Portal
 * Creates 'cmpdi_portal' database and applies schema & seed data.
 */

const fs = require('fs');
const path = require('path');
const readline = require('readline');
const { Client } = require('pg');
require('dotenv').config();

const PGHOST = process.env.PGHOST || 'localhost';
const PGPORT = parseInt(process.env.PGPORT, 10) || 5433; // Detected running on 5433
const PGUSER = process.env.PGUSER || 'postgres';
let PGPASSWORD = process.env.PGPASSWORD || '';
const TARGET_DB = process.env.PGDATABASE || 'cmpdi_portal';

async function promptPassword() {
  if (process.argv[2]) {
    return process.argv[2];
  }
  if (PGPASSWORD) {
    return PGPASSWORD;
  }

  const rl = readline.createInterface({
    input: process.stdin,
    output: process.stdout
  });

  return new Promise((resolve) => {
    rl.question(`Enter PostgreSQL password for user '${PGUSER}' on port ${PGPORT}: `, (ans) => {
      rl.close();
      resolve(ans.trim());
    });
  });
}

async function runSetup() {
  console.log('================================================================');
  console.log('  CMPDI Portal - Local PostgreSQL Database Setup Script');
  console.log(`  Target Host: ${PGHOST}:${PGPORT} | User: ${PGUSER}`);
  console.log('================================================================');

  PGPASSWORD = await promptPassword();

  // 1. Connect to default 'postgres' database to check/create target database
  const rootClient = new Client({
    host: PGHOST,
    port: PGPORT,
    user: PGUSER,
    password: PGPASSWORD,
    database: 'postgres'
  });

  try {
    await rootClient.connect();
    console.log(`[1/3] Connected to PostgreSQL root server.`);

    // Check if target database exists
    const checkDb = await rootClient.query(`SELECT 1 FROM pg_database WHERE datname = $1`, [TARGET_DB]);
    if (checkDb.rows.length === 0) {
      console.log(`Creating database '${TARGET_DB}'...`);
      await rootClient.query(`CREATE DATABASE "${TARGET_DB}"`);
      console.log(`Database '${TARGET_DB}' created successfully.`);
    } else {
      console.log(`Database '${TARGET_DB}' already exists.`);
    }
  } catch (err) {
    console.error(`\n❌ Could not connect to PostgreSQL on port ${PGPORT}:`);
    console.error(`   ${err.message}`);
    console.error(`\nPlease check your password and verify PostgreSQL is running.`);
    process.exit(1);
  } finally {
    await rootClient.end();
  }

  // 2. Connect to the 'cmpdi_portal' database and apply schema
  const dbClient = new Client({
    host: PGHOST,
    port: PGPORT,
    user: PGUSER,
    password: PGPASSWORD,
    database: TARGET_DB
  });

  try {
    await dbClient.connect();
    console.log(`[2/3] Connected to database '${TARGET_DB}'.`);

    const schemaPath = path.join(__dirname, 'schema.sql');
    const sql = fs.readFileSync(schemaPath, 'utf8');

    console.log(`Applying schema from schema.sql...`);
    await dbClient.query(sql);
    console.log(`[3/3] Schema and Seed Data applied successfully!`);

    // Verify created users
    const usersRes = await dbClient.query(`SELECT eis, name, role, designation FROM users ORDER BY role, id`);
    console.log(`\nVerified Registered Personnel in '${TARGET_DB}':`);
    console.table(usersRes.rows);

    // Save password to .env if not already present
    const envPath = path.join(__dirname, '.env');
    const envContent = `PGHOST=${PGHOST}\nPGPORT=${PGPORT}\nPGUSER=${PGUSER}\nPGPASSWORD=${PGPASSWORD}\nPGDATABASE=${TARGET_DB}\nPORT=5000\n`;
    fs.writeFileSync(envPath, envContent, 'utf8');
    console.log(`Saved credentials to .env file.`);

    console.log('\n================================================================');
    console.log('✅ PostgreSQL Database Setup Completed Successfully!');
    console.log('You can now run: npm start');
    console.log('================================================================');

  } catch (err) {
    console.error(`\n❌ Error applying schema to '${TARGET_DB}':`, err.message);
    process.exit(1);
  } finally {
    await dbClient.end();
  }
}

runSetup();
