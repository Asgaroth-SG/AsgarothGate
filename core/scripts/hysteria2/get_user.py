#!/usr/bin/env python3

import init_paths
import json
import sys
import os
import getopt
from datetime import datetime
from bson.objectid import ObjectId
from db.database import db

def convert_datetime_to_str(obj):
    """
    Рекурсивно конвертирует объекты datetime и ObjectId в строки для JSON сериализации.
    """
    if isinstance(obj, datetime):
        # Конвертируем datetime в строку формата YYYY-MM-DD
        return obj.strftime("%Y-%m-%d")
    elif isinstance(obj, ObjectId):
        # Конвертируем ObjectId в строку
        return str(obj)
    elif isinstance(obj, dict):
        return {key: convert_datetime_to_str(value) for key, value in obj.items()}
    elif isinstance(obj, list):
        return [convert_datetime_to_str(item) for item in obj]
    else:
        return obj

def get_user_info(username):
    """
    Retrieves and prints information for a specific user from the database.

    Args:
        username (str): The username to look up.

    Returns:
        int: 0 on success, 1 on failure.
    """
    if db is None:
        print("Error: Database connection failed. Please ensure MongoDB is running.")
        return 1
        
    try:
        user_info = db.get_user(username)
        if user_info:
            # Конвертируем все datetime объекты в строки перед сериализацией
            user_info = convert_datetime_to_str(user_info)
            print(json.dumps(user_info, indent=4))
            return 0
        else:
            print(f"User '{username}' not found in the database.")
            return 1
    except Exception as e:
        print(f"An error occurred while fetching user data: {e}")
        return 1

if __name__ == "__main__":
    username = None
    try:
        opts, args = getopt.getopt(sys.argv[1:], "u:", ["username="])
    except getopt.GetoptError as err:
        print(str(err))
        print(f"Usage: {sys.argv[0]} -u <username>")
        sys.exit(1)

    for opt, arg in opts:
        if opt in ("-u", "--username"):
            username = arg.lower()

    if not username:
        print(f"Usage: {sys.argv[0]} -u <username>")
        sys.exit(1)

    exit_code = get_user_info(username)
    sys.exit(exit_code)