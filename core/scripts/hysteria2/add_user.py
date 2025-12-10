#!/usr/bin/env python3

import init_paths
import sys
import os
import subprocess
import re
import argparse
from datetime import datetime
from db.database import db

def add_user(
    username,
    traffic_gb,
    expiration_days,
    password=None,
    unlimited_user=False,
    note=None,
    creation_date=None,
    max_ips=0,
    plan="standard",  # новый параметр тарифа
):
    if db is None:
        print("Error: Database connection failed. Please ensure MongoDB is running and configured.")
        return 1

    username_lower = username.lower()

    if not password:
        try:
            password_process = subprocess.run(['pwgen', '-s', '32', '1'], capture_output=True, text=True, check=True)
            password = password_process.stdout.strip()
        except FileNotFoundError:
            try:
                password = subprocess.check_output(['cat', '/proc/sys/kernel/random/uuid'], text=True).strip()
            except Exception:
                print("Error: Failed to generate password. Please install 'pwgen' or ensure /proc access.")
                return 1

    if not re.match(r"^[a-zA-Z0-9_]+$", username):
        print("Error: Username can only contain letters, numbers, and underscores.")
        return 1

    try:
        traffic_bytes = int(float(traffic_gb) * 1073741824)
        expiration_days = int(expiration_days)
        max_ips = int(max_ips)
    except ValueError:
        print("Error: Numeric fields must be valid numbers.")
        return 1

    try:
        if db.get_user(username_lower):
            print("User already exists.")
            return 1

        user_data = {
            "username": username_lower,
            "password": password,
            "max_download_bytes": traffic_bytes,
            "expiration_days": expiration_days,
            "blocked": False,
            "unlimited_user": unlimited_user,
            "status": "On-hold",
            "max_ips": max_ips,
            # тариф пользователя
            "plan": plan or "standard",
        }
        
        if note:
            user_data["note"] = note
            
        if creation_date:
            if not re.match(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$", creation_date):
                print("Invalid date format. Expected YYYY-MM-DD.")
                return 1
            try:
                datetime.strptime(creation_date, "%Y-%m-%d")
                user_data["account_creation_date"] = creation_date
            except ValueError:
                print("Invalid date. Please provide a valid date in YYYY-MM-DD format.")
                return 1

        result = db.add_user(user_data)
        if result:
            print(f"User {username} added successfully.")
            return 0
        else:
            print(f"Error: Failed to add user {username}.")
            return 1

    except Exception as e:
        print(f"An error occurred: {e}")
        return 1

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Add a new user.")
    parser.add_argument("-u", "--username", required=True)
    parser.add_argument("-t", "--traffic-limit", required=True)
    parser.add_argument("-e", "--expiration-days", required=True)
    parser.add_argument("-p", "--password", default=None)
    parser.add_argument("--unlimited", action='store_true')
    parser.add_argument("-n", "--note", default=None)
    parser.add_argument("-c", "--creation-date", default=None)
    parser.add_argument("--max-ips", default=0, type=int)  # Новый аргумент
    # Новый CLI-аргумент тарифа
    parser.add_argument(
        "--plan",
        default="standard",
        choices=["standard", "premium"],
        help="User plan (standard or premium). Default: standard.",
    )

    args = parser.parse_args()

    exit_code = add_user(
        args.username,
        args.traffic_limit,
        args.expiration_days,
        args.password,
        args.unlimited,
        args.note,
        args.creation_date,
        args.max_ips,
        args.plan,
    )
    sys.exit(exit_code)
