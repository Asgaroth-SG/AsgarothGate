import pymongo
from bson.objectid import ObjectId
from datetime import datetime
from typing import Optional, List, Dict, Any, Tuple

class Database:
    def __init__(self, db_name="asgaroth_panel", collection_name="users"):
        try:
            # Настраиваем connection pooling для оптимизации производительности
            self.client = pymongo.MongoClient(
                "mongodb://localhost:27017/",
                maxPoolSize=50,  # Максимальный размер пула соединений
                minPoolSize=10,  # Минимальный размер пула (поддерживается постоянно)
                maxIdleTimeMS=30000,  # Время простоя перед закрытием соединения (30 сек)
                serverSelectionTimeoutMS=5000,  # Таймаут выбора сервера (5 сек)
                connectTimeoutMS=10000,  # Таймаут подключения (10 сек)
                socketTimeoutMS=30000,  # Таймаут операций (30 сек)
            )
            self.db = self.client[db_name]
            self.collection = self.db[collection_name]
            self.xui_mapping_collection = self.db["xui_user_mapping"]
            self.client.server_info()
            
            # Создаем индексы для оптимизации запросов
            self._create_indexes()
        except pymongo.errors.ConnectionFailure as e:
            print(f"Could not connect to MongoDB: {e}")
            raise
    
    def _create_indexes(self):
        """
        Создает индексы для оптимизации запросов к БД.
        Вызывается при инициализации соединения.
        """
        try:
            # Индекс для поиска по password (используется в get_username_by_password)
            if "password_1" not in self.collection.index_information():
                self.collection.create_index("password", name="password_1", background=True)
                print("Created index on 'password' field")
            
            # Индекс для поиска по xui_client_uuid (может использоваться в будущем)
            if "xui_client_uuid_1" not in self.xui_mapping_collection.index_information():
                self.xui_mapping_collection.create_index("xui_client_uuid", name="xui_client_uuid_1", background=True)
                print("Created index on 'xui_client_uuid' field")
            
            # Индекс для поиска по xui_host (для multi-xui режима)
            if "xui_host_1" not in self.xui_mapping_collection.index_information():
                self.xui_mapping_collection.create_index("xui_host", name="xui_host_1", background=True)
                print("Created index on 'xui_host' field")
        except Exception as e:
            # Не критично, если индексы уже существуют или произошла ошибка
            print(f"Warning: Failed to create indexes: {e}")

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
    
    def get_users_paginated(self, skip: int = 0, limit: int = 50, sort_field: str = "_id", sort_direction: int = 1) -> Tuple[List[Dict[str, Any]], int]:
        """
        Получает пользователей с пагинацией на уровне БД.
        
        Args:
            skip: Количество записей для пропуска
            limit: Максимальное количество записей для возврата
            sort_field: Поле для сортировки (по умолчанию _id)
            sort_direction: Направление сортировки (1 - по возрастанию, -1 - по убыванию)
        
        Returns:
            Tuple (список пользователей, общее количество пользователей)
        """
        try:
            # Получаем общее количество пользователей
            total_count = self.collection.count_documents({})
            
            # Получаем пользователей с пагинацией
            users = list(
                self.collection.find({})
                .sort(sort_field, sort_direction)
                .skip(skip)
                .limit(limit)
            )
            
            return users, total_count
        except Exception as e:
            print(f"Error getting paginated users: {e}")
            return [], 0
    
    def get_users_mappings_batch(self, usernames: List[str]) -> Dict[str, Dict[str, Any]]:
        """
        Получает маппинги для нескольких пользователей одним запросом (батчинг).
        
        Args:
            usernames: Список имен пользователей
        
        Returns:
            Словарь {username: mapping} для пользователей с маппингами
        """
        try:
            usernames_lower = [u.lower() for u in usernames]
            mappings = list(
                self.xui_mapping_collection.find(
                    {"_id": {"$in": usernames_lower}}
                )
            )
            
            # Преобразуем в словарь {username: mapping}
            result = {}
            for mapping in mappings:
                username = mapping.get('hysteria_username') or mapping.get('_id')
                if username:
                    result[username.lower()] = mapping
            
            return result
        except Exception as e:
            print(f"Error getting batch mappings: {e}")
            return {}

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
    
    def get_user_with_mapping(self, username: str) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
        """
        Получает данные пользователя и его X-UI маппинг одним запросом через aggregation.
        Оптимизирует работу с БД, уменьшая количество запросов.
        
        Args:
            username: Имя пользователя в Hysteria2
        
        Returns:
            Tuple (user_data, xui_mapping) или (None, None) если пользователь не найден
        """
        try:
            username_lower = username.lower()
            # Используем aggregation для объединения данных из двух коллекций
            pipeline = [
                {
                    "$match": {"_id": username_lower}
                },
                {
                    "$lookup": {
                        "from": "xui_user_mapping",
                        "localField": "_id",
                        "foreignField": "_id",
                        "as": "xui_mapping"
                    }
                },
                {
                    "$limit": 1
                }
            ]
            
            result = list(self.collection.aggregate(pipeline))
            
            if not result:
                return None, None
            
            user_data = result[0]
            # Убираем поле xui_mapping из user_data и возвращаем отдельно
            xui_mapping_list = user_data.pop("xui_mapping", [])
            xui_mapping = xui_mapping_list[0] if xui_mapping_list else None
            
            return user_data, xui_mapping
        except Exception as e:
            # При ошибке fallback к отдельным запросам
            user_data = self.get_user(username)
            xui_mapping = self.get_xui_mapping(username)
            return user_data, xui_mapping

try:
    db = Database()
except pymongo.errors.ConnectionFailure:
    db = None