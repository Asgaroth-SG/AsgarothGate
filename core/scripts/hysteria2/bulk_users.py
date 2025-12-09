#!/usr/bin/env python3

import init_paths
import sys
import os
import subprocess
import argparse
import re
from db.database import db

def add_bulk_users(traffic_gb, expiration_days, count, prefix, start_number,
                   unlimited_user, max_ips=0, plan="standard"):
    if db is None:
        print("Ошибка: Подключение к базе данных не удалось. Убедитесь, что MongoDB запущен.")
        return 1
        
    try:
        traffic_bytes = int(float(traffic_gb) * 1073741824)
    except ValueError:
        print("Ошибка: Лимит трафика должен быть числом.")
        return 1

    plan = (plan or "standard").lower()
    if plan not in ("standard", "premium"):
        print("Ошибка: plan должен быть 'standard' или 'premium'.")
        return 1

    potential_usernames = []
    for i in range(count):
        username = f"{prefix}{start_number + i}"
        if not re.match(r"^[a-zA-Z0-9_]+$", username):
            print(f"Ошибка: Сгенерированное имя пользователя '{username}' содержит недопустимые символы. Отмена.")
            return 1
        potential_usernames.append(username.lower())

    try:
        existing_docs = db.collection.find({"_id": {"$in": potential_usernames}}, {"_id": 1})
        existing_users_set = {doc['_id'] for doc in existing_docs}
    except Exception as e:
        print(f"Ошибка запроса к базе данных: {e}")
        return 1
        
    new_usernames = [u for u in potential_usernames if u not in existing_users_set]
    new_users_count = len(new_usernames)

    if new_users_count == 0:
        print("Нет новых пользователей для добавления. Все сгенерированные имена уже существуют.")
        return 0

    if count > new_users_count:
        print(f"Внимание: {count - new_users_count} пользователей уже существуют. Пропускаем их.")

    try:
        password_process = subprocess.run(['pwgen', '-s', '32', str(new_users_count)],
                                          capture_output=True, text=True, check=True)
        passwords = password_process.stdout.strip().split('\n')
    except (FileNotFoundError, subprocess.CalledProcessError):
        print("Внимание: 'pwgen' не найден или произошла ошибка. Используем UUID для генерации паролей.")
        passwords = [subprocess.check_output(['cat', '/proc/sys/kernel/random/uuid'],
                                             text=True).strip() for _ in range(new_users_count)]

    if len(passwords) < new_users_count:
        print("Ошибка: Не удалось сгенерировать достаточное количество паролей.")
        return 1

    users_to_insert = []
    for i, username in enumerate(new_usernames):
        user_doc = {
            "_id": username,
            "password": passwords[i],
            "max_download_bytes": traffic_bytes,
            "expiration_days": expiration_days,
            "blocked": False,
            "unlimited_user": unlimited_user,
            "status": "On-hold",
            "max_ips": int(max_ips),
            "plan": plan,
        }
        users_to_insert.append(user_doc)

    try:
        db.collection.insert_many(users_to_insert, ordered=False)
        print(f"\nУспешно добавлено {len(users_to_insert)} новых пользователей.")
        return 0
    except Exception as e:
        print(f"Произошла непредвиденная ошибка при добавлении в базу данных: {e}")
        return 1

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Add bulk users to Hysteria2 via database.")
    parser.add_argument("-t", "--traffic-gb", dest="traffic_gb", type=float, required=True,
                        help="Traffic limit for each user in GB.")
    parser.add_argument("-e", "--expiration-days", dest="expiration_days", type=int, required=True,
                        help="Expiration duration for each user in days.")
    parser.add_argument("-c", "--count", type=int, required=True,
                        help="Number of users to create.")
    parser.add_argument("-p", "--prefix", type=str, required=True,
                        help="Prefix for usernames.")
    parser.add_argument("-s", "--start-number", type=int, default=1,
                        help="Starting number for username suffix (default: 1).")
    parser.add_argument("-u", "--unlimited", action='store_true',
                        help="Flag to mark users as unlimited (exempt from IP limits).")
    parser.add_argument("--max-ips", type=int, default=0,
                        help="Max IP limit per user.")
    parser.add_argument(
        "--plan",
        choices=["standard", "premium"],
        default="standard",
        help="User plan/tier for all created users (standard or premium). Default: standard",
    )

    args = parser.parse_args()

    sys.exit(add_bulk_users(
        traffic_gb=args.traffic_gb,
        expiration_days=args.expiration_days,
        count=args.count,
        prefix=args.prefix,
        start_number=args.start_number,
        unlimited_user=args.unlimited,
        max_ips=args.max_ips,
        plan=args.plan,
    ))
