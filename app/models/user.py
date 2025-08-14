from dataclasses import dataclass, field
from typing import Optional, List, Dict
from datetime import datetime


@dataclass
class UserData:
    user_id: int
    username: Optional[str]
    first_name: Optional[str]
    last_name: Optional[str]
    join_date: str
    last_activity: str
    total_queries: int = 0
    balance: float = 0.0
    query_history: List[Dict] = field(default_factory=list)

    def __post_init__(self):
        if self.query_history is None:
            self.query_history = []