#!/usr/bin/env python3
"""Debug script to test password initialization"""

import os
import sqlite3
import bcrypt
from dotenv import load_dotenv

load_dotenv()

# Check environment variable
INITIAL_PASSWORDS_ENV = os.getenv("INITIAL_PASSWORDS", "")
print(f"✓ INITIAL_PASSWORDS length: {len(INITIAL_PASSWORDS_ENV)}")

# Parse passwords
if INITIAL_PASSWORDS_ENV:
    passwords_list = [pwd.strip() for pwd in INITIAL_PASSWORDS_ENV.split(",") if pwd.strip()]
    print(f"\n✓ Parsed {len(passwords_list)} passwords from environment variable")
else:
    print("\n✗ INITIAL_PASSWORDS is EMPTY!")
    passwords_list = []

# Test hashing
if "spy11" in passwords_list:
    test_pwd = "spy11"
    hashed = bcrypt.hashpw(test_pwd.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    print(f"\n✓ Test hash for 'spy11': {hashed[:50]}...")
    
    # Test verification
    is_valid = bcrypt.checkpw(test_pwd.encode('utf-8'), hashed.encode('utf-8'))
    print(f"✓ Verification result: {is_valid}")

# Check local database
PASSWORDS_DB = "auth_data/passwords.db"
if os.path.exists(PASSWORDS_DB):
    print(f"\n✓ Database exists: {PASSWORDS_DB}")
    try:
        conn = sqlite3.connect(PASSWORDS_DB)
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM passwords")
        count = c.fetchone()[0]
        print(f"✓ Passwords in DB: {count}")
        
        if count > 0:
            c.execute("SELECT password FROM passwords LIMIT 3")
            samples = c.fetchall()
            print(f"  Sample hashes: {[h[0][:50] + '...' for h in samples]}")
        
        conn.close()
    except Exception as e:
        print(f"✗ Error reading database: {e}")
else:
    print(f"\n✗ Database does NOT exist: {PASSWORDS_DB}")
    print("  This will be created on app startup")
