from pydantic import BaseModel
from typing import Optional, Any, Dict


class WebhookUpdate(BaseModel):
    update_id: int
    message: Optional[Dict[str, Any]] = None
    edited_message: Optional[Dict[str, Any]] = None
    channel_post: Optional[Dict[str, Any]] = None
    edited_channel_post: Optional[Dict[str, Any]] = None
    inline_query: Optional[Dict[str, Any]] = None
    chosen_inline_result: Optional[Dict[str, Any]] = None
    callback_query: Optional[Dict[str, Any]] = None
    shipping_query: Optional[Dict[str, Any]] = None
    pre_checkout_query: Optional[Dict[str, Any]] = None