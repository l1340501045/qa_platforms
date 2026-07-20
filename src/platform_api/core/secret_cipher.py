"""模型 API Key 的应用层加密封装。"""

from cryptography.fernet import Fernet, InvalidToken
from pydantic import SecretStr


class SecretCipherUnavailableError(RuntimeError):
    """服务器总加密密钥缺失或格式错误。"""


class SecretDecryptionError(RuntimeError):
    """密文无法由当前服务器总密钥解密。"""


class ApiKeyCipher:
    """仅暴露安全的 Key 加解密操作，不保留可打印的明文总密钥。"""

    def __init__(self, master_key: SecretStr | str | None):
        raw_key = master_key.get_secret_value() if isinstance(master_key, SecretStr) else master_key
        self._fernet: Fernet | None = None
        if raw_key:
            try:
                self._fernet = Fernet(raw_key.encode("utf-8"))
            except (TypeError, ValueError):
                self._fernet = None

    @property
    def ready(self) -> bool:
        return self._fernet is not None

    def encrypt(self, api_key: str) -> str:
        if self._fernet is None:
            raise SecretCipherUnavailableError("服务器未配置有效的模型配置总加密密钥")
        return self._fernet.encrypt(api_key.encode("utf-8")).decode("utf-8")

    def decrypt(self, ciphertext: str) -> str:
        if self._fernet is None:
            raise SecretCipherUnavailableError("服务器未配置有效的模型配置总加密密钥")
        try:
            return self._fernet.decrypt(ciphertext.encode("utf-8")).decode("utf-8")
        except (InvalidToken, UnicodeDecodeError, ValueError) as exc:
            raise SecretDecryptionError("模型 API Key 无法解密，请重新填写") from exc

    def __repr__(self) -> str:
        return f"ApiKeyCipher(ready={self.ready})"
