import pymongo
from bson.objectid import ObjectId
from datetime import datetime
from typing import Optional, List, Dict, Any

class Database:
    def __init__(self, db_name="asgaroth_panel", collection_name="users"):
        try:
            self.client = pymongo.MongoClient("mongodb://localhost:27017/")
            self.db = self.client[db_name]
            self.collection = self.db[collection_name]
            self.xui_mapping_collection = self.db["xui_user_mapping"]
            self.client.server_info()
        except pymongo.errors.ConnectionFailure as e:
            print(f"Could not connect to MongoDB: {e}")
            raise

    def add_user(self, user_data):
        username = user_data.pop('username', None)
        if not username:
            raise ValueError("Username is required")

        if self.collection.find_one({"_id": username.lower()}):
            return None

        user_data['_id'] = username.lower()
        return self.collection.insert_one(user_data)

    def get_user(self, username):
        return self.collection.find_one({"_id": username.lower()})

    def get_all_users(self):
        return list(self.collection.find({}))

    def update_user(self, username, updates):
        return self.collection.update_one({"_id": username.lower()}, {"$set": updates})

    def delete_user(self, username):
        return self.collection.delete_one({"_id": username.lower()})

    def delete_users(self, usernames):
        return self.collection.delete_many({"_id": {"$in": usernames}})

    # X-UI Mapping methods
    def get_xui_mapping(self, hysteria_username: str) -> Optional[Dict[str, Any]]:
        """
        Получает маппинг пользователя Hysteria2 -> X-UI.
        
        Args:
            hysteria_username: Имя пользователя в Hysteria2
        
        Returns:
            Словарь с маппингом или None
        """
        return self.xui_mapping_collection.find_one({"_id": hysteria_username.lower()})

    def save_xui_mapping(
        self,
        hysteria_username: str,
        xui_client_uuid: str,
        inbound_ids: List[int],
        xui_host: Optional[str] = None,
        sync_status: str = "success",
        error_message: Optional[str] = None
    ) -> Any:
        """
        Сохраняет или обновляет маппинг пользователя.
        
        Args:
            hysteria_username: Имя пользователя в Hysteria2
            xui_client_uuid: UUID клиента в X-UI
            inbound_ids: Список ID inbounds, где добавлен клиент
            xui_host: Хост X-UI (для multi-xui режима)
            sync_status: Статус синхронизации (success, failed, pending)
            error_message: Сообщение об ошибке (если есть)
        
        Returns:
            Результат операции
        """
        mapping = {
            "_id": hysteria_username.lower(),
            "hysteria_username": hysteria_username,
            "xui_client_uuid": xui_client_uuid,
            "inbound_ids": inbound_ids,
            "xui_host": xui_host,
            "sync_status": sync_status,
            "error_message": error_message,
            "sync_at": datetime.utcnow(),
            "updated_at": datetime.utcnow()
        }
        
        existing = self.get_xui_mapping(hysteria_username)
        if existing:
            # Обновляем существующий
            mapping.pop("_id", None)  # Не обновляем _id
            return self.xui_mapping_collection.update_one(
                {"_id": hysteria_username.lower()},
                {"$set": mapping}
            )
        else:
            # Создаем новый
            return self.xui_mapping_collection.insert_one(mapping)

    def delete_xui_mapping(self, hysteria_username: str) -> Any:
        """
        Удаляет маппинг пользователя.
        
        Args:
            hysteria_username: Имя пользователя в Hysteria2
        
        Returns:
            Результат операции
        """
        return self.xui_mapping_collection.delete_one({"_id": hysteria_username.lower()})

    def get_all_xui_mappings(self) -> List[Dict[str, Any]]:
        """
        Получает все маппинги.
        
        Returns:
            Список всех маппингов
        """
        return list(self.xui_mapping_collection.find({}))

try:
    db = Database()
except pymongo.errors.ConnectionFailure:
    db = None