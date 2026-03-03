#!/usr/bin/env python3
"""Complete test of password authentication"""

import os
import sys
import sqlite3
import bcrypt
from dotenv import load_dotenv

load_dotenv()

PASSWORDS_DB = "auth_data/passwords.db"

# Load passwords from DB
def load_passwords():
    conn = sqlite3.connect(PASSWORDS_DB, timeout=10)
    c = conn.cursor()
    c.execute("SELECT password, usage_count, ip1, ip2 FROM passwords")
    passwords = {row[0]: {"usage_count": row[1], "ip1": row[2], "ip2": row[3]} for row in c.fetchall()}
    conn.close()
    return passwords

def test_auth(test_password):
    """Test authentication"""
    print(f"\n{'='*60}")
    print(f"Testing authentication with: {test_password}")
    print(f"{'='*60}")
    
    passwords = load_passwords()
    print(f"✓ Loaded {len(passwords)} password hashes from DB")
    
    input_pwd_bytes = test_password.encode('utf-8')
    
    for i, (hashed_pwd, data) in enumerate(passwords.items(), 1):
        try:
            hashed_pwd_bytes = hashed_pwd.encode('utf-8') if isinstance(hashed_pwd, str) else hashed_pwd
            
            result = bcrypt.checkpw(input_pwd_bytes, hashed_pwd_bytes)
            
            if result:
                print(f"\n✓ MATCH FOUND!")
                print(f"  Hash #{i}: {hashed_pwd[:60]}...")
                print(f"  Input: {test_password}")
                print(f"  Result: {result}")
                return True
        except Exception as e:
            print(f"\n✗ Hash #{i} error: {e}")
            continue
    
    print(f"\n✗ NO MATCH FOUND for {test_password}")
    return False

# Test with multiple passwords
test_passwords = ["spy11", "tsla79", "aapl06", "coin77"]

for pwd in test_passwords:
    test_auth(pwd)

print("\n" + "="*60)
print("Test complete")
