import html
import re
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)


class ResponseFormatter:
    @staticmethod
    def format_imei_response(response_json: Dict[str, Any]) -> str:
        """Format IMEI API response for display"""
        try:
            service_name = response_json.get("service_name", "No disponible")
            imei = response_json.get("imei", "No disponible")
            status = response_json.get("status", "No disponible")
            credit = response_json.get("credit", "0.00")
            balance = response_json.get("balance_left", "0.00")

            result_raw = response_json.get("result", "")
            clean_result = ResponseFormatter._clean_html_content(result_raw)

            message = (
                f"📱 <b>Consulta IMEI</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"🔍 <b>Servicio:</b> {service_name}\n"
                f"📟 <b>IMEI:</b> <code>{imei}</code>\n"
                f"⚡ <b>Estado:</b> {status}\n"
                f"💰 <b>Crédito usado:</b> ${credit}\n"
                f"💳 <b>Saldo restante:</b> ${balance}\n"
            )

            if clean_result:
                message += f"\n📋 <b>Detalles:</b>\n<pre>{clean_result[:1500]}</pre>"
                if len(clean_result) > 1500:
                    message += "\n<i>... (resultado truncado)</i>"

            return message

        except Exception as e:
            logger.error(f"Error formatting response: {e}")
            return "❌ Error al formatear la respuesta del servidor"

    @staticmethod
    def _clean_html_content(html_content: str) -> str:
        """Clean HTML content for display"""
        if not html_content:
            return "No hay información disponible"

        decoded = html.unescape(str(html_content))
        
        # Replace common HTML entities and tags
        replacements = [
            ("\\u003Cbr\\u003E", "\n"),
            ("<br>", "\n"),
            ("<br/>", "\n"),
            ("&nbsp;", " "),
            ("&amp;", "&"),
            ("&lt;", "<"),
            ("&gt;", ">")
        ]
        
        for old, new in replacements:
            decoded = decoded.replace(old, new)
        
        # Remove HTML tags
        clean_text = re.sub(r'<[^>]*>', '', decoded)
        
        # Clean up lines
        lines = []
        for line in clean_text.split('\n'):
            clean_line = line.strip()
            if clean_line:
                lines.append(clean_line)
        
        return '\n'.join(lines)