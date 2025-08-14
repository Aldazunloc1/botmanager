import re
from typing import Tuple


class IMEIValidator:
    @staticmethod
    def validate_imei(imei: str) -> Tuple[bool, str]:
        """Validate IMEI format and checksum"""
        if not imei:
            return False, "IMEI no puede estar vacío"
        
        # Remove all non-digit characters
        clean_imei = re.sub(r'[^\d]', '', imei)
        
        if not clean_imei.isdigit():
            return False, "IMEI debe contener solo números"
        
        if len(clean_imei) < 8 or len(clean_imei) > 17:
            return False, "IMEI debe tener entre 8 y 17 dígitos"
        
        # Validate 15-digit IMEI with Luhn algorithm
        if len(clean_imei) == 15:
            if not IMEIValidator._luhn_check(clean_imei):
                return False, "IMEI no válido según algoritmo de verificación"
        
        return True, clean_imei

    @staticmethod
    def _luhn_check(imei: str) -> bool:
        """Apply Luhn algorithm to validate IMEI"""
        total = 0
        reverse_digits = imei[::-1]
        
        for i, digit in enumerate(reverse_digits):
            n = int(digit)
            if i % 2 == 1:
                n *= 2
                if n > 9:
                    n = n // 10 + n % 10
            total += n
        
        return total % 10 == 0