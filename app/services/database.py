import json
import logging
from pathlib import Path
from typing import Dict, Optional
from dataclasses import asdict
from datetime import datetime

from app.models.user import UserData

logger = logging.getLogger(__name__)


class UserDatabase:
    def __init__(self, db_path: str):
        self.db_path = Path(db_path)
        self.users: Dict[int, UserData] = {}
        self.load_users()

    def load_users(self):
        """Load users from JSON file"""
        if self.db_path.exists():
            try:
                with open(self.db_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    for user_id, user_data in data.items():
                        self.users[int(user_id)] = UserData(**user_data)
                logger.info(f"Loaded {len(self.users)} users from database")
            except Exception as e:
                logger.error(f"Error loading database: {e}")
                self.users = {}

    def save_users(self):
        """Save users to JSON file"""
        try:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            data = {str(user_id): asdict(user_data) for user_id, user_data in self.users.items()}
            with open(self.db_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Error saving database: {e}")

    def get_or_create_user(
        self, 
        user_id: int, 
        username: str = None, 
        first_name: str = None, 
        last_name: str = None
    ) -> UserData:
        """Get existing user or create new one"""
        if user_id not in self.users:
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self.users[user_id] = UserData(
                user_id=user_id,
                username=username,
                first_name=first_name,
                last_name=last_name,
                join_date=now,
                last_activity=now
            )
            self.save_users()
        else:
            # Update user info
            user = self.users[user_id]
            user.username = username
            user.first_name = first_name
            user.last_name = last_name
            user.last_activity = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        return self.users[user_id]

    def update_user_query(
        self, 
        user_id: int, 
        service_title: str, 
        price: float, 
        imei: str, 
        success: bool
    ):
        """Update user query history"""
        if user_id in self.users:
            user = self.users[user_id]
            user.total_queries += 1
            
            if success:
                user.balance -= price
            
            query_record = {
                "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "service": service_title,
                "price": price,
                "imei": imei[-4:],  # Only store last 4 digits
                "success": success
            }
            user.query_history.append(query_record)
            
            # Keep only last 50 queries
            if len(user.query_history) > 50:
                user.query_history = user.query_history[-50:]
                
            self.save_users()