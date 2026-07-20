import pytest
from cryptography.fernet import Fernet

from src.platform_api.core.secret_cipher import (
    ApiKeyCipher,
    SecretCipherUnavailableError,
    SecretDecryptionError,
)


def test_api_key_cipher_round_trip_and_repr_are_safe() -> None:
    key = Fernet.generate_key().decode()
    cipher = ApiKeyCipher(key)

    encrypted = cipher.encrypt("provider-api-key")

    assert encrypted != "provider-api-key"
    assert cipher.decrypt(encrypted) == "provider-api-key"
    assert key not in repr(cipher)
    assert "provider-api-key" not in repr(cipher)


def test_api_key_cipher_reports_missing_or_invalid_master_key() -> None:
    missing = ApiKeyCipher(None)
    invalid = ApiKeyCipher("not-a-fernet-key")

    assert missing.ready is False
    assert invalid.ready is False
    with pytest.raises(SecretCipherUnavailableError):
        missing.encrypt("provider-api-key")
    with pytest.raises(SecretCipherUnavailableError):
        invalid.encrypt("provider-api-key")


def test_api_key_cipher_rejects_ciphertext_from_another_key() -> None:
    ciphertext = ApiKeyCipher(Fernet.generate_key().decode()).encrypt("provider-api-key")
    other_cipher = ApiKeyCipher(Fernet.generate_key().decode())

    with pytest.raises(SecretDecryptionError):
        other_cipher.decrypt(ciphertext)
