# PURPOSE: тесты AES-CBC для API роутера по известным векторам.
import unittest

from homebot.infrastructure.router_crypto import aes_cbc_decrypt, aes_cbc_encrypt, encrypt_block


class RouterCryptoTest(unittest.TestCase):
    def test_aes128_block_vector(self):
        key = bytes(range(16))
        plain = bytes.fromhex("00112233445566778899aabbccddeeff")
        expected = bytes.fromhex("69c4e0d86a7b0430d8cdb78070b4c55a")
        self.assertEqual(encrypt_block(plain, key), expected)

    def test_cbc_roundtrip(self):
        key = b"jiuzhou99jiuzhou"
        iv = b"jiuzhou99jiuzhou"
        payload = '{"loginUsername":"admin","loginPasswd":"secret"}'
        encrypted = aes_cbc_encrypt(payload, key, iv)
        self.assertEqual(aes_cbc_decrypt(encrypted, key, iv), payload)


if __name__ == "__main__":
    unittest.main()
